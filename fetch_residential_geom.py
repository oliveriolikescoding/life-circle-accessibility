# -*- coding: utf-8 -*-
"""住宅面几何单独抓一份：要算真实面积，不能只用 Overpass 给的 bbox 中心点"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(r"C:\Users\kitagawa\Documents\GIS专题\life-circle-accessibility\raw")
OUT.mkdir(parents=True, exist_ok=True)

BBOXES = [
    ("res_sw", "30.60,104.00,30.68,104.08"),
    ("res_se", "30.60,104.08,30.68,104.16"),
    ("res_nw", "30.68,104.00,30.76,104.08"),
    ("res_ne", "30.68,104.08,30.76,104.16"),
]

QUERY = """
[out:json][timeout:180];
way["landuse"="residential"]({bbox});
out geom;
"""

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def fetch(q, tag):
    for ep in ENDPOINTS:
        for attempt in range(3):
            try:
                data = urllib.parse.urlencode({"data": q}).encode()
                req = urllib.request.Request(ep, data=data, headers={"User-Agent": "gis-demo/1.0"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    obj = json.loads(r.read().decode("utf-8"))
                json.dump(obj, open(OUT / f"{tag}.json", "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  OK {tag}: {len(obj['elements'])} ways", flush=True)
                return True
            except Exception as e:
                print(f"  FAIL {tag} try{attempt+1}: {type(e).__name__}", flush=True)
                time.sleep(3 + attempt * 4)
    return False


for name, bbox in BBOXES:
    print(f"[{name}]", flush=True)
    fetch(QUERY.format(bbox=bbox), name)
    time.sleep(2)
print("done")
