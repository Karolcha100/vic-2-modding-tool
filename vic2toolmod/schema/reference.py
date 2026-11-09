"""Readable reference of the commands (T006): syntax, value type, scopes, examples.

One source for two readers: the hover in the editor (`command_hover`) and the
document ``docs/commands.md`` (`commands_markdown`), which is generated::

    python -m vic2toolmod.schema.reference --write

Descriptions come from the schema: ``doc`` (one sentence) and ``details``
(longer text, ``commands/details.yaml``); syntax, value types and examples are
made from the value specifications unless ``details`` gives an example.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from vic2toolmod.schema.model import (
    BlockSpec,
    Command,
    Context,
    DynamicKey,
    FieldsSpec,
    ListSpec,
    RuleSpec,
    Schema,
    TypeSpec,
    ValueSpec,
)

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "commands.md"
"""Where the generated reference is kept in the repository."""

#: Names used in made-up examples (all exist in vanilla).
SAMPLES = {
    "building": "fort",
    "cb_type": "conquest",
    "continent": "europe",
    "country": "ENG",
    "country_flag": "my_country_flag",
    "culture": "british",
    "culture_group": "germanic",
    "event": "10000",
    "global_flag": "my_global_flag",
    "goods": "iron",
    "government": "democracy",
    "ideology": "liberal",
    "invention": "field_fortifications",
    "issue": "slavery",
    "issue_option": "free_trade",
    "leader": "leader_name",
    "localisation": "MY_TEXT_KEY",
    "modifier": "liberal_agitation",
    "national_value": "nv_liberty",
    "pop_type": "craftsmen",
    "province": "300",
    "province_flag": "my_province_flag",
    "region": "ENG_300",
    "religion": "protestant",
    "technology": "flintlock_rifles",
    "terrain": "farmlands",
    "trait": "aggressive",
    "unit": "infantry",
    "variable": "my_variable",
}

#: Readable names of registries (``ref:`` values).
_NOUNS = {
    "country": "a country tag (`ENG`), or `THIS` / `FROM`",
    "province": "a province id (`300`), or `THIS` / `FROM`",
    "event": "an event id",
    "region": "a state (region) name from `map/region.txt`",
    "localisation": "a localisation key",
}

_SCOPE_WORDS = {
    "country": "country",
    "state": "state",
    "province": "province",
    "pop": "pop",
}

_COMPARE = {
    "gte": "true when the game's value is **at least** the given one",
    "lte": "true when the game's value is **at most** the given one",
    "eq": "true when it **equals** the given value",
    "block": "true when the conditions inside hold",
}


# -- value types ------------------------------------------------------------------
def _range(t: TypeSpec) -> str:
    if t.minimum is None and t.maximum is None:
        return ""
    lo = "" if t.minimum is None else f"{t.minimum:g}"
    hi = "" if t.maximum is None else f"{t.maximum:g}"
    if lo and hi:
        return f" from {lo} to {hi}"
    return f" of at least {lo}" if lo else f" of at most {hi}"


def value_words(spec: ValueSpec, schema: Schema) -> str:
    """What may stand after ``=``, in words (Markdown)."""
    if isinstance(spec, TypeSpec):
        name, arg = spec.name, spec.arg or ""
        if name == "bool":
            return "`yes` or `no`"
        if name == "int":
            return "a whole number" + _range(spec)
        if name == "float":
            return "a number" + _range(spec)
        if name == "date":
            return "a date (`1836.1.1`)"
        if name == "scalar":
            return "a name"
        if name == "localisation":
            return "a localisation key"
        if name == "color":
            return "a colour (`{ 255 0 0 }`)"
        if name == "any":
            return "any value"
        if name == "enum":
            values = sorted(schema.enums.get(arg, ()))
            if 0 < len(values) <= 10:
                return "one of " + ", ".join(f"`{v}`" for v in values)
            return f"a value of `{arg}`"
        if name == "ref":
            return _NOUNS.get(arg, f"a {arg.replace('_', ' ')} name")
        return name
    if isinstance(spec, BlockSpec):
        if spec.context is None:
            return "a block of commands (triggers in a trigger, effects in an effect)"
        return f"a block of {spec.context.value}s"
    if isinstance(spec, FieldsSpec):
        keys = ", ".join(f"`{k}`" for k in spec.fields)
        return f"a block with {keys}"
    if isinstance(spec, RuleSpec):
        return f"a block (`{spec.rule}`)"
    if isinstance(spec, ListSpec):
        return f"a block of values ({value_words(spec.item, schema)})"
    return " **or** ".join(value_words(o, schema) for o in spec.options)


def _placeholder(spec: ValueSpec) -> str:
    """Short placeholder for syntax lines: ``<number>``, ``<country>``, ``{ … }``."""
    if isinstance(spec, TypeSpec):
        if spec.name == "bool":
            return "yes|no"
        if spec.name == "float":
            return "<number>"
        if spec.name == "int":
            return "<whole number>"
        if spec.name in ("ref", "enum"):
            return f"<{spec.arg}>"
        if spec.name == "localisation":
            return "<localisation key>"
        if spec.name == "scalar":
            return "<name>"
        return f"<{spec.name}>"
    if isinstance(spec, BlockSpec):
        return "{ " + (f"<{spec.context.value}s>" if spec.context else "<commands>") + " }"
    if isinstance(spec, FieldsSpec):
        return (
            "{ " + " ".join(f"{k} = {_placeholder(f.value)}" for k, f in spec.fields.items()) + " }"
        )
    if isinstance(spec, RuleSpec):
        return "{ … }"
    if isinstance(spec, ListSpec):
        return "{ " + _placeholder(spec.item) + " … }"
    return " | ".join(_placeholder(o) for o in spec.options)


def sample(spec: ValueSpec, schema: Schema, key: str = "") -> str:
    """A plausible example value for a specification."""
    if isinstance(spec, TypeSpec):
        name, arg = spec.name, spec.arg or ""
        if name == "bool":
            return "yes"
        if name in ("int", "float"):
            lo, hi = spec.minimum, spec.maximum
            guess: float = 1 if name == "int" else 0.5
            if key in ("duration", "months", "days", "years"):
                guess = {"duration": 365, "months": 12, "days": 30, "years": 5}[key]
            if lo is not None and guess < lo:
                guess = lo
            if hi is not None and guess > hi:
                guess = hi
            return f"{guess:g}" if name == "float" else str(int(guess))
        if name == "date":
            return "1850.1.1"
        if name == "enum":
            values = sorted(schema.enums.get(arg, ()))
            return values[0] if values else arg
        if name == "ref":
            return SAMPLES.get(arg, arg)
        if name == "localisation":
            return SAMPLES["localisation"]
        if name == "color":
            return "{ 255 0 0 }"
        if key in ("name", "type"):
            return f"my_{key}"
        return "my_name"
    if isinstance(spec, BlockSpec):
        return "{ … }"
    if isinstance(spec, FieldsSpec):
        inner = " ".join(
            f"{k} = {sample(f.value, schema, k)}"
            for k, f in spec.fields.items()
            if not isinstance(f.value, (BlockSpec, RuleSpec))
        )
        return "{ " + inner + " }" if inner else "{ … }"
    if isinstance(spec, ListSpec):
        return "{ " + " ".join([sample(spec.item, schema)] * 2) + " }"
    if isinstance(spec, RuleSpec):
        return "{ … }"
    scalar = [o for o in spec.options if isinstance(o, TypeSpec)]
    return sample(scalar[0] if scalar else spec.options[0], schema, key)


# -- one command ------------------------------------------------------------------
def scopes_words(c: Command) -> str:
    """Where the command may be used."""
    if not c.scopes:
        return "any scope"
    return " / ".join(_SCOPE_WORDS.get(s, s) for s in c.scopes)


def pushed_words(c: Command) -> str:
    """Scope inside the block of a scope change ("" if none)."""
    if c.push_scope is None:
        return ""
    if isinstance(c.push_scope, dict):
        return "; ".join(f"from {a}: {b}" for a, b in c.push_scope.items())
    return c.push_scope


def syntax(c: Command) -> str:
    """One syntax line: ``badboy = <number>``."""
    return f"{c.name} = {_placeholder(c.value)}"


#: A trigger and an effect that work in each scope, for made-up examples of blocks.
_INSIDE = {
    "country": ("ai = no", "prestige = 5"),
    "province": ("is_coastal = yes", "life_rating = 5"),
    "state": ("is_slave = no", "any_owned_province = { life_rating = 5 }"),
    "pop": ("militancy = 5", "consciousness = 1"),
}


def example(c: Command, schema: Schema) -> str:
    """The hand-written example, or one made from the value."""
    if c.example:
        return c.example
    if c.push_scope is not None or isinstance(c.value, BlockSpec):
        if isinstance(c.push_scope, str):
            inner_scope = c.push_scope
        elif isinstance(c.push_scope, dict) and c.push_scope:
            inner_scope = next(iter(c.push_scope.values()))
        else:
            inner_scope = c.scopes[0] if c.scopes else "country"
        trigger, effect = _INSIDE.get(inner_scope, _INSIDE["country"])
        inner = trigger if c.context is Context.TRIGGER else effect
        if isinstance(c.value, BlockSpec) and c.value.context is Context.TRIGGER:
            inner = trigger
        return f"{c.name} = {{ {inner} }}"
    return f"{c.name} = {sample(c.value, schema, c.name)}"


def _all_value_lines(c: Command, schema: Schema) -> list[str]:
    lines = [f"**Value:** {value_words(c.value, schema)}"]
    if isinstance(c.value, FieldsSpec):
        for k, f in c.value.fields.items():
            text = f"- `{k}`: {value_words(f.value, schema)}"
            if f.required:
                text += " (required)"
            if f.doc:
                text += f" — {f.doc}"
            lines.append(text)
    return lines


def command_facts(c: Command, schema: Schema) -> list[str]:
    """Short facts about a command (Markdown lines): kind, scopes, value, comparison."""
    kind = "scope change" if c.push_scope is not None else c.context.value
    head = f"*{kind}* · used in: {scopes_words(c)}"
    pushed = pushed_words(c)
    if pushed:
        head += f" · inside the block: {pushed}"
    facts = [head]
    if c.push_scope is None:
        facts += _all_value_lines(c, schema)
    if c.context is Context.TRIGGER and c.compare in _COMPARE and c.push_scope is None:
        facts.append(f"**Check:** {_COMPARE[c.compare]}")
    return facts


#: ``id(command) -> (command, hover text)``: commands live as long as the schema.
_HOVERS: dict[int, tuple[Command, str]] = {}


def command_hover(c: Command, schema: Schema) -> str:
    """Markdown for the editor's hover over a command key (remembered per command)."""
    hit = _HOVERS.get(id(c))
    if hit is not None and hit[0] is c:
        return hit[1]
    text = _command_hover(c, schema)
    _HOVERS[id(c)] = (c, text)
    return text


