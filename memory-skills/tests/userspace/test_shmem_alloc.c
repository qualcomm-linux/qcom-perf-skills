/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 * SPDX-License-Identifier: BSD-3-Clause
 *
 * test_shmem_alloc.c -- Memory skill validation: shared memory allocation
 *
 * Allocates N MB via shm_open + mmap(MAP_SHARED).
 * Shows in Shmem category (not AnonPages) because it's backed by tmpfs.
 *
 * Expected skill delta: Shmem +N MB, AnonPages unchanged
 *
 * Build:
 *   aarch64-linux-gnu-gcc -O0 -o test_shmem_alloc test_shmem_alloc.c -lrt
 *
 * Usage:
 *   ./test_shmem_alloc --size <MB> [--hold <seconds>] [--name <shm_name>]
 *   ./test_shmem_alloc --size 50 --hold 30
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <getopt.h>
#include <sys/mman.h>
#include <sys/stat.h>

#define DEFAULT_SHM_NAME "/mem_skill_test"

static void usage(const char *prog)
{
    fprintf(stderr, "Usage: %s --size <MB> [--hold <seconds>] [--name <shm_name>]\n", prog);
    fprintf(stderr, "  --size  MB to allocate via shm_open (required)\n");
    fprintf(stderr, "  --hold  seconds to hold allocation (default: 30)\n");
    fprintf(stderr, "  --name  POSIX shared memory name (default: /mem_skill_test)\n");
}

int main(int argc, char *argv[])
{
    int  size_mb  = 0;
    int  hold_sec = 30;
    char shm_name[64] = DEFAULT_SHM_NAME;

    static struct option opts[] = {
        {"size", required_argument, 0, 's'},
        {"hold", required_argument, 0, 'h'},
        {"name", required_argument, 0, 'n'},
        {0, 0, 0, 0}
    };

    int c;
    while ((c = getopt_long(argc, argv, "s:h:n:", opts, NULL)) != -1) {
        switch (c) {
        case 's': size_mb  = atoi(optarg); break;
        case 'h': hold_sec = atoi(optarg); break;
        case 'n': snprintf(shm_name, sizeof(shm_name), "%s", optarg); break;
        default:  usage(argv[0]); return 1;
        }
    }

    if (size_mb <= 0) {
        fprintf(stderr, "ERROR: --size must be > 0\n");
        usage(argv[0]);
        return 1;
    }

    size_t size = (size_t)size_mb * 1024 * 1024;

    printf("[test_shmem_alloc] PID=%d\n", getpid());
    printf("[test_shmem_alloc] Creating shared memory '%s' (%d MB)...\n",
           shm_name, size_mb);

    /* Remove any stale shm from previous run */
    shm_unlink(shm_name);

    int fd = shm_open(shm_name, O_CREAT | O_RDWR, 0666);
    if (fd < 0) {
        perror("shm_open");
        return 1;
    }

    if (ftruncate(fd, (off_t)size) < 0) {
        perror("ftruncate");
        close(fd);
        shm_unlink(shm_name);
        return 1;
    }

    void *buf = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (buf == MAP_FAILED) {
        perror("mmap");
        close(fd);
        shm_unlink(shm_name);
        return 1;
    }

    /* Touch all pages to force physical allocation */
    memset(buf, 0xBE, size);

    printf("[test_shmem_alloc] Allocated %d MB Shmem. Holding for %d seconds.\n",
           size_mb, hold_sec);
    printf("[test_shmem_alloc] Expected skill delta: Shmem +%d MB\n", size_mb);
    printf("[test_shmem_alloc] Note: Shmem is NOT in AnonPages -- it is tmpfs-backed.\n");
    printf("[test_shmem_alloc] Collect snapshot now, then wait for 'Done'.\n");

    sleep(hold_sec);

    munmap(buf, size);
    close(fd);
    shm_unlink(shm_name);
    printf("[test_shmem_alloc] Freed %d MB Shmem. Done.\n", size_mb);
    return 0;
}