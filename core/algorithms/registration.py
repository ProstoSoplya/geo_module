"""
registration.py — Регистрация облака точек с CAD-моделью.

Ключевое улучшение: все параметры вычисляются АВТОМАТИЧЕСКИ
из диагонали ограничивающего прямоугольника модели.
Это решает проблему «параметры не подходят к масштабу модели».

Пайплайн:
    1. Автоматический расчёт параметров по размеру модели
    2. Предвыравнивание по центрам масс (детерминированное)
    3. Мультистарт RANSAC + FPFH (5 попыток)
    4. Двухпроходный Point-to-Plane ICP
    5. Fallback: если всё провалилось — только центроиды + ICP
"""

import concurrent.futures
import copy
import logging
import open3d as o3d
import numpy as np

logger = logging.getLogger(__name__)


class RegistrationError(RuntimeError):
    """Ошибка регистрации — модели несовместимы."""


def _compute_adaptive_params(mesh: o3d.geometry.TriangleMesh) -> dict:
    """
    Вычисляет параметры алгоритмов автоматически,
    исходя из реального размера модели.

    Диагональ ограничивающего прямоугольника (bbox_diag) —
    это «характерный масштаб» объекта. Все пороги задаём
    как доли от этого масштаба. Это работает для моделей
    любого размера: 10 мм или 1000 мм.
    """
    bbox = mesh.get_axis_aligned_bounding_box()
    extent = bbox.get_extent()
    bbox_diag = float(np.linalg.norm(extent))

    params = {
        "voxel_size":       bbox_diag * 0.02,   # 2% от диагонали
        "fpfh_radius":      bbox_diag * 0.05,   # 5% от диагонали
        "ransac_distance":  bbox_diag * 0.03,   # 3% от диагонали
        "bbox_diag":        bbox_diag,
    }

    logger.info(
        f"Размер модели: {extent.round(2)} мм, "
        f"диагональ: {bbox_diag:.2f} мм"
    )
    logger.info(
        f"Адаптивные параметры: "
        f"voxel={params['voxel_size']:.3f}, "
        f"fpfh_r={params['fpfh_radius']:.3f}, "
        f"ransac_d={params['ransac_distance']:.3f}"
    )

    return params


def _prepare_clouds(pcd_full, pcd_down, mesh, ap, progress_callback=None,
                     _prog_start=35, _prog_end=45):
    """
    Подготавливает все облака точек: прореживает, вычисляет нормали.

    Оптимизация: orient_normals_consistent_tangent_plane (k=15) применяется
    только к облакам скана — для облаков CAD-сетки нормали уже согласованы
    геометрически (uniform sampling от меша с vertex normals).
    Это даёт ~2× ускорение при минимальной потере качества нормалей.
    """
    search_param = o3d.geometry.KDTreeSearchParamHybrid(
        radius=ap["fpfh_radius"], max_nn=30
    )

    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()

    # Uniform + use_triangle_normal=True: нормали сразу от граней меша,
    # не нужно вызывать estimate_normals на mesh_pcd. Poisson-disk на больших
    # мешах занимает десятки секунд (rejection-sampling), uniform — доли секунды.
    mesh_pcd_full = mesh.sample_points_uniformly(
        number_of_points=max(len(pcd_full.points), 50000),
        use_triangle_normal=True
    )
    mesh_pcd_down = mesh.sample_points_uniformly(
        number_of_points=max(len(pcd_down.points), 20000),
        use_triangle_normal=True
    )

    prog_step = (_prog_end - _prog_start) / 3

    # pcd_full: только estimate_normals, БЕЗ orient_normals_consistent_tangent_plane.
    # Riemannian MST по 500K–1M точкам занимает 30–120 с, а для нашей задачи не нужен:
    # Point-to-Plane ICP использует квадрат проекции (знак нормали не влияет),
    # RaycastingScene определяет знак отклонения сам по нормали ближайшей грани.
    pcd_full.estimate_normals(search_param)
    if progress_callback:
        progress_callback(int(_prog_start + prog_step))

    # pcd_down: estimate + orient. Облако в 10–50× меньше, согласование быстрое,
    # ориентация помогает FPFH/RANSAC точнее матчить дескрипторы.
    pcd_down.estimate_normals(search_param)
    pcd_down.orient_normals_consistent_tangent_plane(k=15)
    if progress_callback:
        progress_callback(int(_prog_start + 2 * prog_step))

    if progress_callback:
        progress_callback(int(_prog_end))

    return mesh_pcd_full, mesh_pcd_down


def _compute_fpfh(pcd: o3d.geometry.PointCloud, radius: float):
    """Вычисляет FPFH-дескрипторы."""
    return o3d.pipelines.registration.compute_fpfh_feature(
        pcd,
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=100)
    )


