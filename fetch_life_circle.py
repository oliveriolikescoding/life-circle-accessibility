# -*- coding: utf-8 -*-
"""第四周数据抓取：住宅小区 + 5 类设施（OSM Overpass）"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(r"C:\Users\kitagawa\Documents\GIS专题\life-circle-accessibility\raw")
OUT.mkdir(parents=True, exist_ok=True)

BBOXES = [
    ("core_sw", "30.60,104.00,30.68,104.08"),
    ("core_se", "30.60,104.08,30.68,104.16"),
    ("core_nw", "30.68,104.00,30.76,104.08"),
    ("core_ne", "30.68,104.08,30.76,104.16"),
]

QUERY = """
[out:json][timeout:180];
(
  way["landuse"="residential"]({bbox});
  node["amenity"~"^(hospital|clinic)$"]({bbox});
  node["amenity"~"^(school|kindergarten)$"]({bbox});
  node["shop"~"^(supermarket|convenience)$"]({bbox});
  way["leisure"="park"]({bbox});
  node["railway"="station"]["station"="subway"]({bbox});
);
out center;
"""

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def fetch(q, tag):
    for ep in ENDPOINTS:
        for attempt in range(3):
            try:
                data = urllib.parse.urlencode({"data": q}).encode()
                req = urllib.request.Request(ep, data=data, headers={"User-Agent": "gis-demo/1.0"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    obj = json.loads(r.read().decode("utf-8"))
                path = OUT / f"{tag}.json"
                json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False)
                print(f"  OK {tag}: {len(obj['elements'])} elements  ({ep.split('/')[2]})", flush=True)
                return True
            except Exception as e:
                print(f"  FAIL {tag} {ep.split('/')[2]} try{attempt+1}: {type(e).__name__}", flush=True)
                time.sleep(3 + attempt * 4)
    return False


for name, bbox in BBOXES:
    print(f"[{name}] {bbox}", flush=True)
    fetch(QUERY.format(bbox=bbox), name)
    time.sleep(2)
print("done")
