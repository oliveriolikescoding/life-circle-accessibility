#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
life_circle.py —— 15 分钟生活圈评估（多设施可达性 + 完备度评分）

做什么：
    1. 读住宅单元（点）和 5 类设施（医疗/教育/购物/公园/地铁）
    2. 在米制投影下给每个住宅单元算到每类设施的**最近距离**
    3. 按「15 分钟 = 1000 米（直线）」判定可达，汇总成 0–5 的**完备度**
    4. 出图：完备度分级地图 + 完备度分布 + 各类设施可达率

为什么这样做：
    单设施「覆盖范围」只能回答「离地铁远不远」；真实的生活圈是**多类服务同时可达**。
    把 5 个布尔列加起来，就是一个能排序、能筛客户、能讲结论的评分。

用法：
    python life_circle.py --homes data/homes.geojson --facilities data/facilities.geojson \
        --radius 1000 --map life_circle_map.png
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

import carto
from carto import PALETTE

BASE = Path(__file__).resolve().parent
UTM = "EPSG:32648"

CATS = ("医疗", "教育", "购物", "公园", "地铁")

# 完备度 5 档：颜色 + 形状 + 尺寸三重编码（转灰度、打印黑白也要分得出来）
# 方 / 圆 / 空心圆 / 三角 / 叉，五个形状本身就带顺序感
LEVELS = [
    {"key": "5", "name": "完整", "desc": "5 类全可达", "color": "#0E5D4E",
     "marker": "s", "size": 10.0, "hollow": False, "edge": "white", "lw": 0.35},
    {"key": "4", "name": "良好", "desc": "缺 1 类", "color": "#2E7D6B",
     "marker": "o", "size": 8.2, "hollow": False, "edge": "white", "lw": 0.35},
    {"key": "3", "name": "一般", "desc": "缺 2 类", "color": "#6E8B3D",
     "marker": "o", "size": 6.4, "hollow": True, "edge": "#6E8B3D", "lw": 1.2},
    {"key": "2", "name": "薄弱", "desc": "缺 3 类", "color": "#B07A2E",
     "marker": "^", "size": 7.4, "hollow": False, "edge": "white", "lw": 0.35},
    {"key": "0-1", "name": "不达标", "desc": "缺 4–5 类", "color": "#A63A17",
     "marker": "X", "size": 9.0, "hollow": False, "edge": "#7A2A10", "lw": 0.8},
]


def level_of(score: int) -> str:
    if score >= 5:
        return "5"
    if score == 4:
        return "4"
    if score == 3:
        return "3"
    if score == 2:
        return "2"
    return "0-1"


# --------------------------------------------------------------------------- #
# 分析
# --------------------------------------------------------------------------- #

