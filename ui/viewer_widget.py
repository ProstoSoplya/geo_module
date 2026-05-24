"""
viewer_widget.py — Встроенный 3D-просмотрщик на базе PyVistaQt / VTK.

Управление мышью:
  - ЛКМ              = вращение вокруг фокальной точки (стандарт VTK)
  - Колесо           = зум к фокальной точке (стандарт VTK)
  - ПКМ              = перемещение (pan) — наша реализация через прямую
                       манипуляцию камерой
  - Колесо (зажать)  = перемещение (pan, стандарт VTK; работает не на всех
                       мышах — оставлен как дополнительный жест)
  - Двойной клик ЛКМ = перецентрировать камеру на точке под курсором

Двойной клик — основной способ навигации к дефекту: пользователь видит
цветное пятно, кликает по нему дважды — точка становится новым центром
вращения и зума. Затем колесом/ПКМ можно приближаться или сдвигать вид.

Дополнительно:
  - Режимы вида: Наложение / Только скан / Только модель
  - Сброс вида + скриншот для PDF-отчёта
"""

import logging
import os
import tempfile

import numpy as np
import open3d as o3d
import vtk

os.environ.setdefault("QT_API", "pyqt6")

import pyvista as pv
from pyvistaqt import QtInteractor

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer, QObject, QEvent

logger = logging.getLogger(__name__)

# ── Qt-фильтр: двойной клик ЛКМ → перецентрировать камеру ────────────────────

