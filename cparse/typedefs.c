#include "typedefs.h"
#include <string.h>
#include <stdlib.h>

#define MAX_TYPEDEFS 1024

static char *table[MAX_TYPEDEFS];
static int count = 0;

/* There is no preprocessor, so typedefs from standard headers are never seen.
 * Pre-register the common ones so `size_t n;` or `FILE *fp;` parse as declarations. */
static const char *builtin_typedefs[] = {
    "size_t", "ssize_t", "ptrdiff_t", "FILE", "bool",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "intptr_t", "uintptr_t", "time_t", NULL
};

void typedefs_init(void) {
    for (int i = 0; i < count; i++) {
        free(table[i]);
        table[i] = NULL;
    }
    count = 0;
    for (int i = 0; builtin_typedefs[i]; i++) {
        typedefs_add(builtin_typedefs[i]);
    }
}

void typedefs_add(const char *name) {
    if (count < MAX_TYPEDEFS) {
        if (!typedefs_is_type(name)) {
            table[count++] = strdup(name);
        }
    }
}

int typedefs_is_type(const char *name) {
    for (int i = 0; i < count; i++) {
        if (strcmp(table[i], name) == 0) return 1;
    }
    return 0;
}
