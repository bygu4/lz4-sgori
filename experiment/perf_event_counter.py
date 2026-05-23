#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only

"""
Helper script for perf to aggregate event counts.
Used by: perf script -s perf_event_counter.py -i perf.data
"""

counters = {
    'cycles': 0,
    'instructions': 0,
    'branches': 0,
    'branch-misses': 0,
    'cache-references': 0,
    'cache-misses': 0,
    'L1-dcache-load-misses': 0,
    'LLC-load-misses': 0,
    'page-faults': 0,
}


def trace_begin():
    """Called at start of processing."""
    pass


def trace_end():
    """Called at end of processing - output results."""
    for key, value in counters.items():
        if value > 0:
            clean_key = key.replace('-', '_')
            print(f"PERF_COUNTER:{clean_key}:{value:.0f}")


def trace_unhandled(event_name, context, event_fields_dict):
    """Handle raw events directly."""
    # Parse event name from the raw event
    if ':' in event_name:
        ev_name = event_name.split(':')[0]
    else:
        ev_name = event_name
    
    # Try to get period from event fields
    period = 1
    if 'period' in event_fields_dict:
        try:
            period = int(event_fields_dict['period'])
        except (ValueError, TypeError):
            pass
    elif 'sample_period' in event_fields_dict:
        try:
            period = int(event_fields_dict['sample_period'])
        except (ValueError, TypeError):
            pass
    
    if ev_name in counters:
        counters[ev_name] += period


def process_event(param_dict):
    """Process events using the param_dict method."""
    ev_name = param_dict.get('ev_name', '')
    if ':' in ev_name:
        ev_name = ev_name.split(':')[0]
    
    period = param_dict.get('period', 1)
    if period == 0:
        period = 1
    
    if ev_name in counters:
        counters[ev_name] += period