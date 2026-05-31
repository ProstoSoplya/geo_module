# APPLICATION_DESCRIPTION.md

Документ описывает текущее состояние приложения «Модуль анализа отклонений геометрии деталей» по фактическому содержимому исходного кода в `C:\module` на момент составления. Старый `IMPLEMENTATION_REPORT.md` не учитывался.

---

## 1. Общее описание

**Модуль анализа отклонений геометрии** — десктопное приложение для контроля качества изготовления изделий путём сравнения трёхмерного скана физической детали с её эталонной CAD-моделью. Приложение принимает на вход CAD-модель (STL/OBJ) и облако точек скана (PLY/PCD/XYZ/PTS), выполняет совмещение (RANSAC + ICP), рассчитывает отклонения «точка-поверхность» (Cloud-to-Mesh), формирует статистику, цветную визуализацию отклонений и трёхстраничный PDF-отчёт.

Целевая аудитория — инженеры контроля качества, технологи и студенты технических специальностей. Имя приложения зашито в `main.py:417` как «Модуль анализа отклонений геометрии», организация — «РГАТУ» (`main.py:418`). В «О программе» (`ui/help_dialog.py:362-368`) указано: версия `1.0`, автор Отряхина В.Л., организация «РГАТУ им. П.А. Соловьёва», год `2026`, стек «Python · Open3D · PyQt6 · ReportLab».

Полный пайплайн анализа (`core/worker.py:120-270`) последовательно выполняет четыре этапа: предобработку облака точек (SOR-фильтр и опциональный voxel-downsample), грубое совмещение (RANSAC с PCA-затравками и мультистартом), точное совмещение (двухпроходный ICP), расчёт отклонений со статистикой и габаритами. Приложение поддерживает «базовый» и «расширенный» режимы UI: в базовом режиме `worker.py:125-129` принудительно подменяет секции `preprocessing`/`registration` на значения из `BASIC_DEFAULTS` (`core/defaults.py`). Состояние сессии (загруженные данные, параметры, результаты) централизованно хранит `ProjectManager` (`core/project_manager.py:101`), и UI работает с алгоритмами исключительно через него.

---

## 2. Стек технологий

Зависимости из `requirements.txt`:

| Библиотека | Версия | Роль в проекте |
|---|---|---|
| **PyQt6** | ≥6.4.0 | GUI-фреймворк: `QApplication`, `QMainWindow`, `QThread`, сигналы/слоты, диалоги, drag&drop. Используется в `main.py:21`, `ui/*.py`, `core/worker.py:25` |
| **open3d** | ≥0.18.0 | Работа с 3D-геометрией: `TriangleMesh`, `PointCloud`, чтение STL/OBJ/PLY/PCD/XYZ/PTS, RANSAC/ICP-регистрация, SOR-фильтрация, FPFH, RaycastingScene (BVH для C2M). Импорт в `core/project_manager.py:22`, `core/worker.py:22`, `core/algorithms/*` |
| **numpy** | ≥1.24.0 | Массивы координат и отклонений, матрицы трансформации 4×4, NPZ-сериализация. Используется во всех модулях |
| **reportlab** | ≥4.0.0 | Генерация PDF-отчёта (`core/algorithms/report.py`) — `SimpleDocTemplate`, `Image`, `Table`, регистрация TTF-шрифтов |
| **matplotlib** | ≥3.7.0 | Цветовые карты (`get_cmap` для LUT в `deviation.py:391`), бэкенд `Agg` для построения гистограммы и легенды-colorbar PDF-отчёта (`report.py`) |
| **pyvista** | ≥0.42 | 3D-просмотрщик (`ui/viewer_widget.py`) — высокоуровневая обёртка над VTK |
| **pyvistaqt** | ≥0.11 | Интеграция PyVista с Qt: `QtInteractor` встраивается в QWidget |
| **vtk** | ≥9.2 | Базовый движок рендеринга; используются `vtkInteractorStyleTrackballCamera` (кастомизация ПКМ-pan), `vtkPropPicker` (выбор точки по двойному клику) |

Дополнительные библиотеки, используемые в коде, но отсутствующие в `requirements.txt`:

| Библиотека | Роль | Где |
|---|---|---|
| **platformdirs** | Кросс-платформенное определение `user_log_dir` для `app.log`. Импорт обёрнут в `try/except ImportError`; при отсутствии — fallback на CWD | `main.py:259-262` |

Стандартная библиотека: `json`, `logging`, `logging.handlers.RotatingFileHandler`, `sys`, `os`, `copy`, `threading`, `concurrent.futures` (таймаут ICP), `tempfile`, `traceback`, `datetime`, `typing`, `pathlib`.

---

## 3. Структура проекта

```
C:\module\
├── main.py                              448 строк   — точка входа, логгер, загрузка конфига, QSS
├── config.json                                      — пользовательская конфигурация
├── project.json                                     — пример сохранённого проекта
├── project.npz                                      — NPZ-сайдкар примера проекта
├── requirements.txt                                 — зависимости pip
├── IMPLEMENTATION_REPORT.md                         — устаревший отчёт (не использовать)
├── Green_Alien.stl                                  — пример CAD-модели
├── scan.ply                                         — пример облака точек скана
├── report.pdf                                       — пример выходного PDF-отчёта
├── app.log                                          — лог приложения (legacy CWD-копия)
│
├── core/
│   ├── defaults.py                       25 строк   — BASIC_DEFAULTS (preprocessing/registration)
│   ├── project_manager.py               436 строк   — ProjectManager, UNIT_TO_MM, load/save_project
│   ├── worker.py                        270 строк   — AnalysisWorker(QThread)
│   └── algorithms/
│       ├── preprocessing.py             147 строк   — preprocess_pipeline (SOR, voxel)
│       ├── registration.py              572 строки  — register_pipeline, RegistrationError
│       ├── deviation.py                 429 строк   — compute_deviations/statistics/colorize
│       ├── dimensions.py                146 строк   — compute_dimensions, suggest_unit_mismatch_hint
│       └── report.py                    565 строк   — генерация 3-страничного PDF
│
├── ui/
│   ├── main_window.py                  1174 строки  — MainWindow (меню, тулбар, состояния)
│   ├── viewer_widget.py                 755 строк   — ViewerWidget (PyVista/VTK)
│   ├── panels.py                        757 строк   — ControlPanel, ResultsPanel, LogPanel
│   └── help_dialog.py                   390 строк   — HelpDialog, AboutDialog
│
└── tests/
    ├── __init__.py                        0 строк   — пустой маркер пакета
    ├── test_q5_integration.py           416 строк   — интеграционный тест пайплайна
    └── test_registration_robustness.py  465 строк   — устойчивость регистрации к 180°
```

**Итого: 6995 строк Python-кода.**

### Публичный API по файлам

| Файл | Публичный API |
|---|---|
| `main.py` | `setup_logging()`, `load_config(path="config.json")`, `main()`; внутренние: `_resolve_log_path()`, `_deep_merge()`, `_validate_config_ranges()`; константа `_DARK_QSS` (имя историческое; фактически содержит активную тему) |
| `core/defaults.py` | `BASIC_DEFAULTS: dict` — секции `preprocessing` и `registration` |
| `core/project_manager.py` | `ProjectManager`; `UNIT_TO_MM: dict[str, float]`; внутренние: `_deep_merge_config`, `_types_compatible`, `_is_safe_project_path` |
| `core/worker.py` | `AnalysisWorker(QThread)`; сигналы `progress_changed`, `stage_changed`, `log_message`, `analysis_finished`, `analysis_error`, `analysis_cancelled`; методы `cancel()`, `run()` |
| `core/algorithms/preprocessing.py` | `remove_outliers`, `voxel_downsample`, `preprocess_pipeline` |
| `core/algorithms/registration.py` | `register_pipeline`, `RegistrationError`, `pca_alignment_candidates` |
| `core/algorithms/deviation.py` | `compute_deviations`, `compute_statistics`, `colorize_point_cloud` |
| `core/algorithms/dimensions.py` | `compute_dimensions`, `bbox_summary`, `suggest_unit_mismatch_hint`, `UNIT_HINT_RATIOS` |
| `core/algorithms/report.py` | `generate_report` |
| `ui/main_window.py` | `MainWindow(config)` |
| `ui/viewer_widget.py` | `ViewerWidget` |
| `ui/panels.py` | `ControlPanel`, `ResultsPanel`, `LogPanel` |
| `ui/help_dialog.py` | `HelpDialog`, `AboutDialog` |

---

## 4. Архитектура и поток данных

### 4.1 Слои приложения

```
main.py
   │  setup_logging() + load_config() + QApplication
   ▼
MainWindow (ui/main_window.py, 1174 строки)
   │  держит ссылку на ProjectManager(config)
   ▼
ProjectManager (core/project_manager.py)
   │  владеет mesh, pcd, deviations, stats, transformation
   ▼
AnalysisWorker (core/worker.py, QThread)
   │  выполняет preprocess → registration → deviation → dimensions
   ▼
core/algorithms/*  ←  чистые функции, никакого UI
   │
   ▼ сигнал analysis_finished(dict)
MainWindow → ProjectManager.save_results(...)
   │
   ├──▶ ViewerWidget (PyVista/VTK)   — отображает pcd_colored / mesh
   ├──▶ ResultsPanel (ui/panels.py)  — таблицы статистики и вердикт
   └──▶ core/algorithms/report.py    — 3-страничный PDF-отчёт
```

### 4.2 Запуск приложения (`main.py`)

`main.py:407-444`:
1. `setup_logging()` — настраивает StreamHandler + `RotatingFileHandler` (5 МБ × 3 бэкапа).
2. `load_config()` — читает `config.json`, мерджит с дефолтами через `_deep_merge`, валидирует диапазоны.
3. `QApplication(sys.argv)` — обязательно ДО любых виджетов (`main.py:415`).
4. `app.setStyle("Fusion")` + `app.setStyleSheet(_DARK_QSS)` (`main.py:421-422`).
5. Импорт `MainWindow` (`main.py:425`) — отложенный, ПОСЛЕ создания `QApplication`.
6. `MainWindow(config)` создаётся внутри `try/except`. При сбое — `QMessageBox.Icon.Critical` и `sys.exit(1)`.
7. `app.exec()` — главный цикл событий.

### 4.3 Поток данных: файл → анализ → результат

1. **Загрузка CAD** — `ProjectManager.load_cad(path, unit)` (`project_manager.py:150-202`): проверка расширения по `_SUPPORTED_CAD_EXT = {".stl", ".obj"}`, чтение через `o3d.io.read_triangle_mesh`, проверка непустоты, масштабирование `mesh.scale(factor, center=(0,0,0))` с фактором из `UNIT_TO_MM`, вычисление нормалей вершин и треугольников, окрашивание в серый `[0.7, 0.7, 0.7]`, сохранение в `self.mesh`, сброс результатов через `_reset_results()`.
2. **Загрузка скана** — `ProjectManager.load_scan(path, unit)` (`project_manager.py:204-248`): расширения `_SUPPORTED_SCAN_EXT = {".ply", ".pcd", ".xyz", ".pts"}`, проверка минимума `len(pcd.points) >= 100`, масштабирование.
3. **Готовность к анализу** — `is_ready_for_analysis()` (`project_manager.py:250-252`): `mesh is not None and pcd is not None`.
4. **Запуск анализа** — `MainWindow` создаёт `AnalysisWorker(pcd, mesh, config)` и вызывает `worker.start()`.
5. **Этапы пайплайна** (`worker.py:120-270`):
   - **Этап 1/4** — `preprocess_pipeline(pcd, config, progress_callback)` → `(pcd_clean, pcd_down, pcd_voxel_size)` (`worker.py:134-138`).
   - **Этап 2-3/4** — `register_pipeline(pcd_clean, pcd_down, mesh, config, progress_callback, pcd_voxel_size)` → `(pcd_registered, transform, reg_rmse, reg_suspect, reg_diag)` (`worker.py:154-161`). Подэтапы RANSAC и ICP переключаются автоматически по порогам прогресса.
   - **Этап 4/4 (А)** — `compute_deviations(pcd_registered, mesh, progress_callback)` → `(deviations, ambiguous_mask)` (`worker.py:199-203`).
   - **Этап 4/4 (Б)** — `compute_statistics(deviations, tolerance, ambiguous_mask=..., point_coords=..., worst_n=...)` (`worker.py:211-216`); добавляются `registration_rmse`, `registration_suspect`, поля `reg_diag`.
   - **Габариты** — `compute_dimensions(mesh, pcd_registered)` → `stats["dimensions"]` (`worker.py:220-221`).
   - **Раскраска** — `colorize_point_cloud(pcd_registered, deviations, tolerance, colormap_name=config["ui"]["colormap"], ambiguous_mask=...)` (`worker.py:246-250`).
6. **Сигнал завершения** — `analysis_finished.emit({"pcd_registered","pcd_colored","deviations","ambiguous_mask","stats","transform"})` (`worker.py:262-270`).
7. **Приёмка результатов** — `MainWindow._on_analysis_finished` (`main_window.py:723-820`): проверки качества регистрации, `ProjectManager.save_results(results)`, обновление `ViewerWidget` и `ResultsPanel`.
8. **Сохранение** — `ProjectManager.save_project(path)` (`project_manager.py:276-313`): JSON + NPZ-сайдкар.
9. **PDF** — `core/algorithms/report.py:generate_report(...)` использует `pcd_colored`, `stats`, скриншоты из `ViewerWidget.make_multiview_screenshots()`.

### 4.4 Сигналы AnalysisWorker

Все сигналы объявлены в `core/worker.py:54-59`:

| Сигнал | Сигнатура | Когда испускается | Слот в MainWindow |
|---|---|---|---|
| `progress_changed` | `int` (0–100) | `_emit_progress(value)` — `worker.py:87`; также явно 35, 88, 97, 100 | `_on_progress` (`main_window.py:717-718`) → `progress_bar.setValue` |
| `stage_changed` | `str` | `_emit_stage(text)` — `worker.py:93`; вызывается из `_emit_progress` по порогам и явно (`worker.py:132, 207`) | `_on_stage_changed` (`main_window.py:720-721`) → текст `_stage_label` |
| `log_message` | `str` | `_log(message)` — `worker.py:98`; также в `run()` при ошибках | `_log` → `LogPanel.append` |
| `analysis_finished` | `dict` | `worker.py:270` после успешного пайплайна | `_on_analysis_finished` (`main_window.py:723-820`) |
| `analysis_error` | `str` | `worker.py:113, 118` — `RegistrationError`/`TimeoutError`/общий `Exception` | `_on_analysis_error` (`main_window.py:822-827`) → `QMessageBox.critical` |
| `analysis_cancelled` | (без аргументов) | `worker.py:108` при `InterruptedError` | `_on_analysis_cancelled` (`main_window.py:829-834`) — без диалога ошибки |

Подключение — `QueuedConnection` в `run_analysis()` (`main_window.py:524-533`). Перед стартом нового worker'а у предыдущего вызывается `disconnect()` (`main_window.py:512-516`) — это защита от отложенных эмитов из очереди событий.

### 4.5 Поток QThread и отмена

