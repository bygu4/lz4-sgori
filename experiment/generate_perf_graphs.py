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
Generate performance comparison graphs from perf stat CSV data.
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from json import load
from pathlib import Path
from statistics import mean, stdev
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
    """Container for perf statistics from perf stat CSV."""

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
        """Calculate cache hits."""
        if self.cache_references > 0 and self.cache_references >= self.cache_misses:
            return self.cache_references - self.cache_misses
        return 0.0

    @property
    def has_valid_cache_data(self) -> bool:
        """Check if cache data is valid."""
        return self.cache_references > 0 and self.cache_references >= self.cache_misses

    @property
    def has_valid_branch_data(self) -> bool:
        """Check if branch data is valid."""
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
        self._perf_cache: Dict[str, PerfStats] = {}
        self._results: Dict[str, Dict[str, List[Tuple[PerfStats, PerfStats]]]] = {}

    def _parse_perf_stat_csv(self, csv_file: Path) -> Optional[PerfStats]:
        """Parse perf stat CSV output."""
        if not csv_file.exists():
            return None

        cache_key = str(csv_file)
        if cache_key in self._perf_cache:
            return self._perf_cache[cache_key]

        stats = PerfStats()

        try:
            with open(csv_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            value = float(parts[0])
                            event = parts[1]

                            if event == "cycles":
                                stats.cycles = value
                            elif event == "instructions":
                                stats.instructions = value
                            elif event == "branches":
                                stats.branches = value
                            elif event == "branch-misses":
                                stats.branch_misses = value
                            elif event == "cache-references":
                                stats.cache_references = value
                            elif event == "cache-misses":
                                stats.cache_misses = value
                            elif event == "L1-dcache-load-misses":
                                stats.l1_dcache_load_misses = value
                            elif event == "LLC-load-misses":
                                stats.llc_load_misses = value
                            elif event == "page-faults":
                                stats.page_faults = value
                        except (ValueError, IndexError):
                            pass

            # Validate data (should never have misses > total with perf stat)
            if stats.branch_misses > stats.branches:
                print(
                    f"      Warning: Invalid branch data in {csv_file.name} (misses={stats.branch_misses}, branches={stats.branches})"
                )
                stats.branch_misses = stats.branches

            if stats.cache_misses > stats.cache_references:
                print(
                    f"      Warning: Invalid cache data in {csv_file.name} (misses={stats.cache_misses}, refs={stats.cache_references})"
                )
                stats.cache_misses = stats.cache_references

            if stats.cycles > 0 or stats.instructions > 0 or stats.branches > 0:
                self._perf_cache[cache_key] = stats
                return stats

        except Exception as e:
            print(f"      Error parsing {csv_file}: {e}")

        return None

    def load_results_and_perf(self) -> bool:
        """Load result JSON files and corresponding perf CSV data."""
        self._results = {}

        print("\nLoading perf stat data...")

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

                    read_csv = (
                        self.perf_dir
                        / comp_type
                        / test_file_name
                        / f"run{run_num}"
                        / "read_stats.csv"
                    )
                    write_csv = (
                        self.perf_dir
                        / comp_type
                        / test_file_name
                        / f"run{run_num}"
                        / "write_stats.csv"
                    )

                    read_stats = self._parse_perf_stat_csv(read_csv)
                    write_stats = self._parse_perf_stat_csv(write_csv)

                    if read_stats and write_stats:
                        self._results[test_file_name][comp_type].append((read_stats, write_stats))
                    else:
                        print(
                            f"      Warning: Could not load perf data for {test_file_name} run {run_num}"
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
        if not values:
            return 0.0, 0.0, 0
        n = len(values)
        if n == 1:
            return values[0], 0.0, n
        return mean(values), stdev(values), n

    def _format_large_number(self, num: float) -> str:
        if num >= 1e9:
            return f"{num / 1e9:.2f}B"
        elif num >= 1e6:
            return f"{num / 1e6:.2f}M"
        elif num >= 1e3:
            return f"{num / 1e3:.2f}K"
        else:
            return f"{num:.0f}"

    def plot_instructions_per_cycle(self, operation: str) -> None:
        """Plot IPC comparison."""
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
            means, stds, counts = [], [], []

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
                    elif operation == "write":
                        ipc = write_perf.ipc
                    else:  # overall
                        total_cycles = read_perf.cycles + write_perf.cycles
                        total_inst = read_perf.instructions + write_perf.instructions
                        ipc = total_inst / total_cycles if total_cycles > 0 else 0

                    if ipc > 0:
                        ipc_values.append(ipc)

                mean_val, std_val, cnt = self.calculate_stats(ipc_values)
                means.append(mean_val)
                stds.append(std_val)
                counts.append(cnt)

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
                )

                max_h = max(means) if means else 1
                for i, (m, s, c) in enumerate(zip(means, stds, counts)):
                    if m > 0 and c > 0:
                        ax.text(
                            pos[i],
                            m + (s if c > 1 else 0) + max_h * 0.02,
                            f"{m:.3f}",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "Instructions Per Cycle (Read)",
            "write": "Instructions Per Cycle (Write)",
            "overall": "Instructions Per Cycle (Overall)",
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
            means, stds, counts = [], [], []

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
                        val = read_perf.cycles
                    elif operation == "write":
                        val = write_perf.cycles
                    else:
                        val = read_perf.cycles + write_perf.cycles

                    if val > 0:
                        cycle_values.append(val)

                mean_val, std_val, cnt = self.calculate_stats(cycle_values)
                means.append(mean_val)
                stds.append(std_val)
                counts.append(cnt)

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
                )

                max_h = max(means) if means else 1
                for i, (m, s, c) in enumerate(zip(means, stds, counts)):
                    if m > 0 and c > 0:
                        label = self._format_large_number(m)
                        ax.text(
                            pos[i],
                            m + (s if c > 1 else 0) + max_h * 0.02,
                            label,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "CPU Cycles (Read)",
            "write": "CPU Cycles (Write)",
            "overall": "CPU Cycles (Overall)",
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
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, p: self._format_large_number(x))
            )

        plt.tight_layout()
        output_path = self.graph_dir / f"cycles_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: cycles_{operation}.svg")
        else:
            print(f"  Skipped: cycles_{operation}.svg (no data)")

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
            means, stds, counts = [], [], []

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
                        val = read_perf.instructions
                    elif operation == "write":
                        val = write_perf.instructions
                    else:
                        val = read_perf.instructions + write_perf.instructions

                    if val > 0:
                        inst_values.append(val)

                mean_val, std_val, cnt = self.calculate_stats(inst_values)
                means.append(mean_val)
                stds.append(std_val)
                counts.append(cnt)

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
                )

                max_h = max(means) if means else 1
                for i, (m, s, c) in enumerate(zip(means, stds, counts)):
                    if m > 0 and c > 0:
                        label = self._format_large_number(m)
                        ax.text(
                            pos[i],
                            m + (s if c > 1 else 0) + max_h * 0.02,
                            label,
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )

        title_map = {
            "read": "Instructions Executed (Read)",
            "write": "Instructions Executed (Write)",
            "overall": "Instructions Executed (Overall)",
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
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, p: self._format_large_number(x))
            )

        plt.tight_layout()
        output_path = self.graph_dir / f"instructions_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: instructions_{operation}.svg")
        else:
            print(f"  Skipped: instructions_{operation}.svg (no data)")

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
            hits_means, misses_means, hits_stds, totals, miss_rates, counts = [], [], [], [], [], []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    hits_stds.append(0.0)
                    totals.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_vals, rate_vals = [], [], [], []

                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        branches = read_perf.branches
                        misses = read_perf.branch_misses
                    elif operation == "write":
                        branches = write_perf.branches
                        misses = write_perf.branch_misses
                    else:
                        branches = read_perf.branches + write_perf.branches
                        misses = read_perf.branch_misses + write_perf.branch_misses

                    if branches > 0:
                        if misses <= branches:
                            hits_vals.append(branches - misses)
                            misses_vals.append(misses)
                            total_vals.append(branches)
                            rate_vals.append((misses / branches) * 100.0)
                        else:
                            print(
                                f"        Warning: Invalid branch data (branches={branches}, misses={misses})"
                            )

                h_mean, h_std, cnt = self.calculate_stats(hits_vals)
                m_mean, _, _ = self.calculate_stats(misses_vals)
                t_mean, _, _ = self.calculate_stats(total_vals)
                r_mean, _, _ = self.calculate_stats(rate_vals)

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                hits_stds.append(h_std if cnt > 1 else 0.0)
                totals.append(t_mean)
                miss_rates.append(r_mean)
                counts.append(cnt)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(h > 0 for h in hits_means) or any(m > 0 for m in misses_means):
                bars_plotted = True
                ax.bar(
                    pos,
                    hits_means,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(hits_stds, counts)],
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                )
                ax.bar(
                    pos,
                    misses_means,
                    width,
                    bottom=hits_means,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (misses)",
                    color=self.COLORS[comp_type],
                    alpha=0.3,
                    edgecolor="black",
                    linewidth=0.8,
                    hatch="//",
                )

                max_t = max(totals) if totals else 1
                for i, (t, r, c) in enumerate(zip(totals, miss_rates, counts)):
                    if t > 0 and c > 0 and r > 0:
                        ax.text(
                            pos[i],
                            t + max_t * 0.05,
                            f"{r:.1f}%",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                            color="darkred",
                            fontweight="bold",
                        )

        title_map = {
            "read": "Branch Prediction (Read)",
            "write": "Branch Prediction (Write)",
            "overall": "Branch Prediction (Overall)",
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
            legend_elements = []
            for ct in self.COMPRESSION_TYPES:
                base = self.COMPRESSION_NAMES[ct]
                legend_elements.append(
                    plt.Rectangle(
                        (0, 0), 1, 1, facecolor=self.COLORS[ct], alpha=0.75, label=f"{base} (hits)"
                    )
                )
                legend_elements.append(
                    plt.Rectangle(
                        (0, 0),
                        1,
                        1,
                        facecolor=self.COLORS[ct],
                        alpha=0.3,
                        hatch="//",
                        label=f"{base} (misses)",
                    )
                )
            ax.legend(handles=legend_elements, loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, p: self._format_large_number(x))
            )

        plt.tight_layout()
        output_path = self.graph_dir / f"branch_prediction_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: branch_prediction_{operation}.svg")
        else:
            print(f"  Skipped: branch_prediction_{operation}.svg (no valid branch data)")

    def plot_cache_performance(self, operation: str, cache_level: str) -> None:
        """Plot cache performance."""
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
            hits_means, misses_means, hits_stds, misses_stds, totals, miss_rates, counts = (
                [],
                [],
                [],
                [],
                [],
                [],
                [],
            )

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    hits_stds.append(0.0)
                    misses_stds.append(0.0)
                    totals.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_vals, rate_vals = [], [], [], []

                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        perfs = [read_perf]
                    elif operation == "write":
                        perfs = [write_perf]
                    else:
                        perfs = [read_perf, write_perf]

                    if cache_level == "L1":
                        total_misses = sum(p.l1_dcache_load_misses for p in perfs)
                        if total_misses > 0:
                            misses_vals.append(total_misses)
                    elif cache_level == "LLC":
                        total_misses = sum(p.llc_load_misses for p in perfs)
                        if total_misses > 0:
                            misses_vals.append(total_misses)
                    else:
                        total_refs = sum(p.cache_references for p in perfs)
                        total_misses = sum(p.cache_misses for p in perfs)
                        if total_refs > 0 and total_refs >= total_misses:
                            hits_vals.append(total_refs - total_misses)
                            misses_vals.append(total_misses)
                            total_vals.append(total_refs)
                            rate_vals.append((total_misses / total_refs) * 100.0)

                if cache_level in ["L1", "LLC"]:
                    m_mean, m_std, cnt = self.calculate_stats(misses_vals)
                    hits_means.append(0.0)
                    misses_means.append(m_mean)
                    hits_stds.append(0.0)
                    misses_stds.append(m_std if cnt > 1 else 0.0)
                    totals.append(m_mean)
                    miss_rates.append(0.0)
                    counts.append(cnt)
                else:
                    h_mean, h_std, cnt = self.calculate_stats(hits_vals)
                    m_mean, m_std, _ = self.calculate_stats(misses_vals)
                    t_mean, _, _ = self.calculate_stats(total_vals)
                    r_mean, _, _ = self.calculate_stats(rate_vals)

                    hits_means.append(h_mean)
                    misses_means.append(m_mean)
                    hits_stds.append(h_std if cnt > 1 else 0.0)
                    misses_stds.append(m_std if cnt > 1 else 0.0)
                    totals.append(t_mean)
                    miss_rates.append(r_mean)
                    counts.append(cnt)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if cache_level in ["L1", "LLC"]:
                if any(m > 0 for m in misses_means):
                    bars_plotted = True
                    ax.bar(
                        pos,
                        misses_means,
                        width,
                        label=self.COMPRESSION_NAMES[comp_type],
                        color=self.COLORS[comp_type],
                        yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(misses_stds, counts)],
                        capsize=3,
                        alpha=0.8,
                        edgecolor="black",
                        linewidth=0.8,
                    )

                    max_h = max(misses_means) if misses_means else 1
                    for i, (v, s, c) in enumerate(zip(misses_means, misses_stds, counts)):
                        if v > 0 and c > 0:
                            ax.text(
                                pos[i],
                                v + (s if c > 1 else 0) + max_h * 0.02,
                                self._format_large_number(v),
                                ha="center",
                                va="bottom",
                                fontsize=7,
                            )
            else:
                if any(h > 0 for h in hits_means) or any(m > 0 for m in misses_means):
                    bars_plotted = True
                    ax.bar(
                        pos,
                        hits_means,
                        width,
                        label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                        color=self.COLORS[comp_type],
                        yerr=[s if s > 0 and c > 1 else 0 for s, c in zip(hits_stds, counts)],
                        capsize=3,
                        alpha=0.75,
                        edgecolor="black",
                        linewidth=0.8,
                    )
                    ax.bar(
                        pos,
                        misses_means,
                        width,
                        bottom=hits_means,
                        label=f"{self.COMPRESSION_NAMES[comp_type]} (misses)",
                        color=self.COLORS[comp_type],
                        alpha=0.3,
                        edgecolor="black",
                        linewidth=0.8,
                        hatch="//",
                    )

                    max_t = max(totals) if totals else 1
                    for i, (t, r, c) in enumerate(zip(totals, miss_rates, counts)):
                        if t > 0 and c > 0 and r > 0:
                            ax.text(
                                pos[i],
                                t + max_t * 0.05,
                                f"{r:.1f}%",
                                ha="center",
                                va="bottom",
                                fontsize=7,
                                color="darkred",
                                fontweight="bold",
                            )

        cache_names = {"L1": "L1 Data Cache", "LLC": "Last Level Cache", "all": "Cache"}
        ylabel = "Cache Misses" if cache_level in ["L1", "LLC"] else "Cache References"

        title_map = {
            "read": f"{cache_names[cache_level]} Performance (Read)",
            "write": f"{cache_names[cache_level]} Performance (Write)",
            "overall": f"Overall {cache_names[cache_level]} Performance",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            if cache_level not in ["L1", "LLC"]:
                legend_elements = []
                for ct in self.COMPRESSION_TYPES:
                    base = self.COMPRESSION_NAMES[ct]
                    legend_elements.append(
                        plt.Rectangle(
                            (0, 0),
                            1,
                            1,
                            facecolor=self.COLORS[ct],
                            alpha=0.75,
                            label=f"{base} (hits)",
                        )
                    )
                    legend_elements.append(
                        plt.Rectangle(
                            (0, 0),
                            1,
                            1,
                            facecolor=self.COLORS[ct],
                            alpha=0.3,
                            hatch="//",
                            label=f"{base} (misses)",
                        )
                    )
                ax.legend(handles=legend_elements, loc="center left", bbox_to_anchor=(1.02, 0.5))
            else:
                ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        if bars_plotted:
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, p: self._format_large_number(x))
            )

        plt.tight_layout()
        cache_suffix = {"L1": "l1", "LLC": "llc", "all": "all"}
        output_path = self.graph_dir / f"cache_{cache_suffix[cache_level]}_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: cache_{cache_suffix[cache_level]}_{operation}.svg")
        else:
            print(f"  Skipped: cache_{cache_suffix[cache_level]}_{operation}.svg (no data)")

    def generate_all_graphs(self) -> None:
        """Generate all graphs."""
        has_data = self.load_results_and_perf()

        if not has_data:
            print("\nERROR: No valid perf data found! Skipping all graph generation.")
            return

        print(f"\nFound {len(self._results)} test files with valid perf data")

        # Detect what data we have
        has_cycle_data = has_branch_data = has_cache_data = False
        for test_file, comp_data in self._results.items():
            for comp_type, metrics_list in comp_data.items():
                for rp, wp in metrics_list:
                    if rp.cycles > 0 or wp.cycles > 0:
                        has_cycle_data = True
                    if rp.branches > 0 or wp.branches > 0:
                        has_branch_data = True
                    if rp.cache_references > 0 or wp.cache_references > 0:
                        has_cache_data = True

        print(
            f"Data detected: cycles={has_cycle_data}, branches={has_branch_data}, cache={has_cache_data}"
        )
        print("\nGenerating graphs:")

        operations = ["read", "write", "overall"]
        graph_count = 1
        total_graphs = 21

        # IPC graphs
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: IPC ({op})")
                self.plot_instructions_per_cycle(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: IPC graphs skipped")
            graph_count += 3

        # Cycles graphs
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Cycles ({op})")
                self.plot_cycle_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: Cycles graphs skipped")
            graph_count += 3

        # Instructions graphs
        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Instructions ({op})")
                self.plot_instruction_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: Instructions graphs skipped")
            graph_count += 3

        # Branch prediction graphs
        if has_branch_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Branch prediction ({op})")
                self.plot_branch_prediction(op)
                graph_count += 1
        else:
            print(
                f"  {graph_count}-{graph_count + 2}/{total_graphs}: Branch prediction graphs skipped"
            )
            graph_count += 3

        # Cache performance graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Cache performance ({op})")
                self.plot_cache_performance(op, "all")
                graph_count += 1
        else:
            print(
                f"  {graph_count}-{graph_count + 2}/{total_graphs}: Cache performance graphs skipped"
            )
            graph_count += 3

        # L1 cache graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: L1 cache misses ({op})")
                self.plot_cache_performance(op, "L1")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: L1 cache graphs skipped")
            graph_count += 3

        # LLC cache graphs
        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: LLC misses ({op})")
                self.plot_cache_performance(op, "LLC")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: LLC miss graphs skipped")
            graph_count += 3

        print(f"\nAll graphs saved to: {self.graph_dir}")


def main() -> None:
    parser = ArgumentParser(description="Generate performance graphs from perf stat data")
    parser.add_argument(
        "--result", default="./experiment/result", help="Path to intermediate results directory"
    )
    parser.add_argument(
        "--perf-dir", required=True, help="Directory containing perf stat CSV files"
    )
    parser.add_argument("--graph", default="./experiment/graph", help="Path to graph directory")

    args = parser.parse_args()

    generator = PerfGraphGenerator(Path(args.result), Path(args.perf_dir), Path(args.graph))
    generator.generate_all_graphs()


if __name__ == "__main__":
    main()
