#! /bin/bash

source test/literals.sh

set -euxo pipefail

setup() {
	make reinsert
	modprobe brd rd_nr=1 rd_size="$DISK_SIZE_IN_KB" max_part=0
}

run_test() {
	echo -n "not a device" > "$PARAM_MAPPER" && exit 1 || true

	echo -n "$UNDERLYING_DEVICE" > "$PARAM_MAPPER"
	echo -n "$UNDERLYING_DEVICE" > "$PARAM_MAPPER" && exit 1 || true

	cat "$PARAM_MAPPER"
	cat "$PARAM_UNMAPPER"

	echo -n "unmap" > "$PARAM_UNMAPPER"
	echo -n "unmap again" > "$PARAM_UNMAPPER" && exit 1 || true
}

cleanup() {
	exit_code=$?
	make remove
	rmmod brd
	exit $exit_code
}

trap cleanup EXIT

setup
run_test
