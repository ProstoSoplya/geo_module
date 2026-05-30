# REVIEW_REPORT — модуль анализа отклонений геометрии деталей

**Дата:** 2026-05-30  
**Ветка:** master @ 74bef57  
**Стек:** Python 3.10+, PyQt6, Open3D 0.18+, PyVista/VTK 9.2+, NumPy, reportlab, matplotlib  
**Объём:** 14 .py-файлов (core/, ui/, tests/), ~6 600 строк.  
**Методология:** автоматическое чтение всех файлов + 4 субагента (algorithms, ui, tests, security) + кросс-модульная сверка с IMPLEMENTATION_REPORT.md и AUDIT_RESULTS.md.

---

## Executive Summary

Кодовая база — относительно зрелое десктоп-приложение для метрологического контроля.
Архитектура чёткая (core/ algorithmы — ui/ — worker QThread с сигналами), соблюдается
разделение потоков, QueuedConnection прописан явно, есть тесты. После Q1–Q5
большинство критичных багов из предыдущего аудита закрыты (распаковка 5-tuple,
изоляция базового режима через `core/defaults.py`, диагностика поглощённого
отклонения).

Однако ревью выявило **новый класс критических находок**, не обнаруженных
прошлым аудитом — связанных с математической корректностью трансформаций,
гонками жизненного цикла worker'а и неустойчивостью PCA. По severity:

- **Critical: 11** (включая 5 алгоритмических, 4 UI/threading, 1 security, 1 тест)
- **Major: 27**
- **Minor: 35+**
- **Info: 20+**

### ТОП-3 критических проблемы

1. **CRIT-A1 (algorithms/registration.py:516)** — финальная матрица регистрации
   возвращается без учёта `T_centroid`. Сохранённая в NPZ `transformation`
   при применении к исходному `pcd_full` НЕ восстанавливает совмещение —
   фундаментальная ошибка контракта данных проекта.
2. **CRIT-U1 (ui/main_window.py + worker.py)** — несколько race-conditions
   жизненного цикла worker: повторный запуск через модальные диалоги, смена
   единиц/drag&drop/open_project во время анализа мутируют pcd/mesh, с
   которыми работает фоновый поток. Open3D не thread-safe.
3. **CRIT-S1 (core/project_manager.py:262–284)** — пути `cad_path`/`scan_path`
   и параметры конфига из `project.json` подставляются без валидации
   (path traversal + injection в runtime-конфиг алгоритмов).

Остальные критические — пересоздание BVH-сцены, вырожденность PCA на симметричных
деталях, отсутствие изоляции `_SHARED` в тестах, утечка C++-потока при таймауте
ICP, race в `_make_loading_dialog` / `_load_*_from_path` при cancel.

### Расхождение с зафиксированным состоянием

- **Тема**: память пользователя (`project_light_theme.md`, 2026-05-28) утверждает
  миграцию на светлую тему с `_LIGHT_QSS` активным; в коде `main.py:22–251, 347`
  активна тёмная `_DARK_QSS`, `_LIGHT_QSS` отсутствует. Это либо регрессия
  после миграции, либо память устарела. Проверка: `Grep "_LIGHT_QSS"` —
  пустой результат.

---

## Критические проблемы (Critical)

> Формат: `<категория>.N | <file:line> | описание / доказательство / рекомендация`

### CRIT-A1. T_selected без учёта T_centroid в `register_pipeline` возврате
**`core/algorithms/registration.py:339–344, 516, 540`**

```python
# строка 344:
pcd_full_aligned = copy.deepcopy(pcd_full).transform(T_centroid)
# строки 446–469: best_T = T_fine (или T_coarse), вычислено от pcd_full_aligned
T_selected = best_T
# строка 516:
pcd_registered = pcd_full_aligned.transform(T_selected)
# строка 540:
return pcd_registered, T_selected, rmse_out, registration_suspect, reg_diagnostics
```

`T_selected` — трансформация от **уже центроидно-выровненного** облака, а не
от исходного `pcd_full`. NPZ сайдкар (`project_manager.py:239 transformation`)
сохраняет `T_selected`. При перезагрузке проекта применение этой матрицы к
свежезагруженному `pcd_full` (`T_selected @ pcd_full`) НЕ восстановит совмещение
— потерян предварительный сдвиг `T_centroid`.

**Доказательство расхождения:** в worker.py:147 распаковка `transform = T_selected`
сохраняется как `self.transformation = transform` (project_manager.save_results),
дальше → NPZ. Загрузка проекта (`load_project`) подгружает `pcd_points` (уже
выровненные точки) и `transformation` (без centroid). Любой инструмент,
применяющий `transformation @ original_scan`, получит несовмещённый результат.

