# ОТЧЁТ О РЕАЛИЗАЦИИ — МОДУЛЬ АНАЛИЗА ОТКЛОНЕНИЙ ГЕОМЕТРИИ ДЕТАЛЕЙ

> Актуализирован по состоянию кода на HEAD коммита (ветка `master`).  
> Предыдущий отчёт устарел после серии доработок Q1–Q5.

---

## §1. ОБЩАЯ АРХИТЕКТУРА

### 1.1 Дерево файлов

```
C:\module\
├── main.py                            # точка входа, QSS, load_config, _deep_merge
├── config.json                        # пользовательские параметры (перекрывают дефолты)
├── app.log                            # файл лога (создаётся при запуске)
│
├── core/
│   ├── project_manager.py             # ProjectManager: состояние сессии, I/O
│   ├── worker.py                      # AnalysisWorker(QThread): фоновый пайплайн
│   └── algorithms/
│       ├── preprocessing.py           # SOR + Voxel Grid
│       ├── registration.py            # PCA + RANSAC + ICP, возврат 5-tuple
│       ├── deviation.py               # C2M, signed distance, статистика, раскраска
│       ├── dimensions.py              # габаритные размеры (OBB/AABB)
│       └── report.py                  # 3-страничный PDF (reportlab + matplotlib)
│
├── ui/
│   ├── main_window.py                 # MainWindow: меню, тулбар, drag&drop, слоты
│   ├── panels.py                      # ControlPanel, ResultsPanel, LogPanel
│   ├── viewer_widget.py               # ViewerWidget (PyVista/VTK)
│   └── help_dialog.py                 # HelpDialog, AboutDialog
│
└── tests/
    ├── __init__.py
    ├── test_registration_robustness.py # тест на ложный 180°-минимум
    ├── test_q5_integration.py          # интеграционный тест Q5-выходных данных
    └── fixtures/
        ├── L_shape.stl                 # CAD Г-образной детали (100×30×20 + 30×30×40 мм)
        ├── scan_correct.ply            # скан в правильной позе
        └── scan_flipped.ply            # скан, повёрнутый на 180° вокруг Y
```

### 1.2 Компоненты и поток данных

```
main.py
  └─ load_config()         → dict (глубокое слияние defaults + config.json)
  └─ MainWindow(config)
        │
        ├─ ProjectManager(config)   хранит: mesh, pcd, pcd_colored, deviations,
        │                           ambiguous_mask, transformation, stats, results,
        │                           unit_cad, unit_scan, cad_path, scan_path
        │
        ├─ ControlPanel             param_changed(list, object) →
        │                           MainWindow._on_param_changed →
        │                           ProjectManager.update_config()
        │
        ├─ ResultsPanel             update_results(stats) / reset()
        │
        ├─ ViewerWidget             load_mesh_preview(mesh) / load_results(...)
        │
        └─ LogPanel                 append(str) / cancel_requested →
                                    MainWindow.cancel_analysis()

MainWindow.run_analysis()
  └─ AnalysisWorker(pcd, mesh, config).start()
        │  (QThread — фоновый поток)
        ├─ progress_changed(int)    → progress_bar.setValue()
        ├─ stage_changed(str)       → _stage_label.setText()
        ├─ log_message(str)         → LogPanel.append()
        ├─ analysis_finished(dict)  → MainWindow._on_analysis_finished()
        │       └─ ProjectManager.save_results(results)
        │       └─ ResultsPanel.update_results(stats)
        │       └─ ViewerWidget.load_results(...)
        └─ analysis_error(str)      → MainWindow._on_analysis_error()
```

### 1.3 Сигналы AnalysisWorker

| Сигнал | Тип аргумента | Назначение |
|---|---|---|
| `progress_changed` | `int` (0–100) | обновление прогресс-бара |
| `stage_changed` | `str` | текст текущего этапа в статусбаре |
| `log_message` | `str` | сообщение в лог-панель |
| `analysis_finished` | `dict` | словарь результатов (см. §1.4) |
| `analysis_error` | `str` | текст ошибки |

Все сигналы подключаются через `Qt.ConnectionType.QueuedConnection`
(cross-thread, `worker.py:477`).

### 1.4 Пайплайн анализа (AnalysisWorker._run_pipeline)

| Прогресс | Этап | Вызов |
|---|---|---|
| 0–25 % | Предобработка (SOR + Voxel) | `preprocess_pipeline()` |
| 35–65 % | Грубое совмещение (RANSAC) | `register_pipeline()` внутри |
| 65–80 % | Точный ICP (два прохода) | `register_pipeline()` внутри |
| 80–97 % | Расчёт отклонений и статистики | `compute_deviations()` + `compute_statistics()` |
| 97–100 % | Раскраска облака | `colorize_point_cloud()` |

Текст этапа переключается автоматически по порогам (`worker.py:38–41`):

```python
_STAGE_THRESHOLDS = [
    (80, "Этап 4/4: Расчёт отклонений..."),
    (65, "Этап 3/4: Точное совмещение (ICP)..."),
    (35, "Этап 2/4: Грубое совмещение (RANSAC)..."),
]
```

**Словарь results** (`analysis_finished` → `ProjectManager.save_results`):

```python
results = {
    "pcd_registered": o3d.geometry.PointCloud,   # зарегистрированное облако
    "pcd_colored":    o3d.geometry.PointCloud,   # раскрашенное по отклонениям
    "deviations":     np.ndarray (float64, N),   # знаковые отклонения, мм
    "ambiguous_mask": np.ndarray (bool, N),       # маска неоднозначного знака
    "stats":          dict,                       # все метрики (см. §2.3)
    "transform":      np.ndarray (4×4),           # итоговая матрица регистрации
}
```

---

## §2. АЛГОРИТМЫ

### 2.1 preprocessing.py

#### `remove_outliers(pcd, nb_neighbors=20, std_ratio=2.0)`
**Строки: 18–60**

Statistical Outlier Removal (SOR). Для каждой точки ищет `nb_neighbors`
ближайших соседей, вычисляет среднее расстояние. Точки, у которых оно
отличается от общего среднего более чем на `std_ratio × σ`, удаляются.

