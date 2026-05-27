"""
main_window.py — Главное окно приложения (MainWindow).

Структура окна:
    ┌─────────────────────────────────────────────────┐
    │ Меню: Файл | Справка                            │
    ├─────────────────────────────────────────────────┤
    │ Тулбар: [Загр.CAD] [Загр.Скан] [Анализ] [PDF]  │
    ├──────────────┬──────────────────────────────────┤
    │  Параметры   │     3D-вид (Open3D)              │
    │  (ControlPanel)                                 │
    ├──────────────┼──────────────────────────────────┤
    │  Результаты  │     Лог                          │
    └──────────────┴──────────────────────────────────┘
    │ Строка состояния: Модель | Скан | Этап | Progress│
    └─────────────────────────────────────────────────┘
"""

import logging
import os
import time

import numpy as np
import open3d as o3d

os.environ.setdefault("QT_OPENGL", "desktop")

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QPushButton, QFileDialog, QMessageBox,
    QProgressBar, QProgressDialog, QLabel, QToolBar, QStatusBar,
    QApplication
)
from PyQt6.QtCore import Qt, QSize, QObject, QEvent
from PyQt6.QtGui import QAction, QIcon

from core.project_manager import ProjectManager
from core.worker import AnalysisWorker
from core.algorithms.report import generate_report
from core.algorithms.deviation import compute_statistics, colorize_point_cloud
from core.algorithms.dimensions import bbox_summary, suggest_unit_mismatch_hint, compute_dimensions
from ui.panels import ControlPanel, ResultsPanel, LogPanel
from ui.help_dialog import HelpDialog, AboutDialog
from ui.viewer_widget import ViewerWidget

logger = logging.getLogger(__name__)


class _ArrowOnHoverFilter(QObject):
    """Принудительно показывает стрелку при наведении на кнопку,
    даже когда активен глобальный WaitCursor."""
    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.Enter:
            if QApplication.overrideCursor() is not None:
                QApplication.changeOverrideCursor(Qt.CursorShape.ArrowCursor)
        elif t == QEvent.Type.Leave:
            if QApplication.overrideCursor() is not None:
                QApplication.changeOverrideCursor(Qt.CursorShape.WaitCursor)
        return False


