#!/usr/bin/env python3
import json
import os

config_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(config_path) as f:
    d = json.load(f)

# Remove staticServe (not a valid gateway config key)
if "staticServe" in d.get("gateway", {}):
    del d["gateway"]["staticServe"]

with open(config_path, "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print("Removed staticServe.")
print(json.dumps(d.get("gateway", {}), indent=2))