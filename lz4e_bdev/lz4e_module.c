// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#include <linux/blkdev.h>
#include <linux/gfp_types.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/moduleparam.h>
#include <linux/stat.h>
#include <linux/stddef.h>
#include <linux/string.h>
#include <linux/sysfs.h>

#include "include/lz4e_module.h"

#include "include/lz4e_chunk.h"
#include "include/lz4e_dev.h"
#include "include/lz4e_static.h"
#include "include/lz4e_stats.h"

static struct lz4e_module lzmod = {};

// Callbacks can have unused parameters
// NOLINTBEGIN(misc-unused-parameters)

/* --------------------------- callback helpers --------------------------- */

/* run setter callback if device exists */
static inline int
lz4e_cb_w_if_dev(int (*func)(const char *arg, const struct kernel_param *kpar),
		 const char *arg, const struct kernel_param *kpar)
{
	if (!lzmod.lzdev) {
		LZ4E_PR_ERR("no device found");
		return -ENODEV;
	}

	return func(arg, kpar);
}

/* run setter callback if no device exists */
static inline int lz4e_cb_w_if_no_dev(
	int (*func)(const char *arg, const struct kernel_param *kpar),
	const char *arg, const struct kernel_param *kpar)
{
	if (lzmod.lzdev) {
		LZ4E_PR_ERR("device exists");
		return -EBUSY;
	}

	return func(arg, kpar);
}

/* run getter callback if device exists */
static inline int lz4e_cb_r_if_dev(int (*func)(char *buf,
					       const struct kernel_param *kpar),
				   char *buf, const struct kernel_param *kpar)
{
	if (!lzmod.lzdev) {
		LZ4E_PR_ERR("no device found");
		return -ENODEV;
	}

	return func(buf, kpar);
}

/* ------------------------- disk mapper/unmapper ------------------------- */

static inline int lz4e_create_disk(const char *arg,
				   const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev;
	int ret;

	lzdev = lz4e_dev_alloc(GFP_KERNEL);
	if (!lzdev) {
		LZ4E_PR_ERR("failed to allocate block device");
		return -ENOMEM;
	}

	ret = lz4e_dev_init(lzdev, arg, lzmod.major, LZ4E_FIRST_MINOR);
	if (ret) {
		LZ4E_PR_ERR("failed to initialize block device");
		goto free_device;
	}

	lzmod.lzdev = lzdev;

	LZ4E_PR_INFO("device mapped successfully");
	return 0;

free_device:
	lz4e_dev_free(lzdev);
	return ret;
}

static inline int lz4e_delete_disk(const char *arg,
				   const struct kernel_param *kpar)
{
	lz4e_dev_free(lzmod.lzdev);
	lzmod.lzdev = NULL;

	LZ4E_PR_INFO("device unmapped successfully");
	return 0;
}

static inline int lz4e_get_disk_info(char *buf, const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev = lzmod.lzdev;
	int ret;

	char *disk_name = lzdev->disk->disk_name;
	char *under_disk_name = lzdev->under_dev->bdev->bd_disk->disk_name;

	ret = sysfs_emit(buf, "%s: proxy over %s\n", disk_name,
			 under_disk_name);
	if (ret < 0)
		LZ4E_PR_ERR("failed to write disk info");

	return ret;
}

static int lz4e_create_disk_cb(const char *arg, const struct kernel_param *kpar)
{
	return lz4e_cb_w_if_no_dev(lz4e_create_disk, arg, kpar);
}

static int lz4e_delete_disk_cb(const char *arg, const struct kernel_param *kpar)
{
	return lz4e_cb_w_if_dev(lz4e_delete_disk, arg, kpar);
}

static int lz4e_get_disk_info_cb(char *buf, const struct kernel_param *kpar)
{
	return lz4e_cb_r_if_dev(lz4e_get_disk_info, buf, kpar);
}

/* -------------------------- request statistics -------------------------- */

static inline int lz4e_reset_stats(const char *arg,
				   const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev = lzmod.lzdev;

	lz4e_stats_reset(lzdev->read_stats);
	lz4e_stats_reset(lzdev->write_stats);

	LZ4E_PR_INFO("request stats reset");
	return 0;
}