def _ransac_multistart(pcd_down, mesh_pcd_down,
                        fpfh_pcd, fpfh_mesh,
                        ransac_dist, ransac_max_iter=200000, n_starts=5,
                        progress_callback=None, _prog_start=52, _prog_end=65):
    """
    Мультистарт RANSAC. Запускает n_starts раз, возвращает лучший по fitness.
    progress_callback вызывается между запусками — это позволяет Qt event loop
    обрабатывать сообщения между тяжёлыми C++ вызовами Open3D.
    """
    best = None
    prog_step = (_prog_end - _prog_start) / max(n_starts, 1)

    for i in range(n_starts):
        result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            pcd_down, mesh_pcd_down,
            fpfh_pcd, fpfh_mesh,
            mutual_filter=True,
            max_correspondence_distance=ransac_dist,
            estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            ransac_n=3,
            checkers=[
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(ransac_dist)
            ],
            criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(
                ransac_max_iter, 0.9999
            )
        )
        logger.info(
            f"  RANSAC [{i+1}/{n_starts}]: "
            f"fitness={result.fitness:.4f}, rmse={result.inlier_rmse:.4f}"
        )
        if best is None or result.fitness > best.fitness:
            best = result

        # Вызов callback между запусками даёт Qt обработать сообщения Windows
        if progress_callback:
            progress_callback(int(_prog_start + prog_step * (i + 1)))

    logger.info(f"RANSAC лучший: fitness={best.fitness:.4f}")
    return best


