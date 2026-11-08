"""One-time import of commands from CWTools' Victoria 2 rules into our YAML schema.

Source: https://github.com/cwtools/cwtools-vic2-config (MIT licence), commit
b8992c0f48a9878ffb45835fc677a6fa271899d2 (2020-01-31).

Usage::

    git clone https://github.com/cwtools/cwtools-vic2-config /tmp/cwt
    python tools/import_cwtools.py /tmp/cwt vic2toolmod/schema/data

Writes ``commands/triggers.yaml``, ``commands/effects.yaml``,
``commands/scopes.yaml``, ``enums.yaml`` and ``modifiers.yaml``. The result was
reviewed and corrected by hand afterwards (see ``docs/schema.md``), so this
script is kept only to document where the data came from; running it again
overwrites the manual corrections.

The ``.cwt`` files use Paradox syntax, so they are read with our own parser.
``<type>`` references are rewritten to plain words first, because ``<`` and
``>`` are operators in Paradox script.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from vic2toolmod.script import Assignment, Block, Scalar, parse_text

# CWTools type names -> our registry names (ref:NAME).
REGISTRY = {
    "province_id": "province",
    "culture": "culture",
    "culture_group": "culture_group",
    "ideology": "ideology",
    "ideologies": "ideology",
    "religion": "religion",
    "goods": "goods",
    "issue": "issue_option",
    "trade_policy": "issue_option",
    "war_policy": "issue_option",
    "religious_policy": "issue_option",
    "economic_reforms": "issue_option",
    "economic_reform": "issue_option",
    "political_reforms": "issue_option",
    "political_reform": "issue_option",
    "social_reform": "issue_option",
    "military_reforms": "issue_option",
    "military_reform": "issue_option",
    "event_modifier": "modifier",
    "modifier": "modifier",
    "pop_type": "pop_type",
    "poptypes": "pop_type",
    "cb_types": "cb_type",
    "casus_belli": "cb_type",
    "governments": "government",
    "government": "government",
    "inventions": "invention",
    "technology": "technology",
    "national_value": "national_value",
    "national_values": "national_value",
    "continent": "continent",
    "building": "building",
    "state": "region",
    "terrain_type": "terrain",
    "leader": "leader",
    "trait": "trait",
    "background": "trait",
    "event.country": "event",
    "event.province": "event",
    "country_tags": "country",
    "bool": None,
}
FLAGS = {"country_flag", "province_flag", "global_flag", "variable"}


def convert_value(node: Any) -> Any:
    """CWTools right-hand side -> our value specification (YAML-ready)."""
    if isinstance(node, Scalar):
        text = node.value
        if text in ("bool", "boll", "type@bool"):
            return "bool"
        if text in ("int", "float", "scalar", "localisation"):
            return text
        if m := re.fullmatch(r"int\[(-?\d+)\.\.(-?\d+)\]", text):
            return f"int[{m[1]}..{m[2]}]"
        if m := re.fullmatch(r"enum\[(\w+)\]", text):
            return "ref:country" if m[1] == "country_tags" else f"enum:{m[1]}"
        if m := re.fullmatch(r"type@([\w.]+)", text):
            reg = REGISTRY.get(m[1], m[1])
            return "bool" if reg is None else f"ref:{reg}"
        if m := re.fullmatch(r"value(?:_set)?\[(\w+)\]", text):
            return f"ref:{m[1]}"
        if text in ("country", "province"):
            return f"ref:{text}"
        return "scalar"
    assert isinstance(node, Block)
    keys = [i for i in node.items if isinstance(i, Assignment)]
    texts = {i.key_text for i in keys}
    if "alias_name[trigger]" in texts:
        return {"block": "trigger"}
    if "alias_name[effect]" in texts:
        return {"block": "effect"}
    return {"fields": {i.key_text: convert_value(i.value) for i in keys if i.value is not None}}


def metadata(assignment: Assignment) -> dict[str, str]:
    """Read ``## key = value`` comments in front of a CWTools rule."""
    meta: dict[str, str] = {}
    for comment in assignment.key.comments():
        m = re.match(r"#\s*(\w+)\s*=\s*(.+?)\s*$", comment)
        if m:
            meta[m[1]] = m[2]
    return meta


