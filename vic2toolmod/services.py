"""Language services for editors: completion, hover, go to definition, usages, rename.

All functions take a position as a character offset into the file's current
text (the editor buffer if one was set in the `Workspace`). They work on
half-written files too, because the parser never gives up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from vic2toolmod.edit import TextEdit
from vic2toolmod.project.registries import Definition
from vic2toolmod.schema.model import (
    BlockSpec,
    Context,
    FieldsSpec,
    ListSpec,
    OneOf,
    RuleSpec,
    TypeSpec,
    ValueSpec,
)
from vic2toolmod.schema.reference import command_hover
from vic2toolmod.schema.validator import Validator, ValueInfo, _Frame, file_type_for
from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar
from vic2toolmod.script.tokens import Token
from vic2toolmod.workspace import Usage, Workspace

_WORD = re.compile(r"[A-Za-z0-9_.\-@]*$")
MAX_NAMES = 300


@dataclass(frozen=True)
class Completion:
    """One completion suggestion.

    Attributes:
        label: Text to insert.
        kind: ``field``, ``trigger``, ``effect``, ``scope``, ``modifier``, ``name``, ``value``.
        detail: Short extra information (scopes, registry, file).
        doc: Longer description.
    """

    label: str
    kind: str
    detail: str = ""
    doc: str = ""


@dataclass(frozen=True)
class Hover:
    """Information about the thing under the cursor.

    Attributes:
        text: Markdown text.
        start: Start offset of the thing.
        end: End offset.
        sprite: For icon numbers (T003): the sprite and the frame (from 1) to show.
        picture: For picture names (T006): relative path of the picture file.
    """

    text: str
    start: int
    end: int
    sprite: tuple[str, int] | None = None
    picture: str | None = None


@dataclass(frozen=True)
class _Place:
    """Where an offset is: in which block, on which assignment and in which part."""

    path: tuple[Node, ...]  # Document, ..., innermost container
    assignment: Assignment | None
    part: str  # "key", "value" or "free" (between items of the innermost container)
    token: Token | None


def _locate(doc: Document, offset: int) -> _Place:
    path: list[Node] = [doc]
    items = doc.items
    while True:
        for item in items:
            if not (item.start <= offset <= item.end):
                continue
            if isinstance(item, Assignment):
                if item.key.start <= offset <= item.key.end:
                    return _Place(tuple(path), item, "key", item.key)
                v = item.value
                if isinstance(v, Block):
                    close = v.rbrace.start if v.rbrace else len(doc.text)
                    if v.lbrace.end <= offset <= close:
                        path.append(v)
                        items = v.items
                        break
                    return _Place(tuple(path), item, "value", v.lbrace)
                tok = v.token if isinstance(v, Scalar) else None
                return _Place(tuple(path), item, "value", tok)
            if isinstance(item, Block):
                close = item.rbrace.start if item.rbrace else len(doc.text)
                if item.lbrace.end <= offset <= close:
                    path.append(item)
                    items = item.items
                    break
            if isinstance(item, Scalar):
                return _Place(tuple(path), None, "free", item.token)
        else:
            # Not inside any item: maybe right after "key =" with no value yet.
            pending = [
                i
                for i in items
                if isinstance(i, Assignment) and i.value is None and i.operator.end <= offset
            ]
            if pending and not doc.text[pending[-1].operator.end : offset].strip():
                return _Place(tuple(path), pending[-1], "value", None)
            return _Place(tuple(path), None, "free", None)


class LanguageService:
    """Completion, hover, definition, usages and rename for one `Workspace`."""

    def __init__(self, workspace: Workspace) -> None:
        self.ws = workspace

    # -- analysis ------------------------------------------------------------
    def _analyse(self, rel: str) -> tuple[Document, Validator]:
        doc = self.ws.document(rel)
        reg = self.ws.registries()
        validator = Validator(self.ws.schema, reg.has, reg.frames)
        f = self.ws.file(rel)
        ft = file_type_for(f.rel if f else rel, self.ws.schema)
        if ft is not None:
            validator.validate(doc, ft.rule, ft.scope)
        return doc, validator

    # -- completion ----------------------------------------------------------
    def complete(self, rel: str, offset: int) -> list[Completion]:
        """Suggestions for the position (keys in blocks, values after ``=``)."""
        doc, v = self._analyse(rel)
        place = _locate(doc, offset)
        prefix = _WORD.search(doc.text, 0, offset).group()  # type: ignore[union-attr]
        if place.part == "value" and place.assignment is not None:
            info = v.value_info.get(id(place.assignment))
            out = self._value_completions(info.spec, info.scope) if info else []
        else:
            frame = v.block_info.get(id(place.path[-1]))
            out = self._key_completions(frame, place.path[-1]) if frame else []
        low = prefix.lower()
        seen: set[str] = set()
        result = []
        for c in out:
            if c.label.lower().startswith(low) and c.label.lower() not in seen:
                seen.add(c.label.lower())
                result.append(c)
        return result

    def _key_completions(self, frame: _Frame, container: Node) -> list[Completion]:
        out: list[Completion] = []
        present = {
            i.key_text.lower() for i in getattr(container, "items", []) if isinstance(i, Assignment)
        }
        fields = frame.rule.fields if frame.rule else frame.fields.fields if frame.fields else {}
        for key, fld in sorted(fields.items()):
            if fld.multiple or key not in present:
                kind = "field (required)" if fld.required else "field"
                out.append(Completion(key, kind, str(_short(fld.value)), fld.doc))
        if frame.rule:
            for pattern in frame.rule.patterns:
                if pattern.key.startswith("ref:"):
                    out += self._names(pattern.key[4:])
        other = frame.rule.other if frame.rule else frame.fields.other if frame.fields else "warn"
        context = frame.context or (Context(other) if other in ("trigger", "effect") else None)
        if context is not None:
            out += self._commands(context, frame.scope)
        if other == "modifier":
            out += [
                Completion(m, "modifier", str(t), self.ws.schema.modifier_docs.get(m, ""))
                for m, t in sorted(self.ws.schema.modifiers.items())
            ]
        return out

    def _commands(self, context: Context, scope: str | None) -> list[Completion]:
        out = []
        for (ctx, name), alts in sorted(self.ws.schema.commands.items()):
            if ctx is not context:
                continue
            c = alts[0]
            ok = [a for a in alts if not a.scopes or scope is None or scope in a.scopes]
            if not ok:
                continue
            kind = "scope" if c.push_scope else context.value
            scopes = "/".join(sorted({s for a in alts for s in a.scopes})) or "any scope"
            out.append(Completion(name, kind, scopes, command_hover(ok[0], self.ws.schema)))
        return out

    def _names(self, registry: str, limit: int = MAX_NAMES) -> list[Completion]:
        names = self.ws.registries().names.get(registry, {})
        out = []
        for d in list(names.values())[:limit]:
            out.append(Completion(d.name, "name", registry, f"{d.file}:{d.line}"))
        return out

    def _value_completions(self, spec: ValueSpec, scope: str | None) -> list[Completion]:
        if isinstance(spec, OneOf):
            return [c for o in spec.options for c in self._value_completions(o, scope)]
        if isinstance(spec, TypeSpec):
            if spec.name == "bool":
                return [Completion("yes", "value"), Completion("no", "value")]
            if spec.name == "enum":
                return [
                    Completion(x, "value")
                    for x in sorted(self.ws.schema.enums.get(spec.arg or "", ()))
                ]
            if spec.name == "ref" and spec.arg:
                extra = []
                if spec.arg in ("country", "province"):
                    extra = [
                        Completion(k.upper(), "value", "scope keyword") for k in ("this", "from")
                    ]
                return extra + self._names(spec.arg)
            if spec.name == "localisation":
                return self._names("localisation")
            return []
        if isinstance(spec, (BlockSpec, FieldsSpec, RuleSpec, ListSpec)):
            return [Completion("{ }", "value", "block")]
        return []

    # -- hover / definition ----------------------------------------------------
    def _reference_at(self, rel: str, offset: int) -> tuple[str, str, Token] | None:
        doc, v = self._analyse(rel)
        for registry, name, tok in v.references:
            if tok.start <= offset <= tok.end:
                return registry, name, tok
        return None

    def definition(self, rel: str, offset: int) -> Definition | None:
        """Where the name under the cursor is defined."""
        ref = self._reference_at(rel, offset)
        if ref is None:
            return None
        return self.ws.definition(ref[0], ref[1])

    def hover(self, rel: str, offset: int) -> Hover | None:
        """Description of the key or name under the cursor."""
        doc, v = self._analyse(rel)
        place = _locate(doc, offset)
        ref = next(((r, n, t) for r, n, t in v.references if t.start <= offset <= t.end), None)
        if ref is not None:
            registry, name, tok = ref
            d = self.ws.definition(registry, name)
            lines = [f"**{name}** ({registry.replace('_', ' ')})"]
            loc = self.ws.registries().localisation
            entry = loc.get(name) if loc else None
            if entry is not None and entry.text():
                lines.append(f"“{entry.text()}”")
            if registry == "province":  # K98 C: the province's name and owner
                lines[1:] = self._province_lines(name)
            lines.append(f"defined in `{d.file}:{d.line}`" if d else "**not defined anywhere**")
            return Hover("\n\n".join(lines), tok.start, tok.end)
        if place.part == "value" and place.assignment is not None:
            icon = self._icon(v, place.assignment)
            if icon is not None:
                value = place.assignment.value
                assert value is not None
                text = f"icon {value.to_text().strip()}: frame {icon[1]} of `{icon[0]}`"
                return Hover(text, value.start, value.end, icon)
            picture = self._picture(v, place.assignment)
            if picture is not None:
                value = place.assignment.value
                assert value is not None
                return Hover(f"`{picture}`", value.start, value.end, picture=picture)
        if place.part == "key" and place.assignment is not None:
            key = place.assignment.key
            if key.text.isdigit() and self.ws.registries().has("province", key.text):
                text = "\n\n".join([f"**{key.text}** (province)", *self._province_lines(key.text)])
                return Hover(text, key.start, key.end)
            info = v.value_info.get(id(place.assignment))
            if info is None:
                flagged = any(d.start == key.start for d in v.diagnostics_found)
                text = (
                    f"**{key.text}** - unknown here"
                    if flagged
                    else f"**{key.text}** - not described in the schema yet (accepted unchecked)"
                )
                return Hover(text, key.start, key.end)
            parts = [f"**{key.text}**"]
            if info.command is not None:
                # T006: description, value in words, check, example, syntax
                text = command_hover(info.command, self.ws.schema)
                return Hover(text, key.start, key.end)
            if info.modifier:
                low = key.text.lower()
                source = self.ws.schema.modifier_sources.get(low, "")
                parts.append(
                    f"modifier; value: `{_short(info.spec)}`"
                    + (f"; source: {source}" if source else "")
                )
            else:
                parts.append(f"value: `{_short(info.spec)}`")
            if info.doc:
                parts.append(info.doc)
            return Hover("\n\n".join(parts), key.start, key.end, self._icon(v, place.assignment))
        return None

    def _province_lines(self, pid: str) -> list[str]:
        """Name (``PROV<id>``) and owner / controller / cores of a province's history file."""
        lines: list[str] = []
        loc = self.ws.registries().localisation
        entry = loc.get(f"PROV{pid}") if loc else None
        if entry is not None and entry.text():
            lines.append(f"“{entry.text()}”")
        prefix = "history/provinces/"
        for low, f in self.ws.project.files().items():
            rest = low[len(prefix) :].split("/", 1)
            if (
                low.startswith(prefix)
                and len(rest) == 2
                and rest[1].split(" ")[0].split(".")[0] == pid
            ):
                doc = self.ws.document(f.rel)
                facts = {}
                cores = []
                for a in doc.assignments():
                    k = a.key_text.lower()
                    if k == "add_core" and a.value is not None:
                        cores.append(a.value.to_text().strip())
                    elif k in ("owner", "controller") and a.value is not None:
                        facts[k] = a.value.to_text().strip()
                if facts.get("owner"):
                    lines.append(
                        f"owner {facts['owner']}"
                        + (
                            f", controller {facts['controller']}"
                            if facts.get("controller", facts["owner"]) != facts["owner"]
                            else ""
                        )
                        + (f"; cores {' '.join(cores)}" if cores else "")
                        + " (history, at the start)"
                    )
                lines.append(f"history: `{f.rel}`")
                break
        return lines

    def _icon(self, v: Validator, a: Assignment) -> tuple[str, int] | None:
        """``(sprite, frame from 1)`` when the assignment is a valid icon number."""
        info = v.value_info.get(id(a))
        if info is None or not info.sprite or a.value is None or isinstance(a.value, Block):
            return None
        try:
            n = int(a.value.value)
        except ValueError:
            return None
        frames = self.ws.registries().frames(info.sprite)
        frame = n - info.sprite_from + 1
        if frames is None or not 1 <= frame <= frames:
            return None
        return info.sprite, frame

    def _picture(self, v: Validator, a: Assignment) -> str | None:
        """Relative path of the picture file a picture name names, if it exists."""
        info = v.value_info.get(id(a))
        if info is None or not info.picture or a.value is None or isinstance(a.value, Block):
            return None
        d = self.ws.registries().get("picture", f"{info.picture}/{a.value.value.strip()}")
        return d.file if d is not None else None

    # -- usages / rename ---------------------------------------------------------
    def references(self, rel: str, offset: int) -> list[Usage]:
        """Every place where the name under the cursor is used."""
        ref = self._reference_at(rel, offset)
        return self.ws.usages(ref[0], ref[1]) if ref else []

    def rename(self, rel: str, offset: int, new_name: str) -> dict[str, list[TextEdit]]:
        """Edits that rename the name under the cursor everywhere (usages + definition).

        Returns:
            Relative path -> edits for that file (script and localisation files).
        """
        ref = self._reference_at(rel, offset)
        if ref is None:
            return {}
        registry, name, _ = ref
        edits: dict[str, list[TextEdit]] = {}
        for u in self.ws.usages(registry, name):
            edits.setdefault(u.file, []).append(TextEdit(u.start, u.end, new_name))
        d = self.ws.definition(registry, name)
        if d is not None and d.file.lower().endswith((".txt", ".gfx", ".gui")):
            ddoc = self.ws.document(d.file)
            start = ddoc.lines.line_start(d.line)
            end = ddoc.lines.line_start(d.line + 1)
            for tok in ddoc.tokens():
                if start <= tok.start < end and tok.value.lower() == name.lower():
                    e = TextEdit(tok.start, tok.end, new_name)
                    if e not in edits.get(d.file, []):
                        edits.setdefault(d.file, []).append(e)
                    break
        return edits


def _short(spec: ValueSpec) -> str:
    if isinstance(spec, TypeSpec):
        return str(spec)
    if isinstance(spec, BlockSpec):
        return f"{{ {spec.context.value if spec.context else 'same'} }}"
    if isinstance(spec, RuleSpec):
        return f"{{ {spec.rule} }}"
    if isinstance(spec, FieldsSpec):
        return "{ " + " ".join(spec.fields) + " }"
    if isinstance(spec, ListSpec):
        return f"{{ {spec.item} ... }}"
    return " | ".join(_short(o) for o in spec.options)


__all__ = ["Completion", "Hover", "LanguageService", "ValueInfo"]
