/* Evaluation set: correct programs with the loop, guard and division patterns
 * that a naive range checker gets wrong (binary search, reverse loops, guarded
 * indexes, modulo guards, do-while, nested loops). Expect zero interval findings. */
#include <stdio.h>
#define N 10
#define SIZE 5

int arr[SIZE];

int binary_search(int a[], int n, int key) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (a[mid] == key)
            return mid;
        else if (a[mid] < key)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return -1;
}

int sum_reverse(void) {
    int b[N];
    int s = 0;
    for (int i = 0; i < N; i++)
        b[i] = i;
    for (int j = N - 1; j >= 0; j--)
        s += b[j];
    return s;
}

int average(int total, int count) {
    if (count == 0)
        return 0;
    return total / count;
}

int digits(int x) {
    int d = 0;
    if (x < 0) x = -x;
    do {
        d++;
        x /= 10;
    } while (x > 0);
    return d;
}

int guarded(int k) {
    int c[SIZE];
    for (int i = 0; i < SIZE; i++) c[i] = 0;
    if (k >= 0 && k < SIZE)
        c[k] = 1;
    int m = k % SIZE;
    if (m != 0)
        return 100 / m;
    return c[0];
}

int countdown(void) {
    int t[4] = {1, 2, 3, 4};
    int i = 3;
    int s = 0;
    while (i >= 0) {
        s += t[i];
        i--;
    }
    return s;
}

int fib(int n) {
    int a = 0, b = 1;
    for (int i = 0; i < n; i++) {
        int t = a + b;
        a = b;
        b = t;
    }
    return a;
}

int mod_guard(int v) {
    int r = v % 3;
    if (r)
        return 12 / r;
    return 0;
}

int scan_and_divide(void) {
    int n;
    scanf("%d", &n);
    if (n > 0)
        return 100 / n;
    return 0;
}

int even_loop(void) {
    int e[N];
    for (int i = 0; i < N; i += 2)
        e[i] = 1;
    for (int i2 = 0; i2 + 1 < N; i2++)
        e[i2 + 1] = e[i2];
    return e[0];
}

int flag_loop(int limit) {
    int found = 0;
    int i = 0;
    while (!found && i < limit) {
        if (i * i > 50)
            found = 1;
        i++;
    }
    return found ? i : -1;
}

int nested(void) {
    int m[SIZE];
    int total = 0;
    for (int r = 0; r < SIZE; r++) {
        m[r] = r;
        for (int c = r; c < SIZE; c++)
            total += m[r] * c;
    }
    return total;
}

int main(void) {
    int data[SIZE] = {1, 3, 5, 7, 9};
    printf("%d %d %d %d\n", binary_search(data, SIZE, 7), sum_reverse(), average(10, 0), digits(-123));
    printf("%d %d %d %d\n", guarded(2), countdown(), fib(10), mod_guard(7));
    printf("%d %d %d %d\n", scan_and_divide(), even_loop(), flag_loop(100), nested());
    return 0;
}