- `AnalysisWorker` наследует `QThread` (`worker.py:48`). Запуск через `worker.start()`.
- Отмена — `threading.Event` (`worker.py:70`). Комментарий: `Event` даёт гарантированную memory visibility между потоками, тогда как обычный `bool` полагался на implementation detail CPython GIL.
- `cancel()` (`worker.py:73-75`) — `self._cancelled.set()`.
- Проверка отмены: в `_emit_progress` (`worker.py:79-80`) при `_cancelled.is_set()` бросается `InterruptedError("Анализ отменён пользователем")`.
- `run()` (`worker.py:100-118`) ловит `InterruptedError` → `analysis_cancelled.emit()`; `RegistrationError`/`TimeoutError` → `analysis_error.emit(msg)`; всё прочее — лог `traceback.format_exc()` + `analysis_error.emit(str(e))`.
- В `MainWindow.closeEvent` (`main_window.py:1121`) — `worker.wait(3000)` мс перед закрытием.

---

## 5. Конфигурация

### 5.1 Полная таблица параметров `config.json`

Источники дефолтов: `core/defaults.py:8-25` (preprocessing/registration), `main.py:372-387` (analysis/ui/units).

| Ключ | Дефолт | Тип | Описание | Где используется |
|---|---|---|---|---|
| `preprocessing.sor_neighbors` | `20` | int ≥ 1 | Число соседей для Statistical Outlier Removal | `preprocessing.py:remove_outliers`; валидация `main.py:335-337` |
| `preprocessing.sor_std_ratio` | `2.0` | float | Порог отклонения SOR (множитель σ) | `preprocessing.py:remove_outliers` |
| `preprocessing.voxel_size` | `0` | float ≥ 0 или `-1` (sentinel) | Размер вокселя прореживания; `0` — авто (`bbox_diag*0.015`), `-1` — sentinel «отключить» | `preprocessing.py:preprocess_pipeline` |
| `registration.ransac_max_iter` | `200000` | int | Максимум итераций RANSAC | `registration.py:_ransac_multistart` |
| `registration.ransac_n_starts` | `5` | int | Число рестартов RANSAC | `registration.py:_ransac_multistart` |
| `registration.ransac_top_k` | `4` | int | Сколько лучших кандидатов RANSAC попадают в пул гипотез | `registration.py:_ransac_multistart` |
| `registration.icp_coarse_pct` | `5.0` | float | Дистанция грубого ICP в % от `bbox_diag` | `registration.py` |
| `registration.icp_fine_pct` | `1.0` | float | Дистанция точного ICP в % от `bbox_diag` | `registration.py` |
| `registration.icp_max_iter` | `150` | int | Максимум итераций точного прохода ICP | `registration.py:_icp_two_pass` |
| `registration.use_pca_seeds` | `true` | bool | Использовать 4 PCA-затравки для борьбы с 180°-неоднозначностью | `registration.py` |
| `registration.reject_rmse_pct` | `5.0` | float | Порог `registration_suspect` в % от `bbox_diag` | `registration.py:463-473` |
| `registration.alignment_mode` | `"best_fit"` | str | `"best_fit"` или `"conservative"` (см. §6.2) | `registration.py:533-543` |
| `analysis.tolerance_mm` | `0.5` | float > 0 | Допуск ± мм; точки в `±tolerance` считаются «в допуске» | `worker.py:209`, `deviation.py`, `colorize_point_cloud`; валидация `main.py:329-331` |
| `analysis.conformance_threshold` | `95` | float ∈ [0,100] | Целевая доля точек в допуске (вердикт) | `report.py`, `ResultsPanel`; валидация `main.py:332-334` |
| `analysis.worst_points_n` | `10` | int | Размер списка worst-points | `worker.py:210`, `compute_statistics` |
| `ui.advanced_mode` | `false` | bool | В базовом режиме `worker.py:125-129` подменяет preprocessing/registration на `BASIC_DEFAULTS` | `worker.py:124`, `ControlPanel` |
| `ui.last_dir` | `""` | str | Последний каталог в файловых диалогах | `main_window.py` |
| `ui.colormap` | (не в дефолтах `main.py`; fallback `"RdYlGn_r"`) | str | Имя matplotlib-colormap для раскраски и легенды | `worker.py:246`, `viewer_widget.py:260`, `report.py:174` |
| `units.cad` | `"mm"` | str | Единица CAD-файла; ключ `UNIT_TO_MM` | `project_manager.py:168` |
| `units.scan` | `"mm"` | str | Единица скана | `project_manager.py:221` |

Примечание: ключ `ui.colormap` не объявлен в дефолтах `main.py:379-382`, но используется в коде через `.get(..., "RdYlGn_r")`. Поэтому при отсутствии в `config.json` применяется fallback.

### 5.2 `load_config` и глубокое слияние

`main.py:363-404`:
1. Импорт `BASIC_DEFAULTS` из `core.defaults` (`main.py:370`).
2. Формирование полного словаря дефолтов: `{**BASIC_DEFAULTS, "analysis": {...}, "ui": {...}, "units": {...}}` (`main.py:372-387`).
3. Если `config.json` отсутствует — лог `warning`, валидация и возврат дефолтов (`main.py:389-392`).
4. Иначе — чтение JSON, лог `info`, **deep merge** через `_deep_merge(defaults, config)` (`main.py:398`).
5. Валидация диапазонов через `_validate_config_ranges(merged)` (`main.py:399`).
6. При любом исключении чтения — лог `error`, валидация дефолтов и возврат (`main.py:401-404`).

**`_deep_merge(base, override)`** (`main.py:301-314`): рекурсивно сливает словари. Если оба значения по ключу — `dict`, мерджит их рекурсивно (не заменяет секцию целиком); иначе значение из `override` перекрывает. Не мутирует входы.

В `core/project_manager.py:39-74` действует аналогичный мердж при загрузке проекта с валидацией типов: `_types_compatible` запрещает подмену `int/float ↔ bool`, `str ↔ число`, `list ↔ dict`; несовместимые поля пропускаются с warning.

### 5.3 Валидация диапазонов: `_validate_config_ranges`

`main.py:317-360` — четыре правила:

| Параметр | Допустимо | Дефолт при нарушении |
|---|---|---|
| `analysis.tolerance_mm` | `> 0`, не `bool` | `0.5` |
| `analysis.conformance_threshold` | `∈ [0, 100]`, не `bool` | `95` |
| `preprocessing.sor_neighbors` | `int ≥ 1`, не `bool` | `20` |
| `preprocessing.voxel_size` | `≥ 0` или `== -1` (sentinel), не `bool` | `-1` |

Алгоритм: пройти по `key_path`, найти leaf-узел; если не словарь — пропустить; иначе применить `predicate(value)`; при `False` — warning и сброс к дефолту in-place. Bool явно отсеивается через `not isinstance(v, bool)`.

### 5.4 UNIT_TO_MM

`core/project_manager.py:30-36`:

```python
UNIT_TO_MM: dict[str, float] = {
    "mm":    1.0,
    "cm":   10.0,
    "m":  1000.0,
    "in":   25.4,
    "as_is": 1.0,
}
```

Применяется ДО любых вычислений AABB/нормалей:
- `load_cad`: `factor = UNIT_TO_MM.get(unit, 1.0)`; если `factor != 1.0`, вызывается `mesh.scale(factor, center=(0,0,0))` (`project_manager.py:177-180`).
- `load_scan`: симметрично для `pcd.scale` (`project_manager.py:233-236`).
- Единица берётся из аргумента `unit` либо из `config["units"]["cad"]`/`["units"]["scan"]` (`project_manager.py:167-168, 220-221`).
- При загрузке проекта единицы восстанавливаются из явных полей `unit_cad`/`unit_scan` JSON (`project_manager.py:335-336`); fallback — из `config["units"]`.

UI-комбобоксы единиц (`_UNIT_ITEMS` в `panels.py:26-31`) предлагают пункты «мм», «см», «м», «дюйм» (→ `mm/cm/m/in`).

---

## 6. Алгоритмы

### 6.1 preprocessing.py

Файл `core/algorithms/preprocessing.py` (147 строк) реализует предобработку входного облака перед регистрацией. В нём две примитивных операции (SOR и Voxel Grid) и собирающий их в конвейер `preprocess_pipeline`. Импорты (строки 11–13): `logging`, `open3d as o3d`, `numpy as np`. Логгер модуля — `logger = logging.getLogger(__name__)` (15).

#### remove_outliers (18–60)

Сигнатура: `remove_outliers(pcd, nb_neighbors=20, std_ratio=2.0) -> o3d.geometry.PointCloud`.

Алгоритм:
1. `n_before = len(pcd.points)` (37).
2. Защита от слишком малых облаков: если точек меньше 10 — warning и возврат входного облака без изменений (39–41).
3. Лог числа точек до фильтрации (43).
4. `pcd.remove_statistical_outlier(nb_neighbors, std_ratio)` (45–48): для каждой точки среднее расстояние до `nb_neighbors` ближайших соседей; точки, у которых это среднее > `mean + std_ratio * std`, удаляются.
5. Лог удалённых и итогового размера (50–52).
6. Если после фильтрации меньше 100 точек — warning о слишком строгой настройке (54–58).

Граничные случаи: <10 точек → пропуск; <100 после фильтрации → warning (не ошибка).

#### voxel_downsample (63–95)

Сигнатура: `voxel_downsample(pcd, voxel_size=0.1) -> o3d.geometry.PointCloud`.

1. Лог `n_before` и `voxel_size` (79).
2. `pcd.voxel_down_sample(voxel_size)` (81) — пространство делится на кубики со стороной `voxel_size`, в каждом непустом кубике все точки заменяются центроидом.
3. Защита: если результат пуст (например, `voxel_size` слишком велик) — warning и возврат исходного `pcd` (85–90).
4. Лог коэффициента `ratio = n_before / max(n_after, 1)` (92–93).

Граничные случаи: пустой результат → возврат исходного облака; `max(n_after, 1)` страхует от деления на ноль.

#### preprocess_pipeline (98–147)

Сигнатура: `preprocess_pipeline(pcd, config, progress_callback=None) -> (pcd_clean, pcd_down, voxel_size)`.

Шаги:
1. **SOR** (116–122): `remove_outliers(pcd, pre["sor_neighbors"], pre["sor_std_ratio"])`. После — `progress_callback(15)`.
2. **Авторасчёт `voxel_size`** (124–140):
   - `raw_voxel = pre["voxel_size"]`; `try/except (ValueError, TypeError)` → `0.0` (127–130).
   - Условие `if not (voxel_size > 0)` (133) — намеренно через отрицание, чтобы корректно ловить NaN (`NaN <= 0` ложно).
   - **Формула**: `voxel_size = bbox_diag * 0.015` (1.5% от диагонали AABB облака).
3. **Voxel downsampling** (142–145): `voxel_downsample(pcd_clean, voxel_size)`. После — `progress_callback(25)`.

Нормали в этом конвейере **не вычисляются** — `registration.py` рассчитает их с правильным радиусом под масштаб модели (комментарий 105–106).

### 6.2 registration.py

Файл `core/algorithms/registration.py` (572 строки) — главный модуль регистрации скана с CAD. Реализует пайплайн с защитой от ложных 180°-минимумов, мультистартом RANSAC, выбором лучшей гипотезы по C2M-RMSE и двухпроходным ICP. Исключение `RegistrationError(RuntimeError)` объявлено на строках 24–25.

#### Полный пайплайн register_pipeline (288–572)

Сигнатура: `register_pipeline(pcd_full, pcd_down, mesh, config, progress_callback=None, pcd_voxel_size=0.0) -> (pcd_registered, transformation, rmse, registration_suspect, reg_diagnostics)`.

**Шаг 1 — Адаптивные параметры (308–313).** `ap = _compute_adaptive_params(mesh)`. Если `bbox_diag < 1e-6` — `RegistrationError("CAD-меш вырожден (нулевой bbox)")`.

**Шаг 1.5 — Решение о повторном прореживании (315–339).** Сравнивается адаптивный `reg_voxel = ap["voxel_size"]` с переданным `pcd_voxel_size`. Если оба положительны и относительная разница ≤ 20% (`abs(reg-pcd)/max(reg,pcd) <= 0.2`) — используется уже прореженное `pcd_down`. Иначе пересчёт: `pcd_full.voxel_down_sample(reg_voxel)`. Если осталось < 50 точек — откат на исходное `pcd_down` с warning. После — `progress_callback(35)`.

**Шаг 2 — Подготовка облаков (341–346).** `_prepare_clouds(pcd_full, pcd_down_new, mesh, ap, _prog_start=35, _prog_end=45)` возвращает `(mesh_pcd_full, mesh_pcd_down)` — облака, равномерно сэмплированные с меша, и попутно рассчитывает нормали `pcd_full`/`pcd_down_new`.

**Шаг 3 — Центроидное предвыравнивание (348–360).** `T_centroid` = трансляция на `t = c_mesh - c_pcd`, применяется к копиям `pcd_full` и `pcd_down_new`. После — `progress_callback(45)`.

**Шаг 4 — FPFH-дескрипторы (362–368).** `_compute_fpfh(pcd_down_aligned, ap["fpfh_radius"])` и `_compute_fpfh(mesh_pcd_down, ap["fpfh_radius"])`. После — `progress_callback(52)`.

**Шаг 5 — Сборка пула гипотез (370–419).** Чтение `ransac_max_iter`, `ransac_n_starts` (5), `ransac_top_k` (4), `use_pca_seeds` (True). **BVH меша строится один раз**: `mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(mesh); scene = RaycastingScene(); scene.add_triangles(mesh_t)` (377–379) — переиспользуется всеми кандидатами. Базовая гипотеза `[np.eye(4)]`. При `use_pca_seeds=True` добавляются 4 PCA-гипотезы. Запускается `_ransac_multistart`; для каждого RANSAC-результата с `fitness > 0.01` (409) трансформация добавляется. После — `progress_callback(65)`.

**Шаг 6 — Выбор победителя по C2M-RMSE (421–461).** `icp_dist1 = bbox_diag * coarse_pct/100`, `icp_dist2 = bbox_diag * fine_pct/100`. Для каждой `T_h` — `_evaluate_candidate` → `(c2m_rmse, T_refined)`. Победитель — с минимальным `c2m_rmse`. Если **все** провалили — победитель `hypotheses[0]` (identity), warning. После — `progress_callback(68)`.

**Шаг 7 — Валидационный шлюз (463–473).** `reject_thresh = bbox_diag * reject_rmse_pct/100`. `registration_suspect = bool(best_c2m_rmse > reject_thresh)`. При `True` — warning, но регистрация **не прерывается**.

**Шаг 8 — Финальный двухпроходный ICP (475–493).** `_icp_two_pass(pcd_full_aligned, mesh_pcd_full, best_T, icp_dist1, icp_dist2, icp_max_iter, timeout=60, _prog_mid=76)` → `(r_coarse, r_fine)`. После — `progress_callback(80)`.

**Шаг 9 — Диагностика поглощённого отклонения (495–531).** См. ниже.

**Шаг 10 — Выбор финальной трансформации по `alignment_mode` (533–553).**

**Финал — `T_total` и `reg_diagnostics` (545–572).**

#### _compute_adaptive_params (32–54)

Формулы (41–46):
- `extent = bbox.get_extent()`.
- `bbox_diag = ||extent||₂`.
- `voxel_size = bbox_diag * 0.02` (2%).
- `fpfh_radius = bbox_diag * 0.05` (5%).
- `ransac_distance = bbox_diag * 0.03` (3%).

Все пороги — доли диагонали bbox CAD, что делает алгоритм масштабно-инвариантным.

