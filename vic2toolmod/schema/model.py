"""In-memory form of the schema (see ``docs/schema.md`` for the YAML format).

Value specifications (`ValueSpec`) say what may stand on the right of ``=``:

* `TypeSpec` - a scalar of a simple type (``bool``, ``int[0..3]``, ``enum:strata``,
  ``ref:country`` …);
* `BlockSpec` - a block of trigger or effect commands (``{block: trigger}``);
* `FieldsSpec` - a block with fixed keys (``{fields: {...}}``);
* `RuleSpec` - a block described by a named structural rule (``{rule: event}``);
* `ListSpec` - a block of loose values (``{list: int}``);
* `OneOf` - any of several specifications (a YAML list).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Context(StrEnum):
    """Kind of a command block."""

    TRIGGER = "trigger"
    EFFECT = "effect"


SCOPES = ("country", "state", "province", "pop")
"""Scope types of Victoria 2. ``any`` in the schema means "every scope"."""

SIMPLE_TYPES = frozenset({"bool", "int", "float", "date", "scalar", "localisation", "color", "any"})
"""Built-in scalar types; see `vic2toolmod.schema.values`."""


@dataclass(frozen=True)
class TypeSpec:
    """A scalar value of a type.

    Attributes:
        name: ``bool``, ``int``, ``float``, ``date``, ``scalar``, ``localisation``,
            ``any``, ``enum`` or ``ref``.
        arg: Enum name for ``enum``, registry name for ``ref``.
        minimum: Lower bound for ``int`` / ``float`` (inclusive).
        maximum: Upper bound for ``int`` / ``float`` (inclusive).
    """

    name: str
    arg: str | None = None
    minimum: float | None = None
    maximum: float | None = None

    def __str__(self) -> str:
        text = f"{self.name}:{self.arg}" if self.arg else self.name
        if self.minimum is not None or self.maximum is not None:
            lo = "" if self.minimum is None else f"{self.minimum:g}"
            hi = "" if self.maximum is None else f"{self.maximum:g}"
            text += f"[{lo}..{hi}]"
        return text


@dataclass(frozen=True)
class BlockSpec:
    """A block of commands (``{block: trigger}``; ``{block: same}`` = the current context)."""

    context: Context | None


@dataclass(frozen=True)
class FieldsSpec:
    """A block with fixed keys.

    Attributes:
        fields: Key (lower case) -> field.
        other: What to do with other keys (see `Rule.other`).
    """

    fields: dict[str, Field]
    other: str = "warn"


@dataclass(frozen=True)
class RuleSpec:
    """A block described by a named `Rule`."""

    rule: str


@dataclass(frozen=True)
class ListSpec:
    """A block of loose values, all of one type (``color = { 1 2 3 }``)."""

    item: TypeSpec
    min_items: int | None = None
    max_items: int | None = None


@dataclass(frozen=True)
class OneOf:
    """Any of several specifications."""

    options: tuple[ValueSpec, ...]


ValueSpec = TypeSpec | BlockSpec | FieldsSpec | RuleSpec | ListSpec | OneOf


@dataclass(frozen=True)
class Field:
    """A key allowed in a structural block.

    Attributes:
        value: What may stand after ``=``.
        required: Whether the key must be present.
        multiple: Whether the key may appear more than once.
        push_scope: Scope inside the value block (``None`` = unchanged).
        doc: Description.
        sprite: For icon numbers: the sprite of ``interface/*.gfx`` they pick a
            frame of (``GFX_crime_strip``).
        sprite_from: The value that shows the sprite's first frame (1 for most
            icons; 0 for crimes, whose first frame is empty).
    """

    value: ValueSpec
    required: bool = False
    multiple: bool = False
    push_scope: str | None = None
    doc: str = ""
    sprite: str = ""
    sprite_from: int = 1


@dataclass(frozen=True)
class Pattern:
    """A dynamic key in a structural block (e.g. any date, any tag, any name).

    Attributes:
        key: ``int``, ``date``, ``tag``, ``any`` or ``ref:NAME``.
        field: What the key's value must be.
    """

    key: str
    field: Field


@dataclass(frozen=True)
class Rule:
    """Structure of a block (a file root, an event, an issue, …).

    Attributes:
        name: Rule name.
        fields: Fixed keys (lower case) -> field.
        patterns: Dynamic keys, tried in order after `fields`.
        other: Keys that match neither: ``warn`` (unknown-key warning),
            ``trigger`` / ``effect`` (treat as commands of that context),
            ``modifier`` (modifier keys), ``any`` (accept silently).
        values: Type of loose values allowed in the block (``None`` = none allowed).
        doc: Description.
    """

    name: str
    fields: dict[str, Field] = field(default_factory=dict)
    patterns: tuple[Pattern, ...] = ()
    other: str = "warn"
    values: TypeSpec | None = None
    doc: str = ""


@dataclass(frozen=True)
class Command:
    """A trigger, an effect or a scope change.

    Attributes:
        name: Command name (lower case).
        context: Where it may be used.
        scopes: Scopes it may be used in; empty = any scope.
        push_scope: Scope inside its block (for scope changes); a mapping
            ``{current scope: new scope}`` when it depends on the current scope.
        value: What may stand after ``=``.
        compare: How a trigger compares its value: ``eq``, ``gte``, ``lte`` or
            ``block`` (for the future trigger tester, K53).
        doc: Description.
        source: Where the entry comes from (``cwtools``, ``author``, ``vanilla``, ``manual``).
    """

    name: str
    context: Context
    scopes: tuple[str, ...]
    value: ValueSpec
    push_scope: str | dict[str, str] | None = None
    compare: str | None = None
    doc: str = ""
    source: str = "manual"


@dataclass(frozen=True)
class FileType:
    """Which files a root rule applies to.

    Attributes:
        name: File type name.
        paths: Glob patterns relative to the game / mod folder (``events/*.txt``).
        rule: Root rule.
        scope: Scope at the file root (``None`` = no scope).
    """

    name: str
    paths: tuple[str, ...]
    rule: str
    scope: str | None = None


@dataclass(frozen=True)
class DynamicKey:
    """A command key that is a name from the mod (``ENG = { }``, ``aristocrats = { }``).

    Attributes:
        key: ``tag``, ``int`` or ``ref:NAME``.
        contexts: Contexts where it applies.
        push_scope: Scope inside the block (``None`` = unchanged).
        value: Value specification; a same-context block when ``None``.
        doc: Description.
    """

    key: str
    contexts: tuple[Context, ...]
    push_scope: str | None = None
    value: ValueSpec | None = None
    doc: str = ""


@dataclass
class Schema:
    """The whole schema.

    Attributes:
        commands: ``(context, name) -> list of alternatives`` (usually one).
        modifiers: Modifier key -> value type.
        enums: Enum name -> allowed values (lower case).
        rules: Rule name -> rule.
        file_types: File types in matching order.
        dynamic: Dynamic command keys, tried in order when a key is no command.
        not_in_game: Names the game does not know although mods use them
            (lower case) -> hint (what to use instead).
        modifier_docs: Modifier key -> description.
        modifier_sources: Modifier key -> where the entry comes from.
    """

    commands: dict[tuple[Context, str], list[Command]] = field(default_factory=dict)
    modifiers: dict[str, TypeSpec] = field(default_factory=dict)
    enums: dict[str, frozenset[str]] = field(default_factory=dict)
    rules: dict[str, Rule] = field(default_factory=dict)
    file_types: list[FileType] = field(default_factory=list)
    dynamic: list[DynamicKey] = field(default_factory=list)
    not_in_game: dict[str, str] = field(default_factory=dict)
    modifier_docs: dict[str, str] = field(default_factory=dict)
    modifier_sources: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def pushed(command: Command, scope: str | None) -> str | None:
        """Scope inside a command's block when used in ``scope``."""
        push = command.push_scope
        if isinstance(push, dict):
            return push.get(scope or "", None) if scope else None
        return push or scope

    def command(self, context: Context, name: str) -> list[Command]:
        """Alternatives of a command (empty list if unknown); ``name`` any case."""
        return self.commands.get((context, name.lower()), [])
