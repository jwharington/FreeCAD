# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

from __future__ import annotations

import FreeCAD
import FreeCADGui
import Part

from .. import SEAM_TOOL_ICON
from ..objects import SymmetryType
from ..tools.seam import make_edge_seam, make_join_seam
from .Command import BaseCommand
from .CompositeShell import CompositeShellFP, is_composite_shell
from .Laminate import LaminateFP
from .VPCompositePart import CompositePartFP, VPCompositePart


class VirtualLaminateFP(LaminateFP):
    def execute(self, obj):
        return


LAP_SIDE_OPTIONS = ["A+B", "B+A"]
DEFAULT_OVERLAP = "10.0 mm"


def _source_shape(obj):
    support = getattr(obj, "Support", None)
    shape = getattr(support, "Shape", None) if support is not None else None
    if shape is not None:
        return shape
    return getattr(obj, "Shape", None)


def _largest_face(shape):
    if shape is None:
        raise ValueError("missing shape")
    if getattr(shape, "ShapeType", None) == "Face":
        return shape
    faces = getattr(shape, "Faces", None)
    if not faces:
        raise ValueError("missing faces")
    return max(faces, key=lambda face: getattr(face, "Area", 0.0))


def make_shape_seam(master, attachment, overlap: float = 10.0):
    return make_join_seam(
        _largest_face(_source_shape(master)),
        _largest_face(_source_shape(attachment)),
        overlap=overlap,
    )


class SeamFP(CompositePartFP):
    def __init__(self, obj, edges=None):
        if edges is None:
            edges = []

        obj.addProperty(
            "App::PropertyLinkSubList",
            "Edges",
            "References",
            "Edges",
            locked=True,
        ).Edges = edges

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Master",
            "References",
            "Master shape",
            locked=True,
        )

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Attachment",
            "References",
            "Attachment shape",
            locked=True,
        )

        obj.addProperty(
            "App::PropertyEnumeration",
            "LapSide",
            "Composition",
            "Order of laminate aggregation",
            locked=True,
        )
        obj.LapSide = LAP_SIDE_OPTIONS
        obj.LapSide = LAP_SIDE_OPTIONS[0]

        obj.addProperty(
            "App::PropertyLength",
            "Overlap",
            "Dimension",
            "Overlap length",
            locked=True,
        ).Overlap = DEFAULT_OVERLAP

        super().__init__(obj)

    def execute(self, fp):
        if fp.Edges:
            def resolve_edge(ref):
                edge = ref[0].getSubObject(ref[1])
                if isinstance(edge, (list, tuple)):
                    return edge[0]
                return edge

            edges = [resolve_edge(e) for e in fp.Edges]
            source = fp.Edges[0][0]
            shape = make_edge_seam(
                shape=source.Shape,
                edges=edges,
                overlap=float(fp.Overlap),
            )
            fp.Shape = shape
            source.Visibility = False
            return

        if fp.Master is None or fp.Attachment is None:
            raise ValueError("missing edges")

        shape = make_shape_seam(
            fp.Master,
            fp.Attachment,
            overlap=float(fp.Overlap),
        )
        fp.Shape = shape


