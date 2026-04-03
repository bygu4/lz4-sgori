#! /bin/bash

source test/literals.sh

set -euxo pipefail

accelerations=("-32" "0" "4" "90" "455" "8200" "33000" "232323")

setup() {
	make reinsert
	modprobe brd rd_nr=1 rd_size="$DISK_SIZE_IN_KB" max_part=0
	echo -n "$UNDERLYING_DEVICE" > "$PARAM_MAPPER"
	mkdir "$TEMP_DIR"
}

compare_files() {
	file1=$1
	file2=$2
	bytes=$3

	cmp --verbose --bytes="$bytes" "$file1" "$file2"
}

run_test() {
	test_file=$1
	bs=$2
	bytes=$(stat --print="%s" "$test_file")
	count=$(echo "$bytes / $(numfmt --from=iec "$bs") + 1" | bc)

	touch "$TEMP_FILE"

	dd if="$test_file" of="$TEST_DEVICE" bs="$bs" count="$count" oflag=direct
	dd if="$TEST_DEVICE" of="$TEMP_FILE" bs="$bs" count="$count" iflag=direct
	compare_files "$test_file" "$TEMP_FILE" "$bytes"

	rm "$TEMP_FILE"
}

run_all_tests() {
	for comp_type in "${COMP_TYPES[@]}"; do
		echo -n "$comp_type" > "$PARAM_COMP_TYPE"
		cat "$PARAM_COMP_TYPE"

		for acceleration in "${accelerations[@]}"; do
			echo -n "$acceleration" > "$PARAM_ACCELERATION"
			cat "$PARAM_ACCELERATION"

			run_test "$TEST_FILE_ACCELERATION" "64k"
		done
	done
}

cleanup() {
	exit_code=$?
	rm -rf "$TEMP_DIR"
	make remove
	rmmod brd
	exit $exit_code
}

trap cleanup EXIT

setup
run_all_tests
