# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD
import Part
from .. import (
    ROSETTE_TOOL_ICON,
    is_comp_type,
)
from .VPCompositeBase import (
    VPCompositeBase,
    CompositeBaseFP,
)
from .Command import BaseCommand


def is_rosette(obj):
    """Return True if *obj* is a Rosette feature."""
    return is_comp_type(obj, "App::FeaturePython", "Composite::Rosette")


def _frame_rotation(geom, angle_deg):
    """Build the rosette LCS rotation for a support geometry.

    For a Face: X = the face's U-axis at the anchor, rotated by ``angle_deg``
    about the face normal; Z = the face normal. The Angle is folded into the
    LCS so that changing it re-seeds the drape solver (the warp direction is
    the LCS X-axis).

    For a Vertex/Edge (no face-U reference): X = world-X rotated by
    ``angle_deg`` about world-Z, Z = world-Z.

    During document restore the Support sub-object may transiently resolve to
    a bare ``Part.Shape`` (before the subname remaps to the Face/Edge/Vertex),
    or to an empty/None list. In that case fall back to the identity frame so
    the recompute completes; a later recompute once the subname resolves will
    place the LCS correctly.
    """
    match type(geom):
        case Part.Vertex:
            position = geom.Point
            normal = FreeCAD.Vector(0.0, 0.0, 1.0)
            u_axis = FreeCAD.Vector(1.0, 0.0, 0.0)
        case Part.Edge:
            t = geom.getParameterByLength(0.5 * geom.Length)
            position = geom.valueAt(t)
            normal = FreeCAD.Vector(0.0, 0.0, 1.0)
            u_axis = FreeCAD.Vector(1.0, 0.0, 0.0)
        case Part.Face:
            u0, u1, v0, v1 = geom.ParameterRange
            position = geom.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            normal = geom.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            u_axis = geom.Surface.tangent(
                (u0 + u1) / 2.0, (v0 + v1) / 2.0
            )[0]
        case _:
            # Restore ordering: Support not yet resolved to a sub-shape.
            # Place at the origin with the identity frame; a subsequent
            # recompute (once the subname resolves) places the LCS correctly.
            return (
                FreeCAD.Vector(0.0, 0.0, 0.0),
                FreeCAD.Rotation(),
            )

    r_align = FreeCAD.Rotation(normal, float(angle_deg))
    x_axis = r_align.multVec(u_axis)
    y_axis = normal.cross(x_axis)
    rotation = FreeCAD.Rotation(x_axis, y_axis, normal, "ZXY")
    return position, rotation


def _origin_from_support(fp):
    """Return (position, rotation) from the Support and Angle properties.

    The rotation folds the rosette ``Angle`` into the LCS frame so the X-axis
    is the fibre 0\u00b0 direction (face-U rotated by Angle about the normal).
    Returns (FreeCAD.Vector(0,0,0), FreeCAD.Rotation()) when no support is set.
    """
    if not fp.Support:
        return FreeCAD.Vector(0.0, 0.0, 0.0), FreeCAD.Rotation()

    (sup, sub) = fp.Support
    geom_list = sup.getSubObject(sub)
    if not geom_list:
        # Restore ordering: sub-object not yet resolved.
        return FreeCAD.Vector(0.0, 0.0, 0.0), FreeCAD.Rotation()
    geom = geom_list[0]

    return _frame_rotation(geom, float(fp.Angle))