static inline int lz4e_get_stats(char *buf, const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev = lzmod.lzdev;
	int ret;

	struct lz4e_stats *read_stats = lzdev->read_stats;
	struct lz4e_stats *write_stats = lzdev->write_stats;

	u64 r_reqs_total = (u64)atomic64_read(&read_stats->reqs_total);
	u64 r_reqs_failed = (u64)atomic64_read(&read_stats->reqs_failed);
	u64 r_segments = (u64)atomic64_read(&read_stats->segments);
	u64 r_comp_bytes = (u64)atomic64_read(&read_stats->comp_bytes);
	u64 r_decomp_bytes = (u64)atomic64_read(&read_stats->decomp_bytes);
	u64 r_comp_ns = (u64)atomic64_read(&read_stats->comp_ns);
	u64 r_decomp_ns = (u64)atomic64_read(&read_stats->decomp_ns);
	u64 r_total_ns = (u64)atomic64_read(&read_stats->total_ns);

	u64 w_reqs_total = (u64)atomic64_read(&write_stats->reqs_total);
	u64 w_reqs_failed = (u64)atomic64_read(&write_stats->reqs_failed);
	u64 w_segments = (u64)atomic64_read(&write_stats->segments);
	u64 w_comp_bytes = (u64)atomic64_read(&write_stats->comp_bytes);
	u64 w_decomp_bytes = (u64)atomic64_read(&write_stats->decomp_bytes);
	u64 w_comp_ns = (u64)atomic64_read(&write_stats->comp_ns);
	u64 w_decomp_ns = (u64)atomic64_read(&write_stats->decomp_ns);
	u64 w_total_ns = (u64)atomic64_read(&write_stats->total_ns);

	ret = sysfs_emit(
		buf, LZ4E_STATS_FORMAT, r_reqs_total, r_reqs_failed, r_segments,
		r_comp_bytes, r_decomp_bytes,
		LZ4E_AVG_BLOCK(r_decomp_bytes, r_reqs_total, r_reqs_failed),
		LZ4E_AVG_SEGMENT(r_decomp_bytes, r_segments),
		LZ4E_COMP_BPMS(r_decomp_bytes, r_comp_ns),
		LZ4E_DECOMP_BPMS(r_comp_bytes, r_decomp_ns),
		LZ4E_TOTAL_BPMS(r_decomp_bytes, r_total_ns), w_reqs_total,
		w_reqs_failed, w_segments, w_comp_bytes, w_decomp_bytes,
		LZ4E_AVG_BLOCK(w_decomp_bytes, w_reqs_total, w_reqs_failed),
		LZ4E_AVG_SEGMENT(w_decomp_bytes, w_segments),
		LZ4E_COMP_BPMS(w_decomp_bytes, w_comp_ns),
		LZ4E_DECOMP_BPMS(w_comp_bytes, w_decomp_ns),
		LZ4E_TOTAL_BPMS(w_decomp_bytes, w_total_ns));
	if (ret < 0)
		LZ4E_PR_ERR("failed to write request stats");

	return ret;
}

static int lz4e_reset_stats_cb(const char *arg, const struct kernel_param *kpar)
{
	return lz4e_cb_w_if_dev(lz4e_reset_stats, arg, kpar);
}

static int lz4e_get_stats_cb(char *buf, const struct kernel_param *kpar)
{
	return lz4e_cb_r_if_dev(lz4e_get_stats, buf, kpar);
}

/* --------------------------- compression type --------------------------- */

static inline int lz4e_set_comp_type(const char *arg,
				     const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev = lzmod.lzdev;
	lz4e_comp_t comp_type;
	char *comp_str;

	if (strncmp(arg, LZ4E_COMP_CONT_STR, LZ4E_COMP_STR_LEN) == 0) {
		comp_type = LZ4E_COMP_CONT;
		comp_str = LZ4E_COMP_CONT_STR;
	} else if (strncmp(arg, LZ4E_COMP_VECT_STR, LZ4E_COMP_STR_LEN) == 0) {
		comp_type = LZ4E_COMP_VECT;
		comp_str = LZ4E_COMP_VECT_STR;
	} else if (strncmp(arg, LZ4E_COMP_STRM_STR, LZ4E_COMP_STR_LEN) == 0) {
		comp_type = LZ4E_COMP_STRM;
		comp_str = LZ4E_COMP_STRM_STR;
	} else if (strncmp(arg, LZ4E_COMP_EXTD_STR, LZ4E_COMP_STR_LEN) == 0) {
		comp_type = LZ4E_COMP_EXTD;
		comp_str = LZ4E_COMP_EXTD_STR;
	} else {
		LZ4E_PR_ERR("undefined compression type");
		return -EINVAL;
	}

	lzdev->comp_type = comp_type;

	LZ4E_PR_INFO("set compression type: %s", comp_str);
	return 0;
}

