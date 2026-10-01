"""Deck audit semantics, on synthetic decks.

The audit exists because a wrong model runs silently, so it must not
become the thing that breaks runs.  It already had one bug of that kind:
matching section blocks with ``elset.endswith(section_name)``.  A draped
zone is written as one ``*SHELL SECTION`` per element, named
``Material<Section>_<elementId>``, so nothing ever matched and every
section looked unmeshed.  Both naming styles are pinned here.
"""
import os
import sys

import pytest

_CAD = os.path.join(
    os.path.expanduser("~"),
    "Desktop", "Projects", "RTOA", "LS8e", "Design", "ls8e-design-tools",
    "propeller", "cad",
)
if _CAD not in sys.path:
    sys.path.insert(0, _CAD)


class _Proxy:
    def __init__(self, layers):
        self.FEMLayers = [{"t": t} for t in layers]

    def fem_layers(self, obj):
        """The accessor the writer itself uses (see features.Laminate)."""
        return self.FEMLayers


class _BrokenProxy:
    """A laminate whose stack model cannot be merged at all."""

    def fem_layers(self, obj):
        raise ValueError("no FEM layer representation for the Smeared stack")


class _Laminate:
    """A laminate as the audit sees it: plies, merged layers, thickness."""

    def __init__(self, name, plies, isotropic=False):
        self.Name = name
        self.Layers = [None] * plies
        self.Thickness = "%.3f mm" % (plies * 0.1)
        self.IsotropicEquivalent = isotropic
        self.ApproximateIsotropicEquivalent = False
        self.Proxy = _Proxy([0.1] * plies)


class _Geometry:
    def __init__(self, laminate):
        self.Name = "Geometry"
        self.Laminate = laminate


class _Section:
    TypeId = "Fem::FeaturePython"

    def __init__(self, name, laminate):
        self.Name = name
        self.References = [(_Geometry(laminate), "Face1")]


class _Doc:
    def __init__(self, *sections):
        self.Objects = list(sections)


def _block(elset, elements, plies, layered=True):
    """A *SHELL SECTION with the elset and membership it would own.

    Material cards carry the laminate's name, derived from the elset the
    writer built it from, as the real writer does.
    """
    name = elset[len("Material"):]
    if name.endswith("_Section"):
        name = name[:-len("_Section")].upper()
    lines = ["*ELSET,ELSET=%s" % elset]
    lines += ["%d," % e for e in elements]
    lines.append("*SHELL SECTION, ELSET=%s%s, OFFSET=0"
                 % (elset, ", COMPOSITE,ORIENTATION=_OR_%s" % elset
                    if layered else ", MATERIAL=%s:LAMINATE" % name))
    for i, t in enumerate(plies):
        lines.append("%.3f,,%s:%02d: LAMINA" % (t, name, i)
                     if layered else "%.3f,," % t)
    return lines


def _deck(element_ids, blocks):
    lines = ["*Node"] + ["%d,0,0,0" % n for n in range(1, 5)]
    lines.append("*Element, TYPE=S6, ELSET=Efaces")
    lines += ["%d,1,2,3" % e for e in element_ids]
    return "\n".join(lines + sum(blocks, [])) + "\n"


def _per_element(root, first, last, plies, layered=True):
    return [_block("%s_%d" % (root, e), [e], [0.1] * plies, layered)
            for e in range(first, last + 1)]


@pytest.fixture
def write(tmp_path):
    def _write(text):
        path = tmp_path / "deck.inp"
        path.write_text(text)
        return str(path)
    return _write


def test_plain_and_numbered_elsets_map_to_one_section():
    import deckaudit

    assert deckaudit.section_of_elset(
        "MaterialSkinFwdLaminate_Section") == "SkinFwdLaminate_Section"
    assert deckaudit.section_of_elset(
        "MaterialSkinFwdLaminate_Section_2283") == "SkinFwdLaminate_Section"
    assert deckaudit.section_of_elset("Eall") is None
    assert deckaudit.section_of_elset("Efaces") is None


def test_parse_deck_collects_blocks_ids_and_membership():
    import deckaudit

    deck = deckaudit.parse_deck(_deck([1, 2, 3], _per_element(
        "MaterialSkinLaminate_Section", 1, 3, 2)))
    assert len(deck["blocks"]) == 3
    assert deck["ids"] == {1, 2, 3}
    assert deck["owned"] == {1: {"SkinLaminate_Section"},
                             2: {"SkinLaminate_Section"},
                             3: {"SkinLaminate_Section"}}


def test_per_element_blocks_are_matched_to_their_section(write):
    """The regression: 3 blocks, one laminate, numbered elset names."""
    import deckaudit

    laminate = _Laminate("SkinLaminate", 3)
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1, 2, 3], _per_element(
            "MaterialSkinLaminate_Section", 1, 3, 3))), strict=False)
    assert problems == []
    assert rows == [("SkinLaminate_Section", "SkinLaminate", "layered",
                     3, 0.3, 3, 3)]


