from femtaskpanels import task_element_geometry2D
from . import view_base_femelement
import FreeCADGui
from .grid_shaders.MeshGridShader import MeshGridShader


class VPElementGeometryDraped(view_base_femelement.VPBaseFemElement):

    def __init__(self, vobj):

        vobj.addProperty(
            "App::PropertyFloatConstraint",
            "Darken",
            "AnalysisOptions",
            "Grid darkness",
        )
        vobj.Darken = 0.5

        self.child_mesh = None
        self.child_plan = None
        self.grid_shader = None

        super().__init__(vobj)

    def setEdit(self, vobj, mode=0):
        return super().setEdit(vobj, mode, task_element_geometry2D._TaskPanel)

    def getDisplayModes(self, obj):
        return ["Grid"]

    def getDefaultDisplayMode(self):
        return "Grid"

    def attach(self, vobj):
        print("VPDraped attach")
        self.Active = False
        super().attach(vobj)
        self.grid_shader = MeshGridShader()
        self.child_mesh = None
        self.child_plan = None

        vobj.addDisplayMode(self.grid_shader.grp, "Grid")
        self.load_shader()

    def updateData(self, fp, prop):
        print(f"VPDraped updateData {prop}")
        changed = False
        if prop == "Mesh":
            self.child_mesh = fp.Mesh
            changed = True
        if prop == "Plan":
            self.child_plan = fp.Plan
            changed = True
        if changed:
            self.reload_shader()

    def onChanged(self, vobj, prop):
        print(f"VPDraped onChanged {prop}")
        if prop == "Visibility":
            if vobj.Visibility and not self.Active:
                self.load_shader()
            if (not vobj.Visibility) and self.Active:
                self.remove_shader()
            self.child_mesh.Visibility = vobj.Visibility
            self.child_plan.Visibility = vobj.Visibility
        if (prop == "Darken") and self.grid_shader:
            self.grid_shader.Darken = vobj.Darken

    def onDelete(self, vobj, sub):
        self.remove_shader()
        return True

    def claimChildren(self):
        return [self.child_mesh, self.child_plan]

    def reload_shader(self):
        self.remove_shader()
        self.load_shader()

    def load_shader(self):
        if self.Active:
            return
        if not self.child_mesh:
            return
        obj = self.Object.Proxy
        if not hasattr(obj, "draper"):
            return
        print("load")

        vobj = self.Object
        # vobj.Mesh.Mesh = obj.get_mesh()

        # boundaries = obj.get_boundaries()
        # for w in boundaries:
        #     vobj.Plan.Shape = Part.Wire(Part.makePolygon(w))

        tex_coords = obj.get_tex_coords()
        self.grid_shader.attach(vobj, vobj.Mesh, tex_coords)
        self.Active = True
        FreeCADGui.Selection.addObserver(self)

    def remove_shader(self):
        if not self.Active:
            return
        if not self.child_mesh:
            return
        print("unload")
        self.grid_shader.detach(self.child_mesh)
        self.Active = False
        FreeCADGui.Selection.removeObserver(self)
