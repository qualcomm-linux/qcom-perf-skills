/*
 * test_kmalloc_module.c -- Memory skill validation: kernel slab allocation
 *
 * Loadable kernel module that allocates N MB via kmalloc.
 * Memory appears in /proc/meminfo Slab (SUnreclaim) -- NOT reclaimable.
 *
 * Expected skill delta: Slab +N MB (SUnreclaim), KDA unchanged
 *
 * Build (on device or with matching kernel headers):
 *   make -C /lib/modules/$(uname -r)/build M=$(pwd) modules
 *
 * Usage:
 *   insmod test_kmalloc_module.ko size_mb=100
 *   cat /proc/meminfo | grep -E "Slab|SUnreclaim"   # verify increase
 *   rmmod test_kmalloc_module                         # free memory
 *
 * Parameters:
 *   size_mb   -- MB to allocate (default: 50)
 *   chunk_kb  -- size of each kmalloc chunk in KB (default: 1024 = 1 MB)
 *               Use smaller values if large kmalloc fails (e.g. 256 or 64)
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>

static int size_mb  = 50;
static int chunk_kb = 1024;

module_param(size_mb,  int, 0444);
module_param(chunk_kb, int, 0444);
MODULE_PARM_DESC(size_mb,  "Total MB to allocate via kmalloc (default: 50)");
MODULE_PARM_DESC(chunk_kb, "Size of each kmalloc chunk in KB (default: 1024)");

static void **alloc_ptrs = NULL;
static int    num_allocs = 0;

static int __init test_kmalloc_init(void)
{
    int i;
    size_t chunk_size = (size_t)chunk_kb * 1024;
    int    num_chunks = (size_mb * 1024) / chunk_kb;

    pr_info("[test_kmalloc] Loading: size_mb=%d chunk_kb=%d num_chunks=%d\n",
            size_mb, chunk_kb, num_chunks);

    if (num_chunks <= 0) {
        pr_err("[test_kmalloc] Invalid parameters\n");
        return -EINVAL;
    }

    alloc_ptrs = kmalloc_array(num_chunks, sizeof(void *), GFP_KERNEL);
    if (!alloc_ptrs) {
        pr_err("[test_kmalloc] Failed to allocate pointer array\n");
        return -ENOMEM;
    }

    for (i = 0; i < num_chunks; i++) {
        alloc_ptrs[i] = kmalloc(chunk_size, GFP_KERNEL);
        if (!alloc_ptrs[i]) {
            pr_err("[test_kmalloc] kmalloc failed at chunk %d/%d (%zu KB each)\n",
                   i, num_chunks, chunk_size / 1024);
            pr_err("[test_kmalloc] Try smaller --chunk_kb value\n");
            num_allocs = i;
            /* Free what we allocated so far */
            for (i = 0; i < num_allocs; i++)
                kfree(alloc_ptrs[i]);
            kfree(alloc_ptrs);
            alloc_ptrs = NULL;
            return -ENOMEM;
        }
        /* Touch all pages to force physical allocation */
        memset(alloc_ptrs[i], 0xAB, chunk_size);
        num_allocs++;
    }

    pr_info("[test_kmalloc] Allocated %d chunks x %d KB = %d MB via kmalloc\n",
            num_allocs, chunk_kb, (num_allocs * chunk_kb) / 1024);
    pr_info("[test_kmalloc] Check: grep -E 'Slab|SUnreclaim' /proc/meminfo\n");
    pr_info("[test_kmalloc] Free:  rmmod test_kmalloc_module\n");
    return 0;
}

static void __exit test_kmalloc_exit(void)
{
    int i;
    if (alloc_ptrs) {
        for (i = 0; i < num_allocs; i++)
            kfree(alloc_ptrs[i]);
        kfree(alloc_ptrs);
        alloc_ptrs = NULL;
    }
    pr_info("[test_kmalloc] Freed %d MB. Unloaded.\n",
            (num_allocs * chunk_kb) / 1024);
}

module_init(test_kmalloc_init);
module_exit(test_kmalloc_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Memory Skills Validation");
MODULE_DESCRIPTION("Kernel slab allocation test for memory skill validation");
MODULE_VERSION("1.0");