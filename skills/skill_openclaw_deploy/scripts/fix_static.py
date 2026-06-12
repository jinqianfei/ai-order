#!/usr/bin/env python3
import json
import os

config_path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(config_path) as f:
    d = json.load(f)

# Enable static file serving
d.setdefault("gateway", {})
d["gateway"]["staticServe"] = {"enabled": True}

with open(config_path, "w") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

print("Done. staticServe enabled.")