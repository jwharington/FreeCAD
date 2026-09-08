# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""TransferRosette — iterative warp-transfer rosette on an attachment shell.

A :class:`TransferRosetteFP` is a :class:`Rosette` that lives on the
**attachment** shell (``attachment_shell.Rosette = transfer_rosette``). Its
``Angle`` is solved iteratively so the attachment shell's warp direction makes
the same signed angle with the shared boundary edge as the master shell's
warp, at sampled points along that edge. The solved angle is written back
into the inherited ``Angle`` property.

The solve is driven from :meth:`onChanged` (not :meth:`execute`) for the
defining references, guarded by a ``_solving`` flag so the solver's own
``Angle`` writes do not recurse.
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
    solve_rosette_angle,
)
from .Command import BaseCommand
from .CompositeShell import is_composite_shell
from .Rosette import (
    RosetteFP,
    ViewProviderRosette,
)

# Number of sample points along the shared boundary edge.
_EDGE_SAMPLES = 8


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
        """Hash everything the solved angle depends on."""
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
        """Iterate the attachment rosette Angle to match the master warp."""
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
        error_fn = lambda _angle: self._edge_angle_error(fp)
        try:
            angle = solve_rosette_angle(fp.AttachmentShell, fp, error_fn)
        except RosetteSolveError:
            # Keep the feature recompute-safe when the solve cannot bracket
            # (genuine non-convergence).
            return
        fp.Angle = angle

    def _edge_angle_error(self, fp) -> float:
        """Signed mean of (phi_attachment - phi_master) along the shared edge."""
        master = fp.MasterShell
        attachment = fp.AttachmentShell
        try:
            master_draper = master.Proxy.get_draper()
            attachment_draper = attachment.Proxy.get_draper()
        except AssertionError as exc:
            # A drape that failed (e.g. an intermittent solver_failure at
            # fine pitches) must surface as a handled solve failure, not
            # leak an assertion out of the solver.
            raise RosetteSolveError(f"draper invalid during solve: {exc}")
        if master_draper is None or attachment_draper is None:
            return 0.0

        edge = self._shared_edge(
            self._shape_of(master), self._shape_of(attachment)
        )
        if edge is None:
            return 0.0

        # Paired inset samples: each side is evaluated just inside its
        # own surface (boundary frames are unreliable — see
        # _inset_edge_samples).
        master_samples = self._inset_edge_samples(
            edge, self._shape_of(master), _EDGE_SAMPLES
        )
        attach_samples = self._inset_edge_samples(
            edge, self._shape_of(attachment), _EDGE_SAMPLES
        )
        if not master_samples or not attach_samples:
            return 0.0

        residuals: List[float] = []
        for (m_point, tangent), (a_point, _a_tangent) in zip(
            master_samples, attach_samples
        ):
            phi_m = self._warp_angle_at(master_draper, m_point, tangent)
            phi_a = self._warp_angle_at(attachment_draper, a_point, tangent)
            if phi_m is None or phi_a is None:
                continue
            # Wrap the per-sample residual into (-pi, pi] so the signed mean
            # is continuous across the atan2 branch cut at +/-180 deg. Without
            # this, a sample whose (phi_a - phi_m) crosses the cut flips sign
            # and the root-finder loses its bracket.
            residual = (phi_a - phi_m + math.pi) % (2.0 * math.pi) - math.pi
            residuals.append(residual)

        if not residuals:
            return 0.0
        return sum(residuals) / len(residuals)

    @staticmethod
    def _shape_of(shell):
        """The shell's live support geometry.

        The shell feature's own ``Shape`` is a cached snapshot that does not
        necessarily track a moved support; the support's shape is the
        authoritative geometry for shared-edge discovery.
        """
        support = getattr(shell, "Support", None)
        if support is not None:
            return support.Shape
        return shell.Shape

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
    def _inset_edge_samples(edge, shape, n, eps=1.5):
        """Sample the edge offset inward into *shape*'s surface.

        Warp evaluation exactly on the boundary is unreliable: the
        boundary drape nodes are boundary-snapped and their frames do
        not track the rosette seed, and UV queries at the exact edge can
        fail outright (making the residual evaluate to exactly 0 and the
        solver return a bracket endpoint).  Each sample point is offset
        a little along the surface, inward from the edge; the tangent is
        kept (the residual measures angles about the same edge line).
        """
        faces = getattr(shape, "Faces", [])
        out = []
        for point, tangent in TransferRosetteFP._sample_edge(edge, n):
            host = None
            for f in faces:
                try:
                    if f.isInside(point, 1e-6, True):
                        host = f
                        break
                except Exception:
                    continue
            if host is None:
                continue
            try:
                u, v = host.Surface.parameter(point)
                normal = host.normalAt(u, v)
            except Exception:
                continue
            normal.normalize()
            inward = tangent.cross(normal)
            if inward.Length < 1e-12:
                continue
            inward.normalize()
            chosen = None
            for sign in (1.0, -1.0):
                cand = point + inward * (sign * eps)
                try:
                    if host.isInside(cand, 1e-6, True):
                        chosen = cand
                        break
                except Exception:
                    continue
            if chosen is not None:
                out.append((chosen, tangent))
        return out

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

    @staticmethod
    def _draper_basis_at(draper, point):
        """Return (warp, normal) unit vectors at *point* from the draper.

        Warp is the LCS X-axis in world; normal is the LCS Z-axis. Both come
        from ``draper.get_lcs_at_point(point).Rotation``.
        """
        placement = draper.get_lcs_at_point(point)
        if placement is None:
            return None, None
        rotation = placement.Rotation
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        normal = rotation.multVec(FreeCAD.Vector(0.0, 0.0, 1.0))
        return warp, normal

    @staticmethod
    def _warp_angle_at(draper, point, tangent):
        """Signed angle from the edge tangent to the warp about the face normal."""
        warp, normal = TransferRosetteFP._draper_basis_at(draper, point)
        if warp is None or normal is None:
            return None
        if warp.Length < 1e-12 or normal.Length < 1e-12:
            return None
        warp.normalize()
        normal.normalize()
        cross = warp.cross(tangent)
        return math.atan2(cross.dot(normal), warp.dot(tangent))


