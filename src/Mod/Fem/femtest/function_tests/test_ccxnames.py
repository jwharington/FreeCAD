# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""The digest the writer puts in a per-element elset, and reading it back.

The digests pinned here are the ones a real fuselage deck carried: a draped
section is written one card per element as ``<md5(base)[:20]>_<element id>``,
and a reader has to recognise that spelling against the section names the model
declares.
"""

import pytest

from femtools import ccxnames

# Real deck values: the section objects are SkinFwdLaminate_Section and
# SkinLaminate_Section, and the writer starts from "Material" + that name.
_FWD = "MaterialSkinFwdLaminate_Section"
_AFT = "MaterialSkinLaminate_Section"
_FWD_DIGEST = "3d57303cab0f1d9d6723"
_AFT_DIGEST = "e89e98d4337c11cb70fd"


def test_the_writer_digest_is_md5_first_twenty():
    assert ccxnames.hashed_prefix(_FWD) == _FWD_DIGEST
    assert ccxnames.hashed_prefix(_AFT) == _AFT_DIGEST


def test_the_whole_section_under_its_own_name():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD})
    assert ccxnames.section_of_elset(_FWD, index) == "SkinFwdLaminate_Section"


def test_one_element_under_the_plain_name():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD})
    assert ccxnames.section_of_elset(_FWD + "_2509", index) == \
        "SkinFwdLaminate_Section"


def test_one_element_under_the_digest():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD})
    assert ccxnames.section_of_elset(_FWD_DIGEST + "_2509", index) == \
        "SkinFwdLaminate_Section"


def test_the_digest_names_the_right_section_among_several():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD,
                                 "SkinLaminate_Section": _AFT})
    assert ccxnames.section_of_elset(_AFT_DIGEST + "_2283", index) == \
        "SkinLaminate_Section"
    assert ccxnames.section_of_elset(_FWD_DIGEST + "_2509", index) == \
        "SkinFwdLaminate_Section"


def test_an_unrelated_elset_names_no_section():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD})
    assert ccxnames.section_of_elset("Eall", index) is None
    assert ccxnames.section_of_elset("Efaces", index) is None


def test_a_digest_for_a_section_not_named_is_not_guessed():
    index = ccxnames.elset_index({"SkinFwdLaminate_Section": _FWD})
    assert ccxnames.section_of_elset(_AFT_DIGEST + "_1", index) is None