def test_one_block_naming_many_elements_counts_its_elements(write):
    """An orientation-free zone is one block over one big elset; block
    counting would call that a single element."""
    import deckaudit

    laminate = _Laminate("FrameQILaminate", 1, isotropic=True)
    rows, problems = deckaudit.audit(
        _Doc(_Section("FrameQILaminate_Section", laminate)),
        write(_deck(range(1, 41), [_block("MaterialFrameQILaminate_Section",
                                        list(range(1, 41)), [0.1], False)])),
        strict=False)
    assert problems == []
    assert rows[0][5] == 1 and rows[0][6] == 40


def test_smeared_blocks_are_found_even_among_layered_ones(write):
    import deckaudit

    laminate = _Laminate("SkinLaminate", 3)
    blocks = _per_element("MaterialSkinLaminate_Section", 1, 3, 3)
    blocks += _per_element("MaterialSkinLaminate_Section", 4, 4, 3,
                           layered=False)
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1, 2, 3, 4], blocks)), strict=False)
    assert len(problems) == 1
    assert "smeared isotropic" in problems[0]
    assert "1 of 4 blocks" in problems[0]


def test_element_without_a_section_is_found(write):
    import deckaudit

    laminate = _Laminate("SkinLaminate", 2)
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1, 2, 3], _per_element(
            "MaterialSkinLaminate_Section", 1, 2, 2))), strict=False)
    assert any("carry no section" in p for p in problems)


def test_element_in_two_sections_is_found(write):
    import deckaudit

    deck = _deck([1, 2], _per_element("MaterialSkinLaminate_Section", 1, 2, 2)
                 + _per_element("MaterialBandLaminate_Section", 2, 3, 3))
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", _Laminate("SkinLaminate", 2)),
             _Section("BandLaminate_Section", _Laminate("BandLaminate", 3))),
        write(deck), strict=False)
    assert any("sections at once" in p for p in problems)


def test_thickness_mismatch_is_found(write):
    import deckaudit

    laminate = _Laminate("SkinLaminate", 3)
    laminate.Thickness = "0.500 mm"
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1], _per_element("MaterialSkinLaminate_Section", 1, 1, 3))),
        strict=False)
    assert any("0.3000 mm, SkinLaminate is 0.5000 mm" in p for p in problems)


def test_merged_stack_is_not_mistaken_for_the_fallback(write):
    """StackModelType merges a stack: the deck then carries fewer layers
    than the laminate has plies, which is deliberate, not a bug."""
    import deckaudit

    laminate = _Laminate("SkinLaminate", 6)
    laminate.Proxy = _Proxy([0.6])
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1], [_block("MaterialSkinLaminate_Section_1", [1],
                                [0.6])])), strict=False)
    assert problems == []
    assert rows[0][3] == 1


def test_declared_isotropic_written_layered_is_found(write):
    import deckaudit

    laminate = _Laminate("FrameQILaminate", 1, isotropic=True)
    rows, problems = deckaudit.audit(
        _Doc(_Section("FrameQILaminate_Section", laminate)),
        write(_deck([1], [_block("MaterialFrameQILaminate_Section", [1],
                                [0.1], layered=True)])), strict=False)
    assert any("modelled SMEAR" in p for p in problems)


def test_section_with_nothing_meshed_is_found(write):
    import deckaudit

    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", _Laminate("SkinLaminate", 2))),
        write(_deck([1], [])), strict=False)
    assert any("nothing meshed" in p for p in problems)


def test_ply_cards_naming_another_laminate_are_found(write):
    import deckaudit

    laminate = _Laminate("SkinLaminate", 2)
    block = _block("MaterialSkinLaminate_Section_1", [1], [0.1, 0.1])
    block[-1] = "0.100,,OTHERLAMINATE:01: LAMINA"
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1], [block])), strict=False)
    assert any("reference OTHERLAMINATE" in p for p in problems)


def test_laminate_without_deck_layers_is_reported(write):
    """The audit compares against the laminate's deck layers; an empty
    stack says so rather than quietly skipping the comparison."""
    import deckaudit

    laminate = _Laminate("SkinLaminate", 3)
    laminate.Proxy = _Proxy([])
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1], _per_element("MaterialSkinLaminate_Section", 1, 1, 3))),
        strict=False)
    assert any("no FEM layer representation" in p for p in problems)


def test_laminate_that_cannot_merge_its_stack_is_reported(write):
    """A stack model the mechanics cannot apply is a failure with a
    reason, not a silent pass."""
    import deckaudit

    laminate = _Laminate("SkinLaminate", 3)
    laminate.Proxy = _BrokenProxy()
    rows, problems = deckaudit.audit(
        _Doc(_Section("SkinLaminate_Section", laminate)),
        write(_deck([1], _per_element("MaterialSkinLaminate_Section", 1, 1, 3))),
        strict=False)
    assert any("cannot produce a deck representation" in p for p in problems)


def test_strict_raises_and_lax_returns_problems(write):
    import deckaudit

    doc = _Doc(_Section("SkinLaminate_Section", _Laminate("SkinLaminate", 2)))
    deck = write(_deck([1], []))
    with pytest.raises(RuntimeError):
        deckaudit.audit(doc, deck)
    assert deckaudit.audit(doc, deck, strict=False)[1]
