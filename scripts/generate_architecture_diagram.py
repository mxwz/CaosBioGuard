"""生成 CaosBioGuard 分层架构图（SVG）。

运行（在项目根，使用任意 Python 3）：
    python scripts/generate_architecture_diagram.py

输出：
    docs/architecture-diagram.svg

纯标准库实现，不依赖网络或第三方包；SVG 为矢量图，可直接在浏览器查看，
也可插入文档或再转换为 PNG。
"""

from __future__ import annotations

import html
import os

# 画布参数
WIDTH = 1480
MARGIN = 40
CONTENT_W = WIDTH - MARGIN * 2

LAYER_GAP = 34          # 层间距（画箭头）
HEADER_H = 34           # 层标题条高度
NODE_H = 66
NODE_GAP = 18
INNER_PAD = 20
BODY_TOP_PAD = 16
BODY_BOTTOM_PAD = 18

FONT_STACK = (
    "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC','Segoe UI',"
    "Arial,sans-serif"
)

# (层标题, 主色, 节点[(主标题, 副标题)])
LAYERS = [
    (
        "客户端 / 交互层",
        "#6366f1",
        [
            ("边缘 Kiosk 触屏", "PySide6"),
            ("浏览器管理后台", "Web"),
            ("移动端", "PWA / 小程序 / APK"),
            ("AI Agent", "MCP"),
        ],
    ),
    (
        "应用接入层",
        "#0ea5e9",
        [
            ("sideUI.kiosk", "python -m sideUI.kiosk.app"),
            ("web_admin", "Flask + waitress"),
            ("agent_tools / mobile_api", "HTTP 接口"),
        ],
    ),
    (
        "核心业务层 · biometrics",
        "#10b981",
        [
            ("service", "注册 / 验证 / 多因子"),
            ("fusion", "多模态融合"),
            ("registry", "引擎注册 / 容错"),
        ],
    ),
    (
        "识别引擎层 · 9 模态",
        "#f59e0b",
        [
            ("人脸 / 声纹 / 指纹", ""),
            ("虹膜 / 掌纹 / 指静脉", ""),
            ("步态 / 视网膜 / 签名", ""),
            ("adapters 厂商适配", "百度 / 腾讯 / 阿里 / 华为"),
        ],
    ),
    (
        "平台与硬件层",
        "#8b5cf6",
        [
            ("platform_utils", "系统 / 架构识别"),
            ("hardware", "门锁与设备"),
            ("x2000", "串口协议"),
        ],
    ),
    (
        "数据与安全层",
        "#ef4444",
        [
            ("store", "加密模板"),
            ("capture_store", "加密样本"),
            ("consent", "同意记录"),
            ("SQLite / MySQL", "数据库"),
            ("sync", "云边同步"),
            ("notify", "邮件 / Webhook"),
        ],
    ),
]


