"""
panels.py — Боковые панели пользовательского интерфейса.

ControlPanel — панель настройки параметров с двумя режимами:
    Базовый:     единицы, допуск, порог соответствия.
    Расширенный: + предобработка, регистрация, выравнивание.
ResultsPanel — панель с числовыми результатами анализа.
LogPanel     — панель лога (сообщения о ходе работы).
"""

import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QPushButton,
    QGroupBox, QTextEdit, QSizePolicy, QFrame, QFileDialog,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QTextCursor, QFont

logger = logging.getLogger(__name__)

# (label, config_key) для комбобоксов единиц измерения
_UNIT_ITEMS = [
    ("мм",      "mm"),
    ("см",      "cm"),
    ("м",       "m"),
    ("дюйм",    "in"),
]

# (label, config_key) для режима выравнивания
_ALIGNMENT_ITEMS = [
    ("Наилучшее вписывание", "best_fit"),
    ("Консервативный",       "conservative"),
]


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
        Базовый:      единицы, допуск, порог соответствия.
        Расширенный:  + предобработка, регистрация, режим выравнивания.

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
            "В базовом режиме используются значения из конфига по умолчанию."
        )
        outer.addWidget(self._adv_check)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        # ── Единицы — всегда видимы ──────────────────────────────
        outer.addWidget(self._build_units_group())

        # ── Допуск и порог — всегда видимы ───────────────────────
        outer.addWidget(self._build_tolerance_group())

        # ── Расширенные параметры (без внутреннего scroll) ────────
        self._adv_sep = QFrame()
        self._adv_sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(self._adv_sep)

        self._build_advanced_groups()
        outer.addWidget(self._preprocess_group)
        outer.addWidget(self._registration_group)
        outer.addWidget(self._alignment_group)

        outer.addStretch()

        advanced = bool(self.config.get("ui", {}).get("advanced_mode", False))
        self._adv_check.setChecked(advanced)
        self._apply_mode(advanced)
        self._adv_check.toggled.connect(self._on_mode_changed)

    def _build_tolerance_group(self) -> QGroupBox:
        """Допуск ± и порог соответствия — всегда видимы в обоих режимах."""
        group = QGroupBox("Параметры анализа")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(6)

        tol_val = float(self.config.get("analysis", {}).get("tolerance_mm", 0.5))
        thr_val = int(self.config.get("analysis", {}).get("conformance_threshold", 95))

        self._tol_spin = self._make_double_spin(tol_val, 0.001, 50.0, 0.05, 3, "Допуск в мм")
        self._tol_spin.valueChanged.connect(self._on_tol_changed)
        layout.addLayout(self._tol_row("Допуск ±(мм):", self._tol_spin))

        self._thr_spin = self._make_int_spin(
            thr_val, 80, 100, 1,
            "Минимальная доля точек в допуске для соответствия"
        )
        self._thr_spin.valueChanged.connect(self._on_thr_changed)
        layout.addLayout(self._tol_row("Порог соответствия (%):", self._thr_spin))

        return group

    def _build_advanced_groups(self):
        """Создаёт три группы расширенных параметров как атрибуты экземпляра."""
        pre = self.config.get("preprocessing", {})
        reg = self.config.get("registration",  {})

        # ── Предобработка ──────────────────────────────────────────
        self._preprocess_group = QGroupBox("Предобработка")
        pg = QVBoxLayout(self._preprocess_group)

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

        # ── Регистрация ────────────────────────────────────────────
        self._registration_group = QGroupBox("Регистрация")
        rg = QVBoxLayout(self._registration_group)

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
            int(reg.get("icp_max_iter", 50)), 10, 200, 10,
            "Предел итераций"
        )
        rg.addLayout(self._spin_row("Итераций ICP:", self._icp_iter_spin))
        self._icp_iter_spin.valueChanged.connect(
            lambda v: self.param_changed.emit(["registration", "icp_max_iter"], v)
        )

        # ── Режим выравнивания ─────────────────────────────────────
        self._alignment_group = QGroupBox("Режим выравнивания")
        ag = QVBoxLayout(self._alignment_group)
        ag.setContentsMargins(6, 4, 6, 6)
        ag.setSpacing(4)

        hint = QLabel(
            "Наилучшее вписывание: меньше RMSE,\n"
            "но ICP может скрыть реальное отклонение.\n"
            "Консервативный: только грубое совмещение."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #909090; font-size: 10px;")
        ag.addWidget(hint)

        mode = reg.get("alignment_mode", "best_fit")
        self._alignment_combo = QComboBox()
        for label, key in _ALIGNMENT_ITEMS:
            self._alignment_combo.addItem(label, key)
        for i in range(self._alignment_combo.count()):
            if self._alignment_combo.itemData(i) == mode:
                self._alignment_combo.setCurrentIndex(i)
                break
        self._alignment_combo.setToolTip(hint.text())

        arow = QHBoxLayout()
        arow.setContentsMargins(0, 0, 0, 0)
        albl = QLabel("Режим:")
        albl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        arow.addWidget(albl)
        arow.addWidget(self._alignment_combo)
        ag.addLayout(arow)

        self._alignment_combo.currentIndexChanged.connect(self._on_alignment_changed)

    def _build_units_group(self) -> QWidget:
        """Группа «Единицы измерения» — два комбобокса CAD и Скан."""
        units = self.config.get("units", {})

        group = QGroupBox("Единицы измерения")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(6, 4, 6, 6)
        gl.setSpacing(4)

        hint = QLabel("Выберите единицы файлов.\nПрограмма приведёт всё к мм.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #909090; font-size: 10px;")
        gl.addWidget(hint)

        self._cad_unit_combo  = self._make_unit_combo(units.get("cad",  "mm"))
        self._scan_unit_combo = self._make_unit_combo(units.get("scan", "mm"))

        gl.addLayout(self._unit_row("CAD:",  self._cad_unit_combo))
        gl.addLayout(self._unit_row("Скан:", self._scan_unit_combo))

        self._cad_unit_combo.currentIndexChanged.connect(self._on_cad_unit_changed)
        self._scan_unit_combo.currentIndexChanged.connect(self._on_scan_unit_changed)

        note = QLabel("STL/PLY не хранят единицы.\nСверьте габариты с реальной деталью.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #707070; font-size: 9px;")
        gl.addWidget(note)

        return group

    def _on_alignment_changed(self):
        if not self._updating:
            self.param_changed.emit(
                ["registration", "alignment_mode"],
                self._alignment_combo.currentData()
            )

    @staticmethod
    def _set_unit_combo(combo: QComboBox, key: str):
        """Устанавливает комбобокс по ключу единицы ("mm", "cm", …)."""
        if key is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == key:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _make_unit_combo(current_key: str) -> QComboBox:
        combo = QComboBox()
        for label, key in _UNIT_ITEMS:
            combo.addItem(label, key)
        for i in range(combo.count()):
            if combo.itemData(i) == current_key:
                combo.setCurrentIndex(i)
                break
        combo.setFixedWidth(100)
        return combo

    @staticmethod
    def _unit_row(label_text: str, combo: QComboBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label_text)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(lbl)
        row.addWidget(combo)
        return row

    def _on_cad_unit_changed(self):
        if not self._updating:
            self.param_changed.emit(["units", "cad"], self._cad_unit_combo.currentData())

    def _on_scan_unit_changed(self):
        if not self._updating:
            self.param_changed.emit(["units", "scan"], self._scan_unit_combo.currentData())

    # ── Слоты ─────────────────────────────────────────────────────

    def _on_mode_changed(self, checked: bool):
        self._apply_mode(checked)
        self.param_changed.emit(["ui", "advanced_mode"], checked)
        if not checked:
            self._updating = True
            for i in range(self._alignment_combo.count()):
                if self._alignment_combo.itemData(i) == "best_fit":
                    self._alignment_combo.setCurrentIndex(i)
                    break
            self._updating = False
            self.param_changed.emit(["registration", "alignment_mode"], "best_fit")

    def _apply_mode(self, advanced: bool):
        self._adv_sep.setVisible(advanced)
        self._preprocess_group.setVisible(advanced)
        self._registration_group.setVisible(advanced)
        self._alignment_group.setVisible(advanced)

    def _on_tol_changed(self, value: float):
        if not self._updating:
            self.param_changed.emit(["analysis", "tolerance_mm"], round(value, 4))

    def _on_thr_changed(self, value: int):
        if not self._updating:
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
                self._tol_spin.setValue(float(ana["tolerance_mm"]))

            if "conformance_threshold" in ana:
                self._thr_spin.setValue(int(ana["conformance_threshold"]))

            units = config.get("units", {})
            self._set_unit_combo(self._cad_unit_combo,  units.get("cad"))
            self._set_unit_combo(self._scan_unit_combo, units.get("scan"))

            align_mode = reg.get("alignment_mode", "best_fit")
            for i in range(self._alignment_combo.count()):
                if self._alignment_combo.itemData(i) == align_mode:
                    self._alignment_combo.setCurrentIndex(i)
                    break
        finally:
            self._updating = False


# ──────────────────────────────────────────────────────────────────


class ResultsPanel(QWidget):
    """
    Панель числовых результатов анализа.
    Показывает метрики, габариты и вердикт.
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

        # ── Результаты измерений ─────────────────────────────────
        metrics_group = QGroupBox("Результаты измерений")
        mg = QVBoxLayout(metrics_group)
        mg.setContentsMargins(6, 4, 6, 4)
        mg.setSpacing(2)

        metrics = [
            ("mean_deviation",    "Среднее отклонение",     "мм"),
            ("registration_rmse", "RMSE",                   "мм"),
            ("min_deviation",     "Мин. отклонение",        "мм"),
            ("max_deviation",     "Макс. отклонение",       "мм"),
            ("within_tolerance",  "Доля в допуске",         "%"),
            ("over_material_pct", "Избыток материала",      "%"),
            ("under_material_pct","Недостаток материала",   "%"),
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
            mg.addWidget(row)

            self._labels[key] = (val_label, unit)
        layout.addWidget(metrics_group)

        # ── Габаритные размеры ───────────────────────────────────
        dim_group = QGroupBox("Габаритные размеры")
        dg = QVBoxLayout(dim_group)
        dg.setContentsMargins(6, 4, 6, 4)
        dg.setSpacing(2)
        for attr, lbl_text in [
            ("_dim_cad",   "CAD:"),
            ("_dim_scan",  "Скан:"),
            ("_dim_delta", "Δ:"),
        ]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 1, 2, 1)
            name_lbl = QLabel(lbl_text)
            name_lbl.setMinimumWidth(38)
            val_lbl = QLabel("—")
            val_lbl.setFont(QFont("Courier New", 9))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            val_lbl.setWordWrap(True)
            rl.addWidget(name_lbl)
            rl.addWidget(val_lbl, 1)
            dg.addWidget(row)
            setattr(self, attr, val_lbl)
        layout.addWidget(dim_group)

        # ── Вердикт ──────────────────────────────────────────────
        layout.addSpacing(4)
        self.verdict_label = QLabel("Ожидание анализа...")
        self.verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_label.setWordWrap(True)
        self.verdict_label.setStyleSheet("padding: 6px; border-radius: 4px; color: #c0c0c0;")
        layout.addWidget(self.verdict_label)

        layout.addStretch()

    def update_results(self, stats: dict):
        """Обновляет метрики после анализа."""
        format_map = {
            "registration_rmse":  lambda v: f"{v:.6f}",
            "mean_deviation":     lambda v: f"{v:+.4f}",
            "max_deviation":      lambda v: f"{v:+.4f}",
            "min_deviation":      lambda v: f"{v:+.4f}",
            "within_tolerance":   lambda v: f"{v*100:.1f}",
            "over_material_pct":  lambda v: f"{v*100:.1f}",
            "under_material_pct": lambda v: f"{v*100:.1f}",
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

        dims = stats.get("dimensions")
        if dims is not None:
            def _f3(t):
                return f"{t[0]:.1f} x {t[1]:.1f} x {t[2]:.1f} мм"
            self._dim_cad.setText(_f3(dims["cad"]))
            self._dim_scan.setText(_f3(dims["scan"]) if dims["scan"] is not None else "—")
            if dims["delta"] is not None:
                d = dims["delta"]
                self._dim_delta.setText(f"{d[0]:+.2f} x {d[1]:+.2f} x {d[2]:+.2f} мм")
            else:
                self._dim_delta.setText("—")

    def reset(self):
        for key, (label, _) in self._labels.items():
            label.setText("—")
        self.verdict_label.setText("Ожидание анализа...")
        self.verdict_label.setStyleSheet("padding: 6px; border-radius: 4px; color: #c0c0c0;")
        self._dim_cad.setText("—")
        self._dim_scan.setText("—")
        self._dim_delta.setText("—")


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