def _command_hover(c: Command, schema: Schema) -> str:
    parts = [f"**{c.name}** — " + " · ".join(command_facts(c, schema)[:1])]
    rest = command_facts(c, schema)[1:]
    if c.doc:
        parts.append(c.doc)
    if c.details:
        parts.append(c.details)
    if rest:
        parts.append("  \n".join(rest))
    parts.append(f"```paradox\n{example(c, schema)}\n```")
    parts.append(f"*Syntax:* `{syntax(c)}` · *source:* {c.source}")
    return "\n\n".join(parts)


# -- the whole document -------------------------------------------------------------
def _anchor(text: str) -> str:
    """GitHub's heading anchor."""
    low = text.strip().lower()
    low = re.sub(r"[^\w\- ]", "", low)
    return low.replace(" ", "-")


def _entry(c: Command, schema: Schema, title: str) -> list[str]:
    out = [f"### {title}", ""]
    out.append("  \n".join(command_facts(c, schema)))
    out.append("")
    if c.doc:
        out += [c.doc, ""]
    if c.details:
        out += [c.details, ""]
    out += ["```", example(c, schema), "```", ""]
    out += [f"Syntax: `{syntax(c)}` · source: {c.source}", ""]
    return out


def _scope_entry(trigger: Command | None, effect: Command | None, schema: Schema) -> list[str]:
    """A scope change: one entry for its trigger and effect forms."""
    first = trigger or effect
    assert first is not None
    both = trigger is not None and effect is not None
    kind = "trigger and effect" if both else first.context.value
    facts = command_facts(first, schema)
    out = [
        f"### {first.name}",
        "",
        facts[0].replace("*scope change*", f"*scope change* ({kind})"),
        "",
    ]
    texts = dict.fromkeys(t for c in (trigger, effect) if c for t in (c.doc, c.details) if t)
    for text in texts:
        out += [text, ""]
    out += ["```"] + [example(c, schema) for c in (trigger, effect) if c] + ["```", ""]
    out += [f"Syntax: `{syntax(first)}` · source: {first.source}", ""]
    return out