def lighten(hex_color: str, ratio: float) -> str:
    """把十六进制颜色向白色混合，ratio=1 得到白色。"""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r + (255 - r) * ratio)
    g = int(g + (255 - g) * ratio)
    b = int(b + (255 - b) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


def layout() -> tuple[list[dict], int]:
    """计算每个层与节点的几何位置。"""
    y = MARGIN
    laid = []
    for title, color, nodes in LAYERS:
        n = len(nodes)
        body_h = BODY_TOP_PAD + NODE_H + BODY_BOTTOM_PAD
        layer_h = HEADER_H + body_h
        node_w = (CONTENT_W - INNER_PAD * 2 - NODE_GAP * (n - 1)) / n

        node_geom = []
        for i, (name, sub) in enumerate(nodes):
            nx = MARGIN + INNER_PAD + i * (node_w + NODE_GAP)
            ny = y + HEADER_H + BODY_TOP_PAD
            node_geom.append(
                {
                    "name": name,
                    "sub": sub,
                    "x": nx,
                    "y": ny,
                    "w": node_w,
                    "cx": nx + node_w / 2,
                    "top": ny,
                    "bottom": ny + NODE_H,
                }
            )

        laid.append(
            {
                "title": title,
                "color": color,
                "x": MARGIN,
                "y": y,
                "w": CONTENT_W,
                "h": layer_h,
                "nodes": node_geom,
            }
        )
        y += layer_h + LAYER_GAP

    total_h = y - LAYER_GAP + MARGIN
    return laid, total_h


def arrow(x1: float, y1: float, x2: float, y2: float, color: str) -> str:
    """带箭头的竖直线（必要时含水平偏移）。"""
    return (
        f'<path d="M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="1.6" opacity="0.55" '
        f'marker-end="url(#arrow)"/>'
    )


def render() -> str:
    layers, height = layout()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{height}" viewBox="0 0 {WIDTH} {height}" font-family="{FONT_STACK}">',
        '<defs>',
        '<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" '
        'orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L8,3 L0,6 Z" fill="#64748b"/></marker>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">'
        '<feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-color="#0f172a" '
        'flood-opacity="0.12"/></filter>',
        '</defs>',
        f'<rect x="0" y="0" width="{WIDTH}" height="{height}" fill="#f8fafc"/>',
        f'<text x="{WIDTH/2}" y="30" text-anchor="middle" font-size="22" '
        'font-weight="700" fill="#0f172a">CaosBioGuard · 多生物识别门禁系统架构</text>',
    ]

    # 层与节点
    for layer in layers:
        c = layer["color"]
        x, y, w, h = layer["x"], layer["y"], layer["w"], layer["h"]
        # 层容器
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" '
            f'fill="{lighten(c, 0.90)}" stroke="{c}" stroke-width="1.5"/>'
        )
        # 标题条
        parts.append(
            f'<path d="M{x+12},{y} H{x+w-12} A12,12 0 0 1 {x+w},{y+12} '
            f'V{y+HEADER_H} H{x} V{y+12} A12,12 0 0 1 {x+12},{y} Z" fill="{c}"/>'
        )
        parts.append(
            f'<text x="{x+16}" y="{y+HEADER_H/2+7}" font-size="16" '
            f'font-weight="700" fill="#ffffff">{html.escape(layer["title"])}</text>'
        )

        # 节点卡片
        for node in layer["nodes"]:
            nx, ny, nw = node["x"], node["y"], node["w"]
            parts.append(
                f'<rect x="{nx:.1f}" y="{ny}" width="{nw:.1f}" height="{NODE_H}" '
                f'rx="9" fill="#ffffff" stroke="{c}" stroke-width="1.4" '
                'filter="url(#shadow)"/>'
            )
            cap_cy = ny + NODE_H / 2 + (2 if node["sub"] else -4)
            parts.append(
                f'<text x="{nx+nw/2:.1f}" y="{cap_cy:.1f}" text-anchor="middle" '
                f'font-size="15" font-weight="600" fill="#1e293b">'
                f'{html.escape(node["name"])}</text>'
            )
            if node["sub"]:
                parts.append(
                    f'<text x="{nx+nw/2:.1f}" y="{ny+NODE_H-12:.1f}" '
                    f'text-anchor="middle" font-size="12" fill="#64748b">'
                    f'{html.escape(node["sub"])}</text>'
                )

    # 相邻层之间的调用箭头（按索引比例映射，就近连接）
    for li in range(len(layers) - 1):
        upper = layers[li]["nodes"]
        lower = layers[li + 1]["nodes"]
        y_top = layers[li]["y"] + layers[li]["h"]
        y_bottom = layers[li + 1]["y"]
        n_up, n_low = len(upper), len(lower)
        for ui, un in enumerate(upper):
            if n_up == 1:
                target_idx = 0
            else:
                ratio = ui / (n_up - 1)
                target_idx = round(ratio * (n_low - 1))
            ln = lower[target_idx]
            parts.append(arrow(un["cx"], y_top + 2, ln["cx"], y_bottom - 2, "#64748b"))

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "docs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "architecture-diagram.svg")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render())
    print("已生成:", out_path)


if __name__ == "__main__":
    main()
