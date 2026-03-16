"""Remove merge conflict block from main.py"""
with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

out = []
skip = False
i = 0
while i < len(lines):
    line = lines[i]
    if "# CONFLICT_REMOVE_START" in line:
        skip = True
        i += 1
        continue
    if skip:
        if "=======" in line and ">>>>>>>" in lines[i+1] if i+1 < len(lines) else False:
            i += 2  # skip ======= and >>>>>>>
            skip = False
            continue
        if ">>>>>>>" in line:
            skip = False
            i += 1
            continue
        i += 1
        continue
    out.append(line)
    i += 1

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(out)
print("Done")