def _dynamic_entry(d: DynamicKey, schema: Schema) -> list[str]:
    key = {"tag": "TAG", "int": "province id"}.get(
        d.key, d.key.removeprefix("ref:").replace("_", " ")
    )
    sample_key = {"tag": "ENG", "int": "300"}.get(
        d.key, SAMPLES.get(d.key.removeprefix("ref:"), "name")
    )
    contexts = " / ".join(c.value for c in d.contexts)
    out = [f"- **`<{key}>`** ({contexts})"]
    if d.push_scope:
        out[0] += f", scope inside: {d.push_scope}"
    out[0] += f": {d.doc}"
    if d.value is not None:
        out[0] += f" Value: {value_words(d.value, schema)}."
        out.append(f"  `{sample_key} = {sample(d.value, schema)}`")
    else:
        out.append(f"  `{sample_key} = {{ … }}`")
    return out


def commands_markdown(schema: Schema) -> str:
    """The whole command reference as Markdown (``docs/commands.md``)."""
    groups: dict[str, list[tuple[Command, str]]] = {"trigger": [], "effect": []}
    scope_changes: dict[str, dict[Context, Command]] = {}
    for (context, name), alts in sorted(
        schema.commands.items(), key=lambda x: (x[0][1], x[0][0].value)
    ):
        for i, c in enumerate(alts):
            if c.push_scope is not None:
                scope_changes.setdefault(name, {}).setdefault(context, c)
                continue
            label = context.value + (f", {scopes_words(c)}" if len(alts) > 1 else "")
            if i and label == context.value:
                label += f" {i + 1}"
            groups[context.value].append((c, f"{c.name} ({label})"))
    n_names = len({name for _, name in schema.commands})
    lines = [
        "# Command reference",
        "",
        "<!-- Generated by `python -m vic2toolmod.schema.reference --write` from the schema"
        " (vic2toolmod/schema/data); do not edit by hand. -->",
        "",
        f"Every trigger, effect and scope change the tool knows ({n_names} names), with"
        " what it does, where it may be used, what value it takes and an example."
        " The same text is shown when you hover over a key in the editor.",
        "",
        "## How to read an entry",
        "",
        "- **trigger** = a condition (in `trigger`, `limit`, `allow`, `potential`, …);"
        " **effect** = something that happens (in `effect`, `immediate`, `option`, …);"
        " **scope change** = a block that moves the commands inside to other countries,"
        " provinces, states or pops.",
        "- **used in** = the scope the command works in: *country*, *state*, *province*"
        ' or *pop* ("any scope" = everywhere). Inside `any_owned_province = { … }` the'
        " scope is a province; inside `owner = { … }` a country, and so on.",
        "- **Value** = what stands after `=`. `THIS` is the scope the event or decision"
        " started in; `FROM` the one that caused it (the country that fired the event,"
        " the attacker of a CB).",
        "- **Check** (triggers): how the value is compared; most number triggers mean"
        ' "at least". Put a trigger in `NOT = { … }` for the opposite.',
        "- **Source**: where the entry comes from (`cwtools` = the CWTools rules,"
        " `game` = names found in the game's program, `vanilla` = seen in the game's"
        ' files, `manual` / `author` = written for this tool). "not verified" marks'
        " what was taken from the name, the wiki or other mods without a test in the game.",
        "",
        "## Contents",
        "",
        f"- [Scope changes](#scope-changes) ({len(scope_changes)})",
        f"- [Triggers](#triggers) ({len(groups['trigger'])})",
        f"- [Effects](#effects) ({len(groups['effect'])})",
        f"- [Keys named after things](#keys-named-after-things) ({len(schema.dynamic)})",
        f"- [Modifiers](#modifiers) ({len(schema.modifiers)})",
        "",
    ]
    lines += ["## Scope changes", ""]
    lines += [" · ".join(f"[{n}](#{_anchor(n)})" for n in scope_changes), ""]
    for forms in scope_changes.values():
        lines += _scope_entry(forms.get(Context.TRIGGER), forms.get(Context.EFFECT), schema)
    for group, entries in groups.items():
        lines += [f"## {group.capitalize()}s", ""]
        lines += [" · ".join(f"[{c.name}](#{_anchor(title)})" for c, title in entries), ""]
        for c, title in entries:
            lines += _entry(c, schema, title)
    lines += [
        "## Keys named after things",
        "",
        "Keys that are not fixed words but names from the game or the mod.",
        "",
    ]
    for d in schema.dynamic:
        lines += _dynamic_entry(d, schema)
    lines += [
        "",
        "## Modifiers",
        "",
        "Keys inside modifiers (`event_modifiers.txt`, national values, technologies,"
        " reforms, …). The value is usually a number added to the country, province"
        " or pop; `0.1` is often +10 %.",
        "",
        "| Modifier | Value | Description |",
        "|---|---|---|",
    ]
    for name in sorted(schema.modifiers):
        doc = schema.modifier_docs.get(name, "").replace("|", "\\|")
        lines.append(f"| `{name}` | {value_words(schema.modifiers[name], schema)} | {doc} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the reference, or write it to ``docs/commands.md`` (``--write``)."""
    from vic2toolmod.schema.loader import load_schema

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true", help=f"write {DOC_PATH}")
    args = parser.parse_args(argv)
    text = commands_markdown(load_schema())
    if args.write:
        DOC_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {DOC_PATH} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
