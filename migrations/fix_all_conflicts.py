"""Resolve all merge conflicts - keep the incoming (e7394c9) version."""
import os
import re

def fix_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if "<<<<<<< HEAD" not in content:
        return False
    out = []
    i = 0
    lines = content.split("\n")
    if not content.endswith("\n"):
        lines.append("")
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("<<<<<<< HEAD"):
            # Skip until =======
            i += 1
            while i < len(lines) and "=======" not in lines[i]:
                i += 1
            i += 1  # skip =======
            # Keep until >>>>>>>
            while i < len(lines) and ">>>>>>>" not in lines[i]:
                out.append(lines[i])
                i += 1
            i += 1  # skip >>>>>>>
            continue
        out.append(line)
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return True

root = r"d:\TOTLI BI"
for dirpath, dirnames, filenames in os.walk(root):
    if "node_modules" in dirpath or ".git" in dirpath:
        continue
    for fn in filenames:
        if fn == "fix_all_conflicts.py":
            continue
        path = os.path.join(dirpath, fn)
        try:
            if fix_file(path):
                print("Fixed:", path)
        except Exception as e:
            print("Error", path, e)

print("Done")
