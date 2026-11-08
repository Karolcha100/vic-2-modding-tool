from pathlib import Path

from vic2toolmod.analysis.poptypes import influences, pop_weights, promotion_graph
from vic2toolmod.workspace import Workspace


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="latin-1")


def test_weights_graph_and_influences(tmp_path):
    g = tmp_path / "game"
    write(
        g / "common/issues.txt",
        "social_reforms = { trade_unions = { no_trade_unions = { } all_trade_unions = { } } }\n",
    )
    write(g / "poptypes/capitalists.txt", "sprite = 1\n")
    write(
        g / "poptypes/craftsmen.txt",
        """
sprite = 2
promote_to = {
    capitalists = {
        factor = 0.01
        modifier = { factor = 10 trade_unions = all_trade_unions }
        modifier = { factor = 0 literacy = 0.2 }
    }
}
migration_target = { factor = 1 modifier = { factor = 2 trade_unions = no_trade_unions } }
""",
    )
    ws = Workspace.open(g)
    weights = pop_weights(ws)
    promo = [w for w in weights if w.kind == "promote_to"]
    assert [(w.pop, w.target, w.base) for w in promo] == [("craftsmen", "capitalists", 0.01)]
    assert [m.factor for m in promo[0].modifiers] == [10, 0]
    assert promo[0].modifiers[0].refs == (
        ("issue", "trade_unions"),
        ("issue_option", "all_trade_unions"),
    )
    assert promo[0].modifiers[1].conditions == "literacy = 0.2"
    table = influences(weights)
    assert [(w.pop, w.kind) for w, _ in table[("issue_option", "no_trade_unions")]] == [
        ("craftsmen", "migration_target")
    ]
    graph = promotion_graph(weights)
    assert {n["id"] for n in graph["nodes"]} == {"capitalists", "craftsmen"}
    assert graph["edges"][0]["modifiers"][0]["refs"] == [
        ["issue", "trade_unions"],
        ["issue_option", "all_trade_unions"],
    ]
