#@ name: Replace text in files
#@ description: Replace a text (or a regular expression) in many files of the mod. Shows the changes first; nothing is written until you apply them.
#@ param: files = events/*.txt | which files (* also crosses folders, e.g. events/501_*.txt or *.txt for all)
#@ param: old | the text to find (case matters)
#@ param: new | what to put instead (may be empty)
#@ param: regex:bool = no | "old" is a Python regular expression ("new" may use \1, \g<name>)

count = mod.replace(params["old"], params["new"], files=params["files"], regex=params["regex"])
print(f"{count} replacement(s) in {len(mod.changes)} file(s)")
for change in mod.changes:
    print(" ", change.rel)
