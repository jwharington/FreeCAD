# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the document-object helpers (Composites.util.object_util) and
the stack-model pass (Composites.util.stack_util)."""

import FreeCAD
import Part
import pytest

from Composites.mechanics import StackModelType
from Composites.util.object_util import (
    attach_view_provider,
    is_composite_geometry,
    shape_object,
)
from Composites.util.stack_util import apply_stack_model


@pytest.fixture
def doc():
    document = FreeCAD.newDocument("TestObjectUtil")
    yield document
    FreeCAD.closeDocument(document.Name)


def test_shape_object_holds_the_shape_under_the_name():
    document = FreeCAD.newDocument("TestShapeObject")
    try:
        obj = shape_object(document, "Plate", Part.makeBox(1.0, 2.0, 3.0))
        assert obj.Name == "Plate"
        assert obj.Shape.Volume == pytest.approx(6.0)
    finally:
        FreeCAD.closeDocument(document.Name)


class _View:
    def __init__(self):
        self.Proxy = None


class _Object:
    def __init__(self):
        self.ViewObject = _View()


class _ViewProvider:
    def __init__(self, view):
        view.Proxy = self


class _NoView:
    pass


def test_attach_view_provider_installs_one_view_provider():
    obj = _Object()
    attach_view_provider(obj, _ViewProvider)
    assert isinstance(obj.ViewObject.Proxy, _ViewProvider)


def test_attach_view_provider_leaves_an_existing_one_alone():
    """Re-attaching re-runs the constructor, which re-adds its properties
    and raises — so a second call must be a no-op."""
    obj = _Object()
    attach_view_provider(obj, _ViewProvider)
    installed = obj.ViewObject.Proxy
    attach_view_provider(obj, _ViewProvider)
    assert obj.ViewObject.Proxy is installed


def test_attach_view_provider_does_nothing_headless():
    """No ViewObject (a headless FreeCADCmd) is not an error."""
    assert attach_view_provider(_NoView(), _ViewProvider) is None


class _Proxy:
    def __init__(self, type_id):
        self.Type = type_id


class _Feature:
    def __init__(self, proxy):
        self.Proxy = proxy


def test_is_composite_geometry_accepts_only_a_composite_shell():
    assert is_composite_geometry(_Feature(_Proxy("Composite::Shell")))
    assert not is_composite_geometry(_Feature(_Proxy("Part::Feature")))
    assert not is_composite_geometry(_Feature(None))
    assert not is_composite_geometry(object())


def _laminate(doc, name, model_type="Discrete"):
    obj = doc.addObject("App::FeaturePython", name)
    obj.addProperty("App::PropertyEnumeration", "StackModelType", "Test")
    obj.StackModelType = [member.name for member in StackModelType]
    obj.StackModelType = model_type
    return obj


def test_apply_stack_model_sets_every_laminate(doc):
    laminates = [_laminate(doc, "LamA"), _laminate(doc, "LamB")]
    groups = [(lam, []) for lam in laminates]
    apply_stack_model(doc, groups, "Smeared")
    for lam in laminates:
        assert lam.StackModelType == "Smeared"


def test_apply_stack_model_refuses_a_model_it_does_not_have(doc):
    with pytest.raises(RuntimeError, match="stack model"):
        apply_stack_model(doc, [], "NotAModel")


def test_apply_stack_model_refuses_a_laminate_it_cannot_reach(doc):
    """A laminate named in the groups but carrying no StackModelType would
    leave the deck's stack model unknowable, so the pass fails."""
    orphan = doc.addObject("App::FeaturePython", "Orphan")
    with pytest.raises(RuntimeError, match="Orphan"):
        apply_stack_model(doc, [(orphan, [])], "Smeared")
