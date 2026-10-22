/* Evaluation set: 10 range bugs (4 out-of-range indexes, 2 zero divisors,
 * 4 constant conditions). `gcc -Wall -Wextra -O0` reports none of them;
 * the interval-analysis rules should report exactly these 10. */
#include <stdio.h>
#define N 5

int shift_left(void) {
    int a[N];
    for (int i = 0; i < N; i++)
        a[i] = a[i + 1];
    return a[0];
}

int one_based(void) {
    int b[N] = {0};
    int s = 0;
    for (int i = 1; i <= N; i++)
        s += b[i];
    return s;
}

int backwards(void) {
    int c[N] = {0};
    int s = 0;
    for (int i = N; i >= 0; i--)
        s += c[i];
    return s;
}

int past_start(void) {
    int d[N] = {0};
    int s = 0;
    for (int i = N - 1; i >= -1; i--)
        s += d[i];
    return s;
}

int rates(void) {
    int s = 0;
    for (int i = 0; i < 4; i++)
        s += 100 / i;
    int n = 0;
    s %= n;
    return s;
}

int dead_loops(void) {
    int total = 0;
    for (int i = 10; i < 5; i++)
        total += i;
    int k = 0;
    while (k > 0)
        k--;
    int x = 5;
    if (x < 10)
        total = 1;
    else
        total = 2;
    for (int j = 0; j < N; j++) {
        if (j > N)
            total = -1;
    }
    return total + k;
}

int main(void) {
    printf("%d %d %d %d %d %d\n", shift_left(), one_based(), backwards(), past_start(), rates(), dead_loops());
    return 0;
}
