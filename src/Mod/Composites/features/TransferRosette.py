# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""TransferRosette — warp-transfer rosette on an attachment shell.

A :class:`TransferRosetteFP` is a :class:`Rosette` that lives on the
**attachment** shell (``attachment_shell.Rosette = transfer_rosette``). Its
``Angle`` is solved so the attachment's frame makes the same signed angle
with the shared boundary edge as the master shell's warp, at sampled points
along that edge. The solved angle is written back into the inherited
``Angle`` property.

The solve is a phase-1 frame solve: the rosette frame rotates exactly 1:1
with ``Angle`` and the combined-laminate model treats drape deviation as
zero, so the residual is exact-linear in the angle — the master's warp is
measured once and the frame stepped analytically (no per-iteration re-drape
of the attachment). The solve is driven from :meth:`onChanged` (not
:meth:`execute`) for the defining references, guarded by a ``_solving`` flag
so the solve's own ``Angle`` writes do not recurse.
"""

import math
from typing import List

import FreeCAD
import Part

from .. import (
    TRANSFER_ROSETTE_TOOL_ICON,
    is_comp_type,
)
from ..tools.rosette_solver import (
    RosetteSolveError,
    wrap_angle,
)
from .Command import BaseCommand
from .CompositeShell import is_composite_shell
from .Rosette import (
    RosetteFP,
    ViewProviderRosette,
)

# Number of sample points along the shared boundary edge.
_EDGE_SAMPLES = 8

# Warp-continuity convergence tolerance (radians) — ~0.057 degrees.
_ANGLE_TOL_RAD = 1e-3

_HALF_PI = math.pi / 2.0


debug = False


def _debug(message):
    """Emit a solve trace when :data:`debug` is enabled."""
    if debug:
        FreeCAD.Console.PrintMessage(message + "\n")


def is_transfer_rosette(obj) -> bool:
    """Return True if *obj* is a TransferRosette feature."""
    return is_comp_type(obj, "App::FeaturePython", "Composite::TransferRosette")


class TransferRosetteFP(RosetteFP):
    """Rosette whose Angle is solved to match a master shell's warp.

    The rosette is attached to the **attachment** ``CompositeShell`` (its
    ``Angle`` re-seeds that shell's drape). The ``MasterShell`` and
    ``AttachmentShell`` references drive an iterative solve: the attachment
    rosette angle is rotated until the signed mean of
    ``(phi_attachment - phi_master)`` along the shared boundary edge is zero,
    where ``phi`` is the signed angle from the edge tangent to the warp about
    the face normal.
    """

    Type = "Composite::TransferRosette"

    def __init__(self, obj, support=None, master_shell=None, attachment_shell=None):
        # Suppress any solve while the defining references are being set up.
        # Set before super().__init__ (which may trigger onChanged).
        self._solving = True
        super().__init__(obj, support)
        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="MasterShell",
            group="References",
            doc="Master composite shell (already solved)",
        ).MasterShell = master_shell
        obj.addProperty(
            type="App::PropertyLinkGlobal",
            name="AttachmentShell",
            group="References",
            doc="Attachment composite shell whose rosette this is",
        ).AttachmentShell = attachment_shell
        self._solving = False
        if master_shell is not None and attachment_shell is not None:
            # The property-set onChanged calls above were suppressed by the
            # _solving guard, so the initial wiring and angle solve never
            # ran. Run them now, exactly as the deferred onChanged would.
            self._ensure_wired(obj)
            self._solve(obj)
            self._last_solve_fingerprint = self._solve_inputs_fingerprint(obj)
            obj.recompute()

    def execute(self, fp):
        # Place the LCS from Support + Angle only; the iterative solve is
        # driven from onChanged so it never recurses into execute().
        super().execute(fp)

    def resolve(self, fp) -> None:
        """Re-solve when the defining inputs changed (pull-based freshness).

        The constructor solve freezes the angle at creation time; without
        this, downstream changes (a moved support, a re-angled rosette on
        the master shell) leave the transfer angle stale.  Consumers that
        need a current angle (SeamCompositeLaminate) call resolve() before
        reading it; the fingerprint keeps repeat recomputes cheap.
        """
        fingerprint = self._solve_inputs_fingerprint(fp)
        if fingerprint == getattr(self, "_last_solve_fingerprint", None):
            return
        self._last_solve_fingerprint = fingerprint
        self._solving = True
        try:
            self._ensure_wired(fp)
            self._solve(fp)
        finally:
            self._solving = False

    def _solve_inputs_fingerprint(self, fp) -> str:
        """Hash everything the solved angle depends on.

        The attachment shell's Rosette is this transfer itself, so its
        Angle must NOT enter the fingerprint: the solve writes its own
        Angle, and a self-referential fingerprint would re-trigger the
        solve on every resolve — a re-drape storm.
        """
        import hashlib

        from ..util.geometry_util import shape_fingerprint

        parts = []
        for shell in (getattr(fp, "MasterShell", None),
                      getattr(fp, "AttachmentShell", None)):
            if shell is None:
                parts.append("None")
                continue
            try:
                parts.append(shape_fingerprint(self._shape_of(shell)))
            except Exception:
                parts.append("shape-error")
            rosette = getattr(shell, "Rosette", None)
            if rosette is not fp:
                parts.append(str(getattr(rosette, "Angle", 0.0)))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    def onChanged(self, fp, prop):
        if getattr(self, "_solving", False):
            return
        # Don't run the iterative solve during document restore (see
        # AlignFibreRosette for rationale).
        if fp.Document.Restoring:
            return
        match prop:
            case "Support" | "MasterShell" | "AttachmentShell":
                if fp.MasterShell and fp.AttachmentShell:
                    self._solving = True
                    try:
                        self._ensure_wired(fp)
                        self._solve(fp)
                    finally:
                        self._solving = False
                    fp.recompute()
                else:
                    fp.recompute()
            case "Angle":
                fp.recompute()

    def _ensure_wired(self, fp) -> None:
        """Make the attachment shell use this rosette as its orientation ref.

        Required when the feature is created through the GUI command (the
        attachment shell's ``Rosette`` still points at its old rosette). The
        assignment is a no-op when already wired, which avoids a re-entrant
        CompositeShell recompute on every solve iteration.
        """
        attachment = fp.AttachmentShell
        if getattr(attachment, "Rosette", None) is not fp:
            attachment.Rosette = fp

    def _solve(self, fp) -> None:
        """Solve the attachment rosette Angle for warp continuity.

        Phase-1 frame solve: the rosette frame rotates exactly with
        ``Angle`` and the laminates treat drape deviation as zero (the
        approximation stated in the combined-laminate report), so the
        warp-continuity residual is exact-linear in the angle — only the
        master's drape is read, and every measurement is free of
        attachment re-draping.  The slope (including its sign, which
        depends on whether the attachment face's normal agrees with the
        master's) is measured with two free probes, and the step is
        wrapped into the fabric's principal period rather than clamped.
        The old per-iteration re-drape was both wasteful (a full drape
        per candidate angle) and self-defeating: boundary-snapped
        lattice rows quantise the residual into steps no root-finder
        can meet.
        """
        master = fp.MasterShell
        attachment = fp.AttachmentShell
        # The two shells must share a topological boundary edge. If they don't
        # (e.g. a glued assembly with no common edge), this is a misuse of
        # the feature — raise a clear error rather than silently solving
        # against a zero residual.
        edge = self._shared_edge(
            self._shape_of(master), self._shape_of(attachment)
        )
        if edge is None:
            raise ValueError(
                "TransferRosette: master and attachment shells share no "
                "boundary edge — cannot transfer warp orientation."
            )
        self._ensure_wired(fp)
        angle = wrap_angle(float(getattr(fp, "Angle", 0.0) or 0.0))

        def _residual(at_angle: float) -> float:
            fp.Angle = at_angle
            self.execute(fp)  # place the LCS for the current angle
            return self._edge_angle_error(fp)  # radians

        # Closed form: the rosette frame's measured angle decreases exactly
        # radians(1) per degree of Angle — the Angle rotates the frame
        # about the very normal the measurement uses — and the master
        # frame is Angle-independent.  The residual is therefore a
        # sawtooth of exact slope -pi/180 per degree, so the root is one
        # step away; wrapping into the fabric's principal period lands on
        # an equivalent root (period pi, undirected warp).
        residual = _residual(angle)
        for _ in range(3):
            if abs(residual) <= _ANGLE_TOL_RAD:
                _debug(
                    f"TransferRosette {fp.Name}: solved angle {angle:.4f} "
                    f"(residual {residual:.3g} rad)"
                )
                return
            angle = wrap_angle(angle + math.degrees(residual))
            residual = _residual(angle)
        raise RosetteSolveError(
            f"TransferRosette {fp.Name}: warp-continuity residual did not "
            f"settle within tolerance (last angle {angle:.4f} deg, "
            f"residual {residual:.3g} rad)"
        )

    def _edge_angle_error(self, fp) -> float:
        """Signed mean of (phi_rosette - phi_master) along the shared edge.

        Phase-1 frame measurement: both sides are read from rosette
        frames — the master's rosette frame and this rosette's own LCS —
        never from drape fields.  The combined-laminate model treats
        drape deviation as zero (stated in its report), and a drape
        lattice's boundary rows read frames that do not track the
        rosette, which made field-based residuals chaotic.  Per-sample
        residuals are folded into (-pi/2, pi/2] — period pi, the
        fabric's undirected warp — and the tangent varies along a curved
        edge, so the master's frame is compared against each local
        tangent.
        """
        master = fp.MasterShell
        edge = self._shared_edge(
            self._shape_of(master), self._shape_of(fp.AttachmentShell)
        )
        if edge is None:
            return 0.0

        samples = self._sample_edge(edge, _EDGE_SAMPLES)
        if not samples:
            return 0.0

        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return 0.0
        master_rotation = self._master_frame(master)
        rotation = lcs.Placement.Rotation

        residuals: List[float] = []
        for _point, tangent in samples:
            phi_m = self._axis_angle(master_rotation, tangent)
            phi_r = self._axis_angle(rotation, tangent)
            # Fold into (-pi/2, pi/2] — period pi, not 2pi: a fabric's
            # warp is an undirected line, so frames anti-parallel by 180
            # degrees are the SAME layup, and folding mod 2pi would put
            # the comparison on the atan2 branch cut where the signed
            # mean is meaningless.
            residual = (phi_r - phi_m + _HALF_PI) % math.pi - _HALF_PI
            residuals.append(residual)

        if not residuals:
            return 0.0
        return sum(residuals) / len(residuals)

    @staticmethod
    def _master_frame(master):
        """The master side's fibre frame rotation.

        Its rosette's LCS when linked; otherwise the support placement
        the shell's drape seeds from (rosette-less shells).
        """
        rosette = getattr(master, "Rosette", None)
        lcs = getattr(rosette, "LocalCoordinateSystem", None)
        if lcs is not None:
            return lcs.Placement.Rotation
        support = getattr(master, "Support", None)
        placement = getattr(support, "Placement", None)
        if placement is not None:
            return placement.Rotation
        return FreeCAD.Rotation()

    @staticmethod
    def _axis_angle(rotation, tangent) -> float:
        """Signed angle from `tangent` to the frame's X about its Z."""
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        normal = rotation.multVec(FreeCAD.Vector(0.0, 0.0, 1.0))
        if warp.Length < 1e-12 or normal.Length < 1e-12:
            return 0.0
        warp.normalize()
        normal.normalize()
        cross = warp.cross(tangent)
        return math.atan2(cross.dot(normal), warp.dot(tangent))

    @staticmethod
    def _shape_of(shell):
        """The shell's live support geometry.

        The shell feature's own ``Shape`` is a cached snapshot that does not
        necessarily track a moved support; the support's shape is the
        authoritative geometry for shared-edge discovery (delegates to the
        shared helper, known-issue #6).
        """
        from ..util.geometry_util import live_support_shape

        return live_support_shape(shell)

    @staticmethod
    def _shared_edge(master_shape, attachment_shape):
        """Return the longest edge shared by the two shell shapes."""
        try:
            shared = master_shape.section(attachment_shape)
        except Exception:
            return None
        edges = getattr(shared, "Edges", None)
        if not edges:
            return None
        return max(edges, key=lambda e: e.Length)

    @staticmethod
    def _sample_edge(edge, n):
        """Return [(point, unit_tangent)] at ``n`` arc-length midpoints."""
        length = edge.Length
        if length <= 0.0:
            return []
        samples = []
        for i in range(n):
            frac = (i + 0.5) / n
            try:
                t_param = edge.getParameterByLength(frac * length)
                point = edge.valueAt(t_param)
                tangent = edge.tangentAt(t_param)
            except Exception:
                continue
            tan = FreeCAD.Vector(tangent)
            if tan.Length < 1e-12:
                continue
            tan.normalize()
            samples.append((FreeCAD.Vector(point), tan))
        return samples


def attach_rosette_view_provider(rosette):
    """Attach the rosette view provider (GUI only) and raise it.

    Script-created rosettes get no ViewProvider otherwise: without one
    there is no rosette symbol at all — only the LCS datum — and the
    render-order raise has nothing to move.  The raise puts the symbol
    above any weave injected later.
    """
    vo = getattr(rosette, "ViewObject", None)
    if vo is None or getattr(vo, "Proxy", None) is not None:
        return
    try:
        ViewProviderTransferRosette(vo)
        proxy = getattr(vo, "Proxy", None)
        if proxy is not None and hasattr(proxy, "raise_render_order"):
            proxy.raise_render_order()
    except Exception:
        pass


class AnalysisTransferRosetteFP(TransferRosetteFP):
    """Standalone attachment→seam analysis rosette.

    Solves the same frame-based warp-continuity residual as
    :class:`TransferRosetteFP` but never rewires the host shell's
    ``Rosette`` link: it is analysis-only (the seam/stiffener shell's
    Rosette belongs to the master→region transfer).  The residual is
    evaluated against its own LCS frame — the phase-1 approximation
    carries no drape deviation (docs/seam_composite_laminate.md §5.2,
    ADR-0001).
    """

    def _ensure_wired(self, fp) -> None:
        # Standalone: the seam shell's Rosette stays with the
        # master→seam transfer rosette.
        return


class ViewProviderTransferRosette(ViewProviderRosette):
    """View provider for TransferRosette — reuses the Rosette symbol."""

    def getIcon(self):
        return TRANSFER_ROSETTE_TOOL_ICON


def _is_vertex_edge_or_face(o) -> bool:
    return isinstance(o, (Part.Vertex, Part.Edge, Part.Face))


class TransferRosetteCommand(BaseCommand):
    icon = TRANSFER_ROSETTE_TOOL_ICON
    menu_text = "Transfer Rosette"
    tool_tip = (
        "Solve the attachment shell rosette angle so its warp matches the\n"
        "master shell warp across their shared boundary edge.\n"
        "Select a master composite shell, an attachment composite shell,\n"
        "and (optionally) a support vertex/edge/face for the rosette origin."
    )
    sel_args = [
        {
            "key": "master_shell",
            "test": is_composite_shell,
        },
        {
            "key": "attachment_shell",
            "test": is_composite_shell,
        },
        {
            "key": "support",
            "test": _is_vertex_edge_or_face,
            "optional": True,
        },
    ]
    type_id = "App::FeaturePython"
    instance_name = "TransferRosette"
    cls_fp = TransferRosetteFP
    cls_vp = ViewProviderTransferRosette

    def Activated(self):
        sel = self.check_sel(True)
        if sel is None:
            return
        doc = FreeCAD.ActiveDocument
        obj = doc.addObject(self.type_id, self.instance_name)
        # Construct with the support only; the shells are wired afterwards so
        # the solve fires once the attachment shell actually points at this
        # rosette (avoids a premature solve with a stale attachment reference).
        self.cls_fp(obj, support=sel.get("support"))
        self.cls_vp(obj.ViewObject)
        attachment = sel.get("attachment_shell")
        if attachment is not None:
            attachment.Rosette = obj
        obj.MasterShell = sel.get("master_shell")
        obj.AttachmentShell = attachment
        from .Container import getCompositesContainer

        getCompositesContainer().addObject(obj)
        import FreeCADGui
        FreeCADGui.Selection.clearSelection()
        doc.recompute()


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
