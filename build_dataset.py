# -*- coding: utf-8 -*-
"""
build_dataset.py —— 把 Overpass 抓下来的原始 JSON 整理成可直接分析的 GeoJSON

清洗四件事（对应第四周周一任务）：
  1. 按 way id 去重（四块 bbox 拼接，边界上的要素会重复）
  2. 住宅面算真实面积，剔掉面积 < 2000 m² 的碎面
  3. 类别用写死的字典映射，不做模糊匹配
  4. 坐标异常 / 几何破损的剔除
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

BASE = Path(__file__).resolve().parent
RAW = BASE / "raw"
OUT = BASE / "data"
OUT.mkdir(exist_ok=True)

UTM = "EPSG:32648"
MIN_AREA_M2 = 2000

# ---- 类别映射（写死，不做模糊匹配）----
LEVEL4 = {"hospital": "医疗", "clinic": "医疗",
          "school": "教育", "kindergarten": "教育"}
SHOP = {"supermarket": "购物", "convenience": "购物"}


def classify(tags: dict) -> str | None:
    if tags.get("amenity") in LEVEL4:
        return LEVEL4[tags["amenity"]]
    if tags.get("shop") in SHOP:
        return SHOP[tags["shop"]]
    if tags.get("leisure") == "park":
        return "公园"
    if tags.get("railway") == "station" and tags.get("station") == "subway":
        return "地铁"
    return None


# --------------------------------------------------------------------------- #
# 1) 设施
# --------------------------------------------------------------------------- #

def load_facilities() -> gpd.GeoDataFrame:
    rows, seen = [], set()
    n_raw = n_nocat = 0
    for f in sorted(RAW.glob("core_*.json")):
        for el in json.loads(f.read_text(encoding="utf-8"))["elements"]:
            n_raw += 1
            tags = el.get("tags", {})
            cat = classify(tags)
            if cat is None:
                n_nocat += 1
                continue
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            if lat is None or lon is None:
                continue
            if not (103.8 < lon < 104.4 and 30.4 < lat < 31.0):
                continue
            name = (tags.get("name") or "").strip()
            # 同名同类去重；无名设施按坐标去重（OSM 里同一诊所有时被标两次）
            key = (cat, name) if name else (cat, round(lon, 5), round(lat, 5))
            if key in seen:
                continue
            seen.add(key)
            rows.append({"名称": name or "未命名", "类别": cat, "经度": lon, "纬度": lat})
    print(f"设施：读到 {n_raw} 个元素，非 5 类的 {n_nocat} 个，去重后 {len(rows)} 个")
    gdf = gpd.GeoDataFrame(rows, geometry=gpd.points_from_xy(
        [r["经度"] for r in rows], [r["纬度"] for r in rows]), crs="EPSG:4326")
    return gdf


# --------------------------------------------------------------------------- #
# 2) 住宅区（面 → 中心点 + 面积）
# --------------------------------------------------------------------------- #

def load_homes() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    geoms, attrs, seen_ids = [], [], set()
    for f in sorted(RAW.glob("res_*.json")):
        for el in json.loads(f.read_text(encoding="utf-8"))["elements"]:
            if el["id"] in seen_ids:          # 跨块重复
                continue
            geom_pts = el.get("geometry") or []
            if len(geom_pts) < 4:
                continue
            coords = [(p["lon"], p["lat"]) for p in geom_pts if "lon" in p]
            poly = Polygon(coords)
            if poly.is_empty or not poly.is_valid:
                poly = poly.buffer(0)
                if poly.is_empty:
                    continue
            seen_ids.add(el["id"])
            geoms.append(poly)
            attrs.append({"osmid": el["id"], "名称": (el.get("tags", {}).get("name") or "").strip()})

    gdf = gpd.GeoDataFrame(attrs, geometry=geoms, crs="EPSG:4326")
    print(f"住宅：读到 {len(gdf)} 个有效面")

    area = gdf.to_crs(UTM).geometry.area
    print("面积分位数(㎡)：", {q: round(float(area.quantile(q))) for q in (0.05, 0.25, 0.5, 0.75, 0.9, 0.99)})
    keep = (area >= MIN_AREA_M2)
    print(f"剔掉 < {MIN_AREA_M2} ㎡ 的碎面 {int((~keep).sum())} 个，剩 {int(keep.sum())}")
    gdf = gdf[keep].copy()
    gdf["面积_㎡"] = area[keep].round(0)

    # 质心（在米制坐标里算，再转回经纬度），用来当"小区"的分析单元
    cent = gdf.to_crs(UTM).geometry.centroid
    homes = gpd.GeoDataFrame(
        {"osmid": gdf["osmid"].values, "名称": gdf["名称"].values, "面积_㎡": gdf["面积_㎡"].values},
        geometry=cent.values, crs=UTM).to_crs("EPSG:4326")

    # 相邻质心去重：同一片小区常被拆成多个相邻面，<150 m 的合并（留面积大的）
    homes_m = homes.to_crs(UTM).sort_values("面积_㎡", ascending=False).reset_index(drop=True)
    keep_idx, dropped = [], 0
    for i, geom in enumerate(homes_m.geometry):
        if any(geom.distance(homes_m.geometry[j]) < 150 for j in keep_idx):
            dropped += 1
            continue
        keep_idx.append(i)
    homes_m = homes_m.iloc[keep_idx].reset_index(drop=True)
    print(f"相邻质心合并：去掉 {dropped} 个，最终住宅单元 {len(homes_m)} 个")
    homes_m["单元名"] = [n if n else f"住宅片区{i + 1:03d}" for i, n in enumerate(homes_m["名称"])]
    return homes_m.to_crs("EPSG:4326"), homes_m


def main() -> None:
    homes_ll, _ = load_homes()
    fac = load_facilities()

    homes_ll.to_file(OUT / "homes.geojson", driver="GeoJSON")
    fac.to_file(OUT / "facilities.geojson", driver="GeoJSON")

    print("\n设施分类计数：")
    print(fac["类别"].value_counts().to_string())
    print("\n住宅单元面积中位数：", round(homes_ll.to_crs(UTM).geometry.area.median() if False else
                                    float(homes_ll["面积_㎡"].median())), "㎡")
    print(f"\n导出：data/homes.geojson（{len(homes_ll)}）、data/facilities.geojson（{len(fac)}）")


if __name__ == "__main__":
    main()
