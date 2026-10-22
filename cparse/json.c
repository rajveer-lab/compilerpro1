#include "json.h"
#include "ast.h"
#include "errors.h"
#include "directives.h"
#include <stdio.h>
#include <string.h>

static void print_indent(int level) {
    for (int i = 0; i < level; i++) printf("  ");
}

static void print_string(const char *s) {
    if (!s) { printf("null"); return; }
    printf("\"");
    while (*s) {
        if (*s == '"') printf("\\\"");
        else if (*s == '\\') printf("\\\\");
        else if (*s == '\n') printf("\\n");
        else if (*s == '\r') printf("\\r");
        else if (*s == '\t') printf("\\t");
        else if ((unsigned char)*s < 0x20) printf("\\u%04x", (unsigned char)*s);
        else printf("%c", *s);
        s++;
    }
    printf("\"");
}

void json_print_string(const char *s) {
    print_string(s);
}

static void print_type(Type *t);
static void print_node(Node *n, int level);

static void print_type(Type *t) {
    if (!t) { printf("null"); return; }
    printf("{");
    switch (t->tk) {
        case TK_BASE:
            printf("\"tk\": \"base\", \"name\": "); print_string(t->name);
            printf(", \"const\": %s", t->is_const ? "true" : "false");
            break;
        case TK_POINTER:
            printf("\"tk\": \"pointer\", \"to\": "); print_type(t->to);
            printf(", \"const\": %s", t->is_const ? "true" : "false");
            break;
        case TK_ARRAY:
            printf("\"tk\": \"array\", \"of\": "); print_type(t->to);
            printf(", \"size\": ");
            if (t->size) print_node(t->size, 0); else printf("null");
            break;
        case TK_STRUCT:
            printf("\"tk\": \"struct\", \"name\": "); print_string(t->name);
            printf(", \"fields\": ");
            if (t->fields) {
                printf("[");
                for (int i = 0; t->fields[i]; i++) {
                    print_node(t->fields[i], 0);
                    if (t->fields[i+1]) printf(", ");
                }
                printf("]");
            } else {
                printf("null");
            }
            break;
        case TK_TYPEDEF:
            printf("\"tk\": \"typedef\", \"name\": "); print_string(t->name);
            break;
        case TK_FUNCTION:
            printf("\"tk\": \"function\", \"returns\": "); print_type(t->returns);
            printf(", \"params\": [");
            if (t->params) {
                for (int i = 0; t->params[i]; i++) {
                    print_node(t->params[i], 0);
                    if (t->params[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
    }
    printf("}");
}

static void print_loc(Loc loc) {
    printf("\"line\": %d, \"col\": %d, \"end_line\": %d, \"end_col\": %d",
           loc.first_line, loc.first_column, loc.last_line, loc.last_column);
}

static void print_node(Node *n, int level) {
    if (!n) { printf("null"); return; }
    
    // We only indent if level > 0, to format lists nicely. But simple recursive formatting is fine.
    // For arrays we print inline mostly.
    
    printf("{");
    
    switch (n->kind) {
        case ND_FUNCTION_DEF:
            printf("\"kind\": \"FunctionDef\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"return_type\": "); print_type(n->return_type);
            printf(", \"params\": [");
            if (n->params) {
                for (int i = 0; n->params[i]; i++) {
                    print_node(n->params[i], level+1);
                    if (n->params[i+1]) printf(", ");
                }
            }
            printf("], \"storage\": "); print_string(n->storage);
            printf(", \"body\": "); print_node(n->body, level+1);
            break;
        case ND_PROTOTYPE:
            printf("\"kind\": \"Prototype\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"return_type\": "); print_type(n->return_type);
            printf(", \"params\": [");
            if (n->params) {
                for (int i = 0; n->params[i]; i++) {
                    print_node(n->params[i], level+1);
                    if (n->params[i+1]) printf(", ");
                }
            }
            printf("], \"storage\": "); print_string(n->storage);
            break;
        case ND_VAR_DECL:
            printf("\"kind\": \"VarDecl\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"type\": "); print_type(n->type);
            printf(", \"storage\": "); print_string(n->storage);
            printf(", \"init\": "); print_node(n->init, level+1);
            printf(", \"is_global\": %s", n->is_global ? "true" : "false");
            break;
        case ND_TYPEDEF_DECL:
            printf("\"kind\": \"TypedefDecl\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"type\": "); print_type(n->type);
            break;
        case ND_STRUCT_DEF:
            printf("\"kind\": \"StructDef\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"fields\": [");
            if (n->fields) {
                for (int i = 0; n->fields[i]; i++) {
                    print_node(n->fields[i], level+1);
                    if (n->fields[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
        case ND_PARAM:
            printf("\"kind\": \"Param\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"type\": "); print_type(n->type);
            break;
        case ND_BLOCK:
            printf("\"kind\": \"Block\", "); print_loc(n->loc);
            printf(", \"stmts\": [");
            if (n->items) {
                for (int i = 0; n->items[i]; i++) {
                    print_node(n->items[i], level+1);
                    if (n->items[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
        case ND_DECL_STMT:
            printf("\"kind\": \"DeclStmt\", "); print_loc(n->loc);
            printf(", \"decls\": [");
            if (n->items) {
                for (int i = 0; n->items[i]; i++) {
                    print_node(n->items[i], level+1);
                    if (n->items[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
        case ND_EXPR_STMT:
            printf("\"kind\": \"ExprStmt\", "); print_loc(n->loc);
            printf(", \"expr\": "); print_node(n->expr, level+1);
            break;
        case ND_EMPTY_STMT:
            printf("\"kind\": \"EmptyStmt\", "); print_loc(n->loc);
            break;
        case ND_IF:
            printf("\"kind\": \"If\", "); print_loc(n->loc);
            printf(", \"cond\": "); print_node(n->cond, level+1);
            printf(", \"then\": "); print_node(n->then_branch, level+1);
            printf(", \"else\": "); print_node(n->else_branch, level+1);
            break;
        case ND_WHILE:
            printf("\"kind\": \"While\", "); print_loc(n->loc);
            printf(", \"cond\": "); print_node(n->cond, level+1);
            printf(", \"body\": "); print_node(n->body, level+1);
            break;
        case ND_DO_WHILE:
            printf("\"kind\": \"DoWhile\", "); print_loc(n->loc);
            printf(", \"body\": "); print_node(n->body, level+1);
            printf(", \"cond\": "); print_node(n->cond, level+1);
            break;
        case ND_FOR:
            printf("\"kind\": \"For\", "); print_loc(n->loc);
            printf(", \"init\": "); print_node(n->init, level+1);
            printf(", \"cond\": "); print_node(n->cond, level+1);
            printf(", \"step\": "); print_node(n->step, level+1);
            printf(", \"body\": "); print_node(n->body, level+1);
            break;
        case ND_SWITCH:
            printf("\"kind\": \"Switch\", "); print_loc(n->loc);
            printf(", \"expr\": "); print_node(n->expr, level+1);
            printf(", \"body\": "); print_node(n->body, level+1);
            break;
        case ND_CASE:
            printf("\"kind\": \"Case\", "); print_loc(n->loc);
            printf(", \"value\": "); print_node(n->value, level+1);
            break;
        case ND_DEFAULT:
            printf("\"kind\": \"Default\", "); print_loc(n->loc);
            break;
        case ND_BREAK:
            printf("\"kind\": \"Break\", "); print_loc(n->loc);
            break;
        case ND_CONTINUE:
            printf("\"kind\": \"Continue\", "); print_loc(n->loc);
            break;
        case ND_RETURN:
            printf("\"kind\": \"Return\", "); print_loc(n->loc);
            printf(", \"value\": "); print_node(n->value, level+1);
            break;
        case ND_IDENTIFIER:
            printf("\"kind\": \"Identifier\", "); print_loc(n->loc);
            printf(", \"name\": "); print_string(n->name);
            break;
        case ND_INT_LITERAL:
            printf("\"kind\": \"IntLiteral\", "); print_loc(n->loc);
            printf(", \"text\": "); print_string(n->text);
            break;
        case ND_FLOAT_LITERAL:
            printf("\"kind\": \"FloatLiteral\", "); print_loc(n->loc);
            printf(", \"text\": "); print_string(n->text);
            break;
        case ND_CHAR_LITERAL:
            printf("\"kind\": \"CharLiteral\", "); print_loc(n->loc);
            printf(", \"text\": "); print_string(n->text);
            break;
        case ND_STRING_LITERAL:
            printf("\"kind\": \"StringLiteral\", "); print_loc(n->loc);
            printf(", \"text\": "); print_string(n->text);
            break;
        case ND_UNARY:
            printf("\"kind\": \"Unary\", "); print_loc(n->loc);
            printf(", \"op\": "); print_string(n->op);
            printf(", \"operand\": "); print_node(n->operand, level+1);
            break;
        case ND_POSTFIX:
            printf("\"kind\": \"Postfix\", "); print_loc(n->loc);
            printf(", \"op\": "); print_string(n->op);
            printf(", \"operand\": "); print_node(n->operand, level+1);
            break;
        case ND_BINARY:
            printf("\"kind\": \"Binary\", "); print_loc(n->loc);
            printf(", \"op\": "); print_string(n->op);
            printf(", \"left\": "); print_node(n->left, level+1);
            printf(", \"right\": "); print_node(n->right, level+1);
            break;
        case ND_ASSIGN:
            printf("\"kind\": \"Assign\", "); print_loc(n->loc);
            printf(", \"op\": "); print_string(n->op);
            printf(", \"target\": "); print_node(n->target, level+1);
            printf(", \"value\": "); print_node(n->value, level+1);
            break;
        case ND_TERNARY:
            printf("\"kind\": \"Ternary\", "); print_loc(n->loc);
            printf(", \"cond\": "); print_node(n->cond, level+1);
            printf(", \"then\": "); print_node(n->then_branch, level+1);
            printf(", \"else\": "); print_node(n->else_branch, level+1);
            break;
        case ND_CALL:
            printf("\"kind\": \"Call\", "); print_loc(n->loc);
            printf(", \"callee\": "); print_node(n->callee, level+1);
            printf(", \"args\": [");
            if (n->items) {
                for (int i = 0; n->items[i]; i++) {
                    print_node(n->items[i], level+1);
                    if (n->items[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
        case ND_INDEX:
            printf("\"kind\": \"Index\", "); print_loc(n->loc);
            printf(", \"base\": "); print_node(n->base, level+1);
            printf(", \"index\": "); print_node(n->index, level+1);
            break;
        case ND_MEMBER:
            printf("\"kind\": \"Member\", "); print_loc(n->loc);
            printf(", \"base\": "); print_node(n->base, level+1);
            printf(", \"name\": "); print_string(n->name);
            printf(", \"arrow\": %s", n->arrow ? "true" : "false");
            break;
        case ND_CAST:
            printf("\"kind\": \"Cast\", "); print_loc(n->loc);
            printf(", \"type\": "); print_type(n->type);
            printf(", \"operand\": "); print_node(n->operand, level+1);
            break;
        case ND_SIZEOF:
            printf("\"kind\": \"Sizeof\", "); print_loc(n->loc);
            if (n->operand) {
                printf(", \"operand\": "); print_node(n->operand, level+1);
                printf(", \"type\": null");
            } else {
                printf(", \"operand\": null");
                printf(", \"type\": "); print_type(n->type);
            }
            break;
        case ND_INIT_LIST:
            printf("\"kind\": \"InitList\", "); print_loc(n->loc);
            printf(", \"items\": [");
            if (n->items) {
                for (int i = 0; n->items[i]; i++) {
                    print_node(n->items[i], level+1);
                    if (n->items[i+1]) printf(", ");
                }
            }
            printf("]");
            break;
    }
    
    printf("}");
}

void print_json(const char *filename) {
    printf("{\n");
    printf("  \"schema_version\": 1,\n");
    // The path can contain backslashes (Windows) or quotes, so it must be escaped too.
    printf("  \"file\": "); print_string(filename); printf(",\n");
    print_errors_json();
    print_directives_json();
    
    Node **top_level = get_top_level();
    if (top_level && top_level[0]) {
        printf("  \"unit\": {\n");
        printf("    \"kind\": \"TranslationUnit\",\n");
        printf("    \"items\": [\n");
        for (int i = 0; top_level[i]; i++) {
            printf("      ");
            print_node(top_level[i], 3);
            if (top_level[i+1]) printf(",\n");
            else printf("\n");
        }
        printf("    ]\n  }\n");
    } else {
        printf("  \"unit\": null\n");
    }
    printf("}\n");
}
