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
from .Laminate import LaminateFP, get_model_layers
from .Rosette import RosetteFP
from .TransferRosette import TransferRosetteFP


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

    def _validate_wiring(self, obj) -> None:
        """Raise on every violated structural invariant (§3.2 of the PRD)."""
        for name in ("Master", "Attachment"):
            side = getattr(obj, name, None)
            if side is None or not is_composite_shell(side):
                raise ValueError(
                    f"{type(self).__name__}: {name} must be a "
                    f"CompositeShell, got {side}"
                )
        for name in ("MasterTransfer", "AttachmentTransfer"):
            rosette = getattr(obj, name, None)
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
        seam_shape = TransferRosetteFP._shape_of(seam)
        for name in ("Master", "Attachment"):
            edge = TransferRosetteFP._shared_edge(
                TransferRosetteFP._shape_of(getattr(obj, name)), seam_shape
            )
            if edge is None:
                raise ValueError(
                    f"{type(self).__name__}: {name} shares no boundary "
                    f"edge with the seam region"
                )

    # ── angle analysis ────────────────────────────────────────────

    def _seam_angles(self, obj) -> dict:
        """Solved fibre-frame angles of both sides at the seam."""
        master_angle = obj.MasterTransfer.Angle.Value
        attachment_angle = obj.AttachmentTransfer.Angle.Value
        return {
            "master": master_angle,
            "attachment": attachment_angle,
            "effective_offset": attachment_angle - master_angle,
        }

    def _update_angle_outputs(self, obj, angles: dict) -> None:
        obj.EffectiveOffsetAngle = angles["effective_offset"]
        obj.SideAngleReport = {
            "master_angle_at_seam": f"{angles['master']:.6g}",
            "attachment_angle_at_seam": f"{angles['attachment']:.6g}",
            "effective_offset": f"{angles['effective_offset']:.6g}",
            "approximation": (
                "seam-shell drape deviation treated as zero (phase 1)"
            ),
        }

    # ── combination ───────────────────────────────────────────────

    def _side_layers(self, obj, side_name: str, seam_angle: float) -> list:
        """Side's model laminae, rotated into the seam frame.

        One rigid rotation per side: ply nominal orientation relative to
        that side's rosette frame, plus the side's solved transfer angle
        at the seam.  Thickness and material are untouched.
        """
        side = getattr(obj, side_name)
        model_layers = get_model_layers(side.Laminate)
        if not model_layers:
            raise ValueError(
                f"{type(self).__name__}: {side_name} laminate model is "
                f"empty"
            )
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
        )

    def execute(self, obj):
        # Defensive re-pin: ReadOnly only restricts the GUI editor, so a
        # Python writer could set Symmetry = Odd and mirror the stack.
        obj.Symmetry = SymmetryType.Assymmetric.name
        try:
            self._validate_wiring(obj)
            # Pull-based freshness: the transfer rosettes' angles are
            # frozen at solve time; re-solve them when their inputs
            # (shapes, rosette angles) changed since (fingerprint-guarded
            # inside resolve()).
            for name in ("MasterTransfer", "AttachmentTransfer"):
                transfer = getattr(obj, name)
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