**Рекомендация:** возвращать `T_total = T_selected @ T_centroid` либо хранить
обе матрицы в `reg_diagnostics` и в NPZ. Документировать семантику.

---

### CRIT-A2. Пересоздание BVH-сцены в `compute_deviations` (2× построение на анализ)
**`core/algorithms/deviation.py:57–59` vs `core/algorithms/registration.py:365–367`**

В `register_pipeline` `RaycastingScene` строится для `_evaluate_candidate` и
`_c2m_stats_down`, затем выбрасывается. В `compute_deviations` строится снова
с нуля на том же меше:

```python
# deviation.py:57-59
mesh_t = o3d.t.geometry.TriangleMesh.from_legacy(mesh)
scene  = o3d.t.geometry.RaycastingScene()
scene.add_triangles(mesh_t)
```

На меше ~1М треугольников: BVH строится секундами. Заголовок `registration.py`
обещает «BVH 1 раз», но это верно только внутри `register_pipeline`.

**Impact:** удвоение времени фазы 4 (80→97%) на крупных моделях, 2–5 секунд.

**Рекомендация:** добавить `scene=None` параметр в `compute_deviations`, передавать
готовую из worker. Альтернативно — вернуть `scene` шестым элементом из
`register_pipeline` или модульный lazy-кэш по `id(mesh)`.

---

### CRIT-A3. PCA нестабильна на квазипланарных/симметричных деталях
**`core/algorithms/registration.py:114–119, 105–139`**

```python
def pca_frame(pts):
    cov = np.cov((pts - c).T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    idx = np.argsort(eigvals)[::-1]
    return c, eigvecs[:, idx]
```

При кратных собственных значениях (тело вращения, две равные оси) сортировка
по `argsort` нестабильна — порядок зависит от шума. Для квази-планарной детали
(Z ≈ const) два eigval ≈ 0; направления двух осей произвольны и **независимо
поворачиваются** между mesh и pcd → 4 знаковые PCA-гипотезы не покрывают
поворот в плоскости. RANSAC может спасти, но не гарантированно.

**Доказательство:** на L-shape тестах работает, но для производственных
плоских кронштейнов или цилиндров — потенциальный тихий провал.

**Рекомендация:** при отношении `eigvals[0]/eigvals[2] > 100` или близости двух
λ — логировать предупреждение и дополнительно генерировать in-plane
rotation-гипотезы (8 поворотов по 45°).

---

### CRIT-A4. `_icp_with_timeout` оставляет C++-поток после таймаута
**`core/algorithms/registration.py:228–243`**

```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
    fut = executor.submit(...)
    return fut.result(timeout=timeout)
finally:
    executor.shutdown(wait=False)
```

`shutdown(wait=False)` не прерывает выполняемую ICP-итерацию — Open3D C++ не
прерывается. При таймауте 60с поток продолжает молотить полное число итераций
в фоне, конкурируя с UI за CPU. `_icp_two_pass` создаёт 2 таких пула; повторные
анализы накапливают «висящие» ICP. Также cancel-флаг `_cancelled` не проверяется
внутри C++-вызовов — отмена в фазе регистрации фактически не работает.

**Рекомендация:** либо документировать как «leak by design», уменьшить
max_iteration грубого прохода с 80 до 40, либо перейти на нативные callback'и
Open3D (если есть).

---

### CRIT-A5. `_compute_adaptive_params` падает на вырожденном меше
**`core/algorithms/registration.py:32–54, 303–321`**

`bbox_diag = np.linalg.norm(...)` для вырожденного меша → 0. Дальше:
- `reg_voxel = bbox_diag * 0.02 = 0` → `pcd.voxel_down_sample(0)` падает с
  Open3D ошибкой без диагностики.
- `fpfh_radius = 0` → `compute_fpfh_feature` ошибка.
- `arccos((trace-1)/2)` в диагностике защищён `np.clip` (стр. 477) ✓.

**Рекомендация:** в начале `register_pipeline`:
```python
if bbox_diag < 1e-6:
    raise RegistrationError("CAD-меш вырожден (нулевой bbox)")
```

---

### CRIT-U1. Повторный запуск анализа возможен через модальные диалоги
**`ui/main_window.py:377–479, 260–285, 892–921`**

`run_analysis()` проверяет `worker.isRunning()` на стр. 378, но между этой
проверкой и `_set_analysis_running(True)` на стр. 455 показываются `QMessageBox.exec()`
(стр. 390–435). Внутри модального диалога event loop живёт, и пользователь
может через drag&drop / меню / тулбар:
- сбросить `self.manager.mesh/pcd` (`load_cad`/`load_scan`);
- сменить единицы (см. CRIT-U2);
- запустить параллельный анализ через `open_project` (см. CRIT-U3).