static inline int lz4e_get_comp_type(char *buf, const struct kernel_param *kpar)
{
	struct lz4e_dev *lzdev = lzmod.lzdev;
	int ret;

	switch (lzdev->comp_type) {
	case LZ4E_COMP_CONT:
		ret = sysfs_emit(buf,
				 "cont: compression on contiguous buffers");
		break;
	case LZ4E_COMP_VECT:
		ret = sysfs_emit(buf, "vect: compression on each of bvecs");
		break;
	case LZ4E_COMP_STRM:
		ret = sysfs_emit(buf, "strm: streamed compression on bvecs");
		break;
	case LZ4E_COMP_EXTD:
		ret = sysfs_emit(buf,
				 "extd: compression on scatter-gather buffers");
		break;
	}

	if (ret < 0)
		LZ4E_PR_ERR("failed to write response");

	return ret;
}

static int lz4e_set_comp_type_cb(const char *args,
				 const struct kernel_param *kpar)
{
	return lz4e_cb_w_if_dev(lz4e_set_comp_type, args, kpar);
}

static int lz4e_get_comp_type_cb(char *buf, const struct kernel_param *kpar)
{
	return lz4e_cb_r_if_dev(lz4e_get_comp_type, buf, kpar);
}

// Callbacks can have unused parameters
// NOLINTEND(misc-unused-parameters)

/* --------------------------- module init/exit --------------------------- */

static int __init lz4e_module_init(void)
{
	int major = register_blkdev(LZ4E_MAJOR, LZ4E_DEVICE_NAME);

	if (major < 0) {
		LZ4E_PR_ERR("failed to load module");
		return -EIO;
	}

	lzmod.major = major;

	LZ4E_PR_INFO("module loaded successfully");
	return 0;
}

static void __exit lz4e_module_exit(void)
{
	int major = lzmod.major;
	struct lz4e_dev *lzdev = lzmod.lzdev;

	unregister_blkdev((unsigned int)major, LZ4E_DEVICE_NAME);
	lzmod.major = 0;

	lz4e_dev_free(lzdev);
	lzmod.lzdev = NULL;

	LZ4E_PR_INFO("module unloaded successfully");
}

static const struct kernel_param_ops lz4e_mapper_ops = {
	.set = lz4e_create_disk_cb,
	.get = lz4e_get_disk_info_cb,
};

static const struct kernel_param_ops lz4e_unmapper_ops = {
	.set = lz4e_delete_disk_cb,
	.get = lz4e_get_disk_info_cb,
};

static const struct kernel_param_ops lz4e_stats_ops = {
	.set = lz4e_reset_stats_cb,
	.get = lz4e_get_stats_cb,
};

static const struct kernel_param_ops lz4e_comp_type_ops = {
	.set = lz4e_set_comp_type_cb,
	.get = lz4e_get_comp_type_cb,
};

module_param_cb(mapper, &lz4e_mapper_ops, NULL, S_IRUGO | S_IWUSR);
MODULE_PARM_DESC(mapper, "Map to existing block device");

module_param_cb(unmapper, &lz4e_unmapper_ops, NULL, S_IRUGO | S_IWUSR);
MODULE_PARM_DESC(unmapper, "Unmap from existing block device");

module_param_cb(stats, &lz4e_stats_ops, NULL, S_IRUGO | S_IWUSR);
MODULE_PARM_DESC(stats, "Block device request statistics");

module_param_cb(comp_type, &lz4e_comp_type_ops, NULL, S_IRUGO | S_IWUSR);
MODULE_PARM_DESC(comp_type, "Path for compression (cont, vect, strm, extd)");

module_init(lz4e_module_init);
module_exit(lz4e_module_exit);

MODULE_AUTHOR("Alexander Bugaev");
MODULE_DESCRIPTION("Proxy block device for testing extended LZ4");
MODULE_LICENSE("GPL");
