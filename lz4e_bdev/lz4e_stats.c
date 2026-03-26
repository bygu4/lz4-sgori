// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#include <linux/bio.h>
#include <linux/blk_types.h>
#include <linux/fortify-string.h>
#include <linux/ktime.h>
#include <linux/slab.h>
#include <linux/stddef.h>
#include <linux/types.h>

#include "include/lz4e_stats.h"

#include "include/lz4e_chunk.h"
#include "include/lz4e_static.h"

void lz4e_stats_free(struct lz4e_stats *lzstats)
{
	kfree(lzstats);

	LZ4E_PR_DEBUG("released request stats");
}

struct lz4e_stats *lz4e_stats_alloc(gfp_t gfp_mask)
{
	struct lz4e_stats *lzstats;

	lzstats = kzalloc(sizeof(*lzstats), gfp_mask);
	if (!lzstats) {
		LZ4E_PR_ERR("failed to allocate request stats: %zu bytes",
			    sizeof(*lzstats));
		return NULL;
	}

	LZ4E_PR_DEBUG("allocated request stats");
	return lzstats;
}

void lz4e_stats_update(struct lz4e_stats *lzstats, struct bio *bio,
		       lz4e_chunk_t *chunk)
{
	atomic64_inc(&lzstats->reqs_total);

	if (bio->bi_status != BLK_STS_OK) {
		atomic64_inc(&lzstats->reqs_failed);
		return;
	}

	atomic64_add((s64)chunk->comp_size, &lzstats->comp_size);
	atomic64_add((s64)chunk->decomp_size, &lzstats->decomp_size);
	atomic64_add((s64)bio_segments(bio), &lzstats->segments);

	atomic64_add(ktime_to_ns(chunk->comp_time), &lzstats->comp_ns);
	atomic64_add(ktime_to_ns(chunk->decomp_time), &lzstats->decomp_ns);
	atomic64_add(ktime_to_ns(chunk->total_time), &lzstats->total_ns);

	LZ4E_PR_DEBUG("updated request stats");
}

void lz4e_stats_reset(struct lz4e_stats *lzstats)
{
	memset(lzstats, 0, sizeof(*lzstats));

	LZ4E_PR_DEBUG("reset request stats");
}