Защита: если точек < 10 — фильтрация пропускается. Предупреждение если
осталось < 100 точек.

**Параметры:** `pcd` — входное облако, `nb_neighbors` — соседей (больше =
медленнее, мягче), `std_ratio` — порог (меньше = строже).  
**Возврат:** очищенное облако.

#### `voxel_downsample(pcd, voxel_size=0.1)`
**Строки: 63–95**

Voxel Grid Downsampling. Пространство делится на кубики со стороной
`voxel_size`. В каждом кубике оставляется один центроид. Если результат
пустой — возвращается исходное облако с предупреждением.

#### `preprocess_pipeline(pcd, config, progress_callback=None)`
**Строки: 98–146**

Последовательно: SOR → Voxel Grid.

Авторасчёт `voxel_size` (если `config["preprocessing"]["voxel_size"] <= 0`):

```python
bbox_diag = np.linalg.norm(pcd.get_axis_aligned_bounding_box().get_extent())
voxel_size = bbox_diag * 0.015   # 1.5% от диагонали bbox облака
```

Нормали **не вычисляются** — registration.py пересчитает их под масштаб модели.

**Возврат:** `(pcd_full_clean, pcd_down, voxel_size)` — полное очищенное,
прореженное, и фактически использованный размер вокселя (передаётся в
`register_pipeline` для оценки совместимости).

Прогресс: 15 % (после SOR), 25 % (после Voxel Grid).

---

### 2.2 registration.py

Пайплайн защиты от ложного 180°-минимума.

#### `_compute_adaptive_params(mesh)` — строки 32–54

Вычисляет пороги из bbox-диагонали меша (инвариантен к масштабу):

```python
bbox_diag = np.linalg.norm(mesh.get_axis_aligned_bounding_box().get_extent())
params = {
    "voxel_size":      bbox_diag * 0.02,
    "fpfh_radius":     bbox_diag * 0.05,
    "ransac_distance": bbox_diag * 0.03,
    "bbox_diag":       bbox_diag,
}
```

#### `_prepare_clouds(pcd_full, pcd_down, mesh, ap, ...)` — строки 57–94

Прореживает меш (`sample_points_uniformly`), вычисляет нормали для облаков.
Для `pcd_down` применяется `orient_normals_consistent_tangent_plane(k=15)`.
Сэмплинг меша: `max(len(pcd_full), 50000)` точек для `mesh_pcd_full`,
`max(len(pcd_down), 20000)` для `mesh_pcd_down`.

Прогресс: 35–45 % (3 шага).

#### `_compute_fpfh(pcd, radius)` — строки 97–102

Fast Point Feature Histograms. `max_nn=100`.

#### `pca_alignment_candidates(pcd_pts, mesh_pts)` — строки 105–139

Возвращает **4 матрицы 4×4** — PCA-гипотезы совмещения.

Алгоритм:
1. Для каждого набора точек: `c = mean`, `V = eigenvecs(cov)` (сортировка по убыванию λ).
2. 4 знаковые комбинации `S = diag(s1, s2, s3)` с det(R)=+1:

```python
target_det_S = det(V_mesh) * det(V_pcd)   # = ±1
for s1 in (+1, -1):
    for s2 in (+1, -1):
        s3 = target_det_S * s1 * s2
        R  = V_mesh @ diag(s1,s2,s3) @ V_pcd.T
        t  = c_mesh - R @ c_pcd
        T  = [[R, t], [0,0,0,1]]
```

Покрывает 180°-неоднозначность осей.

#### `_ransac_multistart(...)` — строки 142–188

**Параметры:**
- `ransac_dist` = `bbox_diag * 0.03` (адаптивный)
- `ransac_max_iter` — из конфига
- `n_starts` — из конфига (`ransac_n_starts`)
- `top_k` — из конфига (`ransac_top_k`)

Алгоритм: запускает RANSAC `n_starts` раз, сортирует по `fitness` (убывание),
возвращает `top_k` лучших. Каждый запуск: `mutual_filter=True`, `ransac_n=3`,
чекеры EdgeLength(0.9) + Distance. Конвергенция: `RANSACConvergenceCriteria(max_iter, 0.9999)`.

Прогресс: 52–65 % (равномерно по n_starts).

#### `_evaluate_candidate(pcd_down_aligned, mesh_pcd_down, scene, T_init, icp_dist, max_iter=50)` — строки 191–220

Быстрый ICP (50 итераций) + C2M-RMSE через **готовую** `RaycastingScene` (BVH
строится 1 раз и переиспользуется всеми кандидатами).

```python
pcd_tmp  = deepcopy(pcd_down_aligned).transform(T_init)
r        = registration_icp(pcd_tmp, mesh_pcd_down, ...)
T_refined = r.transformation @ T_init           # T: pcd_down_aligned → совмещение

pcd_eval = deepcopy(pcd_down_aligned).transform(T_refined)
dists    = scene.compute_distance(tensor(pcd_eval.points))
c2m_rmse = sqrt(mean(dists²))
```

**Возврат:** `(c2m_rmse, T_refined)`.

#### `_icp_with_timeout(pcd, mesh_pcd, dist, init_T, criteria, timeout=60)` — строки 223–243

ICP с таймаутом через `ThreadPoolExecutor`. Если ICP не сходится за 60 с —
бросает `TimeoutError`.

#### `_icp_two_pass(pcd, mesh_pcd, init_T, dist1, dist2, max_iter=150, ...)` — строки 246–277

Два прохода ICP от уточнённой матрицы победителя:
- **Проход 1** (грубый): `dist1 = bbox_diag * icp_coarse_pct / 100`, `max_iteration=80` (hardcoded)
- **Проход 2** (точный): `dist2 = bbox_diag * icp_fine_pct / 100`, `max_iteration=config["icp_max_iter"]`, `relative_fitness=1e-6`, `relative_rmse=1e-6`

Прогресс: до 76 % (после прохода 1).

