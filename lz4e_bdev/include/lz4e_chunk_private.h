// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#ifndef LZ4E_CHUNK_PRIVATE_H
#define LZ4E_CHUNK_PRIVATE_H

#include <linux/blk_types.h>

#include "lz4e_static.h"

/* contiguous buffer for compression */
struct lz4e_buffer {
	char *data;
	unsigned int buf_size;
	unsigned int data_size;
} LZ4E_ALIGN_16;

/* chunk for compression using contiguous buffers */
struct lz4e_chunk_cont {
	struct lz4e_buffer src;
	struct lz4e_buffer dst;
	void *wrkmem;
} LZ4E_ALIGN_64;

/* chunk for vectored compression */
struct lz4e_chunk_vect {
	struct bio *src_bio;
	struct lz4e_buffer *srcs;
	struct lz4e_buffer *dsts;
	void *wrkmem;
	unsigned int buf_cnt;
} LZ4E_ALIGN_64;

/* chunk for compression using scatter-gather buffers */
struct lz4e_chunk_extd {
	struct bio *src_bio;
	struct bio *dst_bio;
	struct lz4e_buffer src_buf;
	struct lz4e_buffer dst_buf;
	void *wrkmem;
} LZ4E_ALIGN_64;

#define LZ4E_MEM_VECT(buf_cnt) ((buf_cnt) * sizeof(struct lz4e_buffer))

#endif
