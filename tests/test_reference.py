"""Command reference (T006): descriptions, examples, hover and docs/commands.md."""

import dataclasses

from vic2toolmod.schema.loader import default_schema
from vic2toolmod.schema.model import Context, Rule
from vic2toolmod.schema.reference import DOC_PATH, command_hover, commands_markdown, example
from vic2toolmod.schema.validator import Validator
from vic2toolmod.script.parser import parse_text


def test_every_command_is_described():
    schema = default_schema()
    missing = sorted(
        f"{ctx.value} {name}"
        for (ctx, name), alts in schema.commands.items()
        for c in alts
        if not c.doc or not c.details
    )
    assert missing == []


def test_every_example_is_valid():
    schema = default_schema()
    rules = {
        **schema.rules,
        "test_trigger": Rule("test_trigger", other="trigger"),
        "test_effect": Rule("test_effect", other="effect"),
    }
    schema = dataclasses.replace(schema, rules=rules)
    wrong = []
    for (ctx, name), alts in sorted(schema.commands.items()):
        for c in alts:
            doc = parse_text(example(c, schema))
            scope = c.scopes[0] if c.scopes else "country"
            found = list(doc.diagnostics) + Validator(schema).validate(
                doc, f"test_{ctx.value}", scope
            )
            if found:
                wrong.append((ctx.value, name, example(c, schema), [d.message for d in found]))
    assert wrong == []


def test_hover_text():
    schema = default_schema()
    (badboy,) = schema.command(Context.TRIGGER, "badboy")
    text = command_hover(badboy, schema)
    assert "**badboy**" in text and "at least" in text and "badboy = 0.5" in text
    assert badboy.details in text
    war = schema.command(Context.EFFECT, "war")[0]
    assert "attacker_goal" in command_hover(war, schema)


def test_document_is_up_to_date():
    # regenerate with: python -m vic2toolmod.schema.reference --write
    assert DOC_PATH.read_text(encoding="utf-8") == commands_markdown(default_schema())
