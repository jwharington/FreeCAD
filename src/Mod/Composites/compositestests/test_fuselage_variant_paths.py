"""The two fuselage variants must not share a save path.

Building the uncut baseline used to overwrite the cut model: both
defaulted to ``fuselage_v2.FCStd``, and the models differ only by the
``bay_cutout`` flag, so the loss was silent.
"""
import importlib.util
import os
import sys

import pytest

_SCRIPT = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "Projects", "RTOA", "LS8e", "Design", "ls8e-design-tools",
    "propeller", "cad", "FuselageV2.py",
)


@pytest.fixture(scope="module")
def vv():
    spec = importlib.util.spec_from_file_location("fuselage_v2", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fuselage_v2"] = module
    spec.loader.exec_module(module)
    return module


def test_variants_save_to_different_files(vv):
    cut = vv._default_save_path(True)
    nocut = vv._default_save_path(False)
    assert cut != nocut


def test_uncut_variant_is_named_for_what_it_is(vv):
    assert os.path.basename(vv._default_save_path(True)) == "fuselage_v2.FCStd"
    assert os.path.basename(vv._default_save_path(False)) == \
        "fuselage_v2_nocut.FCStd"


def test_default_is_the_cut_model(vv):
    """Callers that do not pass the flag get the primary model, as before."""
    assert vv._default_save_path() == vv._default_save_path(True)
