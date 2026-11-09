#@ name: Set the value of a key
#@ description: Give every "key = value" in the chosen files a new value, e.g. all "mean_time_to_happen" months, or "ai_chance" factors. Works on the syntax tree, so comments and spacing stay as they are.
#@ param: files = events/*.txt | which files (* also crosses folders)
#@ param: key | the key (any case), e.g. months
#@ param: only_if | change only this old value (empty = any value)
#@ param: inside | change only inside a block with this key, e.g. mean_time_to_happen (empty = anywhere)
#@ param: value | the new value
from vic2toolmod.edit import apply_edits, replace_token_text
from vic2toolmod.script.cst import Assignment, Block, Scalar

key = params["key"].lower()
inside = params["inside"].lower()


def assignments(items, in_block):
    """Assignments of a block, with: is this inside the wanted block?"""
    for item in items:
        if isinstance(item, Assignment):
            yield item, in_block
            if isinstance(item.value, Block):
                yield from assignments(
                    item.value.items, in_block or item.key_text.lower() == inside
                )


total = 0
for rel in mod.files(params["files"]):
    doc = mod.document(rel)
    edits = []
    for a, in_block in assignments(doc.items, not inside):
        if a.key_text.lower() != key or not in_block or not isinstance(a.value, Scalar):
            continue
        if params["only_if"] and a.value.value != params["only_if"]:
            continue
        if a.value.value != params["value"]:
            edits.append(replace_token_text(a.value, params["value"]))
    if edits:
        mod.write(rel, apply_edits(doc.text, edits))
        print(f"{rel}: {len(edits)}")
        total += len(edits)
print(f"{total} value(s) changed")
