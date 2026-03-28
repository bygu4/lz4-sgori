#! /bin/bash

source test/literals.sh

set -euo pipefail

# to convert bytes/ns to mb/s
MBPS_FACTOR=$(echo "scale=6; 1000000000 / (1024 * 1024)" | bc)

PRINT_READ=0
PRINT_WRITE=0
PRINT_ALL=0

add() {
	x=$1
	y=$2

	echo "$x + $y" | bc
}

sub() {
	x=$1
	y=$2

	echo "$x - $y" | bc
}

mul() {
	x=$1
	y=$2

	echo "$x * $y" | bc
}

div() {
	x=$1
	y=$2
	scale=$3

	if [ "$y" -ne 0 ]; then
		echo "scale=$scale; $x / $y" | bc
	else
		echo 0
	fi
}

while [[ $# -gt 0 ]]; do
	case $1 in
	-r|--read)
		PRINT_READ=1
		shift
		;;
	-w|--write)
		PRINT_WRITE=1
		shift
		;;
	-a|--all)
		PRINT_ALL=1
		shift
		;;
	-rw|-wr)
		PRINT_READ=1
		PRINT_WRITE=1
		shift
		;;
	-ra|-ar)
		PRINT_READ=1
		PRINT_ALL=1
		shift
		;;
	-wa|-aw)
		PRINT_WRITE=1
		PRINT_ALL=1
		shift
		;;
	-rwa|-raw|-wra|-war|-arw|-awr)
		PRINT_READ=1
		PRINT_WRITE=1
		PRINT_ALL=1
		shift
		;;
	*)
		echo "Unknown option argument: $1"
		exit 1
		;;
	esac
done

if [ "$PRINT_READ" -eq 0 ] \
	&& [ "$PRINT_WRITE" -eq 0 ] \
	&& [ "$PRINT_ALL" -eq 0 ]; then
	PRINT_ALL=1
fi

# ---------------- get stats from sysfs ----------------

r_reqs_total=$(cat "$PARAM_STATS_R_REQS_TOTAL")
r_reqs_failed=$(cat "$PARAM_STATS_R_REQS_FAILED")
r_segments=$(cat "$PARAM_STATS_R_SEGMENTS")
r_decomp_size=$(cat "$PARAM_STATS_R_DECOMP_SIZE")
r_comp_size=$(cat "$PARAM_STATS_R_COMP_SIZE")
r_copy_ns=$(cat "$PARAM_STATS_R_COPY_NS")
r_comp_ns=$(cat "$PARAM_STATS_R_COMP_NS")
r_decomp_ns=$(cat "$PARAM_STATS_R_DECOMP_NS")
r_total_ns=$(cat "$PARAM_STATS_R_TOTAL_NS")

w_reqs_total=$(cat "$PARAM_STATS_W_REQS_TOTAL")
w_reqs_failed=$(cat "$PARAM_STATS_W_REQS_FAILED")
w_segments=$(cat "$PARAM_STATS_W_SEGMENTS")
w_decomp_size=$(cat "$PARAM_STATS_W_DECOMP_SIZE")
w_comp_size=$(cat "$PARAM_STATS_W_COMP_SIZE")
w_copy_ns=$(cat "$PARAM_STATS_W_COPY_NS")
w_comp_ns=$(cat "$PARAM_STATS_W_COMP_NS")
w_decomp_ns=$(cat "$PARAM_STATS_W_DECOMP_NS")
w_total_ns=$(cat "$PARAM_STATS_W_TOTAL_NS")

# ---------------- calculate overall stats ----------------

all_reqs_total=$(add "$r_reqs_total" "$w_reqs_total")
all_reqs_failed=$(add "$r_reqs_failed" "$w_reqs_failed")
all_segments=$(add "$r_segments" "$w_segments")
all_decomp_size=$(add "$r_decomp_size" "$w_decomp_size")
all_comp_size=$(add "$r_comp_size" "$w_comp_size")
all_copy_ns=$(add "$r_copy_ns" "$w_copy_ns")
all_comp_ns=$(add "$r_comp_ns" "$w_comp_ns")
all_decomp_ns=$(add "$r_decomp_ns" "$w_decomp_ns")
all_total_ns=$(add "$r_total_ns" "$w_total_ns")

# ---------------- calculate more complex stats ----------------

r_reqs_success=$(sub "$r_reqs_total" "$r_reqs_failed")
r_avg_block=$(div "$r_decomp_size" "$r_reqs_success" "3")
r_avg_segment=$(div "$r_decomp_size" "$r_segments" "3")
r_comp_ratio=$(div "$r_decomp_size" "$r_comp_size" "9")
r_copy_mbps=$(mul "$MBPS_FACTOR" "$(div "$r_decomp_size" "$r_copy_ns" "6")")
r_comp_mbps=$(mul "$MBPS_FACTOR" "$(div "$r_decomp_size" "$r_comp_ns" "6")")
r_decomp_mbps=$(mul "$MBPS_FACTOR" "$(div "$r_comp_size" "$r_decomp_ns" "6")")
r_total_mbps=$(mul "$MBPS_FACTOR" "$(div "$r_decomp_size" "$r_total_ns" "6")")