def scopes_of(text: str | None) -> list[str]:
    """Scopes named in a ``## scope`` comment."""
    if not text:
        return ["any"]
    return re.findall(r"country|province|state|pop|any", text) or ["any"]


def compare_of(value: Any) -> str | None:
    """Default comparison of a trigger with this value (K53)."""
    if isinstance(value, dict):
        return "block"
    if value in ("int", "float") or str(value).startswith("int["):
        return "gte"
    return "eq"


def read_cwt(path: Path) -> list[Assignment]:
    """Parse a ``.cwt`` file, rewriting ``<type>`` references to words."""
    text = path.read_text(encoding="utf-8-sig")
    text = re.sub(r"<([A-Za-z0-9_.]+)>", r"type@\1", text)
    return [i for i in parse_text(text).items if isinstance(i, Assignment)]


def import_aliases(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Collect ``alias[trigger:x]`` / ``alias[effect:x]`` rules."""
    out: dict[str, dict[str, Any]] = {"trigger": {}, "effect": {}}
    for path in paths:
        for a in read_cwt(path):
            m = re.fullmatch(r"alias\[(trigger|effect):(\w+)\]", a.key_text)
            if not m or a.value is None:
                continue
            context, name = m[1], m[2]
            meta = metadata(a)
            value = convert_value(a.value)
            entry: dict[str, Any] = {"scopes": scopes_of(meta.get("scope")), "value": value}
            if "push_scope" in meta:
                entry["push_scope"] = scopes_of(meta["push_scope"])[0]
            if context == "trigger":
                entry["compare"] = compare_of(value)
            entry["source"] = "cwtools"
            existing = out[context].get(name)
            if existing is None:
                out[context][name] = entry
            elif isinstance(existing, list):
                existing.append(entry)
            else:
                out[context][name] = [existing, entry]
    return out


def main(cwt: Path, target: Path) -> None:
    """Write the YAML files."""
    (target / "commands").mkdir(parents=True, exist_ok=True)
    header = "# Imported from cwtools-vic2-config (MIT) by tools/import_cwtools.py, then curated.\n"
    plain = import_aliases([cwt / "triggers.cwt", cwt / "effects.cwt"])
    scoped = import_aliases([cwt / "scopes.cwt"])
    dump = {"default_flow_style": None, "sort_keys": True, "allow_unicode": True, "width": 100}
    for name, data in (
        ("triggers", {"trigger": plain["trigger"]}),
        ("effects", {"effect": plain["effect"]}),
        ("scopes", {"trigger": scoped["trigger"], "effect": scoped["effect"]}),
    ):
        (target / "commands" / f"{name}.yaml").write_text(header + yaml.safe_dump(data, **dump))
    enums: dict[str, list[str]] = {}
    for a in read_cwt(cwt / "enums.cwt"):
        if isinstance(a.value, Block):
            for e in a.value.items:
                m = (
                    re.fullmatch(r"enum\[(\w+)\]", e.key_text)
                    if isinstance(e, Assignment)
                    else None
                )
                if m and isinstance(e, Assignment) and isinstance(e.value, Block):
                    enums[m[1]] = [i.value for i in e.value.items if isinstance(i, Scalar)]
    (target / "enums.yaml").write_text(header + yaml.safe_dump({"enums": enums}, **dump))
    modifiers: dict[str, str] = {}
    for a in read_cwt(cwt / "modifiers.cwt"):
        if isinstance(a.value, Block):
            for e in a.value.items:
                if isinstance(e, Assignment):
                    modifiers[e.key_text] = "float"
    (target / "modifiers.yaml").write_text(
        header + yaml.safe_dump({"modifiers": modifiers}, **dump)
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
