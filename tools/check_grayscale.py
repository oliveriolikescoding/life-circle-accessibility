# -*- coding: utf-8 -*-
"""灰度可辨性检查：把专题图转灰度并裁一块密集区，确认 5 档不只靠颜色区分。"""
import sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("L")
w, h = im.size
# 裁地图中部（约 x 0.10–0.42, y 0.35–0.70）
box = (int(w * 0.10), int(h * 0.35), int(w * 0.42), int(h * 0.70))
im.crop(box).save(dst)
print(f"灰度裁图已保存：{dst}  {im.crop(box).size}")
