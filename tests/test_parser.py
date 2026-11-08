import pytest

from vic2toolmod.script import Assignment, Block, ErrorNode, Scalar, Severity, parse_text

EVENT = """\
country_event = {
\tid = 95260
\ttitle = "EVTNAME95260" #The Disunited States
\ttrigger = {
\t\ttag = USA
\t\tNOT = { has_global_flag = disunited_states }
\t}
\tmean_time_to_happen = {
\t\tmonths = 24
\t\tmodifier = { factor = 0.8 }
\t\tmodifier = { factor = 1.2 }
\t}
}
"""


def test_tree_shape_and_lookup():
    doc = parse_text(EVENT)
    assert not doc.diagnostics
    event = doc.find("country_event")
    assert isinstance(event, Assignment)
    block = event.value
    assert isinstance(block, Block)
    assert block.find("id").value.text == "95260"
    title = block.find("title").value
    assert isinstance(title, Scalar)
    assert title.quoted and title.value == "EVTNAME95260"
    mtth = block.find("mean_time_to_happen").value
    assert [m.value.find("factor").value.text for m in mtth.assignments("modifier")] == [
        "0.8",
        "1.2",
    ]


def test_lookup_is_case_insensitive():
    doc = parse_text("NOT = { a = 1 }")
    assert doc.find("not") is not None


def test_comment_is_attached_to_next_token():
    doc = parse_text(EVENT)
    trigger = doc.find("country_event").value.find("trigger")
    assert trigger.key.comments() == ["The Disunited States"]


def test_positions_of_nodes():
    doc = parse_text(EVENT)
    tag = doc.find("country_event").value.find("trigger").value.find("tag")
    assert doc.position(tag.start) == (5, 3)
    assert EVENT[tag.start : tag.end] == "tag = USA"


def test_walk_visits_every_node_in_order():
    doc = parse_text("a = { b = 1 c = { d } }")
    kinds = [type(n).__name__ for n in doc.walk()]
    assert kinds == [
        "Document",
        "Assignment",
        "Block",
        "Assignment",
        "Scalar",
        "Assignment",
        "Block",
        "Scalar",
    ]


def test_crlf_positions():
    doc = parse_text("a = 1\r\nb = 2\r\n")
    assert doc.position(doc.find("b").start) == (2, 1)


@pytest.mark.parametrize(
    "text",
    ["", "a", "}", "{", "=", "a = ", "a = {", '"', "a = { b = { c = { }", "} } { {", "= = ="],
)
def test_broken_input_never_raises_and_stays_lossless(text):
    doc = parse_text(text)
    assert doc.to_text() == text


def test_errors_are_sorted_and_have_ranges():
    doc = parse_text("a = 1\n}\nb = {\n")
    codes = [d.code for d in doc.diagnostics]
    assert codes == ["syntax.unmatched-close-brace", "syntax.unclosed-brace"]
    assert all(d.severity is Severity.ERROR for d in doc.diagnostics)
    assert doc.has_errors
    assert [d.start for d in doc.diagnostics] == sorted(d.start for d in doc.diagnostics)


def test_indentation_hint_points_at_real_missing_brace():
    text = (
        "army = {\n"
        "\tregiment = {\n"
        "\t\ttype = a\n"
        "\t}\n"
        "\tregiment = {\n"  # line 5: this one is never closed
        "\t\ttype = b\n"
        "\tregiment = {\n"
        "\t\ttype = c\n"
        "\t}\n"
        "}\n"
    )
    doc = parse_text(text)
    hints = [d for d in doc.diagnostics if d.code == "syntax.brace-indentation"]
    assert [doc.position(h.start)[0] for h in hints] == [5]
    assert hints[0].severity is Severity.WARNING


def test_no_indentation_hints_without_brace_errors():
    doc = parse_text("a = {\n  b = 1\n      }\n")
    assert doc.diagnostics == []


def test_deep_nesting_has_no_recursion_limit():
    depth = 50_000
    text = "a = { " * depth + "b = 1" + " }" * depth
    doc = parse_text(text)
    assert not doc.diagnostics
    assert doc.to_text() == text
    assert sum(1 for _ in doc.walk()) == 2 * depth + 3


def test_error_nodes():
    doc = parse_text("} = x")
    assert [type(i) for i in doc.items] == [ErrorNode, ErrorNode, Scalar]