class SeamShellFP(CompositeShellFP):
    def __init__(
        self,
        obj,
        master,
        attachment,
        lap_side=LAP_SIDE_OPTIONS[0],
        overlap=DEFAULT_OVERLAP,
    ):
        super().__init__(obj, support=None, laminate=None, rosette=None)

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Master",
            "References",
            "Master shell",
            locked=True,
        ).Master = master

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Attachment",
            "References",
            "Attachment shell",
            locked=True,
        ).Attachment = attachment

        obj.addProperty(
            "App::PropertyEnumeration",
            "LapSide",
            "Composition",
            "Order of laminate aggregation",
            locked=True,
        )
        obj.LapSide = LAP_SIDE_OPTIONS
        obj.LapSide = lap_side if lap_side in LAP_SIDE_OPTIONS else LAP_SIDE_OPTIONS[0]

        obj.addProperty(
            "App::PropertyLength",
            "Overlap",
            "Dimension",
            "Overlap length",
            locked=True,
        ).Overlap = overlap

        previous = getattr(self, "_initializing", False)
        self._initializing = True
        try:
            self._sync_virtual_inputs(obj)
        finally:
            self._initializing = previous

    def onChanged(self, fp, prop):
        if getattr(self, "_initializing", False):
            return
        if prop in {"Master", "Attachment", "LapSide", "Overlap"}:
            fp.recompute()
            return
        super().onChanged(fp, prop)

    def _ordered_shells(self, fp):
        if not is_composite_shell(fp.Master) or not is_composite_shell(fp.Attachment):
            raise ValueError("seam shell requires two CompositeShell inputs")
        if fp.LapSide == "B+A":
            return fp.Attachment, fp.Master
        return fp.Master, fp.Attachment

    def _build_virtual_laminate(self, doc, fp, master, attachment):
        ordered_master, ordered_attachment = self._ordered_shells(fp)
        layers = list(getattr(ordered_master.Laminate, "Layers", []) or [])
        layers.extend(list(getattr(ordered_attachment.Laminate, "Layers", []) or []))

        name = f"{fp.Name}_VirtualLaminate"
        laminate = doc.getObject(name)
        if laminate is None:
            laminate = doc.addObject("App::FeaturePython", name)
            VirtualLaminateFP(laminate, laminae=layers)
        else:
            laminate.Layers = layers
        if hasattr(laminate, "Symmetry"):
            laminate.Symmetry = SymmetryType.Assymmetric.name
        return laminate

    def _sync_virtual_inputs(self, fp):
        doc = getattr(fp, "Document", None) or FreeCAD.ActiveDocument
        if doc is None:
            return
        master, attachment = self._ordered_shells(fp)
        shape = make_shape_seam(master, attachment, overlap=float(fp.Overlap))

        support_name = f"{fp.Name}_SeamSupport"
        support = doc.getObject(support_name)
        if support is None:
            support = doc.addObject("Part::Feature", support_name)
            try:
                support.Visibility = False
            except Exception:
                pass
        support.Shape = shape

        laminate = self._build_virtual_laminate(doc, fp, master, attachment)
        fp.Support = support
        fp.Laminate = laminate
        fp.Rosette = getattr(master, "Rosette", None) or getattr(attachment, "Rosette", None)

    def execute(self, fp):
        previous = getattr(self, "_initializing", False)
        self._initializing = True
        try:
            self._sync_virtual_inputs(fp)
            super().execute(fp)
        finally:
            self._initializing = previous


class ViewProviderSeam(VPCompositePart):
    def claimChildren(self):
        return []

    def getIcon(self):
        return SEAM_TOOL_ICON


class CompositeSeamCommand(BaseCommand):
    icon = SEAM_TOOL_ICON
    menu_text = "Seam"
    tool_tip = """Generate seam geometry.
        Select two part shapes or two CompositeShells."""
    sel_args = [
        {
            "key": "master",
            "type": "Part::Feature",
        },
        {
            "key": "attachment",
            "type": "Part::Feature",
        },
    ]
    type_id = "Part::FeaturePython"
    instance_name = "Seam"
    cls_fp = SeamFP
    cls_vp = ViewProviderSeam

    def _create_part_seam(self, doc, master, attachment):
        obj = doc.addObject(self.type_id, self.instance_name)
        self.cls_fp(obj, edges=[])
        obj.Master = master
        obj.Attachment = attachment
        obj.Overlap = DEFAULT_OVERLAP
        return obj

    def _create_shell_seam(self, doc, master, attachment):
        obj = doc.addObject(self.type_id, self.instance_name)
        SeamShellFP(obj, master, attachment, overlap=DEFAULT_OVERLAP)
        if FreeCADGui.ActiveDocument and getattr(obj, "ViewObject", None):
            from .VPCompositeShell import ViewProviderCompositeShell

            ViewProviderCompositeShell(obj.ViewObject)
        return obj

    def Activated(self):
        selection = self.check_sel(True)
        if selection is None:
            return

        doc = FreeCAD.ActiveDocument
        master = selection["master"]
        attachment = selection["attachment"]
        if is_composite_shell(master) and is_composite_shell(attachment):
            obj = self._create_shell_seam(doc, master, attachment)
        else:
            obj = self._create_part_seam(doc, master, attachment)
            if getattr(obj, "ViewObject", None):
                ViewProviderSeam(obj.ViewObject)

        from .Container import getCompositesContainer

        getCompositesContainer().addObject(obj)
        FreeCADGui.Selection.clearSelection()
        doc.recompute()


FreeCADGui.addCommand("Composites_Seam", CompositeSeamCommand())