Worker уже захватил ссылки на старые объекты, новый worker создаётся на
новых — рассогласование `_on_analysis_finished` с актуальным состоянием
`manager`.

**Рекомендация:** ввести единое поле `self._analysis_state` (idle/preparing/running)
и проверять во ВСЕХ точках входа: dropEvent, load_cad/scan, _on_param_changed
(units), open_project, save_report.

---

### CRIT-U2. Смена единиц во время анализа мутирует объекты worker'а
**`ui/main_window.py:867–921, 933–964`**

`_on_param_changed` при смене `units.cad`/`units.scan` вызывает
`_load_cad_from_path`/`_load_scan_from_path`, которые **подменяют ссылки**
`self.manager.mesh`/`self.manager.pcd`. Если worker уже работает с этими
объектами в фоновом потоке (Open3D KDTree, ICP), параллельная подмена
вызывает гонку **внутри C++/Eigen** (Open3D не thread-safe для общих объектов).

`_set_analysis_running(True)` (стр. 933–964) отключает только btn_load_*,
btn_run, btn_report, viewer, log_panel, но **не control_panel и не units-комбобоксы**.

**Рекомендация:** `self.control_panel.setEnabled(not running)` целиком, либо
явный список с включением units-комбобоксов.

---

### CRIT-U3. `open_project` race с активным анализом
**`ui/main_window.py:544–651`**

`open_project()` свободно перезаписывает `manager.mesh/pcd/stats/pcd_colored`
без проверки `worker.isRunning()`. Worker держит старые ссылки (GC безопасно),
но `viewer.load_results/load_mesh_preview` ставит новые акторы; UI считает,
что результатов нет → при последующем `analysis_finished` сохраняется в
рассинхронизированный manager.

**Рекомендация:** проверка `worker.isRunning()` в начале `open_project`,
`save_project`, `load_cad`, `load_scan`, `save_report` с warning-диалогом.

---

### CRIT-U4. `closeEvent` + `worker.wait(3000)` — поток может пережить виджеты
**`ui/main_window.py:1045–1048, 1088`**

```python
if self.worker and self.worker.isRunning():
    self.worker.cancel()
    self.worker.wait(3000)
```

Если worker за 3с не завершился (например, длинная фаза ICP без проверок
cancel), `event.accept()` уничтожает виджеты. Worker эмитит `log_message.emit(...)`
в QueuedConnection — слот в уже уничтоженном LogPanel. На Windows обычно
сегфолт или `QObject::~QObject: Timers cannot be stopped from another thread`.
`self.viewer.plotter.close()` (стр. 1088) синхронен — это OK, worker viewer не
трогает.

**Рекомендация:** при таймауте `wait` — `self.worker.disconnect()` явно перед
`event.accept()`, либо `event.ignore()` + модальный диалог «Завершение анализа…»
с увеличенным таймаутом.

---

### CRIT-S1. Path traversal: `cad_path`/`scan_path` из project.json без валидации
**`core/project_manager.py:272–284`**

```python
if project.get("cad_path"):
    if os.path.exists(project["cad_path"]):
        self.load_cad(project["cad_path"], unit=saved_unit_cad)
```

Пути из внешнего JSON открываются без какой-либо санитизации. Вредоносный
`project.json` с UNC-путём `\\\\attacker\\share\\evil.stl` или абсолютным путём
к системному файлу заставит Open3D обработать произвольный файл. Прямой RCE
маловероятен, но Open3D имеет историю segfault при парсинге битых STL/PLY (C++).
Также `unit_cad`/`unit_scan` из JSON попадают в `UNIT_TO_MM.get(unit, 1.0)`
без проверки.

**Рекомендация:** проверять, что путь находится в пределах рабочей директории
или диалоговый запрос «открыть файл из недоверенного источника?».

---

### CRIT-T1. `test_q5_integration.py:289` — `test_pdf_sections` ложно PASSES без `pypdf`
**`tests/test_q5_integration.py:283–291`**

```python
try:
    import pypdf
except ImportError:
    print("\n[Q5.4 PDF] pypdf not installed — skipping text extraction")
    return  # PASSED без единого assert
```

`pypdf` опциональный. При его отсутствии тест **проходит** без проверок,
маскируя любую регрессию в `generate_report`. Pytest при этом даже не
импортирован — нельзя использовать `pytest.skip`.

**Рекомендация:** `import pytest; pytest.skip("pypdf not installed", allow_module_level=False)`.

---

## Серьёзные проблемы (Major)

### Алгоритмы

