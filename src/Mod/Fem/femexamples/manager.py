# ***************************************************************************
# *   Copyright (c) 2019 Bernd Hahnebach <bernd@bimstatik.org>              *
# *   Copyright (c) 2020 Sudhanshu Dubey <sudhanshu.thethunder@gmail.com>   *
# *                                                                         *
# *   This file is part of the FreeCAD CAx development system.              *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import FreeCAD

_DIRECTION_COMPAT_WARNED = False
_REVERSED_COMPAT_WARNED = False
_PRIMITIVE_DIRECTION_WARNED = False
_DIRECTION_FALLBACK_OBJECT_IDS = set()
_DIRECTION_FALLBACK_REFS = {}


def _is_primitive_direction_object(obj):
    type_id = getattr(obj, "TypeId", "")
    return type_id.startswith("Part::") and type_id != "Part::Feature"


def _first_subname(direction_ref):
    if not isinstance(direction_ref, (list, tuple)) or len(direction_ref) != 2:
        return ""
    _, sub = direction_ref
    if isinstance(sub, str):
        return sub
    if isinstance(sub, (list, tuple)):
        for name in sub:
            if name:
                return name
    return ""


def _direction_shape(direction_ref):
    if not isinstance(direction_ref, (list, tuple)) or len(direction_ref) != 2:
        return None
    obj, _ = direction_ref
    shape = getattr(obj, "Shape", None)
    if shape is None:
        return None

    subname = _first_subname(direction_ref)
    if subname:
        try:
            return shape.getElement(subname)
        except Exception:
            return None
    return shape


def _direction_vector_from_ref(direction_ref):
    shape = _direction_shape(direction_ref)
    if shape is None:
        return None

    stype = getattr(shape, "ShapeType", "")
    if stype == "Edge":
        if len(shape.Vertexes) < 2:
            return None
        vec = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
    elif stype == "Face":
        try:
            u0, u1, v0, v1 = shape.ParameterRange
            vec = shape.normalAt((u0 + u1) * 0.5, (v0 + v1) * 0.5)
        except Exception:
            return None
    else:
        return None

    if vec.Length == 0:
        return None
    return vec / vec.Length


def _apply_direction_vector(constraint_obj, direction_ref, reversed_flag=None):
    vec = _direction_vector_from_ref(direction_ref)
    if vec is None:
        return False

    if reversed_flag is None:
        reversed_flag = bool(getattr(constraint_obj, "Reversed", False))
    if reversed_flag:
        vec = -vec

    try:
        constraint_obj.DirectionVector = vec
        return True
    except Exception:
        return False


# ************************************************************************************************
# setup and run examples by Python

# TODO: use method from examples gui to collect all examples in run_all method
# FreeCAD Gui update between the examples would makes sense too

"""
# setup all examples
from femexamples.manager import *
setup_all()


# run all examples
from femexamples.manager import *
run_all()


# one special example
from femexamples.manager import run_example as run

doc = run("boxanalysis_static")
doc = run("boxanalysis_frequency")

"""


def set_direction_compat(constraint_obj, direction_ref):
    """Set Direction while handling known setter regressions."""
    global _DIRECTION_COMPAT_WARNED
    global _PRIMITIVE_DIRECTION_WARNED

    obj_id = id(constraint_obj)
    _DIRECTION_FALLBACK_OBJECT_IDS.discard(obj_id)
    _DIRECTION_FALLBACK_REFS.pop(obj_id, None)

    obj = direction_ref[0] if isinstance(direction_ref, (list, tuple)) and direction_ref else None

    # Primitive Part objects (Part::Line / Part::Plane) are known to throw or
    # keep a wrong default DirectionVector. Use derived vector fallback.
    if _is_primitive_direction_object(obj):
        try:
            constraint_obj.Direction = direction_ref
        except Exception:
            pass
        _apply_direction_vector(constraint_obj, direction_ref)
        _DIRECTION_FALLBACK_OBJECT_IDS.add(obj_id)
        _DIRECTION_FALLBACK_REFS[obj_id] = direction_ref
        if not _PRIMITIVE_DIRECTION_WARNED:
            FreeCAD.Console.PrintWarning(
                "Using compatibility path for primitive Direction object.\n"
            )
            _PRIMITIVE_DIRECTION_WARNED = True
        return

    try:
        constraint_obj.Direction = direction_ref
        return
    except TypeError as exc:
        msg = str(exc)
        if "Type is not a line, plane or Part object" not in msg:
            raise

        if getattr(constraint_obj, "Direction", None) != direction_ref:
            raise

        if not _DIRECTION_COMPAT_WARNED:
            FreeCAD.Console.PrintWarning(
                "Using compatibility path for ConstraintForce.Direction setter.\n"
            )
            _DIRECTION_COMPAT_WARNED = True

        _apply_direction_vector(constraint_obj, direction_ref)
        _DIRECTION_FALLBACK_OBJECT_IDS.add(obj_id)
        _DIRECTION_FALLBACK_REFS[obj_id] = direction_ref


