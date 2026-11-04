#ifndef ACCEPTANCE_H
#define ACCEPTANCE_H
#include <stdint.h>
typedef struct {
 uint32_t rounds,commands,frames,passed,timeouts,header_errors,xor_errors;
 uint32_t status_errors,data_errors,unsupported,pairs_ok,pairs_mismatch,pairs_skipped;
} acceptance_stats_t;
extern volatile acceptance_stats_t g_acceptance_sw,g_acceptance_hw;
extern volatile uint32_t g_slow_full_pass,g_hw_ran,g_acceptance_finished;
void acceptance_run(void);
#endif
