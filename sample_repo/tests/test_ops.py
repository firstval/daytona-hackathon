from calc import add, fibonacci, is_palindrome, most_common_word


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
    assert add(0, 0) == 0


def test_fibonacci():
    assert [fibonacci(n) for n in range(8)] == [0, 1, 1, 2, 3, 5, 8, 13]


def test_is_palindrome():
    assert is_palindrome("racecar") is True
    assert is_palindrome("A man, a plan, a canal: Panama") is True
    assert is_palindrome("hello") is False


def test_most_common_word():
    text = "The, the. The! the the tree tree tree tree"
    assert most_common_word(text) == "the"
