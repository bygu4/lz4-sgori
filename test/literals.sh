export BDEV_NAME=lz4e_bdev
export BDEV_PARAMETERS=/sys/module/"$BDEV_NAME"/parameters

export PARAM_MAPPER="$BDEV_PARAMETERS"/mapper
export PARAM_UNMAPPER="$BDEV_PARAMETERS"/unmapper

export COMP_TYPES=("cont" "vect" "strm" "extd")

export PARAM_COMP_TYPE="$BDEV_PARAMETERS"/comp_type
export PARAM_ACCELERATION="$BDEV_PARAMETERS"/acceleration

export PARAM_STATS_RESET="$BDEV_PARAMETERS"/stats_reset

export PARAM_STATS_R_REQS_TOTAL="$BDEV_PARAMETERS"/stats_r_reqs_total
export PARAM_STATS_R_REQS_FAILED="$BDEV_PARAMETERS"/stats_r_reqs_failed
export PARAM_STATS_R_SEGMENTS="$BDEV_PARAMETERS"/stats_r_segments
export PARAM_STATS_R_DECOMP_SIZE="$BDEV_PARAMETERS"/stats_r_decomp_size
export PARAM_STATS_R_COMP_SIZE="$BDEV_PARAMETERS"/stats_r_comp_size
export PARAM_STATS_R_COPY_NS="$BDEV_PARAMETERS"/stats_r_copy_ns
export PARAM_STATS_R_COMP_NS="$BDEV_PARAMETERS"/stats_r_comp_ns
export PARAM_STATS_R_DECOMP_NS="$BDEV_PARAMETERS"/stats_r_decomp_ns
export PARAM_STATS_R_TOTAL_NS="$BDEV_PARAMETERS"/stats_r_total_ns

export PARAM_STATS_W_REQS_TOTAL="$BDEV_PARAMETERS"/stats_w_reqs_total
export PARAM_STATS_W_REQS_FAILED="$BDEV_PARAMETERS"/stats_w_reqs_failed
export PARAM_STATS_W_SEGMENTS="$BDEV_PARAMETERS"/stats_w_segments
export PARAM_STATS_W_DECOMP_SIZE="$BDEV_PARAMETERS"/stats_w_decomp_size
export PARAM_STATS_W_COMP_SIZE="$BDEV_PARAMETERS"/stats_w_comp_size
export PARAM_STATS_W_COPY_NS="$BDEV_PARAMETERS"/stats_w_copy_ns
export PARAM_STATS_W_COMP_NS="$BDEV_PARAMETERS"/stats_w_comp_ns
export PARAM_STATS_W_DECOMP_NS="$BDEV_PARAMETERS"/stats_w_decomp_ns
export PARAM_STATS_W_TOTAL_NS="$BDEV_PARAMETERS"/stats_w_total_ns

export UNDERLYING_DEVICE=/dev/ram0
export TEST_DEVICE=/dev/lz4e0
export DISK_SIZE_IN_KB=307200

export TEST_FILES_DIR=test/test_files
export FIO_TESTS_DIR=test/fio_tests
export TEST_FILE_ACCELERATION="$TEST_FILES_DIR"/03.txt

export TEMP_DIR=test/tmp
export TEMP_FILE="$TEMP_DIR"/output

export DEVICE_ZERO=/dev/zero
export DEVICE_RANDOM=/dev/random
