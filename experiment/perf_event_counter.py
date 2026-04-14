#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Alexander Bugaev
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.

"""
Helper script for perf to aggregate event counts.
Used by: perf script -s perf_event_counter.py -i perf.data
"""

import os
import sys
from collections import defaultdict

# Add perf's Python modules to path
perf_exec_path = os.environ.get("PERF_EXEC_PATH", "/usr/libexec/perf-core")
sys.path.append(perf_exec_path + "/scripts/python/Perf-Trace-Util/lib/Perf/Trace")

try:
    from Core import *
    from perf_trace_context import *
except ImportError:
    pass

counters = defaultdict(float)


def trace_begin():
    """Called at start of processing."""
    pass


def trace_end():
    """Called at end of processing - output results."""
    for key, value in counters.items():
        print(f"PERF_COUNTER:{key}:{value:.0f}")


def process_event(param_dict):
    """Process all sample events."""
    ev_name = param_dict.get("ev_name", "")

    if "cycles" in ev_name:
        counters["cycles"] += param_dict.get("period", 1)
    elif "instructions" in ev_name:
        counters["instructions"] += param_dict.get("period", 1)
    elif ev_name == "branches":
        counters["branches"] += param_dict.get("period", 1)
    elif ev_name == "branch-misses":
        counters["branch_misses"] += param_dict.get("period", 1)
    elif ev_name == "cache-references":
        counters["cache_references"] += param_dict.get("period", 1)
    elif ev_name == "cache-misses":
        counters["cache_misses"] += param_dict.get("period", 1)
    elif ev_name == "L1-dcache-load-misses":
        counters["l1_dcache_load_misses"] += param_dict.get("period", 1)
    elif ev_name == "LLC-load-misses":
        counters["llc_load_misses"] += param_dict.get("period", 1)
    elif ev_name == "page-faults":
        counters["page_faults"] += param_dict.get("period", 1)


def trace_unhandled(event_name, context, event_fields_dict):
    """Handle events without specific handlers."""
    pass
