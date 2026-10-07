# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""SeamCompositeLaminate — effective combined layup of a seam joint.

Combines the master and attachment laminates of an overlap seam into a
single laminate representing the joint's effective stiffness over the
seam region.  This is a *derived analysis object*: it does not replace
either side's laminate for FEM export, BOM, or manufacturing — those
stay owned by the side shells.  Consumers that need the joint's
effective stiffness reference this laminate explicitly.

Design decisions (see docs/seam_composite_laminate.md and
docs/adr/0001-seam-angle-analysis-symmetric-transfers.md):

- Ply angles at the seam come from two *solved* transfer rosettes
  (master → seam and attachment → seam), never from copied rosette
  angles — either seam edge may be remote from its part's rosette, and
  drape distortion between rosette and edge makes a copied angle wrong.
- The master→seam transfer rosette seeds the seam shell's drape; the
  attachment→seam rosette is analysis-only.
- ``Symmetry`` is pinned to ``Assymmetric``: the combined stack is a
  literal record of the physical layup; mirroring would fabricate plies.
- Any violated wiring invariant raises loudly — a silent wrong stack is
  the one unacceptable outcome.
"""

import FreeCAD
from dataclasses import replace

from .. import (
    COMPOSITE_LAMINATE_TOOL_ICON,
    is_comp_type,
)
from ..objects import (
    CompositeLaminate,
    SymmetryType,
)
from .CompositeLaminate import (
    CompositeLaminateFP,
    ViewProviderCompositeLaminate,
)
from .CompositeShell import is_composite_shell
from .Laminate import LaminateFP, get_model_layers, is_isotropic_laminate
from .Rosette import RosetteFP
from .TransferRosette import TransferRosetteFP
from ..util.geometry_util import shares_boundary_edge


def _bbox_gap(a, b) -> float:
    """The separation of two bounding boxes, 0 when they overlap."""
    dx = max(b.XMin - a.XMax, a.XMin - b.XMax, 0.0)
    dy = max(b.YMin - a.YMax, a.YMin - b.YMax, 0.0)
    dz = max(b.ZMin - a.ZMax, a.ZMin - b.ZMax, 0.0)
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def _closest_approach(side_shape, seam_shape) -> float:
    """A usable closest-approach figure between two shells, cheaply.

    ``distToShape`` between two B-spline shells runs surface-to-surface
    extrema — measured at 93 s on the fuselage's half-ring, a diagnostic
    costing two orders of magnitude more than the work it describes (and
    it runs on the failure path, which the fingerprint gate re-runs for
    every wiring write until the joint passes).  The message needs zero
    versus nonzero, so the figure is bounded instead:

    * separated bounding boxes settle it outright — the boxes bound the
      shapes, so the box gap is a positive lower bound;
    * overlapping boxes reduce to edge-pair extrema over candidates whose
      own boxes could still beat the running best.  A seat-to-seam gap is
      realised on boundary curves, and curve/curve extrema skip the
      surface work entirely.

    The edge-pair figure is an upper bound when the true closest approach
    lies interior to faces; on the joint geometries this serves (seats
    touch along their boundary rows) it is the actual gap.
    """
    box_gap = _bbox_gap(side_shape.BoundBox, seam_shape.BoundBox)
    if box_gap > 0.0:
        return box_gap
    best = float("inf")
    for edge_a in side_shape.Edges:
        box_a = edge_a.BoundBox
        for edge_b in seam_shape.Edges:
            if _bbox_gap(box_a, edge_b.BoundBox) > best:
                continue
            best = min(best, edge_a.distToShape(edge_b)[0])
            if best == 0.0:
                return best
    return best


def _edge_mismatch_detail(side, side_shape, seam_shape) -> str:
    """Describe why the shared-edge check failed, for the raised message.

    A loud failure should say *which* geometry it looked at: the side's
    support object (the panel's pointer moves along a chained support, so
    which remainder it names is the first thing to establish), the face
    counts and areas on both sides, and the closest approach between them.
    A shape distance at zero with no shared edge means the pieces meet but
    their curves do not coincide — a different repair from pieces that are
    apart.
    """
    support = getattr(side, "Support", None)
    try:
        gap = _closest_approach(side_shape, seam_shape)
    except Exception as exc:
        gap = f"unmeasurable ({exc})"
    return (
        f" [support={getattr(support, 'Name', support)}, "
        f"faces={len(side_shape.Faces)}, "
        f"area={side_shape.Area:.4g}, "
        f"seam faces={len(seam_shape.Faces)}, "
        f"seam area={seam_shape.Area:.4g}, "
        f"gap={gap}]"
    )


def _master_shape(obj):
    """The master-side geometry to judge this joint's seam against.

    The joint's own support remainder when the flow recorded one, else the
    Master shell's live support.  ``Master`` is the whole panel, and the
    panel supports several joints: its Support pointer moves to the deepest
    remainder as stiffeners are wired, and is put back to the root while an
    earlier stiffener re-wires, so it does not describe *this* joint's
    panel-side surface.  The remainder does — the seat was cut from it — and
    its boundary is therefore the seam's boundary.
    """
    support = getattr(obj, "MasterSupport", None)
    if support is not None:
        return support.Shape
    return TransferRosetteFP._shape_of(getattr(obj, "Master"))


class CombinationModel:
    """Names of the supported seam combination models.

    Only the stack models are implemented; the others are reserved and
    raise loudly when selected.
    """

    StackMasterOverAttachment = "StackMasterOverAttachment"
    StackAttachmentOverMaster = "StackAttachmentOverMaster"
    Interleaved = "Interleaved"
    Taper = "Taper"

    ALL = [
        StackMasterOverAttachment,
        StackAttachmentOverMaster,
        Interleaved,
        Taper,
    ]


class SeamCompositeLaminateFP(CompositeLaminateFP):
    """Laminate representing the combined layup of a seam joint.

    Layers are derived from the master and attachment laminates, rotated
    into the seam frame by the two solved transfer rosettes, and
    combined per ``CombinationModel``.  The inherited ``Layers`` list is
    derived (read-only); ``Symmetry`` is pinned (see module docstring).
    """

    def __init__(self, obj):
        self._initializing = True
        try:
            super().__init__(obj, laminae=[])
            # CompositeLaminateFP.__init__ already added the composite
            # props (ResinMaterial etc.).

            obj.addProperty(
                "App::PropertyLinkGlobal",
                "Master",
                "References",
                "Master composite shell (stays whole in seam extraction)",
            )
            obj.addProperty(
                # The panel-side surface *this joint* owns: the support
                # remainder the stiffener's seat was cut from.  The panel's
                # own Support pointer chains to the deepest link in the
                # chain — and is restored to the root while an earlier
                # stiffener re-wires — so reading it can land on a surface
                # this joint does not touch.  Unset where the seat consumed
                # the whole support; there the live support is right.
                "App::PropertyLinkHidden",
                "MasterSupport",
                "References",
                "Master-side support this joint was wired against",
            )
            obj.addProperty(
                "App::PropertyLinkGlobal",
                "Attachment",
                "References",
                "Attachment composite shell (trimmed by seam extraction)",
            )
            obj.addProperty(
                # Back-reference, not a compute dependency: the SCL derives
                # its stack from Master and Attachment; the region shell
                # carries the SCL as its Laminate, so a visible link here
                # made region→SCL→region a dependency cycle that tripped
                # DAGView (known-issue #9).  Hidden links read normally;
                # they only stay out of the touch/DAG propagation.
                "App::PropertyLinkHidden",
                "SeamRegion",
                "References",
                "Seam shell carrying the overlap surface",
            )
            obj.addProperty(
                # Solved-value references, not dependencies: the SCL pulls
                # the angles in execute (resolve()) and its freshness is
                # fingerprint-driven.  Visible links here made
                # shell→SCL→transfer→shell a dependency cycle that tripped
                # DAGView (known-issue #9) — the shell legitimately links
                # both the SCL (its Laminate) and the transfer (its
                # Rosette).
                "App::PropertyLinkHidden",
                "MasterTransfer",
                "References",
                "Solved transfer rosette master → seam (seeds seam drape)",
            )
            obj.addProperty(
                "App::PropertyLinkHidden",
                "AttachmentTransfer",
                "References",
                "Solved transfer rosette attachment → seam (analysis only)",
            )

            obj.addProperty(
                "App::PropertyEnumeration",
                "CombinationModel",
                "Composition",
                "How the two sides' stacks combine at the seam",
            )
            obj.CombinationModel = CombinationModel.ALL
            obj.CombinationModel = CombinationModel.StackMasterOverAttachment

            obj.addProperty(
                "App::PropertyAngle",
                "EffectiveOffsetAngle",
                "Analysis",
                "Relative rotation between the two fibre frames at the seam",
            )
            obj.setPropertyStatus("EffectiveOffsetAngle", "ReadOnly")

            obj.addProperty(
                "App::PropertyMap",
                "SideAngleReport",
                "Analysis",
                "Per-side seam angle analysis (inspection output)",
            )
            obj.setPropertyStatus("SideAngleReport", "ReadOnly")

            # Derived presentation (OQ-6): never declared on the combined
            # laminate — it equals all sides declared, written by execute
            # and pinned read-only.
            obj.setPropertyStatus("IsotropicEquivalent", "ReadOnly")
            obj.setPropertyStatus("ApproximateIsotropicEquivalent", "ReadOnly")

            # The combined stack is a literal record of the physical
            # layup.  The inherited default (Odd) mirrors the stack and
            # would silently fabricate a copy of every ply.
            obj.Symmetry = SymmetryType.Assymmetric.name
            obj.setPropertyStatus("Symmetry", "ReadOnly")
            obj.setPropertyStatus("Symmetry", "Hidden")

            # Layers are composed, not user-selected.
            obj.setPropertyStatus("Layers", "ReadOnly")

            # Attach ViewProvider so it persists in the saved document.
            vobj = obj.ViewObject
            if vobj is not None:
                vobj.Proxy = ViewProviderSeamCompositeLaminate(vobj)
        finally:
            self._initializing = False

    # ── validation ────────────────────────────────────────────────

    @staticmethod
    def _is_rosette(obj) -> bool:
        # Check the proxy type directly: rosette features are created as
        # Part::FeaturePython, so the "App::FeaturePython" TypeId used by
        # is_comp_type-style checks does not match them.
        proxy_type = getattr(getattr(obj, "Proxy", None), "Type", None)
        return proxy_type in ("Composite::Rosette", "Composite::TransferRosette")

    def _side_is_isotropic(self, obj, side_name) -> bool:
        """Whether the side's own laminate declares isotropic presentation."""
        side = getattr(obj, side_name, None)
        return is_isotropic_laminate(getattr(side, "Laminate", None))

    def _input_fingerprint(self, obj) -> str:
        """Hash everything the derived stack depends on.

        Covers the live support geometry of the two sides and the seam
        region, their laminates, the solved transfer angles, the
        combination model and this laminate's own stack model — everything
        ``execute`` reads.  A change in any of them re-derives the stack;
        nothing else does.  The stack model belongs here: setting it
        changes the derived stack but nothing else (a shape-only
        fingerprint skipped the re-derivation, leaving the combined
        laminate fully layered under a smeared model).

        Content stamps (not ``Shape.hashCode()`` and not
        ``shape_fingerprint``, whose traversal-order dependence makes it
        miss on rebuilt compounds) are used: an unstable stamp costs a
        redundant re-derivation, never a wrong skip.
        """
        import hashlib

        from ..util.geometry_util import shape_stamp

        def shape_part(holder):
            support = getattr(holder, "Support", None)
            shape = getattr(support, "Shape", None)
            placement = str(getattr(support, "Placement", ""))
            if shape is None:
                return "no-shape"
            try:
                return f"{shape_stamp(shape)}|{placement}"
            except Exception:
                return "shape-error"

        parts = []
        try:
            parts.append(shape_stamp(_master_shape(obj)))
        except Exception:
            parts.append("master-shape-error")
        for name in ("Master", "Attachment"):
            shell = getattr(obj, name, None)
            parts.append(getattr(shell, "Name", "None"))
            parts.append(shape_part(shell))
            parts.append(getattr(getattr(shell, "Laminate", None), "Name", "None"))
            # The derived stack follows the sides' rosette angles: rotating
            # a side rosette re-solves its transfer and must re-derive here.
            parts.append(str(getattr(getattr(shell, "Rosette", None), "Angle", "None")))
        seam = getattr(obj, "SeamRegion", None)
        parts.append(getattr(seam, "Name", "None"))
        parts.append(shape_part(seam))
        for name in ("MasterTransfer", "AttachmentTransfer"):
            parts.append(str(getattr(getattr(obj, name, None), "Angle", "None")))
        parts.append(str(getattr(obj, "CombinationModel", "None")))
        parts.append(str(getattr(obj, "StackModelType", "None")))

        digest = hashlib.sha256()
        for part in parts:
            digest.update(str(part).encode())
        return digest.hexdigest()

    def _validate_wiring(self, obj) -> None:
        """Raise on every violated structural invariant (§3.2 of the PRD)."""
        for name in ("Master", "Attachment"):
            side = getattr(obj, name, None)
            if side is None or not is_composite_shell(side):
                raise ValueError(
                    f"{type(self).__name__}: {name} must be a "
                    f"CompositeShell, got {side}"
                )
        for name, side_name in (
            ("MasterTransfer", "Master"),
            ("AttachmentTransfer", "Attachment"),
        ):
            rosette = getattr(obj, name, None)
            if self._side_is_isotropic(obj, side_name):
                # D8: a QI side is orientation-free — its transfer
                # rosette may be omitted; a linked non-rosette still
                # raises (wiring error, not an omission).
                if rosette is not None and not self._is_rosette(rosette):
                    raise ValueError(
                        f"{type(self).__name__}: {name} must be a solved "
                        f"transfer rosette, got {rosette}"
                    )
                continue
            if not self._is_rosette(rosette):
                raise ValueError(
                    f"{type(self).__name__}: {name} must be a solved "
                    f"transfer rosette, got {rosette}"
                )
        seam = getattr(obj, "SeamRegion", None)
        if seam is None or not is_composite_shell(seam):
            raise ValueError(
                f"{type(self).__name__}: SeamRegion must be the seam "
                f"shell, got {seam}"
            )
        for name in ("Master", "Attachment"):
            side_laminate = getattr(obj, name).Laminate
            layers = getattr(side_laminate, "Layers", None) if (
                side_laminate is not None
            ) else None
            if not layers:
                raise ValueError(
                    f"{type(self).__name__}: {name} has no laminate "
                    f"layers to combine"
                )
        # Shared-edge partnership, evaluated on live support geometry
        # (the shell's own Shape is a stale snapshot).  The same
        # geometric-identity rule applies as in TransferRosette: the
        # seam region is part of the attachment surface, and the
        # master-side boundary is the master–attachment intersection.
        #
        # Tested by comparing boundary edges directly rather than by
        # sectioning the shells: the contract is literally "share a
        # boundary edge", and the section was the flow's most expensive
        # operation (measured at 8 section builds per ring, ~3 s of a
        # ~15 s ring).
        seam_shape = TransferRosetteFP._shape_of(seam)
        for name in ("Master", "Attachment"):
            side = getattr(obj, name)
            side_shape = (
                _master_shape(obj)
                if name == "Master"
                else TransferRosetteFP._shape_of(side)
            )
            if not shares_boundary_edge(side_shape, seam_shape):
                raise ValueError(
                    f"{type(self).__name__}: {name} shares no boundary "
                    f"edge with the seam region"
                    f"{_edge_mismatch_detail(side, side_shape, seam_shape)}"
                )

    # ── angle analysis ────────────────────────────────────────────

    def _side_angle(self, obj, side_name: str, transfer_name: str):
        """Solved fibre angle of one side at the seam; None when QI."""
        if self._side_is_isotropic(obj, side_name):
            # D8/OQ-5: a QI side contributes no solved angle.
            return None
        transfer = getattr(obj, transfer_name, None)
        if transfer is None:
            raise ValueError(
                f"{type(self).__name__}: {side_name} has no solved "
                f"transfer angle"
            )
        return transfer.Angle.Value

    def _seam_angles(self, obj) -> dict:
        """Solved fibre-frame angles of both sides at the seam.

        QI sides report None (orientation-free); the effective offset is
        only defined when both sides are draped.
        """
        master_angle = self._side_angle(obj, "Master", "MasterTransfer")
        attachment_angle = self._side_angle(
            obj, "Attachment", "AttachmentTransfer"
        )
        effective_offset = (
            attachment_angle - master_angle
            if master_angle is not None and attachment_angle is not None
            else None
        )
        return {
            "master": master_angle,
            "attachment": attachment_angle,
            "effective_offset": effective_offset,
        }

    @staticmethod
    def _format_angle(angle) -> str:
        return "n/a" if angle is None else f"{angle:.6g}"

    def _update_angle_outputs(self, obj, angles: dict) -> None:
        if angles["effective_offset"] is not None:
            # Meaningful only when both sides are draped (D8).
            obj.EffectiveOffsetAngle = angles["effective_offset"]
        obj.SideAngleReport = {
            "master_angle_at_seam": self._format_angle(angles["master"]),
            "attachment_angle_at_seam": self._format_angle(
                angles["attachment"]
            ),
            "effective_offset": self._format_angle(
                angles["effective_offset"]
            ),
            "approximation": (
                "seam-shell drape deviation treated as zero (phase 1)"
            ),
        }

    # ── combination ───────────────────────────────────────────────

    def _side_layers(self, obj, side_name: str, seam_angle: float) -> list:
        """Side's model laminae, rotated into the seam frame.

        One rigid rotation per side: ply nominal orientation relative to
        that side's rosette frame, plus the side's solved transfer angle
        at the seam.  Thickness and material are untouched.  A QI side
        is orientation-free (D8/OQ-5): its plies enter the record at
        their nominal angles with a fixed rotation of 0.
        """
        side = getattr(obj, side_name)
        model_layers = get_model_layers(side.Laminate)
        if not model_layers:
            raise ValueError(
                f"{type(self).__name__}: {side_name} laminate model is "
                f"empty"
            )
        if self._side_is_isotropic(obj, side_name):
            return list(model_layers)
        return [
            replace(layer, orientation=layer.orientation + seam_angle)
            for layer in model_layers
        ]

    def _combined_layers(self, obj) -> list:
        angles = self._seam_angles(obj)
        master_layers = self._side_layers(obj, "Master", angles["master"])
        attachment_layers = self._side_layers(
            obj, "Attachment", angles["attachment"]
        )

        model = obj.CombinationModel
        if model == CombinationModel.StackMasterOverAttachment:
            return attachment_layers + master_layers
        if model == CombinationModel.StackAttachmentOverMaster:
            return master_layers + attachment_layers
        raise NotImplementedError(
            f"{type(self).__name__}: combination model '{model}' is "
            f"reserved but not implemented"
        )

    # ── laminate base integration ─────────────────────────────────

    def get_model(self, obj) -> CompositeLaminate:
        self._validate_wiring(obj)
        model_layers = self._combined_layers(obj)
        # Derived presentation (OQ-6): the combined stack cannot be more
        # isotropic than its sides — all sides declared, never declared
        # here.  Either approximate side makes the combination
        # approximate; the combined stack is re-validated by the §4.2
        # balance check through the model's QI branch when derived-true.
        sides_isotropic = all(
            self._side_is_isotropic(obj, name)
            for name in ("Master", "Attachment")
        )
        sides_approximate = any(
            self._side_is_approximate(obj, name)
            for name in ("Master", "Attachment")
        )
        obj.IsotropicEquivalent = sides_isotropic
        obj.ApproximateIsotropicEquivalent = (
            sides_isotropic and sides_approximate
        )
        if volume_fraction := obj.FibreVolumeFraction:
            volume_fraction *= 0.01
        else:
            volume_fraction = 0
        return CompositeLaminate(
            # Pinned: the combined stack is a literal record; never
            # mirror it (the inherited Odd default would fabricate
            # plies).
            symmetry=SymmetryType.Assymmetric,
            layers=model_layers,
            volume_fraction_fibre=volume_fraction,  # noqa
            material_matrix=obj.ResinMaterial,
            isotropic_equivalent=sides_isotropic,
            approximate_isotropic_equivalent=(
                sides_isotropic and sides_approximate
            ),
            # The combined record is an intentionally asymmetric literal
            # concat (master plies + attachment plies) — the B gate does
            # not apply to the derived QI presentation (D8).
            qi_symmetric=False,
        )

    def _side_is_approximate(self, obj, side_name) -> bool:
        laminate = getattr(getattr(obj, side_name, None), "Laminate", None)
        return bool(
            getattr(laminate, "ApproximateIsotropicEquivalent", False)
        )

    def execute(self, obj):
        # Defensive re-pin: ReadOnly only restricts the GUI editor, so a
        # Python writer could set Symmetry = Odd and mirror the stack.
        obj.Symmetry = SymmetryType.Assymmetric.name
        try:
            # Skip when nothing the stack depends on changed.  Wiring writes
            # several properties on this object, and each write re-executes
            # it; without the gate the validation's sections (panel against
            # seam region, twice per execute) run several times per joint —
            # measured at 8 section builds per ring, more than half the
            # ring's build time.  Fingerprint-driven freshness mirrors
            # SeamExtraction._sync_virtual_inputs.
            current = self._input_fingerprint(obj)
            if current == getattr(self, "_last_input_fingerprint", None):
                self.last_error = None
                return
            self._validate_wiring(obj)
            # Pull-based freshness: the transfer rosettes' angles are
            # frozen at solve time; re-solve them when their inputs
            # (shapes, rosette angles) changed since (fingerprint-guarded
            # inside resolve()).  A QI side may have no transfer at all
            # (D8) — nothing to resolve.
            for name in ("MasterTransfer", "AttachmentTransfer"):
                transfer = getattr(obj, name)
                if transfer is None:
                    continue
                resolve = getattr(transfer.Proxy, "resolve", None)
                if resolve is not None:
                    # Plain rosette stand-ins (e.g. hand-wired tests) have
                    # no solve machinery; their Angle is taken as-is.
                    resolve(transfer)
            angles = self._seam_angles(obj)
            self._update_angle_outputs(obj, angles)
            # LaminateFP.execute, deliberately NOT
            # CompositeLaminateFP.execute: its ResinMaterial requirement
            # does not apply here — the combined plies carry their
            # resolved materials from the side laminates, and
            # ResinMaterial is only a smearing fallback for fabric plies.
            LaminateFP.execute(self, obj)
            # Recorded only after the body succeeds: a failing execute must
            # re-run (and re-raise) on the next recompute rather than be
            # skipped as "unchanged", which would silently clear the error
            # the loud-failure contract requires it to keep surfacing.
            self._last_input_fingerprint = current
        except Exception as exc:
            # Loud-failure contract: record the reason, leave previous
            # outputs untouched, and surface the error so the feature
            # shows as in error — never a silently wrong stack.
            self.last_error = str(exc)
            raise
        self.last_error = None

    def onChanged(self, fp, prop):
        if getattr(self, "_initializing", False):
            return
        # doc.recompute() does NOT re-execute an object touched by a
        # plain value change — only dependency-driven changes propagate.
        # Every reference or model change must therefore recompute the
        # object directly, but only once fully wired: a mid-setup
        # execution would run against half-set references and poison
        # the feature state.
        #
        # A document mid-restore is exactly that state: the references
        # arrive before the joint's own properties, so recomputing here
        # executes against an object that cannot answer for itself yet
        # (and the saved result is already correct — nothing changed).
        if fp.Document.Restoring:
            return
        refs = (
            "Master",
            "Attachment",
            # SeamRegion/MasterTransfer/AttachmentTransfer are hidden
            # (no-dependency) links: assigning them doesn't touch the SCL,
            # so freshness is handled inside execute's pull-based
            # resolve() instead.
            "SeamRegion",
            "MasterTransfer",
            "AttachmentTransfer",
        )
        if prop not in refs:
            return
        if not all(getattr(fp, name, None) for name in refs):
            return
        fp.recompute()


class ViewProviderSeamCompositeLaminate(ViewProviderCompositeLaminate):
    def getIcon(self):
        return COMPOSITE_LAMINATE_TOOL_ICON