def load_data(homes_path: str, facilities_path: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    homes = gpd.read_file(homes_path)
    fac = gpd.read_file(facilities_path)
    if homes.crs is None:
        homes = homes.set_crs(4326)
    if fac.crs is None:
        fac = fac.set_crs(4326)
    homes_m = homes.to_crs(UTM)
    fac_m = fac.to_crs(UTM)
    print(f"✅ 住宅单元 {len(homes)} 个；设施 {len(fac)} 个（" +
          "、".join(f"{c}{int((fac['类别'] == c).sum())}" for c in CATS) + "）")
    return homes_m, fac_m


def compute_accessibility(homes_m: gpd.GeoDataFrame, fac_m: gpd.GeoDataFrame,
                          radius: float, five_min: float) -> gpd.GeoDataFrame:
    """五类设施各做一次最近邻；空值不填 0（填 0 会伪造出完美生活圈）。"""
    out = homes_m.reset_index(drop=True).copy()
    out["_id"] = range(len(out))

    missing = []
    for cat in CATS:
        sub = fac_m[fac_m["类别"] == cat]
        if sub.empty:
            missing.append(cat)
            out[f"dist_{cat}"] = float("nan")
            out[f"neb_{cat}"] = False
            continue
        j = gpd.sjoin_nearest(out[["_id", "geometry"]], sub[["geometry"]],
                              distance_col=f"dist_{cat}", how="left")
        j = j.drop_duplicates("_id").set_index("_id").reindex(out["_id"])
        out[f"dist_{cat}"] = j[f"dist_{cat}"].values
        out[f"neb_{cat}"] = out[f"dist_{cat}"] <= radius
    if missing:
        print(f"⚠️  以下类别在数据里没有任何设施，全程记不可达：{missing}")

    out["完备度"] = out[[f"neb_{c}" for c in CATS]].sum(axis=1).astype(int)
    out["档位"] = out["完备度"].map(level_of)
    for cat in CATS:
        out[f"近_{cat}"] = out[f"dist_{cat}"] <= five_min
    return out


def summarize(out: gpd.GeoDataFrame, radius: float, five_min: float) -> pd.DataFrame:
    total = len(out)
    print("\n—— 完备度分布 ——")
    dist = out["完备度"].value_counts().reindex(range(6), fill_value=0).sort_index(ascending=False)
    for k, v in dist.items():
        print(f"  完备度 {k}（{ {lv['key']: lv['name'] for lv in LEVELS}.get(level_of(k), '')}）："
              f"{v:4d} 个 · {v / total * 100:5.1f}%")

    print(f"\n—— 各类设施 {radius:g} m 可达率 ——")
    rows = []
    for cat in CATS:
        rate = out[f"neb_{cat}"].mean() * 100
        rate5 = out[f"近_{cat}"].mean() * 100
        med = out[f"dist_{cat}"].median()
        rows.append({"类别": cat, f"{radius:g}m 可达率": f"{rate:.1f}%",
                     f"{five_min:g}m 可达率": f"{rate5:.1f}%",
                     "最近距离中位数": f"{med:.0f} m"})
    stats = pd.DataFrame(rows)
    print(stats.to_string(index=False))
    full = int((out["完备度"] == 5).sum())
    worst = int((out["完备度"] <= 1).sum())
    print(f"\n完全达标（5/5）：{full} 个（{full / total * 100:.1f}%）；"
          f"不达标（≤1 类可达）：{worst} 个（{worst / total * 100:.1f}%）")
    return stats


# --------------------------------------------------------------------------- #
# 出图
# --------------------------------------------------------------------------- #

def plot_map(out: gpd.GeoDataFrame, stats: pd.DataFrame, radius: float,
             out_png: str, basemap: gpd.GeoDataFrame | None, dpi: int = 300,
             crs_label: str = "EPSG:32648", title: str | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib import patheffects
    import _caption as C

    zh = carto.setup_chinese_font()

    bb = out.total_bounds
    pad_x = (bb[2] - bb[0]) * 0.03
    pad_y = (bb[3] - bb[1]) * 0.03
    W, H = (bb[2] - bb[0]) + 2 * pad_x, (bb[3] - bb[1]) + 2 * pad_y

    fig_w, fig_h = 14.4, 9.0
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(PALETTE["page"])

    # 左：地图框按数据长宽比算，避免要素被裁（下方留出图例条与图廓外注记）
    AREA = (0.045, 0.228, 0.505, 0.632)
    area_w_in, area_h_in = AREA[2] * fig_w, AREA[3] * fig_h
    if W / H >= area_w_in / area_h_in:
        w_in = area_w_in
        h_in = w_in * H / W
    else:
        h_in = area_h_in
        w_in = h_in * W / H
    ax = fig.add_axes([AREA[0], AREA[1] + (area_h_in - h_in) / 2 / fig_h, w_in / fig_w, h_in / fig_h])
    ax.set_xlim(bb[0] - pad_x, bb[2] + pad_x)
    ax.set_ylim(bb[1] - pad_y, bb[3] + pad_y)
    ax.set_aspect("equal")
    ax.set_facecolor("#FCFDFE")
    ax.axis("off")
    fig.canvas.draw()

    # 底图区县界线（仅作空间参照）
    if basemap is not None and len(basemap):
        from shapely.geometry import box

        bm = basemap.to_crs(utm_crs_of(out))
        cand = bm[bm.intersects(box(bb[0], bb[1], bb[2], bb[3]))]
        if not len(cand):
            cand = bm
        cand.plot(ax=ax, color=PALETTE["basemap_face"], edgecolor=PALETTE["basemap_edge"],
                  linewidth=0.45, zorder=0)
        for _, row in cand.iterrows():
            pt = row.geometry.representative_point()
            if not (bb[0] - pad_x < pt.x < bb[2] + pad_x and bb[1] - pad_y < pt.y < bb[3] + pad_y):
                continue
            label = str(row.get("name", "") or "")
            if label:
                ax.text(pt.x, pt.y, label, fontsize=6.6, color=PALETTE["district_text"],
                        ha="center", va="center", zorder=1,
                        path_effects=[patheffects.withStroke(linewidth=2.0,
                                                             foreground="white", alpha=0.9)])

    # 专题层：完备度分级（颜色 + 形状 + 尺寸）
    handles = []
    for lv in LEVELS:
        sub = out[out["档位"] == lv["key"]]
        if not sub.empty:
            sub.plot(ax=ax, marker=lv["marker"], markersize=lv["size"],
                     facecolor="white" if lv["hollow"] else lv["color"],
                     edgecolor=lv["edge"], linewidth=lv["lw"], zorder=4)
        handles.append(Line2D([], [], marker=lv["marker"], linestyle="none",
                              markerfacecolor="white" if lv["hollow"] else lv["color"],
                              markeredgecolor=lv["edge"], markeredgewidth=lv["lw"],
                              markersize=lv["size"] * 0.95,
                              label=f"{lv['name']}（{lv['desc']}）"))

    carto.frame_and_ticks(ax, crs_note=None)
    # 指北针留在图廓内并贴上框线，横向位置取顶边一处无点位的空列
    import numpy as _np
    xs, ys = out.geometry.x.values, out.geometry.y.values
    xa, xb = ax.get_xlim(); ya, yb = ax.get_ylim()
    Wm, Hm = xb - xa, yb - ya
    best_x = None
    for fx in _np.arange(0.04, 0.91, 0.01):
        cx, cy = xa + fx * Wm, ya + 0.950 * Hm
        if ((_np.abs(xs - cx) < 0.045 * Wm) & (_np.abs(ys - cy) < 0.030 * Hm)).sum() == 0:
            best_x = fx
    pos = (best_x, 0.928) if best_x is not None else (0.944, 0.900)
    carto.north_arrow(ax, *pos)
    carto.scale_bar(ax)
    carto.scale_bar(ax)

    fig.text(AREA[0], ax.get_position().y1 + 0.017, "（a）住宅单元完备度分级",
             fontsize=10.8, color=PALETTE["title"], ha="left", va="center")

    # 图例独立成条放在地图下方，与图廓外坐标注记、图题各留空隙
    ax_leg = fig.add_axes([0.045, 0.108, 0.505, 0.066])
    ax_leg.axis("off")
    ax_leg.legend(handles=handles, loc="upper left", ncol=5, frameon=False, fontsize=8.0,
                  handletextpad=0.7, columnspacing=1.7, borderpad=0.0, labelspacing=0.3,
                  title="完备度分级（1 000 m 内可达类别数）",
                  title_fontsize=8.2, alignment="left")

    # 右：完备度分布 + 各类可达率
    ax_bar = fig.add_axes([0.595, 0.462, 0.372, 0.352])
    counts = out["完备度"].value_counts().reindex(range(6), fill_value=0)
    labels, colors, vals = [], [], []
    for lv in LEVELS:
        if lv["key"] == "0-1":
            v = int(counts[0] + counts[1])
            labels.append("不达标 0–1")
        else:
            v = int(counts[int(lv["key"])])
            labels.append(f"{lv['name']} {lv['key']}")
        colors.append(lv["color"])
        vals.append(v)
    bars = ax_bar.bar(range(len(vals)), vals, color=colors, width=0.62, zorder=3)
    for rect, v in zip(bars, vals):
        ax_bar.text(rect.get_x() + rect.get_width() / 2, v + max(vals) * 0.02,
                    f"{v}\n{v / len(out) * 100:.0f}%", ha="center", va="bottom",
                    fontsize=8.2, color="#2B3A47", linespacing=1.1)
    ax_bar.set_xticks(range(len(vals)))
    ax_bar.set_xticklabels(labels, fontsize=8.2, color="#3D4B5C")
    ax_bar.set_ylim(0, max(vals) * 1.22)
    ax_bar.set_ylabel("住宅单元数", fontsize=8.8, color="#3D4B5C")
    ax_bar.set_xlabel("完备度（1000 m 内可达类别数）", fontsize=8.6, color="#3D4B5C")
    ax_bar.set_title("（b）完备度分布", fontsize=10.6, color=PALETTE["title"], loc="left", pad=8)
    ax_bar.grid(axis="y", color="#E8EDF2", linewidth=0.6, zorder=0)
    ax_bar.set_axisbelow(True)
    for s in ("top", "right"):
        ax_bar.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax_bar.spines[s].set_color("#C9D4DF")
    ax_bar.tick_params(colors="#5C6B7A", labelsize=8.2)

    ax_rate = fig.add_axes([0.595, 0.146, 0.372, 0.230])
    rates = [out[f"neb_{c}"].mean() * 100 for c in CATS]
    y = range(len(CATS))
    ax_rate.barh(list(y), [100] * len(CATS), color="#EDF1F5", height=0.55, zorder=2)
    ax_rate.barh(list(y), rates, color="#3E6B85", height=0.55, zorder=3)
    for i, (cat, r) in enumerate(zip(CATS, rates)):
        n = int(out[f"neb_{cat}"].sum())
        txt = f"{r:.0f}%（{n}/{len(out)}）"
        if r >= 55:
            ax_rate.text(r - 2.5, i, txt, va="center", ha="right", fontsize=8.2, color="white")
        else:
            ax_rate.text(r + 2.5, i, txt, va="center", ha="left", fontsize=8.2, color="#2B3A47")
    ax_rate.set_yticks(list(y))
    ax_rate.set_yticklabels(CATS, fontsize=8.6, color="#3D4B5C")
    ax_rate.invert_yaxis()
    ax_rate.set_xlim(0, 100)
    ax_rate.set_xlabel(f"{radius:g} m 内可达的住宅单元占比", fontsize=8.6, color="#3D4B5C")
    ax_rate.set_title("（c）各类设施可达率", fontsize=10.6, color=PALETTE["title"], loc="left", pad=8)
    ax_rate.grid(axis="x", color="#E8EDF2", linewidth=0.6, zorder=0)
    ax_rate.set_axisbelow(True)
    for s in ("top", "right"):
        ax_rate.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax_rate.spines[s].set_color("#C9D4DF")
    ax_rate.tick_params(colors="#5C6B7A", labelsize=8.2)
    from matplotlib.ticker import FuncFormatter
    ax_rate.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))

    # 图题与图注置于图下
    total = len(out)
    full = int((out["完备度"] == 5).sum())
    notes = [
        f"成都中心城区 {total} 个住宅单元，完备度为五类设施在 {radius:g} m 内可达的类别数，取值 0 至 5；完备度 5 的单元 {full} 个（{full / total * 100:.1f}%）",
        f"投影 {crs_label}（WGS 84 / UTM zone 48N），距离为住宅片区质心至设施中心点的直线距离，不含步行或路网成本",
        f"可达口径为 15 分钟约 {radius:g} m（按步行 4 km/h 折算）",
        "设施与住宅面据 OpenStreetMap contributors（ODbL，2026-11 抓取）绘制；区县界据 DataV.GeoAtlas，仅作空间参照，非法定界线",
        f"制图日期 {_dt.date.today().isoformat()}；本图为示意性专题图，非标准地图，无审图号",
    ]
    C.add_caption(fig, 1, "成都中心城区住宅单元 15 分钟生活圈完备度", notes, lb=0.045, rb=0.955, pad=0.16)



    # 对比度自检（5 档全部过一遍 3:1）
    print("\n—— 对比度自检（对白底，WCAG SC 1.4.11 门槛 3:1）——")
    for lv in LEVELS:
        r = carto.contrast_ratio(lv["color"], PALETTE["page"])
        print(f"   {lv['name']:4s} {lv['color']}  {r:.2f} : 1  "
              f"{'OK' if r >= 3 else '低于 3:1'}")

    plt.savefig(out_png, dpi=dpi, facecolor=PALETTE["page"])
    # 另存一份矢量 SVG（文字转字形轮廓），GitHub 能直接渲染，不受本机字体影响
    out_svg = Path(out_png).with_suffix(".svg")
    plt.rcParams["svg.fonttype"] = "path"
    plt.savefig(out_svg, facecolor=PALETTE["page"])
    plt.close(fig)
    print(f"\n✅ 地图已保存：{out_png}（{dpi} dpi）")
    print(f"✅ 矢量版：{out_svg}")


