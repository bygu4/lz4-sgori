#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Copyright (C) 2026 Alexander Bugaev
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""
Generate performance comparison graphs from perf profiling data.
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from json import load
from pathlib import Path
from statistics import mean, stdev
from subprocess import run
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
from numpy import arange

plt.switch_backend("svg")

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.labelsize": 12,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "legend.fontsize": 9,
        "legend.frameon": False,
        "lines.linewidth": 1,
        "grid.linestyle": "--",
        "grid.alpha": 0.3,
        "errorbar.capsize": 3,
    }
)


@dataclass
class PerfStats:
    """Container for perf statistics."""

    cycles: float = 0.0
    instructions: float = 0.0
    branches: float = 0.0
    branch_misses: float = 0.0
    cache_references: float = 0.0
    cache_misses: float = 0.0
    l1_dcache_load_misses: float = 0.0
    llc_load_misses: float = 0.0
    page_faults: float = 0.0

    @property
    def ipc(self) -> float:
        """Instructions per cycle."""
        return self.instructions / self.cycles if self.cycles > 0 else 0.0

    @property
    def branch_hits(self) -> float:
        """Calculate branch hits."""
        if self.branches > 0 and self.branches >= self.branch_misses:
            return max(0.0, self.branches - self.branch_misses)
        return 0.0

    @property
    def cache_hits(self) -> float:
        """Calculate cache hits - only if references > misses."""
        if self.cache_references > 0 and self.cache_references >= self.cache_misses:
            return self.cache_references - self.cache_misses
        return 0.0

    @property
    def has_valid_cache_data(self) -> bool:
        """Check if cache data is valid (references >= misses)."""
        return self.cache_references > 0 and self.cache_references >= self.cache_misses

    @property
    def has_valid_branch_data(self) -> bool:
        """Check if branch data is valid (branches >= misses)."""
        return self.branches > 0 and self.branches >= self.branch_misses


