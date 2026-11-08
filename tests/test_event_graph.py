from pathlib import Path

from vic2toolmod.analysis.events import event_graph
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")


def test_event_graph(tmp_path):
    g = tmp_path / "game"
    write(
        g / "events/a.txt",
        """
country_event = { id = 1 title = T1 option = { name = OPT_A country_event = 2 }
                  option = { name = OPT_B country_event = { id = 99 days = 5 } } }
country_event = { id = 2 is_triggered_only = yes }
country_event = { id = 3 is_triggered_only = yes }
""",
    )
    write(
        g / "decisions/d.txt",
        "political_decisions = { my_dec = { effect = { country_event = 3 } } }\n",
    )
    write(g / "common/on_actions.txt", "on_yearly_pulse = { 1000 = 2 }\n")
    write(g / "localisation/x.csv", "T1;First event;;;;;;;;;;;;;x\n")
    graph = event_graph(Workspace.open(g))
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["event:1"]["title"] == "First event"
    assert nodes["event:99"]["missing"] is True
    assert not nodes["event:2"]["orphan"] and not nodes["event:3"]["orphan"]
    edges = {(e["source"], e["target"], e["via"]) for e in graph["edges"]}
    assert edges == {
        ("event:1", "event:2", "OPT_A"),
        ("event:1", "event:99", "OPT_B"),
        ("decision:my_dec", "event:3", "effect"),
        ("on_action:on_yearly_pulse", "event:2", "weight 1000"),
    }