def _icp_with_timeout(pcd, mesh_pcd, dist, init_T, criteria, timeout=60):
    """
    Один проход ICP с таймаутом.
    Если ICP не сходится за timeout секунд — бросает TimeoutError.
    Фоновый поток продолжает работу, но pipeline уже прерван.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = executor.submit(
            o3d.pipelines.registration.registration_icp,
            pcd, mesh_pcd, dist, init_T,
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            criteria,
        )
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(
            "Совмещение не сходится. "
            "Возможно, загружены файлы разных деталей."
        )
    finally:
        executor.shutdown(wait=False)


def _icp_two_pass(pcd, mesh_pcd, init_T, dist1, dist2, max_iter=150,
                   timeout=60, progress_callback=None, _prog_mid=73):
    """
    ICP двумя проходами.
    Проход 1: большой порог → устраняет крупные ошибки RANSAC.
    Проход 2: маленький порог → точная финальная доводка.
    progress_callback между проходами позволяет Qt обработать сообщения.
    Каждый проход ограничен timeout секундами.
    """
    r1 = _icp_with_timeout(
        pcd, mesh_pcd, dist1, init_T,
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=80),
        timeout=timeout,
    )
    logger.info(f"ICP проход 1: rmse={r1.inlier_rmse:.6f}, fitness={r1.fitness:.4f}")

    if progress_callback:
        progress_callback(_prog_mid)

    r2 = _icp_with_timeout(
        pcd, mesh_pcd, dist2, r1.transformation,
        o3d.pipelines.registration.ICPConvergenceCriteria(
            max_iteration=max_iter,
            relative_fitness=1e-6,
            relative_rmse=1e-6,
        ),
        timeout=timeout,
    )
    logger.info(f"ICP проход 2: rmse={r2.inlier_rmse:.6f}, fitness={r2.fitness:.4f}")
    return r2


def register_pipeline(pcd_full: o3d.geometry.PointCloud,
                       pcd_down: o3d.geometry.PointCloud,
                       mesh: o3d.geometry.TriangleMesh,
                       config: dict,
                       progress_callback=None,
                       pcd_voxel_size: float = 0.0) -> tuple:
    """
    Полный пайплайн регистрации с адаптивными параметрами.

    Параметры:
        pcd_voxel_size — размер вокселя, использованный preprocessing для pcd_down.
                         Если он близок к адаптивному (разница ≤ 20%) — pcd_down
                         используется как есть, без повторного прореживания.

    Возвращает: (pcd_registered, transformation, rmse)
    """

    # ── Шаг 1: Адаптивные параметры ──────────────────────────────
    ap = _compute_adaptive_params(mesh)

    # Используем уже прореженное pcd_down из preprocessing, если его
    # voxel_size близок к адаптивному (разница ≤ 20%) — это устраняет
    # двойную фильтрацию. Иначе пересчитываем от pcd_full.
    reg_voxel = ap["voxel_size"]
    reuse = (
        pcd_voxel_size > 0
        and abs(reg_voxel - pcd_voxel_size) / max(reg_voxel, pcd_voxel_size) <= 0.2
    )
    if reuse:
        logger.info(
            f"Используем pcd_down из preprocessing "
            f"(voxel={pcd_voxel_size:.4f} ≈ адаптивный {reg_voxel:.4f})"
        )
        pcd_down_new = pcd_down
    else:
        if pcd_voxel_size > 0:
            logger.info(
                f"Пересчитываем прореживание: "
                f"preprocessing voxel={pcd_voxel_size:.4f}, "
                f"адаптивный voxel={reg_voxel:.4f} (разница > 20%)"
            )
        pcd_down_new = pcd_full.voxel_down_sample(reg_voxel)
        if len(pcd_down_new.points) < 50:
            logger.warning("После прореживания слишком мало точек, используем оригинал")
            pcd_down_new = pcd_down

    if progress_callback:
        progress_callback(35)

    # ── Шаг 2: Подготовка облаков (нормали + ориентация) ─────────
    # progress_callback вызывается внутри _prepare_clouds между каждым облаком
    # (35→45), давая Qt окна для обработки сообщений Windows
    mesh_pcd_full, mesh_pcd_down = _prepare_clouds(
        pcd_full, pcd_down_new, mesh, ap,
        progress_callback=progress_callback,
        _prog_start=35, _prog_end=45
    )

    # ── Шаг 3: Предвыравнивание по центрам масс ───────────────────
    # Одна матрица сдвига — применяем к pcd_full и pcd_down_new.
    # Центроиды pcd_full и pcd_down_new практически совпадают (voxel-down
    # сохраняет распределение), так же как mesh_pcd_full ≈ mesh_pcd_down.
    c_pcd  = np.asarray(pcd_full.points).mean(axis=0)
    c_mesh = np.asarray(mesh_pcd_full.points).mean(axis=0)
    t = c_mesh - c_pcd
    T_centroid = np.eye(4)
    T_centroid[:3, 3] = t
    logger.info(f"Предвыравнивание: смещение {t.round(3)} мм")

    pcd_full_aligned = copy.deepcopy(pcd_full).transform(T_centroid)
    pcd_down_aligned = copy.deepcopy(pcd_down_new).transform(T_centroid)

    if progress_callback:
        progress_callback(45)

    # ── Шаг 4: FPFH-дескрипторы ──────────────────────────────────
    logger.info("Вычисление FPFH-дескрипторов...")
    fpfh_pcd  = _compute_fpfh(pcd_down_aligned, ap["fpfh_radius"])
    fpfh_mesh = _compute_fpfh(mesh_pcd_down,    ap["fpfh_radius"])

    if progress_callback:
        progress_callback(52)

    # ── Шаг 5: Мультистарт RANSAC ────────────────────────────────
    ransac_max_iter = config["registration"]["ransac_max_iter"]
    ransac_n_starts = config["registration"].get("ransac_n_starts", 5)
    logger.info(
        f"Запуск RANSAC ({ransac_n_starts} попыток, "
        f"до {ransac_max_iter} итераций каждая)..."
    )
    # progress_callback вызывается между каждым запуском (52→65)
    result_coarse = _ransac_multistart(
        pcd_down_aligned, mesh_pcd_down,
        fpfh_pcd, fpfh_mesh,
        ap["ransac_distance"],
        ransac_max_iter=ransac_max_iter,
        n_starts=ransac_n_starts,
        progress_callback=progress_callback,
        _prog_start=52, _prog_end=65
    )
    # progress_callback(65) уже вызван внутри _ransac_multistart

    # ── Шаг 6: Проверка RANSAC, fallback если плохо ───────────────
    if result_coarse.fitness < 0.01:
        raise RegistrationError(
            f"Не удалось совместить скан с моделью (fitness={result_coarse.fitness:.4f}). "
            "Убедитесь, что загружены файлы одной и той же детали."
        )
    if result_coarse.fitness < 0.05:
        logger.warning(
            f"RANSAC провалился (fitness={result_coarse.fitness:.4f}). "
            f"Используем только центроидное совмещение."
        )
        init_transform = np.eye(4)
    else:
        init_transform = result_coarse.transformation

    # ── Шаг 7: Двухпроходный ICP ─────────────────────────────────
    # Переопределяем пороги ICP из конфига (если заданы) вместо адаптивных
    coarse_pct = config["registration"].get("icp_coarse_pct", 5.0)
    fine_pct   = config["registration"].get("icp_fine_pct",   1.0)
    icp_dist1  = ap["bbox_diag"] * coarse_pct / 100.0
    icp_dist2  = ap["bbox_diag"] * fine_pct   / 100.0

    logger.info(
        f"Запуск двухпроходного ICP: "
        f"грубый={icp_dist1:.3f} мм ({coarse_pct}%), "
        f"точный={icp_dist2:.3f} мм ({fine_pct}%)..."
    )
    # progress_callback(73) вызывается внутри _icp_two_pass между проходами,
    # progress_callback(80) — после завершения обоих проходов
    result_fine = _icp_two_pass(
        pcd_full_aligned, mesh_pcd_full,
        init_transform,
        dist1=icp_dist1,
        dist2=icp_dist2,
        max_iter=config["registration"]["icp_max_iter"],
        timeout=60,
        progress_callback=progress_callback,
        _prog_mid=73
    )

    if progress_callback:
        progress_callback(80)

    # ── Шаг 8: Применяем финальную трансформацию ─────────────────
    # pcd_full_aligned дальше не используется — трансформируем in-place.
    pcd_registered = pcd_full_aligned.transform(result_fine.transformation)

    rmse = result_fine.inlier_rmse
    logger.info(f"Регистрация завершена: fitness={result_fine.fitness:.4f}, RMSE={rmse:.6f} мм")

    if rmse > ap["bbox_diag"] * 0.05:
        logger.warning(
            f"RMSE ({rmse:.4f} мм) велик относительно размера модели "
            f"({ap['bbox_diag']:.1f} мм). Возможно, регистрация неточна."
        )

    return pcd_registered, result_fine.transformation, rmse
