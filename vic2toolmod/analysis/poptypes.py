"""What affects pop types (K59): promotion graph and "who influences whom".

Every ``poptypes/<pop>.txt`` has weights such as::

    promote_to = {
        capitalists = {
            factor = 0.01
            modifier = { factor = 10  political_reform = trade_unions_allowed }
        }
    }

This module reads the weights of every pop type - ``promote_to`` (the
promotion graph), ``ideologies``, ``issues``, ``migration_target`` and
``country_migration_target`` - together with the names their conditions refer
to (reform options, technologies, inventions, ...). From that it answers which
reforms change which promotion, and exports the graph as JSON for a viewer.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from vic2toolmod.schema.validator import Validator, file_type_for
from vic2toolmod.script.cst import Assignment, Block, Document, Scalar
from vic2toolmod.script.tokens import Token
from vic2toolmod.workspace import Workspace

WEIGHT_KINDS = ("promote_to", "ideologies", "issues")
"""Blocks of ``target = { weight }`` entries."""
SINGLE_KINDS = ("migration_target", "country_migration_target")
"""Blocks that are one weight (no targets)."""
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Factor:
    """One ``modifier = { factor = X conditions }`` of a weight.

    Attributes:
        factor: The multiplier (``None`` if missing).
        conditions: The conditions as one line of script.
        refs: ``(registry, name)`` of the names the conditions use.
        line: 1-based line of the modifier.
    """

    factor: float | None
    conditions: str
    refs: tuple[tuple[str, str], ...]
    line: int


@dataclass
class Weight:
    """A weight of a pop type: e.g. how much aristocrats promote to capitalists.

    Attributes:
        pop: The pop type whose file it is.
        kind: ``promote_to``, ``ideologies``, ``issues``, ``migration_target`` ...
        target: Target pop type / ideology / issue option (``""`` for single weights).
        base: The base ``factor`` (``None`` if missing).
        modifiers: Its modifiers.
        file: Relative path.
        line: 1-based line.
    """

    pop: str
    kind: str
    target: str
    base: float | None
    modifiers: list[Factor] = field(default_factory=list)
    file: str = ""
    line: int = 0


def _number(block: Block, key: str) -> float | None:
    a = block.find(key)
    if a is not None and isinstance(a.value, Scalar):
        try:
            return float(a.value.value)
        except ValueError:
            return None
    return None


def _factors(doc: Document, refs: list[tuple[str, str, Token]], block: Block) -> list[Factor]:
    result = []
    for m in block.assignments("modifier"):
        if not isinstance(m.value, Block):
            continue
        body = [
            i
            for i in m.value.items
            if not (isinstance(i, Assignment) and i.key_text.lower() == "factor")
        ]
        text = _SPACES.sub(" ", " ".join(i.to_text().strip() for i in body)).strip()
        inside = tuple(sorted({(r, n.lower()) for r, n, t in refs if m.start <= t.start < m.end}))
        result.append(Factor(_number(m.value, "factor"), text, inside, doc.position(m.start)[0]))
    return result


def pop_weights(ws: Workspace) -> list[Weight]:
    """Every weight of every pop type in the project."""
    out: list[Weight] = []
    validator = Validator(ws.schema, ws.registries().has)
    for f in ws.project.glob("poptypes/*.txt"):
        doc = ws.document(f.rel)
        ft = file_type_for(f.rel, ws.schema)
        if ft is not None:
            validator.validate(doc, ft.rule, ft.scope)
        refs = list(validator.references) if ft is not None else []
        pop = PurePosixPath(f.rel).stem

        for kind in WEIGHT_KINDS:
            for section in doc.assignments(kind):
                if not isinstance(section.value, Block):
                    continue
                for target in section.value.assignments():
                    if isinstance(target.value, Block):
                        out.append(
                            Weight(
                                pop,
                                kind,
                                target.key_text,
                                _number(target.value, "factor"),
                                _factors(doc, refs, target.value),
                                f.rel,
                                doc.position(target.start)[0],
                            )
                        )
        for kind in SINGLE_KINDS:
            for section in doc.assignments(kind):
                if isinstance(section.value, Block):
                    out.append(
                        Weight(
                            pop,
                            kind,
                            "",
                            _number(section.value, "factor"),
                            _factors(doc, refs, section.value),
                            f.rel,
                            doc.position(section.start)[0],
                        )
                    )
    return out


def influences(
    weights: list[Weight], registries: tuple[str, ...] = ("issue_option", "technology", "invention")
) -> dict[tuple[str, str], list[tuple[Weight, Factor]]]:
    """Which weights each name changes: ``(registry, name) -> [(weight, modifier)]``.

    Args:
        weights: From `pop_weights`.
        registries: Kinds of names to report (reform options, techs, inventions ...).
    """
    table: dict[tuple[str, str], list[tuple[Weight, Factor]]] = defaultdict(list)
    for w in weights:
        for m in w.modifiers:
            for ref in m.refs:
                if ref[0] in registries:
                    table[ref].append((w, m))
    return dict(table)


def promotion_graph(weights: list[Weight]) -> dict[str, Any]:
    """The promotion graph as JSON-ready data for a viewer.

    ``{"nodes": [{"id": pop}], "edges": [{"source", "target", "base",
    "modifiers": [{"factor", "conditions", "refs", "line"}], "file", "line"}]}``
    """
    pops = sorted({w.pop for w in weights} | {w.target for w in weights if w.kind == "promote_to"})
    edges = [
        {
            "source": w.pop,
            "target": w.target,
            "base": w.base,
            "modifiers": [
                {
                    "factor": m.factor,
                    "conditions": m.conditions,
                    "refs": [list(r) for r in m.refs],
                    "line": m.line,
                }
                for m in w.modifiers
            ],
            "file": w.file,
            "line": w.line,
        }
        for w in weights
        if w.kind == "promote_to"
    ]
    return {"nodes": [{"id": p} for p in pops], "edges": edges}