def set_reversed_compat(constraint_obj, reversed_flag):
    """Set Reversed while tolerating Direction side-effect TypeError."""
    global _REVERSED_COMPAT_WARNED

    used_fallback = False
    try:
        constraint_obj.Reversed = reversed_flag
    except TypeError as exc:
        msg = str(exc)
        if "Type is not a line, plane or Part object" not in msg:
            raise

        if getattr(constraint_obj, "Reversed", None) != reversed_flag:
            raise

        if not _REVERSED_COMPAT_WARNED:
            FreeCAD.Console.PrintWarning(
                "Using compatibility path for ConstraintForce.Reversed setter.\n"
            )
            _REVERSED_COMPAT_WARNED = True
        used_fallback = True

    obj_id = id(constraint_obj)
    direction_ref = getattr(constraint_obj, "Direction", None)
    if not (isinstance(direction_ref, (list, tuple)) and len(direction_ref) == 2):
        direction_ref = _DIRECTION_FALLBACK_REFS.get(obj_id)

    needs_direction_sync = used_fallback or (obj_id in _DIRECTION_FALLBACK_OBJECT_IDS)

    if needs_direction_sync:
        _apply_direction_vector(constraint_obj, direction_ref, reversed_flag)


def run_all():
    run_example("boxanalysis_frequency", run_solver=True)
    run_example("boxanalysis_static", run_solver=True)
    run_example("assembly_linkbody_free_dynamics", run_solver=True)
    run_example("assembly_linkbody_forced_dynamics", run_solver=True)
    run_example("buckling_lateraltorsionalbuckling", run_solver=True)
    run_example("buckling_platebuckling", run_solver=True)
    run_example("ccx_buckling_flexuralbuckling", run_solver=True)
    run_example("ccx_cantilever_faceload", run_solver=True)
    run_example("ccx_cantilever_hexa20faceload", run_solver=True)
    run_example("ccx_cantilever_nodeload", run_solver=True)
    run_example("ccx_cantilever_prescribeddisplacement", run_solver=True)
    run_example("constraint_contact_shell_shell", run_solver=True)
    run_example("constraint_contact_solid_solid", run_solver=True)
    run_example("constraint_hydrostaticpressure", run_solver=True)
    run_example("constraint_hydrostaticpressure_datafile", run_solver=True)
    run_example("constraint_jig321", run_solver=True)
    run_example("constraint_reaction", run_solver=True)
    run_example("constraint_section_print", run_solver=True)
    run_example("constraint_selfweight_cantilever", run_solver=True)
    run_example("constraint_tie", run_solver=True)
    run_example("constraint_transform_beam_hinged", run_solver=True)
    run_example("elmer_nonguitutorial01_eigenvalue_of_elastic_beam", run_solver=True)
    run_example("equation_deformation_spring_elmer", run_solver=True)
    run_example("equation_electrostatics_capacitance_two_balls", run_solver=True)
    run_example("equation_electrostatics_electricforce_elmer_nongui6", run_solver=True)
    run_example("equation_flow_elmer_2D", run_solver=True)
    run_example("equation_flow_initial_elmer_2D", run_solver=True)
    run_example("equation_flow_turbulent_elmer_2D", run_solver=True)
    run_example("equation_flux_elmer", run_solver=True)
    run_example("equation_magnetodynamics_elmer", run_solver=True)
    run_example("equation_magnetodynamics_2D_elmer.py", run_solver=True)
    run_example("equation_magnetostatics_2D_elmer.py", run_solver=True)
    run_example("frequency_beamsimple", run_solver=True)
    run_example("material_multiple_bendingbeam_fiveboxes", run_solver=True)
    run_example("material_multiple_bendingbeam_fivefaces", run_solver=True)
    run_example("material_multiple_tensionrod_twoboxes", run_solver=True)
    run_example("material_nl_platewithhole", run_solver=True)
    run_example("rc_wall_2d", run_solver=True)
    run_example("square_pipe_end_twisted_edgeforces", run_solver=True)
    run_example("square_pipe_end_twisted_nodeforces", run_solver=True)
    run_example("thermomech_bimetal", run_solver=True)
    run_example("gmsh_transfinite_manual", run_solver=True)
    run_example("gmsh_transfinite_automation", run_solver=True)
    run_example("gmsh_adaptive", run_solver=True)


