import pytest

from vic2toolmod.edit import (
    Buffer,
    TextEdit,
    apply_edits,
    delete,
    indent_unit,
    insert,
    rename_key,
    render_value,
    set_value,
)
from vic2toolmod.script import parse_text

SRC = (
    "# head\r\n"
    "country_event = {\r\n"
    "\tid = 1 # the id\r\n"
    "\ttrigger = { war = no }\r\n"
    "\toption = {\r\n"
    "\t\tname = A\r\n"
    "\t}\r\n"
    "}\r\n"
)


def event(doc):
    return doc.find("country_event").value


def test_apply_edits_and_overlap():
    assert apply_edits("abcdef", [TextEdit(4, 5, "X"), TextEdit(0, 1, "")]) == "bcdXf"
    with pytest.raises(ValueError):
        apply_edits("abc", [TextEdit(0, 2, ""), TextEdit(1, 3, "")])


def test_set_value_keeps_everything_else():
    doc = parse_text(SRC)
    new = apply_edits(SRC, [set_value(doc, event(doc).find("id"), "2")])
    assert new == SRC.replace("id = 1", "id = 2")


def test_insert_into_multiline_block_uses_file_style():
    doc = parse_text(SRC)
    edit = insert(
        doc,
        event(doc).find("option").value,
        [
            ("badboy", "1"),
            (
                "any_pop",
                [
                    ("militancy", "1"),
                    ("consciousness", "2"),
                    ("limit", [("is_primary_culture", "yes")]),
                ],
            ),
        ],
    )
    new = apply_edits(SRC, [edit])
    assert "\t\tname = A\r\n\t\tbadboy = 1\r\n\t\tany_pop = {\r\n\t\t\tmilitancy = 1\r\n" in new
    assert "\t\t\tlimit = { is_primary_culture = yes }\r\n\t\t}\r\n\t}\r\n" in new
    assert parse_text(new).diagnostics == []


def test_insert_into_inline_and_empty_block():
    doc = parse_text(SRC)
    new = apply_edits(SRC, [insert(doc, event(doc).find("trigger").value, [("tag", "USA")])])
    assert "trigger = { war = no tag = USA }" in new
    doc = parse_text("a = { }\n")
    assert (
        apply_edits(doc.text, [insert(doc, doc.find("a").value, [("b", "1")])]) == "a = { b = 1 }\n"
    )


def test_insert_top_level_and_at_index():
    doc = parse_text("a = 1")
    assert apply_edits(doc.text, [insert(doc, doc, [("b", "2")])]) == "a = 1\nb = 2\n"
    doc = parse_text("x = {\n\ta = 1\n\tc = 3\n}\n")
    block = doc.find("x").value
    assert "\ta = 1\n\tb = 2\n\tc = 3\n" in apply_edits(
        doc.text, [insert(doc, block, [("b", "2")], 1)]
    )


def test_delete_whole_line_keeps_comments():
    doc = parse_text(SRC)
    new = apply_edits(SRC, [delete(doc, event(doc).find("option").value.find("name"))])
    assert new == SRC.replace("\t\tname = A\r\n", "")
    doc = parse_text(SRC)
    new = apply_edits(SRC, [delete(doc, event(doc).find("id"))])
    assert "# the id" in new  # trailing comment stays
    doc = parse_text("t = { a = 1 b = 2 }")
    assert apply_edits(doc.text, [delete(doc, doc.find("t").value.find("b"))]) == "t = { a = 1 }"


def test_rename_key_and_render():
    doc = parse_text("a = 1")
    assert apply_edits(doc.text, [rename_key(doc.find("a"), "b")]) == "b = 1"
    assert render_value(["1", "2", "3"], "\t", 0, "\n") == "{ 1 2 3 }"
    assert render_value([], "\t", 0, "\n") == "{ }"


def test_indent_unit():
    assert indent_unit("a = {\n\tb = 1\n}") == "\t"
    assert indent_unit("a = {\n    b = 1\n    c = {\n        d = 1\n    }\n}") == "    "
    assert indent_unit("") == "\t"


def test_buffer_undo_redo():
    b = Buffer("a = 1")
    b.apply(set_value(b.document, b.document.find("a"), "2"))
    b.replace_all("a = 3")
    assert b.text == "a = 3"
    assert b.undo() and b.text == "a = 2"
    assert b.undo() and b.text == "a = 1"
    assert not b.undo()
    assert b.redo() and b.text == "a = 2"
    b.apply(TextEdit(0, 0, "# x\n"))
    assert not b.redo()  # a new change clears redo
