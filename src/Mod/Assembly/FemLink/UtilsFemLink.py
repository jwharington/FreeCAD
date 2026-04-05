import FreeCAD
import UtilsAssembly
from FreeCAD import Console


def find_common_group_objects(ref_group, typeid):
    objs = FreeCAD.ActiveDocument.findObjects(Type=typeid)
    return [obj for obj in objs if obj.getParentGroup() is ref_group]


def get_assembly_bodies(assembly):
    return find_common_group_objects(assembly, "App::Link")


def get_simgroup(assembly):
    sim_groups = []
    for obj in assembly.Group:
        if obj.TypeId == "Assembly::SimulationGroup":
            sim_groups.append(obj)
    if len(sim_groups) != 1:
        Console.PrintError("sim groups != 1\n")
        return None
    return sim_groups[0]


def get_simulations(assembly):

    sim_group = get_simgroup(assembly)
    if not sim_group:
        Console.PrintError("Can't find simgroup\n")
        return []

    def is_simulation(obj):
        return hasattr(obj, "aTimeStart")

    return [obj for obj in sim_group.Group if is_simulation(obj)]


def get_femlinks(assembly):
    def is_femlink(obj):
        return obj.TypeId == "Part::FeaturePython" and hasattr(obj.Proxy, "runAnalysis")

    return [is_femlink(obj) for obj in assembly.Group]
