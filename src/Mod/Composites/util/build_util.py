# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Progress, timing and console handling for a long geometry build.

Building a whole airframe takes minutes and creates hundreds of objects, so
a build needs three things a bare ``print`` does not give it: a progress line
that says which stage is running and how long the run has been going, a way
to time one stage without wrapping every call, and silence for OCCT's
info/trace chatter, which otherwise buries both.

The implementation is here so a part's builder does not have to carry its
own copy; a build names itself with a :class:`BuildLog` and the timeline is
its own.
"""

import time

import FreeCAD


class BuildLog:
    """A timestamped progress log for one build, named after the part.

    The prefix and the clock belong to the build, not to the module: two
    builds in one interpreter keep separate timelines, and a stage that hangs
    is identifiable from the last line and its elapsed time.
    """

    def __init__(self, prefix):
        self._prefix = prefix
        self._t0 = None

    def __call__(self, message):
        """One progress line, flushed and timestamped from the build's start."""
        if self._t0 is None:
            self._t0 = time.perf_counter()
        print("[%s +%7.1fs] %s"
              % (self._prefix, time.perf_counter() - self._t0, message),
              flush=True)

    def timed(self, label, func, *args, **kwargs):
        """Run one build phase, logging its name and wall time."""
        self("%s..." % label)
        started = time.perf_counter()
        result = func(*args, **kwargs)
        self("%s done in %.1fs" % (label, time.perf_counter() - started))
        return result


def silence_occt_chatter():
    """Mute OCCT's info/trace chatter on FreeCAD's console.

    FreeCAD routes every OCCT ``Message_Info``/``Message_Trace`` through
    ``Base::Console().message()`` (Part/App/OCCTMessagePrinter.cpp), so a
    single large boolean emits tens of thousands of "Filling splits of
    edges..." lines and buries the build's own progress.  Muting only the
    ``Msg`` channel leaves OCCT warnings and errors visible.
    """
    console = getattr(FreeCAD, "Console", None)
    if console is None:
        return
    try:
        observers = console.GetObservers()
    except Exception:
        observers = ("Console",)
    for observer in observers:
        try:
            console.SetStatus(observer, "Msg", False)
        except Exception:
            pass
