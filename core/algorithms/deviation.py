"""
deviation.py — Вычисление отклонений облака точек от CAD-модели.

Метод: Cloud-to-Mesh distance (расстояние от облака до поверхности сетки).

Для каждой точки скана находится ближайшая точка на поверхности
треугольной сетки CAD-модели. Это расстояние и есть отклонение.

Знак отклонения (через нормаль ближайшего треугольника —
работает корректно на любом ориентируемом меше, даже не-watertight):
    + (положительное) — точка скана СНАРУЖИ CAD-модели (деталь больше)
    − (отрицательное) — точка скана ВНУТРИ CAD-модели (деталь меньше)
"""

import logging
import open3d as o3d
import numpy as np

logger = logging.getLogger(__name__)


def compute_deviations(pcd_registered: o3d.geometry.PointCloud,
                        mesh: o3d.geometry.TriangleMesh,
                        progress_callback=None) -> np.ndarray:
    """
    Вычисляет знаковые отклонения через RaycastingScene.

    Алгоритм:
        1. scene.compute_closest_points(query) — ближайшая точка на поверхности
           и нормаль треугольника, к которому она принадлежит.
        2. Вектор v = query - closest. Знак отклонения = sign(dot(v, normal_грани)).
        3. Модуль отклонения = |v|.

    Преимущество перед scene.compute_signed_distance: не требует watertight-меша.
    Знак корректно определяется для любой ориентируемой поверхности, т.к. нормали
    граней задают глобально согласованную «наружную» сторону.

    Знак:
        + точка снаружи CAD (деталь больше эталона)
        − точка внутри CAD (деталь меньше эталона)
    """
    logger.info("Cloud-to-Mesh: вычисление отклонений...")

    if not mesh.is_watertight():
        logger.warning(
            "Модель не является замкнутой (watertight). "
            "Знак отклонения восстанавливается по нормали ближайшей грани."
        )

    points = np.asarray(pcd_registered.points).astype(np.float32)

    mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(mesh)

    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(mesh_t)

    query_points = o3d.core.Tensor(points, dtype=o3d.core.Dtype.Float32)

    result = scene.compute_closest_points(query_points)
    closest_points = result["points"].numpy()
    primitive_normals = result["primitive_normals"].numpy()

    vectors = points - closest_points
    distances_unsigned = np.linalg.norm(vectors, axis=1)

    dots = np.einsum("ij,ij->i", vectors, primitive_normals)
    signs = np.where(dots >= 0, 1.0, -1.0)

    signed_distances = (distances_unsigned * signs).astype(np.float64)

    if progress_callback:
        progress_callback(88)

    logger.info(
        f"Отклонения вычислены. "
        f"Мин: {signed_distances.min():.4f}, "
        f"Макс: {signed_distances.max():.4f}, "
        f"Среднее: {signed_distances.mean():.4f}"
    )

    return signed_distances


def compute_statistics(deviations: np.ndarray, tolerance: float) -> dict:
    """Вычисляет статистику по отклонениям."""
    abs_dev = np.abs(deviations)
    within_tol = np.sum(abs_dev <= tolerance) / len(deviations)

    stats = {
        "mean_deviation":   float(np.mean(deviations)),
        "median_deviation": float(np.median(deviations)),
        "rmse":             float(np.sqrt(np.mean(deviations ** 2))),
        "max_deviation":    float(deviations.max()),
        "min_deviation":    float(deviations.min()),
        "max_abs_deviation": float(abs_dev.max()),
        "std_deviation":    float(np.std(deviations)),
        "percentile_95":    float(np.percentile(abs_dev, 95)),
        "percentile_99":    float(np.percentile(abs_dev, 99)),
        "within_tolerance": float(within_tol),
        "n_points":         int(len(deviations)),
        "tolerance":        float(tolerance),
    }

    logger.info(
        f"Статистика: среднее={stats['mean_deviation']:.4f}, "
        f"RMSE={stats['rmse']:.4f}, "
        f"макс|отклонение|={stats['max_abs_deviation']:.4f}, "
        f"в допуске={stats['within_tolerance']*100:.1f}%"
    )

    return stats


_LUT_CACHE: dict[str, np.ndarray] = {}


def _get_lut(name: str) -> np.ndarray:
    """LUT 256×3 (float32) для заданной cmap. Строится один раз на имя."""
    lut = _LUT_CACHE.get(name)
    if lut is None:
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap(name)
        lut = cmap(np.linspace(0.0, 1.0, 256, dtype=np.float32))[:, :3].astype(np.float32)
        _LUT_CACHE[name] = lut
    return lut


def colorize_point_cloud(pcd: o3d.geometry.PointCloud,
                         deviations: np.ndarray,
                         tolerance: float,
                         colormap_name: str = "coolwarm") -> o3d.geometry.PointCloud:
    lut = _get_lut(colormap_name)

    dev = deviations.astype(np.float32, copy=False)
    span = np.float32(2.0 * tolerance)
    idx = (dev + np.float32(tolerance)) * (np.float32(255.0) / span)
    np.clip(idx, 0.0, 255.0, out=idx)
    colors = lut[idx.astype(np.uint8)]

    pcd_colored = o3d.geometry.PointCloud()
    pcd_colored.points = pcd.points
    pcd_colored.colors = o3d.utility.Vector3dVector(colors.astype(np.float64, copy=False))

    return pcd_colored
