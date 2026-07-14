# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

# ── ARCHITECTURE: C++ extension loading ─────────────────────────
# The Composites_drape.so library (nextdrape solver + seam extraction)
# is installed to FreeCAD's lib/ directory and loaded via standard
# Python import (`import Composites_drape`). This matches the pattern
# used by Fem, Part, and Materials workbenches.
#
# DO NOT use importlib.util.spec_from_file_location or nest the .so
# in a subdirectory (e.g. ext/_native/). The old custom loader caused
# interpreter-shutdown crashes because modules created via
# spec_from_file_location are not properly registered in sys.modules,
# leading to double-free and cleanup-order bugs.
#
# See CMakeLists.txt for build/install configuration and InitGui.py
# for the workbench activation import.

import os
from os import path

import FreeCAD

from .resources.colormaps.roma import roma_map
from .version import __version__  # noqa

debug = False


MODULE_PATH = os.path.dirname(__file__)
ICONPATH = os.path.join(MODULE_PATH, "resources", "icons")
UIPATH = os.path.join(MODULE_PATH, "resources", "ui")
MATPATH = os.path.join(MODULE_PATH, "resources", "materials")

TEXTURE_PLAN_TOOL_ICON = path.join(ICONPATH, "TexturePlan.svg")
MOULD_TOOL_ICON = path.join(ICONPATH, "Mould.svg")
PART_PLANE_TOOL_ICON = path.join(ICONPATH, "PartPlane.svg")
SEAM_TOOL_ICON = path.join(ICONPATH, "Seam.svg")
STIFFENER_TOOL_ICON = path.join(ICONPATH, "Stiffener.svg")
DART_TOOL_ICON = path.join(ICONPATH, "Dart.svg")

LAMINATE_TOOL_ICON = path.join(ICONPATH, "Laminate.svg")
COMPOSITE_LAMINATE_TOOL_ICON = path.join(
    ICONPATH,
    "CompositeLaminate.svg",
)
HOMOGENEOUS_LAMINA_TOOL_ICON = path.join(
    ICONPATH,
    "HomogeneousLamina.svg",
)
FIBRE_COMPOSITE_LAMINA_TOOL_ICON = path.join(
    ICONPATH,
    "FibreCompositeLamina.svg",
)
COMPOSITE_SHELL_TOOL_ICON = path.join(ICONPATH, "CompositeShell.svg")
TRANSFER_ROSETTE_TOOL_ICON = path.join(ICONPATH, "TransferRosette.svg")
ALIGN_FIBRE_ROSETTE_TOOL_ICON = path.join(ICONPATH, "AlignFibreRosette.svg")
ROSETTE_TOOL_ICON = path.join(ICONPATH, "Rosette.svg")
WB_ICON = path.join(ICONPATH, "CompositesWB.svg")


TOL3D = 1e-7
TOL2D = 1e-9
if hasattr(FreeCAD.Base, "Precision"):
    TOL3D = FreeCAD.Base.Precision.confusion()
    TOL2D = FreeCAD.Base.Precision.parametric(TOL3D)

# Add materials to the user config dir
material_base = "BaseApp/Preferences/Mod/Material/Resources/Modules"
materials = FreeCAD.ParamGet("User parameter:{material_base}/Composites")
materials.SetString(
    "ModuleIcon",
    COMPOSITE_LAMINATE_TOOL_ICON,
)
materials.SetString("ModuleDir", MATPATH)
# materials.SetString("ModuleModelDir", moddir)

# FreeCAD.addImportType("My own format (*.own)", "importOwn")
# FreeCAD.addExportType("My own format (*.own)", "exportOwn")


def is_comp_type(obj, type_id, proxy_type):
    if obj.TypeId != type_id:
        return False
    if not hasattr(obj, "Proxy"):
        return False
    if not obj.Proxy:
        return False
    if not hasattr(obj.Proxy, "Type"):
        return False
    if obj.Proxy.Type != proxy_type:
        return False
    return True


# Register optional composite-specific FEM extensions if available.
try:
    from .fem.drape_laminate_provider import register_drape_laminate_providers
    from .fem.failure_models_composites import register_composite_failure_models

    register_composite_failure_models()
    register_drape_laminate_providers()
except Exception:
    # Keep Composites WB load robust even when FEM extension registries are unavailable.
    pass


FreeCAD.__unit_test__ += ["TestCompositesApp"]
