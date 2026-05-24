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
Creates both absolute and relative (to Contiguous) performance graphs.
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
    def branch_miss_rate(self) -> float:
        """Branch miss rate as percentage."""
        return (self.branch_misses / self.branches) * 100.0 if self.branches > 0 else 0.0

    @property
    def cache_miss_rate(self) -> float:
        """Cache miss rate as percentage."""
        return (
            (self.cache_misses / self.cache_references) * 100.0
            if self.cache_references > 0
            else 0.0
        )


class PerfGraphGenerator:
    COMPRESSION_TYPES = ["cont", "vect", "strm", "extd"]
    COMPRESSION_NAMES = {
        "cont": "Contiguous",
        "vect": "Vectorized",
        "strm": "Streaming",
        "extd": "Extended",
    }

    # Blue, Yellow, Green, Red
    COLORS = {"cont": "#1f77b4", "vect": "#ff7f0e", "strm": "#2ca02c", "extd": "#d62728"}

    def __init__(self, result_dir: Path, perf_dir: Path, graph_dir: Path):
        self.result_dir = Path(result_dir)
        self.perf_dir = Path(perf_dir)
        self.graph_dir = Path(graph_dir)
        self.graph_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories for absolute and relative graphs
        self.abs_graph_dir = self.graph_dir / "absolute"
        self.rel_graph_dir = self.graph_dir / "relative"
        self.abs_graph_dir.mkdir(parents=True, exist_ok=True)
        self.rel_graph_dir.mkdir(parents=True, exist_ok=True)

        self._perf_cache: Dict[str, PerfStats] = {}
        self._results: Dict[str, Dict[str, List[Tuple[PerfStats, PerfStats]]]] = {}

    def _parse_perf_stat_csv(self, csv_file: Path) -> Optional[PerfStats]:
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
                    if "<not supported>" in line:
                        continue
                    line = line.lstrip("~ ")
                    parts = line.split(",")

                    if len(parts) >= 3:
                        try:
                            value = float(parts[0])
                            event = parts[2].strip()

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
                            continue

            if stats.cycles > 0 or stats.instructions > 0 or stats.branches > 0:
                self._perf_cache[cache_key] = stats
                print(
                    f"        Loaded: cycles={stats.cycles:,.0f}, instructions={stats.instructions:,.0f}, branches={stats.branches:,.0f}"
                )
                return stats

        except Exception as e:
            print(f"      Error parsing {csv_file}: {e}")

        return None

    def load_results_and_perf(self) -> bool:
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
                        print(f"        Loaded perf data for {test_file_name} run {run_num}")

                except Exception as e:
                    print(f"    Error processing {json_file}: {e}")

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

    def calculate_stats(self, values: List[float]) -> Tuple[float, float, float, float, int]:
        """
        Calculate mean, standard deviation, average relative error, max relative error, and count.
        Relative error = |(value - mean) / mean| * 100%
        """
        if not values:
            return 0.0, 0.0, 0.0, 0.0, 0

        n = len(values)
        if n == 1:
            return values[0], 0.0, 0.0, 0.0, n

        mean_val = mean(values)
        std_val = stdev(values)

        # Calculate relative errors for each run
        rel_errors = []
        for v in values:
            if mean_val > 0:
                rel_error = abs((v - mean_val) / mean_val) * 100.0
                rel_errors.append(rel_error)

        avg_rel_error = mean(rel_errors) if rel_errors else 0.0
        max_rel_error = max(rel_errors) if rel_errors else 0.0

        return mean_val, std_val, avg_rel_error, max_rel_error, n

    def _add_error_stats_to_plot(
        self, ax: plt.Axes, all_relative_errors: List[float], max_bar_height: float
    ) -> None:
        """Add error statistics text box to the plot on the right side and adjust y-axis limit."""
        if all_relative_errors:
            avg_error = mean(all_relative_errors)
            max_error = max(all_relative_errors)
        else:
            avg_error = 0.0
            max_error = 0.0

        textstr = f"Avg Relative Error: {avg_error:.2f}%\nMax Relative Error: {max_error:.2f}%"

        # Place text box in upper right corner
        props = {"boxstyle": "round", "facecolor": "wheat", "alpha": 0.7}
        ax.text(
            0.98,
            0.98,
            textstr,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment="top",
            horizontalalignment="right",
            bbox=props,
        )

        # Adjust y-axis limit to ensure enough headroom above the highest bar + error
        if max_bar_height > 0:
            # Add 18% padding above the highest point
            new_ymax = max_bar_height * 1.18
            current_ylim = ax.get_ylim()
            if new_ymax > current_ylim[1]:
                ax.set_ylim(0, new_ymax)

    def _format_large_number(self, num: float) -> str:
        if num >= 1e9:
            return f"{num / 1e9:.2f}B"
        elif num >= 1e6:
            return f"{num / 1e6:.2f}M"
        elif num >= 1e3:
            return f"{num / 1e3:.2f}K"
        else:
            return f"{num:.0f}"

    def _get_contiguous_baseline(self, test_file: str, operation: str, metric: str) -> float:
        """Get the Contiguous baseline mean for normalization."""
        cont_metrics = self._results[test_file].get("cont", [])
        if not cont_metrics:
            return 0.0

        cont_values = []
        for read_perf, write_perf in cont_metrics:
            if operation == "read":
                perfs = [read_perf]
            elif operation == "write":
                perfs = [write_perf]
            else:
                perfs = [read_perf, write_perf]

            if metric == "cycles":
                val = sum(p.cycles for p in perfs)
            elif metric == "instructions":
                val = sum(p.instructions for p in perfs)
            elif metric == "branches":
                val = sum(p.branches for p in perfs)
            elif metric == "cache_references":
                val = sum(p.cache_references for p in perfs)
            else:
                val = 0.0

            if val > 0:
                cont_values.append(val)

        return mean(cont_values) if cont_values else 0.0

    # ===== RELATIVE GRAPHS =====

    def plot_relative_metric(
        self, operation: str, metric: str, metric_name: str, higher_is_better: bool = True
    ) -> None:
        """Generate relative performance graph for a specific metric."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print(f"    No data to plot for relative {metric}")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                if comp_type == "cont":
                    # Contiguous is always 1.0
                    metrics_list = self._results[test_file].get("cont", [])
                    n_runs = len(metrics_list)
                    if (
                        n_runs > 0
                        and self._get_contiguous_baseline(test_file, operation, metric) > 0
                    ):
                        means.append(1.0)
                        stds.append(0.0)
                    else:
                        means.append(0.0)
                        stds.append(0.0)
                else:
                    # Get Contiguous baseline
                    cont_baseline = self._get_contiguous_baseline(test_file, operation, metric)
                    if cont_baseline == 0:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    metrics_list = self._results[test_file].get(comp_type, [])
                    if not metrics_list:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    rel_values = []
                    for read_perf, write_perf in metrics_list:
                        if operation == "read":
                            perfs = [read_perf]
                        elif operation == "write":
                            perfs = [write_perf]
                        else:
                            perfs = [read_perf, write_perf]

                        if metric == "cycles":
                            val = sum(p.cycles for p in perfs)
                        elif metric == "instructions":
                            val = sum(p.instructions for p in perfs)
                        elif metric == "ipc":
                            total_cycles = sum(p.cycles for p in perfs)
                            total_inst = sum(p.instructions for p in perfs)
                            val = total_inst / total_cycles if total_cycles > 0 else 0.0
                        else:
                            val = 0.0

                        if val > 0:
                            rel_values.append(val / cont_baseline)

                    mean_val, std_val, avg_rel_err, max_rel_err, n = self.calculate_stats(
                        rel_values
                    )
                    means.append(mean_val)
                    stds.append(std_val)
                    if n > 1:
                        all_rel_errors.append(avg_rel_err)
                        all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 else 0 for s in stds],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

        # Add value labels above error bars
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                if comp_type == "cont":
                    metrics_list = self._results[test_file].get("cont", [])
                    n_runs = len(metrics_list)
                    if (
                        n_runs > 0
                        and self._get_contiguous_baseline(test_file, operation, metric) > 0
                    ):
                        means.append(1.0)
                        stds.append(0.0)
                    else:
                        means.append(0.0)
                        stds.append(0.0)
                else:
                    cont_baseline = self._get_contiguous_baseline(test_file, operation, metric)
                    if cont_baseline == 0:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    metrics_list = self._results[test_file].get(comp_type, [])
                    if not metrics_list:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    rel_values = []
                    for read_perf, write_perf in metrics_list:
                        if operation == "read":
                            perfs = [read_perf]
                        elif operation == "write":
                            perfs = [write_perf]
                        else:
                            perfs = [read_perf, write_perf]

                        if metric == "cycles":
                            val = sum(p.cycles for p in perfs)
                        elif metric == "instructions":
                            val = sum(p.instructions for p in perfs)
                        elif metric == "ipc":
                            total_cycles = sum(p.cycles for p in perfs)
                            total_inst = sum(p.instructions for p in perfs)
                            val = total_inst / total_cycles if total_cycles > 0 else 0.0
                        else:
                            val = 0.0

                        if val > 0:
                            rel_values.append(val / cont_baseline)

                    mean_val, std_val, _, _, _ = self.calculate_stats(rel_values)
                    means.append(mean_val)
                    stds.append(std_val)

            pos = x + (idx - n_types / 2 + 0.5) * width
            for i, (m, s) in enumerate(zip(means, stds)):
                if m > 0:
                    label_y = m + s + (m * 0.01)
                    ax.text(pos[i], label_y, f"{m:.3f}", ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": f"Relative {metric_name} (Read Operation)",
            "write": f"Relative {metric_name} (Write Operation)",
            "overall": f"Relative {metric_name} (Overall)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(f"Relative {metric_name} (× Contiguous)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([f[:30] for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        output_path = self.rel_graph_dir / f"relative_{metric}_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: relative_{metric}_{operation}.svg")
        else:
            print(f"  Skipped: relative_{metric}_{operation}.svg (no data)")

    def plot_relative_branch_prediction(self, operation: str) -> None:
        """Plot relative branch prediction with misses stacked on hits, normalized to Contiguous total branches."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for relative branch prediction")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                # Get Contiguous baseline total branches
                cont_baseline = self._get_contiguous_baseline(test_file, operation, "branches")

                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list or cont_baseline == 0:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_rel_vals, rate_vals = [], [], [], []

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

                    if branches > 0 and misses <= branches:
                        # Normalize to Contiguous total
                        rel_total = branches / cont_baseline
                        rel_misses = misses / cont_baseline
                        rel_hits = (branches - misses) / cont_baseline

                        hits_vals.append(rel_hits)
                        misses_vals.append(rel_misses)
                        total_rel_vals.append(rel_total)
                        rate_vals.append((misses / branches) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_rel_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

                if h_avg_rel > 0:
                    all_rel_errors.append(h_avg_rel)
                    all_rel_errors.append(h_max_rel)
                if m_avg_rel > 0:
                    all_rel_errors.append(m_avg_rel)
                    all_rel_errors.append(m_max_rel)
                if t_avg_rel > 0:
                    all_rel_errors.append(t_avg_rel)
                    all_rel_errors.append(t_max_rel)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(h > 0 for h in hits_means) or any(m > 0 for m in misses_means):
                bars_plotted = True
                # Plot hits (bottom bar)
                ax.bar(
                    pos,
                    hits_means,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                    color=self.COLORS[comp_type],
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                )
                # Plot misses (stacked on top)
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

                # Add error bars on the TOTAL (at the top of the stacked bar)
                for i, (total, total_std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                    if total > 0 and cnt > 0 and total_std > 0:
                        ax.errorbar(
                            pos[i],
                            total,
                            yerr=total_std,
                            fmt="none",
                            ecolor="black",
                            capsize=3,
                            capthick=1,
                            elinewidth=1,
                        )

        max_top = max([t + s for t, s in zip(totals, totals_stds)]) if totals else 1
        label_offset = max_top * 0.02

        # Add labels - re-compute to avoid scope issues
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                cont_baseline = self._get_contiguous_baseline(test_file, operation, "branches")

                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list or cont_baseline == 0:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_rel_vals, rate_vals = [], [], [], []
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

                    if branches > 0 and misses <= branches:
                        rel_total = branches / cont_baseline
                        rel_misses = misses / cont_baseline
                        rel_hits = (branches - misses) / cont_baseline

                        hits_vals.append(rel_hits)
                        misses_vals.append(rel_misses)
                        total_rel_vals.append(rel_total)
                        rate_vals.append((misses / branches) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_rel_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

            pos = x + (idx - n_types / 2 + 0.5) * width

            # Add total value labels above the error bar whiskers
            for i, (total, std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                if total > 0 and cnt > 0:
                    top_of_whisker = total + std
                    label_y = top_of_whisker + label_offset
                    ax.text(pos[i], label_y, f"{total:.3f}", ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

            # Add miss percentage labels (rotated, above the total value label)
            for i, (total, miss_rate, cnt) in enumerate(zip(totals, miss_rates, counts)):
                if total > 0 and cnt > 0 and miss_rate > 0:
                    top_of_whisker = total + totals_stds[i]
                    total_label_y = top_of_whisker + label_offset
                    miss_label_y = total_label_y + max_top * 0.05
                    ax.text(
                        pos[i],
                        miss_label_y,
                        f"miss {miss_rate:.1f}%",
                        ha="center",
                        va="bottom",
                        fontsize=6.5,
                        color="red",
                        fontweight="bold",
                        rotation=20,
                    )
                    max_overall_height = max(max_overall_height, miss_label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Relative Branch Prediction (Read Operation)",
            "write": "Relative Branch Prediction (Write Operation)",
            "overall": "Relative Branch Prediction (Overall)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Relative Branches (× Contiguous Total)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
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

        plt.tight_layout()
        output_path = self.rel_graph_dir / f"relative_branch_prediction_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: relative_branch_prediction_{operation}.svg")
        else:
            print(f"  Skipped: relative_branch_prediction_{operation}.svg (no valid branch data)")

    def plot_relative_cache_performance(self, operation: str) -> None:
        """Plot relative cache performance with misses stacked on hits, normalized to Contiguous total cache references."""
        test_files = sorted(self._results.keys())
        if not test_files:
            print("    No data to plot for relative cache performance")
            return

        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        fig, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        bars_plotted = False
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                # Get Contiguous baseline total cache references
                cont_baseline = self._get_contiguous_baseline(
                    test_file, operation, "cache_references"
                )

                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list or cont_baseline == 0:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_rel_vals, rate_vals = [], [], [], []

                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        perfs = [read_perf]
                    elif operation == "write":
                        perfs = [write_perf]
                    else:
                        perfs = [read_perf, write_perf]

                    total_refs = sum(p.cache_references for p in perfs)
                    total_misses = sum(p.cache_misses for p in perfs)

                    if total_refs > 0 and total_refs >= total_misses:
                        rel_total = total_refs / cont_baseline
                        rel_misses = total_misses / cont_baseline
                        rel_hits = (total_refs - total_misses) / cont_baseline

                        hits_vals.append(rel_hits)
                        misses_vals.append(rel_misses)
                        total_rel_vals.append(rel_total)
                        rate_vals.append((total_misses / total_refs) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_rel_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

                if h_avg_rel > 0:
                    all_rel_errors.append(h_avg_rel)
                    all_rel_errors.append(h_max_rel)
                if m_avg_rel > 0:
                    all_rel_errors.append(m_avg_rel)
                    all_rel_errors.append(m_max_rel)
                if t_avg_rel > 0:
                    all_rel_errors.append(t_avg_rel)
                    all_rel_errors.append(t_max_rel)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(h > 0 for h in hits_means) or any(m > 0 for m in misses_means):
                bars_plotted = True
                # Plot hits (bottom bar)
                ax.bar(
                    pos,
                    hits_means,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                    color=self.COLORS[comp_type],
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                )
                # Plot misses (stacked on top)
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

                # Add error bars on the TOTAL (at the top of the stacked bar)
                for i, (total, total_std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                    if total > 0 and cnt > 0 and total_std > 0:
                        ax.errorbar(
                            pos[i],
                            total,
                            yerr=total_std,
                            fmt="none",
                            ecolor="black",
                            capsize=3,
                            capthick=1,
                            elinewidth=1,
                        )

        max_top = max([t + s for t, s in zip(totals, totals_stds)]) if totals else 1
        label_offset = max_top * 0.02

        # Add labels - re-compute to avoid scope issues
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                cont_baseline = self._get_contiguous_baseline(
                    test_file, operation, "cache_references"
                )

                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list or cont_baseline == 0:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
                    miss_rates.append(0.0)
                    counts.append(0)
                    continue

                hits_vals, misses_vals, total_rel_vals, rate_vals = [], [], [], []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        perfs = [read_perf]
                    elif operation == "write":
                        perfs = [write_perf]
                    else:
                        perfs = [read_perf, write_perf]

                    total_refs = sum(p.cache_references for p in perfs)
                    total_misses = sum(p.cache_misses for p in perfs)

                    if total_refs > 0 and total_refs >= total_misses:
                        rel_total = total_refs / cont_baseline
                        rel_misses = total_misses / cont_baseline
                        rel_hits = (total_refs - total_misses) / cont_baseline

                        hits_vals.append(rel_hits)
                        misses_vals.append(rel_misses)
                        total_rel_vals.append(rel_total)
                        rate_vals.append((total_misses / total_refs) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_rel_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

            pos = x + (idx - n_types / 2 + 0.5) * width

            # Add total value labels above the error bar whiskers
            for i, (total, std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                if total > 0 and cnt > 0:
                    top_of_whisker = total + std
                    label_y = top_of_whisker + label_offset
                    ax.text(pos[i], label_y, f"{total:.3f}", ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

            # Add miss percentage labels (rotated, above the total value label)
            for i, (total, miss_rate, cnt) in enumerate(zip(totals, miss_rates, counts)):
                if total > 0 and cnt > 0 and miss_rate > 0:
                    top_of_whisker = total + totals_stds[i]
                    total_label_y = top_of_whisker + label_offset
                    miss_label_y = total_label_y + max_top * 0.05
                    ax.text(
                        pos[i],
                        miss_label_y,
                        f"miss {miss_rate:.1f}%",
                        ha="center",
                        va="bottom",
                        fontsize=6.5,
                        color="red",
                        fontweight="bold",
                        rotation=20,
                    )
                    max_overall_height = max(max_overall_height, miss_label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Relative Cache Performance (Read Operation)",
            "write": "Relative Cache Performance (Write Operation)",
            "overall": "Relative Cache Performance (Overall)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(
            "Relative Cache References (× Contiguous Total)", fontsize=12, fontweight="bold"
        )
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
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

        plt.tight_layout()
        output_path = self.rel_graph_dir / f"relative_cache_performance_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: relative_cache_performance_{operation}.svg")
        else:
            print(f"  Skipped: relative_cache_performance_{operation}.svg (no valid cache data)")

    # ===== ABSOLUTE GRAPHS (saved to abs_graph_dir) =====

    def plot_instructions_per_cycle(self, operation: str) -> None:
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
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    continue

                ipc_values = []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        ipc = read_perf.ipc
                    elif operation == "write":
                        ipc = write_perf.ipc
                    else:
                        total_cycles = read_perf.cycles + write_perf.cycles
                        total_inst = read_perf.instructions + write_perf.instructions
                        ipc = total_inst / total_cycles if total_cycles > 0 else 0

                    if ipc > 0:
                        ipc_values.append(ipc)

                mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(ipc_values)
                means.append(mean_val)
                stds.append(std_val)
                all_rel_errors.append(avg_rel_err)
                all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 else 0 for s in stds],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

        # Add value labels above error bars
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    continue
                ipc_values = []
                for read_perf, write_perf in metrics_list:
                    if operation == "read":
                        ipc = read_perf.ipc
                    elif operation == "write":
                        ipc = write_perf.ipc
                    else:
                        total_cycles = read_perf.cycles + write_perf.cycles
                        total_inst = read_perf.instructions + write_perf.instructions
                        ipc = total_inst / total_cycles if total_cycles > 0 else 0
                    if ipc > 0:
                        ipc_values.append(ipc)
                mean_val, std_val, _, _, _ = self.calculate_stats(ipc_values)
                means.append(mean_val)
                stds.append(std_val)

            pos = x + (idx - n_types / 2 + 0.5) * width
            for i, (m, s) in enumerate(zip(means, stds)):
                if m > 0:
                    label_y = m + s + (m * 0.01)
                    ax.text(pos[i], label_y, f"{m:.3f}", ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Instructions Per Cycle (Read Operation)",
            "write": "Instructions Per Cycle (Write Operation)",
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

        plt.tight_layout()
        output_path = self.abs_graph_dir / f"ipc_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: ipc_{operation}.svg")
        else:
            print(f"  Skipped: ipc_{operation}.svg (no data)")

    def plot_cycle_comparison(self, operation: str) -> None:
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
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
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

                mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(cycle_values)
                means.append(mean_val)
                stds.append(std_val)
                all_rel_errors.append(avg_rel_err)
                all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 else 0 for s in stds],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

        # Add value labels above error bars
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
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
                mean_val, std_val, _, _, _ = self.calculate_stats(cycle_values)
                means.append(mean_val)
                stds.append(std_val)

            pos = x + (idx - n_types / 2 + 0.5) * width
            for i, (m, s) in enumerate(zip(means, stds)):
                if m > 0:
                    label_y = m + s + (m * 0.01)
                    label = self._format_large_number(m)
                    ax.text(pos[i], label_y, label, ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "CPU Cycles (Read Operation)",
            "write": "CPU Cycles (Write Operation)",
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
        output_path = self.abs_graph_dir / f"cycles_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: cycles_{operation}.svg")
        else:
            print(f"  Skipped: cycles_{operation}.svg (no data)")

    def plot_instruction_comparison(self, operation: str) -> None:
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
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
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

                mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(inst_values)
                means.append(mean_val)
                stds.append(std_val)
                all_rel_errors.append(avg_rel_err)
                all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(m > 0 for m in means):
                bars_plotted = True
                ax.bar(
                    pos,
                    means,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=[s if s > 0 else 0 for s in stds],
                    capsize=3,
                    alpha=0.8,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

        # Add value labels above error bars
        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
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
                mean_val, std_val, _, _, _ = self.calculate_stats(inst_values)
                means.append(mean_val)
                stds.append(std_val)

            pos = x + (idx - n_types / 2 + 0.5) * width
            for i, (m, s) in enumerate(zip(means, stds)):
                if m > 0:
                    label_y = m + s + (m * 0.01)
                    label = self._format_large_number(m)
                    ax.text(pos[i], label_y, label, ha="center", va="bottom", fontsize=7)
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Instructions Executed (Read Operation)",
            "write": "Instructions Executed (Write Operation)",
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
        output_path = self.abs_graph_dir / f"instructions_{operation}.svg"
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
        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
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

                    if branches > 0 and misses <= branches:
                        hits_vals.append(branches - misses)
                        misses_vals.append(misses)
                        total_vals.append(branches)
                        rate_vals.append((misses / branches) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

                if h_avg_rel > 0:
                    all_rel_errors.append(h_avg_rel)
                    all_rel_errors.append(h_max_rel)
                if m_avg_rel > 0:
                    all_rel_errors.append(m_avg_rel)
                    all_rel_errors.append(m_max_rel)
                if t_avg_rel > 0:
                    all_rel_errors.append(t_avg_rel)
                    all_rel_errors.append(t_max_rel)

            pos = x + (idx - n_types / 2 + 0.5) * width

            if any(h > 0 for h in hits_means) or any(m > 0 for m in misses_means):
                bars_plotted = True
                # Plot hits (bottom bar)
                ax.bar(
                    pos,
                    hits_means,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (hits)",
                    color=self.COLORS[comp_type],
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                )
                # Plot misses (stacked on top)
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

                # Add error bars on the TOTAL (at the top of the stacked bar)
                for i, (total, total_std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                    if total > 0 and cnt > 0 and total_std > 0:
                        ax.errorbar(
                            pos[i],
                            total,
                            yerr=total_std,
                            fmt="none",
                            ecolor="black",
                            capsize=3,
                            capthick=1,
                            elinewidth=1,
                        )

        max_top = max([t + s for t, s in zip(totals, totals_stds)]) if totals else 1
        label_offset = max_top * 0.02

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
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

                    if branches > 0 and misses <= branches:
                        hits_vals.append(branches - misses)
                        misses_vals.append(misses)
                        total_vals.append(branches)
                        rate_vals.append((misses / branches) * 100.0)

                h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_vals)
                r_mean = mean(rate_vals) if rate_vals else 0.0

                hits_means.append(h_mean)
                misses_means.append(m_mean)
                totals.append(t_mean)
                totals_stds.append(t_std)
                miss_rates.append(r_mean)
                counts.append(t_cnt)

            pos = x + (idx - n_types / 2 + 0.5) * width

            # Add total value labels above the error bar whiskers
            for i, (total, std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                if total > 0 and cnt > 0:
                    top_of_whisker = total + std
                    label_y = top_of_whisker + label_offset
                    ax.text(
                        pos[i],
                        label_y,
                        self._format_large_number(total),
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )
                    max_overall_height = max(max_overall_height, label_y)

            # Add miss percentage labels (rotated, above the total value label)
            for i, (total, miss_rate, cnt) in enumerate(zip(totals, miss_rates, counts)):
                if total > 0 and cnt > 0 and miss_rate > 0:
                    top_of_whisker = total + totals_stds[i]
                    total_label_y = top_of_whisker + label_offset
                    miss_label_y = total_label_y + max_top * 0.05
                    ax.text(
                        pos[i],
                        miss_label_y,
                        f"miss {miss_rate:.1f}%",
                        ha="center",
                        va="bottom",
                        fontsize=6.5,
                        color="red",
                        fontweight="bold",
                        rotation=20,
                    )
                    max_overall_height = max(max_overall_height, miss_label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Branch Prediction (Read Operation)",
            "write": "Branch Prediction (Write Operation)",
            "overall": "Branch Prediction (Overall)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Number of Branches", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
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
        output_path = self.abs_graph_dir / f"branch_prediction_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: branch_prediction_{operation}.svg")
        else:
            print(f"  Skipped: branch_prediction_{operation}.svg (no valid branch data)")

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
        all_rel_errors = []
        max_overall_height = 0.0

        all_comp_data = []

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            hits_means = []
            misses_means = []
            totals = []
            totals_stds = []
            miss_rates = []
            counts = []

            for test_file in test_files:
                metrics_list = self._results[test_file].get(comp_type, [])
                if not metrics_list:
                    hits_means.append(0.0)
                    misses_means.append(0.0)
                    totals.append(0.0)
                    totals_stds.append(0.0)
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
                            total_vals.append(total_misses)
                    elif cache_level == "LLC":
                        total_misses = sum(p.llc_load_misses for p in perfs)
                        if total_misses > 0:
                            misses_vals.append(total_misses)
                            total_vals.append(total_misses)
                    else:  # all cache
                        total_refs = sum(p.cache_references for p in perfs)
                        total_misses = sum(p.cache_misses for p in perfs)
                        if total_refs > 0 and total_refs >= total_misses:
                            hits_vals.append(total_refs - total_misses)
                            misses_vals.append(total_misses)
                            total_vals.append(total_refs)
                            rate_vals.append((total_misses / total_refs) * 100.0)

                if cache_level in ["L1", "LLC"]:
                    miss_mean, miss_std, miss_avg_rel, miss_max_rel, miss_cnt = (
                        self.calculate_stats(misses_vals)
                    )
                    t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_vals)
                    hits_means.append(0.0)
                    misses_means.append(miss_mean)
                    totals.append(t_mean)
                    totals_stds.append(miss_std)
                    miss_rates.append(0.0)
                    counts.append(miss_cnt)
                    all_rel_errors.append(miss_avg_rel)
                    all_rel_errors.append(miss_max_rel)
                    all_rel_errors.append(t_avg_rel)
                    all_rel_errors.append(t_max_rel)
                else:
                    h_mean, h_std, h_avg_rel, h_max_rel, h_cnt = self.calculate_stats(hits_vals)
                    m_mean, m_std, m_avg_rel, m_max_rel, m_cnt = self.calculate_stats(misses_vals)
                    t_mean, t_std, t_avg_rel, t_max_rel, t_cnt = self.calculate_stats(total_vals)
                    r_mean = mean(rate_vals) if rate_vals else 0.0

                    hits_means.append(h_mean)
                    misses_means.append(m_mean)
                    totals.append(t_mean)
                    totals_stds.append(t_std)
                    miss_rates.append(r_mean)
                    counts.append(t_cnt)
                    all_rel_errors.append(h_avg_rel)
                    all_rel_errors.append(h_max_rel)
                    all_rel_errors.append(m_avg_rel)
                    all_rel_errors.append(m_max_rel)
                    all_rel_errors.append(t_avg_rel)
                    all_rel_errors.append(t_max_rel)

            pos = x + (idx - n_types / 2 + 0.5) * width

            all_comp_data.append(
                {
                    "comp_type": comp_type,
                    "pos": pos,
                    "hits_means": hits_means,
                    "misses_means": misses_means,
                    "totals": totals,
                    "totals_stds": totals_stds,
                    "miss_rates": miss_rates,
                    "counts": counts,
                }
            )

            if cache_level in ["L1", "LLC"]:
                if any(m > 0 for m in misses_means):
                    bars_plotted = True
                    ax.bar(
                        pos,
                        misses_means,
                        width,
                        label=self.COMPRESSION_NAMES[comp_type],
                        color=self.COLORS[comp_type],
                        yerr=[s if s > 0 else 0 for s in totals_stds],
                        capsize=3,
                        alpha=0.8,
                        edgecolor="black",
                        linewidth=0.8,
                        error_kw={"elinewidth": 1, "capthick": 1},
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

                    for i, (total, total_std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                        if total > 0 and cnt > 0 and total_std > 0:
                            ax.errorbar(
                                pos[i],
                                total,
                                yerr=total_std,
                                fmt="none",
                                ecolor="black",
                                capsize=3,
                                capthick=1,
                                elinewidth=1,
                            )

        max_top = max([t + s for t, s in zip(totals, totals_stds)]) if totals else 1
        label_offset = max_top * 0.02

        for comp_data in all_comp_data:
            pos = comp_data["pos"]
            totals = comp_data["totals"]
            totals_stds = comp_data["totals_stds"]
            counts = comp_data["counts"]
            miss_rates = comp_data["miss_rates"]

            for i, (total, std, cnt) in enumerate(zip(totals, totals_stds, counts)):
                if total > 0 and cnt > 0:
                    top_of_whisker = total + std
                    label_y = top_of_whisker + label_offset
                    ax.text(
                        pos[i],
                        label_y,
                        self._format_large_number(total),
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )
                    max_overall_height = max(max_overall_height, label_y)

            if cache_level not in ["L1", "LLC"]:
                for i, (total, miss_rate, cnt) in enumerate(zip(totals, miss_rates, counts)):
                    if total > 0 and cnt > 0 and miss_rate > 0:
                        top_of_whisker = total + totals_stds[i]
                        total_label_y = top_of_whisker + label_offset
                        miss_label_y = total_label_y + max_top * 0.05
                        ax.text(
                            pos[i],
                            miss_label_y,
                            f"miss {miss_rate:.1f}%",
                            ha="center",
                            va="bottom",
                            fontsize=6.5,
                            color="red",
                            fontweight="bold",
                            rotation=20,
                        )
                        max_overall_height = max(max_overall_height, miss_label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        cache_names = {"L1": "L1 Data Cache", "LLC": "Last Level Cache", "all": "Cache"}
        ylabel = "Cache Misses" if cache_level in ["L1", "LLC"] else "Cache References"

        title_map = {
            "read": f"{cache_names[cache_level]} Performance (Read Operation)",
            "write": f"{cache_names[cache_level]} Performance (Write Operation)",
            "overall": f"{cache_names[cache_level]} Performance (Overall)",
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
        output_path = self.abs_graph_dir / f"cache_{cache_suffix[cache_level]}_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: cache_{cache_suffix[cache_level]}_{operation}.svg")
        else:
            print(f"  Skipped: cache_{cache_suffix[cache_level]}_{operation}.svg (no cache data)")

    def generate_all_graphs(self) -> None:
        has_data = self.load_results_and_perf()

        if not has_data:
            print("\nERROR: No valid perf data found! Skipping all graph generation.")
            return

        print(f"\nFound {len(self._results)} test files with valid perf data")

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

        operations = ["read", "write", "overall"]

        # ===== ABSOLUTE GRAPHS =====
        print("\n" + "=" * 60)
        print("Generating ABSOLUTE value graphs...")
        print("=" * 60)

        graph_count = 1
        total_graphs = 21

        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: IPC ({op})")
                self.plot_instructions_per_cycle(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: IPC graphs skipped")
            graph_count += 3

        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Cycles ({op})")
                self.plot_cycle_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: Cycles graphs skipped")
            graph_count += 3

        if has_cycle_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: Instructions ({op})")
                self.plot_instruction_comparison(op)
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: Instructions graphs skipped")
            graph_count += 3

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

        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: L1 cache misses ({op})")
                self.plot_cache_performance(op, "L1")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: L1 cache graphs skipped")
            graph_count += 3

        if has_cache_data:
            for op in operations:
                print(f"  {graph_count}/{total_graphs}: LLC misses ({op})")
                self.plot_cache_performance(op, "LLC")
                graph_count += 1
        else:
            print(f"  {graph_count}-{graph_count + 2}/{total_graphs}: LLC miss graphs skipped")
            graph_count += 3

        # ===== RELATIVE GRAPHS =====
        print("\n" + "=" * 60)
        print("Generating RELATIVE value graphs (normalized to Contiguous)...")
        print("=" * 60)

        rel_graph_count = 1
        total_rel_graphs = 0
        if has_cycle_data:
            total_rel_graphs += 9  # IPC, Cycles, Instructions × 3 ops
        if has_branch_data:
            total_rel_graphs += 3  # Branch prediction × 3 ops
        if has_cache_data:
            total_rel_graphs += 3  # Cache performance × 3 ops

        if has_cycle_data:
            for op in operations:
                print(f"  {rel_graph_count}/{total_rel_graphs}: Relative IPC ({op})")
                self.plot_relative_metric(op, "ipc", "IPC", higher_is_better=True)
                rel_graph_count += 1

            for op in operations:
                print(f"  {rel_graph_count}/{total_rel_graphs}: Relative Cycles ({op})")
                self.plot_relative_metric(op, "cycles", "Cycles", higher_is_better=False)
                rel_graph_count += 1

            for op in operations:
                print(f"  {rel_graph_count}/{total_rel_graphs}: Relative Instructions ({op})")
                self.plot_relative_metric(
                    op, "instructions", "Instructions", higher_is_better=False
                )
                rel_graph_count += 1

        if has_branch_data:
            for op in operations:
                print(f"  {rel_graph_count}/{total_rel_graphs}: Relative Branch Prediction ({op})")
                self.plot_relative_branch_prediction(op)
                rel_graph_count += 1

        if has_cache_data:
            for op in operations:
                print(f"  {rel_graph_count}/{total_rel_graphs}: Relative Cache Performance ({op})")
                self.plot_relative_cache_performance(op)
                rel_graph_count += 1

        print(f"\nAbsolute graphs saved to: {self.abs_graph_dir}")
        print(f"Relative graphs saved to: {self.rel_graph_dir}")


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
