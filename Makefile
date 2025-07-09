KERNEL_VERSION := $(shell uname -r)
SOURCE_DIR := /lib/modules/$(KERNEL_VERSION)/build

.PHONY: clean

obj-m := blk_comp.o
blk_comp-y := blk_comp_module.o blk_comp_dev.o underlying_dev.o gendisk_utils.o

all: build

build:
	$(MAKE) -C $(SOURCE_DIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(SOURCE_DIR) M=$(PWD) clean