def setup_all():
    run_example("boxanalysis_frequency")
    run_example("boxanalysis_static")
    run_example("assembly_linkbody_free_dynamics")
    run_example("assembly_linkbody_forced_dynamics")
    run_example("buckling_lateraltorsionalbuckling")
    run_example("buckling_platebuckling")
    run_example("ccx_buckling_flexuralbuckling")
    run_example("ccx_cantilever_faceload")
    run_example("ccx_cantilever_hexa20faceload")
    run_example("ccx_cantilever_nodeload")
    run_example("ccx_cantilever_prescribeddisplacement")
    run_example("constraint_contact_shell_shell")
    run_example("constraint_contact_solid_solid")
    run_example("constraint_hydrostaticpressure")
    run_example("constraint_hydrostaticpressure_datafile")
    run_example("constraint_jig321")
    run_example("constraint_reaction")
    run_example("constraint_section_print")
    run_example("constraint_selfweight_cantilever")
    run_example("constraint_tie")
    run_example("constraint_transform_beam_hinged")
    run_example("elmer_nonguitutorial01_eigenvalue_of_elastic_beam")
    run_example("equation_deformation_spring_elmer")
    run_example("equation_electrostatics_capacitance_two_balls")
    run_example("equation_electrostatics_electricforce_elmer_nongui6")
    run_example("equation_flow_elmer_2D")
    run_example("equation_flow_initial_elmer_2D")
    run_example("equation_flow_turbulent_elmer_2D")
    run_example("equation_flux_elmer")
    run_example("equation_magnetodynamics_elmer")
    run_example("equation_magnetodynamics_2D_elmer.py")
    run_example("equation_magnetostatics_2D_elmer.py")
    run_example("frequency_beamsimple")
    run_example("material_multiple_bendingbeam_fiveboxes")
    run_example("material_multiple_bendingbeam_fivefaces")
    run_example("material_multiple_tensionrod_twoboxes")
    run_example("material_nl_platewithhole")
    run_example("rc_wall_2d")
    run_example("square_pipe_end_twisted_edgeforces")
    run_example("square_pipe_end_twisted_nodeforces")
    run_example("thermomech_bimetal")
    run_example("gmsh_transfinite_manual")
    run_example("gmsh_transfinite_automation")
    run_example("gmsh_adaptive")


def run_mesh_generation(doc, analysis=None):

    # find all mesh generation objects
    from femtools.femutils import is_derived_from

    objects = doc.Objects
    if analysis:
        objects = analysis.Group

    gmsh_generators = []
    netgen_generators = []
    for m in objects:
        if is_derived_from(m, "Fem::FemMeshGmsh"):
            gmsh_generators.append(m)
        elif is_derived_from(m, "Fem::FemMeshNetgen"):
            netgen_generators.append(m)

    if not gmsh_generators and not netgen_generators:
        # no meshes to generate
        return

    # run generations
    from femmesh import gmshtools, netgentools

    for gmsh in gmsh_generators:

        if gmsh.FemMesh.NodeCount > 0:
            # only mesh unmehsed generators
            continue

        tool = gmshtools.GmshTools(gmsh)
        tool.create_mesh()

        # make geometry invisible, and mesh visible, like in the other examples
        if FreeCAD.GuiUp:
            gmsh.ViewObject.Visibility=True
            gmsh.Shape.ViewObject.Visibility=False

    for netgen in netgen_generators:
        if netgen.FemMesh.NodeCount > 0:
            # only mesh unmehsed generators
            continue

        tool = netgentools.NetgenTools(netgen)
        tool.compute()


