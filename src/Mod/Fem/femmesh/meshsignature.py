# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Signatures for geometry, so a mesh is reused only when it still fits.

A mesh is a function of two things: the shapes it was cut from, and the mesh
parameters.  Neither is stored next to the mesh, so a run that reuses a mesh
has been guessing — and the usual guess, "is the mesh empty?", cannot tell a
stale mesh from a fresh one.  A stale mesh is the worst failure available
here: the deck's element-to-shape mapping and the results' node IDs then
describe a model that no longer exists, and nothing complains.

So both are digested, and a mesh is only believed when the digest matches.
The part shapes are digested from BREP bytes: a tessellation and a set of
geometric invariants digest identically as well, but BREP costs least and is
exact rather than a lossy summary of the shape.
"""

import hashlib
import os
import subprocess
import tempfile

import FreeCAD

MESH_DATA_PROPERTY = "FemMesh"
# Properties that report the mesh back rather than asking for it.  The element
# map version moves when mesh data is assigned, and the mesh group list is
# built from the mesh's own groups — either in the signature would make the
# mesh its own key.
DERIVED_MESH_PROPERTIES = ("_ElementMapVersion", "MeshGroupList")
NOTHING = ""


def _render(value):
    """A property value as it may safely be digested.

    Two traps, both silent.  An object's default string form carries its
    address, and a signature built from addresses changes every process — the
    cache would miss forever while every run reported a clean miss as normal
    behaviour.  And a Quantity is not a number to isinstance: rendering it by
    its type collapses every element size to the same word, which would leave
    the one mesh parameter that matters out of the signature.  So repr first,
    and only objects whose repr is an address get named instead.
    """
    if isinstance(value, (bool, int, float, str)) or value is None:
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(_render(item) for item in value)
    text = repr(value)
    if " at 0x" not in text:
        return text
    name = getattr(value, "Name", None)
    if isinstance(name, str):
        return "%s:%s" % (type(value).__name__, name)
    return type(value).__name__


def mesh_parameters_text(mesh_object):
    """Every mesh parameter, so a changed element size cannot reuse a mesh.

    Everything except the mesh and what the mesh reports back.  Naming the few
    parameters that matter would silently ignore the ones forgotten — gmsh
    exposes several read only when a plugin or a boundary layer is switched
    on.  The refinement list is rendered from the objects' own properties,
    which the generic object render does not reach.
    """
    parts = []
    for name in sorted(mesh_object.PropertiesList):
        if name == MESH_DATA_PROPERTY or name in DERIVED_MESH_PROPERTIES:
            continue
        if name == "MeshRefinementList":
            continue  # rendered below, with each refinement's own properties
        parts.append("%s=%s" % (name, _render(getattr(mesh_object, name))))
    parts.append("MeshRefinementList=%s" % _render_refinements(
        getattr(mesh_object, "MeshRefinementList", ()) or ()))
    return "\n".join(parts)


_UNSTABLE_OBJECT_PROPERTIES = ("ExpressionEngine", "Label", "Proxy",
                               "ViewObject")


def _render_refinements(refinements):
    """A refinement object with its defining properties, not just its name.

    ``_render`` of the object alone ends at type and name; two refinements of
    one shape but different element sizes would hash alike, and a finer local
    size would reuse a coarser cached mesh (measured: local refinement sizes
    5 / 3 / 2 / 1.5 mm all restored one mesh).  The library object's own
    properties are rendered instead — its label and links are not, since they
    carry addresses or naming, not the mesh it asks for.
    """
    rendered = []
    for obj in refinements:
        own = ";".join(
            "%s=%s" % (name, _render(getattr(obj, name)))
            for name in sorted(obj.PropertiesList)
            if name not in _UNSTABLE_OBJECT_PROPERTIES)
        rendered.append("%s:%s[%s]"
                        % (type(obj).__name__, getattr(obj, "Name", "?"), own))
    return "[%s]" % ", ".join(rendered)


def _hex(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def shape_digest(shape):
    """Content digest of one shape, from its BREP."""
    handle, path = tempfile.mkstemp(suffix=".brep")
    os.close(handle)
    try:
        shape.exportBrep(path)
        with open(path, "rb") as written:
            return _hex(written.read().decode("latin-1"))
    finally:
        os.remove(path)


def parts_digest(parts):
    """Digest of a whole structure: names and shapes together.

    Names are included because a part that moves while nothing else does is a
    different structure for the mesh, even if every shape is unchanged; and
    sorted so that iteration order in the document cannot change the answer.
    """
    return _hex("\n".join("%s %s" % (name, shape_digest(shape))
                          for name, shape in sorted(parts.items())))


def geometry_arguments_digest(arguments):
    """Digest of the arguments the geometry was cut from.

    Deliberately excludes anything that changes only how a laminate is written
    to a deck — a stack model, a material — because those must not dirty a
    mesh: the whole value of the signature is that a layup iteration keeps the
    mesh, and with it the node numbering that makes two runs comparable.
    """
    return _hex("\n".join("%s=%s" % (key, arguments[key])
                          for key in sorted(arguments)))


def versions():
    """The versions that change geometry without a line of source changing.

    FreeCAD and OCCT because tessellation, and the naming of faces a mesh is
    built from, are properties of the geometry kernel; gmsh because its
    algorithm version decides the elements it produces from a shape.
    """
    return {"freecad": ".".join(str(part) for part in FreeCAD.Version()[:3]),
            "occ": getattr(FreeCAD, "getOccVersionString", lambda: NOTHING)(),
            "gmsh": _gmsh_version()}


def versions_digest():
    """Digest of :func:`versions`."""
    return _hex("\n".join("%s=%s" % (name, versions()[name])
                          for name in sorted(versions())))


def _gmsh_version():
    """gmsh's own version string, or why it could not be asked."""
    path = FreeCAD.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/Fem/Gmsh").GetString("gmshBinaryPath")
    if not path or not os.path.isfile(path):
        return "not configured"
    try:
        return subprocess.run([path, "--version"], capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        return "unavailable (%s)" % type(error).__name__


def builder_digest(path):
    """The builder script's own text, so an edited script changes the signature.

    A commit hash alone is not enough: the file being run may be uncommitted
    work, and the signature must describe the geometry that was actually cut.
    The path is required — a default would name one application's builder in a
    module every workbench shares.
    """
    with open(path, encoding="utf-8") as source:
        return _hex(source.read())


def mesh_parameters_digest(mesh_object):
    """Digest of :func:`mesh_parameters_text`."""
    return _hex(mesh_parameters_text(mesh_object))


def geometry_components(parts, arguments, builder_path):
    """What the geometry is, as the parts it is made of.

    Kept in pieces rather than flattened into one value so that a mismatch can
    be explained: ``shapes`` moving is a rebuilt model, ``arguments`` moving is
    a changed knob, ``versions`` moving is the machine, and ``builder`` moving
    is an edited script.
    """
    return {"shapes": parts_digest(parts),
            "arguments": geometry_arguments_digest(arguments),
            "versions": versions_digest(),
            "builder": builder_digest(builder_path)}


def digest_of(components):
    """One value for a set of components, for use as a cache key."""
    return _hex("\n".join("%s=%s" % (name, components[name])
                          for name in sorted(components)))


def mesh_components(geometry, mesh_object):
    """What the mesh is: the geometry components it was cut from, plus how it
    was cut.

    One flat set, because that is what makes a mismatch explainable: "the
    geometry digest moved" says nothing, "arguments moved" says a knob
    changed, "parameters moved" says the geometry is fine and an element size
    did not.  The geometry's own parts stay named here rather than being hashed
    away into one value.
    """
    flat = dict(geometry)
    flat["parameters"] = mesh_parameters_digest(mesh_object)
    return flat


def explain(earlier, later):
    """Which component of a signature changed, in words, for the run log.

    "stale" is not actionable.  "arguments 3f1a.. -> 9b7c.. (band width and
    schedule are the arguments)" is — the components are named here and read
    against the table in the cache.
    """
    changed = [name for name in sorted(set(earlier) & set(later))
               if earlier[name] != later[name]]
    if not changed:
        return "nothing in the signature differs, so a different mesh was " \
               "found under the same signature"
    return ", ".join("%s %s..->%s.." % (name, earlier[name][:4], later[name][:4])
                     for name in changed)
