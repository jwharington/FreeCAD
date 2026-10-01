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
from collections import OrderedDict
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

# Two joint faces whose normals agree to within this are one plane: the
# attachment is the same physical sheet as the master (possibly wound
# opposite), not a fold onto it.
_COPLANAR_DOT_TOL = 1e-9

# Probe separation in degrees of Angle for the measured residual slope.
_SLOPE_PROBE_DEG = 1.0

# Between the fold boundaries the residual is exact-linear in Angle with
# slope +/- pi/180 rad per degree; a measured slope far below that means
# the measurement has lost sensitivity to the angle and no root-finder
# can move.
_MIN_SLOPE_MAGNITUDE = math.pi / 180.0 * 0.25

_HALF_PI = math.pi / 2.0

# Shared-edge memo: the edge depends only on the two shell shapes, while
# the seam validation and any remaining solve ask for it repeatedly for the
# same pair (measured: 4 calls for 2 distinct pairs per ring, and 14 per
# solve before the solve passed its edge down).
#
# Keyed by the order-independent shape stamp.  Two other keys were tried
# and miss on every call here: Shape.hashCode() follows a re-wrapped copy,
# and shape_fingerprint walks vertices in traversal order, so a rebuilt
# compound fingerprints differently for identical geometry.  The stamp
# collapses those calls to the number of real argument pairs.
_SHARED_EDGE_CACHE_MAX = 64
_SHARED_EDGE_CACHE = OrderedDict()


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

    # NOTE: MasterShell/AttachmentShell use App::PropertyLinkHidden — they
    # are solve *references*, not geometry dependencies.  The real
    # dependency is the attachment shell's Rosette link pointing back at
    # this rosette; visible back-references made shell→rosette→shell a
    # dependency cycle that tripped DAGView (known-issue #9).  Hidden
    # links still read normally; they only stay out of the touch/DAG
    # propagation.  Freshness is pull-based: consumers resolve() against
    # the fingerprint, and the SCL re-executes via its own direct shell
    # links.

    def __init__(
        self,
        obj,
        support=None,
        master_shell=None,
        attachment_shell=None,
        direct_contact=False,
        shared_surface=False,
    ):
        # Suppress any solve while the defining references are being set up.
        # Set before super().__init__ (which may trigger onChanged).
        self._solving = True
        super().__init__(obj, support)
        obj.addProperty(
            type="App::PropertyLinkHidden",
            name="MasterShell",
            group="References",
            doc="Master composite shell (already solved)",
        ).MasterShell = master_shell
        obj.addProperty(
            type="App::PropertyLinkHidden",
            name="AttachmentShell",
            group="References",
            doc="Attachment composite shell whose rosette this is",
        ).AttachmentShell = attachment_shell
        obj.addProperty(
            type="App::PropertyBool",
            name="DirectContact",
            group="Solve",
            doc=(
                "Measure warp continuity at the rosette's own contact point "
                "instead of averaging along the shells' shared boundary "
                "edge.  Valid for insertion joints, where the stiffener "
                "must follow the panel where it sits, and it needs no "
                "section at all; the edge solve remains for seam joints."
            ),
        ).DirectContact = bool(direct_contact)
        obj.addProperty(
            type="App::PropertyBool",
            name="SharedSurface",
            group="Solve",
            doc=(
                "The two sides carry one surface: the attachment's rosette "
                "is placed directly at the master's frame (calculated at a "
                "point on the contact boundary edge) and no warp-continuity "
                "solve runs — a stiffener's foot band is cut from its "
                "panel's own faces, so the foot bears the orientation the "
                "support sets."
            ),
        ).SharedSurface = bool(shared_surface)
        self._solving = False
        if master_shell is not None and attachment_shell is not None:
            # The property-set onChanged calls above were suppressed by the
            # _solving guard, so the initial wiring and angle solve never
            # ran. Run them now, exactly as the deferred onChanged would.
            self._ensure_wired(obj)
            self._solve(obj)
            self._last_solve_fingerprint = self._solve_inputs_fingerprint(obj)
            obj.recompute()
            # The solve wrote Angle and placed the LCS (both touch this
            # object mid-sweep — the constructor runs inside another
            # object's execute); the state is consistent, so consume the
            # touch instead of leaving the "still touched" warning.
            obj.purgeTouched()

    def execute(self, fp):
        # Place the LCS from Support + Angle only; the iterative solve is
        # driven from onChanged so it never recurses into execute().
        # A joint whose two sides carry one surface has no angle to solve:
        # the rosette is placed straight from the master's frame.
        if getattr(fp, "SharedSurface", False) or self._support_lies_on_master(fp):
            self._place_from_master(fp)
            return
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
        # The solve wrote Angle and placed the LCS, which touches this
        # object mid-sweep (we are inside the consumer's execute); the
        # state is already consistent, so consume the touch instead of
        # leaving the "still touched after recompute" warning behind.
        fp.purgeTouched()

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

        A joint whose two sides carry ONE surface — the stiffener's foot band
        is cut from its panel's own faces — has its warp continuity by
        construction: the rosette is placed directly at the master's frame,
        calculated at a point on the contact boundary edge, and no residual
        solve runs.  The iterative solve's probes would be meaningless there:
        the edge-referenced LCS rotates about world Z, and on an inclined
        joint the residual then moves at cos(inclination) rad per degree —
        measured 0.000174 on the fuselage's spar joint, a hundredth of the
        true rate, which the slope check rightly refuses as insensitive.
        Same spirit as the seam remainder, which simply carries the
        attachment's own rosette.
        """
        master = fp.MasterShell
        attachment = fp.AttachmentShell
        self._ensure_wired(fp)
        if getattr(fp, "SharedSurface", False) or self._support_lies_on_master(fp):
            self._place_from_master(fp)
            return
        # Insertion joints measure at the rosette's own contact point: the
        # residual is a difference of two frame angles about a shared
        # reference, so one point on the contact line is sufficient and no
        # section is needed.  Everything else — the seam flow, and a joint
        # whose rosette has no contact point — averages along the shells'
        # shared boundary edge, which also validates that the edge exists.
        target = self._contact_point(fp)
        if target is None:
            target = self._shared_edge(
                self._shape_of(master), self._shape_of(attachment)
            )
            if target is None:
                raise ValueError(
                    "TransferRosette: master and attachment shells share no "
                    "boundary edge — cannot transfer warp orientation."
                )
        angle = wrap_angle(float(getattr(fp, "Angle", 0.0) or 0.0))
        residual = self._residual_at(fp, angle, target)
        for _ in range(3):
            if abs(residual) <= _ANGLE_TOL_RAD:
                _debug(
                    f"TransferRosette {fp.Name}: solved angle {angle:.4f} "
                    f"(residual {residual:.3g} rad)"
                )
                return
            slope = self._residual_slope(fp, angle, target)
            if abs(slope) < _MIN_SLOPE_MAGNITUDE:
                raise RosetteSolveError(
                    f"TransferRosette {fp.Name}: residual is insensitive "
                    f"to Angle (slope {slope:.3g} rad/deg) — cannot solve "
                    f"warp continuity on this joint geometry"
                )
            angle = wrap_angle(angle - residual / slope)
            residual = self._residual_at(fp, angle, target)
        raise RosetteSolveError(
            f"TransferRosette {fp.Name}: warp-continuity residual did not "
            f"settle within tolerance (last angle {angle:.4f} deg, "
            f"residual {residual:.3g} rad)"
        )

    def _support_lies_on_master(self, fp) -> bool:
        """Whether the attachment's support lies on the master's mould.

        One surface carried by both sides of the joint: the stiffener's foot
        band, cut from its panel's own faces.  The master's live support is
        the remainder once the seat is consumed — the band lies on the mould
        the panel started from (``SupportBackup``), not on the remainder —
        so the mould is what the test reads.  Decided by the attachment's
        support vertices, every one of which must lie on that shape (the
        band's vertices sit on the panel to ~1e-13; a seam strip spanning a
        junction has vertices off either surface).
        """
        try:
            attachment = self._shape_of(fp.AttachmentShell)
        except Exception:
            return False
        master = self._master_mould_shape(fp)
        if attachment is None or master is None or not attachment.Vertexes:
            return False
        try:
            return all(
                master.distToShape(Part.Vertex(vertex.Point))[0] <= 1e-6
                for vertex in attachment.Vertexes
            )
        except Exception:
            return False

    def _master_mould_shape(self, fp):
        """The master's mould surface: the captured pre-stiffener support
        when the seat has been consumed, else the live support."""
        master = fp.MasterShell
        backup = getattr(master, "SupportBackup", None)
        if backup is not None and hasattr(backup, "Shape"):
            return backup.Shape
        return self._shape_of(master)

    def _place_from_master(self, fp) -> None:
        """Place the rosette directly at the master's frame.

        The phase-1 warp field is the rosette's own frame, so on a joint whose
        sides share one surface the master's rosette rotation IS the
        attachment's.  The LCS is calculated at a point on the contact
        boundary edge — the direct-contact support's own edge centre, else
        the centre of the edge the shells share — and set directly; no angle
        is solved and none is needed.
        """
        point = self._on_contact_geometry(fp)
        if point is None:
            point = self._contact_point(fp)
        if point is None:
            edge = self._shared_edge(
                self._shape_of(fp.MasterShell), self._shape_of(fp.AttachmentShell)
            )
            if edge is None:
                raise ValueError(
                    "TransferRosette: master and attachment shells share no "
                    "boundary edge — cannot place the rosette from the master."
                )
            point = edge.CenterOfMass
        rotation = self._master_frame(fp.MasterShell)
        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return
        lcs.Placement.Base = FreeCAD.Vector(point)
        lcs.Placement.Rotation = rotation
        lcs.purgeTouched()
        _debug(
            f"TransferRosette {fp.Name}: placed from the master's frame at "
            f"{point} (SharedSurface joint; no solve)"
        )

    def _on_contact_geometry(self, fp):
        """A point ON the rosette's referenced contact geometry.

        The direct-contact support names an edge of the attachment's support;
        its centre of mass is on an open edge but is the *centre of the
        curve* for a closed one (a full ring band's base-row ellipse centres
        on the ring's axis, well off the surface) — and the seed point must
        be on the surface to grow from.  The length midpoint is on either.
        """
        support = getattr(fp, "Support", None)
        if support is None:
            return None
        try:
            basis, sub = support
            for geom in basis.getSubObject(sub) or []:
                if isinstance(geom, Part.Edge):
                    t = geom.getParameterByLength(0.5 * geom.Length)
                    return FreeCAD.Vector(geom.valueAt(t))
                centre = getattr(geom, "CenterOfMass", None)
                if centre is not None:
                    return FreeCAD.Vector(centre)
        except Exception:
            return None
        return None

    def _residual_at(self, fp, angle: float, target=None) -> float:
        """Place the LCS at *angle* and read the residual in radians.

        *target* is the joint's shared edge (averaged along it) or, for an
        insertion joint, a single contact point.  Pass it when the caller
        has it: the target does not depend on the angle, while measuring it
        again would (for an edge) rebuild the flow's most expensive section.
        """
        fp.Angle = angle
        self.execute(fp)  # place the LCS for the current angle
        if isinstance(target, FreeCAD.Vector):
            return self._point_angle_error(fp, target)
        return self._edge_angle_error(fp, target)

    def _residual_slope(self, fp, angle: float, target=None) -> float:
        """Measured residual slope, radians of residual per degree of Angle.

        Two free probes one degree either side, with the mod-pi fold
        unwrapped so a probe pair straddling a fold boundary still reads
        the true linear slope instead of its wrapped complement.
        """
        r_lo = self._residual_at(fp, angle - _SLOPE_PROBE_DEG, target)
        r_hi = self._residual_at(fp, angle + _SLOPE_PROBE_DEG, target)
        delta = r_hi - r_lo
        if delta > _HALF_PI:
            delta -= math.pi
        elif delta < -_HALF_PI:
            delta += math.pi
        return delta / (2.0 * _SLOPE_PROBE_DEG)

    @staticmethod
    def _contact_point(fp):
        """A robust point on the contact line, for direct solving.

        None unless the rosette asks for direct contact alignment: the
        general solve's edge measurement (and its boundary-edge validation)
        stays in force for seam joints.

        The point is the centre of mass of the rosette's support face, not
        the LCS origin: the origin is the face's *parametric* centre, which
        on a closed cylinder sits exactly on the face's seam line.  There
        the nearest-face lookup can flip between the seam's two halves,
        flipping the measurement normal and jumping the residual by pi
        between two probe calls — measured as a slope of -0.0012 rad/deg
        where 0.0175 was expected, so the solve refused to converge.  The
        centre of mass is an interior point, well away from any seam.
        """
        if not bool(getattr(fp, "DirectContact", False)):
            return None
        support = getattr(fp, "Support", None)
        if support is not None:
            try:
                basis, sub = support
                for geom in basis.getSubObject(sub) or []:
                    centre = getattr(geom, "CenterOfMass", None)
                    if centre is not None:
                        return FreeCAD.Vector(centre)
            except Exception:
                pass
        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return None
        return FreeCAD.Vector(lcs.Placement.Base)

    def _point_angle_error(self, fp, point) -> float:
        """Warp mismatch at one contact point.

        The same measurement the edge path makes, evaluated at a single
        point on the contact line: each side's signed warp angle about the
        joint normal, against one shared reference tangent.  The reference
        tangent cancels in the difference but must not lie along either
        warp (that puts both angles at an atan2 limit and the residual goes
        flat in Angle), so it is built from the master's surface *U*
        direction at the point, which is independent of both rosettes.
        """
        master = fp.MasterShell
        master_shape = self._shape_of(master)
        master_normal = self._surface_normal(master_shape, point)
        if master_normal is None:
            return 0.0
        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return 0.0
        tangent = self._surface_tangent(master_shape, point, master_normal)
        if tangent is None:
            return 0.0
        # Reference the measurement to the MASTER's warp: the tangent then
        # cancels for the master side and the residual reads directly as the
        # angle still to apply.  It must not be left exactly on the mod-pi
        # fold cut, which is what happens when the two warps start 90 deg
        # apart, so a warp-aligned tangent is rotated a quarter of the joint
        # angle away from the attachment warp is unnecessary here: the value
        # at the cut is handled by the solve's probe unwrap, and the contact
        # point (not the tangent) was what made the measurement discontinuous.

        attachment_shape = self._shape_of(fp.AttachmentShell)
        attachment_normal = self._surface_normal(attachment_shape, point)
        master_rotation = self._master_frame(master)
        attachment_rotation = lcs.Placement.Rotation
        coplanar = (
            attachment_normal is not None
            and abs(master_normal.dot(attachment_normal))
            > 1.0 - _COPLANAR_DOT_TOL
        )
        if coplanar:
            phi_m = self._axis_angle_about(
                master_rotation, tangent, master_normal
            )
            phi_a = self._axis_angle_about(
                attachment_rotation, tangent, master_normal
            )
        else:
            phi_m = self._axis_angle(master_rotation, tangent)
            phi_a = self._axis_angle(attachment_rotation, tangent)
        residual = (phi_a - phi_m + _HALF_PI) % math.pi - _HALF_PI
        _debug(
            "point %s: angle=%.4f coplanar=%s tangent=(%.4f,%.4f,%.4f) "
            "n_m=(%.4f,%.4f,%.4f) n_a=%s phi_m=%+.6f phi_a=%+.6f "
            "residual=%+.6f"
            % (
                fp.Name,
                float(fp.Angle),
                coplanar,
                tangent.x,
                tangent.y,
                tangent.z,
                master_normal.x,
                master_normal.y,
                master_normal.z,
                "None"
                if attachment_normal is None
                else "(%.4f,%.4f,%.4f)"
                % (
                    attachment_normal.x,
                    attachment_normal.y,
                    attachment_normal.z,
                ),
                phi_m,
                phi_a,
                residual,
            )
        )
        return residual

    @staticmethod
    def _surface_tangent(shape, point, normal):
        """A unit tangent of the face of *shape* nearest *point*.

        Taken from the surface's own parameter axes (the U direction), so it
        does not depend on any rosette and cannot coincide with a warp by
        construction.
        """
        vertex = Part.Vertex(point)
        best = None
        for face in shape.Faces:
            try:
                dist, _points, _info = face.distToShape(vertex)
            except Exception:
                continue
            if best is None or dist < best[0]:
                best = (dist, face)
        if best is None:
            return None
        face = best[1]
        u, v = face.Surface.parameter(point)
        d = 1e-6
        try:
            first = face.valueAt(u, v)
            second = face.valueAt(min(u + d, 1.0), v)
            if (second - first).Length <= 1e-9:
                second = face.valueAt(u, min(v + d, 1.0))
            tangent = FreeCAD.Vector(second) - FreeCAD.Vector(first)
        except Exception:
            return None
        if tangent.Length <= 1e-9:
            return None
        tangent = tangent - normal * tangent.dot(normal)
        if tangent.Length <= 1e-9:
            return None
        return tangent.normalize()

    def _edge_angle_error(self, fp, edge=None) -> float:
        """Signed mean of (phi_attachment - phi_master) along the shared edge.

        *edge* is the joint's shared edge.  When not supplied it is derived
        here; the solve derives it once and passes it in, because the
        section is the flow's most expensive operation.

        Phase-1 frame measurement: both sides are read from rosette
        frames — the master's rosette frame and this rosette's own LCS —
        never from drape fields.  The combined-laminate model treats
        drape deviation as zero (stated in its report), and a drape
        lattice's boundary rows read frames that do not track the
        rosette, which made field-based residuals chaotic.

        The measurement normal comes from the JOINT'S surface geometry
        at each sample, not from the frames:

        * folded joint (distinct planes): each side is measured about
          its own frame normal — the ply's angle to the shared edge
          within its own surface, which a real layup preserves across
          the fold;
        * coplanar joint (one plane, possibly wound opposite — the
          panel/foot case): both sides are measured about the master's
          surface normal, comparing the frames in world terms.  Own-
          normal measurement there reads the mirrored warp as
          continuity (opposite normals cancel the mirror's sign flip)
          and converged the solve to the mirror.

        Per-sample residuals are folded into (-pi/2, pi/2] — the
        fabric's warp is an undirected line (0 deg is the same layup as
        180 deg), and folding mod 2pi would put the comparison on the
        atan2 branch cut where the signed mean is meaningless.  The
        tangent varies along a curved edge, so each sample compares
        against its own local tangent.
        """
        if edge is None:
            edge = self._shared_edge(
                self._shape_of(fp.MasterShell),
                self._shape_of(fp.AttachmentShell),
            )
        if edge is None:
            return 0.0

        master = fp.MasterShell
        master_shape = self._shape_of(master)
        attachment_shape = self._shape_of(fp.AttachmentShell)
        samples = self._sample_edge(edge, _EDGE_SAMPLES)
        if not samples:
            return 0.0

        lcs = getattr(fp, "LocalCoordinateSystem", None)
        if lcs is None:
            return 0.0
        master_rotation = self._master_frame(master)
        attachment_rotation = lcs.Placement.Rotation

        residuals: List[float] = []
        for point, tangent in samples:
            master_normal = self._surface_normal(master_shape, point)
            attachment_normal = self._surface_normal(attachment_shape, point)
            if (
                master_normal is not None
                and attachment_normal is not None
                and abs(master_normal.dot(attachment_normal))
                > 1.0 - _COPLANAR_DOT_TOL
            ):
                phi_m = self._axis_angle_about(
                    master_rotation, tangent, master_normal
                )
                phi_a = self._axis_angle_about(
                    attachment_rotation, tangent, master_normal
                )
            else:
                phi_m = self._axis_angle(master_rotation, tangent)
                phi_a = self._axis_angle(attachment_rotation, tangent)
            residual = (phi_a - phi_m + _HALF_PI) % math.pi - _HALF_PI
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
    def _axis_angle_about(rotation, tangent, normal) -> float:
        """Signed angle from the frame's X (warp) to *tangent* about *normal*.

        The measurement normal fixes the sign convention: the same world
        fibre reads opposite signed angles about opposite normals.
        """
        warp = rotation.multVec(FreeCAD.Vector(1.0, 0.0, 0.0))
        if warp.Length < 1e-12 or normal.Length < 1e-12:
            return 0.0
        warp.normalize()
        measurement_normal = FreeCAD.Vector(normal)
        measurement_normal.normalize()
        cross = warp.cross(tangent)
        return math.atan2(cross.dot(measurement_normal), warp.dot(tangent))

    @staticmethod
    def _axis_angle(rotation, tangent) -> float:
        """Signed angle from `tangent` to the frame's X about its own Z."""
        normal = rotation.multVec(FreeCAD.Vector(0.0, 0.0, 1.0))
        return TransferRosetteFP._axis_angle_about(rotation, tangent, normal)

    @staticmethod
    def _surface_normal(shape, point):
        """The world normal of the face of *shape* nearest *point*.

        None when no face can answer (a guard, not an assumption — the
        residual falls back to frame-own-normal measurement then).
        """
        vertex = Part.Vertex(point)
        best = None
        for face in shape.Faces:
            try:
                dist, _points, _info = face.distToShape(vertex)
            except Exception:
                continue
            if best is None or dist < best[0]:
                u, v = face.Surface.parameter(point)
                best = (dist, face.normalAt(u, v))
        return best[1] if best is not None else None

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
        """Return the longest edge shared by the two shell shapes.

        Memoised per pair of shape stamps: this builds a full section of
        the two shells — the most expensive operation in the composite
        flow — and callers ask for it repeatedly for the same pair (the
        seam validation twice, the solve once per residual evaluation
        before it began passing its edge down).  A stamp that does not
        match simply recomputes, so the cache is never wrong, only
        occasionally redundant.
        """
        from ..util.geometry_util import shape_stamp

        key = (shape_stamp(master_shape), shape_stamp(attachment_shape))
        if key in _SHARED_EDGE_CACHE:
            return _SHARED_EDGE_CACHE[key]
        try:
            shared = master_shape.section(attachment_shape)
        except Exception:
            edge = None
        else:
            edges = getattr(shared, "Edges", None)
            edge = max(edges, key=lambda e: e.Length) if edges else None
        _SHARED_EDGE_CACHE[key] = edge
        if len(_SHARED_EDGE_CACHE) > _SHARED_EDGE_CACHE_MAX:
            _SHARED_EDGE_CACHE.popitem(last=False)
        return edge

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


# The ViewProvider class that repairs this feature's serialised VP
# proxy on document restore (see CompositeBaseFP.onDocumentRestored).
TransferRosetteFP.view_provider_class = ViewProviderTransferRosette
