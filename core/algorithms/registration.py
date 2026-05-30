"""
registration.py — Регистрация облака точек с CAD-моделью.

Пайплайн:
    1. Адаптивные параметры из bbox-диагонали модели
    2. Центроидное предвыравнивание (детерминированное)
    3. PCA-гипотезы (4 знаковые комбинации главных осей, det=+1)
    4. Мультистарт RANSAC — top-K лучших по fitness
    5. Выбор победителя по C2M-RMSE через готовую RaycastingScene (BVH строится 1 раз)
    6. Двухпроходный Point-to-Plane ICP от уточнённой матрицы победителя
    7. Флаг registration_suspect при большом C2M-RMSE победителя
"""

import concurrent.futures
import copy
import logging

import numpy as np
import open3d as o3d

logger = logging.getLogger(__name__)


class RegistrationError(RuntimeError):
    """Ошибка регистрации — модели несовместимы."""


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

def _compute_adaptive_params(mesh: o3d.geometry.TriangleMesh) -> dict:
    """
    Вычисляет параметры алгоритмов автоматически из реального размера модели.
    Все пороги — доли от bbox-диагонали; работает для моделей любого масштаба.
    """
    bbox      = mesh.get_axis_aligned_bounding_box()
    extent    = bbox.get_extent()
    bbox_diag = float(np.linalg.norm(extent))

    params = {
        "voxel_size":      bbox_diag * 0.02,
        "fpfh_radius":     bbox_diag * 0.05,
        "ransac_distance": bbox_diag * 0.03,
        "bbox_diag":       bbox_diag,
    }
    logger.info(
        f"Размер модели: {extent.round(2)} мм, диагональ: {bbox_diag:.2f} мм"
    )
    logger.info(
        f"Адаптивные параметры: voxel={params['voxel_size']:.3f}, "
        f"fpfh_r={params['fpfh_radius']:.3f}, ransac_d={params['ransac_distance']:.3f}"
    )
    return params


def _prepare_clouds(pcd_full, pcd_down, mesh, ap, progress_callback=None,
                     _prog_start=35, _prog_end=45):
    """
    Подготавливает облака точек: прореживает меш, вычисляет нормали.
    orient_normals_consistent_tangent_plane применяется только к pcd_down —
    для облаков с меша нормали уже согласованы геометрически.
    """
    search_param = o3d.geometry.KDTreeSearchParamHybrid(
        radius=ap["fpfh_radius"], max_nn=30
    )

    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()

    mesh_pcd_full = mesh.sample_points_uniformly(
        number_of_points=max(len(pcd_full.points), 50000),
        use_triangle_normal=True,
    )
    mesh_pcd_down = mesh.sample_points_uniformly(
        number_of_points=max(len(pcd_down.points), 20000),
        use_triangle_normal=True,
    )

    prog_step = (_prog_end - _prog_start) / 3

    pcd_full.estimate_normals(search_param)
    if progress_callback:
        progress_callback(int(_prog_start + prog_step))

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
        o3d.geometry.KDTreeSearchParamHybrid(radius=radius, max_nn=100),
    )


