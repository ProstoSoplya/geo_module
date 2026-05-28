"""
tests/test_registration_robustness.py

Тестовая оснастка для воспроизведения и измерения бага «ложный локальный минимум»:
симметричная / Г-образная деталь сходится перевёрнутой.

Пайплайн НЕ ИЗМЕНЯЕТСЯ — только диагностика и метаморфные тесты.

Запуск standalone:
    python tests/test_registration_robustness.py

Запуск под pytest:
    pytest tests/test_registration_robustness.py -v -s
"""

import copy
import logging
import sys
import traceback
from pathlib import Path

import numpy as np
import open3d as o3d
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.algorithms.preprocessing import preprocess_pipeline
from core.algorithms.registration  import register_pipeline, RegistrationError
from core.algorithms.deviation      import compute_deviations

logging.basicConfig(level=logging.WARNING)   # убираем INFO-спам в тестах

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ══════════════════════════════════════════════════════════════════════════════
# A. Синтетическая геометрия
# ══════════════════════════════════════════════════════════════════════════════

def make_L_shape() -> o3d.geometry.TriangleMesh:
    """
    Г-образная деталь из двух прямоугольных блоков (создаётся без булевых операций).

    Длинная рука : 100 × 30 × 20 мм (x=[0,100], y=[0,30], z=[0,20])
    Короткая рука: 30  × 30 × 40 мм на ПРАВОМ конце длинной (x=[70,100], z=[20,60])

    Ось 180°-неоднозначности: Y.
    Поворот вокруг Y на 180° ставит короткую руку на ЛЕВЫЙ конец (x=[0,30]) —
    зеркальное Г, неотличимое по FPFH-дескрипторам плоских граней.
    Именно здесь слабый RANSAC (1 старт, мало итераций) часто сходится в
    ложный минимум, а ICP его не покидает.

    Примечание: mesh = arm1 + arm2 содержит внутреннюю грань (z=20, x=[70,100]).
    Это не мешает регистрации и C2M-метрике, но видно в wireframe-режиме.
    """
    arm1 = o3d.geometry.TriangleMesh.create_box(100.0, 30.0, 20.0)
    arm2 = o3d.geometry.TriangleMesh.create_box(30.0,  30.0, 40.0)
    arm2.translate([70.0, 0.0, 20.0])
    mesh = arm1 + arm2
    mesh.compute_vertex_normals()
    mesh.compute_triangle_normals()
    return mesh


def sample_scan(mesh:      o3d.geometry.TriangleMesh,
                n_points:  int,
                noise_std: float = 0.0,
                seed:      int   = 42) -> o3d.geometry.PointCloud:
    """Равномерная передискретизация поверхности меша + опциональный гауссов шум."""
    try:
        pcd = mesh.sample_points_uniformly(n_points, seed=seed)
    except TypeError:
        pcd = mesh.sample_points_uniformly(n_points)   # old Open3D without seed
    if noise_std > 0.0:
        rng = np.random.default_rng(seed)
        pts = np.asarray(pcd.points)
        pts += rng.normal(0.0, noise_std, pts.shape)
        pcd.points = o3d.utility.Vector3dVector(pts)
    return pcd


def make_transform(angle_deg: float, axis, t) -> np.ndarray:
    """4×4 матрица жёсткого преобразования: поворот axis-angle (angle_deg) + сдвиг t."""
    ax = np.asarray(axis, dtype=np.float64)
    ax /= np.linalg.norm(ax)
    a = np.deg2rad(angle_deg)
    c, s   = np.cos(a), np.sin(a)
    x, y, z = ax
    R = np.array([
        [c + x*x*(1-c),     x*y*(1-c) - z*s,  x*z*(1-c) + y*s],
        [y*x*(1-c) + z*s,   c + y*y*(1-c),    y*z*(1-c) - x*s],
        [z*x*(1-c) - y*s,   z*y*(1-c) + x*s,  c + z*z*(1-c)  ],
    ])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3,  3] = np.asarray(t, dtype=np.float64)
    return T


