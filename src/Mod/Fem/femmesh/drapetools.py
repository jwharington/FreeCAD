from femmesh2mesh import femmesh_2_mesh
import Mesh


def get_drape_lcs(mesh_obj, elements, lcs):
    out_mesh = femmesh_2_mesh(mesh_obj)
    Mesh.show(Mesh.Mesh(out_mesh))

    print("TODO unwrap if option selected, via femmesh2mesh")
    return {id: lcs for id in elements}
