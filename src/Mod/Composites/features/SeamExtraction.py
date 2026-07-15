# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Seam extraction — generates overlap geometry from master/attachment."""

from __future__ import annotations

import FreeCAD

from .. import SEAM_TOOL_ICON
from ..tools.seam_extraction import extract_seam
from ..util.geometry_util import shape_fingerprint
from .Command import BaseCommand
from .CompositeShell import CompositeShellFP, is_composite_shell
from .TransferRosette import (
    TransferRosetteFP,
    ViewProviderTransferRosette,
)
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

    Created by SeamShellFP as a child object.  The execute() method is
    overridden to skip drape solves when the shape hasn't changed,
    avoiding redundant expensive draping.
    """

    Type = "Composite::Shell"

    def __init__(self, obj, doc):
        super().__init__(obj, support=None, laminate=None, rosette=None)

    def _shape_fingerprint(self, shape) -> str:
        """Delegate to shared geometry_util function."""
        return shape_fingerprint(shape)

    def execute(self, fp):
        """Skip drape solve when the support shape hasn't changed."""
        if not fp.Support:
            return
        # Check if the support shape changed since last solve.
        current_fp = self._shape_fingerprint(fp.Support.Shape)
        stored_fp = getattr(self, "_last_shape_fingerprint", None)
        if stored_fp and stored_fp == current_fp:
            return  # No change — skip drape solve.
        self._last_shape_fingerprint = current_fp
        # Delegate to parent execute (runs the drape solve).
        super().execute(fp)

    def onDocumentRestored(self, fp):
        """Nothing to restore — shape lives on fp itself."""
        pass

    def update(self, fp, shape, laminate, rosette):
        """Update the seam shell with new geometry and material data."""
        fp.Shape = shape
        # Create a hidden support shape so CompositeShell.execute() can drape.
        sup_name = f"{fp.Name}_Support"
        sup = fp.Document.getObject(sup_name)
        if sup is None:
            sup = fp.Document.addObject("Part::Feature", sup_name)
            try:
                sup.Visibility = False
            except Exception:
                pass
        sup.Shape = shape
        fp.Support = sup
        fp.Laminate = laminate
        fp.Rosette = rosette
        self._recenter_lcs(shape, rosette)

    @staticmethod
    def _recenter_lcs(shape, rosette):
        """Move rosette LCS to the shape centroid."""
        if rosette is None:
            return
        lcs = getattr(rosette, "LocalCoordinateSystem", None)
        if lcs is None:
            return
        try:
            bb = shape.BoundBox
            cx = bb.XMin + bb.XLength / 2.0
            cy = bb.YMin + bb.YLength / 2.0
            cz = bb.ZMin + bb.ZLength / 2.0
            lcs.Placement = FreeCAD.Placement(
                FreeCAD.Vector(cx, cy, cz), lcs.Placement.Rotation
            )
        except Exception:
            pass


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
        """Create or update the SeamGeometryFP child object.

        Creates a TransferRosette whose angle is solved to match the master
        shell's warp direction at the seam boundary.  The solved rosette is
        wired into the seam shell so the seam shell's drape uses the correct
        fibre orientation.
        """
        name = f"{fp.Name}_Seam"
        seam_shell = doc.getObject(name)
        if seam_shell is None:
            seam_shell = doc.addObject("Part::FeaturePython", name)
            SeamGeometryFP(seam_shell, doc)
            self._hide_object(seam_shell)

        laminate = self._build_virtual_laminate(doc, fp, master, attachment)

        # --- seam shell rosette via TransferRosette ---------------------------
        self._wire_transfer_rosette_for(doc, fp, master, seam_shell, "Seam")
        seam_rosette = getattr(seam_shell, "Rosette", None)
        seam_shell.Proxy.update(seam_shell, shape, laminate, seam_rosette)

        fp.Seam = seam_shell

        # Remainder
        if remainder is not None:
            rem_name = f"{fp.Name}_Remainder"
            rem_feat = doc.getObject(rem_name)
            if rem_feat is None:
                rem_feat = doc.addObject("Part::FeaturePython", rem_name)
                SeamGeometryFP(rem_feat, doc)
                self._hide_object(rem_feat)

            self._wire_transfer_rosette_for(
                doc, fp, attachment, rem_feat, "Remainder"
            )
            rem_rosette = getattr(rem_feat, "Rosette", None)
            rem_feat.Proxy.update(rem_feat, remainder, laminate, rem_rosette)
            fp.Remainder = rem_feat

        return seam_shell

    def _wire_transfer_rosette_for(
        self, doc, fp, source_shell, target_shell, label_suffix
    ):
        """Wire a rosette to *target_shell* copied from *source_shell*.

        The target shell inherits the source shell's rosette angle so the
        seam/remainder shells have a sensible fibre orientation.
        """
        source_ros = getattr(source_shell, "Rosette", None)
        if source_ros is None:
            return

        # Create a new rosette on the target shell with the same angle.
        from .Rosette import RosetteFP

        name = f"{fp.Name}_{label_suffix}_Rosette"
        ros = doc.getObject(name)
        if ros is None:
            ros = doc.addObject("Part::FeaturePython", name)
            RosetteFP(ros)
            ros.Angle = source_ros.Angle
            self._hide_object(ros)
        else:
            ros.Angle = source_ros.Angle

        target_shell.Rosette = ros

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

    def _input_fingerprint(self, fp) -> str:
        """Hash the seam extraction inputs so we can skip when they haven't changed."""
        import hashlib
        master = fp.Master
        attachment = fp.Attachment
        width = fp.Width
        parts = []
        if master is not None:
            parts.append(getattr(master, "Name", ""))
        if attachment is not None:
            parts.append(getattr(attachment, "Name", ""))
        parts.append(str(width))
        h = hashlib.sha256()
        for p in parts:
            h.update(str(p).encode())
        return h.hexdigest()

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

            # Skip extraction when inputs haven't changed.
            current_fp = self._input_fingerprint(fp)
            stored_fp = getattr(self, "_last_input_fingerprint", None)
            if stored_fp is not None and current_fp == stored_fp:
                return
            self._last_input_fingerprint = current_fp

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