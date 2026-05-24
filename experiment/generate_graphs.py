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
Generate performance comparison graphs for LZ4 compression variations.
"""

from argparse import ArgumentParser
from dataclasses import dataclass
from json import load
from pathlib import Path
from statistics import mean, stdev
from typing import Dict, List, Tuple

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
    }
)


@dataclass
class IOMetrics:
    """Container for I/O statistics (separate for read and write)."""

    reqs_total: int = 0
    reqs_failed: int = 0
    min_vec: int = 0
    max_vec: int = 0
    vecs: int = 0
    segments: int = 0
    decomp_size: int = 0
    comp_size: int = 0
    mem_usage: int = 0
    copy_ns: int = 0
    comp_ns: int = 0
    decomp_ns: int = 0
    total_ns: int = 0


class GraphGenerator:
    COMPRESSION_TYPES = ["cont", "vect", "strm", "extd"]
    COMPRESSION_NAMES = {
        "cont": "Contiguous",
        "vect": "Vectorized",
        "strm": "Streaming",
        "extd": "Extended",
    }

    COLORS = {"cont": "#1f77b4", "vect": "#ff7f0e", "strm": "#2ca02c", "extd": "#d62728"}

    def __init__(self, result_dir: Path, graph_dir: Path):
        self.result_dir = Path(result_dir)
        self.graph_dir = Path(graph_dir)
        self.graph_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories for absolute and relative graphs
        self.abs_graph_dir = self.graph_dir / "absolute"
        self.rel_graph_dir = self.graph_dir / "relative"
        self.abs_graph_dir.mkdir(parents=True, exist_ok=True)
        self.rel_graph_dir.mkdir(parents=True, exist_ok=True)

    def load_results(self) -> Dict[str, Dict[str, List[Tuple[IOMetrics, IOMetrics]]]]:
        """
        Load all results organized by test file and compression type.
        Returns: {test_file: {comp_type: [(read_metrics, write_metrics)]}}
        """
        results: Dict[str, Dict[str, List[Tuple[IOMetrics, IOMetrics]]]] = {}

        for comp_type in self.COMPRESSION_TYPES:
            comp_dir = self.result_dir / comp_type
            if not comp_dir.exists():
                continue

            for json_file in comp_dir.glob("*.json"):
                try:
                    with open(json_file) as f:
                        data = load(f)

                    test_file = data["test_file"]
                    if test_file not in results:
                        results[test_file] = {ct: [] for ct in self.COMPRESSION_TYPES}

                    stats = data["statistics"]

                    # Read metrics
                    read_metrics = IOMetrics(
                        reqs_total=stats.get("stats_r_reqs_total", 0),
                        reqs_failed=stats.get("stats_r_reqs_failed", 0),
                        min_vec=stats.get("stats_r_min_vec", 0),
                        max_vec=stats.get("stats_r_max_vec", 0),
                        vecs=stats.get("stats_r_vecs", 0),
                        segments=stats.get("stats_r_segments", 0),
                        decomp_size=stats.get("stats_r_decomp_size", 0),
                        comp_size=stats.get("stats_r_comp_size", 0),
                        mem_usage=stats.get("stats_r_mem_usage", 0),
                        copy_ns=stats.get("stats_r_copy_ns", 0),
                        comp_ns=stats.get("stats_r_comp_ns", 0),
                        decomp_ns=stats.get("stats_r_decomp_ns", 0),
                        total_ns=stats.get("stats_r_total_ns", 0),
                    )

                    # Write metrics
                    write_metrics = IOMetrics(
                        reqs_total=stats.get("stats_w_reqs_total", 0),
                        reqs_failed=stats.get("stats_w_reqs_failed", 0),
                        min_vec=stats.get("stats_w_min_vec", 0),
                        max_vec=stats.get("stats_w_max_vec", 0),
                        vecs=stats.get("stats_w_vecs", 0),
                        segments=stats.get("stats_w_segments", 0),
                        decomp_size=stats.get("stats_w_decomp_size", 0),
                        comp_size=stats.get("stats_w_comp_size", 0),
                        mem_usage=stats.get("stats_w_mem_usage", 0),
                        copy_ns=stats.get("stats_w_copy_ns", 0),
                        comp_ns=stats.get("stats_w_comp_ns", 0),
                        decomp_ns=stats.get("stats_w_decomp_ns", 0),
                        total_ns=stats.get("stats_w_total_ns", 0),
                    )

                    results[test_file][comp_type].append((read_metrics, write_metrics))
                except Exception as e:
                    print(f"Error processing {json_file}: {e}")

        return results

    def calculate_stats(self, values: List[float]) -> Tuple[float, float, float, float, int]:
        """
        Calculate mean, standard deviation, average relative error, max relative error, and count.
        Relative error = (std_dev / mean) * 100%
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
        current_ylim = ax.get_ylim()
        if max_bar_height > 0:
            # Add 18% padding above the highest point (bar + error + label)
            new_ymax = max_bar_height * 1.18
            if new_ymax > current_ylim[1]:
                ax.set_ylim(0, new_ymax)

    def _get_contiguous_baseline(
        self, results: Dict, test_file: str, metric: str, operation: str = "overall"
    ) -> float:
        """Get the Contiguous baseline mean for normalization."""
        cont_metrics = results[test_file].get("cont", [])
        if not cont_metrics:
            return 0.0

        values = self._extract_metric_values(cont_metrics, metric, operation)
        return mean(values) if values else 0.0

    def _extract_metric_values(
        self, metrics_list: List[Tuple[IOMetrics, IOMetrics]], metric: str, operation: str
    ) -> List[float]:
        """Extract metric values from a list of (read_metrics, write_metrics) tuples."""
        values = []

        for read_m, write_m in metrics_list:
            val = self._calculate_single_metric(read_m, write_m, metric, operation)
            if val > 0:
                values.append(val)

        return values

    def _calculate_single_metric(
        self, read_m: IOMetrics, write_m: IOMetrics, metric: str, operation: str
    ) -> float:
        """Calculate a single metric value from read and write metrics."""
        if metric == "compression_ratio":
            total_decomp = read_m.decomp_size + write_m.decomp_size
            total_comp = read_m.comp_size + write_m.comp_size
            return total_decomp / total_comp if total_comp > 0 else 0.0

        elif metric == "memory_usage":
            total_mem = read_m.mem_usage + write_m.mem_usage
            total_reqs = read_m.reqs_total + write_m.reqs_total
            total_failed = read_m.reqs_failed + write_m.reqs_failed
            successful_reqs = total_reqs - total_failed
            return (
                (total_mem / successful_reqs / 1024)
                if successful_reqs > 0 and total_mem > 0
                else 0.0
            )

        elif metric == "compression_throughput":
            if operation == "read":
                total_time = read_m.comp_ns + read_m.copy_ns
                return (
                    (read_m.decomp_size / 1e6) / (total_time / 1e9)
                    if total_time > 0 and read_m.decomp_size > 0
                    else 0.0
                )
            elif operation == "write":
                total_time = write_m.comp_ns + write_m.copy_ns
                return (
                    (write_m.decomp_size / 1e6) / (total_time / 1e9)
                    if total_time > 0 and write_m.decomp_size > 0
                    else 0.0
                )
            else:  # overall
                run_decomp = read_m.decomp_size + write_m.decomp_size
                run_comp_ns = read_m.comp_ns + write_m.comp_ns
                run_copy_ns = read_m.copy_ns + write_m.copy_ns
                total_time = run_comp_ns + run_copy_ns
                return (run_decomp / 1e6) / (total_time / 1e9) if total_time > 0 else 0.0

        elif metric == "decompression_throughput":
            if operation == "read":
                total_time = read_m.decomp_ns + read_m.copy_ns
                return (
                    (read_m.comp_size / 1e6) / (total_time / 1e9)
                    if total_time > 0 and read_m.comp_size > 0
                    else 0.0
                )
            elif operation == "write":
                total_time = write_m.decomp_ns + write_m.copy_ns
                return (
                    (write_m.comp_size / 1e6) / (total_time / 1e9)
                    if total_time > 0 and write_m.comp_size > 0
                    else 0.0
                )
            else:  # overall
                run_comp = read_m.comp_size + write_m.comp_size
                run_decomp_ns = read_m.decomp_ns + write_m.decomp_ns
                run_copy_ns = read_m.copy_ns + write_m.copy_ns
                total_time = run_decomp_ns + run_copy_ns
                return (run_comp / 1e6) / (total_time / 1e9) if total_time > 0 else 0.0

        elif metric == "total_throughput":
            if operation == "read":
                return (
                    (read_m.decomp_size / 1e6) / (read_m.total_ns / 1e9)
                    if read_m.total_ns > 0 and read_m.decomp_size > 0
                    else 0.0
                )
            elif operation == "write":
                return (
                    (write_m.decomp_size / 1e6) / (write_m.total_ns / 1e9)
                    if write_m.total_ns > 0 and write_m.decomp_size > 0
                    else 0.0
                )
            else:  # overall
                run_decomp = read_m.decomp_size + write_m.decomp_size
                run_time = read_m.total_ns + write_m.total_ns
                return (run_decomp / 1e6) / (run_time / 1e9) if run_time > 0 else 0.0

        return 0.0

    def _plot_relative_metric(
        self, results: Dict, metric: str, metric_name: str, operation: str = "overall"
    ) -> None:
        """Generate relative performance graph for a specific compression metric."""
        test_files = list(results.keys())
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
                    cont_baseline = self._get_contiguous_baseline(
                        results, test_file, metric, operation
                    )
                    if cont_baseline > 0:
                        means.append(1.0)
                        stds.append(0.0)
                    else:
                        means.append(0.0)
                        stds.append(0.0)
                else:
                    cont_baseline = self._get_contiguous_baseline(
                        results, test_file, metric, operation
                    )
                    if cont_baseline == 0:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    metrics_list = results[test_file].get(comp_type, [])
                    if not metrics_list:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    rel_values = []
                    for read_m, write_m in metrics_list:
                        val = self._calculate_single_metric(read_m, write_m, metric, operation)
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
                    cont_baseline = self._get_contiguous_baseline(
                        results, test_file, metric, operation
                    )
                    if cont_baseline > 0:
                        means.append(1.0)
                        stds.append(0.0)
                    else:
                        means.append(0.0)
                        stds.append(0.0)
                else:
                    cont_baseline = self._get_contiguous_baseline(
                        results, test_file, metric, operation
                    )
                    if cont_baseline == 0:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    metrics_list = results[test_file].get(comp_type, [])
                    if not metrics_list:
                        means.append(0.0)
                        stds.append(0.0)
                        continue

                    rel_values = []
                    for read_m, write_m in metrics_list:
                        val = self._calculate_single_metric(read_m, write_m, metric, operation)
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

        # Build title
        if operation == "overall":
            title = f"Relative {metric_name}"
        else:
            title = f"Relative {metric_name} ({operation.capitalize()} Operation)"

        ylabel = f"Relative {metric_name} (× Contiguous)"

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel(ylabel, fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")

        if bars_plotted:
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()

        # Build filename
        if operation == "overall":
            filename = f"relative_{metric}.svg"
        else:
            filename = f"relative_{metric}_{operation}.svg"

        output_path = self.rel_graph_dir / filename
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()

        if bars_plotted:
            print(f"  Generated: {filename}")
        else:
            print(f"  Skipped: {filename} (no data)")

    # ===== ABSOLUTE GRAPHS =====

    def plot_compression_ratio(self, results: Dict) -> None:
        """
        Compression ratio = decomp_size / comp_size
        Uses overall metrics (sum of read and write)
        """
        test_files = list(results.keys())
        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []
            for test_file in test_files:
                metrics_list = results[test_file][comp_type]
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    continue

                ratios = []
                for read_m, write_m in metrics_list:
                    total_decomp = read_m.decomp_size + write_m.decomp_size
                    total_comp = read_m.comp_size + write_m.comp_size
                    if total_comp > 0:
                        ratio = total_decomp / total_comp
                        ratios.append(ratio)

                mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(ratios)
                means.append(mean_val)
                stds.append(std_val)
                all_rel_errors.append(avg_rel_err)
                all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width
            bars = ax.bar(
                pos,
                means,
                width,
                label=self.COMPRESSION_NAMES[comp_type],
                color=self.COLORS[comp_type],
                yerr=stds,
                capsize=3,
                alpha=0.8,
                edgecolor="black",
                linewidth=0.8,
                error_kw={"elinewidth": 1, "capthick": 1},
            )

            for bar, mean_val, std_val in zip(bars, means, stds):
                if mean_val > 0:
                    label_y = bar.get_height() + std_val + (mean_val * 0.01)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        label_y,
                        f"{mean_val:.3f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Compression Ratio", fontsize=12, fontweight="bold")
        ax.set_title(
            "Compression Ratio (Original Size / Compressed Size)",
            fontsize=13,
            fontweight="bold",
        )
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        plt.savefig(self.abs_graph_dir / "compression_ratio.svg", format="svg", bbox_inches="tight")
        plt.close()
        print("  Generated: compression_ratio.svg")

    def plot_memory_usage(self, results: Dict) -> None:
        """
        Average memory usage per successful request = mem_usage / (reqs_total - reqs_failed)
        Uses overall metrics (sum of read and write)
        """
        test_files = list(results.keys())
        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means, stds = [], []

            for test_file in test_files:
                metrics_list = results[test_file][comp_type]
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    continue

                mem_per_req = []
                for read_m, write_m in metrics_list:
                    total_mem = read_m.mem_usage + write_m.mem_usage
                    total_reqs = read_m.reqs_total + write_m.reqs_total
                    total_failed = read_m.reqs_failed + write_m.reqs_failed
                    successful_reqs = total_reqs - total_failed
                    if successful_reqs > 0 and total_mem > 0:
                        mem = total_mem / successful_reqs
                        mem_per_req.append(mem / 1024)  # Convert to KB

                mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(mem_per_req)
                means.append(mean_val)
                stds.append(std_val)
                all_rel_errors.append(avg_rel_err)
                all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width
            bars = ax.bar(
                pos,
                means,
                width,
                label=self.COMPRESSION_NAMES[comp_type],
                color=self.COLORS[comp_type],
                yerr=stds,
                capsize=3,
                alpha=0.75,
                edgecolor="black",
                linewidth=0.8,
                error_kw={"elinewidth": 1, "capthick": 1},
            )

            for bar, mean_val, std_val in zip(bars, means, stds):
                if mean_val > 0:
                    label_y = bar.get_height() + std_val + (mean_val * 0.01)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        label_y,
                        f"{mean_val:.1f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Memory Usage per Request (KB)", fontsize=12, fontweight="bold")
        ax.set_title("Average Memory Usage (per I/O)", fontsize=13, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        plt.savefig(self.abs_graph_dir / "memory_usage.svg", format="svg", bbox_inches="tight")
        plt.close()
        print("  Generated: memory_usage.svg")

    def plot_compression_throughput(self, results: Dict, operation: str) -> None:
        """
        Compression throughput = decomp_size / comp_ns
        For both READ and WRITE operations (device compresses on every I/O)
        """
        test_files = list(results.keys())
        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            base_throughputs = []
            copy_overheads = []
            base_stds = []

            for test_file in test_files:
                metrics_list = results[test_file][comp_type]
                if not metrics_list:
                    base_throughputs.append(0.0)
                    copy_overheads.append(0.0)
                    base_stds.append(0.0)
                    continue

                if operation == "read":
                    values_actual = []
                    values_ideal = []

                    for read_m, _ in metrics_list:
                        if read_m.comp_ns > 0 and read_m.decomp_size > 0:
                            total_time = read_m.comp_ns + read_m.copy_ns
                            tp_actual = (
                                (read_m.decomp_size / 1e6) / (total_time / 1e9)
                                if total_time > 0
                                else 0
                            )
                            values_actual.append(tp_actual)

                            tp_ideal = (read_m.decomp_size / 1e6) / (read_m.comp_ns / 1e9)
                            values_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        values_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(values_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "write":
                    values_actual = []
                    values_ideal = []

                    for _, write_m in metrics_list:
                        if write_m.comp_ns > 0 and write_m.decomp_size > 0:
                            total_time = write_m.comp_ns + write_m.copy_ns
                            tp_actual = (
                                (write_m.decomp_size / 1e6) / (total_time / 1e9)
                                if total_time > 0
                                else 0
                            )
                            values_actual.append(tp_actual)

                            tp_ideal = (write_m.decomp_size / 1e6) / (write_m.comp_ns / 1e9)
                            values_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        values_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(values_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "overall":
                    per_run_actual = []
                    per_run_ideal = []

                    for read_m, write_m in metrics_list:
                        run_decomp = read_m.decomp_size + write_m.decomp_size
                        run_comp_ns = read_m.comp_ns + write_m.comp_ns
                        run_copy_ns = read_m.copy_ns + write_m.copy_ns

                        if run_comp_ns > 0:
                            total_time = run_comp_ns + run_copy_ns
                            tp_actual = (
                                (run_decomp / 1e6) / (total_time / 1e9) if total_time > 0 else 0
                            )
                            per_run_actual.append(tp_actual)

                            tp_ideal = (run_decomp / 1e6) / (run_comp_ns / 1e9)
                            per_run_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        per_run_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(per_run_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width
            has_overhead = any(o > 0 for o in copy_overheads)

            if has_overhead:
                _ = ax.bar(
                    pos,
                    base_throughputs,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (actual)",
                    color=self.COLORS[comp_type],
                    yerr=base_stds,
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                _ = ax.bar(
                    pos,
                    copy_overheads,
                    width,
                    bottom=base_throughputs,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (copy loss)",
                    color=self.COLORS[comp_type],
                    alpha=0.3,
                    edgecolor="none",
                    linewidth=0,
                )

                for i, (base, std) in enumerate(zip(base_throughputs, base_stds)):
                    if base > 0:
                        label_y = base + std + (base * 0.01)
                        ax.text(
                            pos[i], label_y, f"{base:.1f}", ha="center", va="bottom", fontsize=7
                        )
                        max_overall_height = max(max_overall_height, label_y)
            else:
                bars = ax.bar(
                    pos,
                    base_throughputs,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=base_stds,
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                for bar, val, std in zip(bars, base_throughputs, base_stds):
                    if val > 0:
                        label_y = bar.get_height() + std + (val * 0.01)
                        ax.text(
                            bar.get_x() + bar.get_width() / 2.0,
                            label_y,
                            f"{val:.1f}",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )
                        max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Compression Throughput (Read Operation)",
            "write": "Compression Throughput (Write Operation)",
            "overall": "Overall Compression Throughput (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Compression Throughput (MB/s)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")

        handles, labels = ax.get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        ax.legend(unique.values(), unique.keys(), loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        output_path = self.abs_graph_dir / f"compression_throughput_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: compression_throughput_{operation}.svg")

    def plot_decompression_throughput(self, results: Dict, operation: str) -> None:
        """
        Decompression throughput = comp_size / decomp_ns
        For both READ and WRITE operations (device decompresses on every I/O)
        """
        test_files = list(results.keys())
        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            base_throughputs = []
            copy_overheads = []
            base_stds = []

            for test_file in test_files:
                metrics_list = results[test_file][comp_type]
                if not metrics_list:
                    base_throughputs.append(0.0)
                    copy_overheads.append(0.0)
                    base_stds.append(0.0)
                    continue

                if operation == "read":
                    values_actual = []
                    values_ideal = []

                    for read_m, _ in metrics_list:
                        if read_m.decomp_ns > 0 and read_m.comp_size > 0:
                            total_time = read_m.decomp_ns + read_m.copy_ns
                            tp_actual = (
                                (read_m.comp_size / 1e6) / (total_time / 1e9)
                                if total_time > 0
                                else 0
                            )
                            values_actual.append(tp_actual)

                            tp_ideal = (read_m.comp_size / 1e6) / (read_m.decomp_ns / 1e9)
                            values_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        values_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(values_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "write":
                    values_actual = []
                    values_ideal = []

                    for _, write_m in metrics_list:
                        if write_m.decomp_ns > 0 and write_m.comp_size > 0:
                            total_time = write_m.decomp_ns + write_m.copy_ns
                            tp_actual = (
                                (write_m.comp_size / 1e6) / (total_time / 1e9)
                                if total_time > 0
                                else 0
                            )
                            values_actual.append(tp_actual)

                            tp_ideal = (write_m.comp_size / 1e6) / (write_m.decomp_ns / 1e9)
                            values_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        values_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(values_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "overall":
                    per_run_actual = []
                    per_run_ideal = []

                    for read_m, write_m in metrics_list:
                        run_comp = read_m.comp_size + write_m.comp_size
                        run_decomp_ns = read_m.decomp_ns + write_m.decomp_ns
                        run_copy_ns = read_m.copy_ns + write_m.copy_ns

                        if run_decomp_ns > 0:
                            total_time = run_decomp_ns + run_copy_ns
                            tp_actual = (
                                (run_comp / 1e6) / (total_time / 1e9) if total_time > 0 else 0
                            )
                            per_run_actual.append(tp_actual)

                            tp_ideal = (run_comp / 1e6) / (run_decomp_ns / 1e9)
                            per_run_ideal.append(tp_ideal)

                    mean_actual, std_actual, avg_rel_err, max_rel_err, _ = self.calculate_stats(
                        per_run_actual
                    )
                    mean_ideal, _, _, _, _ = self.calculate_stats(per_run_ideal)

                    overhead = mean_ideal - mean_actual if mean_ideal > mean_actual else 0

                    base_throughputs.append(mean_actual)
                    copy_overheads.append(overhead)
                    base_stds.append(std_actual)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

            pos = x + (idx - n_types / 2 + 0.5) * width
            has_overhead = any(o > 0 for o in copy_overheads)

            if has_overhead:
                _ = ax.bar(
                    pos,
                    base_throughputs,
                    width,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (actual)",
                    color=self.COLORS[comp_type],
                    yerr=base_stds,
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                _ = ax.bar(
                    pos,
                    copy_overheads,
                    width,
                    bottom=base_throughputs,
                    label=f"{self.COMPRESSION_NAMES[comp_type]} (copy loss)",
                    color=self.COLORS[comp_type],
                    alpha=0.3,
                    edgecolor="none",
                    linewidth=0,
                )

                for i, (base, std) in enumerate(zip(base_throughputs, base_stds)):
                    if base > 0:
                        label_y = base + std + (base * 0.01)
                        ax.text(
                            pos[i], label_y, f"{base:.1f}", ha="center", va="bottom", fontsize=7
                        )
                        max_overall_height = max(max_overall_height, label_y)
            else:
                bars = ax.bar(
                    pos,
                    base_throughputs,
                    width,
                    label=self.COMPRESSION_NAMES[comp_type],
                    color=self.COLORS[comp_type],
                    yerr=base_stds,
                    capsize=3,
                    alpha=0.75,
                    edgecolor="black",
                    linewidth=0.8,
                    error_kw={"elinewidth": 1, "capthick": 1},
                )

                for bar, val, std in zip(bars, base_throughputs, base_stds):
                    if val > 0:
                        label_y = bar.get_height() + std + (val * 0.01)
                        ax.text(
                            bar.get_x() + bar.get_width() / 2.0,
                            label_y,
                            f"{val:.1f}",
                            ha="center",
                            va="bottom",
                            fontsize=7,
                        )
                        max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Decompression Throughput (Read Operation)",
            "write": "Decompression Throughput (Write Operation)",
            "overall": "Overall Decompression Throughput (Read + Write)",
        }

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Decompression Throughput (MB/s)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation], fontsize=12, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")

        handles, labels = ax.get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        ax.legend(unique.values(), unique.keys(), loc="center left", bbox_to_anchor=(1.02, 0.5))

        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        output_path = self.abs_graph_dir / f"decompression_throughput_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: decompression_throughput_{operation}.svg")

    def plot_total_throughput(self, results: Dict, operation: str) -> None:
        """
        Total throughput = decomp_size / total_ns
        For READ: uses stats_r_total_ns and stats_r_decomp_size
        For WRITE: uses stats_w_total_ns and stats_w_decomp_size
        For OVERALL: combines both
        """
        test_files = list(results.keys())
        n_files = len(test_files)
        n_types = len(self.COMPRESSION_TYPES)

        _, ax = plt.subplots(figsize=(16, 7))
        x = arange(n_files)
        width = 0.8 / n_types

        all_rel_errors = []
        max_overall_height = 0.0

        for idx, comp_type in enumerate(self.COMPRESSION_TYPES):
            means = []
            stds = []

            for test_file in test_files:
                metrics_list = results[test_file][comp_type]
                if not metrics_list:
                    means.append(0.0)
                    stds.append(0.0)
                    continue

                if operation == "read":
                    values = []
                    for read_m, _ in metrics_list:
                        if read_m.total_ns > 0 and read_m.decomp_size > 0:
                            tp = (read_m.decomp_size / 1e6) / (read_m.total_ns / 1e9)
                            values.append(tp)
                    mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(values)
                    means.append(mean_val)
                    stds.append(std_val)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "write":
                    values = []
                    for _, write_m in metrics_list:
                        if write_m.total_ns > 0 and write_m.decomp_size > 0:
                            tp = (write_m.decomp_size / 1e6) / (write_m.total_ns / 1e9)
                            values.append(tp)
                    mean_val, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(values)
                    means.append(mean_val)
                    stds.append(std_val)
                    all_rel_errors.append(avg_rel_err)
                    all_rel_errors.append(max_rel_err)

                elif operation == "overall":
                    total_decomp = 0
                    total_time = 0
                    per_run_tp = []

                    for read_m, write_m in metrics_list:
                        run_decomp = read_m.decomp_size + write_m.decomp_size
                        run_time = read_m.total_ns + write_m.total_ns

                        if run_time > 0:
                            run_tp = (run_decomp / 1e6) / (run_time / 1e9)
                            per_run_tp.append(run_tp)

                            total_decomp += run_decomp
                            total_time += run_time

                    if total_time > 0:
                        overall_tp = (total_decomp / 1e6) / (total_time / 1e9)
                        _, std_val, avg_rel_err, max_rel_err, _ = self.calculate_stats(per_run_tp)
                        means.append(overall_tp)
                        stds.append(std_val)
                        all_rel_errors.append(avg_rel_err)
                        all_rel_errors.append(max_rel_err)
                    else:
                        means.append(0)
                        stds.append(0)

            pos = x + (idx - n_types / 2 + 0.5) * width
            bars = ax.bar(
                pos,
                means,
                width,
                label=self.COMPRESSION_NAMES[comp_type],
                color=self.COLORS[comp_type],
                yerr=stds,
                capsize=3,
                alpha=0.75,
                edgecolor="black",
                linewidth=0.8,
                error_kw={"elinewidth": 1, "capthick": 1},
            )

            for bar, mean_val, std_val in zip(bars, means, stds):
                if mean_val > 0:
                    label_y = bar.get_height() + std_val + (mean_val * 0.01)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        label_y,
                        f"{mean_val:.1f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )
                    max_overall_height = max(max_overall_height, label_y)

        self._add_error_stats_to_plot(ax, all_rel_errors, max_overall_height)

        title_map = {
            "read": "Total Throughput (Read Operation)",
            "write": "Total Throughput (Write Operation)",
            "overall": "Overall Total Throughput (Read + Write)",
        }

        subtitle = "\n(Includes compression, decompression, copy, and device I/O)"

        ax.set_xlabel("Test Files", fontsize=12, fontweight="bold")
        ax.set_ylabel("Total Throughput (MB/s)", fontsize=12, fontweight="bold")
        ax.set_title(title_map[operation] + subtitle, fontsize=11, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([Path(f).name for f in test_files], rotation=45, ha="right")
        ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5))
        ax.grid(True, alpha=0.3, axis="y", linestyle="--")
        ax.set_axisbelow(True)

        plt.tight_layout()
        output_path = self.abs_graph_dir / f"total_throughput_{operation}.svg"
        plt.savefig(output_path, format="svg", bbox_inches="tight")
        plt.close()
        print(f"  Generated: total_throughput_{operation}.svg")

    def generate_all_graphs(self) -> None:
        """Generate all graphs."""
        print("Loading results...")
        results = self.load_results()

        if not results:
            print("No results found")
            return

        print(f"Found {len(results)} test files with results\n")

        operations = ["read", "write", "overall"]

        # ===== ABSOLUTE GRAPHS =====
        print("=" * 60)
        print("Generating ABSOLUTE value graphs...")
        print("=" * 60)

        graph_count = 1
        total_abs_graphs = 11

        print(f"  {graph_count}/{total_abs_graphs}: Compression ratio")
        self.plot_compression_ratio(results)
        graph_count += 1

        print(f"  {graph_count}/{total_abs_graphs}: Memory usage")
        self.plot_memory_usage(results)
        graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_abs_graphs}: Compression throughput ({op})")
            self.plot_compression_throughput(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_abs_graphs}: Decompression throughput ({op})")
            self.plot_decompression_throughput(results, op)
            graph_count += 1

        for op in operations:
            print(f"  {graph_count}/{total_abs_graphs}: Total throughput ({op})")
            self.plot_total_throughput(results, op)
            graph_count += 1

        # ===== RELATIVE GRAPHS =====
        print("\n" + "=" * 60)
        print("Generating RELATIVE value graphs (normalized to Contiguous)...")
        print("=" * 60)

        rel_graph_count = 1
        total_rel_graphs = 11

        # Compression ratio (overall only)
        print(f"  {rel_graph_count}/{total_rel_graphs}: Relative compression ratio")
        self._plot_relative_metric(results, "compression_ratio", "Compression Ratio")
        rel_graph_count += 1

        # Memory usage (overall only)
        print(f"  {rel_graph_count}/{total_rel_graphs}: Relative memory usage")
        self._plot_relative_metric(results, "memory_usage", "Memory Usage")
        rel_graph_count += 1

        # Compression throughput (read, write, overall)
        for op in operations:
            print(f"  {rel_graph_count}/{total_rel_graphs}: Relative compression throughput ({op})")
            self._plot_relative_metric(
                results, "compression_throughput", "Compression Throughput", op
            )
            rel_graph_count += 1

        # Decompression throughput (read, write, overall)
        for op in operations:
            print(
                f"  {rel_graph_count}/{total_rel_graphs}: Relative decompression throughput ({op})"
            )
            self._plot_relative_metric(
                results, "decompression_throughput", "Decompression Throughput", op
            )
            rel_graph_count += 1

        # Total throughput (read, write, overall)
        for op in operations:
            print(f"  {rel_graph_count}/{total_rel_graphs}: Relative total throughput ({op})")
            self._plot_relative_metric(results, "total_throughput", "Total Throughput", op)
            rel_graph_count += 1

        print(f"\nAbsolute graphs saved to: {self.abs_graph_dir}")
        print(f"Relative graphs saved to: {self.rel_graph_dir}")


def main() -> None:
    parser = ArgumentParser(description="Generate LZ4 comparison graphs")
    parser.add_argument(
        "--result", default="./experiment/result", help="Path to intermediate results directory"
    )
    parser.add_argument("--graph", default="./experiment/graph", help="Path to graph directory")

    args = parser.parse_args()

    generator = GraphGenerator(Path(args.result), Path(args.graph))
    generator.generate_all_graphs()


if __name__ == "__main__":
    main()