def utm_crs_of(gdf: gpd.GeoDataFrame) -> str:
    return gdf.crs.to_string() if gdf.crs is not None else UTM


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="15 分钟生活圈评估：多设施可达性 + 完备度评分")
    p.add_argument("--homes", default="data/homes.geojson", help="住宅单元（点或面，默认取质心）")
    p.add_argument("--facilities", default="data/facilities.geojson", help="设施（点，含 类别 字段）")
    p.add_argument("--radius", type=float, default=1000.0, help="15 分钟可达半径（米，默认 1000）")
    p.add_argument("--five-min", type=float, default=400.0, help="5 分钟半径（米，默认 400）")
    p.add_argument("--map", default="life_circle_map.png", help="输出地图（给空字符串则不画）")
    p.add_argument("--csv", default="life_circle_scores.csv", help="评分结果表")
    p.add_argument("--geojson", default="data/life_circle_scores.geojson",
                   help="带评分的 GeoJSON（给 QGIS 用）")
    p.add_argument("--basemap", default=None, help="区县界线 GeoJSON（可选）")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--title", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    homes_m, fac_m = load_data(args.homes, args.facilities)

    # 住宅如果是面，先取质心（GeoJSON 里也可能已经是点）
    if (homes_m.geom_type == "Polygon").any():
        homes_m = homes_m.set_geometry(homes_m.geometry.centroid)

    out = compute_accessibility(homes_m, fac_m, args.radius, args.five_min)
    stats = summarize(out, args.radius, args.five_min)

    # 导出（经纬度，给 QGIS / 客户）
    ll = out.to_crs(4326).copy()
    ll["经度"] = ll.geometry.x
    ll["纬度"] = ll.geometry.y
    cols = (["单元名", "面积_㎡", "完备度", "档位"] + [f"dist_{c}" for c in CATS]
            + [f"neb_{c}" for c in CATS] + ["经度", "纬度"])
    for c in CATS:
        cols.append(f"近_{c}")
    table = ll[[c for c in cols if c in ll.columns]].copy()
    table = table.rename(columns={f"dist_{c}": f"最近{c}_米" for c in CATS})
    table = table.rename(columns={f"neb_{c}": f"可达{c}" for c in CATS})
    table = table.rename(columns={f"近_{c}": f"5分内{c}" for c in CATS})
    for c in table.columns:
        if table[c].dtype == bool:
            table[c] = table[c].map({True: "是", False: "否"})
    if args.csv:
        table.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"✅ 评分表已导出：{args.csv}")
    if args.geojson:
        ll[[c for c in (["单元名", "完备度", "档位"] + [f"dist_{c}" for c in CATS] + ["geometry"])
            if c in ll.columns]].to_file(args.geojson, driver="GeoJSON")
        print(f"✅ GeoJSON 已导出：{args.geojson}（可直接拖进 QGIS）")

    if args.map:
        basemap = None
        if args.basemap:
            bm_path = Path(args.basemap)
            if bm_path.exists():
                basemap = gpd.read_file(bm_path)
                if basemap.crs is None:
                    basemap = basemap.set_crs(4326)
                print(f"✅ 底图：{bm_path.name} → {len(basemap)} 个区县面")
            else:
                print(f"⚠️  底图不存在，跳过：{bm_path}")
        plot_map(out, stats, args.radius, args.map, basemap,
                 dpi=args.dpi, crs_label="EPSG:32648", title=args.title)
    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())


