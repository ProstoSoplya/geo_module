"""
project_manager.py — Менеджер проекта.

Хранит всё текущее состояние сессии:
    - загруженные файлы (CAD-модель, облако точек)
    - параметры анализа
    - результаты вычислений

Умеет сохранять и загружать проект в/из JSON.

UI работает ТОЛЬКО через ProjectManager — он не обращается к алгоритмам
напрямую. Это обеспечивает чёткое разделение слоёв.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import numpy as np
import open3d as o3d

from core.algorithms.deviation import compute_statistics

logger = logging.getLogger(__name__)

# Коэффициенты перевода единиц файла в миллиметры.
# "as_is" означает «не масштабировать» (файл уже в нужной шкале).
UNIT_TO_MM: dict[str, float] = {
    "mm":    1.0,
    "cm":   10.0,
    "m":  1000.0,
    "in":   25.4,
    "as_is": 1.0,
}


class ProjectManager:
    """
    Центральный класс — хранит состояние всего приложения.

    Атрибуты:
        mesh           — треугольная сетка CAD-модели (o3d.TriangleMesh)
        pcd            — исходное облако точек — скан (o3d.PointCloud)
        pcd_colored    — раскрашенное облако с результатами
        deviations     — массив отклонений (numpy array)
        stats          — словарь статистик
        cad_path       — путь к CAD-файлу
        scan_path      — путь к файлу скана
        config         — текущие параметры алгоритмов
        results        — все результаты последнего анализа
    """

    def __init__(self, config: dict):
        self.config = config

        # Геометрические данные
        self.mesh:           Optional[o3d.geometry.TriangleMesh]  = None
        self.pcd:            Optional[o3d.geometry.PointCloud]    = None
        self.pcd_colored:    Optional[o3d.geometry.PointCloud]    = None
        self.pcd_registered: Optional[o3d.geometry.PointCloud]    = None
        self.deviations:     Optional[np.ndarray]                 = None
        self.ambiguous_mask: Optional[np.ndarray]                 = None
        self.transformation: Optional[np.ndarray]                 = None
        self.stats:          Optional[dict]                       = None

        # Пути к файлам
        self.cad_path:  Optional[str] = None
        self.scan_path: Optional[str] = None

        # Единицы измерения, в которых был загружен каждый файл
        self.unit_cad:  str = "mm"
        self.unit_scan: str = "mm"

        # Метаданные
        self.results:      Optional[dict] = None
        self.project_path: Optional[str]  = None
        self.analysis_date: Optional[str] = None

        logger.info("ProjectManager инициализирован")

    # ── Загрузка файлов ────────────────────────────────────────────

    _SUPPORTED_CAD_EXT  = {".stl", ".obj"}
    _SUPPORTED_SCAN_EXT = {".ply", ".pcd", ".xyz", ".pts"}

    def load_cad(self, path: str, unit: str = None) -> o3d.geometry.TriangleMesh:
        """
        Загружает CAD-модель из STL/OBJ файла.

        unit — единица измерения файла ("mm", "cm", "m", "in", "as_is").
        Если не передана — берётся из config["units"]["cad"].
        Масштабирование к мм происходит сразу после чтения, до любых
        вычислений bounding box, от которых зависят адаптивные пороги.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext not in self._SUPPORTED_CAD_EXT:
            supported = ", ".join(sorted(self._SUPPORTED_CAD_EXT))
            raise ValueError(
                f"Неподдерживаемый формат «{ext}».\n"
                f"Поддерживаемые форматы CAD-моделей: {supported}"
            )

        if unit is None:
            unit = self.config.get("units", {}).get("cad", "mm")

        logger.info(f"Загрузка CAD-модели: {path}")
        mesh = o3d.io.read_triangle_mesh(path)

        if len(mesh.vertices) == 0:
            raise ValueError(f"Файл {os.path.basename(path)} пустой или повреждён")

        # Масштабирование к мм — ДО любых вычислений AABB/нормалей
        factor = UNIT_TO_MM.get(unit, 1.0)
        if factor != 1.0:
            mesh.scale(factor, center=(0.0, 0.0, 0.0))
            logger.info(f"CAD: масштаб x{factor} ({unit} -> мм)")
        else:
            logger.info(f"CAD: масштаб не применяется (единица: {unit})")

        # Вычисляем нормали — нужны для Point-to-Plane ICP
        mesh.compute_vertex_normals()
        mesh.compute_triangle_normals()

        # Красим меш в нейтральный серый для отображения
        mesh.paint_uniform_color([0.7, 0.7, 0.7])

        self.mesh     = mesh
        self.cad_path = path
        self.unit_cad = unit

        # Сбрасываем результаты при загрузке нового файла
        self._reset_results()

        logger.info(
            f"CAD загружена: {len(mesh.vertices):,} вершин, "
            f"{len(mesh.triangles):,} треугольников"
        )
        return mesh

    def load_scan(self, path: str, unit: str = None) -> o3d.geometry.PointCloud:
        """
        Загружает облако точек из PLY/PCD/XYZ файла.

        unit — единица измерения файла ("mm", "cm", "m", "in", "as_is").
        Если не передана — берётся из config["units"]["scan"].
        Масштабирование к мм происходит сразу после чтения.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext not in self._SUPPORTED_SCAN_EXT:
            supported = ", ".join(sorted(self._SUPPORTED_SCAN_EXT))
            raise ValueError(
                f"Неподдерживаемый формат «{ext}».\n"
                f"Поддерживаемые форматы облаков точек: {supported}"
            )

        if unit is None:
            unit = self.config.get("units", {}).get("scan", "mm")

        logger.info(f"Загрузка облака точек: {path}")
        pcd = o3d.io.read_point_cloud(path)

        if len(pcd.points) < 100:
            raise ValueError(
                f"Облако точек содержит только {len(pcd.points)} точек. "
                f"Минимум — 100. Проверьте файл."
            )

        # Масштабирование к мм — ДО любых вычислений AABB
        factor = UNIT_TO_MM.get(unit, 1.0)
        if factor != 1.0:
            pcd.scale(factor, center=(0.0, 0.0, 0.0))
            logger.info(f"Скан: масштаб x{factor} ({unit} -> мм)")
        else:
            logger.info(f"Скан: масштаб не применяется (единица: {unit})")

        self.pcd       = pcd
        self.scan_path = path
        self.unit_scan = unit

        # Сбрасываем результаты при загрузке нового файла
        self._reset_results()

        logger.info(f"Скан загружен: {len(pcd.points):,} точек")
        return pcd

    def is_ready_for_analysis(self) -> bool:
        """Возвращает True если оба файла загружены и можно запускать анализ."""
        return self.mesh is not None and self.pcd is not None

    # ── Сохранение результатов ─────────────────────────────────────

    def save_results(self, results: dict):
        """
        Сохраняет результаты анализа в менеджере.
        Вызывается из MainWindow после получения сигнала analysis_finished.
        """
        self.results        = results
        self.pcd_colored    = results.get("pcd_colored")
        self.deviations     = results.get("deviations")
        self.ambiguous_mask = results.get("ambiguous_mask")
        self.stats          = results.get("stats")
        self.pcd_registered = results.get("pcd_registered")   # зарегистрированное облако
        self.transformation = results.get("transform")        # матрица 4×4
        self.analysis_date  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Результаты анализа сохранены в ProjectManager")

    # ── Сохранение/загрузка проекта ───────────────────────────────

    def save_project(self, path: str):
        """
        Сохраняет проект в JSON + NPZ-сайдкар с массивами отклонений и трансформацией.
        NPZ-файл имеет то же имя, что JSON, но с расширением .npz.
        """
        has_results = self.deviations is not None

        project = {
            "version":       "1.2",
            "saved_at":      datetime.now().isoformat(),
            "cad_path":      self.cad_path,
            "scan_path":     self.scan_path,
            "unit_cad":      self.unit_cad,
            "unit_scan":     self.unit_scan,
            "config":        self.config,
            "analysis_date": self.analysis_date,
            "stats":         self.stats,
            "has_npz":       has_results,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, indent=2)

        # Сохраняем массивы отклонений и трансформацию в NPZ-сайдкар
        if has_results:
            npz_path = os.path.splitext(path)[0] + ".npz"
            arrays = {"deviations": self.deviations}
            if self.transformation is not None:
                arrays["transformation"] = self.transformation
            if self.pcd_registered is not None:
                arrays["pcd_points"] = np.asarray(self.pcd_registered.points)
            if self.ambiguous_mask is not None:
                arrays["ambiguous_mask"] = self.ambiguous_mask
            np.savez_compressed(npz_path, **arrays)
            logger.info(f"NPZ сайдкар сохранён: {npz_path}")

        self.project_path = path
        logger.info(f"Проект сохранён: {path}")

    def load_project(self, path: str) -> dict:
        """
        Загружает проект из JSON.

        Возвращает словарь с данными проекта.
        Ключ 'missing_files' — список путей, которые не найдены на диске.
        Ключ 'npz_data'      — словарь массивов из NPZ-сайдкара (или None).
        """
        with open(path, "r", encoding="utf-8") as f:
            project = json.load(f)

        # Восстанавливаем конфиг
        if "config" in project:
            self.config.update(project["config"])

        # Загружаем файлы (не бросаем исключение — сообщаем через missing_files)
        missing_files = []
        # Единицы берём из явных полей проекта; если их нет (старый формат) —
        # из обновлённого config["units"] (который уже обновлён строкой выше).
        saved_unit_cad  = project.get("unit_cad",  self.config.get("units", {}).get("cad",  "mm"))
        saved_unit_scan = project.get("unit_scan", self.config.get("units", {}).get("scan", "mm"))

        if project.get("cad_path"):
            if os.path.exists(project["cad_path"]):
                self.load_cad(project["cad_path"], unit=saved_unit_cad)
            else:
                self.cad_path = project["cad_path"]   # сохраняем путь для информации
                missing_files.append(project["cad_path"])

        if project.get("scan_path"):
            if os.path.exists(project["scan_path"]):
                self.load_scan(project["scan_path"], unit=saved_unit_scan)
            else:
                self.scan_path = project["scan_path"]
                missing_files.append(project["scan_path"])

        # Пробуем загрузить NPZ-сайдкар с массивами результатов
        npz_data = None
        if project.get("has_npz"):
            npz_path = os.path.splitext(path)[0] + ".npz"
            if os.path.exists(npz_path):
                try:
                    npz_data = dict(np.load(npz_path, allow_pickle=False))
                    logger.info(f"NPZ сайдкар загружен: {npz_path}")
                except Exception as e:
                    logger.warning(f"Не удалось загрузить NPZ: {e}")

        self.project_path     = path
        project["missing_files"] = missing_files
        project["npz_data"]      = npz_data

        # Восстанавливаем worst_points, если они отсутствуют в JSON-статистике
        saved_stats = project.get("stats")
        if saved_stats is not None and not saved_stats.get("worst_points"):
            if npz_data is not None and "deviations" in npz_data:
                if "pcd_points" in npz_data:
                    tolerance = self.config.get("analysis", {}).get("tolerance_mm", 1.0)
                    worst_n = int(self.config.get("analysis", {}).get("worst_points_n", 10))
                    ambiguous_mask = npz_data.get("ambiguous_mask")
                    if ambiguous_mask is not None:
                        ambiguous_mask = ambiguous_mask.astype(bool)
                    tmp_stats = compute_statistics(
                        npz_data["deviations"],
                        tolerance,
                        ambiguous_mask=ambiguous_mask,
                        point_coords=npz_data["pcd_points"],
                        worst_n=worst_n,
                    )
                    saved_stats["worst_points"] = tmp_stats.get("worst_points", [])
                    logger.info(
                        "worst_points восстановлены из данных проекта "
                        f"({len(saved_stats['worst_points'])} точек)"
                    )
                else:
                    saved_stats["worst_points"] = []
                    logger.warning(
                        "pcd_points отсутствует в NPZ — worst_points оставлены пустыми"
                    )

        logger.info(f"Проект загружен: {path}")
        return project

    # ── Вспомогательные ───────────────────────────────────────────

    def update_config(self, key_path: list, value):
        """
        Обновляет параметр конфига по пути ключей.
        Пример: update_config(["preprocessing", "voxel_size"], 0.2)
        """
        d = self.config
        for key in key_path[:-1]:
            d = d[key]
        d[key_path[-1]] = value
        logger.debug(f"Конфиг обновлён: {'.'.join(key_path)} = {value}")

    def save_config(self, path: str = "config.json"):
        """Сохраняет текущий конфиг в файл."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
        logger.info(f"Конфиг сохранён: {path}")

    def _reset_results(self):
        """Сбрасывает результаты анализа (вызывается при загрузке новых файлов)."""
        self.results        = None
        self.pcd_colored    = None
        self.pcd_registered = None
        self.deviations     = None
        self.ambiguous_mask = None
        self.transformation = None
        self.stats          = None
        self.analysis_date  = None
