import sys
path, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
lines = open(path).read().splitlines()[lo-1:hi]
out, skipping = [], False
for ln in lines:
    stripped = ln.strip()
    indent = len(ln) - len(ln.lstrip())
    if stripped.startswith("setup_api_calls:"):
        skipping = True
        out.append(" " * indent + "setup_api_calls: [omitted]")
        continue
    if skipping:
        if stripped and indent <= 10 and stripped.endswith(":"):
            skipping = False
        else:
            continue
    out.append(ln)
print("\n".join(out))
