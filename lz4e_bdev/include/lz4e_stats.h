// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#ifndef LZ4E_STATS_H
#define LZ4E_STATS_H

#include <linux/blk_types.h>
#include <linux/math.h>
#include <linux/types.h>

#include "lz4e_chunk.h"
#include "lz4e_static.h"

/* request statistics of a disk for one of the operations */
struct lz4e_stats {
	atomic64_t reqs_total;	/* how many reqs submitted */
	atomic64_t reqs_failed; /* how many reqs failed */

	atomic64_t segments;	/* number of single-page segments */
	atomic64_t decomp_size; /* size of decompressed data */
	atomic64_t comp_size;	/* size of compressed data */

	atomic64_t comp_ns;   /* time for compression */
	atomic64_t decomp_ns; /* time for decompression */
	atomic64_t total_ns;  /* total elapsed time */
} LZ4E_ALIGN_64;

/* allocate request statistics */
struct lz4e_stats *lz4e_stats_alloc(gfp_t gfp_mask);

/* update statistics using given bio and chunk */
void lz4e_stats_update(struct lz4e_stats *lzstats, struct bio *bio,
		       lz4e_chunk_t *chunk);

/* reset request statistics */
void lz4e_stats_reset(struct lz4e_stats *lzstats);

/* free request statistics */
void lz4e_stats_free(struct lz4e_stats *lzstats);

#define LZ4E_NS_TO_MS(ns) (DIV_ROUND_UP((ns), 1000000LL))

#define LZ4E_REQS_SUCCESS(total, failed) ((total) - (failed))

#define LZ4E_AVG_BLOCK(decomp_size, total, failed)                    \
	((LZ4E_REQS_SUCCESS(total, failed) != 0) ?                    \
		 ((decomp_size) / LZ4E_REQS_SUCCESS(total, failed)) : \
		 0)

#define LZ4E_AVG_SEGMENT(decomp_size, segments) \
	(((segments) != 0) ? ((decomp_size) / (segments)) : 0)

/* throughput in bytes/millisecond ~ KB/second */

#define LZ4E_COMP_BPMS(decomp_size, comp_ns)                \
	((LZ4E_NS_TO_MS(comp_ns) != 0) ?                    \
		 ((decomp_size) / LZ4E_NS_TO_MS(comp_ns)) : \
		 0)

#define LZ4E_DECOMP_BPMS(comp_size, decomp_ns)              \
	((LZ4E_NS_TO_MS(decomp_ns) != 0) ?                  \
		 ((comp_size) / LZ4E_NS_TO_MS(decomp_ns)) : \
		 0)

#define LZ4E_TOTAL_BPMS(decomp_size, total_ns)               \
	((LZ4E_NS_TO_MS(total_ns) != 0) ?                    \
		 ((decomp_size) / LZ4E_NS_TO_MS(total_ns)) : \
		 0)

/* format string for request statistics */
#define LZ4E_STATS_FORMAT \
	"\
read:\n\
	reqs_total: %llu\n\
	reqs_failed: %llu\n\
	segments: %llu\n\
	decomp_size: %llu\n\
	comp_size: %llu\n\
	avg_block: %llu\n\
	avg_segment: %llu\n\
	comp_bpms: %llu\n\
	decomp_bpms: %llu\n\
	total_bpms: %llu\n\
write:\n\
	reqs_total: %llu\n\
	reqs_failed: %llu\n\
	segments: %llu\n\
	decomp_size: %llu\n\
	comp_size: %llu\n\
	avg_block: %llu\n\
	avg_segment: %llu\n\
	comp_bpms: %llu\n\
	decomp_bpms: %llu\n\
	total_bpms: %llu\n\
"

#endif
