from FreeCAD import Vector, Rotation
import Part
import Mesh
import numpy as np
import flatmesh


class Draper:

    unwrap_steps = 5
    unwrap_relax_weight = 0.95

    @staticmethod
    def calculate_strain(OA, OB, OA_d, OB_d):
        # https://www.ce.memphis.edu/7117/notes/presentations/chapter_06a.pdf
        # triangles counterclockwise i,j,m

        # xi, yi etc are locations (unloaded)
        # ui, vi etc are displacements

        x_i = 0
        y_i = 0
        x_j = OA.x
        y_j = OA.y
        x_m = OB.x
        y_m = OB.y

        u_i = 0
        v_i = 0
        u_j = OA_d.x - OA.x
        v_j = OA_d.y - OA.y
        u_m = OB_d.x - OB.x
        v_m = OB_d.y - OB.y

        beta_i = y_j - y_m
        beta_j = y_m - y_i
        beta_m = y_i - y_j

        gamma_i = x_m - x_j
        gamma_j = x_i - x_m
        gamma_m = x_j - x_i

        two_A = x_i * (y_i - y_m) + x_j * (y_m - y_i) + x_m * (y_i - y_j)
        # (A is area of triangle)

        exx = 1 / (two_A) * (beta_i * u_i + beta_j * u_j + beta_m * u_m)
        eyy = 1 / (two_A) * (gamma_i * v_i + gamma_j * v_j + gamma_m * v_m)
        exy = (
            1
            / (two_A)
            * (
                gamma_i * u_i
                + beta_i * v_i
                + gamma_j * u_j
                + beta_j * v_j
                + gamma_m * u_m
                + beta_m * v_m
            )
        )
        return (exx, eyy, exy)

    def get_flattener(self, mesh):
        points = np.array([[i.x, i.y, i.z] for i in mesh.Points])
        faces = np.array([list(i) for i in mesh.Topology[1]])
        flattener = flatmesh.FaceUnwrapper(points, faces)
        flattener.findFlatNodes(self.unwrap_steps, self.unwrap_relax_weight)
        return flattener

    def get_lcs_table(self, mesh, lcs):

        # locate origin in meshes ---------------------------------------
        # track which point index is mapped from the reference vertex O
        #   in the shape at the LCS origin

        v_O = lcs.getGlobalPlacement().Base

        # - find nearest vertex O in the mesh to the origin of the LCS

        def find_nearest_vertex(vO):
            dmin = None
            imin = None
            for i in mesh.Topology[1][0]:
                d = vO.distanceToPoint(mesh.Points[i].Vector)
                if (dmin is None) or (d < dmin):
                    dmin = d
                    imin = i
            return imin

        i_O = find_nearest_vertex(v_O)
        # print(f"nearest vertex {i_O}")

        # determine rotation required for flattened --------------------
        # - find a triangle (OAB) in 3d mesh that includes the reference
        # point O

        def find_triangle(i_O):
            for tri in mesh.Topology[1]:
                if i_O in tri:
                    res = list(tri)
                    res.remove(i_O)
                    return res

        (i_A, i_B) = find_triangle(i_O)
        # print(f"tris {i_A}, {i_B}")

        # - calculate vectors OA, OB

        OA = mesh.Points[i_A].Vector
        OB = mesh.Points[i_B].Vector

        # - cast to LCS OA_l, OB_l

        T_gl = lcs.getGlobalPlacement().inverse()

        # - find the coordinates of the vectors O'A' and O'B' in the
        #   flat coordinate system
        # -> find 2d rotation matrix / angle so OA and OB coordinates
        #    = T * O'A' and T O'B' respectively

        flattener = self.get_flattener(mesh)
        # print(f"ze_nodes {flattener.ze_nodes}")

        def flat_vector(i):
            p = flattener.ze_nodes[i]
            return Vector(p[0], p[1], 0.0)

        if OA.Length > OB.Length:
            O_l = T_gl * OA
            O_f = flat_vector(i_A) - flat_vector(i_O)
        else:
            O_l = T_gl * OB
            O_f = flat_vector(i_B) - flat_vector(i_O)

        O_ld = Vector(O_l.x, O_l.y, 0.0)
        T_fo = Rotation(O_f, O_ld)

        # analyse distortion and save local axes ------------------------

        def find_x_axis_mix(OA_f, OB_f):
            if abs(OA_f.y) < abs(OB_f.y):
                # b = -(OA_y / OB_y ) a
                # a. OA_x - (OA_y / OB_y ) a OB_x = 1
                a = 1 / (OA_f.x - OA_f.y / OB_f.y)
                b = -(OA_f.y / OB_f.y) * a
            else:
                # a = -(OB_y / OA_y ) b
                # (OB_y / OA_y ) b . OA_x - b OB_x = 1
                b = 1 / (OB_f.x - OB_f.y / OA_f.y)
                a = -(OB_f.y / OA_f.y) * b
            return (a, b)

        def calc_local_mesh(tri):
            (i_O, i_A, i_B) = tri

            # mix OA, OB to make vertical line
            O_f = flat_vector(i_O)
            OA_f = flat_vector(i_A) - O_f
            OB_f = flat_vector(i_B) - O_f

            # OP is unit direction in X on 2d space
            # a . OA_f + b . OB_f = [1,0]'

            (a, b) = find_x_axis_mix(OA_f, OB_f)
            OA = mesh.Points[i_A].Vector - mesh.Points[i_O].Vector
            OB = mesh.Points[i_B].Vector - mesh.Points[i_O].Vector
            OP = a * OA + b * OB
            normal = OA.cross(OB)

            T_fl = Rotation(OP, OP.cross(normal)).inverted()

            # now map OA, OB back to flat:
            OA_fd = T_fl * OA
            OB_fd = T_fl * OB

            strain = self.calculate_strain(OA_f, OB_f, OA_fd, OB_fd)
            return T_fl, strain

        def calc_tex_coord(p):
            pr = T_fo * Vector(p[0], p[1], 0)
            return (pr.x, pr.y)

        def make_boundary():
            boundaries = flattener.getFlatBoundaryNodes()
            for edge in boundaries:
                pi = Part.makePolygon([T_fo * Vector(*node) for node in edge])
                Part.show(Part.Wire(pi))

        # save texture coordinates for rendering pattern in 3d
        tex_coords = [calc_tex_coord(p) for p in flattener.ze_nodes]

        # save strain and local rot matrix
        tri_info = [calc_local_mesh(tri) for tri in mesh.Topology[1]]

        # make wire from boundary edges, with rotation ------------------

        make_boundary()
        # TODO: define extra allowance (outset shape)

        return tex_coords, tri_info


def partial_femmesh_2_mesh(myFemMesh, elements):
    # simplified from femmesh_2_mesh
    output_mesh = []
    for e in elements:
        element_nodes = myFemMesh.getElementNodes(e)
        if len(element_nodes) in [3, 6]:
            faceDef = {1: [0, 1, 2]}
        else:  # quad element
            faceDef = {1: [0, 1, 2, 3]}

        for key in faceDef:
            for nodeIdx in faceDef[key]:
                n = myFemMesh.getNodeById(element_nodes[nodeIdx])
                output_mesh.append(n)
    return Mesh.Mesh(output_mesh)


def get_drape_lcs(femmesh_obj, elements, lcs):
    mesh = partial_femmesh_2_mesh(femmesh_obj, elements)
    Mesh.show(mesh)
    draper = Draper()
    (tex_coords, tri_info) = draper.get_lcs_table(mesh, lcs)
    lcs_lookup = zip(elements, tri_info)
    return {id: tri_info[0] for (id, tri_info) in lcs_lookup}
