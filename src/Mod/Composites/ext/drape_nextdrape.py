"""Lazy proxy for drape_nextdrape C++ extension.

Native .so lives in _native/ subdirectory. Loaded via spec_from_file_location
to avoid Python's package-relative import machinery which conflicts with
FreeCAD's OCC initialization timing.
"""
import importlib.util
import os
import sys

_NATIVE_SO = os.path.join(os.path.dirname(__file__), "_native", "drape_nextdrape.cpython-311-x86_64-linux-gnu.so")
_MOD = None


def _load():
    global _MOD
    if _MOD is not None:
        return _MOD
    if not os.path.isfile(_NATIVE_SO):
        return None
    spec = importlib.util.spec_from_file_location("drape_nextdrape", _NATIVE_SO)
    if spec is None or spec.loader is None:
        return None
    _MOD = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(_MOD)
    except Exception:
        _MOD = None
        raise
    return _MOD


def __getattr__(name):
    mod = _load()
    if mod is None:
        raise ImportError("drape_nextdrape C++ extension not available")
    return getattr(mod, name)


def __dir__():
    mod = _load()
    return dir(mod) if mod else []
