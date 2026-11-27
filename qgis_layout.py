# -*- coding: utf-8 -*-
"""
qgis_layout.py —— 用 PyQGIS 无人值守生成 A4 横向打印布局（Phase 1 验收 2 的证据）

为什么是脚本而不是点鼠标：
    同一份 life_circle_scores.geojson，Python 版和 QGIS 版各出一张图，结论必须对得上。
    QGIS 版走 QgsPrintLayout 全自动，才能 300 dpi 复现、以后改口径重跑一次就出图。

运行（必须用 QGIS 自带的 python，不是系统 python）：
    $env:QT_QPA_PLATFORM="offscreen"
    & 'C:\\Program Files\\QGIS 3.44.15\\bin\\python-qgis-ltr.bat' qgis_layout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendStyle,
    QgsMarkerSymbol,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsRendererCategory,
    QgsRuleBasedRenderer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont

BASE = Path(__file__).resolve().parent
HOMES = BASE / "data" / "life_circle_scores.geojson"
DISTRICTS = BASE / "data" / "basemap" / "chengdu_districts.json"
OUT_PDF = BASE / "life_circle_layout.pdf"
OUT_PNG = BASE / "life_circle_layout.png"
OUT_SVG = BASE / "life_circle_layout.svg"
CRS_UTM = "EPSG:32648"
# 图面字体：中文宋体 SimSun、西文 Times New Roman；Qt 5.13+ 按字回落，
# setFamilies 里先西文后中文即可实现混排。宋体没有真粗体面，标题靠同色 buffer 压重。
FONT_LATIN = "Times New Roman"
FONT_CJK = "SimSun"
FONT_FAMILY = FONT_CJK  # 兼容旧引用

# 与 Python 版同一套编码：颜色 + 形状（方/圆/空心圆/三角/叉）+ 尺寸
# 用「规则」而不是「分类值」，是因为 0 和 1 共用一档：分类渲染器会在图例里
# 出现两条一模一样的不达标，看着像图例出错。
LEVELS = [
    ("完整（5 类全可达）", '"完备度" = 5', "#0E5D4E", "square", 1.7, False),
    ("良好（缺 1 类）", '"完备度" = 4', "#2E7D6B", "circle", 1.45, False),
    ("一般（缺 2 类）", '"完备度" = 3', "#6E8B3D", "circle", 1.1, True),
    ("薄弱（缺 3 类）", '"完备度" = 2', "#B07A2E", "triangle", 1.3, False),
    ("不达标（缺 4–5 类）", '"完备度" <= 1', "#A63A17", "cross2", 1.6, False),
]


def font(size: float, bold: bool = False) -> QFont:
    """西文 Times New Roman + 中文宋体混排（Qt 按字回落，用 setFamilies 给候选表）。"""
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(size)
    f.setBold(bold)
    try:
        f.setFamilies([FONT_LATIN, FONT_CJK, "Noto Serif SC", "DejaVu Serif"])
    except AttributeError:  # 老 Qt 没有 setFamilies，退回中文族
        pass
    return f


def build_marker(color: str, shape: str, size: float, hollow: bool) -> QgsMarkerSymbol:
    sym = QgsMarkerSymbol.createSimple({
        "name": shape,
        "size": f"{size}",
        "size_unit": "MM",
        "angle": "0",
        "color": "0,0,0,0" if hollow else color,
        "outline_color": color,
        "outline_width": "0.5" if hollow else "0.3",
        "outline_width_unit": "MM",
    })
    return sym


def add_label(layout, text: str, x: float, y: float, w: float, h: float,
              size: float, color: str = "#12233A", bold: bool = False,
              align=Qt.AlignLeft) -> QgsLayoutItemLabel:
    item = QgsLayoutItemLabel(layout)
    item.setText(text)
    item.setFont(font(size, bold))
    item.setFontColor(QColor(color))
    item.setHAlign(align)
    item.setVAlign(Qt.AlignTop)
    if bold:
        # 宋体没有真粗体面，QGIS 渲染时会退回常规，用同色描边把笔画「压重」一档
        tf = item.textFormat()
        buf = tf.buffer()
        buf.setEnabled(True)
        buf.setSize(0.11)
        buf.setSizeUnit(QgsUnitTypes.RenderMillimeters)
        buf.setColor(QColor(color))
        buf.setOpacity(1.0)
        buf.setJoinStyle(Qt.RoundJoin)
        buf.setFillBufferInterior(True)
        tf.setBuffer(buf)
        item.setTextFormat(tf)
    item.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    item.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(item)
    return item


def main() -> int:
    qgs = QgsApplication([], False)
    qgs.initQgis()
    try:
        project = QgsProject.instance()
        project.setCrs(QgsCoordinateReferenceSystem(CRS_UTM))

        if not HOMES.exists():
            print(f"❌ 缺输入：{HOMES}（先跑 life_circle.py 生成评分 GeoJSON）")
            return 2

        homes = QgsVectorLayer(str(HOMES), "住宅单元完备度", "ogr")
        if not homes.isValid():
            print("❌ 住宅图层加载失败")
            return 2
        # 图例里这一行是图层名，改成带样本量的表述，避免和上面的图例标题「完备度…」重复
        homes.setName(f"住宅单元 {homes.featureCount()} 个")
        print(f"✅ 住宅图层：{homes.featureCount()} 个要素；字段 {[f.name() for f in homes.fields()]}")

        districts = QgsVectorLayer(str(DISTRICTS), "成都市区（县）界线", "ogr")
        if districts.isValid():
            fill = QgsFillSymbol.createSimple({"color": "#F5F7FA", "outline_color": "#C9D3DD",
                                               "outline_width": "0.25"})
            districts.renderer().setSymbol(fill)
            districts.triggerRepaint()
            print(f"✅ 底图：{districts.featureCount()} 个区县面")
        else:
            print("⚠️  底图加载失败，只用住宅层")

        # —— 分级符号化（与 Python 版同一套编码） ——
        root = QgsRuleBasedRenderer.Rule(None)
        for label, expr, color, shape, size, hollow in LEVELS:
            rule = QgsRuleBasedRenderer.Rule(build_marker(color, shape, size, hollow))
            rule.setLabel(label)
            rule.setFilterExpression(expr)
            root.appendChild(rule)
        homes.setRenderer(QgsRuleBasedRenderer(root))
        homes.triggerRepaint()
        print("✅ 分级符号：5 档（方 / 圆 / 空心圆 / 三角 / 叉）")

        layers_for_map = [homes] + ([districts] if districts.isValid() else [])
        project.addMapLayers(layers_for_map)

        # —— 打印布局：A4 横向 ——
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName("LC-01 生活圈完备度")
        page = layout.pageCollection().pages()[0]
        page.setPageSize(QgsLayoutSize(297, 210, QgsUnitTypes.LayoutMillimeters))

        map_item = QgsLayoutItemMap(layout)
        map_item.attemptMove(QgsLayoutPoint(12, 16, QgsUnitTypes.LayoutMillimeters))
        map_item.attemptResize(QgsLayoutSize(119, 132, QgsUnitTypes.LayoutMillimeters))
        map_item.setCrs(QgsCoordinateReferenceSystem(CRS_UTM))
        map_item.setLayers(layers_for_map)
        map_item.setBackgroundColor(QColor("#FFFFFF"))
        map_item.setFrameEnabled(True)
        map_item.setFrameStrokeColor(QColor("#B9C2CC"))
        layout.addLayoutItem(map_item)

        # 图幅范围：先定一个整数比例尺 1:150 000，再反算范围，避免出「1:143,958」这种怪数
        xform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
                                       QgsCoordinateReferenceSystem(CRS_UTM), project)
        ext = xform.transformBoundingBox(homes.extent())
        cx, cy = ext.center().x(), ext.center().y()
        nice_scale = 150000
        w = 119 / 1000 * nice_scale
        h = 132 / 1000 * nice_scale
        map_item.setExtent(QgsRectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        print(f"✅ 图幅：{w / 1000:.1f} × {h / 1000:.1f} km，比例尺 1 : {map_item.scale():,.0f}")

        # 图廓坐标注记（公里数）
        grid = map_item.grid()
        grid.setEnabled(True)
        grid.setIntervalX(2000)
        grid.setIntervalY(2000)
        grid.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
        grid.setAnnotationEnabled(True)
        for side, direction in ((QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Horizontal),
                                (QgsLayoutItemMapGrid.Bottom, QgsLayoutItemMapGrid.Horizontal),
                                (QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.Vertical),
                                (QgsLayoutItemMapGrid.Right, QgsLayoutItemMapGrid.Vertical)):
            grid.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, side)
            grid.setAnnotationDirection(direction, side)
        grid.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
        grid.setAnnotationExpression("@grid_number / 1000")
        grid.setAnnotationPrecision(0)
        grid.setAnnotationFont(font(6))
        grid.setAnnotationFontColor(QColor("#4A5A6A"))
        grid.setAnnotationFrameDistance(1.0)
        map_item.updateBoundingRect()
        map_item.invalidateCache()
        map_item.refresh()

        # 指北针：贴图廓内上边，横位置取顶边无点位空列（按要素坐标试算）
        ext_m = map_item.extent()
        xf = QgsCoordinateTransform(homes.crs(), QgsCoordinateReferenceSystem(CRS_UTM), project)
        xs, ys = [], []
        for f in homes.getFeatures():
            pt = xf.transform(f.geometry().centroid().asPoint())
            xs.append(pt.x()); ys.append(pt.y())
        Wm = ext_m.xMaximum() - ext_m.xMinimum()
        best_fx = None
        for i in range(5, 94):
            fx = i / 100
            cx = ext_m.xMinimum() + fx * Wm
            if sum(1 for x, y in zip(xs, ys)
                   if abs(x - cx) < 0.05 * Wm and y > ext_m.yMaximum() - 0.09 * (
                       ext_m.yMaximum() - ext_m.yMinimum())) == 0:
                best_fx = fx
        fx = best_fx if best_fx is not None else 0.90

        pic = QgsLayoutItemPicture(layout)
        pic.setPicturePath(":/images/north_arrows/default.svg")
        try:
            pic.setMode(QgsLayoutItemPicture.FormatSVG)
        except Exception:
            pass
        pic.attemptMove(QgsLayoutPoint(12 + fx * 119 - 3.0, 17.5, QgsUnitTypes.LayoutMillimeters))
        pic.attemptResize(QgsLayoutSize(6, 8, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(pic)

        # 分段比例尺（图廓内左下）
        sb = QgsLayoutItemScaleBar(layout)
        sb.setLinkedMap(map_item)
        sb.setStyle("Single Box")
        sb.setUnits(QgsUnitTypes.DistanceKilometers)
        sb.setUnitsPerSegment(4.0)
        sb.setNumberOfSegments(2)
        sb.setNumberOfSegmentsLeft(0)
        sb.setHeight(3.2)
        sb.setFont(font(7))
        sb.setFontColor(QColor("#243447"))
        sb.setFillColor(QColor("#FFFFFF"))
        sb.setLineColor(QColor("#243447"))
        sb.setLineWidth(0.3)
        sb.setUnitLabel("km")
        sb.attemptMove(QgsLayoutPoint(146, 66, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(sb)

        # 图例（只列住宅分级，不列底图）
        legend = QgsLayoutItemLegend(layout)
        legend.setTitle("完备度分级（1 000 m 内可达类别数）")
        legend.setLinkedMap(map_item)
        legend.setColumnCount(1)
        legend.setStyleFont(QgsLegendStyle.Title, font(8.5))
        # 图层名那一行（「住宅单元完备度」）由 Group/Subgroup 两档样式控制，
        # 不显式设置就会退回 QGIS 默认字体（无衬线），跟图面其余文字不是一套
        legend.setStyleFont(QgsLegendStyle.Group, font(8.5))
        legend.setStyleFont(QgsLegendStyle.Subgroup, font(8.5))
        legend.setStyleFont(QgsLegendStyle.Symbol, font(8.5))
        legend.setStyleFont(QgsLegendStyle.SymbolLabel, font(8))
        legend.setSymbolWidth(4.0)
        legend.setSymbolHeight(3.4)
        legend.setResizeToContents(True)
        legend.attemptMove(QgsLayoutPoint(146, 16, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(legend)
        # 图例只留住宅分级：底图条目会带出一个空白符号块
        legend.setAutoUpdateModel(False)
        if districts.isValid():
            legend.model().rootGroup().removeLayer(districts)

        # 图题与图注（置于图下）
        add_label(layout, "图 1　成都中心城区住宅单元 15 分钟生活圈完备度", 12, 154, 273, 8,
                  10, align=Qt.AlignHCenter)
        add_label(layout,
                  "　　成都中心城区 1334 个住宅单元，完备度为五类设施在 1000 m 内可达的类别数，"
                  "取值 0 至 5；完备度 5 的单元 429 个（32.2%），完备度 0 至 1 的 106 个（7.9%）。\n"
                  "　　投影 EPSG:32648（WGS 84 / UTM zone 48N）；距离为住宅片区质心至设施中心点的直线距离，"
                  "不含步行或路网成本；可达口径为 15 分钟约 1000 m（按步行 4 km/h 折算）。\n"
                  "　　设施与住宅面据 OpenStreetMap contributors（ODbL，2026-11 抓取）绘制；"
                  "区县界据 DataV.GeoAtlas，仅作空间参照，非法定界线。\n"
                  "　　制图日期 2026-11-27；本图为示意性专题图，非标准地图，无审图号。",
                  12, 163, 273, 26, 7, "#262626")

        # —— 导出 ——
        for p in (OUT_PDF, OUT_PNG, OUT_SVG):
            if p.exists():
                p.unlink()
        exporter = QgsLayoutExporter(layout)
        pdf_settings = QgsLayoutExporter.PdfExportSettings()
        pdf_settings.dpi = 300
        pdf_settings.rasterizeWholeImage = False
        res = exporter.exportToPdf(str(OUT_PDF), pdf_settings)
        print(f"{'✅' if res == QgsLayoutExporter.Success else '❌'} PDF：{OUT_PDF}（code {res}）")

        img_settings = QgsLayoutExporter.ImageExportSettings()
        img_settings.dpi = 300
        res2 = exporter.exportToImage(str(OUT_PNG), img_settings)
        print(f"{'✅' if res2 == QgsLayoutExporter.Success else '❌'} PNG：{OUT_PNG}（code {res2}）")

        # 矢量 SVG：文字转轮廓（AlwaysOutlines），GitHub 直接渲染不会因缺字体错位
        svg_settings = QgsLayoutExporter.SvgExportSettings()
        svg_settings.dpi = 300
        svg_settings.forceVectorOutput = True
        svg_settings.textRenderFormat = Qgis.TextRenderFormat.AlwaysOutlines
        res3 = exporter.exportToSvg(str(OUT_SVG), svg_settings)
        print(f"{'✅' if res3 == QgsLayoutExporter.Success else '❌'} SVG：{OUT_SVG}（code {res3}）")
        return 0 if res == QgsLayoutExporter.Success else 1
    finally:
        qgs.exitQgis()


if __name__ == "__main__":
    sys.exit(main())