def apply_transform(pcd: o3d.geometry.PointCloud,
                    R:   np.ndarray,
                    t:   np.ndarray) -> o3d.geometry.PointCloud:
    """Возвращает новое облако: pts' = R @ pts + t."""
    pts = np.asarray(pcd.points)
    new_pcd = o3d.geometry.PointCloud()
    new_pcd.points = o3d.utility.Vector3dVector((R @ pts.T).T + t)
    return new_pcd


# ══════════════════════════════════════════════════════════════════════════════
# B. Метрики
# ══════════════════════════════════════════════════════════════════════════════

def final_c2m_rmse(mesh:           o3d.geometry.TriangleMesh,
                   pcd_registered: o3d.geometry.PointCloud) -> float:
    """
    Cloud-to-Mesh RMSE по ВСЕМУ облаку через compute_deviations.

    Ключевая метрика:
      - корректная регистрация  → RMSE ≈ 0 (точки лежат на поверхности меша)
      - ложный минимум (180°)   → RMSE >> 0 (точки систематически смещены)
    """
    devs, _ = compute_deviations(pcd_registered, mesh)
    return float(np.sqrt(np.mean(devs ** 2)))


def pose_error(T_est: np.ndarray, T_gt: np.ndarray) -> tuple:
    """
    Возвращает (angle_deg, t_norm_mm).

    angle_deg — угол ошибки поворота (градусы), вычислен из R_rel = R_est @ R_gt^T.
    t_norm_mm — норма ошибки сдвига (мм).
    """
    R_rel  = T_est[:3, :3] @ T_gt[:3, :3].T
    cos_a  = np.clip((np.trace(R_rel) - 1.0) / 2.0, -1.0, 1.0)
    angle  = float(np.degrees(np.arccos(cos_a)))
    t_err  = float(np.linalg.norm(T_est[:3, 3] - T_gt[:3, 3]))
    return angle, t_err


# ══════════════════════════════════════════════════════════════════════════════
# Конфигурации (без изменений в пайплайне)
# ══════════════════════════════════════════════════════════════════════════════

# Нормальная конфигурация — соответствует продакшн-дефолтам из config.json.
_NORMAL_CONFIG: dict = {
    "preprocessing": {
        "sor_neighbors": 20,
        "sor_std_ratio":  2.0,
        "voxel_size":    -1,     # автоопределение: 1.5% диагонали bbox скана
    },
    "registration": {
        "ransac_max_iter": 200_000,
        "ransac_n_starts": 6,
        "icp_max_iter":    200,
        "icp_coarse_pct":  3.5,
        "icp_fine_pct":    1.3,
    },
}

# Конфигурация-провокатор: одиночный слабый RANSAC.
# Воспроизводит ситуацию, при которой ложный 180°-минимум не устраняется:
#   - 1 старт вместо 6   → нет мультистарта, который мог бы найти правильную позу
#   - 20 000 итераций вместо 200 000 → слишком мало для надёжного поиска
# На Г-образной детали этого достаточно для регулярных провалов.
_BUGGY_CONFIG: dict = {
    "preprocessing": {
        "sor_neighbors": 20,
        "sor_std_ratio":  2.0,
        "voxel_size":    -1,
    },
    "registration": {
        "ransac_max_iter": 20_000,   # в 10× меньше
        "ransac_n_starts": 1,         # единственная попытка
        "icp_max_iter":    50,
        "icp_coarse_pct":  3.5,
        "icp_fine_pct":    1.3,
    },
}


def _run_pipeline(pcd:    o3d.geometry.PointCloud,
                  mesh:   o3d.geometry.TriangleMesh,
                  config: dict) -> tuple:
    """
    Минимальный пайплайн: preprocess_pipeline → register_pipeline.
    Возвращает (pcd_registered, T_estimated, icp_rmse).
    """
    pcd_clean, pcd_down, voxel_size = preprocess_pipeline(pcd, config)
    pcd_reg, T_est, icp_rmse, _suspect, _reg_diag = register_pipeline(
        pcd_clean, pcd_down, mesh, config,
        pcd_voxel_size=voxel_size,
    )
    return pcd_reg, T_est, icp_rmse