class PerfGraphGenerator:
    COMPRESSION_TYPES = ["cont", "vect", "strm", "extd"]
    COMPRESSION_NAMES = {
        "cont": "Contiguous",
        "vect": "Vectorized",
        "strm": "Streaming",
        "extd": "Extended",
    }

    COLORS = {"cont": "#1f77b4", "vect": "#ff7f0e", "strm": "#2ca02c", "extd": "#d62728"}

    def __init__(self, result_dir: Path, perf_dir: Path, graph_dir: Path):
        self.result_dir = Path(result_dir)
        self.perf_dir = Path(perf_dir)
        self.graph_dir = Path(graph_dir)
        self.graph_dir.mkdir(parents=True, exist_ok=True)

        # Path to the helper script (assumed to be in the same directory)
        self.helper_script = Path(__file__).parent / "perf_event_counter.py"

        # Cache for perf data
        self._perf_cache: Dict[str, PerfStats] = {}
        
        # Store loaded results for use across methods
        self._results: Dict[str, Dict[str, List[Tuple[PerfStats, PerfStats]]]] = {}

    def _get_perf_stats_fallback(self, perf_file: Path) -> Optional[PerfStats]:
        """Fallback method using perf report directly."""
        if not perf_file.exists():
            return None
        
        stats = PerfStats()
        
        # Use perf report to get total event counts
        cmd = ["perf", "report", "-i", str(perf_file), "--stdio", "--sort=sym", "--no-children"]
        result = run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return None
        
        # Parse the header to find total samples for each event
        current_event = None
        total_samples = 0
        lz4_percent = 0.0
        
        for line in result.stdout.split("\n"):
            line = line.strip()
            
            # Check for event headers
            if "of event" in line:
                # Parse "Samples: 10K of event 'cycles'"
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "event" and i + 1 < len(parts):
                        current_event = parts[i + 1].strip("'")
                        # Get sample count
                        for j, q in enumerate(parts):
                            if q == "Samples:" and j + 1 < len(parts):
                                samples_str = parts[j + 1]
                                if samples_str.endswith('K'):
                                    total_samples = int(float(samples_str[:-1]) * 1000)
                                elif samples_str.endswith('M'):
                                    total_samples = int(float(samples_str[:-1]) * 1000000)
                                else:
                                    try:
                                        total_samples = int(samples_str)
                                    except:
                                        total_samples = 0
                        break
            
            # Parse LZ4 percentage for current event
            if current_event and line and not line.startswith("#") and line.endswith('%'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pct = float(parts[0].rstrip('%'))
                        sym = parts[1]
                        if 'lz4' in sym.lower():
                            lz4_percent += pct
                    except:
                        pass
            
            # When we finish an event section, estimate counts
            if current_event and (line.startswith("#") or line == ""):
                if total_samples > 0 and lz4_percent > 0:
                    estimated = int(total_samples * lz4_percent / 100)
                    if current_event == 'cycles':
                        stats.cycles = estimated
                    elif current_event == 'instructions':
                        stats.instructions = estimated
                    elif current_event == 'branches':
                        stats.branches = estimated
                    elif current_event == 'branch-misses':
                        stats.branch_misses = estimated
                    elif current_event == 'cache-references':
                        stats.cache_references = estimated
                    elif current_event == 'cache-misses':
                        stats.cache_misses = estimated
                
                # Reset for next event
                current_event = None
                total_samples = 0
                lz4_percent = 0.0
        
        # Check if we got any data
        if stats.cycles > 0 or stats.instructions > 0 or stats.branches > 0:
            print(f"        Fallback: cycles={stats.cycles:,.0f}, branches={stats.branches:,.0f}")
            return stats
        
        return None

    def _get_perf_stats(self, perf_file: Path) -> Optional[PerfStats]:
        """Get perf statistics from a perf.data file."""
        if not perf_file.exists():
            return None

        cache_key = str(perf_file)
        if cache_key in self._perf_cache:
            return self._perf_cache[cache_key]

        # Try helper script first
        if self.helper_script.exists():
            try:
                result = run(
                    ["perf", "script", "-s", str(self.helper_script), "-i", str(perf_file)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                stats = PerfStats()
                has_any_data = False

                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if line.startswith("PERF_COUNTER:"):
                            parts = line.split(":")
                            if len(parts) == 3:
                                key = parts[1]
                                try:
                                    value = float(parts[2])
                                    if hasattr(stats, key):
                                        setattr(stats, key, value)
                                        if value > 0:
                                            has_any_data = True
                                except ValueError:
                                    pass

                if has_any_data:
                    self._perf_cache[cache_key] = stats
                    print(
                        f"        Extracted: cycles={stats.cycles:,.0f}, "
                        f"instructions={stats.instructions:,.0f}, "
                        f"branches={stats.branches:,.0f}, "
                        f"branch_misses={stats.branch_misses:,.0f}"
                    )
                    if stats.cache_references > 0:
                        if stats.has_valid_cache_data:
                            rate = (stats.cache_misses / stats.cache_references) * 100
                            print(
                                f"          Cache: refs={stats.cache_references:,.0f}, "
                                f"misses={stats.cache_misses:,.0f}, "
                                f"rate={rate:.1f}%"
                            )
                    return stats

            except Exception as e:
                print(f"      Helper script failed: {e}")

        # Fallback to perf report parsing
        stats = self._get_perf_stats_fallback(perf_file)
        if stats:
            self._perf_cache[cache_key] = stats
            return stats

        return None

    def load_results_and_perf(self) -> bool:
        """Load result JSON files and corresponding perf data.
        
        Returns:
            True if valid perf data was found, False otherwise.
        """
        self._results = {}

        print("\nLoading perf data...")

        for comp_type in self.COMPRESSION_TYPES:
            comp_dir = self.result_dir / comp_type
            if not comp_dir.exists():
                continue

            json_files = list(comp_dir.glob("*.json"))
            if not json_files:
                continue

            print(f"  Processing {comp_type}: {len(json_files)} files")

            for json_file in json_files:
                try:
                    with open(json_file) as f:
                        data = load(f)

                    test_file_name = Path(data["test_file"]).stem
                    run_num = data["run_number"]

                    if test_file_name not in self._results:
                        self._results[test_file_name] = {ct: [] for ct in self.COMPRESSION_TYPES}

                    read_perf_file = (
                        self.perf_dir / comp_type / test_file_name / f"run{run_num}" / "read.data"
                    )
                    write_perf_file = (
                        self.perf_dir / comp_type / test_file_name / f"run{run_num}" / "write.data"
                    )

                    read_stats = self._get_perf_stats(read_perf_file)
                    write_stats = self._get_perf_stats(write_perf_file)

                    if read_stats and write_stats:
                        self._results[test_file_name][comp_type].append((read_stats, write_stats))
                    else:
                        print(
                            f"      Warning: Could not extract perf data for {test_file_name} run {run_num}"
                        )

                except Exception as e:
                    print(f"    Error processing {json_file}: {e}")

        # Filter out test files with no data
        self._results = {
            test_file: comp_data
            for test_file, comp_data in self._results.items()
            if any(len(runs) > 0 for runs in comp_data.values())
        }

        total_datapoints = sum(
            len(self._results[test_file][comp_type])
            for test_file in self._results
            for comp_type in self._results[test_file]
        )
        print(f"\nTotal valid data points loaded: {total_datapoints}")

        if total_datapoints == 0:
            print("\nWARNING: No valid perf data found!")
            return False

        return True

    def calculate_stats(self, values: List[float]) -> Tuple[float, float, int]:
        """Calculate mean, standard deviation, and count."""
        if not values:
            return 0.0, 0.0, 0
        n = len(values)
        if n == 1:
            return values[0], 0.0, n
        return mean(values), stdev(values), n

    def _format_large_number(self, num: float) -> str:
        """Format large numbers with K/M/B suffixes."""
        if num >= 1e9:
            return f"{num/1e9:.2f}B"
        elif num >= 1e6:
            return f"{num/1e6:.2f}M"
        elif num >= 1e3:
            return f"{num/1e3:.2f}K"
        else:
            return f"{num:.0f}"

    def plot_instructions_per_cycle(self, operation: str) -> None:
        """Plot Instructions Per Cycle (IPC) comparison."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for IPC")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    counts.append(0)
                    continue

                ipc_values = []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        ipc = read_perf.ipc
                        if ipc > 0:
                            ipc_values.append(ipc)
                    elif operation == "write":
                        ipc = write_perf.ipc
                        if ipc > 0:
                            ipc_values.append(ipc)
                    elif operation == "overall":
                        total_cycles = read_perf.cycles + write_perf.cycles
                        total_inst = read_perf.instructions + write_perf.instructions
                        if total_cycles > 0:
                            ipc_values.append(total_inst / total_cycles)

                mean_val, std_val, count = self.calculate_stats(ipc_values)
                means.append(mean_val)
                stds.append(std_val if count > 1 else 0.0)
                counts.append(count)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(stds, counts)],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                max_height = max(means) if means and max(means) > 0 else 1
                for i, (mean_val, std_val, count) in enumerate(zip(means, stds, counts)):
                    if mean_val > 0 and count > 0:
                        ax.text(
                            pos[i],
                            mean_val + (std_val if count > 1 else 0) + max_height * 0.02,
                            f"{mean_val:.3f}",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "Instructions Per Cycle (Read Operation)",
            "write": "Instructions Per Cycle (Write Operation)",
            "overall": "Overall Instructions Per Cycle (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("IPC (Instructions / Cycle)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted and any(means):
            ax.set_ylim(0, max(max(means) * 1.2, 2.0))

        plt.tight_layout()
        output_path = self.graph_dir / f"ipc_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        
        if bars_plotted:
            print(f"  Generated: ipc_{operation}.svg")
        else:
            print(f"  Skipped: ipc_{operation}.svg (no data)")
            if output_path.exists():
                output_path.unlink()

    def plot_cycle_comparison(self, operation: str) -> None:
        """Plot total cycles comparison."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for cycles")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    counts.append(0)
                    continue

                cycle_values = []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        if read_perf.cycles > 0:
                            cycle_values.append(read_perf.cycles)
                    elif operation == "write":
                        if write_perf.cycles > 0:
                            cycle_values.append(write_perf.cycles)
                    elif operation == "overall":
                        total_cycles = read_perf.cycles + write_perf.cycles
                        if total_cycles > 0:
                            cycle_values.append(total_cycles)

                mean_val, std_val, count = self.calculate_stats(cycle_values)
                means.append(mean_val)
                stds.append(std_val if count > 1 else 0.0)
                counts.append(count)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(stds, counts)],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                max_height = max(means) if means and max(means) > 0 else 1
                for i, (mean_val, std_val, count) in enumerate(zip(means, stds, counts)):
                    if mean_val > 0 and count > 0:
                        label = self._format_large_number(mean_val)
                        ax.text(
                            pos[i],
                            mean_val + (std_val if count > 1 else 0) + max_height * 0.02,
                            label,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "CPU Cycles (Read Operation)",
            "write": "CPU Cycles (Write Operation)",
            "overall": "Overall CPU Cycles (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Number of Cycles", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"cycles_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        
        if bars_plotted:
            print(f"  Generated: cycles_{operation}.svg")
        else:
            print(f"  Skipped: cycles_{operation}.svg (no data)")
            if output_path.exists():
                output_path.unlink()

    def plot_instruction_comparison(self, operation: str) -> None:
        """Plot total instructions comparison."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for instructions")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    counts.append(0)
                    continue

                inst_values = []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        if read_perf.instructions > 0:
                            inst_values.append(read_perf.instructions)
                    elif operation == "write":
                        if write_perf.instructions > 0:
                            inst_values.append(write_perf.instructions)
                    elif operation == "overall":
                        total_inst = read_perf.instructions + write_perf.instructions
                        if total_inst > 0:
                            inst_values.append(total_inst)

                mean_val, std_val, count = self.calculate_stats(inst_values)
                means.append(mean_val)
                stds.append(std_val if count > 1 else 0.0)
                counts.append(count)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(stds, counts)],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                max_height = max(means) if means and max(means) > 0 else 1
                for i, (mean_val, std_val, count) in enumerate(zip(means, stds, counts)):
                    if mean_val > 0 and count > 0:
                        label = self._format_large_number(mean_val)
                        ax.text(
                            pos[i],
                            mean_val + (std_val if count > 1 else 0) + max_height * 0.02,
                            label,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "Instructions Executed (Read Operation)",
            "write": "Instructions Executed (Write Operation)",
            "overall": "Overall Instructions Executed (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Number of Instructions", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"instructions_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        
        if bars_plotted:
            print(f"  Generated: instructions_{operation}.svg")
        else:
            print(f"  Skipped: instructions_{operation}.svg (no data)")
            if output_path.exists():
                output_path.unlink()

    def plot_branch_prediction(self, operation: str) -> None:
        """Plot branch prediction with misses stacked on hits."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for branch prediction")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            branch_hits_means = []
            branch_misses_means = []
            branch_hits_stds = []
            branch_totals = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    branch_hits_means.append(0.0)
                    branch_misses_means.append(0.0)
                    branch_hits_stds.append(0.0)
                    branch_totals.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_values = []
                misses_values = []
                total_values = []
                rate_values = []

                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        perfs = [read_perf]
                    elif operation == "write":
                        perfs = [write_perf]
                    elif operation == "overall":
                        perfs = [read_perf, write_perf]
                    else:
                        perfs = []

                    total_branches = sum(p.branches for p in perfs)
                    total_misses = sum(p.branch_misses for p in perfs)

                    if total_branches > 0 and total_branches >= total_misses:
                        hits = total_branches - total_misses
                        hits_values.append(hits)
                        misses_values.append(total_misses)
                        total_values.append(total_branches)
                        rate_values.append((total_misses / total_branches) * 100.0)

                hits_mean, hits_std, count = self.calculate_stats(hits_values)
                misses_mean, _, _ = self.calculate_stats(misses_values)
                total_mean, _, _ = self.calculate_stats(total_values)
                rate_mean, _, _ = self.calculate_stats(rate_values)

                branch_hits_means.append(hits_mean)
                branch_misses_means.append(misses_mean)
                branch_hits_stds.append(hits_std if count > 1 else 0.0)
                branch_totals.append(total_mean)
                miss_rates.append(rate_mean)
                counts.append(count)

            pos = x + (idx - n_types / 2 + 0.5) * width

            has_data_for_type = any(h > 0 for h in branch_hits_means) or any(m > 0 for m in branch_misses_means)
            
            if has_data_for_type:
                bars_plotted = True
                # Plot hits
                ax.bar(
                    pos,
                    branch_hits_means,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(branch_hits_stds, counts)],
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                # Plot misses on top
                ax.bar(
                    pos,
                    branch_misses_means,
                    width,
                    bottom=branch_hits_means,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (misses)",
                    color=self.COLORS[comp_type],
                    alpha=0.3,
                    edgecolor="black",
                    linewidth=0.8,
                    hatch="//",
                )

                # Add miss rate labels
                max_total = max(branch_totals) if branch_totals and max(branch_totals) > 0 else 1
                for i, (total, rate, count) in enumerate(zip(branch_totals, miss_rates, counts)):
                    if total > 0 and count > 0 and rate > 0:
                        ax.text(
                            pos[i],
                            total + max_total * 0.05,
                            f"{rate:.1f}%",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                            color="darkred",
                            fontweight="bold",
                        )

        title_map = {
            "read": "Branch Prediction (Read Operation)",
            "write": "Branch Prediction (Write Operation)",
            "overall": "Overall Branch Prediction (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Number of Branches", fontsize=12, fontweight="bold")
        ax.set_title(
            title_map[operation] + ("\n(Labels show branch miss rate %)" if bars_plotted else ""),
            fontsize=12,
            fontweight="bold",
        )
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            # Create legend handles manually
            legend_elements = []
            for comp_type in self.COMPRESSION_TYPES:
                base_label = self.COMPRESSION_NAMES[comp_type]
                legend_elements.append(
                    plt.Rectangle(
                        (0, 0),
                        1,
                        1,
                        facecolor=self.COLORS[comp_type],
                        alpha=0.75,
                        label=f"{base_label} (hits)",
                    )
                )
                legend_elements.append(
                    plt.Rectangle(
                        (0, 0),
                        1,
                        1,
                        facecolor=self.COLORS[comp_type],
                        alpha=0.3,
                        hatch="//",
                        label=f"{base_label} (misses)",
                    )
                )
            ax.legend(handles=legend_elements, loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"branch_prediction_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        
        if bars_plotted:
            print(f"  Generated: branch_prediction_{operation}.svg")
        else:
            print(f"  Skipped: branch_prediction_{operation}.svg (no branch data found)")
            if output_path.exists():
                output_path.unlink()

    def plot_cache_performance(self, operation: str, cache_level: str) -> None:
        """Plot cache performance with misses stacked on hits."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print(f"    No data to plot for {cache_level} cache")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            cache_hits_means = []
            cache_misses_means = []
            cache_hits_stds = []
            cache_misses_stds = []
            cache_totals = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    cache_hits_means.append(0.0)
                    cache_misses_means.append(0.0)
                    cache_hits_stds.append(0.0)
                    cache_misses_stds.append(0.0)
                    cache_totals.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_values = []
                misses_values = []
                total_values = []
                rate_values = []

                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        perfs = [read_perf]
                    elif operation == "write":
                        perfs = [write_perf]
                    elif operation == "overall":
                        perfs = [read_perf, write_perf]
                    else:
                        perfs = []

                    if cache_level == "L1":
                        total_misses = sum(p.l1_dcache_load_misses for p in perfs)
                        if total_misses > 0:
                            misses_values.append(total_misses)
                    elif cache_level == "LLC":
                        total_misses = sum(p.llc_load_misses for p in perfs)
                        if total_misses > 0:
                            misses_values.append(total_misses)
                    else:  # all cache
                        total_refs = sum(p.cache_references for p in perfs)
                        total_misses = sum(p.cache_misses for p in perfs)
                        if total_refs > 0 and total_refs >= total_misses:
                            hits = total_refs - total_misses
                            hits_values.append(hits)
                            misses_values.append(total_misses)
                            total_values.append(total_refs)
                            rate_values.append((total_misses / total_refs) * 100.0)

                if cache_level in ["L1", "LLC"]:
                    misses_mean, misses_std, count = self.calculate_stats(misses_values)
                    cache_hits_means.append(0.0)
                    cache_misses_means.append(misses_mean)
                    cache_hits_stds.append(0.0)
                    cache_misses_stds.append(misses_std if count > 1 else 0.0)
                    cache_totals.append(misses_mean)
                    miss_rates.append(0.0)
                    counts.append(count)
                else:
                    hits_mean, hits_std, count = self.calculate_stats(hits_values)
                    misses_mean, misses_std, _ = self.calculate_stats(misses_values)
                    total_mean, _, _ = self.calculate_stats(total_values)
                    rate_mean, _, _ = self.calculate_stats(rate_values)

                    cache_hits_means.append(hits_mean)
                    cache_misses_means.append(misses_mean)
                    cache_hits_stds.append(hits_std if count > 1 else 0.0)
                    cache_misses_stds.append(misses_std if count > 1 else 0.0)
                    cache_totals.append(total_mean)
                    miss_rates.append(rate_mean)
                    counts.append(count)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if cache_level in ["L1", "LLC"]:
                if any(m > 0 for m in cache_misses_means):
                    bars_plotted = True
                    ax.bar(
                        pos,
                        cache_misses_means,
                        width,
                        label=self.COMPRESSION_NAMES[comp_type],
                        color=self.COLORS[comp_type],
                        yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(cache_misses_stds, counts)],
                        capsize=3,
                        alpha=0.8,
                        edgecolor="black",
                        linewidth=0.8,
                        error_kw={"elinewidth": 1, "capthick": 1},
                    )

                    max_height = max(cache_misses_means) if cache_misses_means and max(cache_misses_means) > 0 else 1
                    for i, (val, std, count) in enumerate(zip(cache_misses_means, cache_misses_stds, counts)):
                        if val > 0 and count > 0:
                            label = self._format_large_number(val)
                            ax.text(
                                pos[i],
                                val + (std if count > 1 else 0) + max_height * 0.02,
                                label,
                                ha="center",
                                va="bottom",
                                fontsize=7,
                            )
            else:
                if any(h > 0 for h in cache_hits_means) or any(m > 0 for m in cache_misses_means):
                    bars_plotted = True
                    ax.bar(
                        pos,
                        cache_hits_means,
                        width,
                        label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                        color=self.COLORS[comp_type],
                        yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(cache_hits_stds, counts)],
                        capsize=3,
                        alpha=0.75,
                        edgecolor="black",
                        linewidth=0.8,
                        error_kw={"elinewidth": 1, "capthick": 1},
                    )

                    ax.bar(
                        pos,
                        cache_misses_means,
                        width,
                        bottom=cache_hits_means,
                        label=f"{self.COMPRESSION_NAMES[comp_type]} (misses)",
                        color=self.COLORS[comp_type],
                        alpha=0.3,
                        edgecolor="black",
                        linewidth=0.8,
                        hatch="//",
                    )

                    max_total = max(cache_totals) if cache_totals and max(cache_totals) > 0 else 1
                    for i, (total, rate, count) in enumerate(zip(cache_totals, miss_rates, counts)):
                        if total > 0 and count > 0 and rate > 0:
                            ax.text(
                                pos[i],
                                total + max_total * 0.05,
                                f"{rate:.1f}%",
                                ha="center",
                                va="bottom",
                                fontsize=7,
                                color="darkred",
                                fontweight="bold",
                            )

        cache_names = {"L1": "L1 Data Cache", "LLC": "Last Level Cache", "all": "Cache"}
        ylabel = "Cache Misses" if cache_level in ["L1", "LLC"] else "Cache References"
        title_suffix = "" if cache_level in ["L1", "LLC"] else "\n(Labels show cache miss rate %)"

        title_map = {
            "read": f"{cache_names[cache_level]} Performance (Read Operation)",
            "write": f"{cache_names[cache_level]} Performance (Write Operation)",
            "overall": f"Overall {cache_names[cache_level]} Performance (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation] + (title_suffix if bars_plotted else ""), fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            if cache_level not in ["L1", "LLC"]:
                # Create legend handles manually
                legend_elements = []
                for comp_type in self.COMPRESSION_TYPES:
                    base_label = self.COMPRESSION_NAMES[comp_type]
                    legend_elements.append(
                        plt.Rectangle(
                            (0, 0),
                            1,
                            1,
                            facecolor=self.COLORS[comp_type],
                            alpha=0.75,
                            label=f"{base_label} (hits)",
                        )
                    )
                    legend_elements.append(
                        plt.Rectangle(
                            (0, 0),
                            1,
                            1,
                            facecolor=self.COLORS[comp_type],
                            alpha=0.3,
                            hatch="//",
                            label=f"{base_label} (misses)",
                        )
                    )
                ax.legend(handles=legend_elements, loc="center left", bbox_to_anchor=(1.02, 0.5))
            else:
                ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        cache_suffix = {"L1": "l1", "LLC": "llc", "all": "all"}
        output_path = self.graph_dir / f"cache_{cache_suffix[cache_level]}_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        
        if bars_plotted:
            print(f"  Generated: cache_{cache_suffix[cache_level]}_{operation}.svg")
        else:
            print(f"  Skipped: cache_{cache_suffix[cache_level]}_{operation}.svg (no cache data)")
            if output_path.exists():
                output_path.unlink()

    def generate_all_graphs(self) -> None:
        """Generate all graphs."""
        # Load data first
        has_data = self.load_results_and_perf()

        if not has_data:
            print("\nERROR: No valid perf data found! Skipping all graph generation.")
            print("Make sure:")
            print("  1. --perf-dir points to the correct directory")
            print("  2. The directory contains perf.data files in the expected subdirectories")
            print("  3. The perf_event_counter.py helper script is in the same directory")
            return

        print(f"\nFound {len(self._results)} test files with valid perf data")
        
        # Check what type of data we have
        has_cycle_data = False
        has_branch_data = False
        has_cache_data = False
        
        for test_file, comp_data in self._results.items():
            for comp_type, metrics_list in comp_data.items():
                for read_perf, write_perf in metrics_list:
                    if read_perf.cycles > 0 or write_perf.cycles > 0:
                        has_cycle_data = True
                    if read_perf.branches > 0 or write_perf.branches > 0:
                        has_branch_data = True
                    if read_perf.cache_references > 0 or write_perf.cache_references > 0:
                        has_cache_data = True
        
        print(f"Data detected: cycles={has_cycle_data}, branches={has_branch_data}, cache={has_cache_data}")
        print("\nGenerating graphs:")

        operations = ["read", "write", "overall"]
        graph_count = 1
        total_graphs = 21
        
        # IPC graphs (require cycle and instruction data)
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: IPC ({op})")
                self.plot_instructions_per_cycle(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: IPC graphs skipped (no cycle/instruction data)")
            graph_count += 3

        # Cycles graphs
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Cycles ({op})")
                self.plot_cycle_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: Cycles graphs skipped (no cycle data)")
            graph_count += 3

        # Instructions graphs
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Instructions ({op})")
                self.plot_instruction_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: Instructions graphs skipped (no instruction data)")
            graph_count += 3

        # Branch prediction graphs
        if has_branch_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Branch prediction ({op})")
                self.plot_branch_prediction(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: Branch prediction graphs skipped (no branch data)")
            graph_count += 3

        # Cache performance graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Cache performance ({op})")
                self.plot_cache_performance(op, "all")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: Cache performance graphs skipped (no cache data)")
            graph_count += 3

        # L1 cache misses graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: L1 cache misses ({op})")
                self.plot_cache_performance(op, "L1")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: L1 cache graphs skipped (no cache data)")
            graph_count += 3

        # LLC misses graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: LLC misses ({op})")
                self.plot_cache_performance(op, "LLC")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count+2}/{total_graphs}: LLC miss graphs skipped (no cache data)")
            graph_count += 3

        print(f"\nAll graphs saved to: {self.graph_dir}")


def main() -> None:
    parser = ArgumentParser(description="Generate performance graphs from perf profiling data")
    parser.add_argument(
        "--result", default="./experiment/result", help="Path to intermediate results directory"
    )
    parser.add_argument(
        "--perf-dir", required=True, help="Directory containing perf profiling data"
    )
    parser.add_argument("--graph", default="./experiment/graph", help="Path to graph directory")

    args = parser.parse_args()

    generator = PerfGraphGenerator(Path(args.result), Path(args.perf_dir), Path(args.graph))
    generator.generate_all_graphs()


if __name__ == "__main__":
    main()