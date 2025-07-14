KERNEL_VERSION := $(shell uname -r)
KERNEL_SOURCES_DIR := /lib/modules/$(KERNEL_VERSION)/build

INCLUDE_DIR := $(PWD)/include
OUTPUT_DIR := $(PWD)/build
COMPILE_COMMANDS := $(PWD)/compile_commands.json

.PHONY: clean

all: build

build:
	export C_INCLUDE_PATH=$(INCLUDE_DIR)
	$(MAKE) -I $(INCLUDE_DIR) -C $(KERNEL_SOURCES_DIR) M=$(PWD) MO=$(OUTPUT_DIR) modules
clean:
	rm -rf $(OUTPUT_DIR) $(COMPILE_COMMANDS)
