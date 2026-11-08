"""Trigger tester (K53): list the facts a trigger depends on, evaluate it with answers.

The tester does not simulate the game. It lists every condition of a trigger
block as a `Fact` ("tag = USA", "war = no", "literacy = 0.5"); the user answers
with the real value in the game ("USA", "no", "0.62") or simply true / false;
`evaluate` then says whether the trigger holds and which facts failed.

* Comparisons come from the schema's ``compare`` field: ``eq`` (same value,
  any case), ``gte`` (number at least the written one - the usual meaning of a
  number in a Vic2 trigger), ``lte``, ``block`` (answer true / false).
* ``AND`` (and the block itself) needs all, ``OR`` any, ``NOT`` none of its
  conditions (Paradox's NOT is "nor").
* A scope change (``any_pop = { ... }``, ``ENG = { ... }``, ``owner = { ... }``)
  is one question: "is there such a pop / does ENG match?" - answered true / false.
* Missing answers make the result unknown (``None``) unless the logic decides
  it anyway (``OR`` with one true condition is true).

`weight` evaluates ``mean_time_to_happen`` / ``ai_chance`` / pop weights: base
value times the factors of the modifiers whose conditions hold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vic2toolmod.schema.model import Context, Schema
from vic2toolmod.script.cst import Assignment, Block, Document, Node, Scalar

Answer = str | bool
_Eval = tuple[bool | None, list[str], list[str]]
_LOGIC = {"and", "or", "not"}


@dataclass(frozen=True)
class Fact:
    """One condition to answer.

    Attributes:
        id: Stable id (positions of the items on the way, e.g. ``"3.0.1"``).
        key: The trigger (``tag``) or scope (``any_pop``).
        value: Its value in the file (``USA``; block text for blocks).
        compare: ``eq``, ``gte``, ``lte`` or ``block``.
        kind: ``condition`` or ``scope`` (a scope change asked as one question).
        line: 1-based line.
    """

    id: str
    key: str
    value: str
    compare: str
    kind: str
    line: int

    @property
    def question(self) -> str:
        """Human-readable question for a form."""
        if self.kind == "scope":
            return f"Does '{self.key}' find a match for its conditions?"
        if self.compare == "gte":
            return f"Value of '{self.key}' (needs at least {self.value})?"
        if self.compare == "lte":
            return f"Value of '{self.key}' (needs at most {self.value})?"
        if self.compare == "block":
            return f"Is '{self.key} = {self.value}' true?"
        return f"Value of '{self.key}' (needs {self.value})?"


@dataclass
class Result:
    """Outcome of an evaluation.

    Attributes:
        value: True / False, or ``None`` if unknown.
        failed: Ids of facts that were answered and are false (the reasons).
        unknown: Ids of facts without an answer that mattered.
    """

    value: bool | None
    failed: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


class TriggerTester:
    """Facts and evaluation for trigger blocks of one document."""

    def __init__(self, schema: Schema, doc: Document) -> None:
        self.schema = schema
        self.doc = doc

    # -- facts -----------------------------------------------------------------------
    def facts(self, block: Block) -> list[Fact]:
        """Every fact of a trigger block, in file order."""
        out: list[Fact] = []
        self._collect(block.items, "", out)
        return out

    def _collect(self, items: list[Node], prefix: str, out: list[Fact]) -> None:
        for n, item in enumerate(items):
            if not isinstance(item, Assignment) or item.value is None:
                continue
            fid = f"{prefix}{n}"
            key = item.key_text.lower()
            if key in _LOGIC and isinstance(item.value, Block):
                self._collect(item.value.items, fid + ".", out)
                continue
            out.append(self._fact(item, fid))

    def _fact(self, item: Assignment, fid: str) -> Fact:
        value = item.value
        assert value is not None
        line = self.doc.position(item.start)[0]
        text = value.to_text().strip() if isinstance(value, Block) else value.text
        if isinstance(value, Block) and self._is_scope(item):
            return Fact(fid, item.key_text, text, "block", "scope", line)
        commands = self.schema.command(Context.TRIGGER, item.key_text)
        compare = next((c.compare for c in commands if c.compare), None)
        if compare is None:
            compare = "block" if isinstance(value, Block) else "eq"
        if isinstance(value, Block):
            compare = "block"
        return Fact(
            fid,
            item.key_text,
            text if isinstance(value, Block) else value.value,
            compare,
            "condition",
            line,
        )

    def _is_scope(self, item: Assignment) -> bool:
        """A block-valued key is a scope change unless the schema says otherwise.

        Unknown block keys are tags, province ids, regions, pop types - all scopes.
        """
        commands = self.schema.command(Context.TRIGGER, item.key_text)
        if commands:
            return any(c.push_scope is not None for c in commands)
        return True

    # -- evaluation --------------------------------------------------------------------
    def evaluate(self, block: Block, answers: dict[str, Answer]) -> Result:
        """Evaluate a trigger block with answers keyed by fact id.

        ``Result.failed`` lists only the facts that decided a false result
        (inside ``NOT`` that is a fact which is *true*).
        """
        facts = {f.id: f for f in self.facts(block)}
        unknown: list[str] = []
        value, falses, _ = self._node_all(block.items, "", facts, answers, unknown)
        return Result(value, falses if value is False else [], unknown)

    def _node_all(
        self,
        items: list[Node],
        prefix: str,
        facts: dict[str, Fact],
        answers: dict[str, Answer],
        unknown: list[str],
    ) -> _Eval:
        """AND of the items: ``(value, facts making it false, facts making it true)``."""
        parts = self._children(items, prefix, facts, answers, unknown)
        values = [p[0] for p in parts]
        trues = [f for p in parts for f in p[2]]
        if False in values:
            return False, [f for p in parts if p[0] is False for f in p[1]], trues
        return (None if None in values else True), [], trues

    def _children(
        self,
        items: list[Node],
        prefix: str,
        facts: dict[str, Fact],
        answers: dict[str, Answer],
        unknown: list[str],
    ) -> list[_Eval]:
        out: list[_Eval] = []
        for n, item in enumerate(items):
            if not isinstance(item, Assignment) or item.value is None:
                continue
            fid = f"{prefix}{n}"
            key = item.key_text.lower()
            if key in _LOGIC and isinstance(item.value, Block):
                sub = item.value.items
                if key == "and":
                    out.append(self._node_all(sub, fid + ".", facts, answers, unknown))
                    continue
                parts = self._children(sub, fid + ".", facts, answers, unknown)
                values = [p[0] for p in parts]
                if True in values:
                    any_value: bool | None = True
                elif None in values:
                    any_value = None
                else:
                    any_value = False
                any_true = [f for p in parts if p[0] is True for f in p[2]]
                any_false = [f for p in parts for f in p[1]]
                if key == "or":
                    out.append((any_value, any_false, any_true))
                else:  # NOT = none of them: false because of the true ones
                    out.append((None if any_value is None else not any_value, any_true, any_false))
                continue
            v = _check(facts[fid], answers.get(fid))
            if v is None:
                unknown.append(fid)
                out.append((None, [], []))
            else:
                out.append((v, [] if v else [fid], [fid] if v else []))
        return out

    # -- weights -----------------------------------------------------------------------
    def weight(self, block: Block, answers: dict[str, dict[str, Answer]]) -> WeightResult:
        """Evaluate a weight block (MTTH, ai_chance, pop weight).

        Args:
            block: The weight block (``months`` / ``factor`` / ``base`` and ``modifier``s).
            answers: Modifier index (``"0"``, ``"1"`` ... among the modifiers) ->
                answers for that modifier's facts.

        Returns:
            The base value, the final value and the factors applied.
        """
        base = None
        for key in ("months", "days", "years", "base", "factor"):
            found = block.find(key)
            if found is not None and isinstance(found.value, Scalar):
                base = float(found.value.value)
                break
        applied: list[tuple[int, float]] = []
        unknown: list[int] = []
        value = base
        modifiers = [m for m in block.assignments("modifier") if isinstance(m.value, Block)]
        for n, m in enumerate(modifiers):
            assert isinstance(m.value, Block)
            conditions = Block(m.value.lbrace)
            conditions.items = [
                i
                for i in m.value.items
                if not (isinstance(i, Assignment) and i.key_text.lower() == "factor")
            ]
            f = m.value.find("factor")
            factor = float(f.value.value) if f is not None and isinstance(f.value, Scalar) else 1.0
            r = self.evaluate(conditions, answers.get(str(n), {})).value
            if r is True:
                applied.append((n, factor))
                value = None if value is None else value * factor
            elif r is None:
                unknown.append(n)
        return WeightResult(base, value, applied, unknown)


@dataclass
class WeightResult:
    """Outcome of `TriggerTester.weight`.

    Attributes:
        base: Base value (months for MTTH).
        value: Base times the applied factors (``None`` without a base).
        applied: ``(modifier index, factor)`` of modifiers whose conditions hold.
        unknown: Indexes of modifiers that could not be decided.
    """

    base: float | None
    value: float | None
    applied: list[tuple[int, float]]
    unknown: list[int]


def _check(fact: Fact, answer: Answer | None) -> bool | None:
    if answer is None:
        return None
    if isinstance(answer, bool):
        return answer
    if fact.compare in ("gte", "lte"):
        try:
            actual, wanted = float(answer), float(fact.value)
        except ValueError:
            return answer.strip().lower() == fact.value.lower()
        return actual >= wanted if fact.compare == "gte" else actual <= wanted
    if fact.compare == "block" or fact.kind == "scope":
        return answer.strip().lower() in ("yes", "true", "1")
    return answer.strip().lower() == fact.value.lower()
