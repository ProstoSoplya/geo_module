"""
worker.py — Фоновый поток для выполнения тяжёлых вычислений.

Зачем нужен отдельный поток:
    PyQt6 (как и любой GUI-фреймворк) — однопоточный.
    Если запустить ICP в главном потоке, окно зависнет до завершения.
    QThread запускает вычисления в фоне, пока главный поток обновляет UI.

Общение с UI через сигналы:
    progress_changed(int)   — обновление прогресс-бара (0–100)
    stage_changed(str)      — текст текущего этапа для строки состояния
    log_message(str)        — сообщение в лог-панель
    analysis_finished(dict) — результаты анализа
    analysis_error(str)     — сообщение об ошибке
"""

import copy
import logging
import threading
import traceback

import open3d as o3d
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal

from core.algorithms.preprocessing import preprocess_pipeline
from core.algorithms.registration import register_pipeline, RegistrationError
from core.algorithms.deviation import (
    compute_deviations,
    compute_statistics,
    colorize_point_cloud,
)
from core.algorithms.dimensions import compute_dimensions
from core.defaults import BASIC_DEFAULTS

logger = logging.getLogger(__name__)

# Текст этапа определяется по порогу прогресса.
# (порог, текст) — находим первый порог <= текущего прогресса.
_STAGE_THRESHOLDS = [
    (80, "Этап 4/4: Расчёт отклонений..."),
    (65, "Этап 3/4: Точное совмещение (ICP)..."),
    (35, "Этап 2/4: Грубое совмещение (RANSAC)..."),
]


