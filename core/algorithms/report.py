"""
report.py — Генерация PDF-отчёта о контроле геометрической точности.

Структура (3 страницы):
  Стр. 1 — заголовок, входные данные, таблица результатов, заключение
  Стр. 2 — 6 видов (3×2) с подписями + легенда цветовой шкалы
  Стр. 3 — гистограмма распределения отклонений
"""

import logging
import os
import tempfile
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, Image, HRFlowable, PageBreak,
    KeepTogether,
)

logger = logging.getLogger(__name__)

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
USABLE_W = PAGE_W - 2 * MARGIN


# ── Шрифты ────────────────────────────────────────────────────────────────────

def _register_fonts() -> tuple[str, str]:
    """Регистрирует шрифты с поддержкой кириллицы. Возвращает (regular, bold)."""
    for ttf_reg, ttf_bold in [
        ("FreeSans.ttf",               "FreeSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]:
        try:
            pdfmetrics.registerFont(TTFont("_RptReg",  ttf_reg))
            pdfmetrics.registerFont(TTFont("_RptBold", ttf_bold))
            return "_RptReg", "_RptBold"
        except Exception:
            pass
    logger.error("Кириллические шрифты не найдены, используется Helvetica")
    return "Helvetica", "Helvetica-Bold"


# ── Вспомогательные изображения ───────────────────────────────────────────────

def _create_histogram(deviations: np.ndarray, tolerance: float, out: str):
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=120)
    n_bins = max(30, min(80, len(deviations) // 30))
    ax.hist(deviations, bins=n_bins, color="#4a90d9",
            edgecolor="#2c5f8a", linewidth=0.4, alpha=0.85)
    ax.axvline(+tolerance, color="#e53935", linestyle="--", linewidth=1.5,
               label=f"+{tolerance:.3f} мм")
    ax.axvline(-tolerance, color="#43a047", linestyle="--", linewidth=1.5,
               label=f"−{tolerance:.3f} мм")
    ax.set_xlabel("Отклонение, мм", fontsize=11)
    ax.set_ylabel("Количество точек", fontsize=11)
    ax.set_title("Распределение отклонений", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(axis="y", alpha=0.3)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f"{int(x):,}".replace(",", " ")
    ))
    fig.tight_layout()
    fig.savefig(out, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _create_colorbar(tolerance: float, colormap: str, out: str):
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(7, 0.75), dpi=110)
    gradient = np.linspace(-tolerance, tolerance, 256).reshape(1, -1)
    ax.imshow(gradient, aspect="auto", cmap=colormap,
              extent=[-tolerance, tolerance, 0, 1])
    ax.set_yticks([])
    n_ticks = 5
    ticks = np.linspace(-tolerance, tolerance, n_ticks)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{v:+.3f}" for v in ticks], fontsize=9)
    ax.set_xlabel("Отклонение, мм", fontsize=9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout(pad=0.3)
    fig.savefig(out, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── Главная функция ───────────────────────────────────────────────────────────

def generate_report(
    output_path: str,
    cad_path: str,
    scan_path: str,
    deviations: np.ndarray,
    stats: dict,
    registration_rmse: float,
    screenshot_paths: list[str] | None = None,
    mesh_triangles: int = 0,
    config: dict = None,
    unit_cad: str = "mm",
    unit_scan: str = "mm",
) -> str:
    """
    Генерирует 3-страничный PDF-отчёт.

    Стр. 1 — входные данные, результаты, заключение.
    Стр. 2 — 6 видов (3×2) + легенда.
    Стр. 3 — гистограмма.
    """
    font_reg, font_bold = _register_fonts()

    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        if hasattr(s, "fontName"):
            s.fontName = font_reg

    def _style(name, parent="Normal", **kw):
        kw.setdefault("fontName", font_reg)
        return ParagraphStyle(name, parent=styles[parent], **kw)

    title_style = _style(
        "Title", parent="Title",
        fontName=font_bold, fontSize=16,
        textColor=colors.HexColor("#1A237E"),
        spaceAfter=4,
    )
    h2_style = _style(
        "H2", parent="Heading2",
        fontName=font_bold, fontSize=12,
        textColor=colors.HexColor("#283593"),
        spaceBefore=8, spaceAfter=4,
    )
    body_style = _style("Body", fontSize=10, leading=14)
    caption_style = _style(
        "Caption", fontSize=9,
        textColor=colors.HexColor("#444444"),
        alignment=1,  # center
    )
    conclusion_style = _style(
        "Conclusion", fontSize=11, leading=16,
        borderColor=colors.HexColor("#1A237E"),
        borderWidth=1, borderPadding=8,
    )

    tolerance   = stats.get("tolerance", config.get("analysis", {}).get("tolerance_mm", 0.5)
                             if config else 0.5)
    within_pct  = stats.get("within_tolerance", 0) * 100
    threshold   = float((config or {}).get("analysis", {}).get("conformance_threshold", 95))
    passed      = within_pct >= threshold
    n_points    = int(stats.get("n_points", 0))
    colormap    = (config or {}).get("ui", {}).get("colormap", "RdYlGn_r")

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )
    story = []

    # ── Страница 1 ────────────────────────────────────────────────────────────

    story.append(Paragraph(
        "ОТЧЁТ О КОНТРОЛЕ ГЕОМЕТРИЧЕСКОЙ ТОЧНОСТИ", title_style
    ))
    story.append(HRFlowable(width="100%", thickness=1.5,
                             color=colors.HexColor("#3949AB")))
    story.append(Spacer(1, 4 * mm))

    # Дата и время
    story.append(Paragraph(
        f"Дата и время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}", body_style
    ))
    story.append(Spacer(1, 4 * mm))

    # Таблица входных данных
    story.append(Paragraph("Входные данные", h2_style))
    _unit_labels = {
        "mm": "мм", "cm": "см", "m": "м", "in": "дюйм", "as_is": "как есть"
    }
    unit_str = (
        f"мм  (CAD загружен в {_unit_labels.get(unit_cad, unit_cad)}, "
        f"скан в {_unit_labels.get(unit_scan, unit_scan)})"
    )
    input_rows = [
        [Paragraph("<b>Параметр</b>", body_style),
         Paragraph("<b>Значение</b>",  body_style)],
        ["CAD-модель",          os.path.basename(cad_path)],
        ["Треугольников (CAD)", f"{mesh_triangles:,}" if mesh_triangles else "—"],
        ["Облако точек",        os.path.basename(scan_path)],
        ["Точек в скане",       f"{n_points:,}" if n_points else "—"],
        ["Единицы измерения",   unit_str],
        ["Допуск",              f"±{tolerance:.3f} мм"],
    ]
    col_w = [55 * mm, USABLE_W - 55 * mm]
    in_table = Table(input_rows, colWidths=col_w)
    in_table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), font_reg),
        ("FONTNAME",   (0, 0), (-1,  0), font_bold),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1,  0), colors.HexColor("#3949AB")),
        ("TEXTCOLOR",  (0, 0), (-1,  0), colors.white),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F5F5F5")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(in_table)
    story.append(Spacer(1, 5 * mm))

    # Таблица результатов
    story.append(Paragraph("Результаты измерений", h2_style))
    result_rows = [
        [Paragraph("<b>Метрика</b>", body_style),
         Paragraph("<b>Значение</b>", body_style)],
        ["Среднее отклонение",  f"{stats.get('mean_deviation', 0):+.4f} мм"],
        ["RMSE",                f"{registration_rmse:.6f} мм"],
        ["Мин. отклонение",     f"{stats.get('min_deviation', 0):+.4f} мм"],
        ["Макс. отклонение",    f"{stats.get('max_deviation', 0):+.4f} мм"],
        ["Доля в допуске",      f"{within_pct:.1f}%  из {n_points:,} точек"],
    ]
    res_table = Table(result_rows, colWidths=col_w)
    res_table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), font_reg),
        ("FONTNAME",   (0, 0), (-1,  0), font_bold),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1,  0), colors.HexColor("#283593")),
        ("TEXTCOLOR",  (0, 0), (-1,  0), colors.white),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#F5F5F5")]),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(res_table)
    story.append(Spacer(1, 5 * mm))

    # Габаритные размеры
    dims = stats.get("dimensions")
    if dims is not None:
        story.append(Paragraph("Габаритные размеры", h2_style))
        cad_d   = dims.get("cad",  (0.0, 0.0, 0.0))
        scan_d  = dims.get("scan")
        delta_d = dims.get("delta")
        cw4 = (USABLE_W - 45 * mm) / 4
        dim_rows = [
            [Paragraph("<b>Параметр</b>",  body_style),
             Paragraph("<b>X, мм</b>",      body_style),
             Paragraph("<b>Y, мм</b>",      body_style),
             Paragraph("<b>Z, мм</b>",      body_style),
             Paragraph("<b>Диаг., мм</b>",  body_style)],
            ["CAD-модель",
             f"{cad_d[0]:.2f}", f"{cad_d[1]:.2f}", f"{cad_d[2]:.2f}",
             f"{dims.get('cad_diag', 0.0):.2f}"],
        ]
        if scan_d is not None:
            dim_rows.append(["Скан",
                f"{scan_d[0]:.2f}", f"{scan_d[1]:.2f}", f"{scan_d[2]:.2f}",
                f"{dims.get('scan_diag', 0.0):.2f}"])
        if delta_d is not None:
            dim_rows.append(["Δ (Скан − CAD)",
                f"{delta_d[0]:+.2f}", f"{delta_d[1]:+.2f}", f"{delta_d[2]:+.2f}", "—"])
        dim_table = Table(dim_rows, colWidths=[45 * mm, cw4, cw4, cw4, cw4])
        dim_table.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, -1), font_reg),
            ("FONTNAME",   (0, 0), (-1,  0), font_bold),
            ("FONTSIZE",   (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1,  0), colors.HexColor("#3949AB")),
            ("TEXTCOLOR",  (0, 0), (-1,  0), colors.white),
            ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F5F5")]),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]))
        story.append(dim_table)
        story.append(Spacer(1, 5 * mm))

    # Заключение
    verdict_word = "СООТВЕТСТВУЕТ" if passed else "НЕ СООТВЕТСТВУЕТ"
    verdict_color = colors.HexColor("#1B5E20" if passed else "#B71C1C")
    verdict_bg    = colors.HexColor("#E8F5E9" if passed else "#FFEBEE")
    verdict_style = ParagraphStyle(
        "Verdict",
        parent=styles["Normal"],
        fontName=font_bold,
        fontSize=12,
        textColor=verdict_color,
        borderColor=verdict_color,
        borderWidth=1.5,
        borderPadding=8,
        backColor=verdict_bg,
        alignment=1,
    )
    story.append(Paragraph(
        f"При допуске {tolerance:.3f} мм доля точек в пределах допуска: "
        f"{within_pct:.1f}%.<br/>"
        f"Деталь <b>{verdict_word} ДОПУСКАМ</b>.",
        verdict_style,
    ))

    # ── Страница 2 — скриншоты ─────────────────────────────────────────────────

    story.append(PageBreak())
    story.append(Paragraph("Визуализация отклонений", h2_style))
    story.append(Spacer(1, 3 * mm))

    view_labels = ["Спереди", "Сзади", "Слева", "Справа", "Сверху", "Изометрия"]
    paths = list(screenshot_paths or [])

    # Заглушки до 6 снимков
    while len(paths) < 6:
        paths.append(None)

    IMG_W = (USABLE_W - 6 * mm) / 2
    IMG_H = IMG_W * 0.62   # уменьшена высота для трёх рядов

    def _img_or_placeholder(p, w, h):
        if p and os.path.exists(p):
            return Image(p, width=w, height=h)
        return Paragraph("(скриншот недоступен)", caption_style)

    # Сетка 3×2: (спереди, сзади) / (слева, справа) / (сверху, изометрия)
    grid_data = []
    for _r in range(3):
        _i, _j = _r * 2, _r * 2 + 1
        grid_data.append([
            _img_or_placeholder(paths[_i], IMG_W, IMG_H),
            _img_or_placeholder(paths[_j], IMG_W, IMG_H),
        ])
        grid_data.append([
            Paragraph(view_labels[_i], caption_style),
            Paragraph(view_labels[_j], caption_style),
        ])
        if _r < 2:
            grid_data.append([Spacer(1, 3 * mm), Spacer(1, 3 * mm)])

    grid_table = Table(grid_data, colWidths=[IMG_W + 3 * mm, IMG_W + 3 * mm])
    grid_table.setStyle(TableStyle([
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",(0, 0), (-1, -1), 2),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    story.append(grid_table)
    story.append(Spacer(1, 5 * mm))

    # Легенда цветовой шкалы
    story.append(Paragraph("Легенда цветовой шкалы", h2_style))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cbar_path = f.name
    _create_colorbar(tolerance, colormap, cbar_path)
    story.append(Image(cbar_path, width=USABLE_W, height=22 * mm))

    # ── Страница 3 — гистограмма ───────────────────────────────────────────────

    story.append(PageBreak())
    story.append(Paragraph("Распределение отклонений", h2_style))
    story.append(Spacer(1, 3 * mm))

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        hist_path = f.name
    _create_histogram(deviations, tolerance, hist_path)
    story.append(Image(hist_path, width=USABLE_W, height=USABLE_W * 0.46))

    # ── Сборка документа ──────────────────────────────────────────────────────
    try:
        doc.build(story)
    finally:
        for tmp in (hist_path, cbar_path):
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass

    return output_path
