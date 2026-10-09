# Runs one conversion in its own process (killed on timeout by app.py). Prints JSON to stdout.
import sys, json, base64, os
from dwgread import read_dwg
dwg, tmp = sys.argv[1], sys.argv[2]
r = read_dwg(dwg, tmp, os.environ.get("LR_BIN", "/opt/lr/bin"))
if r.get("png"):
    with open(r["png"], "rb") as f: r["png"] = base64.b64encode(f.read()).decode()
print(json.dumps(r))
