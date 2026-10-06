# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

import FreeCAD
from dataclasses import replace

from .. import (
    LAMINATE_TOOL_ICON,
    is_comp_type,
)
from ..mechanics import StackModelType
from ..objects import (
    Laminate,
    SymmetryType,
)
from ..util.bom_util import (
    get_layers_bom,
)
from ..util.fem_util import (
    get_layers_ccx,
    write_lamina_materials_ccx,
    write_shell_section_ccx,
)
from .Command import BaseCommand
from .Lamina import is_lamina
from .VPCompositeBase import (
    CompositeBaseFP,
    VPCompositeBase,
)

# import Plot
# Fem::MaterialMechanicalNonlinear
# App::DocumentObjectGroup

# from femtaskpanels import task_material_reinforced


def get_model_layers(obj):
    return [o.Proxy.get_model(o) for o in obj.Layers]


def is_laminate(obj):
    return is_comp_type(
        obj,
        "App::FeaturePython",
        "Fem::MaterialMechanicalLaminate",
    )


def is_isotropic_laminate(laminate):
    """True when the laminate declares isotropic presentation (either
    tier, PRD quasi_isotropic_laminate.md D1)."""
    if laminate is None:
        return False
    return bool(
        getattr(laminate, "IsotropicEquivalent", False)
        or getattr(laminate, "ApproximateIsotropicEquivalent", False)
    )