**Возврат:** `(r1, r2)` — оба результата нужны для диагностики поглощённого отклонения.

#### `register_pipeline(pcd_full, pcd_down, mesh, config, progress_callback, pcd_voxel_size)` — строки 284–540

**Возврат:** `(pcd_registered, T_selected, rmse_out, registration_suspect, reg_diagnostics)` — 5-tuple.

Полный пайплайн (10 шагов):

| Шаг | Действие | Прогресс |
|---|---|---|
| 1 | `_compute_adaptive_params(mesh)` | — |
| 2 | Решение о переиспользовании `pcd_down` (если разница вокселей ≤ 20 %) | — |
| 3 | `_prepare_clouds(...)` — нормали, ориентация | 35–45 % |
| 4 | Центроидное предвыравнивание: `T_centroid[:3,3] = c_mesh - c_pcd` | 45 % |
| 5 | `_compute_fpfh(...)` для pcd и mesh | 52 % |
| 6 | Сборка пула гипотез: `[identity] + PCA(4) + RANSAC_top_k` | 52–65 % |
| 7 | BVH-сцена строится **1 раз**: `RaycastingScene.add_triangles(mesh_t)` | — |
| 8 | `_evaluate_candidate` для каждой гипотезы → выбор победителя по min C2M-RMSE | 65–68 % |
| 9 | Валидационный шлюз: `registration_suspect = (best_c2m_rmse > bbox_diag * reject_rmse_pct / 100)` | 68 % |
| 10 | `_icp_two_pass(pcd_full_aligned, ...)` от T_refined победителя | 68–80 % |
| + | Диагностика поглощённого отклонения (шаг 9) | 80 % |
| + | Выбор трансформации по `alignment_mode` | — |

**Диагностика поглощённого отклонения (строки 473–504):**

```python
T_delta            = T_fine @ inv(T_coarse)
fine_pass_shift_mm = norm(T_delta[:3, 3])           # мм
fine_pass_rot_deg  = degrees(arccos((trace(T_delta[:3,:3]) - 1) / 2))

# C2M-статистика на прореженном облаке через готовую scene:
rmse_coarse,  within_tol_coarse  = _c2m_stats_down(T_coarse)
rmse_bestfit, within_tol_bestfit = _c2m_stats_down(T_fine)
absorbed          = rmse_coarse - rmse_bestfit         # мм
absorbed_within_tol = within_tol_bestfit - within_tol_coarse  # доля, м.б. < 0
```

**reg_diagnostics** (ключи словаря):

| Ключ | Тип | Описание |
|---|---|---|
| `fine_pass_shift_mm` | float | смещение точного прохода, мм |
| `fine_pass_rot_deg` | float | поворот точного прохода, ° |
| `rmse_coarse` | float | C2M-RMSE при грубом выравнивании, мм |
| `rmse_bestfit` | float | C2M-RMSE при точном выравнивании, мм |
| `absorbed_deviation_mm` | float | разница C2M-RMSE (груб. − точн.), мм |
| `within_tolerance_coarse` | float | доля в допуске (прорежено, T_coarse) |
| `within_tolerance_bestfit_down` | float | доля в допуске (прорежено, T_fine) |
| `absorbed_within_tol_pct` | float | разница в долях (= bestfit − coarse) |
| `alignment_mode` | str | `"best_fit"` или `"conservative"` |

**Режим выравнивания (`alignment_mode`):**
- `"best_fit"` — используется `T_fine` (меньший RMSE, но ICP может скрыть реальное отклонение)
- `"conservative"` — используется `T_coarse` (только грубое совмещение)

---

### 2.3 deviation.py

#### `compute_deviations(pcd_registered, mesh, progress_callback=None)` — строки 29–127

**Возврат:** `(signed_distances, ambiguous_mask)`, оба — `np.ndarray(N,)`.

**Ветка watertight** (строки 71–103):
1. `scene.compute_closest_points()` → `unsigned_dist`, `primitive_normals`, `dots`
2. `scene.compute_signed_distance()` → winding-number знак (`sd > 0` = снаружи = `+`, `sd < 0` = внутри = `−`)
3. Sanity-check: если среднее расхождение `|sd| vs unsigned_dist > max(1e-3, bbox_diag * 1e-4)` — предупреждение
4. `ambiguous_mask = (heuristic_signs != sign_sd)` — точки, где эвристика расходится с winding (зоны тонких стенок)
5. `signed_distances = |sd| * sign_sd`

**Ветка не-watertight** (строки 105–116):
1. `heuristic_signs = where(dots >= 0, +1, -1)`
2. `ambiguous_mask = |cos_angle| < 0.05` — точки у рёбер/кромок
3. `signed_distances = unsigned_dist * heuristic_signs`

Прогресс: 88 % после вычисления.

#### `compute_statistics(deviations, tolerance, ambiguous_mask=None, point_coords=None, worst_n=10)` — строки 130–201

**Возврат:** `dict` со следующими ключами:

| Ключ | Описание |
|---|---|
| `mean_deviation` | среднее знаковое отклонение, мм |
| `median_deviation` | медиана знакового отклонения, мм |
| `rmse` | корень из среднего квадрата отклонений |
| `max_deviation` | максимальное знаковое (самое положительное) |
| `min_deviation` | минимальное знаковое (самое отрицательное) |
| `max_abs_deviation` | максимальное по модулю |
| `std_deviation` | стандартное отклонение |
| `percentile_95` | 95-й перцентиль по `abs_dev` |
| `percentile_99` | 99-й перцентиль по `abs_dev` |
| `within_tolerance` | доля точек с `|dev| <= tolerance` |
| `over_material_pct` | доля точек с `dev > +tolerance` |
| `under_material_pct` | доля точек с `dev < -tolerance` |
| `n_points` | общее число точек |
| `tolerance` | использованный допуск, мм |
| `ambiguous_sign_count` | число точек с неоднозначным знаком |
| `ambiguous_sign_pct` | доля неоднозначных |
| `worst_points` | список `worst_n` точек с max `|dev|` (если `point_coords` задан) |

