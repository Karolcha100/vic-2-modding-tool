"""Check a parsed file against the schema (one file at a time, no mod index).

The validator walks the tree with an explicit stack. Each block is checked in
a *frame*: either a structural rule / fixed fields (e.g. the inside of an
event) or a command context (trigger or effect) with the current scope.

Diagnostic codes:

==========================  ========  =========================================
``schema.unknown-key``      warning   key not known in this place (K21 = B)
``schema.wrong-context``    error     an effect used where triggers belong, or vice versa
``schema.wrong-scope``      warning   command not valid in the current scope
``schema.wrong-value``      error     value of the wrong type
``schema.missing-field``    error     required key is missing
``schema.duplicate-key``    warning   key that may appear once appears again
``schema.wrong-operator``   warning   Victoria 2 only understands ``=``
``schema.unexpected-value`` warning   loose value / block where none is allowed
==========================  ========  =========================================
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from vic2toolmod.schema.model import (
    BlockSpec,
    Command,
    Context,
    FieldsSpec,
    FileType,
    ListSpec,
    OneOf,
    Rule,
    RuleSpec,
    Schema,
    TypeSpec,
    ValueSpec,
)
from vic2toolmod.schema.values import SCOPE_KEYWORDS, check_scalar, is_tag
from vic2toolmod.script.cst import Assignment, Block, Document, ErrorNode, Node, Scalar
from vic2toolmod.script.diagnostics import Diagnostic, Severity
from vic2toolmod.script.tokens import Token

_INT_KEY = re.compile(r"\d+")
_DATE_KEY = re.compile(r"\d{1,4}\.\d{1,2}\.\d{1,2}")
_FLOAT_KEY = re.compile(r"-?\d*\.?\d+")


@dataclass
class _Frame:
    """One block being checked."""

    items: list[Node]
    anchor: Token  # where "missing field" is reported
    scope: str | None
    rule: Rule | None = None
    fields: FieldsSpec | None = None
    context: Context | None = None
    list_spec: ListSpec | None = None
    seen: dict[str, int] = field(default_factory=dict)


def file_type_for(path: str, schema: Schema) -> FileType | None:
    """The first file type whose glob matches ``path`` (relative, ``/`` separated)."""
    p = PurePosixPath(path.replace("\\", "/")).as_posix().lower()
    for ft in schema.file_types:
        if any(fnmatch.fnmatchcase(p, g.lower()) for g in ft.paths):
            return ft
    return None


Names = Callable[[str, str], "bool | None"]
"""``names(registry, name)`` -> exists? (``None`` = registry unknown)."""


class Validator:
    """Checks documents against a schema.

    Args:
        schema: The schema.
        names: Optional lookup of names from the mod (Phase 3 registries). With
            it, dynamic keys such as ``aristocrats = { }`` are recognised and
            ``ref:`` values are checked (``ref.unknown-name`` warnings).
    """

    def __init__(self, schema: Schema, names: Names | None = None) -> None:
        self.schema = schema
        self.names = names
        self._out: list[Diagnostic] = []
        self._stack: list[_Frame] = []

    # -- public API ----------------------------------------------------------
    def validate(self, doc: Document, rule: str, scope: str | None = None) -> list[Diagnostic]:
        """Check a whole document whose root follows ``rule``.

        Returns:
            Diagnostics sorted by position.
        """
        self._out = []
        root = self.schema.rules[rule]
        self._stack = [_Frame(doc.items, doc.eof, scope, rule=root)]
        while self._stack:
            frame = self._stack.pop()
            self._check_frame(frame)
        self._out.sort(key=lambda d: d.start)
        return self._out

    def validate_file(self, doc: Document, rel_path: str) -> list[Diagnostic] | None:
        """Check a document by its path; ``None`` if no file type matches the path."""
        ft = file_type_for(rel_path, self.schema)
        if ft is None:
            return None
        return self.validate(doc, ft.rule, ft.scope)

    # -- reporting -------------------------------------------------------------
    def _report(self, severity: Severity, code: str, message: str, node: Node | Token) -> None:
        if isinstance(node, Token):
            start, end = node.start, node.end
        elif isinstance(node, Assignment):
            start, end = node.key.start, node.key.end
        else:
            start, end = node.start, node.end
        self._out.append(Diagnostic(severity, code, message, start, end))

    # -- frames ------------------------------------------------------------------
    def _check_frame(self, frame: _Frame) -> None:
        for item in frame.items:
            if isinstance(item, Assignment):
                if item.operator.text != "=":
                    self._report(
                        Severity.WARNING,
                        "schema.wrong-operator",
                        f"Victoria 2 only understands '=', not '{item.operator.text}'",
                        item.operator,
                    )
                if frame.context is not None:
                    self._command(item, frame.context, frame.scope)
                else:
                    self._structural(item, frame)
            elif isinstance(item, ErrorNode):
                continue  # already reported by the parser
            else:
                self._loose(item, frame)
        if frame.rule is not None or frame.fields is not None:
            fields = frame.rule.fields if frame.rule is not None else frame.fields.fields  # type: ignore[union-attr]
            for key, fld in fields.items():
                if fld.required and key not in frame.seen:
                    self._report(
                        Severity.ERROR,
                        "schema.missing-field",
                        f"required key '{key}' is missing",
                        frame.anchor,
                    )

    def _loose(self, item: Node, frame: _Frame) -> None:
        allowed: TypeSpec | None = None
        if frame.list_spec is not None:
            allowed = frame.list_spec.item
        elif frame.rule is not None:
            allowed = frame.rule.values
        if allowed is None or isinstance(item, Block):
            what = "block" if isinstance(item, Block) else f"value '{item.to_text().strip()}'"
            self._report(
                Severity.WARNING, "schema.unexpected-value", f"unexpected {what} here", item
            )
            return
        assert isinstance(item, Scalar)
        problem = check_scalar(item.value, allowed, self.schema)
        if problem:
            self._report(
                Severity.ERROR, "schema.wrong-value", f"expected {problem}, got '{item.text}'", item
            )

    def _structural(self, item: Assignment, frame: _Frame) -> None:
        key = item.key_text.lower()
        fields = frame.rule.fields if frame.rule is not None else frame.fields.fields  # type: ignore[union-attr]
        other = frame.rule.other if frame.rule is not None else frame.fields.other  # type: ignore[union-attr]
        fld = fields.get(key)
        if fld is not None:
            count = frame.seen.get(key, 0) + 1
            frame.seen[key] = count
            if count == 2 and not fld.multiple:
                self._report(
                    Severity.WARNING,
                    "schema.duplicate-key",
                    f"'{item.key_text}' should appear only once here",
                    item,
                )
            self._value(item, fld.value, fld.push_scope or frame.scope, None)
            return
        if frame.rule is not None:
            for pattern in frame.rule.patterns:
                if self._pattern_matches(item.key_text, pattern.key):
                    self._value(
                        item, pattern.field.value, pattern.field.push_scope or frame.scope, None
                    )
                    return
        if other in ("trigger", "effect"):
            self._command(item, Context(other), frame.scope)
        elif other == "modifier":
            spec = self.schema.modifiers.get(key)
            if spec is None:
                self._report(
                    Severity.WARNING,
                    "schema.unknown-key",
                    f"unknown modifier '{item.key_text}'",
                    item,
                )
            else:
                self._value(item, spec, frame.scope, None)
        elif other == "warn":
            where = frame.rule.name if frame.rule is not None else "this block"
            self._report(
                Severity.WARNING,
                "schema.unknown-key",
                f"unknown key '{item.key_text}' in {where}",
                item,
            )

    def _command(self, item: Assignment, context: Context, scope: str | None) -> None:
        key = item.key_text.lower()
        alternatives = self.schema.command(context, key)
        if not alternatives:
            raw = item.key_text
            if key in ("this", "from") and isinstance(item.value, Block):
                self._push_block(item.value, item, None, context=context)
                return
            for dyn in self.schema.dynamic:
                if context in dyn.contexts and self._dynamic_matches(raw, dyn.key):
                    scope_inside = dyn.push_scope or scope
                    if dyn.value is None:
                        if isinstance(item.value, Block):
                            self._push_block(item.value, item, scope_inside, context=context)
                            return
                        continue
                    self._value(item, dyn.value, scope_inside, context)
                    return
            other = Context.EFFECT if context is Context.TRIGGER else Context.TRIGGER
            if self.schema.command(other, key):
                self._report(
                    Severity.ERROR,
                    "schema.wrong-context",
                    f"'{item.key_text}' is {'an' if other is Context.EFFECT else 'a'} "
                    f"{other.value}, not allowed in a {context.value} block",
                    item,
                )
            else:
                self._report(
                    Severity.WARNING,
                    "schema.unknown-key",
                    f"unknown {context.value} '{item.key_text}'",
                    item,
                )
            return
        command = _pick(alternatives, item.value, scope, self.schema)
        if command.scopes and scope is not None and scope not in command.scopes:
            self._report(
                Severity.WARNING,
                "schema.wrong-scope",
                f"'{item.key_text}' works in {'/'.join(command.scopes)} scope, not in {scope}",
                item,
            )
        self._value(item, command.value, self.schema.pushed(command, scope), context)

    # -- values -----------------------------------------------------------------
    def _value(
        self, item: Assignment, spec: ValueSpec, scope: str | None, context: Context | None
    ) -> None:
        value = item.value
        if value is None:
            return  # syntax error, reported by the parser
        if isinstance(spec, OneOf):
            spec = _choose(spec, value, self.schema)
        if isinstance(spec, TypeSpec):
            if isinstance(value, Block):
                if spec.name != "any":
                    self._report(
                        Severity.ERROR,
                        "schema.wrong-value",
                        f"'{item.key_text}' expects {spec}, not a block",
                        item,
                    )
                return
            problem = check_scalar(value.value, spec, self.schema)
            if problem:
                self._report(
                    Severity.ERROR,
                    "schema.wrong-value",
                    f"'{item.key_text}' expects {problem}, got '{value.text}'",
                    value,
                )
            elif spec.name == "ref" and spec.arg and self.names is not None:
                self._check_name(spec.arg, value)
            return
        if not isinstance(value, Block):
            self._report(
                Severity.ERROR,
                "schema.wrong-value",
                f"'{item.key_text}' expects a block {{ ... }}, got '{value.text}'",
                value,
            )
            return
        if isinstance(spec, BlockSpec):
            block_context = spec.context or context or Context.TRIGGER
            self._push_block(value, item, scope, context=block_context)
        elif isinstance(spec, RuleSpec):
            self._stack.append(
                _Frame(value.items, item.key, scope, rule=self.schema.rules[spec.rule])
            )
        elif isinstance(spec, FieldsSpec):
            self._stack.append(_Frame(value.items, item.key, scope, fields=spec))
        elif isinstance(spec, ListSpec):
            self._stack.append(_Frame(value.items, item.key, scope, list_spec=spec))
            n = sum(1 for i in value.items if isinstance(i, Scalar))
            if (spec.min_items is not None and n < spec.min_items) or (
                spec.max_items is not None and n > spec.max_items
            ):
                self._report(
                    Severity.ERROR,
                    "schema.wrong-value",
                    f"'{item.key_text}' expects {spec.min_items}-{spec.max_items} values, got {n}",
                    item,
                )

    def _pattern_matches(self, key: str, pattern: str) -> bool:
        if pattern.startswith("ref:"):
            if self.names is None:
                return True
            found = self.names(pattern[4:], key)
            return True if found is None else found
        return _key_matches(key, pattern)

    def _check_name(self, registry: str, value: Scalar) -> None:
        name = value.value
        if name.lower() in SCOPE_KEYWORDS or self.names is None:
            return
        if self.names(registry, name) is False:
            self._report(
                Severity.WARNING,
                "ref.unknown-name",
                f"unknown {registry.replace('_', ' ')} '{name}'",
                value,
            )

    def _dynamic_matches(self, raw: str, key: str) -> bool:
        if key == "int":
            return bool(_INT_KEY.fullmatch(raw))
        if key == "tag":
            if self.names is not None:
                found = self.names("country", raw)
                if found is not None:
                    return found
            return is_tag(raw) and raw.isupper()
        if key.startswith("ref:") and self.names is not None:
            return bool(self.names(key[4:], raw))
        return False

    def _push_block(
        self, block: Block, item: Assignment, scope: str | None, *, context: Context
    ) -> None:
        self._stack.append(_Frame(block.items, item.key, scope, context=context))


def _key_matches(key: str, pattern: str) -> bool:
    if pattern == "any":
        return True
    if pattern == "int":
        return bool(_INT_KEY.fullmatch(key))
    if pattern == "date":
        return bool(_DATE_KEY.fullmatch(key))
    if pattern == "float":
        return bool(_FLOAT_KEY.fullmatch(key))
    if pattern == "tag":
        return is_tag(key)
    return pattern.startswith("ref:")  # names checked in Phase 3


def _is_block_spec(spec: ValueSpec) -> bool:
    return not isinstance(spec, TypeSpec) or spec.name == "any"


def _pick(
    alternatives: list[Command], value: Node | None, scope: str | None, schema: Schema
) -> Command:
    """Choose the command alternative that fits the value and the current scope.

    Preference: right kind of value (scalar / block), then valid in the current
    scope, then a scalar value that passes the type check.
    """
    if len(alternatives) == 1:
        return alternatives[0]
    want_block = isinstance(value, Block)

    def score(c: Command) -> int:
        points = 0
        if _is_block_spec(c.value) == want_block or isinstance(c.value, OneOf):
            points += 4
        if not c.scopes or scope is None or scope in c.scopes:
            points += 2
        if (
            isinstance(value, Scalar)
            and isinstance(c.value, TypeSpec)
            and check_scalar(value.value, c.value, schema) is None
        ):
            points += 1
        return points

    return max(alternatives, key=score)


def _choose(spec: OneOf, value: Node, schema: Schema) -> ValueSpec:
    """Choose the option of a `OneOf` that fits the value best."""
    if isinstance(value, Scalar):
        scalar_options = [o for o in spec.options if isinstance(o, TypeSpec)]
        for t in scalar_options:
            if check_scalar(value.value, t, schema) is None:
                return t
        return scalar_options[0] if scalar_options else spec.options[0]
    assert isinstance(value, Block)
    keys = {i.key_text.lower() for i in value.items if isinstance(i, Assignment)}
    best: ValueSpec | None = None
    best_score = -1
    for o in spec.options:
        if not _is_block_spec(o):
            continue
        if isinstance(o, FieldsSpec):
            score = len(keys & set(o.fields)) * 2 - len(keys - set(o.fields))
        elif isinstance(o, ListSpec):
            score = 0 if keys else 1
        else:
            score = 0
        if score > best_score:
            best, best_score = o, score
    return best if best is not None else spec.options[0]