#### pca_alignment_candidates (105–139)

`pca_frame(pts)` (114–119): центр `c = pts.mean(0)`; ковариация `cov = np.cov((pts-c).T)`; `eigvals, eigvecs = np.linalg.eigh(cov)` — значения по возрастанию; сортировка по убыванию: `idx = np.argsort(eigvals)[::-1]`; возврат `(c, V)`.

**4 гипотезы.** PCA-оси знаково неоднозначны. Перебираются 4 варианта знаков `(s1, s2)` первых двух осей; знак третьей `s3` вычисляется так, чтобы `det(R) = +1` (исключение зеркал).

**det(R)=+1.** `R = V_mesh @ S @ V_pcd.T`, `S=diag(s1,s2,s3)`. `det(R) = det(V_mesh)·det(S)·det(V_pcd)`. Чтобы `det(R)=+1`, нужно `s1·s2·s3 = det(V_mesh)·det(V_pcd)`. В коде (126): `target_det_S = int(round(det(V_mesh) * det(V_pcd)))`, далее `s3 = target_det_S * s1 * s2` (131).

Сборка (132–138): `R = V_mesh @ S @ V_pcd.T`, `t = c_mesh - R @ c_pcd`, `T[:3,:3]=R; T[:3,3]=t`.

#### _ransac_multistart (142–192)

Параметры внутреннего RANSAC (155–169):
- `mutual_filter=True` — взаимные лучшие соответствия в FPFH-пространстве.
- `max_correspondence_distance = ransac_dist`.
- `TransformationEstimationPointToPoint(False)` (без масштабирования).
- `ransac_n = 3`, чекеры `CorrespondenceCheckerBasedOnEdgeLength(0.9)` и `CorrespondenceCheckerBasedOnDistance(ransac_dist)`.
- `RANSACConvergenceCriteria(ransac_max_iter, 0.9999)`.

**Multistart-логика.** Цикл по `n_starts` независимых запусков (RANSAC недетерминирован). Результаты собираются; при ошибке стартапа — warning. **Top-K**: сортировка по убыванию `fitness`, первые `top_k`. Если пусто — возвращается `[]`, пайплайн продолжит на identity + PCA.

#### _evaluate_candidate (195–224)

Сигнатура: `(c2m_rmse, T_refined) = _evaluate_candidate(pcd_down_aligned, mesh_pcd_down, scene, T_init, icp_dist, max_iter=50)`.

Алгоритм:
1. `pcd_tmp = copy.deepcopy(pcd_down_aligned).transform(T_init)`.
2. Быстрый Point-to-Plane ICP: `registration_icp(pcd_tmp, mesh_pcd_down, icp_dist, np.eye(4), TransformationEstimationPointToPlane(), ICPConvergenceCriteria(max_iteration=max_iter))`. Заметьте: `T_init` уже применён к облаку; init — identity.
3. `T_refined = result.transformation @ T_init` — итоговая трансформация из исходного `pcd_down_aligned` в финальное положение.
4. **C2M-RMSE через BVH** (заранее построенная `scene`):
   - `pts = np.asarray(pcd_eval.points).astype(np.float32)`;
   - `dists = scene.compute_distance(o3d.core.Tensor(pts)).numpy()`;
   - `c2m_rmse = sqrt(mean(dists²))`.
5. Возврат `(c2m_rmse, T_refined)`.

Принципиальная экономия: BVH меша не пересобирается для каждого кандидата.

#### _icp_with_timeout (227–247)

Создаёт `ThreadPoolExecutor(max_workers=1)`, отправляет `registration_icp(...)` (Point-to-Plane), ждёт через `fut.result(timeout)`. При `concurrent.futures.TimeoutError` — `TimeoutError("Совмещение не сходится. Возможно, загружены файлы разных деталей.")`. В `finally` — `executor.shutdown(wait=False)` (поток-сирота не удерживает процесс).

#### _icp_two_pass (250–281)

- **Проход 1 — грубый** (261–266): `dist1`, `ICPConvergenceCriteria(max_iteration=80)`, init — `init_T`. Результат `r1`.
- `progress_callback(_prog_mid)` (по умолчанию 76).
- **Проход 2 — точный** (271–279): `dist2`, `ICPConvergenceCriteria(max_iteration=max_iter, relative_fitness=1e-6, relative_rmse=1e-6)`, init — `r1.transformation`. Результат `r2`.

Возврат — `(r1, r2)`; оба нужны для диагностики.

#### Диагностика поглощённого отклонения (498–531)

Анализ, **сколько отклонения «съел» точный проход**:
1. `T_delta = T_fine @ inv(T_coarse)`.
2. `fine_pass_shift_mm = ||T_delta[:3,3]||₂`. Поворот — из `cos(α) = (trace(R_delta) − 1)/2` с клипом в [−1,+1]: `fine_pass_rot_deg = degrees(arccos(cos_α))`.
3. Функция `_c2m_stats_down(T)` (511–517) возвращает `(rmse, доля_в_допуске)` для downsampled-облака через ту же `scene`.
4. `absorbed_deviation_mm = rmse_coarse - rmse_bestfit` (мм).
5. `absorbed_within_tol_pct = within_tol_bestfit - within_tol_coarse` (доля, может быть отрицательной).

Цель: пользователь должен видеть, не «дорегистрировал» ли алгоритм деталь в допуск за счёт сдвига, что на реальной оснастке невозможно.

#### alignment_mode: best_fit vs conservative (533–543)

- `alignment_mode = config["registration"].get("alignment_mode", "best_fit")`.
- `"conservative"`: `T_selected = T_coarse`, `rmse_out = r_coarse.inlier_rmse` — имитация фиксированного базирования.
- `"best_fit"` (по умолчанию): `T_selected = T_fine`, `rmse_out = r_fine.inlier_rmse` — наилучшее вписывание.

`pcd_registered = pcd_full_aligned.transform(T_selected)`.

#### Валидационный шлюз (registration_suspect) (463–473)

Порог `reject_thresh = bbox_diag * reject_rmse_pct/100` (5% по умолчанию). При `best_c2m_rmse > reject_thresh` — `registration_suspect=True`, warning, **регистрация не прерывается**. Флаг возвращается наружу. После шага 8 — пост-проверка (554–558): если `rmse_out > bbox_diag * 0.05` — отдельный warning.

#### T_total = T_selected @ T_centroid — семантика (548)

`T_total` — итоговая 4×4-матрица, переводящая исходное `pcd_full` сразу в финальное положение:

- Сначала `T_centroid` (предвыравнивание по центру масс);
- Затем `T_selected` (best-fit или conservative).
- В матричной нотации: `p_final = T_selected · T_centroid · p_initial` ⇒ `T_total = T_selected @ T_centroid`.

Комментарий в коде (546–547): без сохранения `T_centroid` применение `T_selected` к свежезагруженному облаку не воспроизведёт совмещение. Поэтому в NPZ сохраняется именно композиция (тест `test_transformation_includes_centroid` проверяет, что повторное применение `T_total` к `pcd_clean` даёт `pcd_registered` с RMSE < 1e-6 мм).

`reg_diagnostics` (560–570) содержит: `fine_pass_shift_mm`, `fine_pass_rot_deg`, `rmse_coarse`, `rmse_bestfit`, `absorbed_deviation_mm`, `within_tolerance_coarse`, `within_tolerance_bestfit_down`, `absorbed_within_tol_pct`, `alignment_mode`.

### 6.3 deviation.py

Файл `core/algorithms/deviation.py` (429 строк) реализует C2M-расчёт, статистику, поиск worst-точек, кластеризацию дефектов и раскраску. Знаковая семантика (6–8): **`+` — снаружи CAD** (избыток материала), **`−` — внутри** (недостаток).

#### compute_deviations (29–127)

Сигнатура: `compute_deviations(pcd_registered, mesh, progress_callback=None) -> (signed_distances, ambiguous_mask)`.

**Общая часть (55–69).** Точки → `float32`. Строится `RaycastingScene`. Всегда вызывается `scene.compute_closest_points(query_points)` → `closest_points` и `primitive_normals`. Вычисляются `vectors = points - closest_points`, `distances_unsigned = ||vectors||₂`, `dots = einsum("ij,ij->i", vectors, primitive_normals)`.

**Ветвь watertight (71–103).** Если `mesh.is_watertight()`:
1. `sd_values = scene.compute_signed_distance(query_points).numpy()` — winding-number-знак.
2. Конвенция Open3D (проверена тестом на кубе): `sd > 0` снаружи (наш `+`), `sd < 0` внутри (наш `−`), **инверсия не нужна**.
3. `sign_sd = np.sign(sd_values)`; нули → `+1.0`.
4. **Sanity-check** (78–91): `mismatch_mean = mean(|abs_sd − distances_unsigned|)`; порог `max(1e-3, bbox_diag * 1e-4)`. При превышении — warning.
5. `signed_distances = abs_sd * sign_sd` (модуль из winding, знак из winding).
6. **`ambiguous_mask`**: где эвристика по нормали расходится с winding-знаком. Типично для срединных поверхностей тонких стенок.

**Ветвь не-watertight (104–115).** Warning о ненадёжности. Используется только эвристика:
- `cos_angle = dots / (distances_unsigned + 1e-10)`;
- `ambiguous_mask = |cos_angle| < 0.05` (вектор почти параллелен грани);
- `heuristic_signs = +1 если dots≥0 иначе −1`;
- `signed_distances = distances_unsigned * heuristic_signs`.

После — `progress_callback(88)`.

#### Знак отклонений и ambiguous_mask

- **Watertight**: знак абсолютно надёжен (winding-number). `ambiguous_mask` — точки, где старая эвристика (нормаль) дала бы другой знак (маркер срединных поверхностей).
- **Не-watertight**: знак эвристический. `ambiguous_mask` помечает только окрестности рёбер (вектор почти в плоскости грани).

В визуализации точки с `ambiguous_mask=True` окрашиваются нейтральным серым.

#### compute_statistics (130–216)

Сигнатура: `compute_statistics(deviations, tolerance, ambiguous_mask=None, point_coords=None, worst_n=10, min_cluster_size=3) -> dict`.

**Защита от пустого ввода** (150–169): `n == 0` → нулевые метрики и warning.

**Метрики и формулы** (171–192):
- `abs_dev = |deviations|`;
- `within_tolerance = sum(abs_dev ≤ tolerance) / n`;
- `n_over = sum(deviations > tolerance)`, `n_under = sum(deviations < -tolerance)`;
- `mean_deviation = mean(deviations)`; `median_deviation = median(deviations)`;
- `rmse = sqrt(mean(deviations²))`;
- `max_deviation`, `min_deviation`, `max_abs_deviation`, `std_deviation`;
- `percentile_95 = percentile(abs_dev, 95)`, `percentile_99 = percentile(abs_dev, 99)`;
- `over_material_pct = n_over / n`, `under_material_pct = n_under / n`;
- `n_points = n`, `tolerance = float(tolerance)`.

**Неоднозначность** (194–196): `ambiguous_sign_count = sum(ambiguous_mask)`, `ambiguous_sign_pct = count/n`.

**Worst-points и кластеры** (198–205): если переданы `point_coords` — вызываются `_build_worst_points` и `_build_defect_clusters`.

#### worst_points (`_build_worst_points`, 219–279)

1. `candidate_mask = abs_dev > tolerance`.
2. `unfiltered_idx = argsort(abs_dev)[::-1][:worst_n]` — топ-N без фильтрации.
3. Если кандидатов < `min_cluster_size` — возврат нефильтрованных топ-N, флаг `worst_points_unfiltered=True`, `noise_outlier_count=0`.
4. **Фильтрация шума по локальной плотности**:
   - `bbox_diag = ||coords.max − coords.min||₂`;
   - `avg_step = bbox_diag / n^(1/3)`;
   - `radius = 3.0 * avg_step`;
   - KDTree по `candidate_coords`; для каждой точки считается `k`-соседей в радиусе;
   - Порог: `threshold = min_cluster_size + 1` (точка считает саму себя — комментарий 254–255);
   - Точка «реальный дефект», если `k ≥ threshold`.
5. `noise_count = sum(~real_defect_local_mask)`.
6. Если после фильтрации пусто — возврат нефильтрованных топ-N (флаг `True`, подсчёт шума).
7. Иначе — топ-N среди подтверждённых; флаг `False`.

Возврат: `{worst_points: [{x,y,z,dev}], worst_points_unfiltered: bool, noise_outlier_count: int}`.

`_build_defect_clusters` (282–367) повторяет фильтрацию по плотности, затем BFS по соседям в радиусе на массиве настоящих дефектов. Кластеры размером ≥ `min_cluster_size` принимаются; тип («Избыток материала» при положительном среднем, иначе «Недостаток»), `max_deviation`, `point_count`, центр масс. Сортировка по `max_deviation` убыванию.

#### colorize_point_cloud (396–429)

**LUT-кеш** (382–393): глобальный `_LUT_CACHE: dict[str, ndarray]`. `_get_lut(name)` лениво строит таблицу 256×3 (float32) через `matplotlib.pyplot.get_cmap(name)(np.linspace(0,1,256))[:,:3]` и кеширует. Импорт matplotlib — внутри функции (отложенный).

**Шкала отклонений** (411–415):
- `span = 2.0 * tolerance`;
- `idx = (dev + tolerance) * (255 / span)` — линейное отображение `[-tol, +tol]` → `[0, 255]`;
- `np.clip(idx, 0, 255)` — точки вне диапазона прижимаются к крайним цветам;
- `colors = lut[idx.astype(np.uint8)]`.

**Серый для ambiguous** (417–418): соответствующие точки перекрашиваются в `[0.55, 0.55, 0.55]`.

**Защита от shared-памяти** (420–428): создаётся новое облако, координаты копируются **явно через `.copy()`** — иначе `pcd_colored.points = pcd.points` дал бы shared `Vector3dVector`.

### 6.4 dimensions.py

Файл `core/algorithms/dimensions.py` (146 строк) — расчёт габаритов CAD и скана в единой системе отсчёта.

#### UNIT_HINT_RATIOS (23–28) и suggest_unit_mismatch_hint (31–40)

```python
UNIT_HINT_RATIOS = [
    (10.0,   "возможно, один файл в см, другой в мм"),
    (25.4,   "возможно, один файл в дюймах, другой в мм"),
    (100.0,  "возможно, один файл в м, другой в см"),
    (1000.0, "возможно, один файл в м, другой в мм"),
]
```

`suggest_unit_mismatch_hint(ratio, tol=0.15)`: перебирает таблицу, и если `|ratio/known − 1| ≤ tol` (15% по умолчанию) — возвращает подсказку. Иначе — пустая строка.

#### bbox_summary (43–54)

Сигнатура: `bbox_summary(geom) -> ((Lx, Ly, Lz), diag)`. Простой AABB-габарит для быстрого логирования после загрузки геометрии.

#### compute_dimensions (57–146)

Сигнатура: `compute_dimensions(mesh, pcd_registered=None) -> dict`.

