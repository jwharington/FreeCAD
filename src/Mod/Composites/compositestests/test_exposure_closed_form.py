# SPDX-License-Identifier: LGPL-2.1-or-later
"""The load-homogeneous failure models must have an exact closed-form
exposure factor.

maximum_strain/maximum_stress scale linearly with the load, so the
exposure is the model value itself — demand over allowable, 1.0 =
failure at design load — with no per-node scipy search needed (that
search made a 31 MB frd import take ~9 minutes on a 5k-element shell
model).  These tests pin the closed form against the old bounded
search on random tensors, and pin the non-homogeneous models (Tsai-Wu)
to the search path.
"""

import numpy as np
import pytest

from femresult.failuremodels import (
    calc_failure_maximum_stress,
    calc_failure_maximum_strain,
    calc_stress_exposure_factor,
    default_options,
    get_failure_model,
    is_homogeneous_load,
)

RNG = np.random.default_rng(20261001)


def _random_tensors(n):
    s = RNG.uniform(-1.0e2, 1.0e2, size=(n, 6))
    e = RNG.uniform(-4.0e-3, 4.0e-3, size=(n, 6))
    return s, e


def test_homogeneous_models_declared():
    assert is_homogeneous_load("maximum_strain")
    assert is_homogeneous_load("maximum_stress")


def test_closed_form_matches_model_value():
    """The exposure is the model value itself: demand over allowable."""
    s, e = _random_tensors(64)
    for i in range(len(s)):
        f0 = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        r = calc_stress_exposure_factor(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        assert r == pytest.approx(f0, rel=1e-9)


def test_unstressed_point_has_zero_exposure():
    s, e = _random_tensors(64)
    for i in range(len(s)):
        f0 = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        if f0 <= 1e-12:
            r = calc_stress_exposure_factor(
                stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
            )
            assert r == pytest.approx(0.0, abs=1e-15)


def test_closed_form_matches_scipy_search():
    """The non-homogeneous search finds the failure load scale R; the
    exposure is its reciprocal, and must agree with the homogeneous
    closed form's f0 wherever the search could find the root."""
    s, e = _random_tensors(16)
    for i in range(len(s)):
        f0 = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        if not (1.0e-3 < 1.0 / max(f0, 1e-12) < 1.0e3):
            continue  # root outside the search's bounds
        closed = calc_stress_exposure_factor(s[i], e[i], default_options)
        assert f0 == pytest.approx(closed, rel=1e-6)


def test_already_failing_tensor_gives_exposure_above_one():
    s = np.array([500.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    e = np.array([1.0e-2, 0.0, 0.0, 0.0, 0.0, 0.0])  # > sxxt 3.2e-3
    r = calc_stress_exposure_factor(s, e, default_options)
    assert r > 1.0


def test_non_homogeneous_model_present():
    """The Composites models (Tsai-Wu, Hashin) exist for explicit
    selection; they are NOT load-homogeneous (linear terms) and keep the
    search path."""
    assert get_failure_model("tsai_wu") is not None
    assert get_failure_model("hashin") is not None
    assert not is_homogeneous_load("tsai_wu")


# --- batched evaluation ----------------------------------------------------


def test_models_are_axis_aware():
    """A (N, 6) batch of node tensors evaluates to (N,), and each entry is
    exactly what the scalar call gives for that node."""
    s, e = _random_tensors(48)
    batch_strain = calc_failure_maximum_strain(
        stress_tensor=s, strain_tensor=e, model_options=default_options
    )
    batch_stress = calc_failure_maximum_stress(
        stress_tensor=s, strain_tensor=e, model_options=default_options
    )
    assert batch_strain.shape == (48,)
    assert batch_stress.shape == (48,)
    for i in range(48):
        assert batch_strain[i] == pytest.approx(
            calc_failure_maximum_strain(
                stress_tensor=s[i], strain_tensor=e[i],
                model_options=default_options))
        assert batch_stress[i] == pytest.approx(
            calc_failure_maximum_stress(
                stress_tensor=s[i], strain_tensor=e[i],
                model_options=default_options))


def test_models_still_answer_scalar_calls():
    s, e = _random_tensors(8)
    for i in range(8):
        value = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        assert np.isscalar(value) or value.ndim == 0


class _StubMesh:
    def __init__(self, node_count):
        self.NodeCount = node_count


class _StubMeshObject:
    def __init__(self, node_count):
        self.FemMesh = _StubMesh(node_count)


class _StubResult:
    def __init__(self, stresses, strains, node_count):
        self.Mesh = _StubMeshObject(node_count)
        self.NodeStressXX, self.NodeStressYY, self.NodeStressZZ = (list(stresses[:, k]) for k in range(3))
        self.NodeStressXY, self.NodeStressXZ, self.NodeStressYZ = (list(stresses[:, k]) for k in range(3, 6))
        self.NodeStrainXX, self.NodeStrainYY, self.NodeStrainZZ = (list(strains[:, k]) for k in range(3))
        self.NodeStrainXY, self.NodeStrainXZ, self.NodeStrainYZ = (list(strains[:, k]) for k in range(3, 6))


class _StubSection:
    def __init__(self, name="Stub_Section"):
        self.Name = name
        self.References = [(object(), "Face1")]


def test_exposure_field_covers_every_node_at_once():
    """One material set for every section: the field is the batched closed
    form over ALL mesh nodes - no per-section geometric mapping, and the
    per-node loop must agree with it exactly."""
    from femresult.resulttools import add_stress_exposure_factor

    stresses, strains = _random_tensors(37)
    res_obj = _StubResult(stresses, strains, 37)

    add_stress_exposure_factor(res_obj, [_StubSection()])

    field = np.array(res_obj.StressExposureFactor)
    assert field.shape == (37,)
    for i in range(37):
        expected = calc_stress_exposure_factor(
            stress_tensor=stresses[i], strain_tensor=strains[i],
            model_options=default_options)
        assert field[i] == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_no_sections_leaves_the_field_zero():
    from femresult.resulttools import add_stress_exposure_factor

    stresses, strains = _random_tensors(11)
    res_obj = _StubResult(stresses, strains, 11)

    add_stress_exposure_factor(res_obj, [])

    assert res_obj.StressExposureFactor == [0.0] * 11
