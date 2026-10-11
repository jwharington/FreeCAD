# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the shared study command line (Composites.fem.study_cli).

The common flags and their validation live here; a study contributes only its
own flags through ``add_arguments`` and receives the parsed result through
``configure``.  The stub study is the seam, so a regression in the shared
surface is caught before it reaches a real one."""

import os

import pytest

from Composites.fem import study_cli


class _Study:
    """A study with the minimum the command line needs."""

    name = "widget"

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.configured = None

    def cases(self):
        return ["lc01", "lc02", "lc03"]

    def variants(self):
        return {"wide": {"band_width": 60.0}}

    def add_arguments(self, parser):
        parser.add_argument("--band-width", type=float)

    def configure(self, args):
        self.configured = args

    def provenance(self):
        return {"stack_model": "Smeared"}

    def geometry_arguments(self):
        return {"band_width": 45.0}

    def cache_root(self):
        return str(self.tmp_path / "cache")

    def run_paths(self, out_dir, study_name, variant, cases):
        base = os.path.join(out_dir or str(self.tmp_path),
                            "%s_%s" % (study_name, variant or "default"))
        return base + ".log", base + ".json"


@pytest.fixture
def study(tmp_path):
    return _Study(tmp_path)


def test_load_override_parses_a_component_case_insensitively():
    assert study_cli.parse_load_overrides(["fz=1000", "Mx=-500"]) == {
        "Fz": 1000.0, "Mx": -500.0}


def test_load_override_refuses_an_unknown_component():
    with pytest.raises(RuntimeError, match="Q=1"):
        study_cli.parse_load_overrides(["Q=1"])


def test_load_override_refuses_a_missing_value():
    with pytest.raises(RuntimeError, match="COMP=VALUE"):
        study_cli.parse_load_overrides(["Fz="])


def test_selection_defaults_to_every_case():
    assert study_cli.selected_cases(["lc01", "lc02"], "all", None) == \
        ["lc01", "lc02"]


def test_selection_subset_wins_and_keeps_its_order():
    assert study_cli.selected_cases(["lc01", "lc02", "lc03"], "all",
                                    "lc03, lc01") == ["lc03", "lc01"]


def test_selection_rejects_an_unknown_case():
    with pytest.raises(RuntimeError, match="nope"):
        study_cli.selected_cases(["lc01"], "all", "lc01,nope")


def test_selection_rejects_an_empty_subset():
    with pytest.raises(RuntimeError, match="names no case"):
        study_cli.selected_cases(["lc01"], "all", " , ")


def test_refinement_parses_five_numbers():
    assert study_cli.refinement("1,2,3,4,5") == (1.0, 2.0, 3.0, 4.0, 5.0)


def test_refinement_refuses_the_wrong_arity():
    with pytest.raises(RuntimeError, match="x,y,z,radius,size"):
        study_cli.refinement("1,2,3,4")


def test_parse_args_resolves_the_cases_and_overrides(study):
    args = study_cli.parse_args(study, ["--case", "lc02", "--load", "FZ=10"])
    assert args.selected_cases == ["lc02"]
    assert args.load_overrides == {"Fz": 10.0}
    assert args.refinements == []


def test_parse_args_refuses_an_override_on_a_batch(study):
    with pytest.raises(RuntimeError, match="--load Fz"):
        study_cli.parse_args(study, ["--case", "all", "--load", "FZ=10"])


def test_parse_args_refuses_case_and_cases_together(study):
    with pytest.raises(RuntimeError, match="cannot both be given"):
        study_cli.parse_args(study, ["--case", "lc02", "--cases", "lc01,lc03"])


def test_parse_args_refuses_zero_modes(study):
    with pytest.raises(RuntimeError, match="at least one mode"):
        study_cli.parse_args(study, ["--modes", "0"])


def test_parse_args_refuses_an_unknown_case(study):
    with pytest.raises(RuntimeError, match="lc09"):
        study_cli.parse_args(study, ["--case", "lc09"])


def test_a_study_adds_its_own_flags_beside_the_common_ones(study):
    args = study_cli.parse_args(study, ["--band-width", "45"])
    assert args.band_width == 45.0


def test_build_run_carries_the_parsed_options_and_provenance(study):
    args = study_cli.parse_args(study, ["--cases", "lc01,lc03",
                                        "--mesh-max", "12",
                                        "--no-mesh-cache"])
    run = study_cli.build_run(study, args)
    assert run.cases == ["lc01", "lc03"]
    assert run.mesh_max == 12.0
    assert run.provenance["stack_model"] == "Smeared"


def test_build_run_uses_the_variant_overrides(study):
    args = study_cli.parse_args(study, ["--variant", "wide",
                                        "--no-mesh-cache"])
    run = study_cli.build_run(study, args)
    assert run.geometry_arguments["band_width"] == 60.0