Алгоритм:
1. `verts = np.asarray(mesh.vertices, float64)`. Пуст → нули с warning.
2. `obb = mesh.get_oriented_bounding_box()` → `center`, `R` (3×3).
3. **Проверка невырожденности** (103): `if abs(det(R)) < 0.5` → `use_obb = False` (откат на AABB). Аналогично при исключении.
4. **При OBB** (109–111): `verts_local = (verts − center) @ R`, `cad_extent = verts_local.max(0) − verts_local.min(0)` — истинный размер по главным осям модели.
5. **Fallback на AABB** (113–115): `raw = mesh.get_axis_aligned_bounding_box().get_extent()`, **сортировка по убыванию**: `cad_extent = np.sort(raw)[::-1]`. Сортировка делает экстенты однонаправленными, чтобы дельта со сканом имела смысл без общей системы координат.
6. `cad_diag = ||cad_extent||₂`.
7. Если передан `pcd_registered` (124–138) — аналогично: проекция точек или сортированный AABB, вычисление `scan_extent`, `scan_diag`. Дельта `delta = scan_extent − cad_extent`.

Возврат: `{"cad", "scan"|None, "delta"|None, "cad_diag", "scan_diag"|None}`.

### 6.5 report.py

Файл `core/algorithms/report.py` (565 строк) формирует 3-страничный PDF через `reportlab` + `matplotlib`. Бэкенд `Agg` ставится сразу при импорте (17). Глобальные константы (34–36): `PAGE_W, PAGE_H = A4`, `MARGIN = 18 * mm`, `USABLE_W = PAGE_W − 2*MARGIN`.

#### Шрифты — `_register_fonts` (41–54)

Приоритет:
1. `FreeSans.ttf` / `FreeSans-Bold.ttf` (PATH/CWD).
2. `C:/Windows/Fonts/arial.ttf` / `C:/Windows/Fonts/arialbd.ttf`.
3. **Fallback**: `Helvetica` / `Helvetica-Bold` (без кириллицы) — error в лог.

Регистрируется под именами `_RptReg` / `_RptBold`. Возврат — пара `(font_reg, font_bold)`.

#### Гистограмма — `_create_histogram` (59–79)

- Шрифт matplotlib: «DejaVu Sans».
- Figure `(8, 3.8)` дюйма, `dpi=120`.
- `n_bins = max(30, min(80, n//30))` — адаптивно.
- Цвета: бары `#4a90d9`, обводка `#2c5f8a`, alpha 0.85; +tol красная `#e53935`, −tol зелёная `#43a047` (пунктир, 1.5).
- Подписи: «Отклонение, мм», «Количество точек», «Распределение отклонений».
- Сетка Y, alpha 0.3; Y-форматтер: целые с пробелом-разделителем.
- Сохранение `dpi=120, bbox_inches="tight"`.

#### Цветовая шкала — `_create_colorbar` (82–103)

- Figure `(7, 1.0)`, `dpi=110`.
- Градиент `np.linspace(-tol, tol, 256).reshape(1,-1)`, `extent=[-tol, tol, 0, 1]`.
- 5 тиков `[-tol, -tol/2, 0, tol/2, tol]`, средний — `"0"`, остальные `"%+.3f"`.
- Подпись: «Отклонение, мм (−tol мм — недостаток материала, +tol мм — избыток; точки вне диапазона → крайний цвет шкалы)».

#### generate_report (108–565) — 3 страницы

Сигнатура: `generate_report(output_path, cad_path, scan_path, deviations, stats, registration_rmse, screenshot_paths=None, mesh_triangles=0, config=None, unit_cad="mm", unit_scan="mm") -> str`.

Подготовка (128–181): `_register_fonts`, `cbar_path=None; hist_path=None` (инициализация до `try` — для безопасного `finally`), прокачка `styles.byName` всем шрифтом `font_reg`. Параметры: `tolerance` (из `stats["tolerance"]` → `config.analysis.tolerance_mm` → `0.5`); `within_pct = stats["within_tolerance"] * 100`; `threshold = config.analysis.conformance_threshold` (95); `passed = within_pct ≥ threshold`; `colormap = config.ui.colormap` (`"RdYlGn_r"`).

**Страница 1** (183–404):
1. Заголовок «ОТЧЁТ О КОНТРОЛЕ ГЕОМЕТРИЧЕСКОЙ ТОЧНОСТИ» (`#1A237E`) + линия `#3949AB` 1.5 pt.
2. Дата `datetime.now().strftime('%d.%m.%Y %H:%M:%S')`.
3. **Таблица «Входные данные»** (199–235): CAD-модель, треугольники, облако, точек, единицы (через `_unit_labels`), допуск. Шапка белым по `#3949AB`, чередование строк `#F5F5F5`/белый.
4. **Таблица «Результаты измерений»** (238–268): среднее, RMSE (= `registration_rmse`), мин/макс, доля в допуске, избыток/недостаток %, неоднозначные %.
5. **Таблица «Габаритные размеры»** (271–311): если `stats["dimensions"]` — CAD `(Lx, Ly, Lz, диагональ)`, при наличии — Скан и `Δ (Скан − CAD)`.
6. **Таблица «Диагностика регистрации»** (313–354): если в `stats` есть `fine_pass_shift_mm` или `rmse_coarse`. Все поля `reg_diagnostics` плюс перевод `alignment_mode` через `_mode_labels`.
7. **«Технологическая интерпретация»** (357–381): динамические строки про недостаток, избыток, max |отклонение|, при |abs_pp|>0.5 — предупреждение о маскировке.
8. **Заключение/Verdict** (384–404): зелёный «СООТВЕТСТВУЕТ» (`#1B5E20` на `#E8F5E9`) или красный «НЕ СООТВЕТСТВУЕТ» (`#B71C1C` на `#FFEBEE`).

**Страница 2** (406–459): `PageBreak`, заголовок «Визуализация отклонений», 6 видов в сетке 3×2 (`view_labels = ["Спереди","Сзади","Слева","Справа","Сверху","Изометрия"]`), картинки `IMG_W = (USABLE_W − 6mm)/2`, `IMG_H = IMG_W * 0.62`. При отсутствии скриншота — параграф «(скриншот недоступен)». **Легенда** через `_create_colorbar`, высота 28 мм.

**Страница 3** (461–550): `PageBreak`, «Распределение отклонений». **Гистограмма** через `_create_histogram`, `width=USABLE_W, height=USABLE_W * 0.46`. **Таблица «Точки с наибольшим отклонением»**: «#, X, Y, Z, Откл.» (шапка `#37474F`). **Таблица «Обнаруженные дефекты»**: «#, Тип, Макс.откл., Точек, X, Y, Z».

Сборка (552–565): `doc.build(story)` в `try`; в `finally` — удаление временных файлов `hist_path` и `cbar_path` через `os.unlink`. Возврат — `output_path`.

### 6.6 defaults.py

Файл `core/defaults.py` (25 строк) — единый источник истины для параметров базового режима.

```python
BASIC_DEFAULTS = {
    "preprocessing": {
        "sor_neighbors": 20,
        "sor_std_ratio": 2.0,
        "voxel_size": 0,                # 0 → авторасчёт (1.5% от диагонали bbox облака)
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
```

Используется в `main.py:370` (как часть дефолтного конфига) и в `core/worker.py:125-129` (в базовом режиме `ui.advanced_mode=False` секции `preprocessing` и `registration` принудительно подменяются `BASIC_DEFAULTS` через `copy.deepcopy`).

---

## 7. Интерфейс пользователя

Пользовательский интерфейс реализован на PyQt6 и состоит из главного окна `MainWindow`, четырёх боковых/центральных панелей (`ControlPanel`, `ResultsPanel`, `LogPanel`, `ViewerWidget`) и двух модальных диалогов (`HelpDialog`, `AboutDialog`).

### 7.1 MainWindow (`ui/main_window.py`)

Класс `MainWindow(QMainWindow)` объявлен в строке 49 и принимает `config`. Конструктор (52–79) задаёт заголовок «Модуль анализа отклонений геометрии деталей», минимальный размер `1100×700`, начальный — `1280×800`, включает drag&drop (`setAcceptDrops(True)`, 73). Поля состояния:
- `_analysis_start` — момент старта анализа (59);
- `_current_status` — текст состояния (60);
- `_heavy_params_dirty` — флаг изменения «тяжёлого» параметра (61);
- `_last_dir` (62);
- `_analysis_state` — `idle | preparing | running` (66).

#### Структура окна

Метод `_setup_ui()` (83–87) вызывает четыре подметода:

| Элемент | Метод | Строки |
|---|---|---|
| Меню | `_create_menu()` | 89–142 |
| Тулбар | `_create_toolbar()` | 144–183 |
| Статусбар | `_create_status_bar()` | 185–205 |
| Центральная область | `_create_central_widget()` | 207–260 |

Меню верхнего уровня: «Файл» (93) и «Справка» (131).

**Тулбар** «Основные действия» (145), `setIconSize(QSize(24,24))` (146), `setMovable(False)` (147). Кнопки (150–154):
- «Загрузить CAD-модель» (`btn_load_cad`);
- «Загрузить облако точек» (`btn_load_scan`);
- «▶ Запустить анализ» (`btn_run`) — розовая (стили 162–167);
- «■ Отмена» (`btn_cancel`) — тёмно-красная, скрыта (168–172);
- «Сохранить отчёт PDF» (`btn_report`).

На кнопку отмены навешивается фильтр `_ArrowOnHoverFilter` (174–175), который подменяет глобальный `WaitCursor` на стрелку при наведении, чтобы кнопка оставалась «кликабельной» во время анализа.

**Статусбар** (185–205): `status_info_label` («Модель | Скан | Статус», мин. ширина 300), `_stage_label` (курсив, цвет `#e91e63`, ширина 240, скрыт по умолчанию), `progress_bar` (фикс. ширина 180, скрыт).

**Центральная область** (207–260) — горизонтальный `QSplitter`. Слева — вертикальный сплиттер с ограничением 220–320 px: сверху `ControlPanel` в `QScrollArea`, снизу `ResultsPanel`. Справа — вертикальный layout: `ViewerWidget` (мин. высота 300, растягиваемый) и `LogPanel` (фикс. высота).

#### QAction в меню

| Действие | Строки | Шорткат | Слот |
|---|---|---|---|
| «Загрузить CAD-модель...» | 95–98 | `Ctrl+O` | `load_cad` |
| «Загрузить облако точек...» | 100–103 | `Ctrl+Shift+O` | `load_scan` |
| «Сохранить проект...» | 107–110 | `Ctrl+S` | `save_project` |
| «Открыть проект...» | 112–115 | `Ctrl+P` | `open_project` |
| «Сохранить отчёт PDF...» | 119–122 | `Ctrl+R` | `save_report` |
| «Выход» | 125–127 | `Ctrl+Q` | `self.close` |
| «Руководство пользователя» | 133–136 | `F1` | `_show_help` |
| «О программе» | 140–142 | — | `_show_about` |

#### Drag & Drop

`dragEnterEvent` (286–297) и `dropEvent` (299–319). Принципы:
- если `_analysis_state != "idle"` — события игнорируются (даже визуально, чтобы курсор не показывал «можно бросить»);
- `dragEnterEvent` принимает действие только если есть локальные URL (`url.isLocalFile()`);
- `dropEvent` приводит расширение к нижнему регистру (308):
  - `.stl`, `.obj` → `_load_cad_from_path` (309–310);
  - `.ply`, `.pcd`, `.xyz`, `.pts` → `_load_scan_from_path` (311–312);
  - иначе — `QMessageBox.warning` с перечнем форматов (313–319).

#### Горячие клавиши

| Клавиша | Действие |
|---|---|
| `Ctrl+O` | Загрузить CAD-модель |
| `Ctrl+Shift+O` | Загрузить облако точек |
| `Ctrl+S` | Сохранить проект |
| `Ctrl+P` | Открыть проект |
| `Ctrl+R` | Сохранить отчёт PDF |
| `Ctrl+Q` | Выход |
| `F1` | Руководство пользователя |

#### Управление состояниями `_analysis_state`

| Состояние | Где устанавливается | Поведение |
|---|---|---|
| `idle` | Конструктор (66), `_set_analysis_running(False)` (1000), отмена/ошибка/сброс по предупреждениям перед запуском (425, 446, 449, 480) | Всё открыто; drag & drop принимается |
| `preparing` | `run_analysis()` сразу при входе (422) — до проверки готовности | `_is_busy()` блокирует параллельный запуск/загрузку/сохранение |
| `running` | `_set_analysis_running(True)` (1000) | Полная блокировка UI |

`_is_busy(action_label)` (269–282) показывает `QMessageBox.warning` «Анализ выполняется» и возвращает `True`, если `_analysis_state != "idle"`. Вызывается в `load_cad`, `load_scan`, `save_report`, `save_project`, `open_project` (324, 336, 555, 590, 605).

`_set_analysis_running(running)` (999–1038) при `running=True`:
- блокирует `btn_load_cad`, `btn_load_scan`, `btn_run` (1002–1004);
- скрывает `btn_run`, показывает `btn_cancel`, `progress_bar`, `_stage_label` (1005–1008);
- принудительно отключает `btn_report` (1013);
- `control_panel.setEnabled(False)` — комментарий поясняет: иначе смена единиц через `_on_param_changed` могла бы перегрузить `mesh/pcd`, которые держит worker (Open3D не thread-safe) (1015–1019);
- `viewer.set_interactive(False)` (1022);
- `log_panel.set_analysis_running(True)`;
- `QApplication.setOverrideCursor(WaitCursor)` (1028);
- активирует `btn_cancel` и кнопку отмены в LogPanel (1029–1030);
- формат прогресса `%p%` (1031).

При `running=False` — снимает override-курсоры в цикле (1033–1035), сбрасывает `progress_bar` и `_stage_label`.

Дополнительно `_on_param_changed` (956–957) блокирует смену единиц при `_analysis_state != "idle"`.

#### Подключение сигналов AnalysisWorker → слоты

В `run_analysis()` (524–533) через `QueuedConnection`:

| Сигнал | Слот | Строка |
|---|---|---|
| `progress_changed(int)` | `_on_progress` | 528 |
| `stage_changed(str)` | `_on_stage_changed` | 529 |
| `log_message(str)` | `_log` | 530 |
| `analysis_finished(dict)` | `_on_analysis_finished` | 531 |
| `analysis_error(str)` | `_on_analysis_error` | 532 |
| `analysis_cancelled()` | `_on_analysis_cancelled` | 533 |

Перед стартом нового worker'а у предыдущего вызывается `disconnect()` (512–516); то же в `closeEvent` (1126–1129) — защита от отложенных эмитов из очереди событий Qt.

Слоты:
- `_on_progress` (717–718) — `progress_bar.setValue`;
- `_on_stage_changed` (720–721) — текст `_stage_label`;
- `_on_analysis_finished` (723–820) — длительность, проверки качества (`registration_suspect`, `within_tolerance < 50%`, RMSE > 3% диагонали — `QMessageBox.warning` с вопросом «Отменить результаты?», 745–781), `manager.save_results`, обновление `results_panel`, `viewer`, лог диагностики, при `|absorbed_within_tol_pct| > 5 пп` или `|absorbed_deviation_mm| > tolerance` — предупреждение о маскировке (802–820);
- `_on_analysis_error` (822–827) — лог + `QMessageBox.critical`;
- `_on_analysis_cancelled` (829–834) — только лог.

#### Прочие особенности

