"""Render the brand icons from docs/logo.svg.

    pip install cairosvg
    python scripts/make_brand.py

Writes icon.png (256), icon@2x.png (512) and dark variants (a light speaker
frame for dark backgrounds) into custom_components/media_mgmt/brand/, and
docs/logo.png for places that can't show SVG.
"""

from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
SVG = (ROOT / "docs" / "logo.svg").read_text()
OUT = ROOT / "custom_components" / "media_mgmt" / "brand"
OUT.mkdir(parents=True, exist_ok=True)

FRAME = '<rect x="40" y="12" width="148" height="232" rx="26" fill="#263238"/>'
assert FRAME in SVG, "speaker frame not found in docs/logo.svg"
variants = {"": SVG, "dark_": SVG.replace(FRAME, FRAME.replace("#263238", "#cfd8dc"))}

for prefix, svg in variants.items():
    for suffix, size in (("", 256), ("@2x", 512)):
        path = OUT / f"{prefix}icon{suffix}.png"
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(path), output_width=size, output_height=size)
        print("wrote", path)

cairosvg.svg2png(bytestring=SVG.encode(), write_to=str(ROOT / "docs" / "logo.png"), output_width=512, output_height=512)
print("wrote", ROOT / "docs" / "logo.png")
