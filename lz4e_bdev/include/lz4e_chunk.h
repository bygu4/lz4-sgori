// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#ifndef LZ4E_CHUNK_H
#define LZ4E_CHUNK_H

#include <linux/blk_types.h>
#include <linux/bvec.h>
#include <linux/types.h>

#include "lz4e_static.h"
#include "lz4e_under_dev.h"

typedef enum {
	LZ4E_COMP_CONT, /* compression on contiguous buffer */
	LZ4E_COMP_VECT, /* compression on each of bvecs */
	LZ4E_COMP_STRM, /* streamed compression on bvecs */
	LZ4E_COMP_EXTD, /* extended compression on scatter-gather buffers */
} lz4e_comp_t;

typedef enum {
	LZ4E_READ,
	LZ4E_WRITE,
} lz4e_dir_t;

struct lz4e_chunk_operations {
	int (*init)(void *chunk, struct bio *src_bio, lz4e_dir_t data_dir);
	int (*run_comp)(void *chunk);
	int (*end)(void *chunk, struct bio *dst_bio, lz4e_dir_t data_dir);
	void (*free)(void *chunk);
} LZ4E_ALIGN_32;

/* generic chunk for compression */
typedef struct {
	void *internal;
	struct lz4e_chunk_operations *ops;
} LZ4E_ALIGN_16 lz4e_chunk_t;

lz4e_chunk_t *lz4e_chunk_alloc(struct bio *original_bio,
			       struct lz4e_under_dev *under_dev, gfp_t gfp_mask,
			       lz4e_comp_t comp_type);
int lz4e_chunk_init(lz4e_chunk_t *chunk, struct bio *src_bio,
		    lz4e_dir_t data_dir);
int lz4e_chunk_run_comp(lz4e_chunk_t *chunk);
int lz4e_chunk_end(lz4e_chunk_t *chunk, struct bio *dst_bio,
		   lz4e_dir_t data_dir);
void lz4e_chunk_free(lz4e_chunk_t *chunk);

#endif