- `_make_loading_dialog` (1071–1092) показывает indeterminate `QProgressDialog` только для файлов >50 МБ.
- При загрузке скана >5 000 000 точек — предупреждение «Продолжить»/«Отмена» (377–393).
- Перед запуском анализа сравниваются диагонали bbox CAD и скана; если `ratio > 5.0` — модальное предупреждение с подсказкой `suggest_unit_mismatch_hint(ratio)` (455–481).
- `closeEvent` (1111–1174): останов worker'а (`wait(3000)`), при наличии результатов — диалог «Сохранить»/«Не сохранять»/«Отмена», сохранение `config.json`, закрытие plotter.

### 7.2 ControlPanel (`ui/panels.py`)

Класс `ControlPanel(QWidget)` объявлен в строке 53 файла `panels.py`. Сигналы (67–68):
- `param_changed(list, object)` — путь в конфиге + значение;
- `recalculate_requested()` — кнопка быстрого пересчёта.

Поле `_updating` (73) защищает от рекурсивных эмитов при программном обновлении; `_recalc_buttons` (74) хранит ссылки на кнопки `↻`.

#### Простой vs расширенный режим

Чекбокс «Расширенный режим» создаётся в 85–90 с тултипом «Показать все параметры алгоритмов. В базовом режиме используются значения из конфига по умолчанию».

**Базовый режим** (всегда):
- группа «Единицы измерения» — `_build_units_group()` (257–285): комбобоксы CAD и Скан;
- группа «Параметры анализа» — `_build_tolerance_group()` (119–140): «Допуск ±(мм)» (0.001–50.0, шаг 0.05, 3 знака) и «Порог соответствия (%)» (целое 80–100, шаг 1).

**Расширенный режим** — три группы (видимость в `_apply_mode(advanced)`, 360–364):

Группа «Предобработка» (`_preprocess_group`, 148–180):
- «Воксель (мм, 0=авто)» — 0.0–50.0, шаг 0.1, 3 знака, тултип «0 = авто» (156–158);
- «SOR k (соседей)» — 5–100, шаг 1, тултип «Соседей для фильтрации» (164–166);
- «SOR σ (строгость)» — 0.5–5.0, шаг 0.1, 1 знак, тултип «Порог фильтрации шумов» (173–175).

Группа «Регистрация» (`_registration_group`, 183–220):
- «Попытки RANSAC» — 1–20, шаг 1;
- «Грубый ICP (%)» — 1.0–20.0, шаг 0.5, 1 знак;
- «Точный ICP (%)» — 0.1–5.0, шаг 0.1, 1 знак;
- «Итераций ICP» — 10–200, шаг 10.

Группа «Режим выравнивания» (`_alignment_group`, 223–255): подсказка «Наилучшее вписывание: меньше RMSE, но ICP может скрыть реальное отклонение. Консервативный: только грубое совмещение» (228–235), затем `QComboBox` с пунктами `_ALIGNMENT_ITEMS` (34–37): «Наилучшее вписывание» → `best_fit`, «Консервативный» → `conservative`.

При выходе из расширенного режима `MainWindow._on_advanced_mode_changed(False)` (989–997 `main_window.py`) сбрасывает секции `preprocessing` и `registration` на `BASIC_DEFAULTS` и вызывает `control_panel.sync_advanced_widgets()`.

#### Синхронизация полей

`sync_advanced_widgets()` (`panels.py`, 340–358) под флагом `_updating=True` устанавливает значения семи спинбоксов из `self.config["preprocessing"]`/`["registration"]` и выбирает текущий пункт `_alignment_combo`. `apply_config(config)` (451–491) — то же из переданного словаря (для открытия проекта).

#### Кнопка быстрого пересчёта (↻)

Создаётся в `_tol_row()` (413–442). Фикс. размер `24×24`, тултип «Пересчитать статистику без повторной регистрации». Стиль:
- норма: фон `#1e3a2e`, текст `#66cc88`, рамка `#336644`;
- hover: фон `#2a4e3a`;
- disabled: текст `#444`, рамка `#333`, фон `#1a1a1a`.

Изначально `setEnabled(False)` (438), эмитит `recalculate_requested`. В коде создаётся **два** таких ряда (131, 138 — оба добавляются в `_recalc_buttons`). `set_has_results(has_results)` (446–449) включает/выключает их пакетно из `MainWindow._update_button_states()` (1054).

Сигнал приходит в `MainWindow._on_recalculate_tolerance()` (879–927), который без повторной регистрации пересчитывает `compute_statistics` и `colorize_point_cloud`, сохраняя поля `registration_rmse`, `registration_suspect`, `dimensions`, `fine_pass_shift_mm`, `fine_pass_rot_deg`, `rmse_coarse`, `rmse_bestfit`, `absorbed_deviation_mm`, `alignment_mode`, `within_tolerance_coarse`, `within_tolerance_bestfit_down`, `absorbed_within_tol_pct`, `worst_points`, `defect_clusters` (893–902).

#### Единицы измерения

`_UNIT_ITEMS` (26–31): «мм»→`mm`, «см»→`cm`, «м»→`m`, «дюйм»→`in`. Фабрика `_make_unit_combo(current_key)` (304–314) — комбобокс фикс. ширины 100. Подсказки:
- сверху: «Выберите единицы файлов. Программа приведёт всё к мм»;
- снизу мелким серым: «STL/PLY не хранят единицы. Сверьте габариты с реальной деталью».

`_on_cad_unit_changed`/`_on_scan_unit_changed` (277–278) эмитят `param_changed(["units","cad"|"scan"], data)`, если не идёт программное обновление.

**Логика перезагрузки** (`MainWindow._on_param_changed`, 929–987):
- если значение совпадает с `manager.unit_cad/unit_scan` — ничего не делается;
- если `manager.stats is not None` — `QMessageBox.question` «Это приведёт к перезагрузке файла и удалению результатов. Продолжить?»; при отказе комбобокс возвращается через `control_panel._set_unit_combo` и конфиг переписывается обратно;
- иначе — вызов `_load_cad_from_path(self.manager.cad_path)` или `_load_scan_from_path(self.manager.scan_path)`.

#### Режим выравнивания

UI-элемент — `_alignment_combo`. `_on_alignment_changed` (287–292) эмитит `param_changed(["registration","alignment_mode"], "best_fit"|"conservative")`. Эффект применяется на стороне core при следующем `run_analysis()` (это «тяжёлый» параметр). Метка режима выводится в `_log_registration_diagnostics()` (843–847 `main_window.py`).

#### Лёгкие vs тяжёлые параметры

В `MainWindow._on_param_changed` (936–942):

```python
_light = (
    ["analysis", "tolerance_mm"],
    ["analysis", "conformance_threshold"],
)
```

Только эти два пути ставят `_heavy_params_dirty = False` (доступен быстрый пересчёт без полной регистрации). Все остальные изменения (единицы, `preprocessing`, `registration`) ставят `_heavy_params_dirty = True`. Если есть результаты и `_heavy_params_dirty=False`, при `run_analysis` появляется диалог «Быстрый пересчёт» / «Полный анализ» / «Отмена» (432–452).

Смена `conformance_threshold` обновляет порог в `ResultsPanel` и перерисовывает вердикт без пересчёта статистики (945–948).

### 7.3 ResultsPanel (`ui/panels.py`)

Класс `ResultsPanel(QWidget)` объявлен в строке 497. Поля: `_labels` (ключ → `(QLabel, unit)`), `_threshold` (95.0 по умолчанию).

`_setup_ui()` (513–604): заголовок «Результаты анализа», три группы и вердикт.

#### Отображаемые метрики

Список `metrics` (536–545) — 8 строк группы «Результаты измерений»:

| Ключ stats | Подпись | Единицы |
|---|---|---|
| `mean_deviation` | Среднее отклонение | мм |
| `registration_rmse` | RMSE | мм |
| `min_deviation` | Мин. отклонение | мм |
| `max_deviation` | Макс. отклонение | мм |
| `within_tolerance` | Доля в допуске | % |
| `over_material_pct` | Избыток материала | % |
| `under_material_pct` | Недостаток материала | % |
| `ambiguous_sign_pct` | Неоднозн. знак | % |

Значения справа моноширинным `Courier New 10`, мин. ширина 80. До анализа — «—».

Форматы в `update_results` (608–617):

| Ключ | Формат |
|---|---|
| `registration_rmse` | `{:.6f}` |
| `mean_deviation`/`max_deviation`/`min_deviation` | `{+:.4f}` |
| доли (`within_tolerance`, `over/under/ambiguous_*_pct`) | `{v*100:.1f}` |
| остальные | `{:.4f}` |

#### Вердикт

Логика (624–637):
- `within_pct = stats["within_tolerance"] * 100`;
- `tolerance = stats.get("tolerance", 0.5)`;
- если `within_pct ≥ self._threshold` → «✓ СООТВЕТСТВУЕТ ДОПУСКАМ (±{tolerance:.3f} мм)», `background: #1B5E20; color: #A5D6A7`;
- иначе → «✗ НЕ СООТВЕТСТВУЕТ (в допуске {within_pct:.1f}%)», `background: #7f0000; color: #FFCDD2`.

`_threshold` устанавливается через `set_threshold(threshold)` (509–511) — `MainWindow` вызывает при инициализации (234–237), при открытии проекта (634–636) и при изменении `conformance_threshold` (946).

До анализа — «Ожидание анализа...» серым.

#### Габаритные размеры

Группа «Габаритные размеры» (572–594): три строки `CAD:`, `Скан:`, `Δ:` — атрибуты `_dim_cad`, `_dim_scan`, `_dim_delta`. Шрифт `Courier New 9`, перенос строк.

В `update_results` (639–649) при наличии `stats["dimensions"]`:
- CAD: `"{lx:.1f} x {ly:.1f} x {lz:.1f} мм"`;
- Скан: то же или «—»;
- Δ: `"{dx:+.2f} x {dy:+.2f} x {dz:+.2f} мм"` или «—».

#### Диагностика регистрации

Числовых полей диагностики в `ResultsPanel` нет — они выводятся в `LogPanel` через `MainWindow._log_registration_diagnostics()` (838–877). Состав (при наличии `fine_pass_shift_mm` или `rmse_coarse`):
- `── Диагностика регистрации ──`;
- `Режим выравнивания: {Наилучшее вписывание | Консервативный}`;
- `Смещение точного прохода: {fine_pass_shift_mm:.4f} мм`;
- `Поворот точного прохода: {fine_pass_rot_deg:.4f}°`;
- `C2M-RMSE грубое: {rmse_coarse:.4f} мм`;
- `C2M-RMSE точное (best-fit): {rmse_bestfit:.4f} мм`;
- `Разница RMSE (груб.−точн.): {absorbed_deviation_mm:+.4f} мм`;
- `Доля в допуске (грубое): {within_tolerance_coarse:.1f}%` (опционально);
- `Доля в допуске (best-fit↓): {within_tolerance_bestfit_down:.1f}%` (опц.);
- `Поглощённый допуск: {absorbed_within_tol_pct:.1f}%` (опц.);
- `⚠ Регистрация подозрительная!` — при `registration_suspect`;
- разделитель `─ × 30`.

`reset()` (651–658) — очистка метрик, нулевые габариты, начальный вид вердикта.

### 7.4 ViewerWidget (`ui/viewer_widget.py`)

Класс `ViewerWidget(QWidget)` объявлен в строке 246. Фон `_BG = (0.10, 0.10, 0.12)` (249). Реализован на `pyvistaqt.QtInteractor` поверх VTK.

#### Режимы вида

`_mode` (261) принимает `"overlay"`, `"scan"`, `"model"` (по умолчанию `"model"`). Три checkable-кнопки тулбара (391–393): `_btn_overlay`, `_btn_scan`, `_btn_model` (checked).

Логика в `_render()` (530–630):
- `show_scan = _mode in ("overlay","scan") and _pv_pcd is not None`;
- `show_mesh = _mode in ("overlay","model") and _pv_mesh is not None`;
- меш в `model`/`scan`: непрозрачный `opacity=0.92`, цвет `#c0c0b8`, рёбра `#444444` (569–578);
- меш в `overlay`: `opacity=0.22`;
- до анализа (preview): меш всегда непрозрачный, `#c8c8be`, рёбра `#777766` (557–567);
- скан с отклонениями: `add_mesh(scalars="deviation", cmap=_colormap, clim=[-tol,tol], point_size=3, ...)` (583–605);
- скан без отклонений: белые точки.

Кнопки `_btn_overlay`/`_btn_scan` отключены до завершения анализа (`_has_results`, 396–397, 525–526). При первом получении результатов через `load_results()` (456–481), если режим был `"model"`, авто-переключение на `"overlay"` (476–479).

#### Управление мышью

`_TrackballNoDolly` (43–55) — Python-подкласс `vtkInteractorStyleTrackballCamera` с пустыми `OnRightButtonDown/Up`, чтобы стандартный ПКМ-Dolly не срабатывал.

`_ViewerInteractionFilter(QObject)` (60–208):
- **Двойной клик ЛКМ** → `_recenter_at(pos)` (87–89, 163–208). Через `vtkPropPicker.Pick(x, y_vtk, 0, renderer)` подбирает 3D-точку по z-буферу (работает по мешу и облаку). Если клик в пустоту — проецируется на фокальную плоскость. Камера сдвигается параллельно: фокус и позиция сдвигаются на ту же дельту.
- **ПКМ press** → `_last_pos = globalPosition()` (95–99). `globalPosition()` исключает скачок дельты между parent и VTK-child виджетами.
- **MouseMove с ПКМ** → `_pan_camera(dx, dy)` (117–161). `delta = (-dx_px * right + dy_px * up) * scale`, где `scale` = `2 * parallel_scale / h` (параллельная) или `2 * dist * tan(va/2) / h` (перспективная).
- **ПКМ release** → конец pan.

Подсказка под 3D-видом (314–324): «ЛКМ: вращение | ПКМ: перемещение | Колесо: зум | Двойной клик: центрировать», 10 px, фон `#14141a`, текст `#707080`.

Установка фильтра — `_install_mouse_nav()` (335–354), синхронно в `_setup_ui`. Фильтр ставится и на `QtInteractor`, и на все его дочерние QWidget (потому что VTK создаёт внутренний OpenGL-виджет лениво при первом `render()`). После каждого `_render()` повторно вызывается `_install_mouse_nav()` (630) — идемпотентно.

Кнопка «↺ Сброс» (409–413) → `_view_reset()` (641–646): `_force_reset_camera = True`, `plotter.reset_camera()`, `plotter.render()`.

`set_interactive(enabled)` (515–521) отключает все кнопки тулбара и сам `plotter` на время анализа.

#### Scalar bar

В `_render()` для скана с отклонениями (590–603):

| Параметр | Значение |
|---|---|
| `title` | `""` |
| `n_labels` | 5 |
| `fmt` | `"%+.2f"` |
| `color` | white |
| `label_font_size` | 11 |
| `shadow` | False |
| `position_x` / `position_y` | 0.02 / 0.10 |
| `width` / `height` | 0.06 / 0.80 |
| `vertical` | True |

`self._colormap` берётся из `config.ui.colormap` (260) с fallback `"RdYlGn_r"`. `clim = [-tolerance, tolerance]`.

#### Сохранение камеры при смене режима

Поля (269–270): `_camera_initialized`, `_force_reset_camera`.

Алгоритм в `_render()` (535–625):
1. До `plotter.clear()` сохраняется `prev_cam = plotter.camera_position`, если `_camera_initialized and _has_data` (536–540).
2. После очистки и добавления актёров: если `not _camera_initialized` или `_force_reset_camera` или `prev_cam is None` → `plotter.reset_camera()`, `_camera_initialized = True`, `_force_reset_camera = False` (616–619).
3. Иначе восстанавливается `plotter.camera_position = prev_cam` (621–625).

