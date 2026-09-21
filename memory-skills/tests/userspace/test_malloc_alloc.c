/*
 * test_malloc_alloc.c -- Memory skill validation: userspace heap allocation
 *
 * Allocates N MB via malloc + memset (touches all pages).
 * Expected skill delta: AnonPages +N MB, process PSS +N MB
 *
 * Build:
 *   aarch64-linux-gnu-gcc -O0 -o test_malloc_alloc test_malloc_alloc.c
 *
 * Usage:
 *   ./test_malloc_alloc --size <MB> [--hold <seconds>]
 *   ./test_malloc_alloc --size 50 --hold 30
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>

static void usage(const char *prog)
{
    fprintf(stderr, "Usage: %s --size <MB> [--hold <seconds>]\n", prog);
    fprintf(stderr, "  --size  MB to allocate via malloc (required)\n");
    fprintf(stderr, "  --hold  seconds to hold allocation (default: 30)\n");
}

int main(int argc, char *argv[])
{
    int size_mb  = 100;
    int hold_sec = 3000;

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

    printf("[test_malloc_alloc] PID=%d\n", getpid());
    printf("[test_malloc_alloc] Allocating %d MB via malloc...\n", size_mb);

    char *buf = malloc(size);
    if (!buf) {
        perror("malloc");
        return 1;
    }

    /* Touch all pages to force physical allocation (RSS = PSS = size) */
    memset(buf, 0xAB, size);

    printf("[test_malloc_alloc] Allocated %d MB. Holding for %d seconds.\n",
           size_mb, hold_sec);
    printf("[test_malloc_alloc] Expected skill delta: AnonPages +%d MB, PSS +%d MB\n",
           size_mb, size_mb);
    printf("[test_malloc_alloc] Collect snapshot now, then wait for 'Done'.\n");

    sleep(hold_sec);

    free(buf);
    printf("[test_malloc_alloc] Freed %d MB. Done.\n", size_mb);
    return 0;
}
