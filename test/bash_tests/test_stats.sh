#! /bin/bash

source test/literals.sh

set -euxo pipefail

setup() {
	make reinsert
	modprobe brd rd_nr=1 rd_size="$DISK_SIZE_IN_KB" max_part=0
	echo -n "$UNDERLYING_DEVICE" > "$PARAM_MAPPER"
}

make_requests() {
	dd if="$DEVICE_RANDOM" of="$TEST_DEVICE" bs=256k count=5 oflag=direct
	dd if="$TEST_DEVICE" of="$DEVICE_ZERO" bs=512 count=40 iflag=direct
	dd if="$DEVICE_RANDOM" of="$TEST_DEVICE" bs=4M count=1 oflag=direct
	dd if="$TEST_DEVICE" of="$DEVICE_ZERO" bs=8k count=14 iflag=direct
}

reset_stats() {
	echo -n "reset" > "$PARAM_STATS_RESET"
}

get_stats() {
	cat "$PARAM_STATS_R_REQS_TOTAL"
	cat "$PARAM_STATS_R_REQS_FAILED"
	cat "$PARAM_STATS_R_MIN_VEC"
	cat "$PARAM_STATS_R_MAX_VEC"
	cat "$PARAM_STATS_R_VECS"
	cat "$PARAM_STATS_R_SEGMENTS"
	cat "$PARAM_STATS_R_DECOMP_SIZE"
	cat "$PARAM_STATS_R_COMP_SIZE"
	cat "$PARAM_STATS_R_MEM_USAGE"
	cat "$PARAM_STATS_R_COPY_NS"
	cat "$PARAM_STATS_R_COMP_NS"
	cat "$PARAM_STATS_R_DECOMP_NS"
	cat "$PARAM_STATS_R_TOTAL_NS"

	cat "$PARAM_STATS_W_REQS_TOTAL"
	cat "$PARAM_STATS_W_REQS_FAILED"
	cat "$PARAM_STATS_W_MIN_VEC"
	cat "$PARAM_STATS_W_MAX_VEC"
	cat "$PARAM_STATS_W_VECS"
	cat "$PARAM_STATS_W_SEGMENTS"
	cat "$PARAM_STATS_W_DECOMP_SIZE"
	cat "$PARAM_STATS_W_COMP_SIZE"
	cat "$PARAM_STATS_W_MEM_USAGE"
	cat "$PARAM_STATS_W_COPY_NS"
	cat "$PARAM_STATS_W_COMP_NS"
	cat "$PARAM_STATS_W_DECOMP_NS"
	cat "$PARAM_STATS_W_TOTAL_NS"

	make stats-pprint ARGS="-rwa"
}

run_test() {
	make_requests
	get_stats
	reset_stats
	get_stats
}

run_all_tests() {
	for comp_type in "${COMP_TYPES[@]}"; do
		echo -n "$comp_type" > "$PARAM_COMP_TYPE"
		cat "$PARAM_COMP_TYPE"

		run_test
	done
}

cleanup() {
	exit_code=$?
	make remove
	rmmod brd
	exit $exit_code
}

trap cleanup EXIT

setup
run_all_tests
