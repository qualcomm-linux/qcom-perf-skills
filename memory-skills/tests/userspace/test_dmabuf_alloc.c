/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * test_dmabuf_alloc.c -- Memory skill validation: DMA-BUF allocation
 *
 * Allocates N MB via /dev/dma_heap (Linux DMA heap interface).
 * DMA-BUF memory is NOT in AnonPages/PSS -- it appears only in
 * /sys/kernel/debug/dma_buf/bufinfo and the skill's DMA-BUF category.
 *
 * Expected skill delta: DMA-BUF +N MB, AnonPages unchanged
 *
 * Build:
 *   aarch64-linux-gnu-gcc -O0 -o test_dmabuf_alloc test_dmabuf_alloc.c
 *
 * Usage:
 *   ./test_dmabuf_alloc --size <MB> [--hold <seconds>] [--heap <name>]
 *   ./test_dmabuf_alloc --size 50 --hold 30
 *   ./test_dmabuf_alloc --size 50 --heap system-uncached
 *
 * Available heaps (check with: ls /dev/dma_heap/):
 *   system          -- cached system heap (default)
 *   system-uncached -- uncached system heap
 *   linux,cma       -- CMA heap (shows in CMA category)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/dma-heap.h>

#define DEFAULT_HEAP "system"

static void usage(const char *prog)
{
    fprintf(stderr, "Usage: %s --size <MB> [--hold <seconds>] [--heap <name>]\n", prog);
    fprintf(stderr, "  --size  MB to allocate via DMA-BUF (required)\n");
    fprintf(stderr, "  --hold  seconds to hold allocation (default: 30)\n");
    fprintf(stderr, "  --heap  DMA heap name (default: system)\n");
    fprintf(stderr, "          Available: ls /dev/dma_heap/\n");
}

int main(int argc, char *argv[])
{
    int  size_mb  = 0;
    int  hold_sec = 30;
    char heap_name[64] = DEFAULT_HEAP;

    static struct option opts[] = {
        {"size", required_argument, 0, 's'},
        {"hold", required_argument, 0, 'h'},
        {"heap", required_argument, 0, 'H'},
        {0, 0, 0, 0}
    };

    int c;
    while ((c = getopt_long(argc, argv, "s:h:H:", opts, NULL)) != -1) {
        switch (c) {
        case 's': size_mb  = atoi(optarg); break;
        case 'h': hold_sec = atoi(optarg); break;
        case 'H': snprintf(heap_name, sizeof(heap_name), "%s", optarg); break;
        default:  usage(argv[0]); return 1;
        }
    }

    if (size_mb <= 0) {
        fprintf(stderr, "ERROR: --size must be > 0\n");
        usage(argv[0]);
        return 1;
    }

    size_t size = (size_t)size_mb * 1024 * 1024;
    char heap_path[128];
    snprintf(heap_path, sizeof(heap_path), "/dev/dma_heap/%s", heap_name);

    printf("[test_dmabuf_alloc] PID=%d\n", getpid());
    printf("[test_dmabuf_alloc] Opening heap: %s\n", heap_path);

    int heap_fd = open(heap_path, O_RDWR);
    if (heap_fd < 0) {
        perror("open /dev/dma_heap");
        fprintf(stderr, "Available heaps:\n");
        system("ls /dev/dma_heap/ 2>/dev/null || echo '  (none found)'");
        return 1;
    }

    struct dma_heap_allocation_data alloc = {
        .len      = size,
        .fd_flags = O_RDWR | O_CLOEXEC,
        .heap_flags = 0,
    };

    printf("[test_dmabuf_alloc] Allocating %d MB DMA-BUF from heap '%s'...\n",
           size_mb, heap_name);

    if (ioctl(heap_fd, DMA_HEAP_IOCTL_ALLOC, &alloc) < 0) {
        perror("DMA_HEAP_IOCTL_ALLOC");
        close(heap_fd);
        return 1;
    }

    /* Map and touch pages to ensure physical allocation */
    void *buf = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, alloc.fd, 0);
    if (buf != MAP_FAILED) {
        memset(buf, 0xEF, size);
        printf("[test_dmabuf_alloc] Mapped and touched %d MB.\n", size_mb);
    } else {
        printf("[test_dmabuf_alloc] Warning: mmap failed (buffer still allocated).\n");
    }

    printf("[test_dmabuf_alloc] Allocated %d MB DMA-BUF (fd=%d). Holding for %d seconds.\n",
           size_mb, alloc.fd, hold_sec);
    printf("[test_dmabuf_alloc] Expected skill delta: DMA-BUF +%d MB (exporter: %s)\n",
           size_mb, heap_name);
    printf("[test_dmabuf_alloc] Verify: cat /sys/kernel/debug/dma_buf/bufinfo\n");
    printf("[test_dmabuf_alloc] Collect snapshot now, then wait for 'Done'.\n");

    sleep(hold_sec);

    if (buf != MAP_FAILED)
        munmap(buf, size);
    close(alloc.fd);
    close(heap_fd);
    printf("[test_dmabuf_alloc] Freed %d MB DMA-BUF. Done.\n", size_mb);
    return 0;
}