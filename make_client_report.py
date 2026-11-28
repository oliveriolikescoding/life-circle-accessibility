"""生成客户视角样例页：docs/客户视角样例.html

输入：life_circle_scores.csv（1334 个住宅片区 × 五类设施）
输出：docs/客户视角样例.html + docs/sample_figs/{档位分布,缺口分布}.png

客户视角 = 结论先行、按决策组织（这地方行不行 / 差什么 / 先补哪个），
不是把技术口径摊在开头。数据全部来自仓里现成评分表，不造数。
"""
import io
import json
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "docs", "sample_figs")
OUT = os.path.join(HERE, "docs", "客户视角样例.html")

# 中文字体：宋体（图表按项目惯例：中文宋体 + 西文 Times New Roman）
CJK = "SimSun"
if not any(CJK in f.name for f in font_manager.fontManager.ttflist):
    CJK = "Microsoft YaHei"
plt.rcParams.update({
    "font.family": [CJK, "Times New Roman"],
    "axes.unicode_minus": False,
    "figure.dpi": 150,
})

CATS = [("医疗", "最近医疗_米", "可达医疗"), ("教育", "最近教育_米", "可达教育"),
        ("购物", "最近购物_米", "可达购物"), ("公园", "最近公园_米", "可达公园"),
        ("地铁", "最近地铁_米", "可达地铁")]
BAND_ORDER = ["5", "4", "3", "2", "0-1"]
BAND_LABEL = {"5": "五类齐备", "4": "缺 1 类", "3": "缺 2 类", "2": "缺 3 类", "0-1": "缺 4 类以上"}
LEGEND = {"5": "5", "4": "4", "3": "3", "2": "2", "0-1": "0-1"}   # 中文放进图注（图例框内丢字形）
BAND_COLOR = {"5": "#2f7d32", "4": "#7c9b3f", "3": "#d8a13a", "2": "#d2691e", "0-1": "#b3392f"}


def load():
    df = pd.read_csv(os.path.join(HERE, "life_circle_scores.csv"), encoding="utf-8-sig")
    df["档位"] = df["档位"].astype(str)
    return df


def stats(df):
    n = len(df)
    band = Counter(df["档位"])
    reach = {}
    for name, dc, rc in CATS:
        reach[name] = float((df[rc] == "是").mean())
    # 五类各自「差多少米到 1000 m」，只统计未达标的单元
    gap = {}
    for name, dc, rc in CATS:
        s = df.loc[df[rc] != "是", dc] - 1000.0
        gap[name] = float(s.median()) if len(s) else 0.0
    return {"n": n, "band": band, "reach": reach, "gap": gap,
            "full": float((df["完备度"] == 5).mean()),
            "weak": float((df["完备度"] <= 2).mean()),
            "area_med": float(df["面积_㎡"].median())}


