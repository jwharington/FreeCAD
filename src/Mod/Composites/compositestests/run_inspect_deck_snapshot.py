#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2026 John Wharington jwharington@gmail.com

"""Small CLI wrapper for inspect_deck_snapshot.py.

Kept separate from the tool so the tool stays importable. Under ``FreeCADCmd
-c`` a SystemExit discards whatever Python has buffered, so a comparison that
ends by raising exits silently and looks like it did nothing; the status is
returned to the shell after an explicit flush instead.
"""

import sys

from compositestests.inspect_deck_snapshot import main


if __name__ == "__main__":
    status = main(sys.argv[1:])
    sys.stdout.flush()
    raise SystemExit(status)
