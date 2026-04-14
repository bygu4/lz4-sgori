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
        if self.branches > 0:
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

    def _get_perf_stats(self, perf_file: Path) -> Optional[PerfStats]:
        """Get perf statistics from a perf.data file using the helper script."""
        cache_key = str(perf_file)
        if cache_key in self._perf_cache:
            return self._perf_cache[cache_key]

        if not perf_file.exists():
            return None

        if not self.helper_script.exists():
            print(f"      Error: Helper script not found at {self.helper_script}")
            return None

        try:
            result = run(
                ["perf", "script", "-s", str(self.helper_script), "-i", str(perf_file)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            stats = PerfStats()

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
                            except ValueError:
                                pass

            if stats.cycles > 0 or stats.instructions > 0:
                self._perf_cache[cache_key] = stats
                print(
                    f"        Extracted: cycles={stats.cycles:,.0f}, "
                    f"instructions={stats.instructions:,.0f}, "
                    f"IPC={stats.ipc:.3f}"
                )
                if stats.cache_references > 0:
                    if stats.has_valid_cache_data:
                        rate = (stats.cache_misses / stats.cache_references) * 100
                        print(
                            f"          Cache: refs={stats.cache_references:,.0f}, "
                            f"misses={stats.cache_misses:,.0f}, "
                            f"rate={rate:.1f}%"
                        )
                    else:
                        print(
                            f"          Cache: WARNING - invalid data (refs={stats.cache_references:,.0f}, "
                            f"misses={stats.cache_misses:,.0f})"
                        )
                return stats

            if result.stderr:
                print(f"      Warning: perf script stderr: {result.stderr[:200]}")

            return None

        except Exception as e:
            print(f"      Warning: Error parsing {perf_file}: {e}")
            return None

    def load_results_and_perf(self) -> Dict[str, Dict[str, List[Tuple[PerfStats, PerfStats]]]]:
        """Load result JSON files and corresponding perf data."""
        results: Dict[str, Dict[str, List[Tuple[PerfStats, PerfStats]]]] = {}

        print("\nLoading perf data...")

        for comp_type in self.COMPRESSION_TYPES:
            comp_dir = self.result_dir / comp_type
            if not comp_dir.exists():
                continue

            json_files = list(comp_dir.glob("*.json"))
            print(f"  Processing {comp_type}: {len(json_files)} files")

            for json_file in json_files:
                try:
                    with open(json_file) as f:
                        data = load(f)

                    test_file_name = Path(data["test_file"]).name
                    run_num = data["run_number"]

                    if test_file_name not in results:
                        results[test_file_name] = {ct: [] for ct in self.COMPRESSION_TYPES}

                    read_perf_file = (
                        self.perf_dir / comp_type / test_file_name / f"run{run_num}" / "read.data"
                    )
                    write_perf_file = (
                        self.perf_dir / comp_type / test_file_name / f"run{run_num}" / "write.data"
                    )

                    read_stats = self._get_perf_stats(read_perf_file)
                    write_stats = self._get_perf_stats(write_perf_file)

                    if read_stats and write_stats:
                        if read_stats.cycles > 0 or write_stats.cycles > 0:
                            results[test_file_name][comp_type].append((read_stats, write_stats))
                    else:
                        print(
                            f"      Warning: Could not extract perf data for {test_file_name} run {run_num}"
                        )

                except Exception as e:
                    print(f"    Error processing {json_file}: {e}")

        results = {
            test_file: comp_data
            for test_file, comp_data in results.items()
            if any(len(runs) > 0 for runs in comp_data.values())
        }

        total_datapoints = sum(
            len(results[test_file][comp_type])
            for test_file in results
            for comp_type in results[test_file]
        )
        print(f"\nTotal valid data points loaded: {total_datapoints}")

        if total_datapoints == 0:
            print("\nWARNING: No valid perf data found!")

        return results

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

    def plot_instructions_per_cycle(self, results: Dict, operation: str) -> None:
        """Plot Instructions Per Cycle (IPC) comparison."""
        test_files = sorted(results.keys())
        if not test_files:
            print("    No data to plot for IPC")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = results[test_file].get(comp_type, [])
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
            bars = ax.bar(
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
            for bar, mean_val, std_val, count in zip(bars, means, stds, counts):
                if mean_val > 0 and count > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        bar.get_height() + (std_val if count > 1 else 0) + max_height * 0.02,
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
        ax.set_xticklabels([Path(f).name[:30] for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if any(means):
            ax.set_ylim(0, max(max(means) * 1.2, 2.0))

        plt.tight_layout()
        output_path = self.graph_dir / f"ipc_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: ipc_{operation}.svg")

    def plot_cycle_comparison(self, results: Dict, operation: str) -> None:
        """Plot total cycles comparison."""
        test_files = sorted(results.keys())
        if not test_files:
            print("    No data to plot for cycles")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = results[test_file].get(comp_type, [])
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
            bars = ax.bar(
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
            for bar, mean_val, std_val, count in zip(bars, means, stds, counts):
                if mean_val > 0 and count > 0:
                    label = self._format_large_number(mean_val)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        bar.get_height() + (std_val if count > 1 else 0) + max_height * 0.02,
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
        ax.set_xticklabels([Path(f).name[:30] for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"cycles_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: cycles_{operation}.svg")

    def plot_instruction_comparison(self, results: Dict, operation: str) -> None:
        """Plot total instructions comparison."""
        test_files = sorted(results.keys())
        if not test_files:
            print("    No data to plot for instructions")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []
            counts = []

            for test_file in test_files:
                metrics_list = results[test_file].get(comp_type, [])
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
            bars = ax.bar(
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
            for bar, mean_val, std_val, count in zip(bars, means, stds, counts):
                if mean_val > 0 and count > 0:
                    label = self._format_large_number(mean_val)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        bar.get_height() + (std_val if count > 1 else 0) + max_height * 0.02,
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
        ax.set_xticklabels([Path(f).name[:30] for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"instructions_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: instructions_{operation}.svg")

    def plot_branch_prediction(self, results: Dict, operation: str) -> None:
        """Plot branch prediction with misses stacked on hits."""
        test_files = sorted(results.keys())
        if not test_files:
            print("    No data to plot for branch prediction")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            branch_hits_means = []
            branch_misses_means = []
            branch_hits_stds = []
            branch_totals = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = results[test_file].get(comp_type, [])
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

                    # Aggregate across read/write if overall
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

            bars_hits = ax.bar(
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

            bars_misses = ax.bar(
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

            max_total = max(branch_totals) if branch_totals and max(branch_totals) > 0 else 1
            for i, (total, rate, count) in enumerate(zip(branch_totals, miss_rates, counts)):
                if total > 0 and count > 0:
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
            title_map[operation] + "\n(Labels show branch miss rate %)",
            fontsize=12,
            fontweight="bold",
        )
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name[:30] for f in test_files], rotation=45, ha="right")

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

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        output_path = self.graph_dir / f"branch_prediction_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: branch_prediction_{operation}.svg")

    def plot_cache_performance(self, results: Dict, operation: str, cache_level: str) -> None:
        """Plot cache performance."""
        test_files = sorted(results.keys())
        if not test_files:
            print(f"    No data to plot for {cache_level} cache")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            cache_hits_means = []
            cache_misses_means = []
            cache_hits_stds = []
            cache_misses_stds = []
            cache_totals = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = results[test_file].get(comp_type, [])
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
                        # Only include if data is valid (refs >= misses)
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
                bars = ax.bar(
                    pos,
                    cache_misses_means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(cache_misses_stds, counts)],
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                max_height = (
                    max(cache_misses_means)
                    if cache_misses_means and max(cache_misses_means) > 0
                    else 1
                )
                for bar, val, std, count in zip(
                    bars, cache_misses_means, cache_misses_stds, counts
                ):
                    if val > 0 and count > 0:
                        label = self._format_large_number(val)
                        ax.text(
                            bar.get_x() + bar.get_width() / 2.0,
                            bar.get_height() + (std if count > 1 else 0) + max_height * 0.02,
                            label,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )
            else:
                # Skip if no valid data
                if all(c == 0 for c in counts):
                    continue

                bars_hits = ax.bar(
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

                bars_misses = ax.bar(
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
                    if total > 0 and count > 0:
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
        title_map = {
            "read": f"{cache_names[cache_level]} Performance (Read Operation)",
            "write": f"{cache_names[cache_level]} Performance (Write Operation)",
            "overall": f"Overall {cache_names[cache_level]} Performance (Read + Write)",
        }

        ylabel = "Cache Misses" if cache_level in ["L1", "LLC"] else "Cache References"
        title_suffix = "" if cache_level in ["L1", "LLC"] else "\n(Labels show cache miss rate %)"

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation] + title_suffix, fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name[:30] for f in test_files], rotation=45, ha="right")

        if cache_level not in ["L1", "LLC"]:
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

        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: self._format_large_number(x)))

        plt.tight_layout()
        cache_suffix = {"L1": "l1", "LLC": "llc", "all": "all"}
        output_path = self.graph_dir / f"cache_{cache_suffix[cache_level]}_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: cache_{cache_suffix[cache_level]}_{operation}.svg")

    def generate_all_graphs(self) -> None:
        """Generate all graphs."""
        print("Loading results and perf data...")
        results = self.load_results_and_perf()

        if not results:
            print("\nERROR: No valid perf data found!")
            return

        print(f"\nFound {len(results)} test files with valid perf data")
        print("\nGenerating graphs:")

        operations = ["read", "write", "overall"]
        graph_count = 1
        total_graphs = 21

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: IPC ({op})")
            self.plot_instructions_per_cycle(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: Cycles ({op})")
            self.plot_cycle_comparison(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: Instructions ({op})")
            self.plot_instruction_comparison(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: Branch prediction ({op})")
            self.plot_branch_prediction(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: Cache performance ({op})")
            self.plot_cache_performance(results, op, "all")
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: L1 cache misses ({op})")
            self.plot_cache_performance(results, op, "L1")
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_graphs}: LLC misses ({op})")
            self.plot_cache_performance(results, op, "LLC")
            graph_count += 1

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
