# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Seam extraction — generates overlap geometry from master/attachment."""

from __future__ import annotations

import FreeCAD

from .. import SEAM_TOOL_ICON
from ..tools.seam_extraction import extract_seam
from .Command import BaseCommand
from .CompositeShell import CompositeShellFP, is_composite_shell
from .VPCompositeBase import CompositeBaseFP
from .Laminate import LaminateFP
from .VPCompositePart import VPCompositePart


SEAM_WIDTH_DEFAULT = "10.0 mm"


class VirtualLaminateFP(LaminateFP):
    def execute(self, obj):
        return


class SeamFP(CompositeBaseFP):
    """Document object holding seam extraction results for Part::Feature inputs."""

    def __init__(self, obj):
        super().__init__(obj)

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Master",
            "References",
            "Master surface (face or compound)",
        )

        obj.addProperty(
            "App::PropertyLinkGlobal",
            "Attachment",
            "References",
            "Attachment surface (face or compound)",
        )

        obj.addProperty(
            "App::PropertyLength",
            "Width",
            "Dimension",
            "Desired seam width in mm",
        ).Width = SEAM_WIDTH_DEFAULT

        obj.addProperty(
            "App::PropertyLink",
            "Seam",
            "Results",
            "Extracted seam surface (read-only)",
        )

        obj.addProperty(
            "App::PropertyLink",
            "Remainder",
            "Results",
            "Remaining attachment geometry (read-only)",
        )

        obj.Proxy = self

        # Attach ViewProvider so it persists in the saved document.
        try:
            vobj = obj.ViewObject
            if vobj is not None:
                vobj.Proxy = ViewProviderSeamExtraction(vobj)
        except Exception:
            pass

    def execute(self, fp):
        if fp.Master is None or fp.Attachment is None:
            return

        try:
            result = extract_seam(fp.Master, fp.Attachment, float(fp.Width))
        except Exception as exc:
            FreeCAD.Console.PrintError(f"Seam extraction failed: {exc}\n")
            return

        if not result.get("success"):
            FreeCAD.Console.PrintError(
                f"Seam extraction failed: {result.get('error', 'unknown')}\n"
            )
            return

        doc = fp.Document
        if doc is None:
            return

        # Seam surface
        seam_feat = doc.getObject(f"{fp.Name}_SeamSurface")
        if seam_feat is None:
            seam_feat = doc.addObject("Part::Feature", f"{fp.Name}_SeamSurface")
        seam_feat.Shape = result["seam"]
        seam_feat.Label = f"{fp.Label} Seam"
        fp.Seam = seam_feat

        # Remainder
        rem_feat = doc.getObject(f"{fp.Name}_Remainder")
        if rem_feat is None:
            rem_feat = doc.addObject("Part::Feature", f"{fp.Name}_Remainder")
        rem_feat.Shape = result["remainder"]
        rem_feat.Label = f"{fp.Label} Remainder"
        fp.Remainder = rem_feat


class SeamGeometryFP(CompositeShellFP):
    """Composite shell holding seam geometry and laminate context.

    Created by SeamShellFP as a child object.  execute()
    is overridden to no-op so the shell never attempts a drape solve.
    """

    Type = "Composite::Shell"

    def __init__(self, obj, doc):
        super().__init__(obj, support=None, laminate=None, rosette=None)

    def execute(self, fp):
        """Override to prevent drape solves on seam result shells."""
        pass

    def onDocumentRestored(self, fp):
        """Nothing to restore — shape lives on fp itself."""
        pass

    def update(self, fp, shape, laminate, rosette):
        """Update the seam shell with new geometry and material data."""
        fp.Shape = shape
        fp.Laminate = laminate
        fp.Rosette = rosette


