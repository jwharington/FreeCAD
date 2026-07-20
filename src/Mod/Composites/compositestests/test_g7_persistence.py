#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later

"""G7 persistence regression: save conical panel to .FCStd, reload in a
fresh document, verify drape state survives and the shader re-attaches.

Objective, machine-checkable evidence for the G7 "drape state ownership"
requirement — no visual inspection. Requires GUI (ViewObject/shader state
inspection), so skips headless.
"""

import json
import os
import tempfile
import unittest

import FreeCAD


def _shell_of(doc):
    for obj in doc.Objects:
        if obj.Name.endswith("Shell"):
            return obj
    return None


def _shell_state(shell):
    """Capture objective drape/shader state from a shell object."""
    import numpy as np

    fp = shell.Proxy
    backend = getattr(fp, "_backend", None)
    state = {
        "DrapeValid": bool(getattr(shell, "DrapeValid", False)),
        "QualityPass": bool(getattr(shell, "QualityPass", False)),
        "DrapeQuality_repr": repr(getattr(shell, "DrapeQuality", None)),
        "has_backend": backend is not None,
        "backend_valid": bool(backend.is_valid()) if backend else False,
    }
    if backend and backend.is_valid():
        try:
            tex = backend.get_tex_coords()
            arr = np.array(tex) if tex else np.empty((0, 2))
            state["tex_coords_len"] = int(len(arr))
            state["tex_coords_nonzero"] = bool(len(arr) > 0)
        except Exception as e:  # noqa: BLE001
            state["tex_coords_error"] = str(e)
    vobj = getattr(shell, "ViewObject", None)
    if vobj is not None:
        vp = getattr(vobj, "Proxy", None)
        if vp is not None:
            gs = getattr(vp, "grid_shader", None)
            state["shader_present"] = gs is not None
            state["shader_attached"] = bool(getattr(gs, "_attached", False)) if gs else False
            state["shader_coin_geo"] = (
                str(gs._coin_geo.getName()) if gs and getattr(gs, "_coin_geo", None) else None
            )
            dh = getattr(vp, "drape_host", None)
            if dh is not None:
                state["drape_host_children"] = int(dh.getNumChildren())
                state["drape_host_child_names"] = [
                    str(dh.getChild(i).getName()) for i in range(int(dh.getNumChildren()))
                ]
    return state


class TestG7Persistence(unittest.TestCase):
    save_fcstd = True

    def tearDown(self):
        for d in list(FreeCAD.listDocuments()):
            try:
                FreeCAD.closeDocument(d)
            except Exception:
                pass

    def test_conical_panel_drape_and_shader_survive_reload(self):
        if not getattr(FreeCAD, "GuiUp", False):
            self.skipTest("GUI not available — shader/persistence needs MCP/GUI mode")

        from Composites.compositeexamples.examples import conical_panel_segment

        # ── Build ──
        result = conical_panel_segment.build(doc=None, run_solver=False)
        shell = result["feature_stack"]["shell"]
        before = _shell_state(shell)

        self.assertTrue(before["DrapeValid"], "drape must be valid before save")
        self.assertTrue(before["backend_valid"], "backend must be valid before save")
        self.assertTrue(before["shader_attached"], "shader must be attached before save")
        self.assertEqual(before["shader_coin_geo"], "SupportSurface")
        self.assertNotIn("DrapedMeshGeometry", before.get("drape_host_child_names", []))

        # ── Save ──
        path = os.path.join(tempfile.gettempdir(), "g7_persistence_test.FCStd")
        FreeCAD.ActiveDocument.saveAs(path)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 0)

        # ── Reload in a fresh document ──
        FreeCAD.closeDocument(FreeCAD.ActiveDocument.Name)
        doc = FreeCAD.openDocument(path)
        FreeCAD.setActiveDocument(doc.Name)
        shell2 = _shell_of(doc)
        self.assertIsNotNone(shell2, "shell must reload from .FCStd")
        doc.recompute()

        after = _shell_state(shell2)

        # ── Objective assertions ──
        self.assertTrue(after["DrapeValid"], "drape must be valid after reload")
        self.assertEqual(
            after["DrapeValid"], before["DrapeValid"], "DrapeValid must be preserved"
        )
        self.assertTrue(after["has_backend"], "backend must be recreated on restore")
        self.assertTrue(after["backend_valid"], "backend must be valid after reload")
        self.assertTrue(after["tex_coords_nonzero"], "tex coords must be repopulated")
        self.assertEqual(
            after["tex_coords_len"], before["tex_coords_len"],
            "tex coord count must match before/after (deterministic re-solve)",
        )
        self.assertEqual(
            after["DrapeQuality_repr"], before["DrapeQuality_repr"],
            "drape quality metrics must be identical (deterministic)",
        )
        self.assertTrue(after["shader_present"], "shader must be present after reload")
        self.assertTrue(after["shader_attached"], "shader must re-attach after reload")
        self.assertEqual(
            after["shader_coin_geo"], "SupportSurface",
            "shader must re-attach to SupportSurface after reload",
        )
        self.assertNotIn(
            "DrapedMeshGeometry", after.get("drape_host_child_names", []),
            "drape_host must remain mesh-free after reload",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
