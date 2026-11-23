"""One review interface shared by the local CLI session, offline export and worked site example."""
from importlib.resources import files
import json


def asset(name: str) -> str:
    return files("tessri").joinpath("assets", name).read_text(encoding="utf-8")


def render(data: dict, *, live: bool = False, example: bool = False, embedded: bool = False) -> str:
    payload = json.dumps({**data, "live": live, "example": example}, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    body = asset("review.html") + '<script id="review-data" type="application/json">' + payload + '</script><script>' + asset("review.js") + '</script>'
    if embedded:
        return '<style>' + asset("review.css") + '</style>' + body
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tessri · Local review</title><style>' + asset("review.css") + '</style></head><body>' + body + '</body></html>\n'