**MAJ-A1.** `compute_deviations`: возможная двойная инверсия знака для inside-out
STL — `is_watertight()` возвращает True даже при inverted normals, sanity-check
(`deviation.py:83–85`) сравнивает только модули. **Рекомендация:** добавить
проверку согласованности ≥50% знаков heuristic vs winding.

**MAJ-A2.** `_evaluate_candidate`: deepcopy на каждой гипотезе (`registration.py:206, 215`).
До 9 гипотез × 2 deepcopy = 18 копий полного pcd_down (200k точек). **Рекомендация:**
работать с numpy-массивами, переносить точки без копирования Open3D-структуры.

**MAJ-A3.** `_build_worst_points` — `bbox_diag/n^(1/3)` для оценки avg_step
(`deviation.py:223–226`) предполагает 3D-заполнение, но скан — поверхностный.
Для тонкой пластины радиус фильтрации завышен. **Рекомендация:**
`sqrt(bbox_diag² / n)` или `pcd.compute_nearest_neighbor_distance()`.

**MAJ-A4.** `compute_dimensions` fallback к AABB с сортировкой (`dimensions.py:113–138`)
делает `delta = scan_extent - cad_extent` математически бессмысленным, так как
после sort оси CAD и scan уже не соответствуют пространственно. **Рекомендация:**
при `det(R) < 0.5` возвращать `delta = None` + warning.

**MAJ-A5.** `pcd_full.estimate_normals` без `orient_normals_consistent_tangent_plane`
(`registration.py:82–86`) — несогласованные нормали для Point-to-Plane ICP на
полном облаке.

**MAJ-A6.** `compute_statistics`: `len(deviations)` без проверки на 0 —
`ZeroDivisionError` (`deviation.py:149–151`).

**MAJ-A7.** `report.py:548–556`: переменные `cbar_path`, `hist_path` в `finally`
блоке не инициализированы в начале функции — `NameError` при ранней ошибке
до их присвоения.

**MAJ-A8.** `_ransac_multistart` при ошибке всех стартов возвращает пустой
список (`registration.py:175–176, 183`) — тихая деградация, pipeline продолжает
с identity.

**MAJ-A9.** `_evaluate_candidate` исключения проглатываются (`registration.py:428–429`)
— тихий пропуск кандидата.

**MAJ-A10.** `colorize_point_cloud`: `pcd_colored.points = pcd.points` —
shared Vector3dVector (`deviation.py:399–403`). Мутация одного влияет на другой.
В `results` хранятся оба — потенциальная путаница.

### UI и threading

**MAJ-U1.** `_cancelled` — bool без блокировки (`worker.py:66–71`). CPython GIL
делает запись/чтение bool атомарными, но семантика memory visibility формально
не определена. **Рекомендация:** `threading.Event` или `QAtomicInteger`.

**MAJ-U2.** `make_multiview_screenshots` блокирует GUI thread (`viewer_widget.py:618–686`,
вызов `main_window.py:511`). На крупных мешах — десятки секунд без прогресса.

**MAJ-U3.** `make_multiview_screenshots`: `pl.close()` вне per-iteration finally
— при exception в первой итерации остальные plotter'ы остаются открытыми
(утечка VTK renderer/window context).

**MAJ-U4.** `_ViewerInteractionFilter` ставится единожды (`viewer_widget.py:329–348`),
но `_render()` через `QTimer.singleShot(0, ...)` отложен; пользователь может
кликать до установки. Также VTK при resize/DPI-change пересоздаёт детей —
фильтр на новых не появится.

**MAJ-U5.** `_render()` вызывает `plotter.clear()` (`viewer_widget.py:520`) + 
`reset_camera()` (стр. 592) при каждой смене режима → потеря позиции камеры.
UX-регрессия: пользователь приблизил дефект, переключил режим — вернулся в обзор.

**MAJ-U6.** Колормап жёстко зашит `"RdYlGn_r"` в 5 местах (worker.py:239,
main_window.py:586/730/823, viewer_widget.py:259), при этом `config["ui"]["colormap"]`
используется только в `report.py:169` → **расхождение UI vs PDF**.
help_dialog упоминает выбор палитры. См. также CRIT-T memory mismatch.

**MAJ-U7.** Тема: память пользователя описывает завершённую миграцию на
светлую тему (`_LIGHT_QSS`, `_DARK_QSS_LEGACY`, LOD 100k точек,
ColormapCombobox с `currentData()`), но в коде `main.py:22–251, 347` —
только `_DARK_QSS`. Это либо регрессия, либо память устарела. Виджеты
содержат hardcoded тёмные акценты (panels.py:600/627/633/654), VTK фон
`_BG=(0.10, 0.10, 0.12)` (viewer_widget.py:249).

