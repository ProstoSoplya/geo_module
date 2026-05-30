"""
preprocessing.py — Предобработка облака точек.

Содержит два алгоритма:
1. SOR (Statistical Outlier Removal) — удаление шумовых точек
2. Voxel Grid Downsampling — прореживание облака

Эти функции вызываются из worker.py в фоновом потоке.
"""

import logging
import open3d as o3d
import numpy as np

logger = logging.getLogger(__name__)


def remove_outliers(pcd: o3d.geometry.PointCloud,
                    nb_neighbors: int = 20,
                    std_ratio: float = 2.0) -> o3d.geometry.PointCloud:
    """
    SOR — Statistical Outlier Removal.

    Для каждой точки смотрит на nb_neighbors ближайших соседей.
    Вычисляет среднее расстояние до них.
    Удаляет точки, у которых это расстояние статистически аномально велико
    (отличается от среднего по облаку более чем на std_ratio * std_dev).

    Параметры:
        pcd          — входное облако точек (o3d.PointCloud)
        nb_neighbors — сколько соседей учитывать (больше = медленнее, но точнее)
        std_ratio    — строгость фильтрации (меньше = строже, удаляет больше)

    Возвращает:
        Очищенное облако точек.
    """
    n_before = len(pcd.points)

    if n_before < 10:
        logger.warning(f"SOR: слишком мало точек ({n_before}), пропуск фильтрации")
        return pcd

    logger.info(f"SOR: начало. Точек до фильтрации: {n_before:,}")

    pcd_clean, inlier_indices = pcd.remove_statistical_outlier(
        nb_neighbors=nb_neighbors,
        std_ratio=std_ratio
    )

    n_after = len(pcd_clean.points)
    n_removed = n_before - n_after
    logger.info(f"SOR: удалено {n_removed:,} выбросов. Осталось: {n_after:,} точек")

    if n_after < 100:
        logger.warning(
            f"SOR: после фильтрации осталось только {n_after} точек. "
            f"Возможно, std_ratio слишком мал или данные некорректны."
        )

    return pcd_clean


def voxel_downsample(pcd: o3d.geometry.PointCloud,
                     voxel_size: float = 0.1) -> o3d.geometry.PointCloud:
    """
    Voxel Grid Downsampling — прореживание облака точек.

    Делит 3D-пространство на кубики со стороной voxel_size.
    В каждом кубике оставляет одну точку — центроид (среднее всех точек куба).

    Параметры:
        pcd        — входное облако точек
        voxel_size — размер стороны воксела в тех же единицах, что и модель

    Возвращает:
        Прореженное облако точек.
    """
    n_before = len(pcd.points)
    logger.info(f"Voxel Grid: начало. voxel_size={voxel_size:.4f}. Точек: {n_before:,}")

    pcd_down = pcd.voxel_down_sample(voxel_size=voxel_size)

    n_after = len(pcd_down.points)

    if n_after == 0:
        logger.warning(
            f"Voxel Grid: результат пустой (voxel_size={voxel_size:.4f} слишком велик?). "
            f"Возвращаем исходное облако."
        )
        return pcd

    ratio = n_before / max(n_after, 1)
    logger.info(f"Voxel Grid: {n_before:,} → {n_after:,} точек (уменьшено в {ratio:.1f}x)")

    return pcd_down


def preprocess_pipeline(pcd: o3d.geometry.PointCloud,
                         config: dict,
                         progress_callback=None) -> tuple:
    """
    Полный пайплайн предобработки.

    Запускает SOR → Voxel Grid последовательно.
    Нормали НЕ вычисляются здесь — registration.py пересчитает их
    с правильным радиусом под масштаб модели.

    Возвращает:
        (pcd_full, pcd_down, voxel_size) — полное очищенное и прореженное облака
        + размер вокселя, фактически использованный для прореживания (нужен
        registration.py для решения о повторном прореживании).
    """
    pre = config["preprocessing"]

    # Шаг 1: Удаление выбросов
    pcd_clean = remove_outliers(
        pcd,
        nb_neighbors=pre["sor_neighbors"],
        std_ratio=pre["sor_std_ratio"]
    )
    if progress_callback:
        progress_callback(15)

    # Шаг 2: Вычисление voxel_size
    # voxel_size <= 0 или "auto" → адаптивный: 1.5% от диагонали bbox облака
    raw_voxel = pre["voxel_size"]
    try:
        voxel_size = float(raw_voxel)
    except (ValueError, TypeError):
        voxel_size = 0.0

    # `not (voxel_size > 0)` ловит NaN (NaN <= 0 → False, проскакивал бы guard).
    if not (voxel_size > 0):
        bbox = pcd_clean.get_axis_aligned_bounding_box()
        bbox_diag = float(np.linalg.norm(bbox.get_extent()))
        voxel_size = bbox_diag * 0.015
        logger.info(
            f"Авто voxel_size = {voxel_size:.4f} "
            f"(1.5% от диагонали bbox облака {bbox_diag:.2f})"
        )

    # Шаг 3: Прореживание
    pcd_down = voxel_downsample(pcd_clean, voxel_size=voxel_size)
    if progress_callback:
        progress_callback(25)

    return pcd_clean, pcd_down, voxel_size