`_force_reset_camera = True` устанавливается в трёх местах: `load_mesh_preview()` (443), `load_results()` (466), `_view_reset()` (644). В `clear()` (489–513): `_camera_initialized = False` (498).

#### Лимит точек и прореживание

Константа `_MAX_DISPLAY_PTS = 600_000` (215). `_pcd_to_pv(pcd, deviations)` (218–231): если `n > _MAX_DISPLAY_PTS`, вычисляется `step = max(1, n // _MAX_DISPLAY_PTS)`, точки и значения берутся по `np.arange(0, n, step)`. Комментарий (214): «Статистика и PDF всегда считаются на полных данных».

#### Скриншоты для PDF: 6 видов

`make_multiview_screenshots()` (665–746). Возвращает `[]`, если `not _has_data or _pv_mesh is None`.

Алгоритм:
1. Bbox меша, центр `(cx,cy,cz)`, диагональ `diag`.
2. `d = diag * 1.8`.
3. `cam_configs` (685–692):

| Имя | Позиция | Up |
|---|---|---|
| `front` | `(cx, cy − d, cz)` | `(0, 0, 1)` |
| `back` | `(cx, cy + d, cz)` | `(0, 0, 1)` |
| `left` | `(cx − d, cy, cz)` | `(0, 0, 1)` |
| `right` | `(cx + d, cy, cz)` | `(0, 0, 1)` |
| `top` | `(cx, cy, cz + d)` | `(0, 1, 0)` |
| `iso` | `(cx + 0.7d, cy − 0.7d, cz + 0.55d)` | `(0, 0, 1)` |

4. Для каждого — offscreen-плоттер `pv.Plotter(off_screen=True, window_size=(750, 560))` с фоном `_BG`.
5. Если есть `_pv_pcd` и `_deviations` — рисуется меш с `opacity=0.28` (`#b8b8b8`, без рёбер) и поверх него скан с теми же параметрами окраски, `point_size=2`, без scalar bar (705–718).
6. Иначе — только меш с рёбрами (preview-режим).
7. `camera.position/focal_point/up`, `reset_camera()`, `screenshot(out, transparent_background=False)`.
8. Имена через `tempfile.mkstemp(suffix=".png", prefix=f"geo_view_{name}_")`.
9. При ошибке отдельного вида — удаление временного файла, продолжение.

`_take_screenshot()` (650–663) — один скриншот текущего вида с префиксом `geo_viewer_`. В коде определён, но не вызывается.

`MainWindow.save_report` использует `make_multiview_screenshots()` (569).

#### Прочее

Заглушка `_placeholder` (283–294) — `QLabel` «3D-вид\n\nЗагрузите CAD-модель и облако точек, затем запустите анализ.\n\nПоддерживается Drag && Drop файлов». Показывается до `_has_data`.

`_schedule_render()` (483–487) откладывает рендер через `QTimer.singleShot(0, _render)` с флагом `_render_pending`.

`closeEvent` (750–755) корректно закрывает plotter с подавлением исключений.

### 7.5 LogPanel (`ui/panels.py`)

Класс `LogPanel(QWidget)` объявлен в 664. Сигнал `cancel_requested` (667).

UI (`_setup_ui`, 673–712): горизонтальный ряд кнопок сверху, `QTextEdit` (моноширинный `Courier New 9`, read-only) ниже.

Кнопки (682–706):
- «Сохранить лог» — `_save_btn`, фикс. высота 22, слот `_save_log` (743–750): `QFileDialog.getSaveFileName`, фильтр «Текстовые файлы (*.txt);;Все файлы (*.*)», запись `text_edit.toPlainText()` в UTF-8.
- «Очистить лог» — `_clear_btn`, фикс. высота 22, слот `text_edit_clear()` (740–741).
- «■ Отмена» — `_cancel_btn`, скрыта изначально, тёмно-красная (`background: #C62828; color: white; padding: 2px 10px; border-radius: 3px; font-weight: bold`, hover `#D32F2F`). С фильтром `_ArrowOnHoverFilter`, эмитит `cancel_requested`.

Управление:
- `set_analysis_running(running)` (752–753) — `_cancel_btn.setVisible(running)`;
- `set_cancel_enabled(enabled)` (755–756) — `_cancel_btn.setEnabled(enabled)`.

#### Цветовая раскраска сообщений

`_classify_color(message)` (714–724) приводит к нижнему регистру и проверяет регулярки с `\b`:

| Регулярка | Цвет |
|---|---|
| `\b(ошибка\|error)\b` | `#FF6B6B` |
| `\b(предупреждение\|warning\|внимание)\b` | `#FFA726` |
| `\b(завершён\|успешно\|сохранён)\b` | `#66BB6A` |
| остальные | `#e8e8e8` |

`\b` нужны, чтобы «не завершён» не окрашивалось зелёным, а «errorless» — не считалось ошибкой.

`append(message)` (726–738) формирует HTML: метка `[HH:MM:SS]` цветом `#909090`; текст HTML-escape'ится и стилизуется `color:{color}; white-space:pre`; курсор в конец.

### 7.6 HelpDialog (`ui/help_dialog.py`)

Файл содержит два класса.

#### `HelpDialog(QDialog)` (301–329)

Окно «Руководство пользователя», 820×620, с кнопкой «Развернуть» (`WindowMaximizeButtonHint`, 308–310). `QTextBrowser` с фиксированным HTML из константы `_HELP_HTML` (12–298). Стиль `background: #ffffff; color: #212121`, `setOpenExternalLinks(False)`. Внизу кнопка «Закрыть» 90 px.

Содержание HTML-руководства:
1. **«1. Быстрый старт»** (50–72) — 7 шагов; tip-блок про Drag & Drop.
2. **«2. Поддерживаемые форматы»** (74–93) — таблица CAD (STL, OBJ), скан (PLY, PCD, XYZ, PTS), проект (JSON), отчёт (PDF).
3. **«3. Описание параметров»** (96–162) — предобработка, регистрация, расчёт отклонений.
4. **«4. Интерпретация результатов»** (165–204) — метрики и цвета карты.
5. **«5. Управление 3D-видом (мышь)»** (207–239) — ЛКМ/ПКМ/колесо/«↺ Сброс»; tip про осмотр дефекта.
6. **«6. Горячие клавиши»** (241–251) — таблица 7 шорткатов.
7. **«7. Решение проблем»** (254–294) — пять блоков (long-run warn, разные единицы err, RMSE>1мм err, не-watertight warn, ошибка загрузки warn).

CSS — светлая тема: тело `#212121`, заголовки `#1565C0/#2E7D32`, бордюры `#90CAF9/#BDBDBD`, чередование `#F5F5F5`, классы `tip` (зелёный), `warn` (жёлтый), `err` (красный), `kbd` (моноширинный с серой рамкой).

> Примечание: содержание справки описывает несколько элементов, которых в текущем UI нет (например, отдельная кнопка «Показать 3D-вид», параметр «Цветовая шкала» с вариантами `coolwarm`/`RdYlGn_r`, метрики «Стд. отклонение», «Макс. |отклонение|», «95-й перцентиль», вариант «как есть» для единиц).

#### `AboutDialog(QDialog)` (332–390)

Окно «О программе», фикс. 420×260, кнопка контекстной справки скрыта. Содержит заголовок «Программный модуль определения отклонений геометрии деталей от 3D-модели» (Bold 11pt), разделитель из «─» × 48, блок ключ/значение (362–368):

| Поле | Значение |
|---|---|
| Версия | 1.0 |
| Автор | Отряхина В.Л. |
| Организация | РГАТУ им. П.А. Соловьёва |
| Год | 2026 |
| Стек | Python · Open3D · PyQt6 · ReportLab |

Внизу кнопка «ОК» 80 px.

---

## 8. Форматы данных

### 8.1 Входные файлы

**CAD-модель** (`project_manager.py:147`):
```python
_SUPPORTED_CAD_EXT = {".stl", ".obj"}
```
Чтение через `o3d.io.read_triangle_mesh(path)` (171). Ограничения:
- Расширение в наборе, иначе `ValueError` с перечнем (160–165).
- `len(mesh.vertices) > 0`, иначе `ValueError("Файл ... пустой или повреждён")` (173–174).
- Если не watertight, `worker.py:193-198` пишет warning о том, что знак отклонения восстанавливается по нормали ближайшей грани (с особыми правилами для срединных поверхностей).
- Форматы **STEP, IGES не поддерживаются**.

**Облако точек** (`project_manager.py:148`):
```python
_SUPPORTED_SCAN_EXT = {".ply", ".pcd", ".xyz", ".pts"}
```
Чтение через `o3d.io.read_point_cloud(path)` (224). Ограничения:
- Минимум **100 точек**, иначе `ValueError` (226–230).
- Расширение в наборе, иначе `ValueError` (213–218).

Безопасность: пути из внешнего `project.json` фильтруются `_is_safe_project_path` (см. §9).

### 8.2 JSON-проект

Формирование — `ProjectManager.save_project` (`project_manager.py:276-313`):

```json
{
  "version":       "1.2",
  "saved_at":      "<ISO-8601 datetime>",
  "cad_path":      "<абс. путь к CAD>",
  "scan_path":     "<абс. путь к скану>",
  "unit_cad":      "mm",
  "unit_scan":     "as_is",
  "config":        { ... весь self.config ... },
  "analysis_date": "YYYY-MM-DD HH:MM:SS",
  "stats":         { ... словарь статистик ... },
  "has_npz":       true | false
}
```

| Поле | Источник | Описание |
|---|---|---|
| `version` | 284 | Версия формата (`"1.2"`) |
| `saved_at` | `datetime.now().isoformat()` | Момент сохранения |
| `cad_path`, `scan_path` | `self.cad_path`, `self.scan_path` | Абсолютные пути |
| `unit_cad`, `unit_scan` | `self.unit_cad`, `self.unit_scan` | Единицы исходных файлов (для корректного re-load) |
| `config` | `self.config` | Полная копия текущей конфигурации |
| `analysis_date` | `self.analysis_date` | Установлено в `save_results` (`%Y-%m-%d %H:%M:%S`, 271) |
| `stats` | `self.stats` | Структура `compute_statistics` + поля `reg_diag` + `dimensions` |
| `has_npz` | `self.deviations is not None` | Флаг наличия NPZ-сайдкара |

Запись с `ensure_ascii=False, indent=2` (297).

**Версионирование / совместимость.** Текущая версия `"1.2"`. Поле явно не проверяется (best-effort чтение). Старые форматы без `unit_cad`/`unit_scan` поддерживаются через fallback на `config["units"]` (334–336). Поле `worst_points` в `stats` восстанавливается на лету (378–403), если отсутствует в JSON, но есть массивы `deviations` и `pcd_points` в NPZ — вызывается `compute_statistics`.

### 8.3 NPZ-сайдкар

Путь — `os.path.splitext(json_path)[0] + ".npz"` (301). Запись через `np.savez_compressed(npz_path, **arrays)`.

Состав массивов (300–309):

| Ключ | Условие записи | Содержимое |
|---|---|---|
| `deviations` | всегда при `has_results` | `np.ndarray[float]` — отклонения в мм, по точке на `pcd_registered` |
| `transformation` | `self.transformation is not None` | `np.ndarray[4,4]` — финальная **T_total** из исходного `pcd` в положение `pcd_registered`. Включает центроидное предвыравнивание + ICP. Применение к свежезагруженному `pcd` даёт совмещение, эквивалентное `pcd_registered` (см. комментарии `worker.py:151-153`, `project_manager.py:267-269`) |
| `pcd_points` | `self.pcd_registered is not None` | `np.asarray(pcd_registered.points)` — `[N, 3]` в мм |
| `ambiguous_mask` | `self.ambiguous_mask is not None` | Булева маска (приводится `.astype(bool)` при чтении, 386) |

При загрузке: `np.load(npz_path, allow_pickle=False)` (368) — pickle запрещён для безопасности.

---

## 9. Обработка ошибок и защиты

### 9.1 try/except по файлам

**`main.py`:**

| Строки | Что ловится | Действие |
|---|---|---|
| 255–269 | `OSError` при `os.makedirs`, `ImportError` при `import platformdirs` | Fallback на `os.getcwd()` |
| 394–404 | Любое исключение чтения/парсинга `config.json` | Лог `error`, валидация дефолтов, возврат дефолтов |
| 427–438 | Исключение при создании `MainWindow` | `logger.exception` (с traceback), `QMessageBox.Icon.Critical`, `sys.exit(1)` |

**`core/project_manager.py`:**

| Строки | Что ловится | Действие |
|---|---|---|
| 160–165 | (проверка) | `ValueError` с перечнем форматов |
| 173–174 | Пустой меш | `ValueError("Файл ... пустой или повреждён")` |
| 213–218 | Неподдерживаемое расширение | `ValueError` |
| 226–230 | `len(pcd.points) < 100` | `ValueError` |
| 339–360 | Проверки `_is_safe_project_path` | Warning, путь пропущен |
| 367–371 | Исключение чтения NPZ | Warning, `npz_data = None` |

**`core/worker.py`:**

| Строки | Что ловится | Действие |
|---|---|---|
| 106–108 | `InterruptedError` | `_log("[Отмена]...")`, `analysis_cancelled.emit()` |
| 109–113 | `RegistrationError`, `TimeoutError` | `logger.error`, `log_message.emit("[ОШИБКА]...")`, `analysis_error.emit(msg)` |
| 114–118 | Прочее `Exception` | Лог с `traceback.format_exc()`, `analysis_error.emit(str(e))` |

### 9.2 Валидация входных данных

- **Минимум точек скана**: `≥ 100` (`project_manager.py:226-230`).
- **Непустой меш**: `len(mesh.vertices) > 0` (`project_manager.py:173-174`).
- **Watertight-проверка**: `worker.py:193-198` — warning при `not mesh.is_watertight()`.
- **NaN / вырожденный меш**: `register_pipeline` бросает `RegistrationError("CAD-меш вырожден (нулевой bbox)")` при `bbox_diag < 1e-6`. В `compute_dimensions` (`dimensions.py:103`) при `|det(R)| < 0.5` OBB заменяется на AABB. В `preprocess_pipeline:133` отрицание (`if not (voxel_size > 0)`) корректно ловит NaN.
- **Подозрительная регистрация**: `reg_suspect` от `register_pipeline` (`worker.py:179-183`) — лог `[SUSPECT REGISTRATION]`; при `reg_rmse > 1.0` мм — `[WARNING] Высокий ICP RMSE!` (`worker.py:184-188`).

### 9.3 Таймауты

`_icp_with_timeout` в `core/algorithms/registration.py:227-247` (таймаут 60 сек) использует `ThreadPoolExecutor` и `fut.result(timeout)`. `worker.py:109` ловит `TimeoutError` в общей ветке с `RegistrationError`.

### 9.4 Потокобезопасность