class _ViewerInteractionFilter(QObject):
    """Дополнения к стандартной навигации vtkInteractorStyleTrackballCamera:

    1) Двойной клик ЛКМ → камера перецентрируется на 3D-точке под курсором
       (через vtkPropPicker по z-буферу: работает и по мешу, и по облаку).
       Камера двигается параллельным переносом (фокус и позиция на одну
       дельту), направление взгляда и расстояние сохраняются — после клика
       колесо и ПКМ зумят прямо на выбранную точку.

    2) ПКМ (drag) → перемещение (pan). Стандартный VTK pan на средней
       кнопке (зажатое колесо) работает не на всех мышах. Pan реализован
       прямой манипуляцией камерой (без пересылки Qt-событий, чтобы
       исключить рекурсию через eventFilter — именно это ломало все
       предыдущие попытки переназначить ПКМ через sendEvent).
       Стандартный ПКМ-zoom (dolly) при этом теряется: зум остаётся
       на колесе.
    """

    def __init__(self, plotter, parent=None):
        super().__init__(parent)
        self._plotter = plotter
        self._panning = False
        self._last_x = 0
        self._last_y = 0

    def eventFilter(self, obj, event):
        t = event.type()

        # Двойной клик ЛКМ → перецентрировать
        if (t == QEvent.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton):
            return self._recenter_at(event.position())

        # ПКМ → старт pan (VTK не получит событие → не запустит dolly)
        if (t == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton):
            self._panning = True
            self._last_x = event.position().x()
            self._last_y = event.position().y()
            return True

        # Движение во время pan → сдвинуть камеру
        if t == QEvent.Type.MouseMove and self._panning:
            x = event.position().x()
            y = event.position().y()
            self._pan_camera(x - self._last_x, y - self._last_y)
            self._last_x = x
            self._last_y = y
            return True

        # Отпустили ПКМ → конец pan
        if (t == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.RightButton
                and self._panning):
            self._panning = False
            return True

        return False

    def _pan_camera(self, dx_qt: float, dy_qt: float):
        """Параллельный перенос камеры так, что мир под курсором следует
        за курсором (стандартный VTK drag-to-pan).

        Алгоритм:
          1. Берём текущий focal F, проецируем в display.
          2. Вычисляем display-координату точки, которая после переноса
             должна оказаться на месте старого F: смещение в display
             равно (-dx_qt, +dy_qt) — Qt y направлен вниз, VTK display y
             вверх; знак минус, потому что мир «следует» за курсором.
          3. Unproject этой display-точки на focal-плоскость → новая
             позиция focal в мире.
          4. Сдвигаем и focal, и position на одну дельту.
        """
        plotter = self._plotter
        renderer = getattr(plotter, "renderer", None)
        camera   = getattr(plotter, "camera",   None)
        if renderer is None or camera is None:
            return

        fp = np.array(camera.GetFocalPoint(), dtype=np.float64)
        renderer.SetWorldPoint(fp[0], fp[1], fp[2], 1.0)
        renderer.WorldToDisplay()
        fpd = renderer.GetDisplayPoint()

        new_dx = fpd[0] - dx_qt
        new_dy = fpd[1] + dy_qt
        renderer.SetDisplayPoint(new_dx, new_dy, fpd[2])
        renderer.DisplayToWorld()
        w = renderer.GetWorldPoint()
        if abs(w[3]) < 1e-12:
            return
        new_fp = np.array([w[0]/w[3], w[1]/w[3], w[2]/w[3]],
                          dtype=np.float64)

        delta = new_fp - fp
        pos = np.array(camera.GetPosition(), dtype=np.float64)
        camera.SetFocalPoint(*new_fp)
        camera.SetPosition(*(pos + delta))

        renderer.ResetCameraClippingRange()
        plotter.render()

    def _recenter_at(self, qpos) -> bool:
        plotter = self._plotter
        renderer = getattr(plotter, "renderer", None)
        camera   = getattr(plotter, "camera",   None)
        if renderer is None or camera is None:
            return False

        widget_h = plotter.height()
        if widget_h <= 0:
            return False

        x = float(int(qpos.x()))
        y_vtk = float(widget_h - int(qpos.y()) - 1)

        # Сначала пробуем подобрать реальную точку поверхности/облака
        # через vtkPropPicker (использует z-буфер).
        picker = vtk.vtkPropPicker()
        if picker.Pick(x, y_vtk, 0.0, renderer):
            wp = picker.GetPickPosition()
            world = np.array(wp, dtype=np.float64)
        else:
            # Клик в пустоту — проецируем на текущую фокальную плоскость.
            focal = np.array(camera.GetFocalPoint(), dtype=np.float64)
            renderer.SetWorldPoint(focal[0], focal[1], focal[2], 1.0)
            renderer.WorldToDisplay()
            depth = renderer.GetDisplayPoint()[2]
            renderer.SetDisplayPoint(x, y_vtk, float(depth))
            renderer.DisplayToWorld()
            w = renderer.GetWorldPoint()
            if abs(w[3]) < 1e-12:
                return False
            world = np.array([w[0]/w[3], w[1]/w[3], w[2]/w[3]],
                             dtype=np.float64)

        old_focal = np.array(camera.GetFocalPoint(), dtype=np.float64)
        old_pos   = np.array(camera.GetPosition(),   dtype=np.float64)
        delta = world - old_focal

        camera.SetFocalPoint(*world)
        camera.SetPosition(*(old_pos + delta))

        renderer.ResetCameraClippingRange()
        plotter.render()
        return True


# ── Конвертация Open3D → PyVista ──────────────────────────────────────────────

# Максимум точек для отображения. Если облако больше — прореживаем шагом.
# Статистика и PDF всегда считаются на полных данных.
_MAX_DISPLAY_PTS = 600_000


def _pcd_to_pv(pcd: o3d.geometry.PointCloud,
               deviations: np.ndarray | None = None) -> pv.PolyData:
    points = np.asarray(pcd.points, dtype=np.float64)
    n = len(points)
    if n > _MAX_DISPLAY_PTS:
        step = max(1, n // _MAX_DISPLAY_PTS)
        idx = np.arange(0, n, step)
        points = points[idx]
        if deviations is not None:
            deviations = deviations[idx]
    poly = pv.PolyData(points)
    if deviations is not None:
        poly["deviation"] = deviations.astype(np.float32)
    return poly


def _mesh_to_pv(mesh: o3d.geometry.TriangleMesh) -> pv.PolyData:
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.triangles, dtype=np.int64)
    if len(faces) == 0:
        return pv.PolyData(verts)
    prefix = np.full((len(faces), 1), 3, dtype=np.int64)
    faces_pv = np.hstack([prefix, faces]).ravel()
    return pv.PolyData(verts, faces_pv)


