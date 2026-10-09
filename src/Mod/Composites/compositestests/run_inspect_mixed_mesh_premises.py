#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Small CLI wrapper for inspect_mixed_mesh_premises.py.

FreeCADCmd leaves its own switches in sys.argv when it runs a script through
``-c``, so the arguments are filtered down to the case names this probe knows
before they reach the parser. The explicit flush matters too: under
``FreeCADCmd -c`` a SystemExit discards whatever Python has buffered, so
without it the wrapper exits silently and looks like it did nothing.
"""

import sys

from compositestests.inspect_mixed_mesh_premises import CASES, main


if __name__ == "__main__":
    status = main([arg for arg in sys.argv[1:] if arg in CASES])
    sys.stdout.flush()
    raise SystemExit(status)