- **`threading.Event`** для отмены (`worker.py:70`) — гарантированная memory visibility между потоками.
- **Проверка отмены** на границах этапов: каждый `_emit_progress(value)` (`worker.py:77-87`) проверяет `_cancelled.is_set()` и бросает `InterruptedError`.
- **Сигналы Qt** — `progress_changed`, `log_message` и др. через `QueuedConnection` сериализуются в очередь событий главного потока.
- **`_analysis_state`** в `MainWindow` (`idle/preparing/running`) — единый флаг, защищающий от параллельных операций (см. §7.1).
- **`disconnect()`** у предыдущего worker'а перед стартом нового (`main_window.py:512-516`) — защита от отложенных эмитов.
- **Изоляция конфига**: `worker.py:124-129` делает `copy.deepcopy(self.config)` и подменяет `preprocessing`/`registration` на копию `BASIC_DEFAULTS` в базовом режиме, чтобы не мутировать общий конфиг.
- **Защита от shared-памяти Open3D**: в `colorize_point_cloud` (`deviation.py:420-428`) координаты копируются явным `.copy()`, иначе `pcd_colored.points = pcd.points` дал бы shared `Vector3dVector`.

### 9.5 Безопасность

- **Валидация путей из `project.json`** — `_is_safe_project_path` (`project_manager.py:77-98`): не пустая, не UNC, абсолютная, без `..`. Комментарий: Open3D исторически имеет segfault на повреждённых STL/PLY; фильтр снижает поверхность атаки.
- **Валидация типов конфига** при загрузке проекта — `_types_compatible` (`project_manager.py:62-74`).
- **NPZ без pickle**: `np.load(npz_path, allow_pickle=False)` (`project_manager.py:368`).
- **Валидация диапазонов конфига** — `_validate_config_ranges` (`main.py:317-360`).
- **Ротация лога**: `RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")` (`main.py:285-287`). Каталог — `platformdirs.user_log_dir("GeoDeviation", appauthor=False)` (`main.py:259-260`); fallback на CWD.
- **Сброс результатов** при загрузке новых файлов — `_reset_results` (`project_manager.py:427-436`).

---

## 10. Тесты

Модуль содержит два интеграционных тест-файла на pytest, покрывающих ядро алгоритмического пайплайна: регистрацию, вычисление отклонений, статистику и генерацию PDF-отчёта. `conftest.py` отсутствует; маркер пакета `tests/__init__.py` пуст. Артефакты для GUI-демонстрации лежат в `tests/fixtures/` (`L_shape.stl`, `scan_correct.ply`, `scan_flipped.ply`) и генерируются standalone-запуском `test_registration_robustness.py`.

### 10.1 `tests/__init__.py`

Пустой файл (0 строк), маркирует `tests/` как пакет.

### 10.2 `tests/test_q5_integration.py` (416 строк)

Проверяет полный пайплайн Q5: `preprocess → register → compute_deviations → compute_statistics → generate_report`. Использует синтетическую Г-образную деталь с двумя детерминированными зонами дефектов (избыток на верхней грани короткой руки, недостаток на левой грани длинной руки) и предварительно смещённый/повёрнутый скан, чтобы регистрация была нетривиальной.

#### Конструкторы данных (не тесты)

- `_make_L_shape()` (44–52) — Г-меш из двух боксов (`100×30×20` + `30×30×40` со смещением `[70,0,20]`), без булевых операций.
- `_make_defective_scan(mesh, n_points=10_000, noise_std=0.05, defect_mm=2.5, seed=42)` (55–108) — равномерная выборка с поверхности, гауссов шум `σ=0.05`, две зоны дефектов: **избыток** `+2.5 мм` по `+Z` при `z>57 ∧ x>68`; **недостаток** `+2.5 мм` по `+X` при `x<1 ∧ y<30 ∧ z<20`. Затем жёсткий сдвиг `[8,0,0]` мм и поворот `3°` вокруг Z. Возвращает `(pcd, n_excess, n_deficit)`.
- `_CONFIG` (111–133) — `voxel_size=-1` (автоопределение), `ransac_max_iter=200_000`, `ransac_n_starts=6`, `icp_max_iter=150`, `tolerance_mm=0.5`, `worst_points_n=10`, `colormap="RdYlGn_r"`, `alignment_mode="best_fit"`.
- `_run_full_pipeline(pcd, mesh, config)` (136–158) — точно повторяет `worker.py`: `preprocess_pipeline → register_pipeline → compute_deviations → compute_statistics`, обогащает stats полями `registration_rmse`, `registration_suspect`, содержимым `reg_diag`.

#### Фикстура

Shared в модуль-глобальном словаре `_SHARED` через `_ensure_shared()` (163–177). Поля: `mesh`, `pcd`, `stats`, `reg_diag`, `deviations`, `pcd_reg`, `pcd_clean`, `T_total`, `n_excess`, `n_deficit`. Реальные STL/PLY не используются. Пайплайн прогоняется один раз и переиспользуется всеми тестами.

#### Тесты

| # | Функция | Строки | Проверяет |
|---|---|---|---|
| 1 | `test_material_split_invariant` | 182–201 | Инвариант материального баланса: `within_tolerance + over_material_pct + under_material_pct == 100%` с точностью `1e-6`; `over > 0`, `under > 0`. |
| 2 | `test_worst_points` | 206–234 | `stats["worst_points"]` существует, длина ровно `10`; `abs(worst_points[0].dev) == max_abs_deviation` (±`1e-8`); сортировка по `|dev|` по убыванию. |
| 3 | `test_masking_metrics` | 239–280 | Алгебраический инвариант Q4 на downsampled-облаке: `within_tolerance_coarse + absorbed_within_tol_pct == within_tolerance_bestfit_down` (±`1e-9`). Также `wtc ∈ [0,1]` и сумма `∈ [0,1]`. |
| 4 | `test_pdf_sections` | 285–338 | Crash-тест `generate_report`: PDF создан, размер > 0, страниц ≥ 3 (если установлен `pypdf`). Содержимое кириллицы намеренно не проверяется. |
| 5 | `test_transformation_includes_centroid` | 343–376 | Контракт NPZ-сайдкара: `T_total` — 4×4, и применение к **входному** `pcd_clean` воспроизводит `pcd_registered` (RMSE < `1e-6` мм). Гарантирует, что центроидное предвыравнивание упаковано в `T_total`. |

#### Standalone-runner

Строки 381–416: при `python tests/test_q5_integration.py` — UTF-8 stdout, прогоняет все пять тестов с печатью таблиц, exit-код `0`/`1`.

### 10.3 `tests/test_registration_robustness.py` (465 строк)

Тестовая оснастка для воспроизведения и измерения бага «ложный 180°-минимум» на симметричной Г-детали. Пайплайн не модифицируется — только метаморфные тесты и тест-провокатор.

#### Конструкторы данных и метрики

- `make_L_shape()` (41–63) — та же Г-деталь. Ось 180°-неоднозначности — Y; зеркальное Г неотличимо по FPFH плоских граней.
- `sample_scan(mesh, n_points, noise_std=0.0, seed=42)` (66–80) — равномерная передискретизация + опциональный шум.
- `make_transform(angle_deg, axis, t)` (83–98) — `4×4`-матрица Родрига.
- `apply_transform(pcd, R, t)` (101–108) — новое облако `R @ pts + t`.
- `final_c2m_rmse(mesh, pcd_registered)` (115–125) — C2M-RMSE по всему облаку через `compute_deviations`.
- `pose_error(T_est, T_gt)` (128–139) — `(angle_deg, t_norm_mm)`: угол ошибки и норма ошибки сдвига.
- `_NORMAL_CONFIG` (147–160) — продакшн-дефолты (`ransac_max_iter=200_000`, `n_starts=6`, `icp_max_iter=200`).
- `_BUGGY_CONFIG` (167–180) — провокатор: `ransac_max_iter=20_000` (×10 меньше), `ransac_n_starts=1`, `icp_max_iter=50`.
- `_run_pipeline(pcd, mesh, config)` (183–195) — `preprocess → register`, возвращает `(pcd_registered, T_estimated, icp_rmse)`.
- `_generate_fixtures(force=False)` (202–238) — сохраняет в `tests/fixtures/`: `L_shape.stl`, `scan_correct.ply`, `scan_flipped.ply` (повёрнутый на 180° вокруг Y). Эти артефакты — для GUI-демонстрации, тесты их не читают.

#### Фикстуры

Реальные STL/PLY тестами **не используются**. Все данные — синтетические in-memory. Pytest-фикстур (`@pytest.fixture`) нет; данные строятся в теле каждой тестовой функции.

#### Тесты

| # | Функция | Строки | Проверяет |
|---|---|---|---|
| 1 | `test_zero_deviation_identity` | 245–285 | Метаморфный тест C: точная передискретизация меша (5000 точек, без шума), начальная дезориентация 10° вокруг Y + сдвиг 5 мм. Пороги: `C2M RMSE < bbox_diag * 1e-3` (≈0.12 мм), `pose_angle < 10°`. |
| 2 | `test_false_minimum_Lshape` | 297–376 | Тест-провокатор D: скан стартует из позы 180° вокруг Y, конфиг `_BUGGY_CONFIG`. `_N_RUNS = 10` запусков; провал — `RMSE > 5% bbox_diag` или `angle > 90°`. Ожидание после фикса (PCA-гипотезы + выбор по C2M-RMSE): **0/10 провалов**. |
| 3 | `test_stability_5seeds` | 383–418 | Тест E: пять seed-ов (`0…4`) выборки скана. Все должны пройти (`RMSE < eps`, `angle < 10°`); список провалов вычисляется и логируется. |

#### Standalone-runner

Строки 425–465: `python tests/test_registration_robustness.py` принудительно перегенерирует fixture-файлы (`force=True`), последовательно запускает C, D, E с печатью PASS/FAIL.

### 10.4 Запуск

`conftest.py` в проекте нет. Поддерживаются два способа:

```bash
# Pytest (рекомендуется)
C:\module\.venv\Scripts\python.exe -m pytest tests\ -v -s

# Только один файл
C:\module\.venv\Scripts\python.exe -m pytest tests\test_q5_integration.py -v -s
C:\module\.venv\Scripts\python.exe -m pytest tests\test_registration_robustness.py -v -s

# Standalone
C:\module\.venv\Scripts\python.exe tests\test_q5_integration.py
C:\module\.venv\Scripts\python.exe tests\test_registration_robustness.py
```

Оба файла в начале вставляют корень проекта в `sys.path`:
```python
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
```

### 10.5 Покрытие

**Что покрыто:**

- `preprocessing.preprocess_pipeline` — косвенно, через оба файла.
- `registration.register_pipeline` — глубоко: контракт `T_total` (центроидное предвыравнивание), устойчивость к 180°-неоднозначности (D), сходимость на точных данных (C, E), стабильность по seed-ам (E).
- `deviation.compute_deviations` — косвенно, через `final_c2m_rmse` и сценарии с инжектированными дефектами.
- `deviation.compute_statistics` — материальный баланс, `worst_points` (длина, сортировка, связь с `max_abs_deviation`), Q4-маска.
- `report.generate_report` — только crash-тест: PDF создан, страниц ≥ 3.

**Что НЕ покрыто:**

- **UI-слой полностью без тестов** — PyQt-виджеты, VTK-сцена, MainWindow, диалоги, переключатели режимов, сохранение/загрузка проекта, горячие клавиши, тулбар, состояние камеры.
- **`dimensions.py` без тестов** — нет проверок длины, OBB.
- **Содержательная проверка PDF отсутствует** — `test_pdf_sections` сознательно не проверяет легенду, строки over/under, таблицу worst-points (вопреки docstring файла); только `size > 0` и `n_pages ≥ 3`.
- **Нет unit-тестов отдельных функций deviation** (только end-to-end).
- **Нет тестов на единицы измерения** (`UNIT_TO_MM`, преобразования mm/m/inch).
- **Нет тестов логирования** (`RotatingFileHandler`).
- **Нет тестов скриншотов** (`make_multiview_screenshots`).
- **Нет тестов worker-потока** (логика `_run_full_pipeline` копирует worker, а не тестирует его).
- **Нет реальных STL/PLY-фикстур в pytest-сценариях** — все на синтетике.
- **Нет параметризованных тестов** (`@pytest.mark.parametrize`); повторы реализованы циклами внутри тестов.
- **Нет тестов на крупных/реальных сканах** — все 5000–10000 точек, простая Г-деталь.

---

## 11. Известные ограничения

По фактическому состоянию кода:

1. **Форматы CAD ограничены STL и OBJ.** STEP, IGES, BREP, FBX, GLTF не поддерживаются (`project_manager.py:147`).
2. **Форматы скана**: только PLY, PCD, XYZ, PTS. E57 не поддерживается (`project_manager.py:148`).
3. **Минимум 100 точек** для облака скана; ниже — `ValueError` (`project_manager.py:226-230`).
4. **Для надёжного определения знака отклонения нужен watertight-меш.** Для не-watertight используется эвристика по нормали ближайшей грани (`deviation.py:104-115`), которая не распознаёт срединные поверхности тонких стенок — точки попадают в `ambiguous_mask` лишь у рёбер (вектор почти параллелен грани).
5. **Линейный лимит отображения 600 000 точек.** Сверх — равномерное прореживание шагом `n // 600_000` (`viewer_widget.py:215`). Статистика и PDF считаются на полных данных.
6. **OBB через Open3D `get_oriented_bounding_box`.** При `|det(R)| < 0.5` (вырожденная ориентация) — fallback на сортированный AABB (`dimensions.py:103`), что искажает соответствие осей CAD↔скан.
7. **Геометрические габариты по AABB-в-локальном-OBB-фрейме**, а не «истинный» минимальный OBB. Для деталей со сложной симметрией это может давать неинтуитивные значения.
8. **Таймаут ICP — 60 секунд (зашит)** на каждый проход через `concurrent.futures` (`registration.py:251, 487`). При срабатывании поднимается `TimeoutError` и пайплайн прерывается с сообщением «Совмещение не сходится. Возможно, загружены файлы разных деталей.»
9. **`alignment_mode="best_fit"` может маскировать реальные отклонения**, сдвигая деталь в зону допуска. Метрика `absorbed_within_tol_pct` это показывает; при `|abs_pp| > 5 пп` или `|absorbed_deviation_mm| > tolerance` MainWindow показывает предупреждение (`main_window.py:802-820`).
10. **`registration_suspect` не прерывает анализ**, только маркирует флаг и пишет warning (`registration.py:463-473`). Решение принимает пользователь (диалог `main_window.py:745-781`).
11. **Только один canonical `T_total`** в проекте: повторное применение к свежезагруженному `pcd` точно воспроизводит `pcd_registered`. Многократные накопленные регистрации не поддерживаются.
12. **Шрифты PDF**: если ни TTF (FreeSans / arial) не найдены — fallback на Helvetica без кириллицы (`report.py:41-54`), кириллица превратится в `□`.
13. **При экспорте PDF используется только 6 фиксированных видов**, выбираемых из bbox меша (`viewer_widget.py:685-692`). Пользовательские ракурсы не сохраняются.
14. **HelpDialog содержит описания элементов, которых нет в UI** (см. примечание в §7.6), — это документационный дрейф.
15. **`worst_points_n` и `min_cluster_size`** влияют не только на отчёт, но и на фильтрацию шума (KDTree-радиус `3*avg_step`): при очень разреженном облаке или малом числе кандидатов выдаётся «нефильтрованная» версия с флагом `worst_points_unfiltered=True`.
16. **Open3D не thread-safe**: смена единиц во время анализа жёстко заблокирована UI (`main_window.py:956-957, 1015-1019`).
17. **`ui.colormap` не объявлен в дефолтах `main.py`**, но используется кодом через `.get(..., "RdYlGn_r")`. То есть фактически дефолт есть, но из конфига он не виден без явного задания.