**MAJ-U8.** Hardcoded размеры без HiDPI (main_window.py:65, panels.py:155/312/382/393/426,
help_dialog.py:307/338). `Qt.AA_EnableHighDpiScaling` не выставлен. На Win10 @ 150% — обрезка.

**MAJ-U9.** `setStyleSheet` локально на ControlPanel/ResultsPanel (`panels.py:80, 514`)
переопределяет глобальный QSS для потомков.

**MAJ-U10.** Слоты Qt без try/except — `_on_analysis_finished`, `_on_param_changed`,
`LogPanel.append` (под QueuedConnection после уничтожения widget) могут молча
проглатывать AttributeError.

**MAJ-U11.** Drag&drop активен во время анализа и модальных диалогов
(`main_window.py:260–285`).

**MAJ-U12.** Help_dialog описывает несуществующую функциональность:
кнопка «Показать 3D-вид», выбор палитры, метрики «Стд. отклонение», единица
«как есть» в UI отсутствует в `_UNIT_ITEMS`.

**MAJ-U13.** `save_report` использует `manager.unit_cad/unit_scan` без проверки
наличия (main_window.py:523–524) — если scan не загружен, атрибут может
отсутствовать.

**MAJ-U14.** Сигналы worker не disconnected перед созданием нового
(`main_window.py:463–479`) — если предыдущий worker не GC, эмиты продолжатся.

**MAJ-U15.** `analysis_error` интерпретируется по подстроке `"отмен"`
(`main_window.py:760–772`) — хрупко. Нужен отдельный `analysis_cancelled`-сигнал.

### Безопасность

**MAJ-S1.** Config injection: `project_manager.py:262–263` использует поверхностный
`self.config.update(project["config"])` — целые секции заменяются без deep_merge
и без валидации типов. Строка `"ransac_max_iter": "evil"` или огромное число
проходит без ошибок до `RANSACConvergenceCriteria`.

**MAJ-S2.** Malformed STL/PLY: `o3d.io.read_*` может вызвать **C++ segfault** при
повреждённом файле (известная проблема Open3D 0.18 на PLY). Python try/except
не поможет.

**MAJ-S3.** Отсутствует валидация диапазонов config.json (main.py:292–329):
`tolerance_mm < 0`, `sor_neighbors = 0`, `voxel_size < 0`,
`conformance_threshold > 100` принимаются без ошибок.

**MAJ-S4.** Предсказуемые имена временных файлов скриншотов
(`viewer_widget.py:614, 649`): `geo_viewer_screenshot.png`, `geo_view_{name}.png`.
При двух экземплярах приложения — взаимная перезапись. `_take_screenshot` не
имеет finally с unlink.

**MAJ-S5.** app.log без ротации, append-режим, путь относительно `cwd` (main.py:271).
Рост неограничен; при запуске через ярлык cwd может быть системной директорией.

**MAJ-S6.** Голые `except Exception: pass` в критических путях:
`main_window.py:1083–1090` (save_config при closeEvent — потеря настроек без
уведомления), `viewer_widget.py:683–684` (трейсбек не логируется),
`registration.py:175–176, 428–429` (см. MAJ-A8/A9).

### Тесты

**MAJ-T1.** `_SHARED` — модульный синглтон в test_q5_integration.py:163–175
без pytest fixture-scope. Нарушение изоляции тестов; первый вызвавший
определяет состояние.

**MAJ-T2.** `test_worst_points` (test_q5:220–222): `abs(first_abs - max_abs) < 1e-8`
может ложно упасть после фильтрации `_build_worst_points` по плотности
кластера (deviation.py:198–258). Если точка с максимумом — изолированный шум,
её отфильтруют, тест упадёт на корректно работающем коде.

**MAJ-T3.** `test_false_minimum_Lshape` (test_registration_robustness.py:292–376):
`assert failures == 0` при стохастическом Open3D RANSAC без C++-уровня seeding
→ потенциально флейки.

**MAJ-T4.** `_NORMAL_CONFIG` в test_registration_robustness.py:147–160 расходится
с `BASIC_DEFAULTS` (ransac_n_starts: 6 vs 5, icp_coarse_pct: 3.5 vs 5.0,
icp_fine_pct: 1.3 vs 1.0, icp_max_iter: 200 vs 150). Тест не проверяет
production-дефолты.

**MAJ-T5.** `_CONFIG` в test_q5_integration.py:111–133 не содержит ключей
`use_pca_seeds`, `reject_rmse_pct`, `ransac_top_k` → поведение зависит от
дефолтов `.get()` в registration.py. Регрессия дефолтов не зафиксируется.

**MAJ-T6.** `except (RegistrationError, TimeoutError, Exception)`
(test_registration_robustness.py:347–351) — слишком широкий catch. Опечатки
конфига скроются под failures.