def run_analysis(doc, base_name, analysis=None, filepath="", run_solver=False,  blocking=True):

    from os import makedirs
    from os.path import exists, join
    from tempfile import gettempdir as gettmp

    # computable?
    if not analysis and not hasattr(doc, "Analysis"):
        return

    # get the default analysis if not specified otherwise
    if not analysis:
        analysis = doc.Analysis

    # recompute
    doc.recompute()

    # check if we need to generate the mesh
    run_mesh_generation(doc, analysis=analysis)

    # filepath
    if filepath == "":
        filepath = join(gettmp(), "FEM_examples")
    if not exists(filepath):
        makedirs(filepath)

    # find the first solver
    # thus ATM only one solver per analysis is supported
    from femtools.femutils import is_derived_from

    solver = None
    for m in analysis.Group:
        if is_derived_from(m, "Fem::FemSolverObjectPython"):
            solver = m
            break

    if not solver:
        return

    # a file name is needed for the besides dir to work
    save_fc_file = join(filepath, (base_name + ".FCStd"))
    FreeCAD.Console.PrintMessage(f"Save FreeCAD file for {base_name} analysis to {save_fc_file}\n.")
    doc.saveAs(save_fc_file)

    # get analysis workig dir
    from femtools.femutils import get_beside_dir

    working_dir = get_beside_dir(solver)

    # run analysis
    from femsolver.run import run_fem_solver

    if run_solver is True:
        run_fem_solver(solver, working_dir, blocking=blocking)

    # save doc once again with results
    doc.save()


def run_example(example, solver=None, base_name=None, run_solver=False, blocking=True, doc=None):

    from importlib import import_module

    module = import_module("femexamples." + example)
    if not hasattr(module, "setup"):
        FreeCAD.Console.PrintError(f"Setup method not found in {example}\n")
        return None

    if solver is None:
        doc = getattr(module, "setup")(doc=doc)
    else:
        doc = getattr(module, "setup")(doc=doc, solvertype=solver)

    if base_name is None:
        base_name = example
        if solver is not None:
            base_name += "_" + solver

    # As of now, we support:
    # 1. Multiple analysis objects, each having a mesh and solver object
    # 2. Or multiple mesh objects outside of analysis

    # find all analysis
    analysis = []
    for obj in doc.Objects:
        if obj.isDerivedFrom('Fem::FemAnalysis'):
            analysis.append(obj)

    if not analysis:
        # run all mesh generators in the document!
        run_mesh_generation(doc)
    else:
        # run each analysis
        for ana in analysis:
            run_analysis(doc, base_name, analysis=ana, run_solver=run_solver, blocking=blocking)

    doc.recompute()

    return doc


# ************************************************************************************************
# helper used from examples
def init_doc(doc=None):
    if doc is None:
        doc = FreeCAD.newDocument()
        # set license
        doc.License = "Creative Commons Attribution 4.0"
        doc.LicenseURL = "https://creativecommons.org/licenses/by/4.0/"
    return doc


def get_meshname():
    # needs to be "Mesh" to work with unit tests
    return "Mesh"


def get_header(information):
    return """{name}

{information}""".format(
        name=information["name"], information=print_info_dict(information)
    )


def print_info_dict(information):
    the_text = ""
    for k, v in information.items():
        value_text = ""
        if isinstance(v, list):
            for j in v:
                value_text += f"{j}, "
            value_text = value_text.rstrip(", ")
        else:
            value_text = v
        the_text += f"{k} --> {value_text}\n"
    # print(the_text)
    return the_text


def add_explanation_obj(doc, the_text):
    text_obj = doc.addObject("App::TextDocument", "Explanation_Report")
    text_obj.Text = the_text
    text_obj.setPropertyStatus("Text", "ReadOnly")  # set property editor readonly
    if FreeCAD.GuiUp:
        text_obj.ViewObject.ReadOnly = True  # set editor view readonly
    return text_obj
