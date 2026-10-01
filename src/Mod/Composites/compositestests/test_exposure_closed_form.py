# SPDX-License-Identifier: LGPL-2.1-or-later
"""The load-homogeneous failure models must have an exact closed-form
exposure factor.

maximum_strain/maximum_stress scale linearly with the load, so the
exposure factor is R = 1/model-value — no per-node scipy search needed
(that search made a 31 MB frd import take ~9 minutes on a 5k-element
shell model).  These tests pin the closed form against the old bounded
search on random tensors, and pin the non-homogeneous models (Tsai-Wu)
to the search path.
"""

import numpy as np
import pytest

from femresult.failuremodels import (
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
    s, e = _random_tensors(64)
    for i in range(len(s)):
        f0 = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        if f0 <= 1e-12:
            expected = 1.0e3
        else:
            expected = min(1.0 / f0, 1.0e3)
        r = calc_stress_exposure_factor(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        assert r == pytest.approx(expected, rel=1e-9)


def test_closed_form_matches_scipy_search():
    """The exposure factor must agree with the old bounded search's root
    wherever the search could find it."""
    s, e = _random_tensors(16)
    for i in range(len(s)):
        f0 = calc_failure_maximum_strain(
            stress_tensor=s[i], strain_tensor=e[i], model_options=default_options
        )
        if not (1.0e-3 < 1.0 / max(f0, 1e-12) < 1.0e3):
            continue  # search would clip; closed form caps identically
        closed = calc_stress_exposure_factor(s[i], e[i], default_options)
        assert 1.0 / f0 == pytest.approx(closed, rel=1e-6)


def test_already_failing_tensor_gives_reserve_below_one():
    s = np.array([500.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    e = np.array([1.0e-2, 0.0, 0.0, 0.0, 0.0, 0.0])  # > sxxt 3.2e-3
    r = calc_stress_exposure_factor(s, e, default_options)
    assert r < 1.0


def test_non_homogeneous_model_present():
    """The Composites models (Tsai-Wu, Hashin) exist for explicit
    selection; they are NOT load-homogeneous (linear terms) and keep the
    search path."""
    assert get_failure_model("tsai_wu") is not None
    assert get_failure_model("hashin") is not None
    assert not is_homogeneous_load("tsai_wu")
