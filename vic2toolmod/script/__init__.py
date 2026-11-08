"""Lossless parsing of Paradox (Clausewitz) script files.

Typical use::

    from vic2toolmod.script import parse_file
    doc, encoding = parse_file("events/500_RPM_Reforms_Events.txt")
    for event in doc.assignments("country_event"):
        ...
    assert doc.to_text() == doc.text
"""

from vic2toolmod.script.cst import Assignment, Block, Document, ErrorNode, Node, Scalar
from vic2toolmod.script.diagnostics import Diagnostic, LineIndex, Severity
from vic2toolmod.script.lexer import tokenize
from vic2toolmod.script.parser import parse_file, parse_text
from vic2toolmod.script.tokens import Token, TokenKind

__all__ = [
    "Assignment",
    "Block",
    "Diagnostic",
    "Document",
    "ErrorNode",
    "LineIndex",
    "Node",
    "Scalar",
    "Severity",
    "Token",
    "TokenKind",
    "parse_file",
    "parse_text",
    "tokenize",
]
