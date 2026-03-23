// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (C) 2025 Alexander Bugaev
 *
 * This file is released under the GPL.
 */

#include <linux/bio.h>
#include <linux/blk_types.h>
#include <linux/blkdev.h>
#include <linux/gfp_types.h>
#include <linux/stddef.h>
#include <linux/types.h>

#include "include/lz4e_req.h"

#include "include/lz4e_chunk.h"
#include "include/lz4e_dev.h"
#include "include/lz4e_static.h"
#include "include/lz4e_stats.h"
#include "include/lz4e_under_dev.h"

void lz4e_req_free(struct lz4e_req *lzreq)
{
	if (!lzreq)
		return;

	lz4e_chunk_free(lzreq->chunk);
	bio_put(lzreq->new_bio);

	kfree(lzreq);

	LZ4E_PR_DEBUG("released request");
}

static inline struct bio *
lz4e_req_alloc_new_bio(struct bio *original_bio,
		       struct lz4e_under_dev *under_dev, gfp_t gfp_mask,
		       lz4e_comp_t comp_type)
{
	switch (comp_type) {
	case LZ4E_COMP_CONT:
		/* no clone, will add buffer */
		return bio_alloc_bioset(under_dev->bdev, original_bio->bi_vcnt,
					original_bio->bi_opf, gfp_mask,
					under_dev->bset);
	case LZ4E_COMP_VECT:
	case LZ4E_COMP_STRM:
	case LZ4E_COMP_EXTD:
		return bio_alloc_clone(under_dev->bdev, original_bio, gfp_mask,
				       under_dev->bset);
	default:
		return NULL;
	}
}

struct lz4e_req *lz4e_req_alloc(struct bio *original_bio,
				struct lz4e_under_dev *under_dev,
				gfp_t gfp_mask, lz4e_comp_t comp_type)
{
	struct lz4e_req *lzreq;
	lz4e_chunk_t *chunk;
	struct bio *new_bio;

	lzreq = kzalloc(sizeof(*lzreq), gfp_mask);
	if (!lzreq) {
		LZ4E_PR_ERR("failed to allocate request struct: %zu bytes",
			    sizeof(*lzreq));
		goto error;
	}

	chunk = lz4e_chunk_alloc(original_bio, under_dev, gfp_mask, comp_type);
	if (!chunk) {
		LZ4E_PR_ERR("failed to allocate chunk");
		goto free_req;
	}

	new_bio = lz4e_req_alloc_new_bio(original_bio, under_dev, gfp_mask,
					 comp_type);
	if (!new_bio) {
		LZ4E_PR_ERR("failed to allocate new bio");
		goto free_chunk;
	}

	lzreq->chunk = chunk;
	lzreq->new_bio = new_bio;
	lzreq->new_bio->bi_iter.bi_sector = original_bio->bi_iter.bi_sector;
	lzreq->new_bio->bi_vcnt = original_bio->bi_vcnt;

	LZ4E_PR_DEBUG("allocated request");
	return lzreq;

free_chunk:
	lz4e_chunk_free(chunk);
free_req:
	kfree(lzreq);
error:
	return NULL;
}

static void lz4e_end_io_read(struct bio *new_bio)
{
	blk_status_t status;
	int ret;

	struct lz4e_req *lzreq = new_bio->bi_private;
	struct bio *original_bio = lzreq->original_bio;
	struct lz4e_stats *stats_to_update = lzreq->stats_to_update;
	lz4e_chunk_t *chunk = lzreq->chunk;

	if (new_bio->bi_status != BLK_STS_OK) {
		status = new_bio->bi_status;
		goto end;
	}

	ret = lz4e_chunk_run_comp(chunk);
	if (ret) {
		LZ4E_PR_ERR("read: chunk compression failed");
		status = BLK_STS_IOERR;
		goto end;
	}

	ret = lz4e_chunk_end(chunk, original_bio, LZ4E_READ);
	if (ret) {
		LZ4E_PR_ERR("read: failed to finish chunk");
		status = BLK_STS_IOERR;
		goto end;
	}

	lz4e_stats_update(stats_to_update, new_bio);
	status = BLK_STS_OK;
end:
	LZ4E_PR_INFO("read: completed request");

	original_bio->bi_status = status;
	bio_endio(original_bio);

	lz4e_req_free(lzreq);
}

static void lz4e_end_io_write(struct bio *new_bio)
{
	struct lz4e_req *lzreq = new_bio->bi_private;
	struct bio *original_bio = lzreq->original_bio;
	struct lz4e_stats *stats_to_update = lzreq->stats_to_update;

	lz4e_stats_update(stats_to_update, new_bio);

	LZ4E_PR_INFO("write: completed request");

	original_bio->bi_status = new_bio->bi_status;
	bio_endio(original_bio);

	lz4e_req_free(lzreq);
}

static blk_status_t lz4e_req_init_read(struct lz4e_req *lzreq,
				       struct bio *original_bio,
				       struct lz4e_dev *lzdev)
{
	int ret;

	ret = lz4e_chunk_init(lzreq->chunk, lzreq->new_bio, LZ4E_READ);
	if (ret) {
		LZ4E_PR_ERR("read: failed to initialize chunk");
		return BLK_STS_IOERR;
	}

	lzreq->original_bio = original_bio;
	lzreq->stats_to_update = lzdev->read_stats;
	lzreq->new_bio->bi_end_io = lz4e_end_io_read;

	LZ4E_PR_DEBUG("read: initialized request");
	return BLK_STS_OK;
}

static blk_status_t lz4e_req_init_write(struct lz4e_req *lzreq,
					struct bio *original_bio,
					struct lz4e_dev *lzdev)
{
	int ret;

	ret = lz4e_chunk_init(lzreq->chunk, lzreq->original_bio, LZ4E_WRITE);
	if (ret) {
		LZ4E_PR_ERR("write: failed to initialize chunk");
		return BLK_STS_IOERR;
	}

	ret = lz4e_chunk_run_comp(lzreq->chunk);
	if (ret) {
		LZ4E_PR_ERR("write: chunk compression failed");
		return BLK_STS_IOERR;
	}

	ret = lz4e_chunk_end(lzreq->chunk, lzreq->new_bio, LZ4E_WRITE);
	if (ret) {
		LZ4E_PR_ERR("write: failed to finish chunk");
		return BLK_STS_IOERR;
	}

	lzreq->original_bio = original_bio;
	lzreq->stats_to_update = lzdev->write_stats;
	lzreq->new_bio->bi_end_io = lz4e_end_io_write;

	LZ4E_PR_DEBUG("write: initialized request");
	return BLK_STS_OK;
}

blk_status_t lz4e_req_init(struct lz4e_req *lzreq, struct bio *original_bio,
			   struct lz4e_dev *lzdev)
{
	enum req_op op_type = bio_op(original_bio);

	switch (op_type) {
	case REQ_OP_READ:
		return lz4e_req_init_read(lzreq, original_bio, lzdev);
	case REQ_OP_WRITE:
		return lz4e_req_init_write(lzreq, original_bio, lzdev);
	default:
		LZ4E_PR_ERR("unsupported request operation");
		return BLK_STS_NOTSUPP;
	}
}

void lz4e_req_submit(struct lz4e_req *lzreq)
{
	struct bio *new_bio = lzreq->new_bio;

	new_bio->bi_private = lzreq;

	submit_bio_noacct(new_bio);

	LZ4E_PR_DEBUG("submitted request to underlying device");
}
