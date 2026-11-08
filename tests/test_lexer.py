from vic2toolmod.script import TokenKind, tokenize


def kinds(text):
    return [(t.kind, t.text) for t in tokenize(text)]


def test_simple_assignment():
    assert kinds("a = 1") == [
        (TokenKind.WORD, "a"),
        (TokenKind.OPERATOR, "="),
        (TokenKind.WORD, "1"),
        (TokenKind.EOF, ""),
    ]


def test_no_spaces_needed_around_operators_and_braces():
    assert [t for _, t in kinds("a={b=c}")] == ["a", "=", "{", "b", "=", "c", "}", ""]


def test_comments_and_whitespace_go_to_leading_trivia():
    tokens = tokenize("# head\n\ta = 1 # tail\n")
    assert tokens[0].leading == "# head\n\t"
    assert tokens[0].comments() == [" head"]
    assert tokens[-1].kind is TokenKind.EOF
    assert tokens[-1].leading == " # tail\n"
    assert tokens[-1].comments() == [" tail"]


def test_hash_inside_string_is_not_a_comment():
    tokens = tokenize('text = "#2" # real comment')
    assert tokens[2].kind is TokenKind.STRING
    assert tokens[2].value == "#2"
    assert tokens[3].comments() == [" real comment"]


def test_string_may_span_lines():
    tokens = tokenize('a = "x\ny"')
    assert tokens[2].text == '"x\ny"'


def test_unterminated_string_ends_at_end_of_line():
    tokens = tokenize('a = "open\nb = 2')
    assert tokens[2].kind is TokenKind.BAD_STRING
    assert tokens[2].text == '"open'
    assert tokens[2].value == "open"
    assert [t.text for t in tokens[3:]] == ["b", "=", "2", ""]


def test_comparison_operators():
    assert [t for k, t in kinds("a < 1 b >= 2 c <= 3 d > 4") if k is TokenKind.OPERATOR] == [
        "<",
        ">=",
        "<=",
        ">",
    ]


def test_positions():
    tokens = tokenize("  key = value")
    assert (tokens[0].start, tokens[0].end, tokens[0].full_start) == (2, 5, 0)
    assert tokens[2].start == 8


def test_lossless_for_odd_input():
    text = "﻿\x00 a=\t{}}{ # c\r\n\"s\" = ''\x1a"
    assert "".join(t.leading + t.text for t in tokenize(text)) == text


def test_empty_input():
    tokens = tokenize("")
    assert len(tokens) == 1
    assert tokens[0].kind is TokenKind.EOF