class AnalysisTransferRosetteFP(TransferRosetteFP):
    """Standalone attachment→seam analysis rosette.

    Like :class:`TransferRosetteFP` but never rewires the host shell's
    ``Rosette`` link (it is analysis-only: the seam shell's Rosette
    belongs to the master→seam transfer), and the residual is evaluated
    against its *own* LCS frame rather than the host shell's drape — the
    phase-1 seam approximation carries no drape deviation
    (docs/seam_composite_laminate.md §5.2, ADR-0001).
    """

    def _ensure_wired(self, fp) -> None:
        # Standalone: the seam shell's Rosette stays with the
        # master→seam transfer rosette.
        return

    def _edge_angle_error(self, fp) -> float:
        master = fp.MasterShell
        try:
            master_draper = master.Proxy.get_draper()
        except AssertionError as exc:
            raise RosetteSolveError(
                f"draper invalid during solve: {exc}"
            )
        if master_draper is None:
            return 0.0

        edge = self._shared_edge(
            self._shape_of(master), self._shape_of(fp.AttachmentShell)
        )
        if edge is None:
            return 0.0

        # Master warp is evaluated just inside the master's surface —
        # boundary frames are unreliable (see _inset_edge_samples).  The
        # rosette frame is uniform in the phase-1 approximation, so the
        # inset does not affect phi_r.
        samples = self._inset_edge_samples(
            edge, self._shape_of(master), _EDGE_SAMPLES
        )
        if not samples:
            return 0.0

        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return 0.0
        rotation = lcs.Placement.Rotation
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        normal = rotation.multVec(FreeCAD.Vector(0.0, 0.0, 1.0))
        if warp.Length < 1e-12 or normal.Length < 1e-12:
            return 0.0
        warp.normalize()
        normal.normalize()

        residuals: List[float] = []
        for point, tangent in samples:
            phi_m = self._warp_angle_at(master_draper, point, tangent)
            if phi_m is None:
                continue
            cross = warp.cross(tangent)
            phi_r = math.atan2(cross.dot(normal), warp.dot(tangent))
            residual = (phi_r - phi_m + math.pi) % (2.0 * math.pi) - math.pi
            residuals.append(residual)
        if not residuals:
            return 0.0
        return sum(residuals) / len(residuals)


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
