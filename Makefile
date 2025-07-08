KERNEL_VERSION := $(shell uname -r)
SOURCE_DIR := /lib/modules/$(KERNEL_VERSION)/build

all: build

build:
	$(MAKE) -C $(SOURCE_DIR) M=$(PWD) modules
clean:
	$(MAKE) -C $(SOURCE_DIR) M=$(PWD) clean
