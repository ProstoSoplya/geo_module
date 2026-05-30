"""
deviation.py — Вычисление отклонений облака точек от CAD-модели.

Метод: Cloud-to-Mesh distance (расстояние от облака до поверхности сетки).

Знак отклонения:
    + (положительное) — точка скана СНАРУЖИ CAD-модели (деталь больше эталона)
    − (отрицательное) — точка скана ВНУТРИ  CAD-модели (деталь меньше эталона)

Для watertight-моделей знак определяется через winding-number
(compute_signed_distance) — это надёжно работает на срединной поверхности
тонких стенок, где эвристика по нормали грани ненадёжна.

Для не-watertight моделей знак остаётся эвристическим (нормаль ближайшей грани).

Конвенция Open3D compute_signed_distance (проверена тестом на кубе):
    sd > 0 — снаружи замкнутой поверхности  → совпадает с нашей семантикой (+)
    sd < 0 — внутри  замкнутой поверхности  → совпадает с нашей семантикой (−)
    Инверсия НЕ нужна.
"""

import logging
import open3d as o3d
import numpy as np

logger = logging.getLogger(__name__)


def compute_deviations(
    pcd_registered: o3d.geometry.PointCloud,
    mesh: o3d.geometry.TriangleMesh,
    progress_callback=None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Вычисляет знаковые отклонения и маску неоднозначного знака.

    Возвращает:
        (signed_distances, ambiguous_mask)
        signed_distances — float64 ndarray, размер (N,), мм
        ambiguous_mask   — bool ndarray,    размер (N,)

    Алгоритм (watertight):
        1. compute_closest_points → unsigned distance + heuristic sign
        2. compute_signed_distance → winding-based sign (надёжен на срединных поверхностях)
        3. ambiguous_mask = где эвристика расходится с winding-знаком
        4. signed_distance = |sd| * sign_sd

    Алгоритм (не-watertight):
        1. Эвристика по нормали ближайшей грани (как раньше)
        2. ambiguous_mask = точки, где вектор почти в плоскости грани (|cos| < 0.05),
           т.е. у рёбер/кромок; НЕ ловит срединную поверхность тонкой стенки.
    """
    logger.info("Cloud-to-Mesh: вычисление отклонений...")

    points = np.asarray(pcd_registered.points).astype(np.float32)

    mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(mesh)
    scene  = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(mesh_t)
    query_points = o3d.core.Tensor(points, dtype=o3d.core.Dtype.Float32)

    # ── Всегда: ближайшая точка → unsigned dist + heuristic sign ──
    result           = scene.compute_closest_points(query_points)
    closest_points   = result["points"].numpy()
    primitive_normals= result["primitive_normals"].numpy()

    vectors           = points - closest_points
    distances_unsigned= np.linalg.norm(vectors, axis=1)
    dots              = np.einsum("ij,ij->i", vectors, primitive_normals)

    if mesh.is_watertight():
        # ── Watertight: winding-number знак ───────────────────────
        sd_values = scene.compute_signed_distance(query_points).numpy()  # float32

        sign_sd = np.sign(sd_values).astype(np.float64)
        sign_sd[sign_sd == 0.0] = 1.0   # на поверхности: нейтральный → "+"

        # Sanity-check модулей
        abs_sd = np.abs(sd_values)
        bbox_diag = float(np.linalg.norm(
            np.asarray(mesh.get_axis_aligned_bounding_box().get_extent())
        ))
        threshold = max(1e-3, bbox_diag * 1e-4)
        mismatch_mean = float(np.abs(abs_sd - distances_unsigned).mean())
        if mismatch_mean > threshold:
            logger.warning(
                "Sanity-check расстояний: среднее расхождение "
                f"compute_signed_distance vs compute_closest_points = "
                f"{mismatch_mean:.6f} мм (порог {threshold:.6f} мм). "
                "Возможна ошибка геометрии."
            )

        signed_distances = (abs_sd * sign_sd).astype(np.float64)

        # ambiguous = где эвристика по нормали расходится с winding-знаком
        heuristic_signs = np.where(dots >= 0, 1.0, -1.0)
        ambiguous_mask  = heuristic_signs != sign_sd

        logger.info(
            f"Watertight: знак по winding-number. "
            f"Неоднозначных точек (эвристика vs winding): "
            f"{int(ambiguous_mask.sum()):,}"
        )
    else:
        # ── Не-watertight: эвристика ──────────────────────────────
        logger.warning(
            "Модель не является замкнутой (watertight). "
            "Знак отклонения эвристический — определяется по нормали ближайшей грани. "
            "Надёжен только для замкнутых моделей; "
            "флаг ambiguous отмечает точки у рёбер/кромок."
        )
        cos_angle      = dots / (distances_unsigned + 1e-10)
        ambiguous_mask = np.abs(cos_angle) < 0.05   # вектор почти в плоскости грани
        heuristic_signs= np.where(dots >= 0, 1.0, -1.0)
        signed_distances = (distances_unsigned * heuristic_signs).astype(np.float64)

    if progress_callback:
        progress_callback(88)

    logger.info(
        f"Отклонения вычислены. "
        f"Мин: {signed_distances.min():.4f}, "
        f"Макс: {signed_distances.max():.4f}, "
        f"Среднее: {signed_distances.mean():.4f}"
    )

    return signed_distances, ambiguous_mask


def compute_statistics(
    deviations: np.ndarray,
    tolerance: float,
    ambiguous_mask: np.ndarray | None = None,
    point_coords: np.ndarray | None = None,
    worst_n: int = 10,
    min_cluster_size: int = 3,
) -> dict:
    """
    Вычисляет статистику по отклонениям.

    Параметры:
        deviations       — знаковые отклонения (float64 ndarray)
        tolerance        — допуск в мм
        ambiguous_mask   — булева маска точек с неоднозначным знаком (необязательна)
        point_coords     — координаты (N×3), если переданы — заполняется worst_points
        worst_n          — число точек с максимальным |отклонением| для worst_points
        min_cluster_size — мин. число соседей-кандидатов для подтверждения дефекта
    """
    n = int(len(deviations))
    if n == 0:
        logger.warning("compute_statistics: пустой массив отклонений — нулевые метрики")
        return {
            "mean_deviation":       0.0,
            "median_deviation":     0.0,
            "rmse":                 0.0,
            "max_deviation":        0.0,
            "min_deviation":        0.0,
            "max_abs_deviation":    0.0,
            "std_deviation":        0.0,
            "percentile_95":        0.0,
            "percentile_99":        0.0,
            "within_tolerance":     0.0,
            "over_material_pct":    0.0,
            "under_material_pct":   0.0,
            "n_points":             0,
            "tolerance":            float(tolerance),
            "ambiguous_sign_count": 0,
            "ambiguous_sign_pct":   0.0,
        }

    abs_dev   = np.abs(deviations)
    within_tol= np.sum(abs_dev <= tolerance) / n

    n_over  = int(np.sum(deviations >  tolerance))
    n_under = int(np.sum(deviations < -tolerance))

    stats = {
        "mean_deviation":    float(np.mean(deviations)),
        "median_deviation":  float(np.median(deviations)),
        "rmse":              float(np.sqrt(np.mean(deviations ** 2))),
        "max_deviation":     float(deviations.max()),
        "min_deviation":     float(deviations.min()),
        "max_abs_deviation": float(abs_dev.max()),
        "std_deviation":     float(np.std(deviations)),
        "percentile_95":     float(np.percentile(abs_dev, 95)),
        "percentile_99":     float(np.percentile(abs_dev, 99)),
        "within_tolerance":  float(within_tol),
        "over_material_pct": float(n_over  / n) if n > 0 else 0.0,
        "under_material_pct":float(n_under / n) if n > 0 else 0.0,
        "n_points":          n,
        "tolerance":         float(tolerance),
    }

    amb_count = int(np.sum(ambiguous_mask)) if ambiguous_mask is not None else 0
    stats["ambiguous_sign_count"] = amb_count
    stats["ambiguous_sign_pct"]   = float(amb_count / n) if n > 0 else 0.0

    if point_coords is not None and len(point_coords) == n:
        stats.update(_build_worst_points(
            abs_dev, deviations, point_coords, tolerance,
            worst_n, min_cluster_size,
        ))
        stats["defect_clusters"] = _build_defect_clusters(
            abs_dev, deviations, point_coords, tolerance, min_cluster_size,
        )

    logger.info(
        f"Статистика: среднее={stats['mean_deviation']:.4f}, "
        f"RMSE={stats['rmse']:.4f}, "
        f"макс|отклонение|={stats['max_abs_deviation']:.4f}, "
        f"в допуске={stats['within_tolerance']*100:.1f}%, "
        f"избыток={n_over}, недостаток={n_under}, "
        f"неоднозначный знак={amb_count}"
    )

    return stats


def _build_worst_points(
    abs_dev: np.ndarray,
    deviations: np.ndarray,
    point_coords: np.ndarray,
    tolerance: float,
    worst_n: int,
    min_cluster_size: int,
) -> dict:
    """Формирует worst_points с фильтрацией шумовых выбросов по локальной плотности."""
    n = len(deviations)
    candidate_mask = abs_dev > tolerance
    n_candidates = int(candidate_mask.sum())

    unfiltered_idx = np.argsort(abs_dev)[::-1][:worst_n]

    if n_candidates < min_cluster_size:
        return {
            "worst_points": _idx_to_points(unfiltered_idx, point_coords, deviations),
            "worst_points_unfiltered": n_candidates < min_cluster_size,
            "noise_outlier_count": 0,
        }

    candidate_indices = np.nonzero(candidate_mask)[0]
    candidate_coords = point_coords[candidate_indices]

    bbox_diag = float(np.linalg.norm(
        point_coords.max(axis=0) - point_coords.min(axis=0)
    ))
    avg_step = bbox_diag / (n ** (1.0 / 3.0))
    radius = 3.0 * avg_step

    pcd_cand = o3d.geometry.PointCloud()
    pcd_cand.points = o3d.utility.Vector3dVector(candidate_coords)
    tree = o3d.geometry.KDTreeFlann(pcd_cand)

    # search_radius_vector_3d включает саму точку → порог = min_cluster_size + 1
    threshold = min_cluster_size + 1
    real_defect_local_mask = np.empty(n_candidates, dtype=bool)
    for i in range(n_candidates):
        k, _, _ = tree.search_radius_vector_3d(pcd_cand.points[i], radius)
        real_defect_local_mask[i] = k >= threshold

    noise_count = int(np.sum(~real_defect_local_mask))
    real_defect_global_indices = candidate_indices[real_defect_local_mask]

    if len(real_defect_global_indices) == 0:
        return {
            "worst_points": _idx_to_points(unfiltered_idx, point_coords, deviations),
            "worst_points_unfiltered": True,
            "noise_outlier_count": noise_count,
        }

    filtered_abs = abs_dev[real_defect_global_indices]
    top_local = np.argsort(filtered_abs)[::-1][:worst_n]
    top_global = real_defect_global_indices[top_local]

    return {
        "worst_points": _idx_to_points(top_global, point_coords, deviations),
        "worst_points_unfiltered": False,
        "noise_outlier_count": noise_count,
    }


def _build_defect_clusters(
    abs_dev: np.ndarray,
    deviations: np.ndarray,
    point_coords: np.ndarray,
    tolerance: float,
    min_cluster_size: int,
) -> list[dict]:
    """Группирует дефектные точки (|dev| > tolerance) в кластеры, исключая шум."""
    candidate_mask = abs_dev > tolerance
    n_candidates = int(candidate_mask.sum())
    if n_candidates < min_cluster_size:
        return []

    candidate_indices = np.nonzero(candidate_mask)[0]
    candidate_coords = point_coords[candidate_indices]
    candidate_devs = deviations[candidate_indices]

    n = len(deviations)
    bbox_diag = float(np.linalg.norm(
        point_coords.max(axis=0) - point_coords.min(axis=0)
    ))
    avg_step = bbox_diag / (n ** (1.0 / 3.0))
    radius = 3.0 * avg_step

    pcd_cand = o3d.geometry.PointCloud()
    pcd_cand.points = o3d.utility.Vector3dVector(candidate_coords)
    tree = o3d.geometry.KDTreeFlann(pcd_cand)

    threshold = min_cluster_size + 1
    real_mask = np.empty(n_candidates, dtype=bool)
    for i in range(n_candidates):
        k, _, _ = tree.search_radius_vector_3d(pcd_cand.points[i], radius)
        real_mask[i] = k >= threshold

    real_local = np.where(real_mask)[0]
    if len(real_local) == 0:
        return []

    real_coords = candidate_coords[real_local]
    real_devs = candidate_devs[real_local]

    pcd_real = o3d.geometry.PointCloud()
    pcd_real.points = o3d.utility.Vector3dVector(real_coords)
    tree_real = o3d.geometry.KDTreeFlann(pcd_real)

    visited = np.zeros(len(real_local), dtype=bool)
    clusters = []

    for start in range(len(real_local)):
        if visited[start]:
            continue
        queue = [start]
        visited[start] = True
        members = []
        while queue:
            cur = queue.pop(0)
            members.append(cur)
            k, idx, _ = tree_real.search_radius_vector_3d(
                pcd_real.points[cur], radius)
            for j in range(k):
                nb = idx[j]
                if not visited[nb]:
                    visited[nb] = True
                    queue.append(nb)

        if len(members) < min_cluster_size:
            continue

        m = np.array(members)
        m_devs = real_devs[m]
        m_coords = real_coords[m]
        mean_dev = float(np.mean(m_devs))
        max_abs = float(np.max(np.abs(m_devs)))
        center = m_coords.mean(axis=0)

        clusters.append({
            "type": "Избыток материала" if mean_dev > 0 else "Недостаток материала",
            "max_deviation": max_abs,
            "point_count": len(members),
            "center_x": float(center[0]),
            "center_y": float(center[1]),
            "center_z": float(center[2]),
        })

    clusters.sort(key=lambda c: c["max_deviation"], reverse=True)
    return clusters


def _idx_to_points(indices: np.ndarray, coords: np.ndarray, devs: np.ndarray) -> list[dict]:
    return [
        {
            "x":   float(coords[i, 0]),
            "y":   float(coords[i, 1]),
            "z":   float(coords[i, 2]),
            "dev": float(devs[i]),
        }
        for i in indices
    ]


_LUT_CACHE: dict[str, np.ndarray] = {}


def _get_lut(name: str) -> np.ndarray:
    """LUT 256×3 (float32) для заданной cmap. Строится один раз на имя."""
    lut = _LUT_CACHE.get(name)
    if lut is None:
        import matplotlib.pyplot as plt
        cmap = plt.get_cmap(name)
        lut  = cmap(np.linspace(0.0, 1.0, 256, dtype=np.float32))[:, :3].astype(np.float32)
        _LUT_CACHE[name] = lut
    return lut


def colorize_point_cloud(
    pcd: o3d.geometry.PointCloud,
    deviations: np.ndarray,
    tolerance: float,
    colormap_name: str = "coolwarm",
    ambiguous_mask: np.ndarray | None = None,
) -> o3d.geometry.PointCloud:
    """
    Раскрашивает облако точек по отклонениям (цветовая шкала ±tolerance).

    Если передана ambiguous_mask — точки с неоднозначным знаком окрашиваются
    нейтральным серым [0.55, 0.55, 0.55] поверх цветовой шкалы.
    """
    lut = _get_lut(colormap_name)

    dev  = deviations.astype(np.float32, copy=False)
    span = np.float32(2.0 * tolerance)
    idx  = (dev + np.float32(tolerance)) * (np.float32(255.0) / span)
    np.clip(idx, 0.0, 255.0, out=idx)
    colors = lut[idx.astype(np.uint8)]

    if ambiguous_mask is not None and ambiguous_mask.any():
        colors[ambiguous_mask] = np.float32([0.55, 0.55, 0.55])

    pcd_colored        = o3d.geometry.PointCloud()
    pcd_colored.points = pcd.points
    pcd_colored.colors = o3d.utility.Vector3dVector(
        colors.astype(np.float64, copy=False)
    )
    return pcd_colored
