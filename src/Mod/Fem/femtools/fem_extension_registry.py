# SPDX-License-Identifier: LGPL-2.1-or-later

"""Extension registry for optional composites integrations.

FEM core stays generic and exposes a few plugin seams. External workbenches
(such as CompositesWB) can register providers at runtime.
"""

_shell_orientation_providers = {}
_shell_section_providers = {}
_shell_section_dimension_providers = {}
_indirect_material_providers = {}


def _register(registry, name, fn):
    if not name:
        raise ValueError("Provider name must be non-empty")
    if not callable(fn):
        raise TypeError("Provider must be callable")
    registry[name] = fn


def _unregister(registry, name):
    registry.pop(name, None)


def _providers(registry):
    return [registry[k] for k in sorted(registry.keys())]


def register_shell_orientation_provider(name, fn):
    _register(_shell_orientation_providers, name, fn)


def unregister_shell_orientation_provider(name):
    _unregister(_shell_orientation_providers, name)


def register_shell_section_provider(name, fn):
    _register(_shell_section_providers, name, fn)


def unregister_shell_section_provider(name):
    _unregister(_shell_section_providers, name)


def register_shell_section_dimension_provider(name, fn):
    _register(_shell_section_dimension_providers, name, fn)


def unregister_shell_section_dimension_provider(name):
    _unregister(_shell_section_dimension_providers, name)


def register_indirect_material_provider(name, fn):
    _register(_indirect_material_providers, name, fn)


def unregister_indirect_material_provider(name):
    _unregister(_indirect_material_providers, name)


def get_shell_orientation_overrides(shellth_obj, femmesh_obj, elements, orientation=None):
    result = {}
    if orientation is not None:
        result["orientation"] = orientation

    for provider in _providers(_shell_orientation_providers):
        try:
            update = provider(shellth_obj, femmesh_obj, elements, result.get("orientation"))
        except Exception:
            continue
        if isinstance(update, dict):
            result.update(update)

    return result


def get_shell_section_override(shellth_obj, matgeoset, orientation_name):
    for provider in _providers(_shell_section_providers):
        try:
            override = provider(shellth_obj, matgeoset, orientation_name)
        except Exception:
            continue
        if isinstance(override, dict) and override:
            return override
    return None


def get_shell_section_dimensions(shellth_obj):
    """The thickness and offset a section will be written with, or ``None``.

    A provider owns the mapping from a section object to the values its deck
    card uses; a caller that reads them -- a tolerance check that runs before
    the card is written, for one -- falls back to the object's own properties
    when no provider answers.
    """
    for provider in _providers(_shell_section_dimension_providers):
        try:
            dimensions = provider(shellth_obj)
        except Exception:
            continue
        if isinstance(dimensions, dict) and dimensions:
            return dimensions
    return None


def get_indirect_materials(geos_shellthickness):
    materials = []
    for provider in _providers(_indirect_material_providers):
        try:
            provided = provider(geos_shellthickness)
        except Exception:
            continue
        if isinstance(provided, (list, tuple)):
            materials.extend(provided)
    return materials
