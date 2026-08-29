import re
from collections import Counter

# calc: small arithmetic/string helpers.


def add(a, b):
    """Add two numbers together."""
    return a + b


def fibonacci(n):
    """Return the n-th Fibonacci number (0-indexed: fib(0) == 0, fib(1) == 1)."""
    if n <= 0:
        return 0
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def is_palindrome(s):
    """Return True if s reads the same forwards and backwards, ignoring case and non-alphanumerics."""
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    return cleaned == cleaned[::-1]


def most_common_word(text):
    """Return the most frequently occurring word in text, ignoring punctuation and case."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    counts = Counter(words)
    return counts.most_common(1)[0][0]
