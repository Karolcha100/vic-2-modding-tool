"""Load the YAML schema files into a `Schema` and check them for consistency."""

from __future__ import annotations

import dataclasses
import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from vic2toolmod.schema.model import (
    SCOPES,
    SIMPLE_TYPES,
    BlockSpec,
    Command,
    Context,
    DynamicKey,
    Field,
    FieldsSpec,
    FileType,
    ListSpec,
    OneOf,
    Pattern,
    Rule,
    RuleSpec,
    Schema,
    TypeSpec,
    ValueSpec,
)

DATA_DIR = Path(__file__).parent / "data"
"""Folder with the schema shipped with the package."""

_TYPE_RE = re.compile(
    r"^(?P<name>[a-z_]+)(?::(?P<arg>[a-z0-9_.]+))?"
    r"(?:\[(?P<lo>-?[\d.]*)\.\.(?P<hi>-?[\d.]*)\])?$"
)
_FIELD_PROPS = {"required", "multiple", "push_scope", "doc", "sprite", "sprite_from"}
_SPEC_KEYS = {"block", "fields", "rule", "list", "one_of", "value"}
_OTHER = {"warn", "trigger", "effect", "modifier", "any"}
_PATTERN_KEYS = {"int", "date", "tag", "any", "float"}


class SchemaError(ValueError):
    """The schema files are inconsistent; ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid schema:\n  " + "\n  ".join(problems))
        self.problems = problems


def parse_type(text: str) -> TypeSpec:
    """Parse a type expression such as ``int``, ``int[0..3]``, ``enum:strata``.

    Raises:
        ValueError: If the expression is malformed.
    """
    m = _TYPE_RE.match(text.strip())
    if not m:
        raise ValueError(f"bad type expression {text!r}")
    lo, hi = m["lo"], m["hi"]
    return TypeSpec(
        name=m["name"],
        arg=m["arg"],
        minimum=float(lo) if lo else None,
        maximum=float(hi) if hi else None,
    )


class _Builder:
    def __init__(self) -> None:
        self.schema = Schema()
        self.problems: list[str] = []
        self.where = ""
        self.docs: dict[str, dict[Context, str]] = {}

    def fail(self, message: str) -> None:
        self.problems.append(f"{self.where}: {message}")

    # -- value specifications -------------------------------------------------
    def spec(self, raw: Any) -> ValueSpec:
        if isinstance(raw, str):
            try:
                return parse_type(raw)
            except ValueError as exc:
                self.fail(str(exc))
                return TypeSpec("any")
        if isinstance(raw, list):
            return OneOf(tuple(self.spec(r) for r in raw))
        if not isinstance(raw, dict):
            self.fail(f"bad value specification {raw!r}")
            return TypeSpec("any")
        if "value" in raw:
            return self.spec(raw["value"])
        if "one_of" in raw:
            return OneOf(tuple(self.spec(r) for r in raw["one_of"]))
        if "block" in raw:
            if raw["block"] == "same":
                return BlockSpec(None)
            try:
                return BlockSpec(Context(raw["block"]))
            except ValueError:
                self.fail(f"unknown block context {raw['block']!r}")
                return TypeSpec("any")
        if "rule" in raw:
            return RuleSpec(str(raw["rule"]))
        if "list" in raw:
            item = self.spec(raw["list"])
            if not isinstance(item, TypeSpec):
                self.fail("list items must be a simple type")
                item = TypeSpec("any")
            return ListSpec(item, raw.get("min"), raw.get("max"))
        if "fields" in raw:
            fields = {str(k).lower(): self.field(v) for k, v in (raw["fields"] or {}).items()}
            other = raw.get("other", "warn")
            if other not in _OTHER:
                self.fail(f"bad 'other' {other!r}")
            return FieldsSpec(fields, other)
        self.fail(f"bad value specification {raw!r}")
        return TypeSpec("any")

    def field(self, raw: Any) -> Field:
        if isinstance(raw, dict) and (set(raw) & _FIELD_PROPS):
            unknown = set(raw) - _FIELD_PROPS - _SPEC_KEYS - {"other", "min", "max"}
            if unknown:
                self.fail(f"unknown field properties {sorted(unknown)}")
            spec_raw = {k: v for k, v in raw.items() if k not in _FIELD_PROPS}
            push = raw.get("push_scope")
            if push is not None and push not in SCOPES:
                self.fail(f"bad push_scope {push!r}")
            return Field(
                value=self.spec(spec_raw) if spec_raw else TypeSpec("any"),
                required=bool(raw.get("required", False)),
                multiple=bool(raw.get("multiple", False)),
                push_scope=push,
                doc=str(raw.get("doc", "")),
                sprite=str(raw.get("sprite", "")),
                sprite_from=int(raw.get("sprite_from", 1)),
            )
        return Field(value=self.spec(raw))

    # -- files -------------------------------------------------------------
    def add_commands(self, data: dict[str, Any]) -> None:
        for raw in data.pop("dynamic", None) or []:
            self.add_dynamic(raw)
        for name, hint in (data.pop("not_in_game", None) or {}).items():
            self.schema.not_in_game[str(name).lower()] = str(hint or "")
        for name, doc in (data.pop("docs", None) or {}).items():
            if isinstance(doc, dict):
                bad = set(doc) - {"trigger", "effect"}
                if bad:
                    self.fail(
                        f"docs of {name!r}: unknown keys {sorted(bad)} (use trigger / effect)"
                    )
                self.docs[str(name).lower()] = {Context(k): str(v) for k, v in doc.items()}
            else:
                self.docs[str(name).lower()] = {
                    Context.TRIGGER: str(doc),
                    Context.EFFECT: str(doc),
                }
        for section, entries in data.items():
            if section not in ("trigger", "effect", "both"):
                self.fail(f"unknown section {section!r} (use trigger / effect / both)")
                continue
            contexts = (
                [Context.TRIGGER, Context.EFFECT] if section == "both" else [Context(section)]
            )
            for name, raw in (entries or {}).items():
                alternatives = raw if isinstance(raw, list) else [raw]
                for alt in alternatives:
                    for context in contexts:
                        self.add_command(str(name), context, alt)

    def apply_docs(self) -> None:
        """Give the descriptions of ``docs`` sections to commands without their own."""
        for name, by_context in self.docs.items():
            found = False
            for context, doc in by_context.items():
                alts = self.schema.commands.get((context, name))
                if not alts:
                    continue
                found = True
                self.schema.commands[(context, name)] = [
                    a if a.doc else dataclasses.replace(a, doc=doc) for a in alts
                ]
            if not found:
                self.fail(f"docs for unknown command {name!r}")

    def add_dynamic(self, raw: dict[str, Any]) -> None:
        key = str(raw.get("key", ""))
        if key not in ("tag", "int") and not key.startswith("ref:"):
            self.fail(f"bad dynamic key {key!r}")
        contexts = raw.get("contexts", ["trigger", "effect"])
        push = raw.get("push_scope")
        if push is not None and push not in SCOPES:
            self.fail(f"bad push_scope {push!r}")
        self.schema.dynamic.append(
            DynamicKey(
                key=key,
                contexts=tuple(Context(c) for c in contexts),
                push_scope=push,
                value=self.spec(raw["value"]) if "value" in raw else None,
                doc=str(raw.get("doc", "")),
            )
        )

    def add_command(self, name: str, context: Context, raw: Any) -> None:
        old_where = self.where
        self.where = f"{old_where}: {name}"
        if not isinstance(raw, dict):
            raw = {"value": raw}
        scopes = raw.get("scopes", ["any"])
        if isinstance(scopes, str):
            scopes = [scopes]
        for s in scopes:
            if s != "any" and s not in SCOPES:
                self.fail(f"bad scope {s!r}")
        push = raw.get("push_scope")
        if isinstance(push, dict):
            for a, b in push.items():
                if a not in SCOPES or b not in SCOPES:
                    self.fail(f"bad push_scope mapping {a!r}: {b!r}")
            push = {str(a): str(b) for a, b in push.items()}
        elif push is not None and push not in (*SCOPES, "any"):
            self.fail(f"bad push_scope {push!r}")
        extra = [*raw.get("vanilla_scopes", []), *raw.get("game_scopes", [])]
        for s_ in extra:
            if s_ not in SCOPES:
                self.fail(f"bad vanilla / game scope {s_!r}")
        if "any" not in scopes:
            scopes = [*scopes, *(s_ for s_ in extra if s_ not in scopes)]
        known = {
            "value",
            "scopes",
            "vanilla_scopes",
            "game_scopes",
            "push_scope",
            "compare",
            "doc",
            "source",
        }
        if set(raw) - known:
            self.fail(f"unknown command properties {sorted(set(raw) - known)}")
        command = Command(
            name=name.lower(),
            context=context,
            scopes=tuple(s for s in scopes if s != "any"),
            value=self.spec(raw.get("value", "any")),
            push_scope=None if push in (None, "any") else push,
            compare=raw.get("compare"),
            doc=str(raw.get("doc", "")),
            source=str(raw.get("source", "manual")),
        )
        self.schema.commands.setdefault((context, command.name), []).append(command)
        self.where = old_where

    def add_rules(self, data: dict[str, Any]) -> None:
        for name, raw in (data.get("rules") or {}).items():
            self.where = f"{self.where.split(':')[0]}: rule {name}"
            raw = raw or {}
            other = raw.get("other", "warn")
            if other not in _OTHER:
                self.fail(f"bad 'other' {other!r}")
            patterns = []
            for p in raw.get("patterns") or []:
                key = str(p.get("key", ""))
                if key not in _PATTERN_KEYS and not key.startswith("ref:"):
                    self.fail(f"bad pattern key {key!r}")
                patterns.append(
                    Pattern(key, self.field({k: v for k, v in p.items() if k != "key"}))
                )
            values = raw.get("values")
            if name in self.schema.rules:
                self.fail("rule defined twice")
            self.schema.rules[str(name)] = Rule(
                name=str(name),
                fields={
                    str(k).lower(): self.field(v) for k, v in (raw.get("fields") or {}).items()
                },
                patterns=tuple(patterns),
                other=other,
                values=parse_type(values) if isinstance(values, str) else None,
                doc=str(raw.get("doc", "")),
            )
        for name, raw in (data.get("file_types") or {}).items():
            paths = raw.get("paths", [])
            if isinstance(paths, str):
                paths = [paths]
            scope = raw.get("scope")
            if scope is not None and scope not in SCOPES:
                self.where = f"file type {name}"
                self.fail(f"bad scope {scope!r}")
            self.schema.file_types.append(
                FileType(str(name), tuple(paths), str(raw.get("rule", name)), scope)
            )

    # -- consistency -------------------------------------------------------
    def check(self) -> None:
        s = self.schema
        self.where = "check"

        def walk(spec: ValueSpec, where: str) -> None:
            if isinstance(spec, TypeSpec):
                if spec.name == "enum" and spec.arg not in s.enums:
                    self.problems.append(f"{where}: unknown enum {spec.arg!r}")
                elif spec.name not in SIMPLE_TYPES | {"enum", "ref"}:
                    self.problems.append(f"{where}: unknown type {spec.name!r}")
            elif isinstance(spec, RuleSpec):
                if spec.rule not in s.rules:
                    self.problems.append(f"{where}: unknown rule {spec.rule!r}")
            elif isinstance(spec, FieldsSpec):
                for k, f in spec.fields.items():
                    walk(f.value, f"{where}.{k}")
            elif isinstance(spec, OneOf):
                for o in spec.options:
                    walk(o, where)
            elif isinstance(spec, ListSpec):
                walk(spec.item, where)

        for (_, name), alts in s.commands.items():
            for c in alts:
                walk(c.value, f"command {name}")
        for rule in s.rules.values():
            for k, f in rule.fields.items():
                walk(f.value, f"rule {rule.name}.{k}")
            for p in rule.patterns:
                walk(p.field.value, f"rule {rule.name}.<{p.key}>")
        for ft in s.file_types:
            if ft.rule not in s.rules:
                self.problems.append(f"file type {ft.name}: unknown rule {ft.rule!r}")


def load_schema(directory: Path = DATA_DIR) -> Schema:
    """Load every ``*.yaml`` file of a schema folder.

    Layout: ``enums.yaml``, ``modifiers.yaml``, ``commands/*.yaml`` (sections
    ``trigger``, ``effect``, ``both``) and ``files/*.yaml`` (``file_types`` and
    ``rules``).

    Raises:
        SchemaError: If anything is inconsistent (all problems are listed).
    """
    b = _Builder()

    def read(path: Path) -> dict[str, Any]:
        b.where = str(path.relative_to(directory))
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            b.fail("top level must be a mapping")
            return {}
        return data

    enums = directory / "enums.yaml"
    if enums.is_file():
        for name, values in (read(enums).get("enums") or {}).items():
            b.schema.enums[str(name)] = frozenset(str(v).lower() for v in values)
    modifiers = directory / "modifiers.yaml"
    if modifiers.is_file():
        for name, raw in (read(modifiers).get("modifiers") or {}).items():
            low = str(name).lower()
            if isinstance(raw, dict):
                if raw.get("doc"):
                    b.schema.modifier_docs[low] = str(raw["doc"])
                b.schema.modifier_sources[low] = str(raw.get("source", "cwtools"))
                raw = raw.get("value", "float")
            else:
                b.schema.modifier_sources[low] = "cwtools"
            spec = b.spec(raw if raw is not None else "float")
            b.schema.modifiers[low] = spec if isinstance(spec, TypeSpec) else TypeSpec("float")
    for path in sorted((directory / "commands").glob("*.yaml")):
        b.add_commands(read(path))
    for path in sorted((directory / "files").glob("*.yaml")):
        b.add_rules(read(path))
    b.where = "commands: docs"
    b.apply_docs()
    b.check()
    if b.problems:
        raise SchemaError(b.problems)
    return b.schema


@cache
def default_schema() -> Schema:
    """The schema shipped with the package (loaded once)."""
    return load_schema()
