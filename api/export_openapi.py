"""
api/export_openapi.py -- writes api/openapi.json, the contract the front end builds its types from (WEBSITE_DESIGN.md 1.4). Run after any change to a route or a schema:
    python api/export_openapi.py
test_api_health.py fails if the committed file differs from what the app now produces.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def render():
    from api.main import app
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    with open(os.path.join(HERE, "openapi.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render())
    print("wrote api/openapi.json")