w_reqs_success=$(sub "$w_reqs_total" "$w_reqs_failed")
w_avg_block=$(div "$w_decomp_size" "$w_reqs_success" "3")
w_avg_segment=$(div "$w_decomp_size" "$w_segments" "3")
w_comp_ratio=$(div "$w_decomp_size" "$w_comp_size" "9")
w_copy_mbps=$(mul "$MBPS_FACTOR" "$(div "$w_decomp_size" "$w_copy_ns" "6")")
w_comp_mbps=$(mul "$MBPS_FACTOR" "$(div "$w_decomp_size" "$w_comp_ns" "6")")
w_decomp_mbps=$(mul "$MBPS_FACTOR" "$(div "$w_comp_size" "$w_decomp_ns" "6")")
w_total_mbps=$(mul "$MBPS_FACTOR" "$(div "$w_decomp_size" "$w_total_ns" "6")")

all_reqs_success=$(sub "$all_reqs_total" "$all_reqs_failed")
all_avg_block=$(div "$all_decomp_size" "$all_reqs_success" "3")
all_avg_segment=$(div "$all_decomp_size" "$all_segments" "3")
all_comp_ratio=$(div "$all_decomp_size" "$all_comp_size" "9")
all_copy_mbps=$(mul "$MBPS_FACTOR" "$(div "$all_decomp_size" "$all_copy_ns" "6")")
all_comp_mbps=$(mul "$MBPS_FACTOR" "$(div "$all_decomp_size" "$all_comp_ns" "6")")
all_decomp_mbps=$(mul "$MBPS_FACTOR" "$(div "$all_comp_size" "$all_decomp_ns" "6")")
all_total_mbps=$(mul "$MBPS_FACTOR" "$(div "$all_decomp_size" "$all_total_ns" "6")")

# ---------------- print to stdout ----------------

output=""

if [ "$PRINT_READ" -eq 1 ]; then
	output+="read:\n"
	output+="\treqs_total: $r_reqs_total\n"
	output+="\treqs_failed: $r_reqs_failed\n\n"
	output+="\tdecomp_size: $r_decomp_size\n"
	output+="\tcomp_size: $r_comp_size\n"
	output+="\tcomp_ratio: $r_comp_ratio\n\n"
	output+="\tsegments: $r_segments\n"
	output+="\tavg_block: $r_avg_block\n"
	output+="\tavg_segment: $r_avg_segment\n\n"
	output+="\tcopy_mbps: $r_copy_mbps\n"
	output+="\tcomp_mbps: $r_comp_mbps\n"
	output+="\tdecomp_mbps: $r_decomp_mbps\n"
	output+="\ttotal_mbps: $r_total_mbps\n"
fi

if [ "$PRINT_WRITE" -eq 1 ]; then
	output+="write:\n"
	output+="\treqs_total: $w_reqs_total\n"
	output+="\treqs_failed: $w_reqs_failed\n\n"
	output+="\tdecomp_size: $w_decomp_size\n"
	output+="\tcomp_size: $w_comp_size\n"
	output+="\tcomp_ratio: $w_comp_ratio\n\n"
	output+="\tsegments: $w_segments\n"
	output+="\tavg_block: $w_avg_block\n"
	output+="\tavg_segment: $w_avg_segment\n\n"
	output+="\tcopy_mbps: $w_copy_mbps\n"
	output+="\tcomp_mbps: $w_comp_mbps\n"
	output+="\tdecomp_mbps: $w_decomp_mbps\n"
	output+="\ttotal_mbps: $w_total_mbps\n"
fi

if [ "$PRINT_ALL" -eq 1 ]; then
	output+="all:\n"
	output+="\treqs_total: $all_reqs_total\n"
	output+="\treqs_failed: $all_reqs_failed\n\n"
	output+="\tdecomp_size: $all_decomp_size\n"
	output+="\tcomp_size: $all_comp_size\n"
	output+="\tcomp_ratio: $all_comp_ratio\n\n"
	output+="\tsegments: $all_segments\n"
	output+="\tavg_block: $all_avg_block\n"
	output+="\tavg_segment: $all_avg_segment\n\n"
	output+="\tcopy_mbps: $all_copy_mbps\n"
	output+="\tcomp_mbps: $all_comp_mbps\n"
	output+="\tdecomp_mbps: $all_decomp_mbps\n"
	output+="\ttotal_mbps: $all_total_mbps\n"
fi

echo -e "$output"
