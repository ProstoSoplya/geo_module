"""
dimensions.py — Вычисление габаритных размеров CAD-модели и скана.

Все результаты в мм (предполагается, что геометрия уже приведена
к мм в project_manager.load_cad / load_scan).

Общая система отсчёта — ориентированный bounding box (OBB) CAD-меша:
  - obb.center: центр OBB в мировых координатах
  - obb.R:      матрица поворота (столбцы = локальные оси в мировых коорд.)
Проекция в OBB-фрейм:  p_local = (p - center) @ R
Тогда AABB в этом фрейме даёт Lx, Ly, Lz вдоль одних осей для CAD и скана,
и ΔL = scan_extent − cad_extent приобретает геометрический смысл.
"""

import logging
import numpy as np
import open3d as o3d

logger = logging.getLogger(__name__)

# Известные коэффициенты единиц и подсказки для диалога о несоответствии масштабов.
# Ключ — ожидаемое отношение диагоналей; значение — текст подсказки.
UNIT_HINT_RATIOS: list[tuple[float, str]] = [
    (10.0,   "возможно, один файл в см, другой в мм"),
    (25.4,   "возможно, один файл в дюймах, другой в мм"),
    (100.0,  "возможно, один файл в м, другой в см"),
    (1000.0, "возможно, один файл в м, другой в мм"),
]


def suggest_unit_mismatch_hint(ratio: float, tol: float = 0.15) -> str:
    """
    По наблюдаемому отношению диагоналей возвращает текстовую подсказку
    о вероятной причине расхождения, или '' если ничего не подходит.
    tol — допустимое относительное отклонение от известного коэффициента.
    """
    for known, hint in UNIT_HINT_RATIOS:
        if abs(ratio / known - 1.0) <= tol:
            return hint
    return ""


def bbox_summary(
    geom: o3d.geometry.TriangleMesh | o3d.geometry.PointCloud,
) -> tuple[tuple[float, float, float], float]:
    """
    Быстрый AABB-габарит одного объекта.
    Возвращает ((Lx, Ly, Lz), diagonal) в единицах геометрии (мм после масштаба).
    Использует простой AABB — быстро и устойчиво, подходит для лога после загрузки.
    """
    bbox = geom.get_axis_aligned_bounding_box()
    ext = np.asarray(bbox.get_extent(), dtype=np.float64)
    diag = float(np.linalg.norm(ext))
    return (float(ext[0]), float(ext[1]), float(ext[2])), diag


def compute_dimensions(
    mesh: o3d.geometry.TriangleMesh,
    pcd_registered: o3d.geometry.PointCloud | None = None,
) -> dict:
    """
    Вычисляет габаритные размеры CAD-модели и (опционально) скана
    в единой системе отсчёта — OBB CAD-меша.

    Алгоритм:
        1. Вычисляем OBB меша (obb.center, obb.R).
        2. Проецируем вершины меша и точки скана в OBB-фрейм:
               p_local = (p - center) @ R
        3. Берём AABB-экстенты в этом фрейме → Lx, Ly, Lz одинаково
           ориентированы для обоих наборов.
        4. ΔL = scan_extent − cad_extent.

    При ошибке OBB (вырожденный меш) — откат к AABB, экстенты
    сортируются по убыванию (наибольший с наибольшим).

    Аргументы:
        mesh            — CAD-меш (уже в мм)
        pcd_registered  — зарегистрированное облако (уже в мм); None → только CAD

    Возвращает:
        {
          "cad":       (Lx, Ly, Lz),          # float, мм
          "scan":      (Lx, Ly, Lz) | None,
          "delta":     (dLx, dLy, dLz) | None,
          "cad_diag":  float,                  # мм
          "scan_diag": float | None,
        }
    """
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    if len(verts) == 0:
        logger.warning("compute_dimensions: меш пустой, возвращаем нули")
        return {
            "cad": (0.0, 0.0, 0.0), "scan": None,
            "delta": None, "cad_diag": 0.0, "scan_diag": None,
        }

    use_obb = True
    try:
        obb = mesh.get_oriented_bounding_box()
        center = np.asarray(obb.center, dtype=np.float64)
        R      = np.asarray(obb.R,      dtype=np.float64)   # (3,3)
        # Проверяем невырожденность R
        if abs(np.linalg.det(R)) < 0.5:
            use_obb = False
    except Exception as exc:
        logger.warning("OBB не вычислен (%s), откат к AABB", exc)
        use_obb = False

    if use_obb:
        verts_local = (verts - center) @ R
        cad_extent  = verts_local.max(axis=0) - verts_local.min(axis=0)
    else:
        # Откат: AABB с сортировкой по убыванию
        raw = np.asarray(mesh.get_axis_aligned_bounding_box().get_extent(), dtype=np.float64)
        cad_extent = np.sort(raw)[::-1]

    cad_diag = float(np.linalg.norm(cad_extent))
    cad_t    = (float(cad_extent[0]), float(cad_extent[1]), float(cad_extent[2]))

    scan_t    = None
    scan_diag = None
    delta_t   = None

    if pcd_registered is not None and len(pcd_registered.points) > 0:
        pts = np.asarray(pcd_registered.points, dtype=np.float64)
        if use_obb:
            pts_local    = (pts - center) @ R
            scan_extent  = pts_local.max(axis=0) - pts_local.min(axis=0)
        else:
            raw_s        = np.asarray(
                pcd_registered.get_axis_aligned_bounding_box().get_extent(), dtype=np.float64
            )
            scan_extent  = np.sort(raw_s)[::-1]

        scan_diag = float(np.linalg.norm(scan_extent))
        scan_t    = (float(scan_extent[0]), float(scan_extent[1]), float(scan_extent[2]))
        delta     = scan_extent - cad_extent
        delta_t   = (float(delta[0]), float(delta[1]), float(delta[2]))

    return {
        "cad":       cad_t,
        "scan":      scan_t,
        "delta":     delta_t,
        "cad_diag":  cad_diag,
        "scan_diag": scan_diag,
    }
