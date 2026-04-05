import FreeCAD
import FreeCADGui
import numpy as np
import visvalingamwyatt as vw
from FreeCAD import Console
from PySide import QtCore
from scipy.spatial import ConvexHull
from UtilsAssembly import (
    restoreAssemblyPartsPlacements,
    saveAssemblyPartsPlacements,
)

from FemLink.LinkBody import UpdateMode

from .UtilsFemLink import find_common_group_objects


def extract_results(femlnk) -> dict:
    analysis = femlnk.Proxy.findAnalysis(femlnk)
    result_series = find_common_group_objects(analysis, "Fem::FemResultObjectPython")

    def process(result):
        return {"max vonMises": np.max(result.vonMises)}

    results = [process(result) for result in result_series]
    all_results = {}
    for k in results[0].keys():
        all_results[k] = [result[k] for result in results]
        if "index" not in all_results:
            all_results["index"] = [k for k, _ in enumerate(all_results[k])]
    return all_results


def reduce_svd(A, k: int = 2):
    # Perform SVD
    U, s, Vh = np.linalg.svd(A, full_matrices=False)
    # full_matrices=False for a more compact result

    # Choose the number of components (dimensions) to keep
    Sigma_k = np.diag(s[:k])

    # Reconstruct the data in the reduced dimension
    # The new feature space is U * Sigma_k
    U_k = U[:, :k]
    A_reduced = U_k @ Sigma_k
    Vh_reduced = Vh[:k, :]
    # Console.PrintMessage(f"A reduced: {A_reduced}\n")
    return A_reduced, Vh_reduced


def convex_hull(points):
    qhull_options = "QJ QbB"
    hull = ConvexHull(points, qhull_options=qhull_options)
    return [points[i] for i in hull.vertices], hull.vertices


def svd_qhull_reduce(states, n_bodies, num_hull=8):
    A = states
    if A.shape[0] < 2:
        return A, A, [1, 0]

    A_reduced, Vh_reduced = reduce_svd(A[:, : -16 * n_bodies])  # exclude placement data
    A_hull, indices = convex_hull(A_reduced)

    if len(A_hull) > num_hull:
        Console.PrintMessage(f"... simplifying hull from {len(A_hull)} to {num_hull} points\n")
        simplifier = vw.Simplifier(A_hull)
        A_simplified = simplifier.simplify(number=num_hull)
        A_convex = []
        for row in A_simplified:
            for i, ah in enumerate(A_hull):
                if np.array_equal(row, ah):
                    A_convex.append(A[indices[i]])
                    break
        A_hull = A_simplified
    else:
        # A_convex = A_hull @ Vh_reduced
        A_convex = [A[i] for i in indices]
    return A_convex, A_hull, A_reduced


def out_forces(femlnk, states, dry_run=False):
    for idx, row in enumerate(states):
        Console.PrintMessage(f"...    set frame {idx}\n")
        femlnk.Proxy.state_set(femlnk, row)
        femlnk.Proxy.updateFEMLinks(femlnk, mode=UpdateMode.LOAD)
        femlnk.ViewObject.update()
        if FreeCAD.GuiUp:
            FreeCADGui.updateGui()
            QtCore.QCoreApplication.processEvents()
        if not dry_run:
            femlnk.Proxy.runAnalysis(femlnk, index=idx)
            femlnk.Document.recompute()


def run_stored_analysis(femlnk, reduced=False, dry_run=False):
    Console.PrintMessage("... assembly FEM analysis\n")
    if not femlnk.Proxy.num_states():
        return None, None
    states = np.array(list(femlnk.Proxy.states_vector(femlnk)))
    states_reduced, hull, dim_reduced = svd_qhull_reduce(
        states,
        n_bodies=femlnk.Proxy.num_bodies(femlnk),
    )
    if reduced:
        out_forces(femlnk, states_reduced, dry_run=dry_run)
    else:
        out_forces(femlnk, states, dry_run=dry_run)
    return hull, dim_reduced


def assembly_collect_states(assembly, femlnk, index=None):
    def finish():
        restoreAssemblyPartsPlacements(assembly, initialPlcs=initialPlcs)

    Console.PrintMessage("... assembly collect load states\n")
    initialPlcs = saveAssemblyPartsPlacements(assembly)
    nsim = assembly.numberOfFrames()
    if (not nsim) or (nsim < 2):
        return finish()

    for idx in range(1, nsim):
        if index and (idx is not index):
            continue
        # Console.PrintMessage(f"...    scan frame {idx}\n")
        assembly.updateForFrame(idx)
        femlnk.Proxy.updateFEMLinks(femlnk, mode=UpdateMode.SAVE)
        femlnk.ViewObject.update()
        if FreeCAD.GuiUp:
            FreeCADGui.updateGui()
            QtCore.QCoreApplication.processEvents()

    return finish()