class SeamShellFP(CompositeShellFP):
    """Seam extraction for CompositeShell inputs."""

    def __init__(
        self,
        obj,
        master,
        attachment,
        seam_width=SEAM_WIDTH_DEFAULT,
    ):
        super().__init__(obj, support=None, laminate=None, rosette=None)

        # Replace inherited ViewProviderCompositeShell with the seam-specific one.
        try:
            vobj = obj.ViewObject
            if vobj is not None:
                vobj.Proxy = ViewProviderSeamExtraction(vobj)
        except Exception:
            pass

        # Seam must be registered before any property that triggers
        # onChanged callbacks (Master / Attachment / Width), because
        # _sync_virtual_inputs assigns to fp.Seam during init.
        obj.addProperty(
            "App::PropertyLink",
            "Seam",
            "Results",
            "Extracted seam composite shell",
        )
        obj.addProperty(
            "App::PropertyLink",
            "Remainder",
            "Results",
            "Remaining attachment geometry after seam extraction",
        )

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
            "App::PropertyLength",
            "Width",
            "Dimension",
            "Desired seam width in mm",
            locked=True,
        ).Width = seam_width

        previous = getattr(self, "_initializing", False)
        self._initializing = True
        try:
            self._sync_virtual_inputs(obj)
        finally:
            self._initializing = previous

    def execute(self, fp):
        """Run seam extraction when Master/Attachment change."""
        if fp.Master is None or fp.Attachment is None:
            return
        self._sync_virtual_inputs(fp)

    def onChanged(self, fp, prop):
        if getattr(self, "_initializing", False):
            return
        if prop in {"Master", "Attachment", "Width"}:
            # Guard against being called before all properties are registered
            if not all(hasattr(fp, p) for p in ("Master", "Attachment", "Width")):
                return
            self._sync_virtual_inputs(fp)
            return
        super().onChanged(fp, prop)

    def _hide_object(self, obj):
        try:
            obj.Visibility = False
        except Exception:
            view_object = getattr(obj, "ViewObject", None)
            if view_object is not None:
                view_object.Visibility = False

    def _build_seam_shell(self, doc, fp, master, attachment, shape, remainder=None):
        """Create or update the SeamGeometryFP child object."""
        name = f"{fp.Name}_Seam"
        seam_shell = doc.getObject(name)
        if seam_shell is None:
            seam_shell = doc.addObject("Part::FeaturePython", name)
            SeamGeometryFP(seam_shell, doc)
            self._hide_object(seam_shell)

        laminate = self._build_virtual_laminate(doc, fp, master, attachment)
        rosette = getattr(master, "Rosette", None) or getattr(
            attachment, "Rosette", None
        )
        seam_shell.Proxy.update(seam_shell, shape, laminate, rosette)

        fp.Seam = seam_shell

        # Remainder
        if remainder is not None:
            rem_name = f"{fp.Name}_Remainder"
            rem_feat = doc.getObject(rem_name)
            if rem_feat is None:
                rem_feat = doc.addObject("Part::FeaturePython", rem_name)
                SeamGeometryFP(rem_feat, doc)
                self._hide_object(rem_feat)
            att_rosette = getattr(attachment, "Rosette", None)
            rem_feat.Proxy.update(rem_feat, remainder, laminate, att_rosette)
            fp.Remainder = rem_feat

        return seam_shell

    def _build_virtual_laminate(self, doc, fp, master, attachment):
        layers = list(getattr(master.Laminate, "Layers", []) or [])
        layers.extend(list(getattr(attachment.Laminate, "Layers", []) or []))

        name = f"{fp.Name}_VirtualLaminate"
        laminate = doc.getObject(name)
        if laminate is None:
            laminate = doc.addObject("App::FeaturePython", name)
            VirtualLaminateFP(laminate, laminae=layers)
        else:
            laminate.Layers = layers
        self._hide_object(laminate)
        return laminate

    def _sync_virtual_inputs(self, fp):
        doc = getattr(fp, "Document", None) or FreeCAD.ActiveDocument
        if doc is None:
            return

        previous = getattr(self, "_initializing", False)
        self._initializing = True
        try:
            master, attachment = fp.Master, fp.Attachment
            if not is_composite_shell(master) or not is_composite_shell(attachment):
                return

            result = extract_seam(master, attachment, float(fp.Width))
            if not result.get("success"):
                return

            shape = result["seam"]
            remainder = result.get("remainder")
            self._build_seam_shell(doc, fp, master, attachment, shape, remainder)
        finally:
            self._initializing = previous

    def execute(self, fp):
        previous = getattr(self, "_initializing", False)
        self._initializing = True
        try:
            self._sync_virtual_inputs(fp)
        finally:
            self._initializing = previous


class ViewProviderSeamExtraction(VPCompositePart):
    def __init__(self, vobj):
        super().__init__(vobj)
        self.attach(vobj)

    def claimChildren(self):
        children = []
        fp = self.Object
        seam = getattr(fp, "Seam", None)
        if seam is not None:
            children.append(seam)
        remainder = getattr(fp, "Remainder", None)
        if remainder is not None:
            children.append(remainder)
        virtual_lam = getattr(fp.Document, "getObject", lambda n: None)(
            f"{fp.Name}_VirtualLaminate"
        )
        if virtual_lam is not None:
            children.append(virtual_lam)
        return children

    def getIcon(self):
        return SEAM_TOOL_ICON


class CompositeSeamExtractionCommand(BaseCommand):
    """Command to extract seam geometry between master and attachment."""

    icon = SEAM_TOOL_ICON
    menu_text = "Seam Extraction"
    tool_tip = (
        "Generate seam overlap geometry between two panels. "
        "Select a master and attachment panel to create the seam."
    )
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
    instance_name = "SeamExtraction"
    cls_fp = SeamFP
    cls_vp = ViewProviderSeamExtraction

    def _create_part_extraction(self, doc, master, attachment):
        obj = doc.addObject(self.type_id, self.instance_name)
        SeamFP(obj)
        obj.Master = master
        obj.Attachment = attachment
        obj.Width = SEAM_WIDTH_DEFAULT
        return obj

    def _create_shell_extraction(self, doc, master, attachment):
        obj = doc.addObject(self.type_id, self.instance_name)
        SeamShellFP(obj, master, attachment, seam_width=SEAM_WIDTH_DEFAULT)
        return obj

    def Activated(self):
        selection = self.check_sel(True)
        if selection is None:
            return

        doc = FreeCAD.ActiveDocument
        master = selection["master"]
        attachment = selection["attachment"]
        if is_composite_shell(master) and is_composite_shell(attachment):
            obj = self._create_shell_extraction(doc, master, attachment)
        else:
            obj = self._create_part_extraction(doc, master, attachment)

        if getattr(obj, "ViewObject", None):
            ViewProviderSeamExtraction(obj.ViewObject)

        from .Container import getCompositesContainer

        getCompositesContainer().addObject(obj)
        import FreeCADGui

        FreeCADGui.Selection.clearSelection()
        doc.recompute()


# Command registration moved to InitGui.py to avoid FreeCADGui dependency