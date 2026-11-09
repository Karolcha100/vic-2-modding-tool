"""Checking a scalar value against a `TypeSpec`.

Reference types (``ref:NAME``) are only checked for their *shape* here (a
country is a tag or a scope keyword, a province is a number). Whether the
named thing exists in the mod is checked by the project index (Phase 3).
"""

from __future__ import annotations

import re

from vic2toolmod.schema.model import Schema, TypeSpec

_INT = re.compile(r"[-+]?\d+")
_FLOAT = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)")
_DATE = re.compile(r"\d{1,4}\.\d{1,2}\.\d{1,2}")
_TAG = re.compile(r"[A-Za-z][A-Za-z0-9]{2}")

SCOPE_KEYWORDS = frozenset({"this", "from", "owner", "controller", "root"})
"""Words that may stand for a country / province instead of a name."""

_SHAPES: dict[str, re.Pattern[str]] = {
    "country": _TAG,
    "province": _INT,
}


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def is_tag(text: str) -> bool:
    """Whether ``text`` looks like a country tag (``USA``, ``D01``)."""
    return bool(_TAG.fullmatch(text))


def check_scalar(text: str, spec: TypeSpec, schema: Schema) -> str | None:
    """Check one value.

    Args:
        text: The value without quotes.
        spec: Expected type.
        schema: For enum values.

    Returns:
        ``None`` if the value fits, otherwise a short English description of
        what was expected.
    """
    name = spec.name
    low = text.lower()
    if name in ("any", "scalar", "localisation"):
        return None
    if name == "bool":
        return None if low in ("yes", "no") else "yes or no"
    if name in ("int", "float"):
        pattern = _INT if name == "int" else _FLOAT
        if not pattern.fullmatch(text):
            return "an integer" if name == "int" else "a number"
        number = float(text)
        if spec.minimum is not None and number < spec.minimum:
            return f"a number >= {_fmt(spec.minimum)}"
        if spec.maximum is not None and number > spec.maximum:
            return f"a number <= {_fmt(spec.maximum)}"
        return None
    if name == "date":
        return None if _DATE.fullmatch(text) else "a date (year.month.day)"
    if name == "enum":
        values = schema.enums.get(spec.arg or "", frozenset())
        return None if low in values else f"one of: {', '.join(sorted(values)[:12])}"
    if name == "ref":
        if low in SCOPE_KEYWORDS:
            return None
        shape = _SHAPES.get(spec.arg or "")
        if shape is not None and not shape.fullmatch(text):
            return "a country tag" if spec.arg == "country" else f"a {spec.arg} id"
        return None
    if name == "color":
        return None
    return None  # pragma: no cover - unknown types are rejected by the loader