class RosetteFP(CompositeBaseFP):
    """FeaturePython for a Rosette – a planar local coordinate system datum.

    The Rosette defines an origin (derived from a vertex, edge midpoint, or
    face parametric centre) and a primary fibre-orientation angle (the degree
    of freedom).  A ``Part::LocalCoordinateSystem`` child object tracks the
    computed placement.
    """

    Type = "Composite::Rosette"

    def __init__(self, obj, support=None):

        obj.addProperty(
            "App::PropertyLinkSubGlobal",
            "Support",
            "References",
            "Vertex, edge, or face that defines the rosette origin",
        ).Support = support

        obj.addProperty(
            "App::PropertyAngle",
            "Angle",
            "Parameters",
            "Primary fibre orientation angle (degrees)",
        ).Angle = 0.0

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "LocalCoordinateSystem",
            "Materials",
            "Local coordinate system for the rosette datum",
        )
        obj.LocalCoordinateSystem = obj.Document.addObject(
            "Part::LocalCoordinateSystem",
            "LCS",
        )
        obj.setPropertyStatus("LocalCoordinateSystem", "LockDynamic")
        obj.setPropertyStatus("LocalCoordinateSystem", "ReadOnly")

        super().__init__(obj)

    def execute(self, fp):
        position, rotation = _origin_from_support(fp)
        lcs = fp.LocalCoordinateSystem
        lcs.Placement.Base = position
        lcs.Placement.Rotation = rotation
        # Writing the placement touches the LCS datum mid-sweep (we may be
        # executing inside another object's recompute); the datum is fully
        # placed, so consume the touch instead of leaving the "still touched
        # after recompute" warning behind (known-issue #9).
        lcs.purgeTouched()

        # The VP symbol is built in attach() before execute() runs, so
        # it sits at the origin until a property change re-triggers it.
        # Refresh it now that the LCS placement is known.
        vp = getattr(fp, "ViewObject", None)
        if vp is not None:
            proxy = getattr(vp, "Proxy", None)
            if proxy is not None and hasattr(proxy, "_update_symbol"):
                proxy._update_symbol()

    def onChanged(self, fp, prop):
        match prop:
            case "Support" | "Angle":
                fp.recompute()


