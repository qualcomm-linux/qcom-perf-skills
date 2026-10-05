/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * test_mmap_alloc.c -- Memory skill validation: anonymous mmap allocation
 *
 * Allocates N MB via mmap(MAP_ANONYMOUS) + memset (touches all pages).
 * This is how large buffers are allocated in practice (cam-server ISP buffers,
 * media codecs, etc.) -- shows in AnonPages, not heap.
 *
 * Expected skill delta: AnonPages +N MB, process PSS +N MB
 *
 * Build:
 *   aarch64-linux-gnu-gcc -O0 -o test_mmap_alloc test_mmap_alloc.c
 *
 * Usage:
 *   ./test_mmap_alloc --size <MB> [--hold <seconds>]
 *   ./test_mmap_alloc --size 50 --hold 30
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <sys/mman.h>

static void usage(const char *prog)
{
    fprintf(stderr, "Usage: %s --size <MB> [--hold <seconds>]\n", prog);
    fprintf(stderr, "  --size  MB to allocate via mmap(MAP_ANONYMOUS) (required)\n");
    fprintf(stderr, "  --hold  seconds to hold allocation (default: 30)\n");
}

int main(int argc, char *argv[])
{
    int size_mb  = 0;
    int hold_sec = 30;

    static struct option opts[] = {
        {"size", required_argument, 0, 's'},
        {"hold", required_argument, 0, 'h'},
        {0, 0, 0, 0}
    };

    int c;
    while ((c = getopt_long(argc, argv, "s:h:", opts, NULL)) != -1) {
        switch (c) {
        case 's': size_mb  = atoi(optarg); break;
        case 'h': hold_sec = atoi(optarg); break;
        default:  usage(argv[0]); return 1;
        }
    }

    if (size_mb <= 0) {
        fprintf(stderr, "ERROR: --size must be > 0\n");
        usage(argv[0]);
        return 1;
    }

    size_t size = (size_t)size_mb * 1024 * 1024;

    printf("[test_mmap_alloc] PID=%d\n", getpid());
    printf("[test_mmap_alloc] Allocating %d MB via mmap(MAP_PRIVATE|MAP_ANONYMOUS)...\n",
           size_mb);

    void *buf = mmap(NULL, size,
                     PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS,
                     -1, 0);
    if (buf == MAP_FAILED) {
        perror("mmap");
        return 1;
    }

    /* Touch all pages to force physical allocation */
    memset(buf, 0xCD, size);

    printf("[test_mmap_alloc] Allocated %d MB. Holding for %d seconds.\n",
           size_mb, hold_sec);
    printf("[test_mmap_alloc] Expected skill delta: AnonPages +%d MB, PSS +%d MB\n",
           size_mb, size_mb);
    printf("[test_mmap_alloc] Collect snapshot now, then wait for 'Done'.\n");

    sleep(hold_sec);

    munmap(buf, size);
    printf("[test_mmap_alloc] Freed %d MB. Done.\n", size_mb);
    return 0;
}