**MAJ-T7.** Покрытие 0%: `core/algorithms/dimensions.py`, `core/algorithms/colorize_point_cloud`,
`core/project_manager.py`, `core/worker.py`, всё `ui/`. Негативные тесты
(RegistrationError, malformed files) отсутствуют.

---

## Незначительные проблемы (Minor)

### Алгоритмы

- `preprocessing.py:128–130`: `float("nan") <= 0` → False, NaN voxel_size
  передаётся в Open3D.
- `registration.py:71–78`: hardcoded 50000/20000 точек семплирования меша.
- `registration.py:87`: `k=15` для `orient_normals_consistent_tangent_plane`
  подобран на глаз; на разреженных облаках мало.
- `registration.py:289`: `pcd_voxel_size: float = 0.0` как sentinel вместо `None`.
- `registration.py:482`: `config.get("analysis", {})` рассогласовано с
  `worker.py:202` (`self.config["analysis"]["tolerance_mm"]` без get).
- `report.py:53–54`: Helvetica fallback без кириллицы — отчёт сгенерится с
  тофу вместо текста; должен бросать исключение.
- `report.py:62`: формула n_bins корректна, но не задокументирована.
- `deviation.py:329`: `np.array(members)` — лишняя обёртка.
- `deviation.py:55`: `points.astype(np.float32)` — потеря точности для
  координат >10⁶ мм (info, не баг).
- `worker.py:75`: `_cancelled` проверяется только в `_emit_progress`.
- `defaults.py`: 25 строк, корректная изоляция базового режима.

### UI

- `panels.py:481–482`: `_set_unit_combo` под `_updating=True` не синхронизирует
  `manager.unit_cad`.
- `panels.py:587–588`: word-wrap `_dim_delta` может разорвать пару значений.
- `panels.py:707–735`: `LogPanel.text_edit` без `setMaximumBlockCount` —
  неограниченный рост.
- `panels.py:713–721`: `_classify_color` по подстроке — «не завершён»
  окрашивается зелёным из-за «завершён».
- `panels.py:618–621`: `format_map.get(key, lambda v: f"{v:.4f}")` — `None`
  значения вызовут ValueError.
- `main_window.py:148–149, 1012`: Unicode-символы '▶', '■' зависят от шрифта;
  `QProgressDialog` без cancel-кнопки → пользователь не отменит зависшую
  загрузку 50+ МБ.
- `main_window.py:954, 960–961`: `restoreOverrideCursor` в цикле снимает курсор
  и для других диалогов.
- `main_window.py:740–758`: два подряд модальных диалога после анализа.
- `viewer_widget.py:95–113`: ПКМ-drag — если release ушёл вне plotter,
  `_last_pos != None`, последующие move без зажатой кнопки сделают «free pan».
- `viewer_widget.py:163–208`: `_recenter_at` не учитывает devicePixelRatio
  для z-buffer pickPosition.
- `viewer_widget.py:43–55`: `_TrackballNoDolly` ловит обновления VTK без guard'а.
- `help_dialog.py:317`: белый фон браузера в тёмной теме — рассогласование.

### Безопасность

- `main.py:271`: app.log в cwd, без ротации.
- `report.py:44–45`: hardcoded `C:/Windows/Fonts/arial.ttf`.
- `project_manager.py:291–295`: `allow_pickle=False` ✓, но формы массивов не
  проверяются.
- `requirements.txt`: открытые верхние границы (`open3d>=0.18.0` и т.п.).
  CVE-2021-34141, CVE-2021-41496 для NumPy <1.26.4 включены диапазоном.
- `project_manager.py:108, 161, 247–248, 329, main.py:325–326`: полные пути
  пишутся в app.log и LogPanel (раскрытие имени пользователя).
- `project_manager.py:258–259`: `json.load` в `load_project` без try/except.
- `main_window.py:268–285`: drop без `os.path.exists` проверки.

### Тесты

- `test_registration_robustness.py:16`: `import copy` не используется.
- `test_registration_robustness.py:255, 307, 401`: `np.random.seed()` legacy API
  без изоляции.
- `test_q5_integration.py:331–367`: проверка кириллицы в PDF через `pypdf`
  без нормализации Unicode.
- Отсутствует `conftest.py` — `sys.path.insert(0, str(ROOT))` дублируется в
  каждом файле.
- `test_worst_points` не проверяет координаты (только dev и порядок).
- `_BUGGY_CONFIG` покрывает только сценарий 180°-минимума; нет тестов для
  scan вне bbox, mesh с 0 треугольниками, RegistrationError при всех провалах.

---

## Информационные замечания (Info)

