import FreeCAD
import numpy as np
from FreeCAD import Console
from PySide import QtCore
from scipy.spatial import ConvexHull
from UtilsAssembly import (
    restoreAssemblyPartsPlacements,
    saveAssemblyPartsPlacements,
)

from FemLink.LinkBody import UpdateMode

from .UtilsFemLink import find_common_group_objects

try:
    import FreeCADGui
except ImportError:
    FreeCADGui = None

try:
    import visvalingamwyatt as vw
except ImportError:
    vw = None


def _refresh_gui():
    if FreeCAD.GuiUp and FreeCADGui is not None:
        FreeCADGui.updateGui()
        QtCore.QCoreApplication.processEvents()


def _update_view_object(obj):
    view_obj = getattr(obj, "ViewObject", None)
    if view_obj is not None:
        view_obj.update()


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

    # Exclude placement matrices; only dynamic load-state variables are reduced.
    A_features = A[:, : -16 * n_bodies]

    # Degenerate case: no/insufficient non-placement columns for 2D hull.
    if A_features.ndim != 2 or A_features.shape[1] < 2:
        idx = np.arange(A.shape[0], dtype=float)
        A_reduced = np.column_stack((idx, np.zeros(A.shape[0], dtype=float)))
        return [A[i] for i in range(A.shape[0])], A_reduced, A_reduced

    A_reduced, Vh_reduced = reduce_svd(A_features)
    try:
        A_hull, indices = convex_hull(A_reduced)
    except Exception as exc:
        Console.PrintWarning(f"Convex hull failed; using all states: {exc}\n")
        return [A[i] for i in range(A.shape[0])], A_reduced, A_reduced

    if len(A_hull) > num_hull and vw is not None:
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
        if len(A_hull) > num_hull and vw is None:
            Console.PrintWarning("visvalingamwyatt unavailable; skipping hull simplification.\n")
        A_convex = [A[i] for i in indices]
    return A_convex, A_hull, A_reduced


def out_forces(femlnk, states, dry_run=False):
    for idx, row in enumerate(states):
        Console.PrintMessage(f"...    set frame {idx}\n")
        femlnk.Proxy.state_set(femlnk, row)
        femlnk.Proxy.updateFEMLinks(femlnk, mode=UpdateMode.LOAD)
        _update_view_object(femlnk)
        _refresh_gui()
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
        _update_view_object(femlnk)
        _refresh_gui()

    return finish()


def synthesize_load_cases(femlnk, scale_factors=None):
    """Seed additional load cases from the current LinkBody state.

    This is useful for examples/tests where no assembly simulation frames are
    available yet but we still want to exercise the load-case handling flow.
    """
    if scale_factors is None:
        scale_factors = [0.5, 1.0, 1.5, 2.0]

    if not scale_factors:
        return 0

    # Capture one baseline state from current assembly/joint values.
    femlnk.Proxy.clear(femlnk)
    femlnk.Proxy.updateFEMLinks(femlnk, mode=UpdateMode.SAVE)
    if not femlnk.Proxy.num_states():
        return 0

    base_state = dict(femlnk.Proxy.all_states[-1])
    base_scale = scale_factors[0]

    def scale_value(key, value, factor):
        if not isinstance(key, tuple):
            return value
        if key[1] in {
            "Force",
            "Torque",
            "LinearAcceleration",
            "LinearVelocity",
            "AngularVelocity",
            "AngularAcceleration",
            "RelativeVelocity",
        }:
            # Keep baseline as-is for its own scale, scale all synthetic cases
            # relative to that baseline vector magnitude.
            if base_scale == 0:
                return value
            return value * (factor / base_scale)
        return value

    # Replace baseline with requested baseline factor if needed.
    femlnk.Proxy.all_states[-1] = {
        key: scale_value(key, value, base_scale) for key, value in base_state.items()
    }

    # Append additional synthetic states.
    for factor in scale_factors[1:]:
        femlnk.Proxy.all_states.append(
            {key: scale_value(key, value, factor) for key, value in base_state.items()}
        )

    return femlnk.Proxy.num_states()


def exercise_load_case_pipeline(assembly, femlnk, dry_run=True, scale_factors=None):
    """Exercise the same load-case handling path used by TaskAssemblyLinkBody.

    Steps:
    1. Clear existing states
    2. Try collecting states from assembly simulation frames
    3. If none were collected, synthesize states from baseline loads
    4. Run both full and reduced stored-analysis paths
    """
    femlnk.Proxy.clear(femlnk)

    # Prefer real simulation frames when available.
    assembly_collect_states(assembly, femlnk)

    num_states = femlnk.Proxy.num_states()
    if num_states == 0:
        num_states = synthesize_load_cases(femlnk, scale_factors=scale_factors)

    if num_states == 0:
        return {
            "num_states": 0,
            "full_hull_size": 0,
            "reduced_hull_size": 0,
        }

    hull_full, _ = run_stored_analysis(femlnk, reduced=False, dry_run=dry_run)
    hull_reduced, _ = run_stored_analysis(femlnk, reduced=True, dry_run=dry_run)

    return {
        "num_states": num_states,
        "full_hull_size": len(hull_full) if hull_full is not None else 0,
        "reduced_hull_size": len(hull_reduced) if hull_reduced is not None else 0,
    }
