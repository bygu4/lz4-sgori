#ifndef LZ4E
#define LZ4E

#include <linux/bio.h>
#include <linux/types.h>

#define LZ4E_NAME "lz4e"

#define LZ4E_ACCELERATION_DEFAULT 1

/* whether to use multi-page bvecs on sg-buffer read/write/copy */
#ifndef CONFIG_HIGHMEM
#define LZ4E_MULTIPAGE 1
#endif

/* whether to map pages prematurely */
#ifdef LZ4E_MULTIPAGE
#define LZ4E_PREMAP 1
#endif

#define LZ4E_MEMORY_USAGE	14
#define LZ4E_HASHLOG		(LZ4E_MEMORY_USAGE - 2)
#define LZ4E_HASH_SIZE_U32	(1 << LZ4E_HASHLOG)
#define LZ4E_HASH_SIZE_U64	(LZ4E_HASH_SIZE_U32 >> 1)
#define LZ4E_BV_ITER_SIZE_U64	(BIO_MAX_VECS >> 1)

#ifdef LZ4E_PREMAP
#define LZ4E_ADDRS_SIZE_U64	(BIO_MAX_VECS * sizeof(size_t) / sizeof(unsigned long long))
#define LZ4E_STREAMSIZE_U64	\
	(LZ4E_HASH_SIZE_U64 \
	 + (2 * LZ4E_ADDRS_SIZE_U64) \
	 + LZ4E_BV_ITER_SIZE_U64 + 1)
#else
#define LZ4E_STREAMSIZE_U64	\
	(LZ4E_HASH_SIZE_U64 + LZ4E_BV_ITER_SIZE_U64 + 1)
#endif

#define LZ4E_STREAMSIZE		\
	(LZ4E_STREAMSIZE_U64 * sizeof(unsigned long long))

#define LZ4E_MEM_COMPRESS LZ4E_STREAMSIZE

#define LZ4E_MAX_INPUT_SIZE		0x7E000000 /* 2 113 929 216 bytes */
#define LZ4E_COMPRESSBOUND(isize)	(\
	(unsigned int)(isize) > (unsigned int)LZ4E_MAX_INPUT_SIZE \
	? 0 \
	: (isize) + ((isize)/255) + 16)

/*
 * LZ4E_stream_t - information structure to track an LZ4E stream.
 */
typedef struct {
	uint32_t hashTable[LZ4E_HASH_SIZE_U32];
#ifdef LZ4E_PREMAP
	uint8_t *srcAddrs[BIO_MAX_VECS];
	uint8_t *dstAddrs[BIO_MAX_VECS];
#endif
	uint32_t bvIterSize[BIO_MAX_VECS];
	uint32_t srcBaseIdx;
	uint32_t dstBaseIdx;
} LZ4E_stream_t_internal;
typedef union {
	unsigned long long table[LZ4E_STREAMSIZE_U64];
	LZ4E_stream_t_internal internal_donotuse;
} LZ4E_stream_t;

int LZ4E_compress_fast(const struct bio_vec *src, struct bio_vec *dst,
		struct bvec_iter *srcIter, struct bvec_iter *dstIter,
		int acceleration, void *wrkmem);

int LZ4E_compress_default(const struct bio_vec *src, struct bio_vec *dst,
		struct bvec_iter *srcIter, struct bvec_iter *dstIter, void *wrkmem);

int LZ4E_decompress_safe(const char *source, char *dest,
		int compressedSize, int maxDecompressedSize);

#ifndef LZ4E_DISTANCE_MAX	/* history window size; can be user-defined at compile time */
#define LZ4E_DISTANCE_MAX 65535	/* set to maximum value by default */
#endif

#endif /* LZ4E */
