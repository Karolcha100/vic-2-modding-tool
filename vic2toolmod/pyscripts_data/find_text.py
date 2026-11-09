#@ name: Find text in files
#@ description: List every line that contains a text (or matches a regular expression). Changes nothing.
#@ param: files = *.txt | which files (* also crosses folders)
#@ param: text | the text to find (case matters)
#@ param: regex:bool = no | "text" is a Python regular expression
#@ param: game:bool = no | also search the game files the mod does not replace

found = mod.find(
    params["text"], files=params["files"], regex=params["regex"], only_mod=not params["game"]
)
for m in found:
    print(f"{m.rel}:{m.line}: {m.text}")
print(f"{len(found)} line(s) in {len({m.rel for m in found})} file(s)")
