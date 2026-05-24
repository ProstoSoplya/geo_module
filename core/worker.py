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

import logging
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

    progress_changed  = pyqtSignal(int)   # 0–100
    stage_changed     = pyqtSignal(str)   # текст текущего этапа
    log_message       = pyqtSignal(str)   # строка для лога
    analysis_finished = pyqtSignal(dict)  # словарь с результатами
    analysis_error    = pyqtSignal(str)   # текст ошибки

    def __init__(self, pcd: o3d.geometry.PointCloud,
                 mesh: o3d.geometry.TriangleMesh,
                 config: dict):
        super().__init__()
        self.pcd    = pcd
        self.mesh   = mesh
        self.config = config
        self._cancelled  = False
        self._stage_text = ""

    def cancel(self):
        """Запросить отмену анализа (проверяется между этапами)."""
        self._cancelled = True

    def _emit_progress(self, value: int):
        """Обновляет прогресс-бар, автоматически переключает текст этапа."""
        if self._cancelled:
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
            self.analysis_error.emit(str(e))
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

        pcd_registered, transform, reg_rmse = register_pipeline(
            pcd_clean,
            pcd_down,
            self.mesh,
            self.config,
            progress_callback=self._emit_progress,
            pcd_voxel_size=pcd_voxel_size,
        )
        self._log(f"   ICP завершён. RMSE совмещения: {reg_rmse:.6f} мм")

        if reg_rmse > 1.0:
            self._log(
                "   ⚠ Высокий RMSE! Проверьте качество данных или "
                "увеличьте диапазон RANSAC."
            )

        # ── Этап 4: Расчёт отклонений ─────────────────────────────
        self._log("③ Вычисление отклонений (Cloud-to-Mesh)...")

        if not self.mesh.is_watertight():
            self._log(
                "   ⚠ Предупреждение: модель не является замкнутой (watertight). "
                "Знак отклонения восстановлен по нормали ближайшей грани."
            )

        deviations = compute_deviations(
            pcd_registered,
            self.mesh,
            progress_callback=self._emit_progress
        )
        self._emit_progress(88)

        # ── Статистика + раскраска ────────────────────────────────
        self._emit_stage("Этап 4/4: Формирование результатов...")
        self._log("④ Вычисление статистики...")
        tolerance = self.config["analysis"]["tolerance_mm"]
        stats = compute_statistics(deviations, tolerance)
        stats["registration_rmse"] = reg_rmse

        self._log("⑤ Раскраска облака точек по отклонениям...")
        colormap_name = self.config.get("ui", {}).get("colormap", "coolwarm")
        pcd_colored = colorize_point_cloud(
            pcd_registered, deviations, tolerance, colormap_name=colormap_name
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
            "stats":          stats,
            "transform":      transform,
        }
        self.analysis_finished.emit(results)
