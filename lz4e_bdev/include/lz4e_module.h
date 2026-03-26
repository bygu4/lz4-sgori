// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#ifndef LZ4E_MODULE_H
#define LZ4E_MODULE_H

#include <linux/moduleparam.h>

#include "lz4e_dev.h"
#include "lz4e_static.h"

/* struct representing the block device module */
struct lz4e_module {
	int major;
	struct lz4e_dev *lzdev;
} LZ4E_ALIGN_16;

/* run setter callback if no device exists */
inline int lz4e_cb_w_if_no_dev(int (*func)(const char *arg,
					   const struct kernel_param *kpar),
			       struct lz4e_module *lzmod, const char *arg,
			       const struct kernel_param *kpar)
{
	if (lzmod->lzdev) {
		LZ4E_PR_ERR("device exists");
		return -EBUSY;
	}

	return func(arg, kpar);
}

/* run setter callback if device exists */
inline int lz4e_cb_w_if_dev(int (*func)(const char *arg,
					const struct kernel_param *kpar),
			    struct lz4e_module *lzmod, const char *arg,
			    const struct kernel_param *kpar)
{
	if (!lzmod->lzdev) {
		LZ4E_PR_ERR("no device found");
		return -ENODEV;
	}

	return func(arg, kpar);
}

/* run getter callback if device exists */
inline int lz4e_cb_r_if_dev(int (*func)(char *buf,
					const struct kernel_param *kpar),
			    struct lz4e_module *lzmod, char *buf,
			    const struct kernel_param *kpar)
{
	if (!lzmod->lzdev) {
		LZ4E_PR_ERR("no device found");
		return -ENODEV;
	}

	return func(buf, kpar);
}

#define LZ4E_CB_W_IF_NO_DEV(name, func, lzmod)                             \
	static int(name)(const char *arg, const struct kernel_param *kpar) \
	{                                                                  \
		return lz4e_cb_w_if_no_dev((func), &(lzmod), arg, kpar);   \
	}

#define LZ4E_CB_W_IF_DEV(name, func, lzmod)                                \
	static int(name)(const char *arg, const struct kernel_param *kpar) \
	{                                                                  \
		return lz4e_cb_w_if_dev((func), &(lzmod), arg, kpar);      \
	}

#define LZ4E_CB_R_IF_DEV(name, func, lzmod)                           \
	static int(name)(char *buf, const struct kernel_param *kpar)  \
	{                                                             \
		return lz4e_cb_r_if_dev((func), &(lzmod), buf, kpar); \
	}

#define LZ4E_PARAM_OPS(name, setter, getter)           \
	static const struct kernel_param_ops(name) = { \
		.set = (setter),                       \
		.get = (getter),                       \
	}

#endif
