import json, sys, re
path = sys.argv[1]
text = open(path).read()
blocks = text.split("### NAME: ")[1:]
for b in blocks:
    name = b.split("\n", 1)[0].strip()
    print("### " + name)
    m = re.search(r"^CLAIM: (.*)$", b, re.M)
    if m:
        print("CLAIM: " + m.group(1))
    m = re.search(r"^DISTINGUISHING: (.*)$", b, re.M)
    if m:
        print("DISTINGUISHING: " + m.group(1))
    m = re.search(r"^RECIPE:\n(\{.*?\n\})\s*$", b, re.S | re.M)
    if not m:
        m = re.search(r"RECIPE:\n(\{.*)", b, re.S)
    if m:
        try:
            r = json.loads(m.group(1))
        except Exception as e:
            print("  [recipe parse failed: %s]" % e)
            print()
            continue
        for key in ("setup", "assert", "notes"):
            if key in r:
                print(key.upper() + ":")
                for line in r[key]:
                    print("  - " + str(line))
        for key in ("setup_api_calls", "trigger"):
            if key in r:
                print(key.upper() + " CALLS:")
                for c in r[key]:
                    if isinstance(c, dict):
                        print("  - %s as %s" % (c.get("call"), c.get("as")))
                    else:
                        print("  - " + str(c))
    print()