- `i1` Возвращаемые типы согласованы: `preprocess_pipeline` → 3-tuple,
  `register_pipeline` → 5-tuple, `compute_deviations` → 2-tuple, тесты
  распаковывают правильно.
- `i2` Q1–Q5 регрессий не обнаружено: worker.py:120–125 корректно использует
  `BASIC_DEFAULTS`, advanced/basic режим изолированы.
- `i3` QueuedConnection указана явно (main_window.py:472–477) — хорошая практика.
- `i4` `arccos` clamp `np.clip` присутствует (registration.py:477).
- `i5` PCA: `det(R) = +1` гарантируется через `target_det_S` (registration.py:124–126).
- `i6` LUT-раскраска эффективна (deviation.py:213+), кеш `_LUT_CACHE`.
- `i7` Отсутствие `eval`/`exec`/`subprocess`/`os.system` — подтверждено grep'ом.
- `i8` Экранирование HTML в LogPanel (panels.py:726–732) — корректно.
- `i9` `allow_pickle=False` в NPZ загрузке — безопасно.
- `i10` LOD-логика, описанная в memory (`_LOD_DISPLAY_PTS=100_000`,
  `_set_lod()`), в коде НЕ найдена. Активен только `_MAX_DISPLAY_PTS=600_000`
  с равномерным прореживанием (viewer_widget.py).
- `i11` `_recalc_buttons` (panels.py:73) — список с одной кнопкой, «на вырост».
- `i12` `_ArrowOnHoverFilter` дублирован в main_window.py:49–60 и panels.py:39–49
  (известно из AUDIT_RESULTS M5).
- `i13` Дублирование `worst_points` восстановления в project_manager.py:283–308
  и main_window.py:614–642 (известно из AUDIT_RESULTS D1).
- `i14` Мёртвый код из AUDIT_RESULTS (M1–M8) сохраняется в кодовой базе.

---

## Матрица покрытия тестами

| Модуль | Покрытие | Что нужно дотестировать |
|---|---|---|
| `core/algorithms/preprocessing.py` | частично (через integration) | `remove_outliers` напрямую; `n_before < 10`; `n_after == 0`; NaN voxel_size |
| `core/algorithms/registration.py` | значительно (2 файла) | `alignment_mode="conservative"`; `registration_suspect=True`; `reuse=False` явный пересчёт; `_ransac_multistart` n_starts=0; вырожденный PCA; вырожденный mesh |
| `core/algorithms/deviation.py` (compute_deviations) | частично | ветка `not is_watertight()`; sanity-check warning; inverted-normals STL |
| `core/algorithms/deviation.py` (compute_statistics) | значительно | `point_coords=None`; `n_candidates < min_cluster_size`; `len(deviations)==0`; `defect_clusters` |
| `core/algorithms/deviation.py` (colorize_point_cloud) | **0%** | вся функция |
| `core/algorithms/dimensions.py` | **0%** | `compute_dimensions`, `bbox_summary`, `suggest_unit_mismatch_hint`, fallback OBB |
| `core/algorithms/report.py` | частично (`test_pdf_sections` ложно проходит без pypdf) | пустой `screenshot_paths`; `dims=None`; ветка Helvetica; кириллица как баг |
| `core/project_manager.py` | **0%** | `load_cad/scan`, `save/load_project`, `_reset_results`, неподдерживаемые форматы, `has_npz=True`, malformed JSON |
| `core/worker.py` | **0%** | `AnalysisWorker.run()`, `cancel()`, сигналы (нужен QApplication mock) |
| `ui/main_window.py` | **0%** | требует pytest-qt + QApplication |
| `ui/panels.py` | **0%** | требует pytest-qt |
| `ui/viewer_widget.py` | **0%** | требует pytest-qt + VTK |
| `ui/help_dialog.py` | **0%** | требует pytest-qt |
| Error paths (RegistrationError) | **0%** | нет `pytest.raises(RegistrationError)` |
| Error paths (file format, NaN/Inf) | **0%** | нет негативных тестов |

---

## Приоритизированный план исправлений

### Уровень 1 — Критические (1–3 дня, до защиты обязательно)

