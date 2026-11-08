"""Concrete syntax tree of a script file.

The tree knows nothing about Victoria 2 itself: it only describes the syntax
``key = value``, ``key = { ... }``, loose values ``{ 1 2 3 }`` and errors.
Every token of the file belongs to exactly one node, so printing the tree
gives back the file unchanged (see `Node.to_text`).

Node types:

* `Document` - the whole file;
* `Assignment` - ``key <op> value`` (the value can be missing on error);
* `Scalar` - a single word or string used as a value;
* `Block` - ``{ ... }``, possibly without its closing brace on error;
* `ErrorNode` - tokens that do not fit anywhere (a stray ``}`` or ``=``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from vic2toolmod.script.diagnostics import Diagnostic, LineIndex
from vic2toolmod.script.tokens import Token, TokenKind


class Node:
    """Base class of all tree nodes."""

    __slots__ = ()

    def parts(self) -> Sequence[Token | Node]:
        """The node's direct tokens and child nodes, in file order."""
        raise NotImplementedError

    def tokens(self) -> Iterator[Token]:
        """Yield all tokens of the node in file order.

        Iterative (no recursion), so arbitrarily deep nesting is safe.
        """
        stack: list[Iterator[Token | Node]] = [iter(self.parts())]
        while stack:
            for part in stack[-1]:
                if isinstance(part, Token):
                    yield part
                else:
                    stack.append(iter(part.parts()))
                    break
            else:
                stack.pop()

    def children(self) -> Iterator[Node]:
        """Yield the direct child nodes."""
        return iter(())

    def walk(self) -> Iterator[Node]:
        """Yield this node and all its descendants, depth first, in file order."""
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(list(node.children())))

    @property
    def first_token(self) -> Token:
        """The first token of the node."""
        return next(self.tokens())

    @property
    def last_token(self) -> Token:
        """The last token of the node."""
        part: Token | Node = self
        while not isinstance(part, Token):
            part = part.parts()[-1]
        return part

    @property
    def start(self) -> int:
        """Offset of the node's first token text (leading trivia excluded)."""
        return self.first_token.start

    @property
    def end(self) -> int:
        """Offset just past the node's last token."""
        return self.last_token.end

    def to_text(self) -> str:
        """Print the node, including the leading trivia of its tokens."""
        return "".join(t.leading + t.text for t in self.tokens())


class Scalar(Node):
    """A single word or string used as a value (or as a loose list item).

    Attributes:
        token: The word / string token.
    """

    __slots__ = ("token",)

    def __init__(self, token: Token) -> None:
        self.token = token

    @property
    def text(self) -> str:
        """Raw text (quotes kept)."""
        return self.token.text

    @property
    def value(self) -> str:
        """Text with quotes removed."""
        return self.token.value

    @property
    def quoted(self) -> bool:
        """Whether the value is a quoted string."""
        return self.token.kind is not TokenKind.WORD

    def parts(self) -> Sequence[Token | Node]:  # noqa: D102
        return (self.token,)

    def __repr__(self) -> str:
        return f"Scalar({self.token.text!r})"


class Block(Node):
    """``{ ... }`` - a list of items (assignments, scalars, blocks, errors).

    Attributes:
        lbrace: The ``{`` token.
        items: The contents in file order.
        rbrace: The ``}`` token, or ``None`` if the file ends before it.
    """

    __slots__ = ("items", "lbrace", "rbrace")

    def __init__(self, lbrace: Token) -> None:
        self.lbrace = lbrace
        self.items: list[Node] = []
        self.rbrace: Token | None = None

    def parts(self) -> Sequence[Token | Node]:  # noqa: D102
        tail: list[Token | Node] = [] if self.rbrace is None else [self.rbrace]
        return [self.lbrace, *self.items, *tail]

    def children(self) -> Iterator[Node]:  # noqa: D102
        return iter(self.items)

    def assignments(self, key: str | None = None) -> Iterator[Assignment]:
        """Yield direct assignments, optionally only those with a given key.

        Keys are compared case-insensitively, as the game does.
        """
        return _assignments(self.items, key)

    def find(self, key: str) -> Assignment | None:
        """Return the first direct assignment with this key, or ``None``."""
        return next(self.assignments(key), None)

    def __repr__(self) -> str:
        return f"Block({len(self.items)} items{'' if self.rbrace else ', unclosed'})"


class Assignment(Node):
    """``key <op> value``.

    Attributes:
        key: The key token (a word or a string).
        operator: The operator token (usually ``=``).
        value: The value, or ``None`` if it is missing (a syntax error).
    """

    __slots__ = ("key", "operator", "value")

    def __init__(self, key: Token, operator: Token, value: Scalar | Block | None) -> None:
        self.key = key
        self.operator = operator
        self.value = value

    @property
    def key_text(self) -> str:
        """The key without quotes."""
        return self.key.value

    def parts(self) -> Sequence[Token | Node]:  # noqa: D102
        if self.value is None:
            return (self.key, self.operator)
        return (self.key, self.operator, self.value)

    def children(self) -> Iterator[Node]:  # noqa: D102
        if self.value is not None:
            yield self.value

    def __repr__(self) -> str:
        return f"Assignment({self.key.text!r} {self.operator.text} {self.value!r})"


class ErrorNode(Node):
    """Tokens that do not fit the grammar, e.g. a ``}`` without ``{``.

    Attributes:
        error_tokens: The offending tokens.
    """

    __slots__ = ("error_tokens",)

    def __init__(self, error_tokens: list[Token]) -> None:
        self.error_tokens = error_tokens

    def parts(self) -> Sequence[Token | Node]:  # noqa: D102
        return self.error_tokens

    def __repr__(self) -> str:
        return f"ErrorNode({[t.text for t in self.error_tokens]!r})"


def _assignments(items: list[Node], key: str | None) -> Iterator[Assignment]:
    wanted = key.lower() if key is not None else None
    for item in items:
        if isinstance(item, Assignment) and (wanted is None or item.key_text.lower() == wanted):
            yield item


@dataclass(eq=False)
class Document(Node):
    """A whole parsed file.

    Attributes:
        text: The source text the document was parsed from.
        items: Top-level items in file order.
        eof: The end-of-file token (its leading trivia is the file's tail).
        diagnostics: Syntax problems found while parsing.
    """

    text: str
    items: list[Node]
    eof: Token
    diagnostics: list[Diagnostic] = field(default_factory=list)
    _lines: LineIndex | None = field(default=None, repr=False)

    def parts(self) -> Sequence[Token | Node]:  # noqa: D102
        return [*self.items, self.eof]

    def children(self) -> Iterator[Node]:  # noqa: D102
        return iter(self.items)

    def assignments(self, key: str | None = None) -> Iterator[Assignment]:
        """Yield top-level assignments, optionally only those with a given key."""
        return _assignments(self.items, key)

    def find(self, key: str) -> Assignment | None:
        """Return the first top-level assignment with this key, or ``None``."""
        return next(self.assignments(key), None)

    @property
    def lines(self) -> LineIndex:
        """Offset → line/column converter for this document (built lazily)."""
        if self._lines is None:
            self._lines = LineIndex(self.text)
        return self._lines

    def position(self, offset: int) -> tuple[int, int]:
        """Return ``(line, column)`` of an offset, both counted from 1."""
        return self.lines.position(offset)

    @property
    def has_errors(self) -> bool:
        """Whether parsing reported any error-level diagnostic."""
        return any(d.severity == "error" for d in self.diagnostics)
