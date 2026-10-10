# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Meshes kept under the signature that made them.

A cached mesh is only worth having if restoring it is the same as meshing
again, down to the node numbering: the deck's element blocks and the results'
node IDs are both read positionally, so a mesh whose nodes were renumbered on
restore would report a displacement belonging to a different node.  That is
why the mesh lives in a document of its own — which is how FreeCAD already
proves it can persist a mesh — rather than in a mesh file format.

The key is the geometry signature from :mod:`meshsignature`, which covers the
geometry and the mesh parameters.  A JSON file beside the saved mesh records
the components the signature was made of, so a mismatch can be explained
rather than merely noticed.  The cache root is always an argument: a module
that writes to a fixed location is not one a shared workbench can adopt.
"""

import datetime
import json
import os

import FreeCAD

MESH_OBJECT = "Mesh"
STAGING = "staging"
LATEST = "latest.json"


def _counts(fem_mesh):
    """How many elements: shells, and volumes if the mesh has any."""
    return fem_mesh.FaceCount + getattr(fem_mesh, "VolumeCount", 0)


def ensure_root(cache_root):
    """Create the cache directory if it is not there, and return it."""
    if not os.path.isdir(cache_root):
        os.makedirs(cache_root)
    return cache_root


def paths(cache_root, digest):
    return (os.path.join(cache_root, "%s.FCStd" % digest),
            os.path.join(cache_root, "%s.json" % digest))


def _active_name():
    """The run's document, asked for before this module creates another."""
    active = FreeCAD.ActiveDocument
    return active.Name if active is not None else None


def _close(document, was_active):
    """Close a cache document and give the run its document back.

    FreeCAD's ``closeDocument`` clears ``ActiveDocument`` whichever document
    closed, and a great deal of the FEM code reaches for
    ``FreeCAD.ActiveDocument`` rather than for a document it was handed.  So a
    cache read that closed its own document left the run with no active
    document, and the failure surfaced much later, inside result loading, as
    "'NoneType' object has no attribute 'getObject'".

    The caller captures the name before this module creates another document,
    because creating one makes it the active document, and a name outlives a
    document another caller has already closed where an object would raise
    ``ReferenceError``.
    """
    name = document.Name
    FreeCAD.closeDocument(name)
    if was_active and was_active in FreeCAD.listDocuments():
        FreeCAD.setActiveDocument(was_active)


def store(cache_root, digest, fem_mesh, components, note=None):
    """Write a mesh and what it was made from, under its signature.

    Saved in a staging subdirectory and then moved in, because ``saveAs``
    names the format by extension — a ``.part`` file is not an FCStd at all.  A
    run that dies halfway therefore leaves no half-written mesh where a later
    run could find it.
    """
    ensure_root(cache_root)
    document_path, meta_path = paths(cache_root, digest)
    staging = os.path.join(cache_root, STAGING)
    if not os.path.isdir(staging):
        os.makedirs(staging)
    for path in (document_path, meta_path):
        if os.path.exists(path):
            os.remove(path)
    staged = os.path.join(staging, "%s.FCStd" % digest)
    was_active = _active_name()
    document = FreeCAD.newDocument("mesh_" + digest[:12])
    obj = document.addObject("Fem::FemMeshObject", MESH_OBJECT)
    obj.FemMesh = fem_mesh
    document.saveAs(staged)
    _close(document, was_active)
    os.replace(staged, document_path)
    with open(os.path.join(staging, "%s.json" % digest), "w") as handle:
        json.dump(dict(components=components,
                       nodes=fem_mesh.NodeCount,
                       elements=_counts(fem_mesh),
                       written=datetime.datetime.now().isoformat(timespec="seconds"),
                       note=note or ""), handle, indent=1, sort_keys=True)
    os.replace(os.path.join(staging, "%s.json" % digest), meta_path)
    return document_path


def load(cache_root, digest, mesh_object):
    """Restore the cached mesh into ``mesh_object``, or say there is none.

    Returns ``(found, nodes, elements)``.  Found means the file was readable
    and produced a non-empty mesh: a document that opens to an empty mesh is a
    failed save, not a hit, and must not be believed.
    """
    document_path, _ = paths(cache_root, digest)
    if not os.path.isfile(document_path):
        return False, 0, 0
    was_active = _active_name()
    document = FreeCAD.openDocument(document_path)
    cached = document.getObject(MESH_OBJECT)
    if cached is None or not cached.FemMesh.NodeCount:
        _close(document, was_active)
        raise RuntimeError("mesh cache file %s holds no mesh — delete it and "
                           "let the next run mesh again" % document_path)
    mesh_object.FemMesh = cached.FemMesh
    counts = (cached.FemMesh.NodeCount, _counts(cached.FemMesh))
    _close(document, was_active)
    return True, counts[0], counts[1]


def note(cache_root, digest, components, fem_mesh, outcome):
    """Record what this run signed and decided, for the next run to compare
    against.

    A miss has no key to look up — that is what a miss is — so the only way to
    say why the mesh changed is to remember the previous signature.  Without
    this a run can only report "meshing", and "because the band width moved"
    is the useful half of that sentence.
    """
    ensure_root(cache_root)
    with open(os.path.join(cache_root, LATEST), "w") as handle:
        json.dump(dict(digest=digest,
                       components=components,
                       nodes=fem_mesh.NodeCount,
                       elements=_counts(fem_mesh),
                       outcome=outcome,
                       written=datetime.datetime.now().isoformat(timespec="seconds")),
                  handle, indent=1, sort_keys=True)


def latest(cache_root):
    """What the last run signed, or None if nothing has run here yet."""
    path = os.path.join(cache_root, LATEST)
    if not os.path.isfile(path):
        return None
    with open(path) as handle:
        return json.load(handle)


def components_of(cache_root, digest):
    """The components a cached mesh was signed with, or None."""
    _, meta_path = paths(cache_root, digest)
    if not os.path.isfile(meta_path):
        return None
    with open(meta_path) as handle:
        return json.load(handle).get("components")
