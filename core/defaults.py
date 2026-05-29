"""
defaults.py — Параметры алгоритмов по умолчанию (базовый режим).

Единый источник истины для дефолтных значений preprocessing и registration.
Используется в main.py (загрузка конфига) и worker.py (изоляция базового режима).
"""

BASIC_DEFAULTS = {
    "preprocessing": {
        "sor_neighbors": 20,
        "sor_std_ratio": 2.0,
        "voxel_size": 0,
    },
    "registration": {
        "ransac_max_iter": 200000,
        "ransac_n_starts": 5,
        "ransac_top_k": 4,
        "icp_coarse_pct": 5.0,
        "icp_fine_pct": 1.0,
        "icp_max_iter": 150,
        "use_pca_seeds": True,
        "reject_rmse_pct": 5.0,
        "alignment_mode": "best_fit",
    },
}
