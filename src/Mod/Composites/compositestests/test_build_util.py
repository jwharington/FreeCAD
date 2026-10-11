# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright 2025 John Wharington jwharington@gmail.com

"""Tests for the build progress/console helpers (Composites.util.build_util)."""

import contextlib
import io

from Composites.util.build_util import BuildLog, silence_occt_chatter


def _capture():
    stream = io.StringIO()
    return stream, contextlib.redirect_stdout(stream)


def test_a_line_carries_the_build_prefix_and_its_message():
    log = BuildLog("widget")
    stream, redirect = _capture()
    with redirect:
        log("build start")
    assert stream.getvalue().startswith("[widget +")
    assert "build start" in stream.getvalue()


def test_the_clock_starts_at_the_first_line_not_at_import():
    """One log's elapsed time is its own, so the prefix names the build and
    the seconds measure from when that build spoke first."""
    log = BuildLog("widget")
    stream, redirect = _capture()
    with redirect:
        log("first")
    first = stream.getvalue().strip()
    assert first.startswith("[widget +")
    assert "first" in first


def test_timed_returns_the_result_and_brackets_the_phase():
    log = BuildLog("widget")

    def phase(value):
        return value * 2

    stream, redirect = _capture()
    with redirect:
        assert log.timed("doubling", phase, 21) == 42
    text = stream.getvalue()
    assert "doubling..." in text
    assert "doubling done in" in text


def test_two_logs_keep_separate_timelines():
    first = BuildLog("first")
    second = BuildLog("second")
    stream, redirect = _capture()
    with redirect:
        first("a")
        second("b")
    lines = stream.getvalue().splitlines()
    assert lines[0].startswith("[first +")
    assert lines[1].startswith("[second +")


def test_silence_occt_chatter_is_idempotent_and_silent():
    """Muting the Msg channel twice is a no-op, not an error."""
    assert silence_occt_chatter() is None
    assert silence_occt_chatter() is None