# ══════════════════════════════════════════════════════════════════════════════
# E. Артефакты для GUI-демонстрации (tests/fixtures/)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_fixtures(force: bool = False):
    """
    Сохраняет три файла в tests/fixtures/:
      L_shape.stl       — CAD-модель для загрузки в GUI
      scan_correct.ply  — скан в правильной позе  (ground truth = identity)
      scan_flipped.ply  — скан, повёрнутый на 180° вокруг Y (поза ложного минимума)

    Загрузить в приложение:
      CAD   ← L_shape.stl
      Скан  ← scan_flipped.ply
    Запустить анализ со слабыми настройками RANSAC → наблюдать ложный минимум.
    """
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    stl_path  = FIXTURES_DIR / "L_shape.stl"
    ply_corr  = FIXTURES_DIR / "scan_correct.ply"
    ply_flip  = FIXTURES_DIR / "scan_flipped.ply"

    if not force and stl_path.exists() and ply_corr.exists() and ply_flip.exists():
        return str(stl_path), str(ply_corr), str(ply_flip)

    mesh = make_L_shape()
    o3d.io.write_triangle_mesh(str(stl_path), mesh)

    pcd_correct = sample_scan(mesh, 10_000, noise_std=0.2, seed=42)
    o3d.io.write_point_cloud(str(ply_corr), pcd_correct)

    centroid = np.asarray(mesh.get_axis_aligned_bounding_box().get_center())
    T_flip   = make_transform(180.0, [0, 1, 0], [0, 0, 0])
    R_flip   = T_flip[:3, :3]
    pts_c    = np.asarray(pcd_correct.points) - centroid
    pts_flip = (R_flip @ pts_c.T).T + centroid
    pcd_flip = o3d.geometry.PointCloud()
    pcd_flip.points = o3d.utility.Vector3dVector(pts_flip)
    o3d.io.write_point_cloud(str(ply_flip), pcd_flip)

    return str(stl_path), str(ply_corr), str(ply_flip)


# ══════════════════════════════════════════════════════════════════════════════
# C. Метаморфный тест
# ══════════════════════════════════════════════════════════════════════════════