class MainWindow(QMainWindow):
    """Главное окно приложения."""

    def __init__(self, config: dict):
        super().__init__()
        self.config  = config
        self.setStyleSheet("QWidget { color: #c0c0c0; }")
        self.manager = ProjectManager(config)
        self.worker: AnalysisWorker = None

        self._analysis_start   = 0.0
        self._current_status   = "Готов"
        self._heavy_params_dirty = True   # True пока не выполнен хотя бы один анализ
        self._last_dir = self.config.get("ui", {}).get("last_dir", "")

        self.setWindowTitle("Модуль анализа отклонений геометрии деталей")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)

        # Принимаем файлы drag & drop
        self.setAcceptDrops(True)

        self._setup_ui()
        self._update_button_states()
        self._update_status_info()

        logger.info("Главное окно инициализировано")

    # ── Построение UI ──────────────────────────────────────────────

    def _setup_ui(self):
        self._create_menu()
        self._create_toolbar()
        self._create_status_bar()
        self._create_central_widget()

    def _create_menu(self):
        menubar = self.menuBar()

        # ── Меню Файл ─────────────────────────────────────────────
        file_menu = menubar.addMenu("Файл")

        open_cad_action = QAction("Загрузить CAD-модель...", self)
        open_cad_action.setShortcut("Ctrl+O")
        open_cad_action.triggered.connect(self.load_cad)
        file_menu.addAction(open_cad_action)

        open_scan_action = QAction("Загрузить облако точек...", self)
        open_scan_action.setShortcut("Ctrl+Shift+O")
        open_scan_action.triggered.connect(self.load_scan)
        file_menu.addAction(open_scan_action)

        file_menu.addSeparator()

        save_project_action = QAction("Сохранить проект...", self)
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        open_project_action = QAction("Открыть проект...", self)
        open_project_action.setShortcut("Ctrl+P")
        open_project_action.triggered.connect(self.open_project)
        file_menu.addAction(open_project_action)

        file_menu.addSeparator()

        save_report_action = QAction("Сохранить отчёт PDF...", self)
        save_report_action.setShortcut("Ctrl+R")
        save_report_action.triggered.connect(self.save_report)
        file_menu.addAction(save_report_action)

        file_menu.addSeparator()
        exit_action = QAction("Выход", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ── Меню Справка ──────────────────────────────────────────
        help_menu = menubar.addMenu("Справка")

        help_action = QAction("Руководство пользователя", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self._show_help)
        help_menu.addAction(help_action)

        help_menu.addSeparator()

        about_action = QAction("О программе", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        toolbar = QToolBar("Основные действия")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.btn_load_cad  = QPushButton("Загрузить CAD-модель")
        self.btn_load_scan = QPushButton("Загрузить облако точек")
        self.btn_run       = QPushButton("▶  Запустить анализ")
        self.btn_cancel    = QPushButton("■  Отмена")
        self.btn_report    = QPushButton("Сохранить отчёт PDF")

        self.btn_load_cad.clicked.connect(self.load_cad)
        self.btn_load_scan.clicked.connect(self.load_scan)
        self.btn_run.clicked.connect(self.run_analysis)
        self.btn_cancel.clicked.connect(self.cancel_analysis)
        self.btn_report.clicked.connect(self.save_report)

        self.btn_run.setStyleSheet(
            "QPushButton { background: #ad1457; color: white; "
            "padding: 4px 12px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #e91e63; }"
            "QPushButton:disabled { background: #4a4a4a; color: #777; border: 1px solid #555; }"
        )
        self.btn_cancel.setStyleSheet(
            "QPushButton { background: #C62828; color: white; "
            "padding: 4px 12px; border-radius: 4px; }"
        )
        self.btn_cancel.setVisible(False)
        # Стрелка при наведении на кнопку отмены даже во время анализа (WaitCursor)
        self._cancel_cursor_filter = _ArrowOnHoverFilter(self)
        self.btn_cancel.installEventFilter(self._cancel_cursor_filter)

        toolbar.addWidget(self.btn_load_cad)
        toolbar.addWidget(self.btn_load_scan)
        toolbar.addSeparator()
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.btn_cancel)
        toolbar.addSeparator()
        toolbar.addWidget(self.btn_report)

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Информация о загруженных файлах и текущем статусе (левая часть)
        self.status_info_label = QLabel("Готов к работе")
        self.status_info_label.setMinimumWidth(300)
        self.status_bar.addWidget(self.status_info_label, 1)

        # Текст текущего этапа (показывается во время анализа)
        self._stage_label = QLabel("")
        self._stage_label.setStyleSheet("color: #e91e63; font-style: italic;")
        self._stage_label.setMinimumWidth(240)
        self._stage_label.setVisible(False)
        self.status_bar.addPermanentWidget(self._stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

    def _create_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Левая панель ───────────────────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.control_panel = ControlPanel(self.config)
        self.control_panel.param_changed.connect(self._on_param_changed)
        self.control_panel.recalculate_requested.connect(self._on_recalculate_tolerance)
        left_layout.addWidget(self.control_panel)

        self.results_panel = ResultsPanel()
        self.results_panel.set_threshold(
            self.config.get("analysis", {}).get("conformance_threshold", 95)
        )
        left_layout.addWidget(self.results_panel)

        left_panel.setMaximumWidth(320)
        left_panel.setMinimumWidth(220)
        h_splitter.addWidget(left_panel)

        # ── Правая часть: 3D-вид сверху, лог снизу ───────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self.viewer = ViewerWidget(self.config, self)
        self.viewer.setMinimumHeight(300)
        right_layout.addWidget(self.viewer, 1)   # растягивается

        self.log_panel = LogPanel()
        self.log_panel.cancel_requested.connect(self.cancel_analysis)
        right_layout.addWidget(self.log_panel, 0)   # фиксированная высота

        h_splitter.addWidget(right_panel)
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(h_splitter, 1)

    # ── Drag & Drop ────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.isLocalFile() for url in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        for url in urls:
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ext  = os.path.splitext(path)[1].lower()
            if ext in (".stl", ".obj"):
                self._load_cad_from_path(path)
            elif ext in (".ply", ".pcd", ".xyz", ".pts"):
                self._load_scan_from_path(path)
            else:
                QMessageBox.warning(
                    self, "Неподдерживаемый формат",
                    f"Неподдерживаемый формат файла: «{os.path.basename(path)}»\n\n"
                    "CAD-модель: STL, OBJ\n"
                    "Облако точек: PLY, PCD, XYZ, PTS"
                )

    # ── Загрузка файлов ────────────────────────────────────────────

    def load_cad(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать CAD-модель", self._last_dir,
            "3D-модели (*.stl *.obj);;Все файлы (*.*)"
        )
        if path:
            self._last_dir = os.path.dirname(path)
            self.manager.update_config(["ui", "last_dir"], self._last_dir)
            self._load_cad_from_path(path)

    def load_scan(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать облако точек", self._last_dir,
            "Облака точек (*.ply *.pcd *.xyz *.pts);;Все файлы (*.*)"
        )
        if path:
            self._last_dir = os.path.dirname(path)
            self.manager.update_config(["ui", "last_dir"], self._last_dir)
            self._load_scan_from_path(path)

    def _load_cad_from_path(self, path: str):
        dlg = self._make_loading_dialog("Загрузка CAD-модели...", path)
        try:
            self.manager.load_cad(path)
            self._log(f"CAD-модель загружена: {os.path.basename(path)}")
            self._log(
                f"  Вершин: {len(self.manager.mesh.vertices):,}, "
                f"треугольников: {len(self.manager.mesh.triangles):,}"
            )
            (lx, ly, lz), diag = bbox_summary(self.manager.mesh)
            self._log(f"  Габариты: {lx:.1f} x {ly:.1f} x {lz:.1f} мм  (диаг. {diag:.1f} мм)")
            self.results_panel.reset()
            self.viewer.load_mesh_preview(self.manager.mesh)
        except Exception as e:
            self._show_error("Ошибка загрузки CAD", str(e))
        finally:
            if dlg:
                dlg.close()

        self._update_button_states()
        self._update_status_info()
        QApplication.processEvents()   # дать Qt обновить UI после загрузки

    def _load_scan_from_path(self, path: str):
        dlg = self._make_loading_dialog("Загрузка облака точек...", path)
        cancelled = False
        try:
            self.manager.load_scan(path)
            n_points = len(self.manager.pcd.points)

            if n_points > 5_000_000:
                msg = QMessageBox(self)
                msg.setWindowTitle("Предупреждение о большом файле")
                msg.setText(
                    f"Загружено облако из {n_points:,} точек.\n"
                    "Обработка может занять длительное время.\n\n"
                    "Рекомендуется уменьшить плотность в расширенных настройках\n"
                    "(уменьшить размер вокселя)."
                )
                btn_cont = msg.addButton("Продолжить", QMessageBox.ButtonRole.AcceptRole)
                msg.addButton("Отмена загрузки", QMessageBox.ButtonRole.RejectRole)
                msg.setDefaultButton(btn_cont)
                msg.exec()
                if msg.clickedButton() is not btn_cont:
                    self.manager.pcd = None
                    self.manager.scan_path = None
                    cancelled = True

            if not cancelled:
                self._log(f"Облако точек загружено: {os.path.basename(path)}")
                self._log(f"  Точек: {n_points:,}")
                (lx, ly, lz), diag = bbox_summary(self.manager.pcd)
                self._log(f"  Габариты: {lx:.1f} x {ly:.1f} x {lz:.1f} мм  (диаг. {diag:.1f} мм)")
                self.results_panel.reset()
                if self.manager.mesh is None:
                    self.viewer.clear()
        except Exception as e:
            self._show_error("Ошибка загрузки скана", str(e))
        finally:
            if dlg:
                dlg.close()

        self._update_button_states()
        self._update_status_info()
        QApplication.processEvents()   # дать Qt обновить UI после загрузки

    # ── Анализ ─────────────────────────────────────────────────────

    def run_analysis(self):
        if not self.manager.is_ready_for_analysis():
            QMessageBox.warning(self, "Внимание",
                                "Загрузите CAD-модель и облако точек перед анализом.")
            return

        # Если есть результаты и изменены только «лёгкие» параметры —
        # предложить быстрый пересчёт вместо полного анализа
        if self.manager.stats is not None and not self._heavy_params_dirty:
            msg = QMessageBox(self)
            msg.setWindowTitle("Запуск анализа")
            msg.setText(
                "Изменены только допуск или цветовая шкала.\n"
                "Можно пересчитать статистику без повторной регистрации."
            )
            btn_quick  = msg.addButton("Быстрый пересчёт", QMessageBox.ButtonRole.AcceptRole)
            btn_full   = msg.addButton("Полный анализ",    QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = msg.addButton("Отмена",           QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(btn_quick)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked is btn_cancel or clicked is None:
                return
            if clicked is btn_quick:
                self._on_recalculate_tolerance()
                return
            # btn_full → продолжаем в полный анализ

        # ── Предупреждение о несоответствии размеров ────────────────
        if self.manager.mesh is not None and self.manager.pcd is not None:
            mesh_bbox  = self.manager.mesh.get_axis_aligned_bounding_box()
            pcd_bbox   = self.manager.pcd.get_axis_aligned_bounding_box()
            mesh_diag  = float(np.linalg.norm(mesh_bbox.get_extent()))
            pcd_diag   = float(np.linalg.norm(pcd_bbox.get_extent()))
            denom      = max(min(mesh_diag, pcd_diag), 1e-9)
            ratio      = max(mesh_diag, pcd_diag) / denom
            if ratio > 5.0:
                msg = QMessageBox(self)
                msg.setWindowTitle("Предупреждение о размерах")
                msg.setIcon(QMessageBox.Icon.Warning)
                hint = suggest_unit_mismatch_hint(ratio)
                hint_line = f"\n\nВероятная причина: {hint}" if hint else ""
                msg.setText(
                    f"Размеры модели и скана сильно отличаются.\n\n"
                    f"Модель: {mesh_diag:.1f} мм  |  Скан: {pcd_diag:.1f} мм\n"
                    f"Разница: {ratio:.1f}×{hint_line}\n\n"
                    "Проверьте панель «Единицы измерения».\n"
                    "Совмещение может не работать."
                )
                btn_cont = msg.addButton("Продолжить", QMessageBox.ButtonRole.AcceptRole)
                msg.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
                msg.setDefaultButton(btn_cont)
                msg.exec()
                if msg.clickedButton() is not btn_cont:
                    return

        # Если раньше был показан цветной скан — скроем его, перерисовав меш.
        # На «свежем» запуске меш уже на экране с момента загрузки — лишний
        # рендер VTK в главном потоке здесь блокировал бы UI на 5–10 с.
        had_previous_results = self.manager.pcd_colored is not None

        # Сброс результатов предыдущего анализа (если был)
        self.manager.results    = None
        self.manager.stats      = None
        self.manager.pcd_colored = None
        self.manager.deviations  = None
        self.results_panel.reset()

        if had_previous_results:
            self.viewer.load_mesh_preview(self.manager.mesh)

        self._log("=" * 50)
        self._log("Запуск анализа...")
        self._analysis_start = time.time()
        self._set_analysis_running(True)
        self._update_button_states()        # btn_report → серая сразу
        self._update_status_info("Выполняется анализ...")

        # Даём Qt прокачать сообщения — чтобы смена курсора и блокировка
        # кнопок применились ДО того как worker начнёт грузить CPU.
        QApplication.processEvents()

        self.worker = AnalysisWorker(
            self.manager.pcd,
            self.manager.mesh,
            self.config
        )

        # QueuedConnection — сигналы из worker-потока доставляются через event loop
        # главного потока, что гарантирует потокобезопасность (это дефолт для
        # cross-thread соединений, но указываем явно для наглядности)
        qc = Qt.ConnectionType.QueuedConnection
        self.worker.progress_changed.connect(self._on_progress,          qc)
        self.worker.stage_changed.connect(   self._on_stage_changed,     qc)
        self.worker.log_message.connect(     self._log,                  qc)
        self.worker.analysis_finished.connect(self._on_analysis_finished, qc)
        self.worker.analysis_error.connect(   self._on_analysis_error,   qc)

        self.worker.start()

    def cancel_analysis(self):
        if not (self.worker and self.worker.isRunning()):
            return

        # Немедленная обратная связь: обе кнопки отмены в серое состояние,
        # прогресс-бар показывает «Отмена...», лог сообщает пользователю.
        self.btn_cancel.setEnabled(False)
        self.log_panel.set_cancel_enabled(False)
        self.progress_bar.setFormat("Отмена...")
        self._log("Отмена анализа, ожидайте завершения текущего этапа...")
        self._update_status_info("Отмена анализа...")

        # Принудительно отрисовываем UI до того как уйдём в worker.cancel().
        QApplication.processEvents()

        self.worker.cancel()

    def save_report(self):
        if self.manager.stats is None:
            QMessageBox.warning(self, "Внимание", "Сначала выполните анализ.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", "report.pdf", "PDF файлы (*.pdf)"
        )
        if not path:
            return

        try:
            self._log("Генерация PDF-отчёта (6 видов)...")
            screenshot_paths = self.viewer.make_multiview_screenshots()
            mesh = self.manager.mesh
            generate_report(
                output_path=path,
                cad_path=self.manager.cad_path or "—",
                scan_path=self.manager.scan_path or "—",
                deviations=self.manager.deviations,
                stats=self.manager.stats,
                registration_rmse=self.manager.stats.get("registration_rmse", 0),
                screenshot_paths=screenshot_paths,
                mesh_triangles=len(mesh.triangles) if mesh is not None else 0,
                config=self.config,
                unit_cad=self.manager.unit_cad,
                unit_scan=self.manager.unit_scan,
            )
            self._log(f"Отчёт сохранён: {path}")
            QMessageBox.information(self, "Готово", f"Отчёт сохранён:\n{path}")
        except Exception as e:
            self._show_error("Ошибка генерации отчёта", str(e))

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект", "project.json", "JSON файлы (*.json)"
        )
        if path:
            try:
                self.manager.save_project(path)
                self._log(f"Проект сохранён: {path}")
                return True
            except Exception as e:
                self._show_error("Ошибка сохранения", str(e))
        return False

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть проект", "", "JSON файлы (*.json)"
        )
        if not path:
            return

        try:
            project = self.manager.load_project(path)
        except Exception as e:
            self._show_error("Ошибка загрузки проекта", str(e))
            return

        self._log(f"Проект загружен: {path}")

        # Предупреждение о ненайденных файлах
        missing = project.get("missing_files", [])
        if missing:
            names = "\n".join(f"  • {p}" for p in missing)
            QMessageBox.warning(
                self, "Файлы не найдены",
                f"Следующие файлы не найдены по сохранённым путям:\n{names}\n\n"
                "Загрузите их вручную через меню «Файл»."
            )

        # Восстанавливаем конфиг в UI (обновляем спинбоксы)
        if "config" in project:
            self.control_panel.apply_config(project["config"])
            self.results_panel.set_threshold(
                self.config.get("analysis", {}).get("conformance_threshold", 95)
            )

        # Обновляем вид CAD-модели если загружена
        if self.manager.mesh is not None:
            self.viewer.load_mesh_preview(self.manager.mesh)

        # Если есть NPZ с результатами — восстанавливаем без повторного анализа
        npz = project.get("npz_data")
        saved_stats = project.get("stats")
        if npz is not None and "deviations" in npz and saved_stats is not None and self.manager.mesh is not None:
            deviations = npz["deviations"]
            tolerance  = self.config["analysis"]["tolerance_mm"]
            colormap   = self.config.get("ui", {}).get("colormap", "RdYlGn_r")

            # Восстанавливаем зарегистрированное облако точек
            if "pcd_points" in npz:
                pcd_reg = o3d.geometry.PointCloud()
                pcd_reg.points = o3d.utility.Vector3dVector(npz["pcd_points"])
            elif self.manager.pcd is not None:
                pcd_reg = self.manager.pcd
            else:
                pcd_reg = None

            if pcd_reg is not None:
                # Восстанавливаем ambiguous_mask из NPZ (если есть)
                ambiguous_mask = npz.get("ambiguous_mask")
                if ambiguous_mask is not None:
                    ambiguous_mask = ambiguous_mask.astype(bool)

                pcd_colored = colorize_point_cloud(
                    pcd_reg, deviations, tolerance, colormap,
                    ambiguous_mask=ambiguous_mask,
                )

                # Пересчитываем статистику с текущим допуском
                new_stats = compute_statistics(
                    deviations, tolerance, ambiguous_mask=ambiguous_mask
                )
                new_stats["registration_rmse"] = saved_stats.get("registration_rmse", 0)
                new_stats["dimensions"] = compute_dimensions(self.manager.mesh, pcd_reg)
                for _k in ("registration_suspect", "fine_pass_shift_mm", "fine_pass_rot_deg",
                           "rmse_coarse", "rmse_bestfit", "absorbed_deviation_mm", "alignment_mode",
                           "within_tolerance_coarse", "within_tolerance_bestfit_down",
                           "absorbed_within_tol_pct", "worst_points"):
                    if _k in saved_stats:
                        new_stats[_k] = saved_stats[_k]

                self.manager.deviations     = deviations
                self.manager.ambiguous_mask = ambiguous_mask
                self.manager.transformation = npz.get("transformation")
                self.manager.pcd_colored    = pcd_colored
                self.manager.pcd_registered = pcd_reg
                self.manager.stats          = new_stats
                self.manager.results        = {
                    "stats":          new_stats,
                    "pcd_colored":    pcd_colored,
                    "deviations":     deviations,
                    "ambiguous_mask": ambiguous_mask,
                }
                self.manager.analysis_date = project.get("analysis_date")

                self.results_panel.update_results(new_stats)
                self.viewer.load_results(
                    pcd_colored=pcd_colored,
                    mesh=self.manager.mesh,
                    deviations=deviations,
                    tolerance=tolerance,
                    colormap=colormap,
                )
                self._heavy_params_dirty = False
                self._log(
                    f"Результаты анализа восстановлены из проекта "
                    f"(дата: {project.get('analysis_date', '—')})"
                )

        self._update_button_states()
        self._update_status_info()

    # ── Слоты сигналов Worker Thread ──────────────────────────────

    def _on_progress(self, value: int):
        self.progress_bar.setValue(value)

    def _on_stage_changed(self, text: str):
        self._stage_label.setText(text)

    def _on_analysis_finished(self, results: dict):
        elapsed = time.time() - self._analysis_start
        mins    = int(elapsed // 60)
        secs    = int(elapsed % 60)
        elapsed_str = f"{mins} мин {secs} сек" if mins else f"{secs} сек"

        self.manager.save_results(results)
        self._set_analysis_running(False)
        self.results_panel.update_results(results["stats"])

        # Показать результаты во встроенном 3D-просмотрщике
        colormap = self.config.get("ui", {}).get("colormap", "RdYlGn_r")
        self.viewer.load_results(
            pcd_colored=results["pcd_colored"],
            mesh=self.manager.mesh,
            deviations=results["deviations"],
            tolerance=self.config["analysis"]["tolerance_mm"],
            colormap=colormap,
        )

        self._heavy_params_dirty = False   # сброс: тяжёлые параметры применены

        within_pct = results["stats"]["within_tolerance"] * 100
        self._log(f"Анализ завершён! Точек в допуске: {within_pct:.1f}%")
        self._update_status_info(f"Анализ завершён за {elapsed_str}")
        self._update_button_states()

    def _on_analysis_error(self, error_msg: str):
        self._set_analysis_running(False)
        # Отмена пользователем приходит тем же сигналом, что и ошибки —
        # отличаем по тексту, чтобы не показывать Critical-диалог.
        is_cancelled = "отмен" in error_msg.lower()
        if is_cancelled:
            self._log("Анализ отменён пользователем")
            self._update_status_info("Анализ отменён")
        else:
            self._log(f"[ОШИБКА] {error_msg}")
            self._show_error("Ошибка анализа", error_msg)
            self._update_status_info("Ошибка анализа")
        self._update_button_states()

    # ── Вспомогательные методы ────────────────────────────────────

    def _on_recalculate_tolerance(self):
        """Быстрый пересчёт: только статистика + перекраска — без повторной регистрации."""
        if self.manager.deviations is None or self.manager.pcd_colored is None:
            return

        tolerance = self.config["analysis"]["tolerance_mm"]
        colormap  = self.config.get("ui", {}).get("colormap", "RdYlGn_r")

        amb_mask = self.manager.ambiguous_mask   # сохранённая маска — не пересчитываем

        new_stats = compute_statistics(
            self.manager.deviations, tolerance, ambiguous_mask=amb_mask
        )
        # Поля из регистрации вычисляются один раз — сохраняем при пересчёте допуска
        _reg_keys = (
            "registration_rmse", "registration_suspect", "dimensions",
            "fine_pass_shift_mm", "fine_pass_rot_deg",
            "rmse_coarse", "rmse_bestfit", "absorbed_deviation_mm", "alignment_mode",
            "within_tolerance_coarse", "within_tolerance_bestfit_down",
            "absorbed_within_tol_pct", "worst_points",
        )
        for _k in _reg_keys:
            if _k in self.manager.stats:
                new_stats[_k] = self.manager.stats[_k]

        new_pcd = colorize_point_cloud(
            self.manager.pcd_colored, self.manager.deviations, tolerance, colormap,
            ambiguous_mask=amb_mask,
        )

        self.manager.pcd_colored = new_pcd
        self.manager.stats       = new_stats
        if self.manager.results is not None:
            self.manager.results["stats"]       = new_stats
            self.manager.results["pcd_colored"] = new_pcd

        self.results_panel.update_results(new_stats)
        self.viewer.load_results(
            pcd_colored=new_pcd,
            mesh=self.manager.mesh,
            deviations=self.manager.deviations,
            tolerance=tolerance,
            colormap=colormap,
        )
        self._log(f"Статистика пересчитана с допуском {tolerance:.3f} мм")

    def _on_param_changed(self, key_path: list, value):
        self.manager.update_config(key_path, value)
        # Только допуск, порог соответствия и цветовая шкала — «лёгкие» параметры
        _light = (
            ["analysis", "tolerance_mm"],
            ["analysis", "conformance_threshold"],
            ["ui", "colormap"],
        )
        if key_path not in _light:
            self._heavy_params_dirty = True

        # При изменении порога соответствия — обновляем вердикт без пересчёта
        if key_path == ["analysis", "conformance_threshold"]:
            self.results_panel.set_threshold(value)
            if self.manager.stats is not None:
                self.results_panel.update_results(self.manager.stats)

        # При смене единиц для уже загруженного файла — перезагружаем его
        # с новым коэффициентом. Сравниваем со значением, уже применённым к
        # геометрии (unit_cad/unit_scan), чтобы избежать лишней перезагрузки
        # при apply_config после открытия проекта.
        if key_path == ["units", "cad"] and self.manager.cad_path:
            if value != self.manager.unit_cad:
                self._log(f"Единица CAD изменена на «{value}», перезагрузка...")
                self._load_cad_from_path(self.manager.cad_path)
        elif key_path == ["units", "scan"] and self.manager.scan_path:
            if value != self.manager.unit_scan:
                self._log(f"Единица скана изменена на «{value}», перезагрузка...")
                self._load_scan_from_path(self.manager.scan_path)

    def _set_analysis_running(self, running: bool):
        self.btn_load_cad.setEnabled(not running)
        self.btn_load_scan.setEnabled(not running)
        self.btn_run.setEnabled(not running)
        self.btn_run.setVisible(not running)
        self.btn_cancel.setVisible(running)
        self.progress_bar.setVisible(running)
        self._stage_label.setVisible(running)

        # btn_report принудительно серая во время анализа;
        # после — _update_button_states() сама решает, включать ли её
        if running:
            self.btn_report.setEnabled(False)

        # Блокируем все кнопки 3D-виджета во время анализа
        self.viewer.set_interactive(not running)
        self.log_panel.set_analysis_running(running)

        if running:
            # setOverrideCursor гарантированно работает поверх VTK-виджета,
            # в отличие от self.setCursor(), которое QtInteractor игнорирует.
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.btn_cancel.setEnabled(True)
            self.log_panel.set_cancel_enabled(True)
            self.progress_bar.setFormat("%p%")
        else:
            # Снимаем override-курсор; на случай вложенных вызовов — сбрасываем весь стек
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("%p%")
            self._stage_label.setText("")

    def _update_button_states(self):
        ready       = self.manager.is_ready_for_analysis()
        has_results = self.manager.stats is not None

        self.btn_run.setEnabled(ready)
        self.btn_run.setToolTip(
            "" if ready else "Загрузите модель и скан для начала анализа"
        )

        self.btn_report.setEnabled(has_results)
        self.btn_report.setToolTip(
            "" if has_results else "Сначала выполните анализ"
        )

        self.control_panel.set_has_results(has_results)

    def _update_status_info(self, status: str = None):
        """Обновляет строку состояния: Модель | Скан | Статус."""
        if status is not None:
            self._current_status = status

        cad_name  = (os.path.basename(self.manager.cad_path)
                     if self.manager.cad_path else "не загружена")
        scan_name = (os.path.basename(self.manager.scan_path)
                     if self.manager.scan_path else "не загружен")

        self.status_info_label.setText(
            f"Модель: {cad_name}  |  Скан: {scan_name}  |  "
            f"Статус: {self._current_status}"
        )

    def _make_loading_dialog(self, message: str, path: str) -> QProgressDialog | None:
        """
        Создаёт и показывает индeterminate QProgressDialog для файлов крупнее 50 МБ.
        Возвращает диалог (нужно закрыть вызывающим кодом) или None для малых файлов.
        Вызов QApplication.processEvents() гарантирует, что диалог отрисуется
        до начала блокирующей I/O-операции.
        """
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            return None

        if size_mb < 50:
            return None

        dlg = QProgressDialog(message, None, 0, 0, self)
        dlg.setWindowTitle("Загрузка файла")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)   # показывать немедленно
        dlg.setValue(0)
        QApplication.processEvents()   # отрисовать диалог до блокирующего вызова
        return dlg

    def _log(self, message: str):
        self.log_panel.append(message)

    def _show_error(self, title: str, message: str):
        QMessageBox.critical(self, title, message)
        logger.error(f"{title}: {message}")

    def _show_help(self):
        dlg = HelpDialog(self)
        dlg.exec()

    def _show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()

    # ── Закрытие окна ─────────────────────────────────────────────

    def closeEvent(self, event):
        """
        При закрытии:
        1. Если работает анализ — останавливаем поток.
        2. Если есть результаты — спрашиваем про сохранение.
        3. Сохраняем конфиг.
        """
        # Останавливаем worker если запущен
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)

        # Спрашиваем про сохранение если есть результаты анализа
        if self.manager.results is not None or self.manager.stats is not None:
            reply = QMessageBox.question(
                self,
                "Выход из программы",
                "Сохранить проект перед выходом?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )

            if reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

            if reply == QMessageBox.StandardButton.Save:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Сохранить проект", "project.json", "JSON файлы (*.json)"
                )
                if not path:
                    # Пользователь отменил диалог — не закрываем
                    event.ignore()
                    return
                try:
                    self.manager.save_project(path)
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка сохранения", str(e))
                    event.ignore()
                    return

        # Сохраняем конфиг
        try:
            self.manager.save_config("config.json")
        except Exception:
            pass

        # Закрываем 3D-просмотрщик после всех диалогов
        try:
            self.viewer.plotter.close()
        except Exception:
            pass

        event.accept()