def pca_alignment_candidates(pcd_pts: np.ndarray,
                               mesh_pts: np.ndarray) -> list[np.ndarray]:
    """
    Возвращает 4 матрицы 4×4, каждая из которых совмещает pcd с mesh по PCA-осям.

    Для обоих облаков собственные векторы ковариации сортируются по убыванию
    собственного значения — ось i облака скана сопоставляется оси i меша.
    4 знаковые комбинации (det(R)=+1) покрывают 180°-неоднозначность.
    """
    def pca_frame(pts: np.ndarray):
        c        = pts.mean(axis=0)
        cov      = np.cov((pts - c).T)
        eigvals, eigvecs = np.linalg.eigh(cov)          # по возрастанию
        idx      = np.argsort(eigvals)[::-1]             # → по убыванию
        return c, eigvecs[:, idx]

    c_pcd,  V_pcd  = pca_frame(pcd_pts)
    c_mesh, V_mesh = pca_frame(mesh_pts)

    # det(R) = det(V_mesh) · det(S) · det(V_pcd)  (все ±1)
    # → det(S) = det(V_mesh) · det(V_pcd)  чтобы det(R) = +1
    target_det_S = int(round(np.linalg.det(V_mesh) * np.linalg.det(V_pcd)))

    candidates: list[np.ndarray] = []
    for s1 in (+1, -1):
        for s2 in (+1, -1):
            s3 = target_det_S * s1 * s2   # s1·s2·s3 = target_det_S
            S  = np.diag([float(s1), float(s2), float(s3)])
            R  = V_mesh @ S @ V_pcd.T
            t  = c_mesh - R @ c_pcd
            T  = np.eye(4)
            T[:3, :3] = R
            T[:3,  3] = t
            candidates.append(T)
    return candidates


def _ransac_multistart(pcd_down, mesh_pcd_down,
                        fpfh_pcd, fpfh_mesh,
                        ransac_dist, ransac_max_iter=200_000, n_starts=5,
                        top_k=4,
                        progress_callback=None, _prog_start=52, _prog_end=65):
    """
    Мультистарт RANSAC. Запускает n_starts раз, возвращает top_k лучших по fitness.
    """
    results = []
    prog_step = (_prog_end - _prog_start) / max(n_starts, 1)

    for i in range(n_starts):
        try:
            result = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
                pcd_down, mesh_pcd_down,
                fpfh_pcd, fpfh_mesh,
                mutual_filter=True,
                max_correspondence_distance=ransac_dist,
                estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
                ransac_n=3,
                checkers=[
                    o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                    o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(ransac_dist),
                ],
                criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(
                    ransac_max_iter, 0.9999
                ),
            )
            logger.info(
                f"  RANSAC [{i+1}/{n_starts}]: "
                f"fitness={result.fitness:.4f}, rmse={result.inlier_rmse:.4f}"
            )
            results.append(result)
        except Exception as exc:
            logger.warning(f"  RANSAC [{i+1}/{n_starts}]: ошибка — {exc}")

        if progress_callback:
            progress_callback(int(_prog_start + prog_step * (i + 1)))

    if not results:
        logger.warning("Все RANSAC-старты провалились; продолжаем без RANSAC-гипотез")
        return []

    results.sort(key=lambda r: r.fitness, reverse=True)
    top = results[:top_k]
    logger.info(f"RANSAC топ-{len(top)}: fitness={[f'{r.fitness:.4f}' for r in top]}")
    return top


def _evaluate_candidate(
    pcd_down_aligned: o3d.geometry.PointCloud,
    mesh_pcd_down: o3d.geometry.PointCloud,
    scene: "o3d.t.geometry.RaycastingScene",
    T_init: np.ndarray,
    icp_dist: float,
    max_iter: int = 50,
) -> tuple[float, np.ndarray]:
    """
    Быстрый ICP (прореженное облако) + C2M-RMSE через готовую RaycastingScene.

    BVH меша не пересобирается — scene передаётся снаружи и используется
    всеми кандидатами. Возвращает (c2m_rmse, T_refined), где
    T_refined: pcd_down_aligned → совмещённое положение.
    """
    pcd_tmp = copy.deepcopy(pcd_down_aligned).transform(T_init)
    result  = o3d.pipelines.registration.registration_icp(
        pcd_tmp, mesh_pcd_down, icp_dist, np.eye(4),
        o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iter),
    )
    # T_refined переводит pcd_down_aligned прямо в совмещённое положение
    T_refined = result.transformation @ T_init

    pcd_eval = copy.deepcopy(pcd_down_aligned).transform(T_refined)
    pts      = np.asarray(pcd_eval.points).astype(np.float32)
    query    = o3d.core.Tensor(pts, dtype=o3d.core.Dtype.Float32)
    dists    = scene.compute_distance(query).numpy()
    c2m_rmse = float(np.sqrt(np.mean(dists ** 2)))
    return c2m_rmse, T_refined