# ── ViewerWidget ──────────────────────────────────────────────────────────────

class ViewerWidget(QWidget):
    """Встроенный 3D-просмотрщик PyVista/VTK с управляющей панелью."""

    _BG = (0.10, 0.10, 0.12)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)

        self._config          = config
        self._pv_pcd          = None
        self._pv_mesh         = None
        self._deviations      = None
        self._tolerance       = 0.5
        self._colormap        = config.get("ui", {}).get("colormap", "RdYlGn_r")
        self._mode            = "model"   # по умолчанию — только модель
        self._has_data        = False
        self._has_results     = False     # True только после завершения анализа
        self._render_pending  = False
        self._screenshot_path: str | None = None
        self._toolbar_buttons: list[QPushButton] = []

        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_toolbar())

        self._placeholder = QLabel(
            "3D-вид\n\n"
            "Загрузите CAD-модель и облако точек,\n"
            "затем запустите анализ.\n\n"
            "Поддерживается Drag && Drop файлов."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            "background: #0f0f14; color: #909090; "
            "font-size: 13px; border-radius: 6px;"
        )
        layout.addWidget(self._placeholder, 1)

        self.plotter = QtInteractor(self)
        self.plotter.set_background(self._BG)
        # Явно включаем стандартный VTK trackball-camera стиль:
        #   ЛКМ = rotate, СКМ (зажать колесо) = pan, ПКМ = dolly, колесо = zoom.
        # Без этого вызова QtInteractor может оказаться без интеракторного
        # стиля вообще — тогда не работают ни pan, ни dolly.
        self.plotter.enable_trackball_style()
        # ВАЖНО: убираем VTK-обработчики ПКМ у активного стиля. Без этого первое
        # нажатие ПКМ, попавшее в VTK до установки Qt-фильтра, запускает Dolly
        # и резко смещает камеру вдоль вектора взгляда — пользователь видит
        # «сброс/прыжок». Удаление обработчиков на самом VTK-стиле гарантирует,
        # что ПКМ-Dolly не сработает ни в одном сценарии (Qt-фильтр выше — это
        # реализация Pan, она кладётся параллельно).
        try:
            iren_style = self.plotter.iren.interactor.GetInteractorStyle()
            for evt_name in ("RightButtonPressEvent", "RightButtonReleaseEvent"):
                iren_style.RemoveObservers(evt_name)
        except Exception as exc:
            logger.debug("Не удалось снять VTK-обработчики ПКМ: %s", exc)
        self.plotter.setVisible(False)
        layout.addWidget(self.plotter, 1)

        # Подсказка по управлению мышью — мелкая полоса под 3D-видом.
        self._hint = QLabel(
            "ЛКМ: вращение   |   ПКМ: перемещение   |   "
            "Колесо: зум   |   Двойной клик: центрировать"
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            "background: #14141a; color: #707080; "
            "font-size: 10px; padding: 3px 8px; "
            "border-top: 1px solid #2a2a3a;"
        )
        layout.addWidget(self._hint)

        # Двойной клик ЛКМ → перецентрировать; ПКМ → pan (наш Qt-фильтр).
        # Ставим фильтр СИНХРОННО, а не через QTimer.singleShot(0, ...).
        # Иначе образуется окно гонки между показом виджета и установкой
        # фильтра: первое попадание ПКМ может уйти в VTK раньше фильтра и
        # запустить Dolly у trackball-camera — это и есть «прыжок камеры
        # на первом ПКМ-перетаскивании». На последующих нажатиях фильтр
        # уже стоит, поэтому пан работает нормально.
        self._install_mouse_nav()

    def _install_mouse_nav(self):
        """Ставит Qt event filter на QtInteractor (он же QVTKRenderWindowInteractor)."""
        # self.plotter — это сам QVTKRenderWindowInteractor (QWidget).
        # ВАЖНО: self.plotter.iren.interactor — это VTK-объект, а не QObject:
        # installEventFilter на нём упадёт. Ставим строго на Qt-виджет.
        self._interaction_filter = _ViewerInteractionFilter(self.plotter, self)
        self.plotter.installEventFilter(self._interaction_filter)
        logger.debug(
            "ViewerInteractionFilter установлен на %s",
            type(self.plotter).__name__,
        )

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(
            "background: #1a1a24; "
            "border-bottom: 1px solid #2a2a3a;"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(4)

        lbl_style = "color: #c8c8c8; font-size: 11px; background: transparent;"
        mode_style = (
            "QPushButton {"
            "  background: #252535; color: #cccccc;"
            "  border: 1px solid #444455;"
            "  padding: 2px 8px; border-radius: 3px; font-size: 11px;"
            "}"
            "QPushButton:checked {"
            "  background: #ad1457; color: white; border-color: #e91e63;"
            "}"
            "QPushButton:hover:!checked { background: #333344; color: #ffffff; }"
            "QPushButton:disabled { color: #484848; border-color: #333; background: #1a1a24; }"
        )
        cam_style = (
            "QPushButton {"
            "  background: #222232; color: #aaaaaa;"
            "  border: 1px solid #3a3a4a;"
            "  padding: 2px 8px; border-radius: 3px; font-size: 11px;"
            "}"
            "QPushButton:hover { background: #2e2e3e; }"
            "QPushButton:disabled { color: #444; border-color: #333; background: #1a1a24; }"
        )

        # Режимы вида
        row.addWidget(self._mk_label("Вид:", lbl_style))
        self._btn_overlay = self._mk_toggle("Наложение",     mode_style, False)
        self._btn_scan    = self._mk_toggle("Только скан",   mode_style, False)
        self._btn_model   = self._mk_toggle("Только модель", mode_style, True)

        # Overlay и Scan недоступны до завершения анализа
        self._btn_overlay.setEnabled(False)
        self._btn_scan.setEnabled(False)

        self._btn_overlay.clicked.connect(lambda: self._set_mode("overlay"))
        self._btn_scan.clicked.connect(   lambda: self._set_mode("scan"))
        self._btn_model.clicked.connect(  lambda: self._set_mode("model"))
        for b in (self._btn_overlay, self._btn_scan, self._btn_model):
            row.addWidget(b)

        row.addSpacing(10)

        # Только кнопка сброса камеры
        row.addWidget(self._mk_label("Камера:", lbl_style))
        btn_reset = QPushButton("↺ Сброс")
        btn_reset.setStyleSheet(cam_style)
        btn_reset.setToolTip("Сбросить камеру на исходное положение")
        btn_reset.clicked.connect(self._view_reset)
        row.addWidget(btn_reset)

        row.addStretch()

        btn_shot = QPushButton("Скриншот")
        btn_shot.setStyleSheet(cam_style)
        btn_shot.setToolTip("Снять скриншот 3D-вида для включения в PDF-отчёт")
        btn_shot.clicked.connect(self._take_screenshot)
        row.addWidget(btn_shot)

        self._toolbar_buttons = [
            self._btn_overlay, self._btn_scan, self._btn_model,
            btn_reset, btn_shot,
        ]

        return bar

    @staticmethod
    def _mk_label(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    @staticmethod
    def _mk_toggle(text: str, style: str, checked: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setStyleSheet(style)
        return btn

    # ── Загрузка данных ───────────────────────────────────────────────────────

    def load_mesh_preview(self, mesh: o3d.geometry.TriangleMesh):
        """Показать CAD-модель до выполнения анализа (с рёбрами, непрозрачная)."""
        self._pv_mesh     = _mesh_to_pv(mesh)
        self._pv_pcd      = None
        self._deviations  = None
        self._has_data    = True
        self._has_results = False
        self._mode        = "model"
        self._btn_model.setChecked(True)
        self._btn_overlay.setChecked(False)
        self._btn_scan.setChecked(False)
        self._update_view_buttons()
        self._schedule_render()

    def load_results(
        self,
        pcd_colored: o3d.geometry.PointCloud,
        mesh: o3d.geometry.TriangleMesh,
        deviations: np.ndarray,
        tolerance: float,
        colormap: str | None = None,
    ):
        """Показать результаты анализа: цветное облако + сетка + шкала."""
        self._pv_pcd     = _pcd_to_pv(pcd_colored, deviations)
        self._pv_mesh    = _mesh_to_pv(mesh)
        self._deviations = deviations
        self._tolerance  = tolerance
        if colormap:
            self._colormap = colormap
        self._has_data    = True
        self._has_results = True
        # При первой загрузке результатов переключаемся на наложение
        if self._mode == "model":
            self._mode = "overlay"
            self._btn_overlay.setChecked(True)
            self._btn_model.setChecked(False)
        self._update_view_buttons()
        self._schedule_render()

    def _schedule_render(self):
        """Откладывает VTK-рендер на следующую итерацию event loop."""
        if not self._render_pending:
            self._render_pending = True
            QTimer.singleShot(0, self._render)

    def clear(self):
        """Сбросить вид и показать заглушку."""
        self._pv_pcd          = None
        self._pv_mesh         = None
        self._deviations      = None
        self._has_data        = False
        self._has_results     = False
        self._render_pending  = False
        self._mode            = "model"
        self._btn_model.setChecked(True)
        self._btn_overlay.setChecked(False)
        self._btn_scan.setChecked(False)
        self._update_view_buttons()
        self._placeholder.setText(
            "3D-вид\n\n"
            "Загрузите CAD-модель и облако точек,\n"
            "затем запустите анализ.\n\n"
            "Поддерживается Drag && Drop файлов."
        )
        self._placeholder.setVisible(True)
        self.plotter.setVisible(False)
        self.plotter.clear()
        self.plotter.render()

    def set_interactive(self, enabled: bool):
        """Включить/выключить управление 3D-видом (на время анализа)."""
        for btn in self._toolbar_buttons:
            btn.setEnabled(enabled)
        self.plotter.setEnabled(enabled)
        if enabled:
            self._update_view_buttons()

    def _update_view_buttons(self):
        """Кнопки Наложение и Скан активны только после завершения анализа."""
        self._btn_overlay.setEnabled(self._has_results)
        self._btn_scan.setEnabled(self._has_results)

    # ── Рендеринг ─────────────────────────────────────────────────────────────

    def _render(self):
        self._render_pending = False
        self.plotter.clear()

        if not self._has_data:
            self._placeholder.setVisible(True)
            self.plotter.setVisible(False)
            return

        self._placeholder.setVisible(False)
        self.plotter.setVisible(True)

        show_scan = self._mode in ("overlay", "scan")  and self._pv_pcd  is not None
        show_mesh = self._mode in ("overlay", "model") and self._pv_mesh is not None

        if show_mesh:
            is_preview = not self._has_results
            if is_preview:
                # До анализа: светло-серый, непрозрачный, с рёбрами
                self.plotter.add_mesh(
                    self._pv_mesh,
                    color="#c8c8be",
                    opacity=1.0,
                    smooth_shading=True,
                    show_edges=True,
                    edge_color="#777766",
                    name="mesh",
                )
            else:
                opacity = 0.22 if self._mode == "overlay" else 0.92
                self.plotter.add_mesh(
                    self._pv_mesh,
                    color="#c0c0b8",
                    opacity=opacity,
                    smooth_shading=True,
                    show_edges=True,
                    edge_color="#444444",
                    name="mesh",
                )

        if show_scan:
            if self._deviations is not None:
                tol = self._tolerance
                self.plotter.add_mesh(
                    self._pv_pcd,
                    scalars="deviation",
                    cmap=self._colormap,
                    clim=[-tol, tol],
                    point_size=3,
                    render_points_as_spheres=False,
                    show_scalar_bar=True,
                    scalar_bar_args={
                        "title": "",
                        "n_labels": 5,
                        "fmt": "%+.2f",
                        "color": "white",
                        "label_font_size": 11,
                        "shadow": False,
                        "position_x": 0.02,
                        "position_y": 0.10,
                        "width": 0.06,
                        "height": 0.80,
                        "vertical": True,
                    },
                    name="pcd",
                )
            else:
                self.plotter.add_mesh(
                    self._pv_pcd,
                    color="white",
                    point_size=3,
                    name="pcd",
                )

        self.plotter.reset_camera()
        self.plotter.render()

    # ── Режимы и камера ───────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._mode = mode
        self._btn_overlay.setChecked(mode == "overlay")
        self._btn_scan.setChecked(   mode == "scan")
        self._btn_model.setChecked(  mode == "model")
        self._render()

    def _view_reset(self):
        self.plotter.reset_camera()
        self.plotter.render()

    # ── Скриншоты ─────────────────────────────────────────────────────────────

    def _take_screenshot(self):
        path = os.path.join(tempfile.gettempdir(), "geo_viewer_screenshot.png")
        self.plotter.screenshot(path, transparent_background=False)
        self._screenshot_path = path
        return path

    def make_screenshot(self) -> str | None:
        """Снять скриншот текущего вида (для PDF-отчёта)."""
        if self.plotter.isVisible() and self._has_data:
            return self._take_screenshot()
        return None

    def make_multiview_screenshots(self) -> list[str]:
        """
        Рендерит 4 вида (спереди, сзади, сверху, изометрия) через offscreen-рендерер.
        Возвращает список путей к PNG-файлам.
        """
        if not self._has_data or self._pv_mesh is None:
            return []

        bounds = self._pv_mesh.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
        cx = (bounds[0] + bounds[1]) / 2
        cy = (bounds[2] + bounds[3]) / 2
        cz = (bounds[4] + bounds[5]) / 2
        center = (cx, cy, cz)
        diag = (
            (bounds[1] - bounds[0]) ** 2 +
            (bounds[3] - bounds[2]) ** 2 +
            (bounds[5] - bounds[4]) ** 2
        ) ** 0.5
        d = diag * 1.8

        cam_configs = [
            ("front", (cx,          cy - d,       cz),           (0, 0, 1)),
            ("back",  (cx,          cy + d,       cz),           (0, 0, 1)),
            ("left",  (cx - d,      cy,           cz),           (0, 0, 1)),
            ("right", (cx + d,      cy,           cz),           (0, 0, 1)),
            ("top",   (cx,          cy,           cz + d),       (0, 1, 0)),
            ("iso",   (cx + d*0.7,  cy - d*0.7,  cz + d*0.55),  (0, 0, 1)),
        ]

        paths = []
        for name, cam_pos, cam_up in cam_configs:
            out = os.path.join(tempfile.gettempdir(), f"geo_view_{name}.png")
            try:
                pl = pv.Plotter(off_screen=True, window_size=(750, 560))
                pl.set_background(self._BG)

                if self._pv_pcd is not None and self._deviations is not None:
                    pl.add_mesh(
                        self._pv_mesh,
                        color="#b8b8b8", opacity=0.28,
                        smooth_shading=True, show_edges=False,
                    )
                    pl.add_mesh(
                        self._pv_pcd,
                        scalars="deviation",
                        cmap=self._colormap,
                        clim=[-self._tolerance, self._tolerance],
                        point_size=2,
                        show_scalar_bar=False,
                    )
                else:
                    pl.add_mesh(
                        self._pv_mesh,
                        color="#c8c8be", opacity=1.0,
                        smooth_shading=True, show_edges=True,
                        edge_color="#777766",
                    )

                pl.camera.position = cam_pos
                pl.camera.focal_point = center
                pl.camera.up = cam_up
                pl.reset_camera()
                pl.screenshot(out, transparent_background=False)
                pl.close()
                paths.append(out)
            except Exception as exc:
                logger.warning("Скриншот вида '%s' не удался: %s", name, exc)

        return paths

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        try:
            self.plotter.close()
        except Exception:
            pass
        super().closeEvent(event)
