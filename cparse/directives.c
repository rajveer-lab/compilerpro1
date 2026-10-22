#include "directives.h"
#include "json.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *text;
    int line;
    int col;
} Include;

typedef struct {
    char *name;
    char *value;
    int line;
    int col;
} Define;

static Include includes[100];
static int include_count = 0;

static Define defines[100];
static int define_count = 0;

void add_include(const char *text, int line, int col) {
    if (include_count < 100) {
        includes[include_count].text = strdup(text);
        includes[include_count].line = line;
        includes[include_count].col = col;
        include_count++;
    }
}

void add_define(const char *name, const char *value, int line, int col) {
    if (define_count < 100) {
        defines[define_count].name = strdup(name);
        defines[define_count].value = strdup(value);
        defines[define_count].line = line;
        defines[define_count].col = col;
        define_count++;
    }
}

void print_directives_json(void) {
    printf("  \"directives\": {\n");
    /* Include paths and define values are raw source text (`"x"`, `'\n'`), so they
     * must go through the JSON string escaper. */
    printf("    \"includes\": [");
    for (int i = 0; i < include_count; i++) {
        printf("{\"text\": ");
        json_print_string(includes[i].text);
        printf(", \"line\": %d, \"col\": %d}%s",
               includes[i].line, includes[i].col,
               (i < include_count - 1) ? ", " : "");
    }
    printf("],\n");

    printf("    \"defines\": [");
    for (int i = 0; i < define_count; i++) {
        printf("{\"name\": ");
        json_print_string(defines[i].name);
        printf(", \"value\": ");
        json_print_string(defines[i].value);
        printf(", \"line\": %d, \"col\": %d}%s",
               defines[i].line, defines[i].col,
               (i < define_count - 1) ? ", " : "");
    }
    printf("]\n  },\n");
}