`worst_points` — список словарей `{"x": float, "y": float, "z": float, "dev": float}`,
отсортированных по убыванию `|dev|`. Заполняется только если переданы координаты.

#### `colorize_point_cloud(pcd, deviations, tolerance, colormap_name="coolwarm", ambiguous_mask=None)` — строки 218–247

LUT-раскраска: 256-цветная таблица строится **1 раз** на имя colormap (_LUT_CACHE).

```python
idx = (deviations + tolerance) * (255.0 / (2 * tolerance))
np.clip(idx, 0, 255, out=idx)
colors = lut[idx.astype(uint8)]
if ambiguous_mask is not None:
    colors[ambiguous_mask] = [0.55, 0.55, 0.55]   # серый
```

Точки за пределами `[-tolerance, +tolerance]` окрашиваются в крайние цвета шкалы.
Ambiguous-точки — всегда нейтральный серый `[0.55, 0.55, 0.55]`.

---

### 2.4 dimensions.py (НОВЫЙ МОДУЛЬ)

#### `suggest_unit_mismatch_hint(ratio, tol=0.15)` — строки 31–40

По наблюдаемому отношению диагоналей возвращает текстовую подсказку о причине.

```python
UNIT_HINT_RATIOS = [
    (10.0,   "возможно, один файл в см, другой в мм"),
    (25.4,   "возможно, один файл в дюймах, другой в мм"),
    (100.0,  "возможно, один файл в м, другой в см"),
    (1000.0, "возможно, один файл в м, другой в мм"),
]
```

Условие совпадения: `|ratio/known - 1.0| <= tol (= 0.15)`.

#### `bbox_summary(geom)` — строки 43–54

Быстрый AABB-габарит одного объекта (mesh или pcd).  
**Возврат:** `((Lx, Ly, Lz), diagonal)` в мм.  
Используется в `MainWindow` при загрузке файлов для лог-вывода.

#### `compute_dimensions(mesh, pcd_registered=None)` — строки 57–146

Габаритные размеры в единой системе отсчёта — **OBB CAD-меша**.

Алгоритм:
1. `obb = mesh.get_oriented_bounding_box()` → `center`, `R` (матрица 3×3)
2. Проверка невырожденности: `|det(R)| >= 0.5`
3. Проекция вершин меша в OBB-фрейм: `verts_local = (verts - center) @ R`
4. `cad_extent = verts_local.max(axis=0) - verts_local.min(axis=0)`
5. Аналогично для точек скана → `scan_extent`
6. `delta = scan_extent - cad_extent`

**Откат** (при вырожденном меше): AABB с сортировкой `np.sort(extent)[::-1]`.

**Возврат:**
```python
{
    "cad":       (Lx, Ly, Lz),           # float, мм
    "scan":      (Lx, Ly, Lz) | None,
    "delta":     (dLx, dLy, dLz) | None, # Скан − CAD
    "cad_diag":  float,                   # мм
    "scan_diag": float | None,
}
```

---

### 2.5 report.py

3-страничный PDF (reportlab + matplotlib, `generate_report()`, строки 109–511).

#### Шрифты (`_register_fonts()`, строки 43–55)

Попытки по приоритету:
1. `FreeSans.ttf` / `FreeSans-Bold.ttf`
2. `C:/Windows/Fonts/arial.ttf` / `C:/Windows/Fonts/arialbd.ttf`
3. Fallback: `Helvetica` / `Helvetica-Bold` (без кириллицы)

#### Страница 1 (строки 179–394)

Секции в порядке вывода:

| Секция | Содержание |
|---|---|
| Заголовок | «ОТЧЁТ О КОНТРОЛЕ ГЕОМЕТРИЧЕСКОЙ ТОЧНОСТИ» + линия |
| Входные данные | CAD-файл, треугольников, скан-файл, точек, единицы, допуск |
| Результаты измерений | среднее, RMSE, мин, макс, доля в допуске, **избыток/недостаток материала** |
| **Габаритные размеры** | CAD / Скан / Δ (если есть dims в stats) |
| **Диагностика регистрации** | смещение/поворот точн. прохода, C2M-RMSE грубое/точное, разница, маскировка, режим |
| **Технологическая интерпретация** | текст о недостатке/избытке материала, предупреждение если маскировка > 0.5 п.п. |
| Заключение | вердикт СООТВЕТСТВУЕТ/НЕ СООТВЕТСТВУЕТ (цветной блок) |

#### Страница 2 (строки 396–450)

- Сетка 3×2 из 6 видов: спереди, сзади, слева, справа, сверху, изометрия
- Подписи под каждой парой
- **Легенда цветовой шкалы** (`_create_colorbar`) — горизонтальный градиент с подписями ±tolerance

#### Страница 3 (строки 452–498)