def _icp_with_timeout(pcd, mesh_pcd, dist, init_T, criteria, timeout=60):
    """
    Один проход ICP с таймаутом.
    Если ICP не сходится за timeout секунд — бросает TimeoutError.
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
                   timeout=60, progress_callback=None, _prog_mid=76):
    """
    ICP двумя проходами от уточнённой матрицы победителя.
    Проход 1: большой порог → устраняет остаточные ошибки гипотезы.
    Проход 2: маленький порог → точная финальная доводка.

    Возвращает (r1, r2) — оба результата нужны для диагностики поглощённого отклонения.
    r1.transformation — трансформация после грубого прохода (T_coarse).
    r2.transformation — трансформация после точного прохода  (T_fine).
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
    return r1, r2


# ──────────────────────────────────────────────────────────────────────────────
# Главная функция
# ──────────────────────────────────────────────────────────────────────────────

def register_pipeline(pcd_full: o3d.geometry.PointCloud,
                       pcd_down: o3d.geometry.PointCloud,
                       mesh: o3d.geometry.TriangleMesh,
                       config: dict,
                       progress_callback=None,
                       pcd_voxel_size: float = 0.0) -> tuple:
    """
    Полный пайплайн регистрации с защитой от ложного 180°-минимума.

    Возвращает: (pcd_registered, transformation, rmse, registration_suspect, reg_diagnostics)
        pcd_registered      — зарегистрированное облако точек
        transformation      — итоговая матрица 4×4 от ИСХОДНОГО pcd_full в финальное
                              положение (T_total = T_selected @ T_centroid). Применение
                              этой матрицы к свежезагруженному pcd_full восстановит
                              совмещение, эквивалентное pcd_registered.
        rmse                — ICP inlier RMSE финального прохода
        registration_suspect— True если C2M-RMSE победителя > reject_rmse_pct% bbox_diag
        reg_diagnostics     — словарь диагностики (RMSE проходов, маскировка и т.п.)
    """

    # ── Шаг 1: Адаптивные параметры ──────────────────────────────
    ap = _compute_adaptive_params(mesh)

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
    mesh_pcd_full, mesh_pcd_down = _prepare_clouds(
        pcd_full, pcd_down_new, mesh, ap,
        progress_callback=progress_callback,
        _prog_start=35, _prog_end=45,
    )

    # ── Шаг 3: Предвыравнивание по центрам масс ───────────────────
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

    # ── Шаг 5: Сборка пула гипотез ───────────────────────────────
    ransac_max_iter = config["registration"]["ransac_max_iter"]
    ransac_n_starts = config["registration"].get("ransac_n_starts", 5)
    ransac_top_k    = config["registration"].get("ransac_top_k",   4)
    use_pca_seeds   = config["registration"].get("use_pca_seeds",  True)

    # BVH меша строится ОДИН раз — переиспользуется для всех кандидатов
    mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(mesh)
    scene  = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(mesh_t)

    # Базовая гипотеза: только центроидное смещение
    hypotheses: list[np.ndarray] = [np.eye(4)]

    # PCA-гипотезы: 4 знаковые комбинации главных осей
    if use_pca_seeds:
        pca_cands = pca_alignment_candidates(
            np.asarray(pcd_down_aligned.points),
            np.asarray(mesh_pcd_down.points),
        )
        hypotheses.extend(pca_cands)
        logger.info(f"PCA: добавлено {len(pca_cands)} гипотез")

    # Top-K RANSAC
    logger.info(
        f"Запуск RANSAC ({ransac_n_starts} попыток, "
        f"до {ransac_max_iter} итераций, top_k={ransac_top_k})..."
    )
    ransac_top = _ransac_multistart(
        pcd_down_aligned, mesh_pcd_down,
        fpfh_pcd, fpfh_mesh,
        ap["ransac_distance"],
        ransac_max_iter=ransac_max_iter,
        n_starts=ransac_n_starts,
        top_k=ransac_top_k,
        progress_callback=progress_callback,
        _prog_start=52, _prog_end=65,
    )
    for r in ransac_top:
        if r.fitness > 0.01:
            hypotheses.append(r.transformation)

    logger.info(
        f"Пул гипотез: {len(hypotheses)} "
        f"(identity=1 + PCA={len(pca_cands) if use_pca_seeds else 0} "
        f"+ RANSAC top-{len(ransac_top)})"
    )

    if progress_callback:
        progress_callback(65)

    # ── Шаг 6: Выбор победителя по C2M-RMSE ─────────────────────
    coarse_pct = config["registration"].get("icp_coarse_pct", 5.0)
    fine_pct   = config["registration"].get("icp_fine_pct",   1.0)
    icp_dist1  = ap["bbox_diag"] * coarse_pct / 100.0
    icp_dist2  = ap["bbox_diag"] * fine_pct   / 100.0

    best_c2m_rmse: float    = float("inf")
    best_T:        np.ndarray = hypotheses[0]

    for hi, T_h in enumerate(hypotheses):
        try:
            c2m, T_ref = _evaluate_candidate(
                pcd_down_aligned, mesh_pcd_down, scene,
                T_h, icp_dist=icp_dist1, max_iter=50,
            )
            logger.info(f"  Гипотеза {hi}: C2M-RMSE={c2m:.4f} мм")
            if c2m < best_c2m_rmse:
                best_c2m_rmse = c2m
                best_T        = T_ref
        except Exception as exc:
            logger.warning(f"  Гипотеза {hi}: ошибка оценки — {exc}")

    logger.info(f"Победитель: C2M-RMSE={best_c2m_rmse:.4f} мм")

    if progress_callback:
        progress_callback(68)

    # ── Шаг 7: Валидационный шлюз ────────────────────────────────
    reject_rmse_pct      = config["registration"].get("reject_rmse_pct", 5.0)
    reject_thresh        = ap["bbox_diag"] * reject_rmse_pct / 100.0
    registration_suspect = bool(best_c2m_rmse > reject_thresh)
    if registration_suspect:
        logger.warning(
            f"SUSPECT REGISTRATION: C2M-RMSE победителя = {best_c2m_rmse:.4f} мм "
            f"> порог {reject_thresh:.4f} мм "
            f"({reject_rmse_pct}% от bbox_diag={ap['bbox_diag']:.1f} мм). "
            "Проверьте соответствие скана и CAD-модели."
        )

    # ── Шаг 8: Финальный двухпроходный ICP (полное облако) ────────
    logger.info(
        f"Финальный ICP от уточнённой матрицы победителя: "
        f"грубый={icp_dist1:.3f} мм ({coarse_pct}%), "
        f"точный={icp_dist2:.3f} мм ({fine_pct}%)..."
    )
    r_coarse, r_fine = _icp_two_pass(
        pcd_full_aligned, mesh_pcd_full,
        best_T,
        dist1=icp_dist1,
        dist2=icp_dist2,
        max_iter=config["registration"]["icp_max_iter"],
        timeout=60,
        progress_callback=progress_callback,
        _prog_mid=76,
    )

    if progress_callback:
        progress_callback(80)

    T_coarse = r_coarse.transformation
    T_fine   = r_fine.transformation

    # ── Шаг 9: Диагностика поглощённого отклонения ───────────────
    # Движение точного прохода: T_delta = T_fine @ inv(T_coarse)
    T_delta    = T_fine @ np.linalg.inv(T_coarse)
    t_delta    = T_delta[:3, 3]
    R_delta    = T_delta[:3, :3]
    fine_pass_shift_mm = float(np.linalg.norm(t_delta))
    cos_a = float(np.clip((np.trace(R_delta) - 1.0) / 2.0, -1.0, 1.0))
    fine_pass_rot_deg  = float(np.degrees(np.arccos(cos_a)))

    # C2M-статистика при обоих выравниваниях — прореженное облако, уже готовая scene.
    # Один проход: возвращает (rmse, within_tolerance_fraction) на downsampled cloud.
    tolerance_mm = float(config.get("analysis", {}).get("tolerance_mm", 0.5))

    def _c2m_stats_down(T: np.ndarray) -> tuple[float, float]:
        pcd_tmp = copy.deepcopy(pcd_down_aligned).transform(T)
        pts     = np.asarray(pcd_tmp.points).astype(np.float32)
        query   = o3d.core.Tensor(pts, dtype=o3d.core.Dtype.Float32)
        dists   = scene.compute_distance(query).numpy()
        return (float(np.sqrt(np.mean(dists ** 2))),
                float(np.mean(dists <= tolerance_mm)))

    rmse_coarse,  within_tol_coarse  = _c2m_stats_down(T_coarse)
    rmse_bestfit, within_tol_bestfit = _c2m_stats_down(T_fine)
    absorbed             = rmse_coarse - rmse_bestfit
    absorbed_within_tol  = within_tol_bestfit - within_tol_coarse   # в долях, м.б. < 0

    logger.info(
        f"Диагностика: сдвиг точного прохода={fine_pass_shift_mm:.4f} мм, "
        f"поворот={fine_pass_rot_deg:.4f}°, "
        f"rmse_coarse={rmse_coarse:.4f} мм, rmse_bestfit={rmse_bestfit:.4f} мм, "
        f"absorbed_rmse={absorbed:.4f} мм, "
        f"within_tol_coarse={within_tol_coarse*100:.1f}%, "
        f"absorbed_within_tol={absorbed_within_tol*100:+.1f} п.п."
    )

    # ── Шаг 10: Выбор трансформации по режиму ─────────────────────
    alignment_mode = config["registration"].get("alignment_mode", "best_fit")
    if alignment_mode == "conservative":
        T_selected = T_coarse
        rmse_out   = r_coarse.inlier_rmse
        logger.info("Режим conservative: возвращаем грубое выравнивание")
    else:
        T_selected = T_fine
        rmse_out   = r_fine.inlier_rmse

    pcd_registered = pcd_full_aligned.transform(T_selected)

    # T_total: трансформация из ИСХОДНОГО pcd_full в финальное положение.
    # Сохраняет преварительный центроидный сдвиг T_centroid, без которого
    # повторное применение к свежезагруженному облаку не восстановит совмещение.
    T_total = T_selected @ T_centroid

    logger.info(
        f"Регистрация завершена (режим={alignment_mode}): "
        f"fitness={r_fine.fitness:.4f}, RMSE={rmse_out:.6f} мм"
    )
    if rmse_out > ap["bbox_diag"] * 0.05:
        logger.warning(
            f"RMSE ({rmse_out:.4f} мм) велик относительно размера модели "
            f"({ap['bbox_diag']:.1f} мм). Возможно, регистрация неточна."
        )

    reg_diagnostics = {
        "fine_pass_shift_mm":         fine_pass_shift_mm,
        "fine_pass_rot_deg":          fine_pass_rot_deg,
        "rmse_coarse":                rmse_coarse,
        "rmse_bestfit":               rmse_bestfit,
        "absorbed_deviation_mm":      absorbed,
        "within_tolerance_coarse":    within_tol_coarse,
        "within_tolerance_bestfit_down": within_tol_bestfit,
        "absorbed_within_tol_pct":    absorbed_within_tol,
        "alignment_mode":             alignment_mode,
    }

    return pcd_registered, T_total, rmse_out, registration_suspect, reg_diagnostics
