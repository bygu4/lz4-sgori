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
Experimental environment for comparing LZ4 compression variations in Linux kernel.
"""

from argparse import ArgumentParser, Namespace
from dataclasses import asdict, dataclass
from json import dump
from os import walk
from pathlib import Path
from shutil import rmtree
from subprocess import CalledProcessError, run
from sys import exit
from tempfile import NamedTemporaryFile
from time import sleep
from typing import Any, Dict, List, Union

from generate_graphs import GraphGenerator


@dataclass
class LZ4Stats:
    """Container for LZ4 I/O statistics."""

    # Read statistics
    stats_r_reqs_total: int = 0
    stats_r_reqs_failed: int = 0
    stats_r_min_vec: int = 0
    stats_r_max_vec: int = 0
    stats_r_vecs: int = 0
    stats_r_segments: int = 0
    stats_r_decomp_size: int = 0
    stats_r_comp_size: int = 0
    stats_r_mem_usage: int = 0
    stats_r_copy_ns: int = 0
    stats_r_comp_ns: int = 0
    stats_r_decomp_ns: int = 0
    stats_r_total_ns: int = 0

    # Write statistics
    stats_w_reqs_total: int = 0
    stats_w_reqs_failed: int = 0
    stats_w_min_vec: int = 0
    stats_w_max_vec: int = 0
    stats_w_vecs: int = 0
    stats_w_segments: int = 0
    stats_w_decomp_size: int = 0
    stats_w_comp_size: int = 0
    stats_w_mem_usage: int = 0
    stats_w_copy_ns: int = 0
    stats_w_comp_ns: int = 0
    stats_w_decomp_ns: int = 0
    stats_w_total_ns: int = 0

    @classmethod
    def from_sysfs(cls, base_path: Path = Path("/sys/module/lz4e_bdev/parameters")) -> "LZ4Stats":
        """Read statistics from sysfs."""
        stats = cls()
        for field in cls.__dataclass_fields__:
            param_path = base_path / field
            if param_path.exists():
                with open(param_path) as f:
                    value = f.read().strip()
                    try:
                        setattr(stats, field, int(value))
                    except ValueError:
                        pass
        return stats

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class LZ4Experiment:
    """Main experiment class for LZ4 compression testing."""

    COMPRESSION_TYPES = ["cont", "vect", "strm", "extd"]
    IGNORE_FILES = [".gitkeep"]

    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.bs_bytes = self._parse_bs(args.bs)
        self.proxy_dev = Path("/dev/lz4e0")
        self.under_dev = args.under_dev
        self.tmp_dir = Path("./experiment/tmp")

        # Create result and graph directories
        self.result_dir = Path(args.result)
        self.graph_dir = Path(args.graph)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.graph_dir.mkdir(parents=True, exist_ok=True)

        # Setup dataset
        self.dataset_dir = Path(args.dataset)
        if not self.dataset_dir.exists():
            raise FileNotFoundError(f"Dataset directory not found: {self.dataset_dir}")

        # Setup perf directory if specified
        self.perf_dir = None
        if args.perf_dir:
            self.perf_dir = Path(args.perf_dir)
            self.perf_dir.mkdir(parents=True, exist_ok=True)
            print(f"Perf profiling data will be saved to: {self.perf_dir}")

    def _parse_bs(self, bs_str: str) -> int:
        """Parse block size from IEC format to bytes."""
        try:
            # Use numfmt utility for conversion
            result = run(
                ["numfmt", "--from=iec", bs_str],
                capture_output=True,
                text=True,
                check=True,
            )
            return int(result.stdout.strip())
        except CalledProcessError:
            # Fallback to manual parsing
            multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
            if bs_str[-1] in multipliers:
                return int(bs_str[:-1]) * multipliers[bs_str[-1]]
            return int(bs_str)

    def _setup_under_device(self) -> Union[Any, str]:
        """Setup underlying device if not provided."""
        if self.under_dev == "None" or self.under_dev is None:
            dev_size_kb = self.args.dev_size
            print(f"Creating RAM device of size {dev_size_kb} KB...")
            run(
                ["modprobe", "brd", "rd_nr=1", f"rd_size={dev_size_kb}", "max_part=0"],
                check=True,
            )
            self.under_dev = "/dev/ram0"
            sleep(0.001)
        return self.under_dev

    def _load_modules(self) -> None:
        """Load required kernel modules."""
        print("Loading lz4e_bdev module...")
        run(["make", "reinsert"], cwd=".", check=True)
        sleep(0.001)

    def _unload_modules(self) -> None:
        """Unload kernel modules."""
        print("Unloading modules...")
        run(["make", "remove"], cwd=".", check=True)
        sleep(0.001)

    def _create_proxy_device(self, under_dev: str) -> None:
        """Create proxy device over underlying device."""
        print(f"Creating proxy device over {under_dev}...")
        sysfs_param = Path("/sys/module/lz4e_bdev/parameters/mapper")
        with open(sysfs_param, "w") as f:
            f.write(under_dev)
        sleep(0.001)

        if not self.proxy_dev.exists():
            raise RuntimeError(f"Proxy device {self.proxy_dev} not created")

    def _remove_proxy_device(self) -> None:
        """Remove proxy device."""
        print("Removing proxy device...")
        sysfs_param = Path("/sys/module/lz4e_bdev/parameters/unmapper")
        with open(sysfs_param, "w") as f:
            f.write("lz4e0")
        sleep(0.001)

    def _set_compression_type(self, comp_type: str) -> None:
        """Set compression type."""
        sysfs_param = Path("/sys/module/lz4e_bdev/parameters/comp_type")
        with open(sysfs_param, "w") as f:
            f.write(comp_type)
        sleep(0.001)

    def _set_acceleration(self, accel: int) -> None:
        """Set acceleration factor."""
        sysfs_param = Path("/sys/module/lz4e_bdev/parameters/acceleration")
        with open(sysfs_param, "w") as f:
            f.write(str(accel))
        sleep(0.001)

    def _reset_stats(self) -> None:
        """Reset I/O statistics."""
        sysfs_param = Path("/sys/module/lz4e_bdev/parameters/stats_reset")
        with open(sysfs_param, "w") as f:
            f.write("1")
        sleep(0.001)

    def _get_count(self, file_size: int) -> int:
        """Calculate count parameter for dd."""
        return file_size // self.bs_bytes

    def _run_dd_write(self, input_file: Path, count: int) -> bool:
        """Run dd write operation."""
        cmd = [
            "dd",
            f"if={input_file}",
            f"of={self.proxy_dev}",
            f"bs={self.args.bs}",
            f"count={count}",
            "iflag=fullblock",
            "oflag=direct",
            "status=none",
        ]
        result = run(cmd, capture_output=True)
        return result.returncode == 0

    def _run_dd_read(self, output_file: Path, count: int) -> bool:
        """Run dd read operation."""
        cmd = [
            "dd",
            f"if={self.proxy_dev}",
            f"of={output_file}",
            f"bs={self.args.bs}",
            f"count={count}",
            "iflag=direct,fullblock",
            "status=none",
        ]
        result = run(cmd, capture_output=True)
        return result.returncode == 0

    def _run_perf_record(self, cmd: List[str], perf_output_path: Path) -> bool:
        """Run perf record for a command and save to specified path."""
        perf_events = [
            "cycles",
            "instructions",
            "branches",
            "branch-misses",
            "cache-references",
            "cache-misses",
            "L1-dcache-load-misses",
            "LLC-load-misses",
            "page-faults",
        ]

        perf_cmd = [
            "perf",
            "record",
            "-o",
            str(perf_output_path),
            "-e",
            ",".join(perf_events),
            "-a",
            "-F",
            "99",
            "--",
        ]
        perf_cmd.extend(cmd)

        result = run(perf_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"      Warning: perf record failed with return code {result.returncode}")
            if result.stderr:
                print(f"      stderr: {result.stderr[:200]}")
            return False

        return True

    def _run_with_perf(self, operation_name: str, cmd: List[str], perf_subdir: Path) -> bool:
        """Run a command with perf profiling if perf_dir is enabled."""
        if self.perf_dir is None:
            # No perf profiling, just run the command directly
            result = run(cmd, capture_output=True)
            return result.returncode == 0

        # Run with perf profiling
        perf_file = perf_subdir / f"{operation_name}.data"
        return self._run_perf_record(cmd, perf_file)

    def _run_dd_write_with_perf(self, input_file: Path, count: int, perf_subdir: Path) -> bool:
        """Run dd write operation with optional perf profiling."""
        cmd = [
            "dd",
            f"if={input_file}",
            f"of={self.proxy_dev}",
            f"bs={self.args.bs}",
            f"count={count}",
            "iflag=fullblock",
            "oflag=direct",
            "status=none",
        ]
        return self._run_with_perf("write", cmd, perf_subdir)

    def _run_dd_read_with_perf(self, output_file: Path, count: int, perf_subdir: Path) -> bool:
        """Run dd read operation with optional perf profiling."""
        cmd = [
            "dd",
            f"if={self.proxy_dev}",
            f"of={output_file}",
            f"bs={self.args.bs}",
            f"count={count}",
            "iflag=direct,fullblock",
            "status=none",
        ]
        return self._run_with_perf("read", cmd, perf_subdir)

    def _verify_integrity(self, original: Path, test: Path, size: int) -> bool:
        """Verify integrity by comparing first N bytes."""
        with open(original, "rb") as f1, open(test, "rb") as f2:
            return f1.read(size) == f2.read(size)

    def _get_test_files(self) -> List[Path]:
        """Recursively find all test files in dataset directory."""
        test_files = []
        for root, _, files in walk(self.dataset_dir):
            for file in files:
                if file not in self.IGNORE_FILES:
                    test_files.append(Path(root) / file)
        return test_files

    def _save_intermediate_results(
        self, test_file: Path, comp_type: str, run_num: int, stats: LZ4Stats
    ) -> None:
        """Save intermediate results to JSON file."""
        # Create directory structure
        comp_dir = self.result_dir / comp_type
        comp_dir.mkdir(exist_ok=True)

        # Create filename with test file name and run number
        safe_filename = test_file.name.replace("/", "_")
        result_file = comp_dir / f"{safe_filename}_run{run_num}.json"

        # Prepare result data
        result_data = {
            "test_file": str(test_file),
            "compression_type": comp_type,
            "run_number": run_num,
            "block_size": self.args.bs,
            "acceleration": self.args.acceleration,
            "statistics": stats.to_dict(),
        }

        # Add perf directory info if enabled
        if self.perf_dir:
            result_data["perf_data_dir"] = str(
                self.perf_dir / comp_type / safe_filename / f"run{run_num}"
            )

        # Save to JSON
        with open(result_file, "w") as f:
            dump(result_data, f, indent=2)

        print(f"  Saved intermediate results to {result_file}")

    def _cleanup_tmp_dir(self) -> None:
        """Remove temporary directory and all its contents."""
        if self.tmp_dir.exists():
            rmtree(self.tmp_dir, ignore_errors=True)

    def run_single_test(self, test_file: Path, comp_type: str, run_num: int) -> None:
        """Run a single test for a specific file and compression type."""
        file_size = test_file.stat().st_size
        count = self._get_count(file_size)

        # Create perf subdirectory if needed
        perf_subdir = None
        if self.perf_dir:
            perf_subdir = self.perf_dir / comp_type / test_file.name / f"run{run_num}"
            perf_subdir.mkdir(parents=True, exist_ok=True)
            print(f"    Perf data will be saved to: {perf_subdir}")

        # Create temporary output file
        with NamedTemporaryFile(dir=self.tmp_dir, delete=False) as tmp:
            tmp_output = Path(tmp.name)

        try:
            # Set compression parameters
            self._set_compression_type(comp_type)
            self._set_acceleration(self.args.acceleration)
            self._reset_stats()

            # Write test file to proxy device
            print(f"    Writing {test_file.name} to proxy device...")
            if (
                not self._run_dd_write_with_perf(test_file, count, perf_subdir)
                if perf_subdir
                else self._run_dd_write(test_file, count)
            ):
                raise RuntimeError(f"DD write failed for {test_file}")

            # Read from proxy device
            print(f"    Reading from proxy device to {tmp_output.name}...")
            if (
                not self._run_dd_read_with_perf(tmp_output, count, perf_subdir)
                if perf_subdir
                else self._run_dd_read(tmp_output, count)
            ):
                raise RuntimeError(f"DD read failed for {test_file}")

            # Verify integrity
            if not self._verify_integrity(test_file, tmp_output, count * self.bs_bytes):
                raise RuntimeError(f"Integrity check failed for {test_file}")

            # Collect statistics
            stats = LZ4Stats.from_sysfs()

            # Save intermediate results
            self._save_intermediate_results(test_file, comp_type, run_num, stats)

            print("    Test completed successfully")

        except Exception as e:
            print(f"    ERROR: {e}")
            # Still try to save any available statistics
            try:
                stats = LZ4Stats.from_sysfs()
                self._save_intermediate_results(test_file, comp_type, run_num, stats)
            except Exception:
                pass
            raise

        finally:
            # Cleanup
            if tmp_output.exists():
                tmp_output.unlink()
            self._reset_stats()

    def _generate_graphs(self) -> None:
        """Generate graphs using imported GraphGenerator."""
        print("\n" + "=" * 60)
        print("Generating performance graphs...")
        print("=" * 60)

        try:
            # Create graph generator instance
            generator = GraphGenerator(self.result_dir, self.graph_dir)

            # Generate all graphs
            generator.generate_all_graphs()

            print("\nGraphs generated successfully!")
            print(f"Graphs saved to: {self.graph_dir}")

        except Exception as e:
            print(f"\nError generating graphs: {e}")
            from traceback import print_exc

            print_exc()

    def run_experiment(self) -> None:
        """Run the complete experiment."""
        experiment_success = False

        try:
            # Create temporary directory for test files
            self.tmp_dir.mkdir(exist_ok=True)

            # Setup environment
            under_dev = self._setup_under_device()
            self._load_modules()
            self._create_proxy_device(under_dev)

            # Get test files
            test_files = self._get_test_files()
            total_files = len(test_files)
            total_runs = total_files * len(self.COMPRESSION_TYPES) * self.args.runs

            # Print experiment information
            print("\n" + "=" * 80)
            print("LZ4 COMPRESSION EXPERIMENT")
            print("=" * 80)
            print(f"Dataset directory:    {self.dataset_dir}")
            print(f"Test files found:     {total_files}")
            print(f"Compression types:    {', '.join(self.COMPRESSION_TYPES)}")
            print(f"Runs per type:        {self.args.runs}")
            print(f"Total operations:     {total_runs}")
            print(f"Block size:           {self.args.bs} ({self.bs_bytes:,} bytes)")
            print(f"Acceleration factor:  {self.args.acceleration}")
            print(f"Underlying device:    {under_dev}")
            print(f"Proxy device:         {self.proxy_dev}")
            print(f"Result directory:     {self.result_dir}")
            print(f"Graph directory:      {self.graph_dir}")
            if self.perf_dir:
                print(f"Perf directory:       {self.perf_dir}")
            else:
                print("Perf profiling:       Disabled")
            print("=" * 80)

            # Save kallsyms to perf directory for later symbol resolution
            if self.perf_dir:
                kallsyms_file = self.perf_dir / "kallsyms.txt"
                try:
                    with open("/proc/kallsyms") as src, open(kallsyms_file, "w") as dst:
                        dst.write(src.read())
                    print(f"      Saved kallsyms to: {kallsyms_file}")
                except Exception as e:
                    print(f"      Warning: Could not save kallsyms: {e}")

            # Run experiments
            for test_idx, test_file in enumerate(test_files, 1):
                file_size = test_file.stat().st_size
                block_count = self._get_count(file_size)
                io_size = block_count * self.bs_bytes

                print(f"\n{'=' * 60}")
                print(f"Test file {test_idx}/{total_files}: {test_file.name}")
                print(f"  Original size:  {file_size:,} bytes")
                print(f"  Block count:    {block_count}")
                print(f"  I/O size:       {io_size:,} bytes ({io_size / (1024 * 1024):.2f} MB)")
                print(f"{'=' * 60}")

                for comp_type in self.COMPRESSION_TYPES:
                    print(f"\n  Compression type: {comp_type}")

                    for run_num in range(1, self.args.runs + 1):
                        print(f"\n    Run {run_num}/{self.args.runs}")
                        self.run_single_test(test_file, comp_type, run_num)

            experiment_success = True
            print("\n" + "=" * 60)
            print("Experiment completed successfully!")
            print("=" * 60)

        except KeyboardInterrupt:
            print("\n\n" + "!" * 60)
            print("Experiment interrupted by user")
            print("!" * 60)
            experiment_success = False
        except Exception as e:
            print(f"\n{'!' * 60}")
            print(f"Experiment failed: {e}")
            print(f"{'!' * 60}")
            import traceback

            traceback.print_exc()
            experiment_success = False

        finally:
            # Generate graphs if requested
            if not self.args.no_graph and experiment_success:
                self._generate_graphs()
            elif not self.args.no_graph:
                print("\nGraph generation skipped due to experiment failure")
            else:
                print("\nGraph generation skipped (--no-graph)")

            # Cleanup: remove proxy device and unload modules
            print("\nCleaning up kernel modules...")
            try:
                self._remove_proxy_device()
            except Exception as e:
                print(f"Warning: Could not remove proxy device: {e}")

            try:
                self._unload_modules()
            except Exception as e:
                print(f"Warning: Could not unload modules: {e}")

            # Always cleanup temporary directory on exit
            self._cleanup_tmp_dir()

        if not experiment_success:
            exit(1)


def main() -> None:
    parser = ArgumentParser(description="LZ4 Compression Experiment")
    parser.add_argument("--bs", default="1M", help="Block size (IEC format)")
    parser.add_argument(
        "--dataset", default="./experiment/dataset", help="Path to dataset directory"
    )
    parser.add_argument(
        "--result",
        default="./experiment/result",
        help="Path to intermediate results directory",
    )
    parser.add_argument("--graph", default="./experiment/graph", help="Path to graph directory")
    parser.add_argument(
        "--under-dev", default="None", help="Underlying device (or None for RAM device)"
    )
    parser.add_argument(
        "--dev-size",
        default=1024 * 1024,
        type=int,
        help="Device size in KB (for RAM device)",
    )
    parser.add_argument("--runs", default=5, type=int, help="Number of test runs")
    parser.add_argument("--acceleration", default=1, type=int, help="LZ4 acceleration factor")
    parser.add_argument("--no-graph", action="store_true", help="Skip graph generation")
    parser.add_argument(
        "--perf-dir",
        default=None,
        help="Directory to save perf profiling data)",
    )

    args = parser.parse_args()

    experiment = LZ4Experiment(args)
    experiment.run_experiment()


if __name__ == "__main__":
    main()