class AnalysisWorker(QThread):
    """
    Фоновый поток, выполняющий полный пайплайн анализа:
        предобработка → регистрация → расчёт отклонений → статистика
    """

    progress_changed   = pyqtSignal(int)   # 0–100
    stage_changed      = pyqtSignal(str)   # текст текущего этапа
    log_message        = pyqtSignal(str)   # строка для лога
    analysis_finished  = pyqtSignal(dict)  # словарь с результатами
    analysis_error     = pyqtSignal(str)   # текст ошибки
    analysis_cancelled = pyqtSignal()      # отмена пользователем — без диалога

    def __init__(self, pcd: o3d.geometry.PointCloud,
                 mesh: o3d.geometry.TriangleMesh,
                 config: dict):
        super().__init__()
        self.pcd    = pcd
        self.mesh   = mesh
        self.config = config
        # threading.Event даёт гарантированную memory visibility между
        # потоками — bool полагался на implementation detail CPython GIL.
        self._cancelled  = threading.Event()
        self._stage_text = ""

    def cancel(self):
        """Запросить отмену анализа (проверяется между этапами)."""
        self._cancelled.set()

    def _emit_progress(self, value: int):
        """Обновляет прогресс-бар, автоматически переключает текст этапа."""
        if self._cancelled.is_set():
            raise InterruptedError("Анализ отменён пользователем")

        for threshold, text in _STAGE_THRESHOLDS:
            if value >= threshold:
                self._emit_stage(text)
                break

        self.progress_changed.emit(value)

    def _emit_stage(self, text: str):
        """Отправляет текст этапа только если он изменился."""
        if text != self._stage_text:
            self._stage_text = text
            self.stage_changed.emit(text)

    def _log(self, message: str):
        """Отправляет сообщение в лог-панель UI."""
        logger.info(message)
        self.log_message.emit(message)

    def run(self):
        """
        Основной метод потока. Вызывается автоматически при worker.start().
        """
        try:
            self._run_pipeline()
        except InterruptedError as e:
            self._log(f"[Отмена] {e}")
            self.analysis_cancelled.emit()
        except (RegistrationError, TimeoutError) as e:
            msg = str(e)
            logger.error(f"Ошибка регистрации: {msg}")
            self.log_message.emit(f"[ОШИБКА] {msg}")
            self.analysis_error.emit(msg)
        except Exception as e:
            error_msg = f"Ошибка анализа: {e}\n\n{traceback.format_exc()}"
            logger.error(error_msg)
            self.log_message.emit(f"[ОШИБКА] {e}")
            self.analysis_error.emit(str(e))

    def _run_pipeline(self):
        """Выполняет все этапы анализа последовательно."""
        self._stage_text = ""

        advanced = bool(self.config.get("ui", {}).get("advanced_mode", False))
        if not advanced:
            self.config = copy.deepcopy(self.config)
            self.config["preprocessing"] = copy.deepcopy(BASIC_DEFAULTS["preprocessing"])
            self.config["registration"] = copy.deepcopy(BASIC_DEFAULTS["registration"])
            self._log("Базовый режим: используются параметры по умолчанию")

        # ── Этап 1: Предобработка ─────────────────────────────────
        self._emit_stage("Этап 1/4: Предобработка данных...")
        self._log("① Предобработка облака точек...")
        pcd_clean, pcd_down, pcd_voxel_size = preprocess_pipeline(
            self.pcd,
            self.config,
            progress_callback=self._emit_progress
        )
        self._log(
            f"   Предобработка завершена. "
            f"Осталось точек: {len(pcd_clean.points):,} (полное), "
            f"{len(pcd_down.points):,} (прореженное)"
        )

        # ── Этап 2–3: Регистрация ─────────────────────────────────
        # Этапы 2/4 и 3/4 переключаются автоматически внутри _emit_progress
        # по порогам 35% (RANSAC) и 65% (ICP).
        self._log("② Регистрация (совмещение скана с CAD-моделью)...")
        self._emit_progress(35)

        # transform — итоговая 4×4 матрица из ИСХОДНОГО pcd в финальное положение
        # (включает центроидное предвыравнивание + ICP). Применение к свежему
        # pcd_full даст совмещение, эквивалентное pcd_registered.
        pcd_registered, transform, reg_rmse, reg_suspect, reg_diag = register_pipeline(
            pcd_clean,
            pcd_down,
            self.mesh,
            self.config,
            progress_callback=self._emit_progress,
            pcd_voxel_size=pcd_voxel_size,
        )
        self._log(f"   ICP завершён. RMSE совмещения: {reg_rmse:.6f} мм")

        shift  = reg_diag["fine_pass_shift_mm"]
        rot    = reg_diag["fine_pass_rot_deg"]
        absorb = reg_diag["absorbed_deviation_mm"]
        self._log(
            f"   Точная регистрация сместила деталь на {shift:.4f} мм / {rot:.4f}°, "
            f"разница C2M-RMSE: {absorb:+.4f} мм"
        )
        wtc          = reg_diag.get("within_tolerance_coarse", 0.0) * 100
        abs_tol_pp   = reg_diag.get("absorbed_within_tol_pct",  0.0) * 100
        wtbf         = wtc + abs_tol_pp
        self._log(
            f"   Точная регистрация повысила долю в допуске на {abs_tol_pp:+.1f} п.п. "
            f"(с {wtc:.1f}% до {wtbf:.1f}%) — мера маскировки"
        )

        if reg_suspect:
            self._log(
                "   [SUSPECT REGISTRATION] Лучший кандидат имеет большой C2M-RMSE. "
                "Регистрация может быть неверной — проверьте визуально."
            )
        elif reg_rmse > 1.0:
            self._log(
                "   [WARNING] Высокий ICP RMSE! Проверьте качество данных или "
                "увеличьте диапазон RANSAC."
            )

        # ── Этап 4: Расчёт отклонений ─────────────────────────────
        self._log("③ Вычисление отклонений (Cloud-to-Mesh)...")

        if not self.mesh.is_watertight():
            self._log(
                "   ⚠ Предупреждение: модель не является замкнутой (watertight). "
                "Знак отклонения восстановлен по нормали ближайшей грани."
            )

        deviations, ambiguous_mask = compute_deviations(
            pcd_registered,
            self.mesh,
            progress_callback=self._emit_progress
        )
        self._emit_progress(88)

        # ── Статистика + раскраска ────────────────────────────────
        self._emit_stage("Этап 4/4: Формирование результатов...")
        self._log("④ Вычисление статистики...")
        tolerance = self.config["analysis"]["tolerance_mm"]
        worst_n   = int(self.config.get("analysis", {}).get("worst_points_n", 10))
        stats = compute_statistics(
            deviations, tolerance,
            ambiguous_mask=ambiguous_mask,
            point_coords=np.asarray(pcd_registered.points),
            worst_n=worst_n,
        )
        stats["registration_rmse"]    = reg_rmse
        stats["registration_suspect"] = reg_suspect
        stats.update(reg_diag)
        dims = compute_dimensions(self.mesh, pcd_registered)
        stats["dimensions"] = dims
        self._log(
            f"   Габариты CAD: {dims['cad'][0]:.1f} x {dims['cad'][1]:.1f} x "
            f"{dims['cad'][2]:.1f} мм  (диаг. {dims['cad_diag']:.1f} мм)"
        )
        if dims["scan"] is not None:
            self._log(
                f"   Габариты скана: {dims['scan'][0]:.1f} x {dims['scan'][1]:.1f} x "
                f"{dims['scan'][2]:.1f} мм  (диаг. {dims['scan_diag']:.1f} мм)"
            )

        amb_count = stats["ambiguous_sign_count"]
        if amb_count > 0:
            amb_pct   = stats["ambiguous_sign_pct"] * 100
            zone_label = (
                "зоны тонких стенок / срединная поверхность"
                if self.mesh.is_watertight()
                else "точки у рёбер/кромок"
            )
            self._log(
                f"   Неоднозначный знак: {amb_count:,} точек "
                f"({amb_pct:.1f}%) — {zone_label}"
            )

        self._log("⑤ Раскраска облака точек по отклонениям...")
        colormap_name = "RdYlGn_r"
        pcd_colored = colorize_point_cloud(
            pcd_registered, deviations, tolerance,
            colormap_name=colormap_name, ambiguous_mask=ambiguous_mask,
        )

        self._emit_progress(97)

        within_pct = stats["within_tolerance"] * 100
        self._log(
            f"✓ Анализ завершён! "
            f"Среднее отклонение: {stats['mean_deviation']:+.4f} мм, "
            f"в допуске: {within_pct:.1f}%"
        )
        self._emit_progress(100)

        results = {
            "pcd_registered": pcd_registered,
            "pcd_colored":    pcd_colored,
            "deviations":     deviations,
            "ambiguous_mask": ambiguous_mask,
            "stats":          stats,
            "transform":      transform,
        }
        self.analysis_finished.emit(results)