class LaminateFP(CompositeBaseFP):
    Type = "Fem::MaterialMechanicalLaminate"

    def __init__(self, obj, laminae=[]):
        obj.addProperty(
            "App::PropertyLinkListGlobal",
            "Layers",
            "Dimensions",
            "Link to lamina",
        ).Layers = laminae

        obj.addProperty(
            "App::PropertyEnumeration",
            "StackModelType",
            "Dimensions",
            "Representation of layers",
        )
        obj.StackModelType = [item.name for item in StackModelType]
        obj.StackModelType = StackModelType.Discrete.name

        obj.addProperty(
            "App::PropertyEnumeration",
            "Symmetry",
            "Composition",
            "Repeating stackup",
        )
        obj.Symmetry = [item.name for item in SymmetryType]
        obj.Symmetry = SymmetryType.Odd.name

        obj.addProperty(
            "App::PropertyBool",
            "IsotropicEquivalent",
            "Composition",
            "Declare exact quasi-isotropic presentation; the stack must "
            "satisfy the QI balance conditions to round-off (validated "
            "loudly) and FEM export collapses to one isotropic material",
        )
        obj.IsotropicEquivalent = False

        obj.addProperty(
            "App::PropertyBool",
            "ApproximateIsotropicEquivalent",
            "Composition",
            "Declare approximate quasi-isotropic presentation; passes only "
            "within the residual budget and the deviation is recorded",
        )
        obj.ApproximateIsotropicEquivalent = False

        obj.addProperty(
            "App::PropertyMap",
            "ApproximateIsotropicResiduals",
            "Composition",
            "Recorded balance residuals of the approximate presentation",
        )
        obj.setPropertyStatus("ApproximateIsotropicResiduals", "ReadOnly")
        obj.ApproximateIsotropicResiduals = {}

        obj.addProperty(
            "App::PropertyMap",
            "StackOrientation",
            "Composition",
            "Orientation of layers in stack",
            hidden=True,
        ).StackOrientation = {}

        obj.addProperty(
            "App::PropertyLength",
            "Thickness",
            "Dimensions",
            "Thickness of laminate",
        )
        obj.setPropertyStatus("Thickness", "ReadOnly")

        super().__init__(obj)

        # Attach ViewProvider so it persists in the saved document.
        vobj = obj.ViewObject
        if vobj is not None:
            vobj.Proxy = ViewProviderLaminate(vobj)

        # obj.addProperty(
        #     "App::PropertyPythonObject",
        #     "FEMLayers",
        #     "Dimensions",
        #     "FEM representation of layers",
        #     0,
        #     True,
        # ).FEMLayers = []

    def execute(self, obj):
        laminate = self.get_model(obj)

        if not hasattr(obj, "StackModelType"):
            return

        try:
            self.FEMLayers = get_layers_ccx(
                laminate=laminate,
                model_type=StackModelType[obj.StackModelType],
            )
            obj.StackOrientation = {
                o.material["Name"]: f"{int(o.orientation_display):+03d}"
                for o in self.FEMLayers
            }
            if laminate:
                obj.Thickness = FreeCAD.Units.Quantity(laminate.thickness)
                obj.ApproximateIsotropicResiduals = (
                    {
                        name: f"{residual:.6g}"
                        for name, residual in laminate.qi_residuals.items()
                    }
                    if obj.ApproximateIsotropicEquivalent
                    else {}
                )
            else:
                obj.Thickness = FreeCAD.Units.Quantity(0.0)
        except Exception as exc:
            # Loud-failure contract (PRD §5.3): record the reason and
            # surface the error so the feature shows as in error — never
            # a silently pseudo-isotropic export.
            self.last_error = str(exc)
            raise
        self.last_error = None

    def get_stack_assembly(self, obj):
        laminate = self.get_model(obj)
        return get_layers_bom(laminate=laminate)

    def onChanged(self, fp, prop):
        match prop:
            case "Layers":
                fp.recompute()

    def is_isotropic(self, obj):
        """Whether the deck writes this laminate as one smeared isotropic layer.

        Part of the laminate's deck contract next to fem_layers, so a
        consumer of the written deck - an audit, a mass tally - can ask the
        laminate instead of importing the writer, which drags in the whole
        workbench and cannot be done outside a running FreeCAD.
        """
        return is_isotropic_laminate(obj)

    def fem_layers(self, obj):
        """The stack as ccx should see it, merged by the stack model type.

        FEMLayers is built in execute(), so a document reopened from disk
        has none — nothing is touched, so nothing runs — and the solver
        writer then died on the missing attribute.  Deriving it here means
        the deck representation cannot be stale or absent without saying
        so.
        """
        layers = getattr(self, "FEMLayers", None)
        if not layers:
            obj.recompute()
            layers = getattr(self, "FEMLayers", None)
        if not layers:
            reason = ": %s" % self.last_error if self.last_error else ""
            raise ValueError(
                "%s: no FEM layer representation for the %s stack model%s"
                % (obj.Name, obj.StackModelType, reason)
            )
        return layers

    def get_materials(self, obj):
        return write_lamina_materials_ccx(
            prefix=obj.Name,
            layers=self.fem_layers(obj),
        )

    def deck_layers(self, obj):
        """The layers the deck presents, as the writer emits them.

        A single merged (CLT-collapsed) orthotropic layer cannot be decked
        as a one-layer COMPOSITE section: the solver cannot expand that
        presentation (measured heap corruption, §7.6 plate, 2026-10-07;
        the same deck with the layer split in two solves).  The deck
        therefore presents it as two stacked half-thickness layers of the
        same material — identical ABD by construction.  This accessor is
        the one definition of that rule: the section writer uses it, and
        the deck audit checks the deck against it, so neither can drift
        from the other.
        """
        layers = self.fem_layers(obj)
        if len(layers) == 1 and not is_isotropic_laminate(obj):
            return [replace(layers[0], thickness=layers[0].thickness / 2)
                    for _ in range(2)]
        return layers

    def write_shell_section(self, obj):
        return write_shell_section_ccx(
            prefix=obj.Name,
            layers=self.deck_layers(obj),
        )

    def get_model(self, obj) -> Laminate:
        if model_layers := get_model_layers(obj):
            return self.make_model(obj, model_layers)
        return None  # noqa

    def make_model(self, obj, model_layers):
        return Laminate(
            symmetry=SymmetryType[obj.Symmetry],
            layers=model_layers,
            isotropic_equivalent=obj.IsotropicEquivalent,
            approximate_isotropic_equivalent=(
                obj.ApproximateIsotropicEquivalent
            ),
        )


class ViewProviderLaminate(VPCompositeBase):
    def getIcon(self):
        return LAMINATE_TOOL_ICON

    def updateData(self, vobj, prop):
        pass

    def claimChildren(self):
        if not getattr(self, "Object", None):
            return []
        layers = self.Object.Layers if hasattr(self.Object, "Layers") else []
        return [l for l in layers if l is not None]


class LaminateCommand(BaseCommand):
    icon = LAMINATE_TOOL_ICON
    menu_text = "Laminate"
    tool_tip = """Create laminate.
        Select laminae."""
    type_id = "App::FeaturePython"
    instance_name = "LaminatedShell"
    cls_fp = LaminateFP
    cls_vp = ViewProviderLaminate

    sel_args = [
        {
            "key": "laminae",
            "test": is_lamina,
            "array": True,
            "optional": True,
        },
    ]


# Command registration moved to InitGui.py to avoid FreeCADGui dependency


# The ViewProvider class that repairs this feature's serialised VP
# proxy on document restore (see CompositeBaseFP.onDocumentRestored).
LaminateFP.view_provider_class = ViewProviderLaminate
