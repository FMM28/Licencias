#!/usr/bin/env python3
"""Genera el guilloché del panel (la trama de líneas finas de billetes y certificados).

    python frontend/tools/make_guilloche.py

Escribe en app/web/static/img/:
  guilloche-band.svg   banda horizontal (barra superior, cabecera de la tarjeta de clave)
  rosette.svg          roseta (panel del login)
  favicon.svg          icono de la pestaña

Los SVG de trama se usan como *máscara* CSS (mask-image) y se tiñen con las variables de color
del tema, por eso solo importa su canal alfa: los trazos van en negro.
"""
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "img"


def band(width=1200, height=140, lines=24) -> str:
    """Familias de ondas con fases desfasadas: al cruzarse forman el tejido típico del guilloché."""
    mid, paths = height / 2, []
    for family, (wave, wave2, amp) in enumerate([(300, 520, 0.40), (380, 610, 0.34)]):
        for k in range(lines):
            phase = k * 2 * math.pi / lines
            pts = []
            for x in range(0, width + 12, 12):
                envelope = 0.55 + 0.45 * math.cos(2 * math.pi * x / wave2 + phase * (1 + family))
                y = mid + height * amp * envelope * math.sin(2 * math.pi * x / wave + phase)
                pts.append(f"{x},{y:.1f}")
            paths.append(f'<path d="M{" L".join(pts)}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="xMidYMid slice"><g fill="none" stroke="#000" '
            f'stroke-width="0.6" stroke-linejoin="round">{"".join(paths)}</g></svg>')


def rosette(size=640) -> str:
    """Hipotrocoides concéntricas. Con R/r entero cada curva cierra en una sola vuelta
    (R/r picos), así bastan 240 puntos por trazo y el dibujo queda limpio."""
    cx = cy = size / 2
    families = [(150, 30), (168, 24), (180, 20), (144, 24)]   # 5, 7, 9 y 6 picos
    paths = []
    for i in range(12):
        R, r = families[i % len(families)]
        d = 26 + (i // len(families)) * 24 + (i % len(families)) * 5
        scale = size / 2 * 0.93 / (R - r + d)
        pts = []
        for s in range(241):
            t = s / 240 * 2 * math.pi
            x = (R - r) * math.cos(t) + d * math.cos((R - r) / r * t)
            y = (R - r) * math.sin(t) - d * math.sin((R - r) / r * t)
            pts.append(f"{cx + x * scale:.1f},{cy + y * scale:.1f}")
        paths.append(f'<path d="M{" L".join(pts)}Z"/>')
    circles = "".join(f'<circle cx="{cx}" cy="{cy}" r="{size / 2 - 6 - j * 5}"/>' for j in range(3))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            f'<g fill="none" stroke="#000" stroke-width="0.6" stroke-linejoin="round">'
            f'{circles}{"".join(paths)}</g></svg>')


FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#0f5c45"/>
<g fill="none" stroke="#fff" stroke-width="1.5">
<ellipse cx="16" cy="16" rx="9.5" ry="4.2"/>
<ellipse cx="16" cy="16" rx="9.5" ry="4.2" transform="rotate(60 16 16)"/>
<ellipse cx="16" cy="16" rx="9.5" ry="4.2" transform="rotate(120 16 16)"/>
</g><circle cx="16" cy="16" r="1.7" fill="#d9a441"/></svg>
"""

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in {"guilloche-band.svg": band(), "rosette.svg": rosette(),
                          "favicon.svg": FAVICON}.items():
        (OUT / name).write_text(content, encoding="utf-8")
        print(f"{name:22s}{len(content) / 1024:6.1f} KB")