def fig_band(st, path):
    fig, ax = plt.subplots(figsize=(6.4, 2.9))
    labels, vals, colors = [], [], []
    for b in BAND_ORDER:
        labels.append("%s（%s）" % (b, BAND_LABEL[b]))
        vals.append(st["band"].get(b, 0))
        colors.append(BAND_COLOR[b])
    bars = ax.barh(labels, vals, color=colors, height=0.62)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_width() + max(vals) * 0.015, bar.get_y() + bar.get_height() / 2,
                "%d 个 · %.0f%%" % (v, v / st["n"] * 100), va="center", fontsize=9)
    ax.set_xlim(0, max(vals) * 1.22)
    ax.set_xlabel("住宅片区数（共 %d 个）" % st["n"], fontsize=9)
    ax.invert_yaxis()
    ax.set_title("中心城区各住宅片区的设施齐备程度", fontsize=11)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=9)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_map(df, path):
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    for b in BAND_ORDER:
        sub = df[df["档位"] == b]
        if not len(sub):
            continue
        ax.scatter(sub["经度"], sub["纬度"], s=9, c=BAND_COLOR[b],
                   label=LEGEND[b], linewidths=0, alpha=0.85)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("经度", fontsize=9)
    ax.set_ylabel("纬度", fontsize=9)
    ax.set_title("短板片区分布（红＝缺 4 类以上，橙＝缺 3 类）", fontsize=11, pad=10)
    ax.legend(fontsize=8, frameon=False, ncol=5, markerscale=2,
              loc="upper center", bbox_to_anchor=(0.5, -0.10))
    ax.tick_params(labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def pick_sample(df):
    """给客户看的「一处具体地方」：取一个完整片区 + 一个只差一类的片区。"""
    good = df[df["完备度"] == 5].sort_values("面积_㎡", ascending=False).iloc[0]
    near = df[(df["完备度"] == 4)].copy()
    if len(near):
        near["最差距离"] = near[[c[1] for c in CATS]].max(axis=1)
        one = near.sort_values("最差距离").iloc[0]
    else:
        one = near.iloc[0] if len(near) else good
    return good, one


def unit_block(u, title):
    rows = []
    for name, dc, rc in CATS:
        d = float(u[dc])
        ok = u[rc] == "是"
        rows.append("<tr><td>%s</td><td>%.0f m</td><td class=\"%s\">%s</td></tr>"
                    % (name, d, "ok" if ok else "no", "15 分钟内" if ok else "超出 · 差 %.0f m" % (d - 1000)))
    return """<div class="unit"><h3>%s</h3>
<p class="meta">%s · 面积 %.0f ㎡ · 完备度 %d/5</p>
<table class="mini">%s</table></div>""" % (title, u["单元名"], float(u["面积_㎡"]), int(u["完备度"]), "".join(rows))


def top_gaps(df):
    """只差一点就能补齐的单元（客户最想知道「补哪儿最划算」）。"""
    s = df[df["完备度"] <= 4].copy()
    s["缺口数"] = 5 - s["完备度"].astype(int)
    s["最缺类别"] = s[[c[1] for c in CATS]].idxmax(axis=1).str.replace("最近|_米", "", regex=True)
    s["最大差距"] = s[[c[1] for c in CATS]].max(axis=1) - 1000
    s = s.sort_values(["缺口数", "最大差距"]).head(10)
    rows = "".join(
        "<tr><td>%s</td><td>%d/5</td><td>%s</td><td>%.0f m</td></tr>"
        % (r["单元名"], int(r["完备度"]), r["最缺类别"], float(r["最大差距"]))
        for _, r in s.iterrows())
    return "<table class=\"tbl\"><tr><th>片区</th><th>完备度</th><th>最难达标类别</th><th>距 1 000 m 还差</th></tr>%s</table>" % rows


def main():
    os.makedirs(FIGDIR, exist_ok=True)
    df = load()
    st = stats(df)
    fb = os.path.join(FIGDIR, "档位分布.png")
    fm = os.path.join(FIGDIR, "缺口分布.png")
    fig_band(st, fb)
    fig_map(df, fm)
    good, one = pick_sample(df)

    order = sorted(st["reach"], key=lambda k: st["reach"][k])   # 可达率从低到高
    reach_rows = "".join(
        "<tr><td>%s</td><td>%.0f%%</td><td>%s</td></tr>"
        % (name, st["reach"][name] * 100,
           "已达标为主" if st["reach"][name] >= 0.6 else
           "<span class=\"no\">主要短板</span>")
        for name, _, _ in CATS)

    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>15 分钟生活圈 · 客户视角样例</title>
<style>
 :root {{ --ink:#1c1c1c; --muted:#666; --line:#e2e2e2; --bg:#fbfbfa; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:36px 44px 56px; background:var(--bg); color:var(--ink);
        font-family:"SimSun","Times New Roman",serif; line-height:1.75; max-width:960px; }}
 h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:.5px; }}
 .sub {{ color:var(--muted); font-size:13px; margin-bottom:26px; }}
 h2 {{ font-size:17px; margin:34px 0 10px; padding-left:9px; border-left:4px solid {accent}; }}
 p {{ margin:8px 0; font-size:14.5px; }}
 .lead {{ font-size:15.5px; background:#fff; border:1px solid var(--line); padding:16px 18px;
          margin:0 0 8px; }}
 .cards {{ display:flex; gap:12px; margin:16px 0 6px; }}
 .card {{ flex:1; background:#fff; border:1px solid var(--line); padding:12px 14px; }}
 .card b {{ font-size:22px; display:block; font-family:"Times New Roman",SimSun,serif; }}
 .card span {{ font-size:12px; color:var(--muted); }}
 table {{ border-collapse:collapse; width:100%; font-size:13.5px; background:#fff; margin:10px 0 4px; }}
 th, td {{ border-bottom:1px solid var(--line); padding:7px 9px; text-align:left; }}
 th {{ background:#f3f3f1; font-weight:normal; color:#444; }}
 .ok {{ color:{okc}; }} .no {{ color:{noc}; }}
 .unit {{ background:#fff; border:1px solid var(--line); padding:12px 16px; margin:10px 0; }}
 .unit h3 {{ margin:0 0 2px; font-size:15px; }}
 .meta {{ color:var(--muted); font-size:12.5px; margin:0 0 8px; }}
 .mini {{ font-size:13px; margin:0; }}
 figure {{ margin:14px 0; background:#fff; border:1px solid var(--line); padding:10px; }}
 img {{ width:100%; display:block; }}
 figcaption {{ font-size:12px; color:var(--muted); padding-top:6px; }}
 .note {{ font-size:12.5px; color:var(--muted); background:#fff; border:1px solid var(--line); padding:12px 16px; }}
</style></head><body>

<h1>15 分钟生活圈 · 客户视角样例</h1>
<div class="sub">成都中心城区 · 1 334 个住宅片区 · 五类日常设施 · 直线 1 000 m 口径 · 数据时点 2026-11（OpenStreetMap）</div>

<div class="lead"><b>一句话结论：</b>该片区五类设施齐备的住宅片区只有
<b>{full:.0f}%</b>，<b>{weak:.0f}%</b> 的片区缺 3 类以上；最短的两块板是<b>{worst}</b>（可达率 {worst_r:.0f}%）
和<b>{second}</b>（{second_r:.0f}%），{best}已经达到 {best_r:.0f}%，不是瓶颈。
若要花最少的钱提升最多片区，应优先补「只差一类」的那批（见第四节）。</div>

<div class="cards">
  <div class="card"><b>{n}</b><span>参与评估的住宅片区</span></div>
  <div class="card"><b>{full:.0f}%</b><span>五类齐备（完备度 5）</span></div>
  <div class="card"><b>{worst_r:.0f}%</b><span>{worst}可达率（最低一类）</span></div>
  <div class="card"><b>{area_med:.0f} ㎡</b><span>片区面积中位数</span></div>
</div>

<h2>一、这地方整体什么水平</h2>
<figure><img src="sample_figs/档位分布.png" alt="档位分布">
<figcaption>按完备度分档统计。绿＝五类齐备，红＝缺 4 类以上；总数与占比见右侧标注。</figcaption></figure>

<h2>二、五类设施各是什么状况</h2>
<table><tr><th>设施类别</th><th>15 分钟内可达率</th><th>判断</th></tr>{reach_rows}</table>
<p>判断口径：可达率 ≥ 60% 视为「已达标为主」，低于此则列为主要短板。未达标单元到最近设施的中位距离：{gaps}</p>

<h2>三、短板集中在哪里</h2>
<figure><img src="sample_figs/缺口分布.png" alt="缺口分布">
<figcaption>每个点是一个住宅片区，颜色为完备度档位（5＝五类齐备，4＝缺 1 类，3＝缺 2 类，2＝缺 3 类，0-1＝缺 4 类以上）。红点群就是需要优先布点的区域。</figcaption></figure>

<h2>四、先从哪儿下手（只差一点就能补齐的 10 个片区）</h2>
{top_gaps}

<h2>五、两处具体地方，长什么样</h2>
<p>给客户讲方案时，抽象数字要能落到一个具体片区上。下面取仓里两个真实单元：一个已齐备、一个只差一类。</p>
{good_block}
{one_block}

<h2>六、口径与免责</h2>
<div class="note">
① 距离为<b>直线距离</b>（UTM 48N 下计算），不是步行路网距离；跨河、跨铁路的实际步行时间会更长。<br>
② 设施判定只看「最近设施是否在 1 000 m 内」，与设施容量、班次、开放时间无关。<br>
③ 数据来自 OpenStreetMap（ODbL），2026-11 抓取，新开/关闭的设施未反映。<br>
④ 底图与行政界线仅作空间参照，非法定界线。<br>
⑤ 本页数字由 `make_client_report.py` 从 `life_circle_scores.csv` 现算，未手工改写。
</div>

<p class="sub" style="margin-top:30px">生成：`python make_client_report.py` · 数据：`life_circle_scores.csv`（1 334 行）</p>
</body></html>
""".format(accent="#2f7d32", okc="#2f7d32", noc="#b3392f",
           full=st["full"] * 100, weak=st["weak"] * 100, n=st["n"],
           worst=order[0], worst_r=st["reach"][order[0]] * 100,
           second=order[1], second_r=st["reach"][order[1]] * 100,
           best=order[-1], best_r=st["reach"][order[-1]] * 100,
           area_med=st["area_med"],
           reach_rows=reach_rows,
           gaps="；".join("%s 还差 %.0f m" % (k, v) for k, v in st["gap"].items()),
           top_gaps=top_gaps(df),
           good_block=unit_block(good, "已达标的片区（可作对照基准）"),
           one_block=unit_block(one, "只差一类的片区（最值得优先补）"))

    io.open(OUT, "w", encoding="utf-8").write(html)
    print("→", OUT)
    print("→", fb, "/", fm)


if __name__ == "__main__":
    main()
