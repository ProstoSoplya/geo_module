"""
panels.py — Боковые панели пользовательского интерфейса.

ControlPanel — панель настройки параметров с двумя режимами:
    Простой:    только поле допуска, все параметры — из config по умолчанию.
    Расширенный: все группы параметров с tooltips.
ResultsPanel — панель с числовыми результатами анализа.
LogPanel     — панель лога (сообщения о ходе работы).
"""

import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QPushButton,
    QGroupBox, QTextEdit, QSizePolicy, QFrame, QScrollArea, QFileDialog,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QTextCursor, QFont

logger = logging.getLogger(__name__)

_COLORMAPS = ["coolwarm", "RdYlGn_r", "jet"]


class _ArrowOnHoverFilter(QObject):
    """Показывает стрелку при наведении на кнопку, когда активен глобальный WaitCursor."""
    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.Enter:
            if QApplication.overrideCursor() is not None:
                QApplication.changeOverrideCursor(Qt.CursorShape.ArrowCursor)
        elif t == QEvent.Type.Leave:
            if QApplication.overrideCursor() is not None:
                QApplication.changeOverrideCursor(Qt.CursorShape.WaitCursor)
        return False


class ControlPanel(QWidget):
    """
    Панель настройки параметров алгоритмов.

    Два режима:
        Простой     — только допуск, остальное из config.
        Расширенный — все параметры в трёх группах.

    Сигналы:
        param_changed(list, object) — при изменении любого параметра.
        Путь в конфиге + новое значение. Пример:
        (["preprocessing", "voxel_size"], 0.0)
    """

    param_changed = pyqtSignal(list, object)
    recalculate_requested = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._updating = False
        self._recalc_buttons: list[QPushButton] = []
        self._setup_ui()

    # ── Построение UI ──────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        self.setStyleSheet("color: #c0c0c0;")
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        self._adv_check = QCheckBox("Расширенный режим")
        self._adv_check.setToolTip(
            "Показать все параметры алгоритмов.\n"
            "В простом режиме используются значения из конфига по умолчанию."
        )
        outer.addWidget(self._adv_check)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(2, 2, 2, 2)
        self._content_layout.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        tol_val = float(self.config.get("analysis", {}).get("tolerance_mm", 0.5))
        thr_val = int(self.config.get("analysis", {}).get("conformance_threshold", 95))

        self._simple_widget = self._build_simple(tol_val, thr_val)
        self._content_layout.addWidget(self._simple_widget)

        self._advanced_widget = self._build_advanced(tol_val, thr_val)
        self._content_layout.addWidget(self._advanced_widget)

        self._content_layout.addStretch()

        advanced = bool(self.config.get("ui", {}).get("advanced_mode", False))
        self._adv_check.setChecked(advanced)
        self._apply_mode(advanced)
        self._adv_check.toggled.connect(self._on_mode_changed)

    def _build_simple(self, tol_val: float, thr_val: int) -> QWidget:
        """Виджет простого режима: подсказка + поле допуска + порог соответствия."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hint = QLabel(
            "Параметры алгоритмов подобраны\n"
            "автоматически. Задайте допуск:"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #c0c0c0; font-size: 11px;")
        layout.addWidget(hint)

        self._simple_tol = self._make_double_spin(tol_val, 0.001, 50.0, 0.05, 3, "Допуск в мм")
        self._simple_tol.valueChanged.connect(self._on_simple_tol_changed)
        layout.addLayout(self._tol_row("Допуск ±(мм):", self._simple_tol))

        self._simple_thr = self._make_int_spin(
            thr_val, 80, 100, 1,
            "Минимальная доля точек в допуске для соответствия"
        )
        self._simple_thr.valueChanged.connect(self._on_simple_thr_changed)
        layout.addLayout(self._tol_row("Порог соответствия (%):", self._simple_thr))

        return w

    def _build_advanced(self, tol_val: float, thr_val: int) -> QWidget:
        """Виджет расширенного режима: все группы параметров."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        pre = self.config.get("preprocessing", {})
        reg = self.config.get("registration",  {})
        ui  = self.config.get("ui", {})

        # ── Предобработка ──────────────────────────────────────────
        pre_group = QGroupBox("Предобработка")
        pg = QVBoxLayout(pre_group)

        voxel_val = pre.get("voxel_size", 0)
        try:
            voxel_val = float(voxel_val)
        except (ValueError, TypeError):
            voxel_val = 0.0
        self._voxel_spin = self._make_double_spin(
            voxel_val, 0.0, 50.0, 0.1, 3, "0 = авто"
        )
        pg.addLayout(self._spin_row("Воксель (мм, 0=авто):", self._voxel_spin))
        self._voxel_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["preprocessing", "voxel_size"], round(v, 4))
        )

        self._sor_k_spin = self._make_int_spin(
            int(pre.get("sor_neighbors", 20)), 5, 100, 1,
            "Соседей для фильтрации"
        )
        pg.addLayout(self._spin_row("SOR k (соседей):", self._sor_k_spin))
        self._sor_k_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["preprocessing", "sor_neighbors"], v)
        )

        self._sor_std_spin = self._make_double_spin(
            float(pre.get("sor_std_ratio", 2.0)), 0.5, 5.0, 0.1, 1,
            "Порог фильтрации шумов"
        )
        pg.addLayout(self._spin_row("SOR σ (строгость):", self._sor_std_spin))
        self._sor_std_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["preprocessing", "sor_std_ratio"], round(v, 4))
        )
        layout.addWidget(pre_group)

        # ── Регистрация ────────────────────────────────────────────
        reg_group = QGroupBox("Регистрация")
        rg = QVBoxLayout(reg_group)

        self._ransac_n_spin = self._make_int_spin(
            int(reg.get("ransac_n_starts", 5)), 1, 20, 1,
            "Число попыток совмещения"
        )
        rg.addLayout(self._spin_row("Попытки RANSAC:", self._ransac_n_spin))
        self._ransac_n_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["registration", "ransac_n_starts"], v)
        )

        self._icp_coarse_spin = self._make_double_spin(
            float(reg.get("icp_coarse_pct", 5.0)), 1.0, 20.0, 0.5, 1,
            "% от размера детали"
        )
        rg.addLayout(self._spin_row("Грубый ICP (%):", self._icp_coarse_spin))
        self._icp_coarse_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["registration", "icp_coarse_pct"], round(v, 4))
        )

        self._icp_fine_spin = self._make_double_spin(
            float(reg.get("icp_fine_pct", 1.0)), 0.1, 5.0, 0.1, 1,
            "% от размера детали"
        )
        rg.addLayout(self._spin_row("Точный ICP (%):", self._icp_fine_spin))
        self._icp_fine_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["registration", "icp_fine_pct"], round(v, 4))
        )

        self._icp_iter_spin = self._make_int_spin(
            int(reg.get("icp_max_iter", 140)), 10, 200, 10,
            "Предел итераций"
        )
        rg.addLayout(self._spin_row("Итераций ICP:", self._icp_iter_spin))
        self._icp_iter_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["registration", "icp_max_iter"], v)
        )
        layout.addWidget(reg_group)

        # ── Расчёт отклонений ──────────────────────────────────────
        dev_group = QGroupBox("Расчёт отклонений")
        dg = QVBoxLayout(dev_group)

        self._adv_tol_spin = self._make_double_spin(tol_val, 0.001, 50.0, 0.05, 3, "Допуск в мм")
        self._adv_tol_spin.valueChanged.connect(self._on_adv_tol_changed)
        dg.addLayout(self._tol_row("Допуск ±(мм):", self._adv_tol_spin))

        self._adv_thr_spin = self._make_int_spin(
            thr_val, 80, 100, 1,
            "Минимальная доля точек в допуске для соответствия"
        )
        self._adv_thr_spin.valueChanged.connect(self._on_adv_thr_changed)
        dg.addLayout(self._tol_row("Порог соответствия (%):", self._adv_thr_spin))

        cm_row = QHBoxLayout()
        cm_label = QLabel("Цветовая шкала:")
        cm_label.setToolTip(
            "Палитра раскраски облака точек по отклонениям:\n"
            "coolwarm   — синий → белый → красный\n"
            "RdYlGn_r   — красный → жёлтый → зелёный\n"
            "jet        — синий → зелёный → красный"
        )
        cm_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._colormap_combo = QComboBox()
        self._colormap_combo.addItems(_COLORMAPS)
        self._colormap_combo.setFixedWidth(110)
        self._colormap_combo.setToolTip(cm_label.toolTip())
        current_cm = ui.get("colormap", "coolwarm")
        if current_cm in _COLORMAPS:
            self._colormap_combo.setCurrentText(current_cm)
        cm_row.addWidget(cm_label)
        cm_row.addWidget(self._colormap_combo)
        dg.addLayout(cm_row)
        self._colormap_combo.currentTextChanged.connect(
            lambda v: self.param_changed.emit(["ui", "colormap"], v)
        )
        layout.addWidget(dev_group)

        return w

    # ── Слоты ─────────────────────────────────────────────────────

    def _on_mode_changed(self, checked: bool):
        self._apply_mode(checked)
        self.param_changed.emit(["ui", "advanced_mode"], checked)

    def _apply_mode(self, advanced: bool):
        self._simple_widget.setVisible(not advanced)
        self._advanced_widget.setVisible(advanced)

    def _on_simple_tol_changed(self, value: float):
        """Простой допуск изменился → синхронизируем расширенный."""
        if self._updating:
            return
        self._updating = True
        self._adv_tol_spin.setValue(value)
        self._updating = False
        self.param_changed.emit(["analysis", "tolerance_mm"], round(value, 4))

    def _on_adv_tol_changed(self, value: float):
        """Расширенный допуск изменился → синхронизируем простой."""
        if self._updating:
            return
        self._updating = True
        self._simple_tol.setValue(value)
        self._updating = False
        self.param_changed.emit(["analysis", "tolerance_mm"], round(value, 4))

    def _on_simple_thr_changed(self, value: int):
        """Простой порог соответствия → синхронизируем расширенный."""
        if self._updating:
            return
        self._updating = True
        self._adv_thr_spin.setValue(value)
        self._updating = False
        self.param_changed.emit(["analysis", "conformance_threshold"], int(value))

    def _on_adv_thr_changed(self, value: int):
        """Расширенный порог соответствия → синхронизируем простой."""
        if self._updating:
            return
        self._updating = True
        self._simple_thr.setValue(value)
        self._updating = False
        self.param_changed.emit(["analysis", "conformance_threshold"], int(value))

    # ── Вспомогательные фабрики ────────────────────────────────────

    def _make_double_spin(self, value: float, min_val: float, max_val: float,
                           step: float, decimals: int, tooltip: str = "") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setFixedWidth(100)
        if tooltip:
            spin.setToolTip(tooltip)
        return spin

    def _make_int_spin(self, value: int, min_val: int, max_val: int,
                        step: int, tooltip: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setFixedWidth(100)
        if tooltip:
            spin.setToolTip(tooltip)
        return spin

    def _spin_row(self, label_text: str, spin_widget) -> QHBoxLayout:
        """Строка: метка слева + спинбокс справа."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tip = spin_widget.toolTip()
        if tip:
            label.setToolTip(tip)
        row.addWidget(label)
        row.addWidget(spin_widget)
        return row

    def _tol_row(self, label_text: str, spin_widget) -> QHBoxLayout:
        """Строка допуска: метка + спинбокс + кнопка ↻ быстрого пересчёта."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tip = spin_widget.toolTip()
        if tip:
            label.setToolTip(tip)
        row.addWidget(label)
        row.addWidget(spin_widget)

        btn = QPushButton("↻")
        btn.setFixedSize(24, 24)
        btn.setToolTip("Пересчитать статистику без повторной регистрации")
        btn.setStyleSheet(
            "QPushButton {"
            "  background: #1e3a2e; color: #66cc88;"
            "  border: 1px solid #336644; border-radius: 3px;"
            "  font-size: 13px; padding: 0px;"
            "}"
            "QPushButton:hover { background: #2a4e3a; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a1a; }"
        )
        btn.setEnabled(False)
        btn.clicked.connect(self.recalculate_requested)
        self._recalc_buttons.append(btn)
        row.addWidget(btn)
        return row

    # ── Публичные методы ───────────────────────────────────────────

    def set_has_results(self, has_results: bool):
        """Включает/выключает кнопки ↻ в зависимости от наличия результатов анализа."""
        for btn in self._recalc_buttons:
            btn.setEnabled(has_results)

    def apply_config(self, config: dict):
        """Обновляет все поля из словаря конфига (например, после загрузки проекта)."""
        self._updating = True
        try:
            pre = config.get("preprocessing", {})
            reg = config.get("registration",  {})
            ana = config.get("analysis",      {})
            ui  = config.get("ui",            {})

            if "voxel_size" in pre:
                self._voxel_spin.setValue(float(pre["voxel_size"]))
            if "sor_neighbors" in pre:
                self._sor_k_spin.setValue(int(pre["sor_neighbors"]))
            if "sor_std_ratio" in pre:
                self._sor_std_spin.setValue(float(pre["sor_std_ratio"]))

            if "ransac_n_starts" in reg:
                self._ransac_n_spin.setValue(int(reg["ransac_n_starts"]))
            if "icp_coarse_pct" in reg:
                self._icp_coarse_spin.setValue(float(reg["icp_coarse_pct"]))
            if "icp_fine_pct" in reg:
                self._icp_fine_spin.setValue(float(reg["icp_fine_pct"]))
            if "icp_max_iter" in reg:
                self._icp_iter_spin.setValue(int(reg["icp_max_iter"]))

            if "tolerance_mm" in ana:
                tol = float(ana["tolerance_mm"])
                self._adv_tol_spin.setValue(tol)
                self._simple_tol.setValue(tol)

            if "conformance_threshold" in ana:
                thr = int(ana["conformance_threshold"])
                self._adv_thr_spin.setValue(thr)
                self._simple_thr.setValue(thr)

            if "colormap" in ui and ui["colormap"] in _COLORMAPS:
                self._colormap_combo.setCurrentText(ui["colormap"])
        finally:
            self._updating = False


# ──────────────────────────────────────────────────────────────────


class ResultsPanel(QWidget):
    """
    Панель числовых результатов анализа.
    Показывает 5 ключевых метрик + вердикт.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = {}
        self._threshold = 95.0
        self._setup_ui()

    def set_threshold(self, threshold: float):
        """Устанавливает порог соответствия (%) для вердикта."""
        self._threshold = float(threshold)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        self.setStyleSheet("color: #c0c0c0;")
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Результаты анализа")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        metrics = [
            ("mean_deviation",    "Среднее отклонение", "мм"),
            ("registration_rmse", "RMSE",               "мм"),
            ("min_deviation",     "Мин. отклонение",    "мм"),
            ("max_deviation",     "Макс. отклонение",   "мм"),
            ("within_tolerance",  "Доля в допуске",     "%"),
        ]

        for key, name, unit in metrics:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)

            name_label = QLabel(name + ":")
            name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            val_label = QLabel("—")
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            val_label.setMinimumWidth(80)
            val_label.setFont(QFont("Courier New", 10))

            unit_label = QLabel(unit)
            unit_label.setMinimumWidth(25)

            row_layout.addWidget(name_label)
            row_layout.addWidget(val_label)
            row_layout.addWidget(unit_label)
            layout.addWidget(row)

            self._labels[key] = (val_label, unit)

        layout.addSpacing(8)
        self.verdict_label = QLabel("Ожидание анализа...")
        self.verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_label.setWordWrap(True)
        self.verdict_label.setStyleSheet("padding: 6px; border-radius: 4px; color: #c0c0c0;")
        layout.addWidget(self.verdict_label)

        layout.addStretch()

    def update_results(self, stats: dict):
        """Обновляет метрики после анализа."""
        format_map = {
            "registration_rmse": lambda v: f"{v:.6f}",
            "mean_deviation":    lambda v: f"{v:+.4f}",
            "max_deviation":     lambda v: f"{v:+.4f}",
            "min_deviation":     lambda v: f"{v:+.4f}",
            "within_tolerance":  lambda v: f"{v*100:.1f}",
        }

        for key, (label, _) in self._labels.items():
            if key in stats:
                fmt = format_map.get(key, lambda v: f"{v:.4f}")
                label.setText(fmt(stats[key]))

        within_pct = stats.get("within_tolerance", 0) * 100
        tolerance  = stats.get("tolerance", 0.5)
        if within_pct >= self._threshold:
            self.verdict_label.setText(f"✓ СООТВЕТСТВУЕТ ДОПУСКАМ\n(±{tolerance:.3f} мм)")
            self.verdict_label.setStyleSheet(
                "padding: 6px; border-radius: 4px; "
                "background: #1B5E20; color: #A5D6A7; font-weight: bold;"
            )
        else:
            self.verdict_label.setText(f"✗ НЕ СООТВЕТСТВУЕТ\n(в допуске {within_pct:.1f}%)")
            self.verdict_label.setStyleSheet(
                "padding: 6px; border-radius: 4px; "
                "background: #7f0000; color: #FFCDD2; font-weight: bold;"
            )

    def reset(self):
        for key, (label, _) in self._labels.items():
            label.setText("—")
        self.verdict_label.setText("Ожидание анализа...")
        self.verdict_label.setStyleSheet("padding: 6px; border-radius: 4px; color: #c0c0c0;")


# ──────────────────────────────────────────────────────────────────


class LogPanel(QWidget):
    """Панель лога — цветные сообщения, сохранение, очистка, отмена анализа."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(2, 2, 2, 0)
        btn_row.setSpacing(4)

        self._save_btn = QPushButton("Сохранить лог")
        self._save_btn.setFixedHeight(22)
        self._save_btn.clicked.connect(self._save_log)

        self._clear_btn = QPushButton("Очистить лог")
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.clicked.connect(self.text_edit_clear)

        self._cancel_btn = QPushButton("■  Отмена")
        self._cancel_btn.setFixedHeight(22)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #C62828; color: white; "
            "padding: 2px 10px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background: #D32F2F; }"
        )
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_cursor_filter = _ArrowOnHoverFilter(self)
        self._cancel_btn.installEventFilter(self._cancel_cursor_filter)

        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Courier New", 9))
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.text_edit, 1)

    def _classify_color(self, message: str) -> str:
        m = message.lower()
        if any(k in m for k in ("ошибка", "error")):
            return "#FF6B6B"
        if any(k in m for k in ("предупреждение", "warning", "внимание")):
            return "#FFA726"
        if any(k in m for k in ("завершён", "успешно", "сохранён")):
            return "#66BB6A"
        return "#e8e8e8"

    def append(self, message: str):
        color = self._classify_color(message)
        ts = datetime.now().strftime("%H:%M:%S")
        safe = (message.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
        self.text_edit.insertHtml(
            f'<span style="color:#909090;">[{ts}]</span> '
            f'<span style="color:{color}; white-space:pre;">{safe}</span><br>'
        )
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)

    def text_edit_clear(self):
        self.text_edit.clear()

    def clear(self):
        self.text_edit.clear()

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лог", "log.txt",
            "Текстовые файлы (*.txt);;Все файлы (*.*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_edit.toPlainText())

    def set_analysis_running(self, running: bool):
        self._cancel_btn.setVisible(running)

    def set_cancel_enabled(self, enabled: bool):
        self._cancel_btn.setEnabled(enabled)

    def set_cancel_cursor(self, shape):
        self._cancel_btn.setCursor(shape)
