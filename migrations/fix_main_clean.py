"""Remove orphaned/duplicate routes from main.py - keep only refactored structure"""
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the block to remove: from "    # Fake user for testing" through ">>>>>>> e7394c9"
start_marker = "    # Fake user for testing"
end_marker = ">>>>>>> e7394c9 (TOTLI BI: Backend + Flutter mobil ilova)"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)
if start_idx == -1 or end_idx == -1:
    print("Markers not found")
    exit(1)

# Keep: before start, the replacement (between ======= and >>>>>>>), and after >>>>>>>
before = content[:start_idx]
# Find ======= and get content between ======= and >>>>>>>
eq_idx = content.find("=======", start_idx)
replacement = content[eq_idx:end_idx].replace("=======\n", "").replace("=======", "")
after = content[end_idx + len(end_marker):].lstrip()

# The replacement has the comments we want - but it also has >>>>>>> at the end
replacement = content[eq_idx + 9:end_idx]  # Skip "=======\n"

result = before + replacement + "\n\n" + after
with open("main.py", "w", encoding="utf-8") as f:
    f.write(result)
print("Cleaned")
