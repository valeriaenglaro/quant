// qs_wasm.c - QuantSuite-specific wasm entry (GNU AGPLv3 - see LICENSE/NOTICE).
// Minimal browser ABI: init the interpreter, hand JS an input buffer, eval it.
// master.k uses only native verbs (`j json, `exp/`ln/`cos, arithmetic), so no
// .k modules are loaded (mirrors `amber master.k`, which is just kinit + bsl).
#if defined(wasm)
#include "a.h"
#define QS_SZ (1<<20)               // 1 MiB input program buffer
static char g_qs[QS_SZ];
static const char *qs_argv[2] = {"amber", 0};

__attribute__((export_name("qs_init")))
void qs_init(void){ kinit(); kargs(1,(S*)qs_argv); }

__attribute__((export_name("qs_inbuf")))
void* qs_inbuf(void){ return g_qs; }

__attribute__((export_name("qs_run")))
void qs_run(void){ A r = evs(g_qs, 1); if (r) mr(r); }  // flag 1: auto-print final value
#endif