def test_zero_deviation_identity():
    """
    Метаморфный тест: скан = точная передискретизация меша.

    Истинное отклонение равно нулю. Пайплайн с нормальными настройками
    должен вернуть C2M-RMSE < eps = bbox_diag × 1e-3 и ошибку позы < 10°.

    Начальная дезориентация (10° вокруг Y, 5 мм сдвиг) — типичная
    ситуация при реальном сканировании.
    """
    np.random.seed(0)

    mesh     = make_L_shape()
    bbox_ext = np.asarray(mesh.get_axis_aligned_bounding_box().get_extent())
    bbox_diag = float(np.linalg.norm(bbox_ext))
    eps = bbox_diag * 1e-3   # ~0.12 мм при диаге ~120 мм

    # Точная передискретизация + небольшая начальная дезориентация
    pcd_gt   = sample_scan(mesh, 5_000, noise_std=0.0, seed=0)
    T_init   = make_transform(10.0, [0, 1, 0], [5.0, 0.0, 0.0])
    pcd_scan = apply_transform(pcd_gt, T_init[:3, :3], T_init[:3, 3])

    pcd_reg, T_est, icp_rmse = _run_pipeline(pcd_scan, mesh, _NORMAL_CONFIG)
    rmse = final_c2m_rmse(mesh, pcd_reg)

    # Ground truth: transform, обратный начальному смещению
    T_gt_inv = np.linalg.inv(T_init)
    angle_err, t_err = pose_error(T_est, T_gt_inv)

    print(f"\n[C metamorphic]  bbox_diag={bbox_diag:.1f} мм  eps={eps:.4f} мм")
    print(f"  C2M RMSE    = {rmse:.6f} мм  (порог < {eps:.4f} мм)")
    print(f"  ICP RMSE    = {icp_rmse:.6f} мм")
    print(f"  pose_angle  = {angle_err:.2f}°   pose_t = {t_err:.3f} мм")

    assert rmse < eps, (
        f"C2M RMSE={rmse:.4f} мм > eps={eps:.4f} мм — "
        "пайплайн не сошёлся на точном скане"
    )
    assert angle_err < 10.0, (
        f"Ошибка позы {angle_err:.1f}° > 10° — деталь перевёрнута"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. Тест-провокатор
# ══════════════════════════════════════════════════════════════════════════════

_N_RUNS            = 10
_FAIL_RMSE_PCT     = 0.05   # > 5% bbox_diag = явно неверная регистрация
_FAIL_ANGLE_DEG    = 90.0   # > 90° от правильной позы = перевёрнуто


def test_false_minimum_Lshape():
    """
    Тест-провокатор: 0/10 провалов после фикса (PCA-гипотезы + выбор по C2M-RMSE).

    Сценарий:
      Скан Г-детали стартует из позы 180°-поворота вокруг Y-оси (относительно
      центроида). Раньше слабый RANSAC сваливался в ложный минимум.
      После фикса: PCA-кандидат правильной ориентации всегда попадает в пул,
      C2M-RMSE выбирает его победителем → 0 провалов из 10.
    """
    np.random.seed(0)

    mesh      = make_L_shape()
    bbox_ext  = np.asarray(mesh.get_axis_aligned_bounding_box().get_extent())
    bbox_diag = float(np.linalg.norm(bbox_ext))
    fail_thresh = bbox_diag * _FAIL_RMSE_PCT

    # Центроид меша — вокруг него применяем 180°-поворот
    centroid = np.asarray(mesh.get_axis_aligned_bounding_box().get_center())

    # Скан в правильной позе (ground truth = identity), с реалистичным шумом
    pcd_gt = sample_scan(mesh, 5_000, noise_std=0.5, seed=1)

    # Перевёрнутая поза: 180° вокруг Y относительно центроида
    T_flip  = make_transform(180.0, [0, 1, 0], [0, 0, 0])
    R_flip  = T_flip[:3, :3]
    pts_c   = np.asarray(pcd_gt.points) - centroid
    pts_f   = (R_flip @ pts_c.T).T + centroid
    pcd_flipped = o3d.geometry.PointCloud()
    pcd_flipped.points = o3d.utility.Vector3dVector(pts_f)

    # Ground truth: pipeline должен применить R_flip вокруг centroid, чтобы
    # вернуть скан в исходное положение (R_flip^{-1} = R_flip для 180°).
    T_gt = np.eye(4)
    T_gt[:3, :3] = R_flip
    T_gt[:3,  3] = centroid - R_flip @ centroid   # перевод при повороте вокруг centroid

    failures  = 0
    rmse_log  = []
    angle_log = []

    print(f"\n[D provocation]  bbox_diag={bbox_diag:.1f} мм  "
          f"fail_thresh={fail_thresh:.1f} мм  N={_N_RUNS}")
    print(f"  config: RANSAC n_starts=1, max_iter=20 000 (слабый) + PCA-гипотезы (фикс)")

    for i in range(_N_RUNS):
        try:
            pcd_reg, T_est, _ = _run_pipeline(pcd_flipped, mesh, _BUGGY_CONFIG)
            rmse      = final_c2m_rmse(mesh, pcd_reg)
            angle_err, t_err = pose_error(T_est, T_gt)
        except (RegistrationError, TimeoutError, Exception) as exc:
            print(f"  [{i+1:02d}/{_N_RUNS}] ОШИБКА пайплайна: {exc}")
            failures += 1
            rmse_log.append(float("inf"))
            angle_log.append(180.0)
            continue

        failed = (rmse > fail_thresh) or (angle_err > _FAIL_ANGLE_DEG)
        if failed:
            failures += 1
        rmse_log.append(rmse)
        angle_log.append(angle_err)

        marker = "FAIL [LOZHNYJ MINIMUM]" if failed else "ok"
        print(f"  [{i+1:02d}/{_N_RUNS}]  "
              f"C2M RMSE={rmse:6.2f} mm  angle={angle_err:6.1f} deg  -> {marker}")

    finite_rmse = [r for r in rmse_log if r != float("inf")]
    mean_r = float(np.mean(finite_rmse)) if finite_rmse else float("inf")
    std_r  = float(np.std(finite_rmse))  if finite_rmse else 0.0

    print(f"\n  failures: {failures}/{_N_RUNS}")
    print(f"  C2M RMSE: среднее={mean_r:.2f} +- {std_r:.2f} mm  "
          f"(bbox_diag={bbox_diag:.1f} mm, порог={fail_thresh:.1f} mm)")
    print(f"  pose_angle: среднее={float(np.mean(angle_log)):.1f} deg")

    assert failures == 0, (
        f"{failures}/{_N_RUNS} запусков нашли ложный 180-минимум "
        f"(C2M RMSE > {fail_thresh:.1f} mm или pose_angle > {_FAIL_ANGLE_DEG} deg)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. Стабильность на 5 seed-ах (метаморфный × 5)
# ══════════════════════════════════════════════════════════════════════════════

def test_stability_5seeds():
    """
    Тест C повторяется с 5 разными seed-ами выборки скана.
    Все 5 должны пройти после фикса: пул гипотез детерминированно
    покрывает правильную ориентацию независимо от случайности RANSAC.
    """
    mesh      = make_L_shape()
    bbox_ext  = np.asarray(mesh.get_axis_aligned_bounding_box().get_extent())
    bbox_diag = float(np.linalg.norm(bbox_ext))
    eps       = bbox_diag * 1e-3

    T_init   = make_transform(10.0, [0, 1, 0], [5.0, 0.0, 0.0])
    T_gt_inv = np.linalg.inv(T_init)

    failures = []
    print(f"\n[E stability 5 seeds]  bbox_diag={bbox_diag:.1f} mm  eps={eps:.4f} mm")

    for seed in range(5):
        np.random.seed(seed)
        pcd_gt   = sample_scan(mesh, 5_000, noise_std=0.0, seed=seed)
        pcd_scan = apply_transform(pcd_gt, T_init[:3, :3], T_init[:3, 3])

        pcd_reg, T_est, icp_rmse = _run_pipeline(pcd_scan, mesh, _NORMAL_CONFIG)
        rmse      = final_c2m_rmse(mesh, pcd_reg)
        angle_err, _ = pose_error(T_est, T_gt_inv)

        passed = (rmse < eps) and (angle_err < 10.0)
        marker = "PASS" if passed else "FAIL"
        print(f"  seed={seed}: C2M RMSE={rmse:.6f} mm  angle={angle_err:.2f} deg  -> {marker}")

        if not passed:
            failures.append(seed)

    assert len(failures) == 0, (
        f"seed(s) {failures} failed: C2M RMSE >= {eps:.4f} mm or angle >= 10 deg"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("Генерация fixture-файлов (tests/fixtures/)...")
    stl, ply_c, ply_f = _generate_fixtures(force=True)
    print(f"  CAD:           {stl}")
    print(f"  Скан (верно):  {ply_c}")
    print(f"  Скан (180°):   {ply_f}")
    print("  Для демонстрации бага: загрузить в GUI L_shape.stl + scan_flipped.ply,")
    print("  запустить анализ — регистрация должна перевернуть деталь.")

    print()
    print("=" * 70)
    print("Тест C: Метаморфный (нулевое отклонение на точном скане)...")
    try:
        test_zero_deviation_identity()
        print("  ИТОГ: PASS")
    except AssertionError as e:
        print(f"  ИТОГ: FAIL  {e}")
        traceback.print_exc()

    print()
    print("=" * 70)
    print(f"Тест D: Провокатор (180-поворот, {_N_RUNS} запусков, BUGGY config + PCA)...")
    try:
        test_false_minimum_Lshape()
        print("  ИТОГ: PASS (0 провалов)")
    except AssertionError as e:
        print(f"  ИТОГ: FAIL  {e}")

    print()
    print("=" * 70)
    print("Тест E: Стабильность на 5 seed-ах...")
    try:
        test_stability_5seeds()
        print("  ИТОГ: PASS")
    except AssertionError as e:
        print(f"  ИТОГ: FAIL  {e}")

    print()
    print("=" * 70)
    sys.exit(0)
