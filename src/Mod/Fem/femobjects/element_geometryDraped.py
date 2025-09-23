from .base_fempythonobject import _PropHelper
from .element_geometry2D import ElementGeometry2D
from femmesh.drapetools import Draper
import Part
import MeshPart


class ElementGeometryDraped(ElementGeometry2D):

    def __init__(self, obj):
        super().__init__(obj)

        if not obj.Mesh:
            obj.Mesh = obj.Document.addObject(
                "Mesh::Feature",
                "DrapeMesh",
            )

        if not obj.Plan:
            obj.Plan = obj.Document.addObject(
                "Part::Feature",
                "Plan",
            )
        obj.setPropertyStatus("Mesh", "LockDynamic")
        obj.setPropertyStatus("Plan", "LockDynamic")

    def _get_properties(self):
        prop = super()._get_properties()

        prop.append(
            _PropHelper(
                type="App::PropertyBool",
                name="Drape",
                group="Orthographic",
                doc="Drape orientation of material",
                value=False,
            )
        )
        prop.append(
            _PropHelper(
                type="App::PropertyFloat",
                name="MaxLength",
                group="Orthographic",
                doc="Max length of mesh",
                value=5.0,
            )
        )
        prop.append(
            _PropHelper(
                type="App::PropertyLinkGlobal",
                name="LocalCoordinateSystem",
                group="Orthographic",
                doc="Local coordinate system used for orthotropic materials",
                value=None,
            )
        )

        prop.append(
            _PropHelper(
                # type="Mesh::Feature",
                type="App::PropertyLinkGlobal",
                name="Mesh",
                group="Orthographic",
                doc="Mesh for orthotropic materials",
                value=None,
            )
        )

        prop.append(
            _PropHelper(
                # type="Part::FeaturePython",
                type="App::PropertyLinkGlobal",
                name="Plan",
                group="Orthographic",
                doc="Flattened surface for orthotropic materials",
                value=None,
            )
        )
        return prop

    def execute(self, fp):
        print("Draped: execute")
        for part, subs in fp.References:
            if not (lcs := fp.LocalCoordinateSystem):
                lcs = part
            for sub in subs:
                shape = Part.getShape(part, sub)
                mesh = self.update_mesh(shape, fp)
                if not mesh.Points:
                    continue
                self.draper = Draper(mesh, lcs)
                fp.ViewObject.update()

    def get_mesh(self):
        return self.draper.mesh

    def get_boundaries(self):
        return self.draper.get_boundaries()

    def get_drape_lcs(self, fp, tris):
        return self.draper.get_lcs(tris)

    def get_tex_coords(self):
        return self.draper.get_tex_coords()

    def update_mesh(self, shape, fp):
        return MeshPart.meshFromShape(Shape=shape, MaxLength=fp.MaxLength)

    def onDocumentRestored(self, fp):
        print("Draped: onDocumentRestored")
        super().onDocumentRestored(fp)
        fp.recompute()

    def onChanged(self, fp, prop):
        print(f"Draped onChanged {prop}")
        if "MaxLength" == prop:
            fp.recompute()
