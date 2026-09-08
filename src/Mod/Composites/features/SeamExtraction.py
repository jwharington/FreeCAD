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
from .Rosette import RosetteFP
from .SeamCompositeLaminate import SeamCompositeLaminateFP
from .TransferRosette import (
    AnalysisTransferRosetteFP,
    TransferRosetteFP,
    ViewProviderTransferRosette,
)
from .VPCompositeBase import CompositeBaseFP
from .Laminate import LaminateFP
from .VPCompositePart import VPCompositePart


SEAM_WIDTH_DEFAULT = "10.0 mm"

# Number of sample points along the shared boundary edge (mirrors
# TransferRosette).
_EDGE_SAMPLES = 8


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
        """Skip drape solve when the drape inputs haven't changed.

        The fingerprint covers the support shape AND the drape seed
        (rosette angle + LCS placement): the transfer solves iterate the
        rosette angle and re-drape the seam shell each iteration — with a
        shape-only fingerprint the draper would freeze at the bootstrap
        angle and the solve would return garbage.
        """
        if not fp.Support:
            return
        current_fp = self._shape_fingerprint(fp.Support.Shape)
        rosette = getattr(fp, "Rosette", None)
        if rosette is not None:
            current_fp += f"|angle:{float(rosette.Angle):.6f}"
            lcs = getattr(rosette, "LocalCoordinateSystem", None)
            if lcs is not None:
                q = lcs.Placement.Rotation.Q
                current_fp += "|lcs:" + ",".join(f"{v:.6f}" for v in q)
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

        # Original attachment support, captured before the attachment is
        # re-supported on the remainder.  Extraction must keep using this
        # geometry: once the attachment shell is re-supported, its
        # Support.Shape is the remainder and re-extracting from it would
        # be garbage.  Registered BEFORE the inputs: Width's onChanged
        # can drive the first extraction during __init__, and the
        # remainder block must see this property already in place.
        obj.addProperty(
            "App::PropertyLinkGlobal",
            "AttachmentBase",
            "References",
            "Original attachment support (captured pre-seam)",
        )

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

        The seam shell's rosette is a *solved* TransferRosette
        (master → seam): its angle gives warp continuity across the
        master–seam edge, and it seeds the seam shell's drape.  A second,
        analysis-only rosette is solved against the attachment's warp at
        the attachment–seam edge.  Both solved angles feed the
        SeamCompositeLaminate, which replaces the naive virtual laminate
        as the seam shell's Laminate (docs/seam_composite_laminate.md,
        ADR-0001).
        """
        name = f"{fp.Name}_Seam"
        seam_shell = doc.getObject(name)
        if seam_shell is None:
            seam_shell = doc.addObject("Part::FeaturePython", name)
            SeamGeometryFP(seam_shell, doc)
            self._hide_object(seam_shell)
        # The seam strip's narrow dimension is the seam width; the
        # default drape pitch (20 mm) can exceed it, and a lattice that
        # cannot fit one cell across the width fails to drape at most
        # seed angles.  Scale the pitch to the strip.
        try:
            seam_pitch = max(0.5, min(20.0, float(fp.Width) / 4.0))
            if abs(float(seam_shell.DrapePitch) - seam_pitch) > 1e-9:
                seam_shell.DrapePitch = seam_pitch
        except Exception:
            pass

        # Bootstrap: the transfer solves iterate the seam shell's drape,
        # which needs a Laminate before the SeamCompositeLaminate exists.
        # The attachment's own laminate is the physically correct
        # stand-in — the seam region is part of the attachment surface.
        bootstrap = getattr(attachment, "Laminate", None)
        if bootstrap is None:
            bootstrap = self._build_virtual_laminate(doc, fp, master, attachment)
        seam_shell.Proxy.update(seam_shell, shape, bootstrap, None)

        master_transfer = self._wire_seam_master_transfer(
            doc, fp, master, seam_shell
        )
        attachment_transfer = self._wire_seam_analysis_rosette(
            doc, fp, seam_shell, attachment
        )

        scl = self._build_seam_composite_laminate(
            doc, fp, master, attachment, seam_shell,
            master_transfer, attachment_transfer,
        )

        seam_shell.Proxy.update(seam_shell, shape, scl, master_transfer)
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
            # The remainder carries the attachment's OWN laminate — the
            # master's plies lie on the attachment only within the
            # overlap (the seam region), so the combined stack never
            # applies here (ADR-0001 boundary decision).
            rem_laminate = getattr(attachment, "Laminate", None)
            rem_feat.Proxy.update(rem_feat, remainder, rem_laminate, rem_rosette)
            fp.Remainder = rem_feat

            # Weave exclusivity: the seam region carries the combined
            # stack, so the attachment's plies exist only on the
            # remainder.  Re-supporting the attachment shell on the
            # remainder geometry makes its weave exclusive of the seam
            # region by construction (no render-path clipping needed).
            # The pre-seam geometry is preserved in AttachmentBase and
            # drives future extractions.
            if "AttachmentBase" in fp.PropertiesList and \
                    getattr(fp, "AttachmentBase", None) is None:
                fp.AttachmentBase = attachment.Support
            if "AttachmentBase" in fp.PropertiesList and \
                    attachment.Support is not rem_feat.Support:
                attachment.Support = rem_feat.Support

        return seam_shell

    def _wire_transfer_rosette_for(
        self, doc, fp, source_shell, target_shell, label_suffix
    ):
        """Wire a rosette to *target_shell* copied from *source_shell*.

        Used for the remainder shell, which is a piece of the attachment
        surface: copying the attachment's rosette angle is correct there
        (same surface frame, no edge crossing).  The seam shell itself
        uses solved transfers instead (see _wire_seam_master_transfer).
        """
        source_ros = getattr(source_shell, "Rosette", None)
        if source_ros is None:
            return

        name = f"{fp.Name}_{label_suffix}_Rosette"
        ros = doc.getObject(name)
        if ros is None:
            ros = doc.addObject("Part::FeaturePython", name)
            RosetteFP(ros)
            self._hide_object(ros)
        ros.Angle = source_ros.Angle
        target_shell.Rosette = ros

    def _seam_support_sub(self, seam_shell):
        """Support link-sub for rosettes placed on the seam surface."""
        return (seam_shell.Support, ["Face1"])

    def _wire_seam_master_transfer(self, doc, fp, master, seam_shell):
        """Create/update the solved TransferRosette master → seam.

        The TransferRosette constructor runs the warp-continuity solve
        and wires itself as the seam shell's Rosette, seeding the seam
        shell's drape with the master's fibre direction at the seam
        boundary.
        """
        name = f"{fp.Name}_SeamMasterTransfer"
        transfer = doc.getObject(name)
        if transfer is None:
            transfer = doc.addObject("Part::FeaturePython", name)
            TransferRosetteFP(
                transfer,
                support=self._seam_support_sub(seam_shell),
                master_shell=master,
                attachment_shell=seam_shell,
            )
            self._hide_object(transfer)
        return transfer

    def _wire_seam_analysis_rosette(self, doc, fp, seam_shell, attachment):
        """Create/update the solved attachment → seam analysis rosette.

        Analysis-only (ADR-0001): it translates the attachment's lamina
        directions into the seam's frame at the attachment's edge.  It is
        a standalone :class:`AnalysisTransferRosetteFP` — it never
        becomes the seam shell's Rosette, which belongs to the
        master→seam transfer.  The constructor runs the solve.
        """
        name = f"{fp.Name}_SeamAttachmentTransfer"
        rosette = doc.getObject(name)
        if rosette is None:
            rosette = doc.addObject("Part::FeaturePython", name)
            AnalysisTransferRosetteFP(
                rosette,
                support=self._seam_support_sub(seam_shell),
                master_shell=attachment,
                attachment_shell=seam_shell,
            )
            self._hide_object(rosette)
        return rosette

    def _build_seam_composite_laminate(
        self, doc, fp, master, attachment, seam_shell,
        master_transfer, attachment_transfer,
    ):
        """Create/update the SeamCompositeLaminate on the seam shell.

        Replaces the naive virtual laminate: combined stack per the
        selected model, per-ply angles from the two solved transfer
        rosettes.
        """
        name = f"{fp.Name}_SeamCompositeLaminate"
        scl = doc.getObject(name)
        if scl is None:
            scl = doc.addObject("App::FeaturePython", name)
            SeamCompositeLaminateFP(scl)
            self._hide_object(scl)
            # Migrate documents that still carry the naive virtual
            # laminate: hide the orphan.
            old = doc.getObject(f"{fp.Name}_VirtualLaminate")
            if old is not None:
                self._hide_object(old)
        scl.Master = master
        scl.Attachment = attachment
        scl.SeamRegion = seam_shell
        scl.MasterTransfer = master_transfer
        scl.AttachmentTransfer = attachment_transfer
        scl.ResinMaterial = self._side_resin(master, attachment)
        scl.recompute()
        return scl

    @staticmethod
    def _side_resin(master, attachment):
        """Resin fallback for fabric plies, taken from either side."""
        for side in (master, attachment):
            lam = getattr(side, "Laminate", None)
            resin = getattr(lam, "ResinMaterial", None)
            if resin:
                return resin
        return {}

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
        attachment_base = getattr(fp, "AttachmentBase", None)
        for shell in (master, attachment):
            if shell is None:
                parts.append("None")
                continue
            parts.append(getattr(shell, "Name", ""))
            # The attachment's extraction input is its captured base
            # geometry, not the re-pointed (remainder) support.
            if shell is attachment and attachment_base is not None:
                support = attachment_base
            else:
                support = getattr(shell, "Support", None)
            shape = getattr(support, "Shape", None)
            if shape is not None:
                try:
                    from ..util.geometry_util import shape_fingerprint

                    parts.append(shape_fingerprint(shape))
                except Exception:
                    parts.append("shape-error")
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

            # Extract from the live SUPPORT geometry: a draped shell's
            # own .Shape is the drape output, not the mould surface
            # (known-issues #6 stale-shape trap).  The attachment side
            # uses the captured base geometry — after the first
            # extraction the attachment is re-supported on the
            # remainder, which must never be re-extracted.
            attachment_src = getattr(fp, "AttachmentBase", None) or attachment
            result = extract_seam(
                TransferRosetteFP._shape_of(master),
                TransferRosetteFP._shape_of(attachment_src),
                float(fp.Width),
            )
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
        scl = getattr(fp.Document, "getObject", lambda n: None)(
            f"{fp.Name}_SeamCompositeLaminate"
        )
        if scl is not None:
            children.append(scl)
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