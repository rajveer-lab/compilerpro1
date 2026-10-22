#include <stdio.h>

#define STUDENTS 5

/* Compiles cleanly with `gcc -Wall -Wextra`, yet every function has a bug that
 * interval analysis finds by tracking the range of values each variable can hold. */

int total_marks(void) {
    int marks[STUDENTS];
    int total = 0;
    for (int i = 0; i <= STUDENTS; i++) {   /* i reaches 5: one past the end */
        marks[i] = i * 10;
        total += marks[i];
    }
    return total;
}

int average(int total) {
    int count = 0;                            /* never updated */
    return total / count;
}

int grade(void) {
    int score = 72;
    if (score > 100)                          /* score is always 72 */
        return -1;
    return score / 10;
}

int main(void) {
    int total = total_marks();
    printf("%d %d %d\n", total, average(total), grade());
    return 0;
}