class ViewProviderRosette(VPCompositeBase):

    def attach(self, vobj):
        from pivy import coin
        from .RosetteSymbol import RosetteSymbol

        self.Object = vobj.Object
        self.ViewObject = vobj
        self._rosette = RosetteSymbol()
        self.standard = coin.SoGroup()
        self.standard.addChild(self._rosette.separator)
        # Named so the mode switch can be located reliably later — pivy
        # returns a fresh Python wrapper per getChild(), so node identity
        # must be established on the C++ side (by name), not with `is`.
        self.standard.setName("RosetteStandardMode")
        vobj.addDisplayMode(self.standard, "Standard")
        self._pin_display_switch(vobj)
        self._update_symbol()
        self._hide_datum_symbology()
        # The GUI's new-object finalization is deferred: it can re-derive
        # the mode switch after this attach returns. Re-pin once the
        # event loop settles.
        try:
            from PySide import QtCore

            def _deferred_pin():
                try:
                    self._pin_display_switch(vobj)
                except Exception:
                    pass  # document closed before the timer fired

            QtCore.QTimer.singleShot(0, _deferred_pin)
        except Exception:
            pass

    def _pin_display_switch(self, vobj):
        """Force the Standard-mode switch onto the symbol (whichChild 0).

        A rosette whose ViewProvider attaches after FreeCAD's GUI has
        already initialised the object's display bookkeeping — e.g. a
        transfer rosette wired up by a flow mid-build — can in principle
        be left with the mode switch at NONE: the node sits in the scene
        graph but nothing renders (the attach race from the
        rosette-visibility work).  The switch holding the named Standard
        branch is located by traversal and pinned explicitly; harmless
        when already selected.  Other switches under the RootNode (the
        hidden datum/indicator symbology) are legitimately NONE and are
        left alone.

        The mode switch IS the visibility mechanism (C++ hide() writes
        whichChild = -1), so a deliberately hidden rosette must stay
        hidden — only a VISIBLE rosette is pinned.
        """
        from pivy import coin

        if not getattr(vobj, "Visibility", True):
            return
        root = getattr(vobj, "RootNode", None)
        if root is None:
            return

        def visit(node):
            if node is None:
                return
            try:
                is_switch = node.getTypeId().isDerivedFrom(
                    coin.SoSwitch.getClassTypeId()
                )
                children = int(node.getNumChildren())
            except AttributeError:
                return
            if is_switch and any(
                (node.getChild(i).getName() or "") == "RosetteStandardMode"
                for i in range(children)
            ):
                node.whichChild = 0
            for i in range(children):
                visit(node.getChild(i))

        visit(root)

    def updateData(self, fp, prop):
        if prop in ("Support", "Angle"):
            self._update_symbol()
            self._hide_datum_symbology()

    def raise_render_order(self):
        """Move this rosette's scene node after all other objects.

        The symbol renders in Coin's deferred pass, which preserves scene
        order: a rosette created before its shell would have its symbol
        blended over by the shell's weave shader. Moving the node to the
        end of the viewer's scene graph puts the symbol on top.

        The node is not necessarily a direct child of the scene graph:
        rosettes created while a recompute is in flight (e.g. the seam
        flow's transfer rosettes) get their RootNode nested under a group
        instead of appended at top level. The node's actual parent is
        located by traversal and the node re-parented from there.
        """
        import FreeCADGui

        view = FreeCADGui.activeDocument().activeView()
        if not hasattr(view, "getSceneGraph"):
            return
        scene = view.getSceneGraph()
        root = self.ViewObject.RootNode

        def find_parent(node, target):
            try:
                n = node.getNumChildren()
            except AttributeError:
                return None  # group-less node (transforms, materials, ...)
            for i in range(n):
                child = node.getChild(i)
                if child is target:
                    return node
                parent = find_parent(child, target)
                if parent is not None:
                    return parent
            return None

        parent = find_parent(scene, root)
        if parent is None or parent is scene:
            try:
                scene.removeChild(root)
            except Exception:
                return
        else:
            parent.removeChild(root)
        scene.addChild(root)
        # The re-parent is the flow's last render fixup — re-pin the mode
        # switch so a deferred GUI update cannot leave it at NONE.
        self._pin_display_switch(self.ViewObject)

    def _hide_datum_symbology(self):
        """Hide the LCS datum's native grey glyph.

        The coloured RosetteSymbol replaces it — the grey datum display is
        nearly invisible against the shell surfaces and gets mistaken for
        the rosette itself. The LCS's Origin sub-objects (axes, planes) are
        hidden too: they draw as coloured translucent flags right where the
        symbol sits.
        """
        lcs = getattr(self.Object, "LocalCoordinateSystem", None)
        if lcs is None:
            return
        to_hide = [lcs]
        origin = getattr(lcs, "Origin", None)
        if origin is not None:
            to_hide.extend(getattr(origin, "OriginFeatures", []) or [])
            to_hide.append(origin)
        for obj in to_hide:
            vobj = getattr(obj, "ViewObject", None)
            if vobj is not None and vobj.Visibility:
                vobj.Visibility = False

    def _update_symbol(self):
        fp = self.Object
        angle = float(fp.Angle)
        lcs = fp.LocalCoordinateSystem
        pos = lcs.Placement.Base
        rot = lcs.Placement.Rotation
        q = rot.Q
        self._rosette.update(
            orientations=[angle],
            position=(pos.x, pos.y, pos.z),
            rotation=(q[0], q[1], q[2], q[3]),
        )

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        return [obj.LocalCoordinateSystem]

    def getIcon(self):
        return ROSETTE_TOOL_ICON


def _is_vertex_edge_or_face(o):
    """Return True if *o* is a Part vertex, edge, or face shape."""
    return isinstance(o, (Part.Vertex, Part.Edge, Part.Face))


class RosetteCommand(BaseCommand):

    icon = ROSETTE_TOOL_ICON
    menu_text = "Rosette"
    tool_tip = (
        "Create a Rosette (planar local coordinate system datum).\n"
        "Select a vertex (origin at vertex), edge (origin at midpoint),\n"
        "or face (origin at parametric centre).\n"
        "Without selection the origin is at the model origin."
    )
    sel_args = [
        {
            "key": "support",
            "test": _is_vertex_edge_or_face,
            "optional": True,
        },
    ]
    type_id = "App::FeaturePython"
    instance_name = "Rosette"
    cls_fp = RosetteFP
    cls_vp = ViewProviderRosette


# Command registration moved to InitGui.py to avoid FreeCADGui dependency
