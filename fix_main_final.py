"""Remove old routes block - keep only up to comments and then startup"""
with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find OLD_ROUTES_BLOCK_START and @app.on_event("startup")
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if "OLD_ROUTES_BLOCK_START" in line:
        start_idx = i  # Remove this line and everything after until...
    if start_idx is not None and '@app.on_event("startup")' in line and 'async def startup' in (lines[i+1] if i+1 < len(lines) else ""):
        end_idx = i
        break

if start_idx is None or end_idx is None:
    print("Markers not found", start_idx, end_idx)
    exit(1)

# Keep lines 0 to start_idx-1, then lines end_idx to end
result = lines[:start_idx] + lines[end_idx:]
with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(result)
print("Removed lines", start_idx, "to", end_idx-1)
