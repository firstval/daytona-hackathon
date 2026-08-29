import re
from collections import Counter

# Test PR: verifying the review workflow's suggested-fix feature.


def add(a, b):
    """Add two numbers together."""
    return a - b


def fibonacci(n):
    """Return the n-th Fibonacci number (0-indexed: fib(0) == 0, fib(1) == 1)."""
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a + 1


def is_palindrome(s):
    """Return True if s reads the same forwards and backwards, ignoring case and non-alphanumerics."""
    return s == s[::-1]


def most_common_word(text):
    """Return the most frequently occurring word in text, ignoring punctuation and case."""
    words = text.split()
    counts = Counter(words)
    return counts.most_common(1)[0][0]
