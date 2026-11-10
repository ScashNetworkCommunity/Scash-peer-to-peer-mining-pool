#include <atomic>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
#include "randomx.h"

#if defined(_WIN32) || defined(__CYGWIN__)
  #define SCASH_MINER_API __declspec(dllexport)
#else
  #define SCASH_MINER_API __attribute__((visibility("default")))
#endif

namespace {
    std::mutex g_miner_mutex;
    uint8_t g_active_seed[32] = {0};
    bool g_seed_initialized = false;
    bool g_dataset_ready = false;
    randomx_flags g_flags = RANDOMX_FLAG_DEFAULT;
    randomx_cache* g_cache = nullptr;
    randomx_dataset* g_dataset = nullptr;
    std::vector<randomx_vm*> g_vms;

    void cleanup_vms() {
        for (size_t i = 0; i < g_vms.size(); ++i) {
            if (g_vms[i]) {
                randomx_destroy_vm(g_vms[i]);
            }
        }
        g_vms.clear();
    }

    bool ensure_initialized(const uint8_t* seed_32, int num_threads, int want_fast_mode) {
        if (!g_seed_initialized || std::memcmp(g_active_seed, seed_32, 32) != 0) {
            cleanup_vms();
            g_flags = randomx_get_flags();
            if (!g_cache) {
                g_cache = randomx_alloc_cache(g_flags | RANDOMX_FLAG_LARGE_PAGES);
                if (!g_cache) {
                    g_cache = randomx_alloc_cache(g_flags);
                }
            }
            if (!g_cache) {
                return false;
            }
            randomx_init_cache(g_cache, seed_32, 32);

            if (want_fast_mode) {
                if (!g_dataset) {
                    g_dataset = randomx_alloc_dataset(RANDOMX_FLAG_LARGE_PAGES);
                    if (!g_dataset) {
                        g_dataset = randomx_alloc_dataset(RANDOMX_FLAG_DEFAULT);
                    }
                }
                if (g_dataset) {
                    unsigned long total_items = randomx_dataset_item_count();
                    int init_threads = num_threads > 0 ? num_threads : 1;
                    std::vector<std::thread> workers;
                    unsigned long per_thread = total_items / init_threads;
                    for (int t = 0; t < init_threads; ++t) {
                        unsigned long start = t * per_thread;
                        unsigned long count = (t == init_threads - 1) ? (total_items - start) : per_thread;
                        workers.emplace_back([start, count]() {
                            randomx_init_dataset(g_dataset, g_cache, start, count);
                        });
                    }
                    for (size_t t = 0; t < workers.size(); ++t) {
                        workers[t].join();
                    }
                    g_dataset_ready = true;
                } else {
                    g_dataset_ready = false;
                }
            } else {
                g_dataset_ready = false;
            }

            std::memcpy(g_active_seed, seed_32, 32);
            g_seed_initialized = true;
        }

        if ((int)g_vms.size() < num_threads) {
            cleanup_vms();
            randomx_flags vm_flags = g_flags;
            if (g_dataset_ready && g_dataset) {
                vm_flags = vm_flags | RANDOMX_FLAG_FULL_MEM;
            }
            for (int i = 0; i < num_threads; ++i) {
                randomx_vm* vm = randomx_create_vm(vm_flags | RANDOMX_FLAG_LARGE_PAGES, g_dataset_ready ? nullptr : g_cache, g_dataset_ready ? g_dataset : nullptr);
                if (!vm) {
                    vm = randomx_create_vm(vm_flags, g_dataset_ready ? nullptr : g_cache, g_dataset_ready ? g_dataset : nullptr);
                }
                if (!vm && (vm_flags & RANDOMX_FLAG_JIT)) {
                    vm = randomx_create_vm(RANDOMX_FLAG_DEFAULT | (g_dataset_ready ? RANDOMX_FLAG_FULL_MEM : RANDOMX_FLAG_DEFAULT), g_dataset_ready ? nullptr : g_cache, g_dataset_ready ? g_dataset : nullptr);
                }
                if (!vm) {
                    return false;
                }
                g_vms.push_back(vm);
            }
        }
        return true;
    }
}