| № | Задача | Файлы | Категория |
|---|--------|-------|-----------|
| L1.1 | **CRIT-A1**: `T_total = T_selected @ T_centroid` или сохранение обеих в reg_diagnostics + NPZ | `registration.py:516, 540`, `worker.py:147`, `project_manager.py:239` | data contract |
| L1.2 | **CRIT-S1**: валидация cad_path/scan_path при load_project (проверка traversal, диалог подтверждения) | `project_manager.py:272–284` | security |
| L1.3 | **MAJ-S1**: deep_merge + валидация типов config из project.json | `project_manager.py:262–263` | security |
| L1.4 | **CRIT-U1+U2+U3**: единый `_analysis_state` флаг во всех точках входа (drop, units, open_project, save_report, load_*) | `main_window.py` глобально | threading |
| L1.5 | **CRIT-U4**: `worker.disconnect()` при таймауте wait в closeEvent | `main_window.py:1045–1048` | threading |
| L1.6 | **CRIT-A5**: guard `bbox_diag < 1e-6` в начале register_pipeline | `registration.py:284–290` | edge case |
| L1.7 | **CRIT-T1**: заменить `return` на `pytest.skip` в test_pdf_sections | `test_q5_integration.py:283–291` | tests |
| L1.8 | **MAJ-S3**: валидация диапазонов config.json после load_config | `main.py:292–329` | security |
| L1.9 | **MAJ-A6**: ранний return в `compute_statistics` для пустого массива | `deviation.py:149` | edge case |
| L1.10 | **MAJ-A7**: инициализировать `cbar_path=None, hist_path=None` в начале `generate_report` | `report.py` | bug |

**Оценка: 12–18 часов.**

### Уровень 2 — Major (3–7 дней, желательно)

| № | Задача | Файлы |
|---|--------|-------|
| L2.1 | **CRIT-A2**: shared BVH между register_pipeline и compute_deviations | registration.py, deviation.py, worker.py |
| L2.2 | **CRIT-A3**: предупреждение о вырожденной PCA + расширенный набор гипотез для симметричных деталей | registration.py |
| L2.3 | **CRIT-A4**: документировать leak ICP-таймаута, уменьшить max_iter coarse | registration.py |
| L2.4 | **MAJ-U1**: `threading.Event` для `_cancelled` | worker.py |
| L2.5 | **MAJ-U2**: прогресс-диалог для make_multiview_screenshots | viewer_widget.py, main_window.py |
| L2.6 | **MAJ-U5**: сохранение положения камеры при смене режима | viewer_widget.py |
| L2.7 | **MAJ-U6**: единый источник colormap (config или хардкод везде) | worker.py, main_window.py, viewer_widget.py, report.py |
| L2.8 | **MAJ-U7**: разобраться с темой — восстановить _LIGHT_QSS или обновить память | main.py |
| L2.9 | **MAJ-A1, A2, A5**: убрать deepcopy в _evaluate_candidate, согласовать нормали pcd_full | registration.py |
| L2.10 | **MAJ-A3**: правильная оценка avg_step через surface area | deviation.py |
| L2.11 | **MAJ-A4**: `delta=None` при вырожденном OBB | dimensions.py |
| L2.12 | **MAJ-A10**: shared Vector3dVector — клонировать points в colorize | deviation.py |
| L2.13 | **MAJ-S2**: предупреждение о возможном crash на malformed файлах | project_manager.py, main_window.py |
| L2.14 | **MAJ-S4**: tempfile.mkstemp для скриншотов + finally unlink | viewer_widget.py |
| L2.15 | **MAJ-S5**: RotatingFileHandler для app.log в `platformdirs.user_log_dir` | main.py |
| L2.16 | **MAJ-T1**: pytest fixture `scope="module", autouse=True` для _SHARED | test_q5_integration.py |
| L2.17 | **MAJ-T2**: проверять worst_points с учётом фильтрации | test_q5_integration.py |
| L2.18 | **MAJ-T7**: dimensions/colorize/project_manager — добавить unit-тесты | new tests |

**Оценка: 5–7 дней.**

### Уровень 3 — Minor + код-гигиена (когда будет время)

| № | Задача |
|---|--------|
| L3.1 | Hardcoded размеры → адаптивный layout + AA_EnableHighDpiScaling |
| L3.2 | Удалить мёртвый код AUDIT_RESULTS M1–M8 |
| L3.3 | Согласовать help_dialog с реальной функциональностью |
| L3.4 | `setMaximumBlockCount` для LogPanel |
| L3.5 | `_classify_color` — точное совпадение, не подстрока |
| L3.6 | Bare except в worker/main_window — логировать traceback |
| L3.7 | `conftest.py` + `pyproject.toml` с pythonpath |
| L3.8 | Удалить shared `_ArrowOnHoverFilter` (вынести в общий модуль) |
| L3.9 | `_reg_keys` в модульную константу (D3 из AUDIT) |
| L3.10 | Закрепить версии зависимостей с верхней границей |

---

## Что НЕ изменено

Согласно `.claude/CLAUDE.md` («Не изменяй код. Только анализируй и документируй»),
ни одна строка кода не модифицирована. Этот отчёт — материал для решения
о порядке исправлений.

Если требуется реализация — запросите конкретный пункт (L1.x, L2.x), и я
выполню изменения с тестами и дифом.