---

## 12. Hardcoded константы

Сводная таблица «магических» значений, встречающихся непосредственно в коде (без вынесения в конфиг).

### 12.1 core/ + main.py

| Имя / контекст | Значение | Файл:строка | Описание |
|---|---|---|---|
| Имя приложения | `"Модуль анализа отклонений геометрии"` | main.py:417 | `app.setApplicationName(...)` |
| Имя организации | `"РГАТУ"` | main.py:418 | `app.setOrganizationName(...)` |
| Стиль Qt | `"Fusion"` | main.py:421 | `app.setStyle(...)` |
| `_DARK_QSS` | строка ~230 строк QSS | main.py:23-252 | Применяется через `app.setStyleSheet` |
| Имя лог-приложения | `"GeoDeviation"` | main.py:260 | `platformdirs.user_log_dir(...)` |
| Имя лог-файла | `"app.log"` | main.py:269 | |
| Размер ротации лога | `5 * 1024 * 1024` (5 МБ) | main.py:286 | `RotatingFileHandler maxBytes` |
| Число бэкапов лога | `3` | main.py:286 | `backupCount` |
| Кодировка лога | `"utf-8"` | main.py:286 | |
| Формат лога | `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"` | main.py:281 | |
| Формат даты лога | `"%H:%M:%S"` | main.py:282 | |
| Уровень логирования | `logging.INFO` | main.py:290 | |
| Дефолт `tolerance_mm` (валидатор) | `0.5` | main.py:330 | |
| Дефолт `conformance_threshold` | `95` | main.py:333 | |
| Дефолт `sor_neighbors` | `20` | main.py:336, defaults.py:10 | |
| Дефолт `voxel_size` sentinel | `-1` | main.py:339 | |
| Дефолт `sor_std_ratio` | `2.0` | defaults.py:11 | |
| Дефолт `voxel_size` | `0` | defaults.py:12 | |
| Дефолт `ransac_max_iter` | `200000` | defaults.py:15 | |
| Дефолт `ransac_n_starts` | `5` | defaults.py:16 | |
| Дефолт `ransac_top_k` | `4` | defaults.py:17 | |
| Дефолт `icp_coarse_pct` | `5.0` | defaults.py:18 | |
| Дефолт `icp_fine_pct` | `1.0` | defaults.py:19 | |
| Дефолт `icp_max_iter` | `150` | defaults.py:20 | |
| Дефолт `use_pca_seeds` | `True` | defaults.py:21 | |
| Дефолт `reject_rmse_pct` | `5.0` | defaults.py:22 | |
| Дефолт `alignment_mode` | `"best_fit"` | defaults.py:23 | |
| Дефолт `worst_points_n` | `10` | main.py:377 | |
| Дефолт `units.cad` | `"mm"` | main.py:385 | |
| Дефолт `units.scan` | `"mm"` | main.py:386 | |
| Имя config-файла | `"config.json"` | main.py:363, project_manager.py:421 | |
| `UNIT_TO_MM` | `{mm:1, cm:10, m:1000, in:25.4, as_is:1}` | project_manager.py:30-36 | |
| Минимум точек скана | `100` | project_manager.py:226 | |
| Поддерживаемые CAD-форматы | `{".stl", ".obj"}` | project_manager.py:147 | |
| Поддерживаемые форматы скана | `{".ply", ".pcd", ".xyz", ".pts"}` | project_manager.py:148 | |
| Цвет CAD-меша | `[0.7, 0.7, 0.7]` | project_manager.py:189 | |
| Версия формата проекта | `"1.2"` | project_manager.py:284 | |
| Fallback `tolerance_mm` для воссоздания worst_points | `1.0` | project_manager.py:382 | |
| Формат `analysis_date` | `"%Y-%m-%d %H:%M:%S"` | project_manager.py:271 | |
| Пороги этапов прогресса | `35, 65, 80` | worker.py:41-45 | `_STAGE_THRESHOLDS` |
| Промежуточные `_emit_progress` | `35, 88, 97, 100` | worker.py:149, 204, 252, 260 | |
| Порог `[WARNING] Высокий ICP RMSE` | `1.0` мм | worker.py:184 | |
| Fallback colormap (worker) | `"RdYlGn_r"` | worker.py:246 | |
| Сообщение отмены | `"Анализ отменён пользователем"` | worker.py:80 | |

### 12.2 core/algorithms/

| Имя / контекст | Значение | Файл:строка | Описание |
|---|---|---|---|
| Минимум точек для SOR | 10 | preprocessing.py:39 | |
| Порог warning после SOR | 100 | preprocessing.py:54 | |
| Доля диагонали для auto voxel_size | 0.015 (1.5%) | preprocessing.py:136 | |
| `voxel_size` (регистрация) | `bbox_diag * 0.02` | registration.py:42 | |
| `fpfh_radius` | `bbox_diag * 0.05` | registration.py:43 | |
| `ransac_distance` | `bbox_diag * 0.03` | registration.py:44 | |
| `max_nn` для KDTree (нормали) | 30 | registration.py:65 | |
| Минимум сэмплов с меша (full) | 50000 | registration.py:72 | |
| Минимум сэмплов с меша (down) | 20000 | registration.py:76 | |
| `k` для согласования нормалей | 15 | registration.py:87 | |
| `max_nn` для FPFH | 100 | registration.py:101 | |
| Порог различия voxel'ов для reuse | 0.2 (20%) | registration.py:318 | |
| Мин. точек после повторного voxel'а | 50 | registration.py:334 | |
| Порог вырожденности bbox | 1e-6 | registration.py:312 | |
| Минимальный `fitness` RANSAC | 0.01 | registration.py:409 | |
| RANSAC: `mutual_filter` | True | registration.py:158 | |
| RANSAC: `CheckerEdgeLength` | 0.9 | registration.py:163 | |
| RANSAC: вероятность успеха | 0.9999 | registration.py:167 | |
| RANSAC: `ransac_n` | 3 | registration.py:161 | |
| Быстрый ICP `max_iter` | 50 | registration.py:201, 436 | |
| Грубый ICP `max_iteration` (пасс 1) | 80 | registration.py:263 | |
| Точный ICP `relative_fitness/rmse` | 1e-6 | registration.py:275-276 | |
| Таймаут ICP | 60 сек | registration.py:251, 487 | |
| Пост-порог RMSE warning | 5% bbox_diag | registration.py:554 | |
| Прогрессы внутри пайплайна | 35, 45, 52, 65, 68, 76, 80 | registration.py | |
| Watertight sanity порог | `max(1e-3, bbox_diag * 1e-4)` | deviation.py:83 | |
| Не-watertight: порог \|cos\| | 0.05 | deviation.py:113 | |
| ε для деления (cos) | 1e-10 | deviation.py:112 | |
| Прогресс после deviation | 88 | deviation.py:118 | |
| LUT-разрешение | 256 | deviation.py:391 | |
| Цвет ambiguous | `[0.55, 0.55, 0.55]` | deviation.py:418 | |
| Радиус кластеризации | `3.0 * avg_step` | deviation.py:248, 304 | `avg_step = bbox_diag / n^(1/3)` |
| OBB: порог невырожденности | 0.5 | dimensions.py:103 | |
| Единичные коэффициенты | 10, 25.4, 100, 1000 | dimensions.py:24-27 | `UNIT_HINT_RATIOS` |
| Допуск ratio в hint | 0.15 (15%) | dimensions.py:31 | |
| Размер страницы | A4 | report.py:34 | |
| Поле страницы | 18 мм | report.py:35 | |
| Гистограмма: figure | (8, 3.8) | report.py:61 | |
| Гистограмма: n_bins | `max(30, min(80, n//30))` | report.py:62 | |
| Гистограмма: цвета | `#4a90d9, #2c5f8a, #e53935, #43a047` | report.py:63-67 | |
| Colorbar: figure | (7, 1.0) | report.py:84 | |
| Высота легенды (стр.2) | 28 мм | report.py:459 | |
| Размер картинки скриншота | `(USABLE_W-6mm)/2 × × 0.62` | report.py:419-420 | |
| Высота гистограммы | `USABLE_W * 0.46` | report.py:470 | |
| Conformance threshold (умолч.) | 95 | report.py:171 | |
| Tolerance fallback | 0.5 мм | report.py:168-169 | |
| Colormap fallback | `"RdYlGn_r"` | report.py:174 | |
| Цвета шапок таблиц | `#3949AB, #283593, #37474F` | report.py:226, 259, 345, 499, 540 | |
| Verdict зелёный/красный | `#1B5E20/#E8F5E9` / `#B71C1C/#FFEBEE` | report.py:385-386 | |
| Цвет заголовка | `#1A237E` | report.py:148 | |
| `worst_n` по умолчанию | 10 | deviation.py:136 | |
| `min_cluster_size` по умолчанию | 3 | deviation.py:137 | |

### 12.3 ui/

| Имя / контекст | Значение | Файл:строка | Описание |
|---|---|---|---|
| `_UNIT_ITEMS` | `[("мм","mm"),("см","cm"),("м","m"),("дюйм","in")]` | panels.py:26-31 | |
| `_ALIGNMENT_ITEMS` | `[("Наилучшее вписывание","best_fit"),("Консервативный","conservative")]` | panels.py:34-37 | |
| Мин. размер главного окна | `1100 × 700` | main_window.py:69 | |
| Начальный размер | `1280 × 800` | main_window.py:70 | |
| Стиль `btn_run` | `#ad1457` / `#e91e63` / `#4a4a4a` | main_window.py:162-167 | |
| Стиль `btn_cancel` | `#C62828`, белый текст | main_window.py:168-171 | |
| Цвет `_stage_label` | `#e91e63`, курсив | main_window.py:196 | |
| Иконки тулбара | 24×24 | main_window.py:146 | |
| Ширина `status_info_label` | 300 | main_window.py:191 | |
| Ширина `_stage_label` | 240 | main_window.py:198 | |
| Ширина `progress_bar` | 180 | main_window.py:203 | |
| Лимит ширины левой колонки | 220 / 320 | main_window.py:218-219 | |
| Мин. высота `ViewerWidget` | 300 | main_window.py:249 | |
| Порог «большой файл» | 5_000_000 точек | main_window.py:377 | |
| Порог `ratio` для unit-hint | 5.0 | main_window.py:462 | |
| Порог RMSE warning (от диагонали) | 3% | main_window.py:743 | |
| Порог низкой доли в допуске | 50% | main_window.py:738 | |
| Порог `absorbed_within_tol_pct` | 5.0 пп | main_window.py:806 | |
| Порог для прогресс-диалога | 50 МБ | main_window.py:1083 | |
| Ожидание worker'а в `closeEvent` | 3000 мс | main_window.py:1121 | |
| Диапазон «Допуск ±(мм)» | 0.001–50.0, шаг 0.05, 3 знака | panels.py:129 | |
| Диапазон «Порог соответствия» | 80–100, шаг 1 | panels.py:134 | |
| Диапазон «Воксель» | 0.0–50.0, шаг 0.1 | panels.py:157-158 | |
| Диапазон «SOR k» | 5–100, шаг 1 | panels.py:165-166 | |
| Диапазон «SOR σ» | 0.5–5.0, шаг 0.1 | panels.py:174-175 | |
| Диапазон «Попытки RANSAC» | 1–20 | panels.py:187-188 | |
| Диапазон «Грубый ICP (%)» | 1.0–20.0, шаг 0.5 | panels.py:196-197 | |
| Диапазон «Точный ICP (%)» | 0.1–5.0, шаг 0.1 | panels.py:205-206 | |
| Диапазон «Итераций ICP» | 10–200, шаг 10 | panels.py:214-215 | |
| Размер кнопки ↻ | 24×24 | panels.py:427 | |
| Стиль кнопки ↻ | `#1e3a2e/#66cc88/#336644` / `#2a4e3a` / `#444/#333/#1a1a1a` | panels.py:429-437 | |
| Цвет вердикта «соответствует» | фон `#1B5E20`, текст `#A5D6A7` | panels.py:629-630 | |
| Цвет «не соответствует» | фон `#7f0000`, текст `#FFCDD2` | panels.py:635-636 | |
| Цвет ошибки в логе | `#FF6B6B` | panels.py:719 | |
| Цвет предупреждения | `#FFA726` | panels.py:721 | |
| Цвет «успешно» | `#66BB6A` | panels.py:723 | |
| Нейтральный текст | `#e8e8e8` | panels.py:724 | |
| Метка времени | `#909090` | panels.py:733 | |
| Шрифт результатов | Courier New 9–10 | panels.py:558, 587, 710 | |
| Стиль cancel-кнопки LogPanel | `#C62828`/`#D32F2F` | panels.py:694-697 | |
| Высота кнопок LogPanel | 22 | panels.py:683, 687, 691 | |
| Дефолт `_threshold` | 95.0 | panels.py:506 | |
| Цвет фона 3D `_BG` | `(0.10, 0.10, 0.12)` | viewer_widget.py:249 | |
| `_MAX_DISPLAY_PTS` | 600_000 | viewer_widget.py:215 | |
| Дефолт `_tolerance` | 0.5 | viewer_widget.py:258 | |
| Fallback палитры | `"RdYlGn_r"` | viewer_widget.py:260 | |
| Дефолтный режим вида | `"model"` | viewer_widget.py:261 | |
| Множитель расстояния камеры | `diag * 1.8` | viewer_widget.py:683 | |
| Изометрический ракурс | `(0.7d, −0.7d, 0.55d)` | viewer_widget.py:691 | |
| Окно offscreen-плоттера | 750×560 | viewer_widget.py:702 | |
| Scalar bar (n_labels/fmt/width/height) | 5 / `"%+.2f"` / 0.06 / 0.80 | viewer_widget.py:592-602 | |
| Положение scalar bar | x=0.02, y=0.10 | viewer_widget.py:598-599 | |
| Размер точки | 3 (live), 2 (offscreen) | viewer_widget.py:588, 717 | |
| Прозрачность меша в overlay | 0.22 (live), 0.28 (offscreen) | viewer_widget.py:569, 709 | |
| Прозрачность меша после анализа | 0.92 | viewer_widget.py:569 | |
| Цвет меша preview/результат | `#c8c8be / #c0c0b8` | viewer_widget.py:561, 572 | |
| Цвет рёбер | `#777766 / #444444` | viewer_widget.py:565, 576 | |
| Префиксы временных скриншотов | `geo_viewer_`, `geo_view_{name}_` | viewer_widget.py:653, 698 | |
| Стиль тулбара 3D | фон `#1a1a24`, бордюр `#2a2a3a` | viewer_widget.py:359-361 | |
| Активная кнопка режима вида | фон `#ad1457`, бордюр `#e91e63` | viewer_widget.py:373-375 | |
| Hint-полоса под 3D | фон `#14141a`, текст `#707080`, 10 px | viewer_widget.py:319-323 | |
| Размер HelpDialog | 820 × 620 | help_dialog.py:307 | |
| Размер AboutDialog | 420 × 260 (фикс.) | help_dialog.py:338 | |
| Версия / Автор / Организация / Год / Стек | `1.0` / `Отряхина В.Л.` / `РГАТУ им. П.А. Соловьёва` / `2026` / `Python · Open3D · PyQt6 · ReportLab` | help_dialog.py:362-368 | |