- Гистограмма отклонений (`_create_histogram`) — n_bins = max(30, min(80, N//30))
- **Таблица worst_points** — `#`, X, Y, Z, Откл. (мм) для top-N точек

#### Вспомогательные изображения

`_create_histogram(deviations, tolerance, out)` — строки 60–80:
- `n_bins = max(30, min(80, N // 30))`
- красная/зелёная пунктирная линия при ±tolerance

`_create_colorbar(tolerance, colormap, out)` — строки 83–104:
- горизонтальный градиент `[-tolerance, +tolerance]`
- 5 меток: `-tol`, `-tol/2`, `0`, `+tol/2`, `+tol`
- подпись оси со смысловой расшифровкой

---

## §3. ДАННЫЕ

### 3.1 Форматы входных файлов

| Тип | Форматы | Ограничение |
|---|---|---|
| CAD-модель | STL, OBJ | треугольная сетка; вершин > 0 |
| Облако точек | PLY, PCD, XYZ, PTS | минимум 100 точек |
| Drag & Drop | те же | определяется по расширению |

### 3.2 Единицы измерения

**UNIT_TO_MM** (`project_manager.py:28–34`):

```python
UNIT_TO_MM = {
    "mm":    1.0,
    "cm":   10.0,
    "m":  1000.0,
    "in":   25.4,
    "as_is": 1.0,   # не масштабировать
}
```

Масштабирование выполняется **сразу после чтения файла** — до любых вычислений
AABB/нормалей (`load_cad:104`, `load_scan:152`):

```python
factor = UNIT_TO_MM.get(unit, 1.0)
if factor != 1.0:
    mesh.scale(factor, center=(0.0, 0.0, 0.0))
```

При изменении единицы для уже загруженного файла — `MainWindow` автоматически
перезагружает его (`main_window.py:775–782`), но только если новая единица
отличается от уже применённой (`unit_cad`/`unit_scan`).

### 3.3 config.json — актуальные ключи и дефолты

Конфиг загружается через `load_config()` (`main.py:292`).
**Дефолты** — значения, используемые при отсутствии или неполном config.json.
**Текущий config.json** — файл в `C:\module\config.json`.

| Ключ | Дефолт (`load_config`) | Значение в config.json |
|---|---|---|
| `preprocessing.sor_neighbors` | 20 | 21 |
| `preprocessing.sor_std_ratio` | 2.0 | 1.6 |
| `preprocessing.voxel_size` | 0 | 0 |
| `registration.ransac_max_iter` | 200000 | 200000 |
| `registration.ransac_n_starts` | 5 | 6 |
| `registration.ransac_top_k` | 4 | 4 |
| `registration.icp_coarse_pct` | 5.0 | 3.5 |
| `registration.icp_fine_pct` | 1.0 | 1.3 |
| `registration.icp_max_iter` | 150 | 90 |
| `registration.use_pca_seeds` | True | true |
| `registration.reject_rmse_pct` | 5.0 | 5.0 |
| `registration.alignment_mode` | `"best_fit"` | `"conservative"` |
| `analysis.tolerance_mm` | 0.5 | 0.5 |
| `analysis.conformance_threshold` | 95 | 94 |
| `analysis.worst_points_n` | 10 | 10 |
| `ui.advanced_mode` | False | false |
| `ui.colormap` | `"RdYlGn_r"` | `"RdYlGn_r"` |
| `ui.last_dir` | `""` | `"C:/module/tests/fixtures"` |
| `units.cad` | `"mm"` | `"mm"` |
| `units.scan` | `"mm"` | `"as_is"` |

Слияние: `_deep_merge(defaults, user_config)` — рекурсивное, секции не
заменяются целиком (`main.py:276`).

### 3.4 Формат JSON-проекта (версия 1.2)

Сохраняется через `ProjectManager.save_project(path)` (`project_manager.py:190`):

```json
{
  "version":       "1.2",
  "saved_at":      "ISO-8601 datetime",
  "cad_path":      "/abs/path/to/model.stl",
  "scan_path":     "/abs/path/to/scan.ply",
  "unit_cad":      "mm",
  "unit_scan":     "as_is",
  "config":        { ...полный конфиг... },
  "analysis_date": "YYYY-MM-DD HH:MM:SS",
  "stats":         { ...словарь stats... },
  "has_npz":       true
}
```

**Поля unit_cad/unit_scan** — новые в v1.2. Старые проекты без них читаются
корректно: значения берутся из `config["units"]` (строка `project_manager.py:248–249`).

При загрузке (`load_project`) восстанавливаются: конфиг, пути файлов,
статистика, единицы, NPZ. Ключ `missing_files` содержит список ненайденных файлов.

### 3.5 NPZ-сайдкар

Файл `*.npz` — то же имя, что JSON. Сохраняется через `np.savez_compressed`.

| Ключ массива | Тип | Описание |
|---|---|---|
| `deviations` | float64, (N,) | знаковые отклонения, мм |
| `transformation` | float64, (4,4) | итоговая матрица регистрации |
| `pcd_points` | float64, (N,3) | координаты зарегистрированного облака |
| `ambiguous_mask` | bool, (N,) | маска неоднозначного знака |

Массивы `transformation`, `pcd_points`, `ambiguous_mask` сохраняются только
если они не `None` (`project_manager.py:217–223`).

---

## §4. ИНТЕРФЕЙС

### 4.1 Структура главного окна (ASCII)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Меню: Файл | Справка                                                │
├──────────────────────────────────────────────────────────────────────┤
│  Тулбар: [Загр.CAD] [Загр.Скан] │ [▶ Запустить анализ] [■ Отмена]  │
│          │ [Сохранить отчёт PDF]                                     │
├───────────────────┬──────────────────────────────────────────────────┤
│                   │  [Вид: Наложение | Только скан | Только модель]  │
│  ControlPanel     │  [Камера: ↺ Сброс]              [Скриншот]      │
│  (≤ 320 px)       │                                                  │
│                   │  3D-вид (PyVista/VTK + scalar bar)               │
│                   │                                                  │
│  ResultsPanel     │  ─────────────────────────────────────────────   │
│                   │  ЛКМ: вращение | ПКМ: перемещение | Колесо: зум │
│                   │  Двойной клик: центрировать                      │
│                   │  ─────────────────────────────────────────────   │
│                   │  [Сохранить лог] [Очистить лог]   [■ Отмена]   │
│                   │  LogPanel (QTextEdit, Courier New 9)             │
└───────────────────┴──────────────────────────────────────────────────┘
│  Статусбар: Модель: xxx | Скан: yyy | Статус: zzz  [этап] [████░░]  │
└──────────────────────────────────────────────────────────────────────┘
```

Ширина левой панели: 220–320 px (ограничена `setMaximumWidth(320)`).
Правая часть растягивается (stretch factor 1).

### 4.2 ControlPanel (`panels.py:55`)

#### Всегда видимые группы

**Единицы измерения** (строки 293–321):
- Подсказка «Программа приведёт всё к мм»
- Комбобокс **CAD**: мм / см / м / дюйм / как есть
- Комбобокс **Скан**: мм / см / м / дюйм / как есть
- Примечание «STL/PLY не хранят единицы»

**Режим выравнивания** (строки 323–360):
- Подсказка с описанием режимов
- Комбобокс: Наилучшее вписывание (`best_fit`) / Консервативный (`conservative`)

#### Простой режим (строки 136–162)

Подсказка «Параметры подобраны автоматически» + два поля:
- **Допуск ±(мм)**: `QDoubleSpinBox`, диапазон 0.001–50.0, шаг 0.05, 3 знака + кнопка ↻
- **Порог соответствия (%)**: `QSpinBox`, 80–100, шаг 1 + кнопка ↻

Кнопка ↻ — быстрый пересчёт статистики без повторной регистрации (`recalculate_requested`).
Активна только при наличии результатов.

#### Расширенный режим (строки 164–291)

Три группы параметров:

**Предобработка:**
- Воксель (мм, 0=авто): 0.0–50.0, шаг 0.1
- SOR k (соседей): 5–100, шаг 1
- SOR σ (строгость): 0.5–5.0, шаг 0.1

**Регистрация:**
- Попытки RANSAC: 1–20, шаг 1
- Грубый ICP (%): 1.0–20.0, шаг 0.5
- Точный ICP (%): 0.1–5.0, шаг 0.1
- Итераций ICP: 10–200, шаг 10

**Расчёт отклонений:**
- Допуск ±(мм) + кнопка ↻
- Порог соответствия (%) + кнопка ↻
- Цветовая шкала: coolwarm / RdYlGn_r / jet

Все поля допуска/порога синхронизированы между простым и расширенным
режимами через флаг `_updating` (строки 419–453).

**Сигналы:**
- `param_changed(list, object)` — путь в конфиге + значение
- `recalculate_requested()` — запрос быстрого пересчёта

**Параметры, изменение которых НЕ требует повторной регистрации («лёгкие»):**

```python
_light = (
    ["analysis", "tolerance_mm"],
    ["analysis", "conformance_threshold"],
    ["ui", "colormap"],
)
```

Все остальные параметры устанавливают флаг `_heavy_params_dirty = True`
(`main_window.py:756–763`).

### 4.3 ResultsPanel (`panels.py:586`)

#### Метрики (строки 619–650)

| Ключ | Метка | Единица | Формат |
|---|---|---|---|
| `mean_deviation` | Среднее отклонение | мм | `{:+.4f}` |
| `registration_rmse` | RMSE | мм | `{:.6f}` |
| `min_deviation` | Мин. отклонение | мм | `{:+.4f}` |
| `max_deviation` | Макс. отклонение | мм | `{:+.4f}` |
| `within_tolerance` | Доля в допуске | % | `{:.1f}` (×100) |
| `over_material_pct` | Избыток материала | % | `{:.1f}` (×100) |
| `under_material_pct` | Недостаток материала | % | `{:.1f}` (×100) |

#### Вердикт (строки 742–755)

- Зелёный фон (`#1B5E20`/`#A5D6A7`): «✓ СООТВЕТСТВУЕТ ДОПУСКАМ (±X.XXX мм)»
- Красный фон (`#7f0000`/`#FFCDD2`): «✗ НЕ СООТВЕТСТВУЕТ (в допуске XX.X%)»
- Порог — из `set_threshold()` (от `config["analysis"]["conformance_threshold"]`)

#### Группа «Габаритные размеры» (строки 659–682)

- CAD: `Lx.x × Ly.y × Lz.z мм`
- Скан: аналогично
- Δ: `±dLx.xx × ±dLy.xx × ±dLz.xx мм`

#### Группа «Диагностика регистрации» (строки 685–721)

| Атрибут | Метка | Единица |
|---|---|---|
| `_diag_shift` | Смещение точн. прохода | мм |
| `_diag_rot` | Поворот точн. прохода | ° |
| `_diag_coarse` | RMSE до точного ICP | мм |
| `_diag_bestfit` | RMSE после точного ICP | мм |
| `_diag_absorb` | Разница C2M-RMSE | мм |
| `_diag_coarse_tol` | Доля в допуске (грубая) | % |
| `_diag_absorb_tol` | Маскировка доли | п.п. |
| `_diag_mode` | Режим | — |

### 4.4 ViewerWidget (`viewer_widget.py:225`)

**Константа:**
```python
_MAX_DISPLAY_PTS = 600_000   # viewer_widget.py:194
```
Если облако точек > 600 000 — прореживается равномерным шагом для отображения.
Статистика и PDF всегда считаются на полных данных.

**Фон:** `_BG = (0.10, 0.10, 0.12)` (строка 228).

#### Режимы вида (строки 359–384)

| Кнопка | Режим | Описание |
|---|---|---|
| Наложение | `"overlay"` | полупрозрачный меш (opacity=0.22) + раскрашенный скан |
| Только скан | `"scan"` | только раскрашенное облако точек |
| Только модель | `"model"` | меш: до анализа — непрозрачный серый с рёбрами, после — opacity=0.92 |

Кнопки «Наложение» и «Только скан» заблокированы до завершения анализа.

#### Scalar bar (строки 554–565)

```python
scalar_bar_args = {
    "title": "",
    "n_labels": 5,
    "fmt": "%+.2f",
    "color": "white",
    "label_font_size": 11,
    "position_x": 0.02,
    "position_y": 0.10,
    "width": 0.06,
    "height": 0.80,
    "vertical": True,
}
```

#### make_multiview_screenshots() (строки 604–672)

6 видов через offscreen-рендерер `pv.Plotter(off_screen=True, window_size=(750, 560))`:

| Имя | Позиция камеры | Up |
|---|---|---|
| front | `(cx, cy-d, cz)` | Z |
| back | `(cx, cy+d, cz)` | Z |
| left | `(cx-d, cy, cz)` | Z |
| right | `(cx+d, cy, cz)` | Z |
| top | `(cx, cy, cz+d)` | Y |
| iso | `(cx+d·0.7, cy-d·0.7, cz+d·0.55)` | Z |

`d = diagonal × 1.8`.

### 4.5 LogPanel (`panels.py:808`)

Цветовая раскраска сообщений (`_classify_color`, строки 857–866):

| Цвет | Hex | Триггеры |
|---|---|---|
| Красный | `#FF6B6B` | «ошибка», «error» |
| Оранжевый | `#FFA726` | «предупреждение», «warning», «внимание» |
| Зелёный | `#66BB6A` | «завершён», «успешно», «сохранён» |
| Светло-серый | `#e8e8e8` | всё остальное |

Метка времени `[HH:MM:SS]` в цвете `#909090`.

Кнопки: «Сохранить лог» (`.txt`), «Очистить лог», «■ Отмена» (видна только
во время анализа). Шрифт: Courier New 9pt.

### 4.6 Горячие клавиши (`main_window.py:106–138`)

| Клавиша | Действие |
|---|---|
| `Ctrl+O` | Загрузить CAD-модель |
| `Ctrl+Shift+O` | Загрузить облако точек |
| `Ctrl+S` | Сохранить проект |
| `Ctrl+P` | Открыть проект |
| `Ctrl+R` | Сохранить отчёт PDF |
| `F1` | Руководство пользователя |
| `Ctrl+Q` | Выход |

### 4.7 Управление мышью в 3D-виде

`_ViewerInteractionFilter` (`viewer_widget.py:42`) — Qt event filter поверх `QtInteractor`:

| Жест | Действие |
|---|---|
| ЛКМ + движение | вращение (стандарт VTK TrackballCamera) |
| Колесо | зум к фокальной точке (стандарт VTK) |
| ПКМ + движение | перемещение (pan): реализовано через прямую манипуляцию камерой |
| Двойной клик ЛКМ | перецентровать камеру на точке под курсором (z-буфер `vtkPropPicker`) |
| Кнопка «↺ Сброс» | `plotter.reset_camera()` |

VTK-обработчики ПКМ (`RightButtonPressEvent`, `RightButtonReleaseEvent`) удалены
у активного стиля (`viewer_widget.py:283–288`) чтобы предотвратить «прыжок камеры».

---

## §5. ИЗВЕСТНЫЕ ПРОБЛЕМЫ И ОГРАНИЧЕНИЯ

### 5.1 Hardcoded константы

| Константа | Значение | Файл:строка | Описание |
|---|---|---|---|
| `_MAX_DISPLAY_PTS` | 600 000 | `viewer_widget.py:194` | лимит точек в 3D-виде |
| adaptive voxel (preproc) | `bbox_diag * 0.015` | `preprocessing.py:135` | авто-воксель при voxel_size=0 |
| adaptive voxel (reg) | `bbox_diag * 0.02` | `registration.py:42` | воксель для регистрации |
| adaptive fpfh_radius | `bbox_diag * 0.05` | `registration.py:43` | радиус FPFH |
| adaptive ransac_dist | `bbox_diag * 0.03` | `registration.py:44` | порог RANSAC |
| ICP pass-1 max_iter | 80 | `registration.py:258` | грубый проход ICP |
| ICP convergence | `relative_fitness=1e-6, relative_rmse=1e-6` | `registration.py:272` | точный проход |
| ICP timeout | 60 с | `registration.py:223` | таймаут каждого прохода |
| PCA кандидатов | 4 | `registration.py:128–138` | знаковые комбинации |
| reject_rmse_pct (дефолт) | 5.0 % | `main.py:316` | порог валидационного шлюза |
| candidate quick-ICP iter | 50 | `registration.py:195` | в `_evaluate_candidate` |
| ambiguous threshold (non-wt) | `|cos| < 0.05` | `deviation.py:113` | порог у рёбер |
| sanity-check threshold | `max(1e-3, bbox_diag*1e-4)` | `deviation.py:83` | расхождение sd vs dist |
| масштаб меша reuse-delta | 20 % | `registration.py:306` | совместимость вокселей |
| warning large file | 5 000 000 точек | `main_window.py:348` | предупреждение о большом скане |
| loading dialog | 50 МБ | `main_window.py:860` | порог прогресс-диалога |
| unit mismatch ratio | > 5.0× | `main_window.py:421` | предупреждение о разных масштабах |
| suggest_unit_mismatch tol | 0.15 | `dimensions.py:36` | 15% окно совпадения |
| masking warning (PDF) | `|abs_pp| > 0.5 п.п.` | `report.py:364` | порог для текста об маскировке |
| LUT размер | 256 | `deviation.py:213` | разрешение таблицы цветов |
| ambiguous color | `[0.55, 0.55, 0.55]` | `deviation.py:240` | серый для неоднозначных точек |
| ICP _NORMAL_CONFIG (тест) | `ransac_n_starts=6, max_iter=200` | `test_registration_robustness.py:156` | тестовый конфиг |

### 5.2 Прочие ограничения

- **Кириллица в PDF**: если на машине нет `FreeSans.ttf` и `C:/Windows/Fonts/arial.ttf` — reportlab упадёт на fallback `Helvetica`, который не поддерживает кириллицу. PDF будет создан, но текст заменится «?».
- **Частичные сканы**: при сканировании только части поверхности (неполное перекрытие) RANSAC может дать неверные гипотезы; `registration_suspect` помогает, но не гарантирует обнаружение.
- **Симметричные детали**: для цилиндров, сфер, кубов PCA-гипотезы не устраняют неоднозначность (все позы равнозначны по C2M-RMSE).
- **Non-watertight меш**: знак отклонения эвристический; `ambiguous_mask` покрывает только точки у рёбер, не тонкие стенки.
- **Масштаб `as_is`**: для скана `unit_scan="as_is"` геометрия не масштабируется. Это корректно только если скан уже в мм.
- **NPZ без worst_points**: `worst_points` — список словарей, который не сохраняется в NPZ. При загрузке проекта он восстанавливается только если `saved_stats` содержит его.

---

## §6. ТЕСТЫ

### 6.1 test_registration_robustness.py

**Цель:** воспроизведение и верификация исправления бага «ложный 180°-минимум».

#### Синтетическая геометрия (`make_L_shape`)

Г-образная деталь из двух `create_box`:
- Длинная рука: 100 × 30 × 20 мм
- Короткая рука: 30 × 30 × 40 мм (сдвинута к `x=[70,100], z=[20,60]`)

Ось неоднозначности: Y. Поворот на 180° вокруг Y переставляет короткую руку
на левый конец — деталь геометрически неотличима по FPFH плоских граней.

Вспомогательные функции:
- `sample_scan(mesh, n_points, noise_std, seed)` — равномерная передискретизация + гауссов шум
- `make_transform(angle_deg, axis, t)` — матрица 4×4 поворота + сдвига
- `apply_transform(pcd, R, t)` — применение жёсткого преобразования
- `final_c2m_rmse(mesh, pcd_registered)` — ключевая метрика через `compute_deviations`
- `pose_error(T_est, T_gt)` — `(angle_deg, t_norm_mm)` ошибки позы

#### Тестовые конфигурации

**`_NORMAL_CONFIG`** (строки 148–161): production-дефолты.
- `ransac_n_starts=6`, `ransac_max_iter=200_000`, `icp_max_iter=200`

**`_BUGGY_CONFIG`** (строки 163–181): конфигурация-провокатор.
- `ransac_n_starts=1`, `ransac_max_iter=20_000` — слабый одиночный RANSAC,
  регулярно проваливавшийся в ложный минимум до исправления.

#### Тесты

**`test_zero_deviation_identity()`** (строки 246–283):
- Скан = точная передискретизация меша + 10° вокруг Y + сдвиг 5 мм
- Проверяет: C2M-RMSE < `bbox_diag × 1e-3` ≈ 0.12 мм, ошибка позы < 10°

**`test_false_minimum_Lshape()`** (строки 298–377):
- Скан стартует из перевёрнутой позы (180° вокруг Y). 10 запусков с `_BUGGY_CONFIG`
- Порог провала: C2M-RMSE > `bbox_diag × 5%` ИЛИ ошибка позы > 90°
- Проверяет: `failures == 0` после фикса (PCA-гипотезы покрывают правильную ориентацию)

**`test_stability_5seeds()`** (строки 384–418):
- Тест C повторяется с seed 0–4
- Все 5 должны: C2M-RMSE < eps, ошибка позы < 10°

#### Известная проблема в тесте

Вспомогательная функция `_run_pipeline` (строка 192) распаковывает только
4 значения из `register_pipeline`, которая возвращает 5-tuple:

```python
# test_registration_robustness.py:193 — НЕВЕРНО для текущего кода:
pcd_reg, T_est, icp_rmse, _suspect = register_pipeline(...)
# Правильно (как в test_q5_integration.py:141):
pcd_reg, T_est, icp_rmse, suspect, reg_diag = register_pipeline(...)
```

Это вызовет `ValueError: too many values to unpack` при запуске тестов.

### 6.2 test_q5_integration.py

**Цель:** интеграционная проверка выходных данных Q5-функциональности.

#### Синтетическая сцена (`_make_defective_scan`)

Г-деталь с детерминированными дефектами:
- **Избыток материала**: вершина короткой руки (`z > 57, x > 68`) смещена `+2.5 мм` по Z
- **Недостаток материала**: левая грань длинной руки (`x < 1, y < 30, z < 20`) смещена `+2.5 мм` по X (внутрь)
- Гауссов шум: std=0.05 мм
- Начальное смещение: `+8 мм` по X + 3° вокруг Z (чтобы регистрация реально работала)

Пайплайн выполняется **1 раз** на модуль через `_ensure_shared()`.

#### Тесты

**`test_material_split_invariant()`**:
- Проверяет: `within + over + under == 100.000000%` (|sum - 100| < 1e-6)
- Проверяет: `over > 0`, `under > 0`

**`test_worst_points()`**:
- `len(worst_points) == 10`
- `|worst_points[0].dev| == max_abs_deviation` (точность 1e-8)
- Список отсортирован по убыванию `|dev|`

**`test_masking_metrics()`**:
- Инвариант: `within_tolerance_coarse + absorbed_within_tol_pct == within_tolerance_bestfit_down`
  (на прореженном облаке, точность < 1e-9)
- Примечание: `stats["within_tolerance"]` (полное облако) будет отличаться от
  `within_tolerance_bestfit_down` — это корректно и проверяется отдельно

**`test_pdf_sections()`**:
- Генерирует PDF в tmpfile
- Через `pypdf.PdfReader` проверяет наличие секций:
  1. Заголовок легенды цветовой шкалы (стр. 2)
  2. Строки «Избыток материала» и «Недостаток материала» (стр. 1)
  3. Секция «Технологическая интерпретация» (стр. 1)
  4. Строки маскировки в диагностике (стр. 1)
  5. Таблица worst_points (стр. 3)
- При отсутствии `pypdf` — тест пропускается (не падает)

### 6.3 Fixture-файлы

Генерируются функцией `_generate_fixtures()` (`test_registration_robustness.py:203`):

| Файл | Описание |
|---|---|
| `tests/fixtures/L_shape.stl` | CAD Г-детали (100+30 мм) |
| `tests/fixtures/scan_correct.ply` | 10 000 точек, правильная поза, шум 0.2 мм |
| `tests/fixtures/scan_flipped.ply` | тот же скан, повёрнутый на 180° вокруг Y относительно центроида |

Для GUI-демонстрации бага: загрузить `L_shape.stl` + `scan_flipped.ply`,
выставить слабый RANSAC (`n_starts=1, max_iter=5000`).

### 6.4 Запуск тестов

```bash
# pytest с выводом:
pytest tests/test_q5_integration.py -v -s

# Standalone (без pytest):
C:/module/.venv/Scripts/python.exe tests/test_q5_integration.py

# Тест регистрации (с учётом проблемы распаковки 4 vs 5 — см. §6.1):
pytest tests/test_registration_robustness.py -v -s

# Standalone (генерирует fixtures + 3 теста):
python tests/test_registration_robustness.py
```

Переменная `FIXTURES_DIR = Path(__file__).parent / "fixtures"`. При первом
запуске standalone-режима — генерируются fixture-файлы.
