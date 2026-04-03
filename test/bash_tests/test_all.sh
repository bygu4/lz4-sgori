#! /bin/bash

set -euxo pipefail

./test/bash_tests/test_mapper.sh
./test/bash_tests/test_proxy.sh
./test/bash_tests/test_acceleration.sh
./test/bash_tests/test_stats.sh
