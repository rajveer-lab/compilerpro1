%{
#include <stdio.h>
#include <string.h>
#include "parser.h"
#include "ast.h"
#include "errors.h"
#include "directives.h"
#include "typedefs.h"

// yylloc tracking
#define YY_USER_ACTION \
    yylloc.first_line = yylloc.last_line = yylineno; \
    yylloc.first_column = yycolumn; \
    yycolumn += yyleng; \
    yylloc.last_column = yycolumn - 1;

int yycolumn = 1;
%}

%option noyywrap nounput noinput yylineno
%x COMMENT
%x LINE_COMMENT
%x DIR_INCLUDE
%x DIR_DEFINE

L [a-zA-Z_]
D [0-9]
H [a-fA-F0-9]
E [Ee][+-]?{D}+

%%
[\n] { yycolumn = 1; }
[ \t\r]+ { /* skip whitespace */ }

"/*"         { BEGIN(COMMENT); }
<COMMENT>"*/" { BEGIN(INITIAL); }
<COMMENT>\n   { yycolumn = 1; }
<COMMENT>.    { }
<COMMENT><<EOF>> { report_error(yylloc.first_line, yylloc.first_column, "unterminated block comment"); return 0; }

"//"         { BEGIN(LINE_COMMENT); }
<LINE_COMMENT>\n { yycolumn = 1; BEGIN(INITIAL); }
<LINE_COMMENT>. { }

"#"[ \t]*"include"[ \t]* { BEGIN(DIR_INCLUDE); }
<DIR_INCLUDE>[<\"][^>\"\n]+[>\"] {
    add_include(yytext, yylloc.first_line, yylloc.first_column);
    BEGIN(INITIAL);
}
<DIR_INCLUDE>. { BEGIN(INITIAL); }

"#"[ \t]*"define"[ \t]+ { BEGIN(DIR_DEFINE); }
<DIR_DEFINE>{L}({L}|{D})*[ \t]+[^ \t\r\n][^\r\n]* {
    char buf[1024];
    strncpy(buf, yytext, sizeof(buf)-1);
    buf[1023] = '\0';
    char *name = strtok(buf, " \t");
    char *val = strtok(NULL, "");
    if (val) {
        while (*val == ' ' || *val == '\t') val++;
        add_define(name, val, yylloc.first_line, yylloc.first_column);
    }
    BEGIN(INITIAL);
}
    /* Function-like macros (`MAX(a,b) ...`) and value-less defines (`#define DEBUG`)
     * don't match the object-like rule above; skip the rest of the line instead of
     * lexing the macro body as code. For `N 5` both rules match the same length and
     * flex picks the earlier (object-like) one. */
<DIR_DEFINE>[^\r\n]* { BEGIN(INITIAL); }
<DIR_DEFINE>\n { yycolumn = 1; BEGIN(INITIAL); }

    /* Conditional compilation and other directives are skipped (docs/C_SUBSET.md). */
"#"[ \t]*("if"|"ifdef"|"ifndef"|"elif"|"else"|"endif"|"undef"|"pragma"|"error"|"warning"|"line")[^\r\n]* { }

"void"     { return VOID; }
"char"     { return CHAR; }
"short"    { return SHORT; }
"int"      { return INT; }
"long"     { return LONG; }
"float"    { return FLOAT; }
"double"   { return DOUBLE; }
"signed"   { return SIGNED; }
"unsigned" { return UNSIGNED; }
"const"    { return CONST; }
"static"   { return STATIC; }
"extern"   { return EXTERN; }
"struct"   { return STRUCT; }
"typedef"  { return TYPEDEF; }
"if"       { return IF; }
"else"     { return ELSE; }
"while"    { return WHILE; }
"do"       { return DO; }
"for"      { return FOR; }
"switch"   { return SWITCH; }
"case"     { return CASE; }
"default"  { return DEFAULT; }
"break"    { return BREAK; }
"continue" { return CONTINUE; }
"return"   { return RETURN; }
"sizeof"   { return SIZEOF; }

{L}({L}|{D})* {
    char *s = strdup(yytext);
    yylval.s = s;
    if (typedefs_is_type(s)) return TYPE_NAME;
    return IDENT;
}

0[xX]{H}+[uUlL]* { yylval.s = strdup(yytext); return INT_LITERAL; }
0{D}+[uUlL]*     { yylval.s = strdup(yytext); return INT_LITERAL; }
{D}+[uUlL]*      { yylval.s = strdup(yytext); return INT_LITERAL; }

{D}+{E}[fFlL]?   { yylval.s = strdup(yytext); return FLOAT_LITERAL; }
{D}*"."{D}+({E})?[fFlL]? { yylval.s = strdup(yytext); return FLOAT_LITERAL; }
{D}+"."{D}*({E})?[fFlL]? { yylval.s = strdup(yytext); return FLOAT_LITERAL; }

L?'(\\.|[^\\'\n])+' { yylval.s = strdup(yytext); return CHAR_LITERAL; }
L?'(\\.|[^\\'\n])* { report_error(yylloc.first_line, yylloc.first_column, "unterminated character literal"); BEGIN(INITIAL); }

L?\"(\\.|[^\"\n])*\" { yylval.s = strdup(yytext); return STRING_LITERAL; }
L?\"(\\.|[^\"\n])* { report_error(yylloc.first_line, yylloc.first_column, "unterminated string literal"); BEGIN(INITIAL); }

"->" { return PTR_OP; }
"++" { return INC_OP; }
"--" { return DEC_OP; }
"<<" { return LEFT_OP; }
">>" { return RIGHT_OP; }
"<=" { return LE_OP; }
">=" { return GE_OP; }
"==" { return EQ_OP; }
"!=" { return NE_OP; }
"&&" { return AND_OP; }
"||" { return OR_OP; }
"*=" { return MUL_ASSIGN; }
"/=" { return DIV_ASSIGN; }
"%=" { return MOD_ASSIGN; }
"+=" { return ADD_ASSIGN; }
"-=" { return SUB_ASSIGN; }
"<<=" { return LEFT_ASSIGN; }
">>=" { return RIGHT_ASSIGN; }
"&=" { return AND_ASSIGN; }
"^=" { return XOR_ASSIGN; }
"|=" { return OR_ASSIGN; }

";"  { return ';'; }
"{"  { return '{'; }
"}"  { return '}'; }
","  { return ','; }
":"  { return ':'; }
"="  { return '='; }
"("  { return '('; }
")"  { return ')'; }
"["  { return '['; }
"]"  { return ']'; }
"."  { return '.'; }
"&"  { return '&'; }
"!"  { return '!'; }
"~"  { return '~'; }
"-"  { return '-'; }
"+"  { return '+'; }
"*"  { return '*'; }
"/"  { return '/'; }
"%"  { return '%'; }
"<"  { return '<'; }
">"  { return '>'; }
"^"  { return '^'; }
"|"  { return '|'; }
"?"  { return '?'; }

. {
    char msg[64];
    snprintf(msg, sizeof(msg), "invalid character '%c'", yytext[0]);
    report_error(yylloc.first_line, yylloc.first_column, msg);
}
%%