extern "C" SCASH_MINER_API int scash_mine_batch(
    const uint8_t* seed_key_32,
    const uint8_t* header_80,
    uint64_t target_u64,
    uint32_t start_nonce,
    uint32_t hashes_per_thread,
    int num_threads,
    int use_fast_dataset,
    uint32_t* out_winning_nonce,
    uint8_t* out_rx_hash_32,
    uint8_t* out_rx_cm_32,
    uint64_t* out_total_hashes
) {
    if (num_threads < 1) num_threads = 1;
    if (num_threads > 64) num_threads = 64;
    if (hashes_per_thread < 2) hashes_per_thread = 2;

    std::lock_guard<std::mutex> lock(g_miner_mutex);
    if (!ensure_initialized(seed_key_32, num_threads, use_fast_dataset)) {
        return -1;
    }

    std::atomic<int> found(0);
    std::atomic<uint64_t> total_done(0);
    std::mutex win_mutex;

    std::vector<std::thread> threads;
    threads.reserve(num_threads);

    for (int tid = 0; tid < num_threads; ++tid) {
        randomx_vm* vm = g_vms[tid];
        uint32_t thread_start = start_nonce + (uint32_t)(tid * hashes_per_thread);

        threads.emplace_back([=, &found, &total_done, &win_mutex]() {
            uint8_t hdr112[112];
            std::memset(hdr112, 0, 112);
            std::memcpy(hdr112, header_80, 80);

            uint8_t rx_hash[RANDOMX_HASH_SIZE];
            uint8_t rx_cm[RANDOMX_HASH_SIZE];

            uint32_t n = thread_start;
            // Serialize initial nonce in little-endian at byte offset 76
            hdr112[76] = (uint8_t)(n & 0xFF);
            hdr112[77] = (uint8_t)((n >> 8) & 0xFF);
            hdr112[78] = (uint8_t)((n >> 16) & 0xFF);
            hdr112[79] = (uint8_t)((n >> 24) & 0xFF);

            randomx_calculate_hash_first(vm, hdr112, 112);
            uint64_t local_count = 0;

            for (uint32_t step = 0; step < hashes_per_thread; ++step) {
                if (found.load(std::memory_order_relaxed)) {
                    break;
                }
                uint32_t next_n = n + 1;
                hdr112[76] = (uint8_t)(next_n & 0xFF);
                hdr112[77] = (uint8_t)((next_n >> 8) & 0xFF);
                hdr112[78] = (uint8_t)((next_n >> 16) & 0xFF);
                hdr112[79] = (uint8_t)((next_n >> 24) & 0xFF);

                // Pipeline next hash while retrieving result for nonce n
                randomx_calculate_hash_next(vm, hdr112, 112, rx_hash);

                // Restore nonce n at offset 76 to compute Scash commitment
                hdr112[76] = (uint8_t)(n & 0xFF);
                hdr112[77] = (uint8_t)((n >> 8) & 0xFF);
                hdr112[78] = (uint8_t)((n >> 16) & 0xFF);
                hdr112[79] = (uint8_t)((n >> 24) & 0xFF);

                randomx_calculate_commitment(hdr112, 112, rx_hash, rx_cm);
                local_count++;

                uint64_t cm_top64 = 0;
                for (int b = 7; b >= 0; --b) {
                    cm_top64 = (cm_top64 << 8) | rx_cm[24 + b];
                }

                if (cm_top64 <= target_u64) {
                    if (found.exchange(1) == 0) {
                        std::lock_guard<std::mutex> wlock(win_mutex);
                        *out_winning_nonce = n;
                        std::memcpy(out_rx_hash_32, rx_hash, 32);
                        std::memcpy(out_rx_cm_32, rx_cm, 32);
                    }
                    break;
                }
                n = next_n;
            }
            total_done.fetch_add(local_count, std::memory_order_relaxed);
        });
    }

    for (size_t t = 0; t < threads.size(); ++t) {
        threads[t].join();
    }

    *out_total_hashes = total_done.load();
    return found.load();
}
