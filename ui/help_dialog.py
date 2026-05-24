"""
help_dialog.py — Окна «Руководство пользователя» и «О программе».
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# ── HTML-содержимое справки ────────────────────────────────────────
_HELP_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  body   { font-family: Arial, sans-serif; font-size: 13px;
           margin: 12px; color: #212121; }
  h1     { color: #1565C0; font-size: 18px;
           border-bottom: 2px solid #1565C0; padding-bottom: 4px; }
  h2     { color: #2E7D32; font-size: 14px; margin-top: 18px; }
  p      { margin: 4px 0 8px 0; }
  ol, ul { margin: 4px 0 8px 16px; }
  li     { margin-bottom: 3px; }
  table  { border-collapse: collapse; width: 100%; margin: 8px 0; }
  th     { background: #E3F2FD; padding: 6px 8px;
           text-align: left; border: 1px solid #90CAF9; }
  td     { padding: 5px 8px; border: 1px solid #BDBDBD; }
  tr:nth-child(even) td { background: #F5F5F5; }
  .tip   { background: #E8F5E9; border: 1px solid #A5D6A7;
           padding: 8px 10px; margin: 6px 0; border-radius: 4px; }
  .warn  { background: #FFF8E1; border: 1px solid #FFE082;
           padding: 8px 10px; margin: 6px 0; border-radius: 4px; }
  .err   { background: #FFEBEE; border: 1px solid #EF9A9A;
           padding: 8px 10px; margin: 6px 0; border-radius: 4px; }
  kbd    { background: #EEEEEE; border: 1px solid #9E9E9E;
           padding: 1px 5px; border-radius: 3px;
           font-family: monospace; font-size: 12px; }
  code   { font-family: monospace; background: #F5F5F5;
           padding: 1px 4px; }
</style>
</head>
<body>

<h1>Руководство пользователя</h1>
<p>Программный модуль определения отклонений геометрии деталей от 3D-модели.</p>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>1. Быстрый старт</h2>
<ol>
  <li><b>Загрузите CAD-модель</b> — нажмите кнопку «Загрузить CAD-модель» или
      используйте меню <i>Файл → Загрузить CAD-модель…</i>.
      Поддерживаются форматы STL, OBJ.</li>
  <li><b>Загрузите облако точек</b> — нажмите «Загрузить облако точек».
      Поддерживаются форматы PLY, PCD, XYZ, PTS.</li>
  <li><b>Задайте допуск</b> — в поле «Допуск ±(мм)» укажите допустимое
      отклонение для вашей задачи (например, 0.5 мм).</li>
  <li><b>Запустите анализ</b> — нажмите кнопку «▶ Запустить анализ».
      Прогресс отображается в строке состояния.</li>
  <li><b>Просмотрите результаты</b> — числовые показатели появятся
      в панели «Результаты анализа» слева.</li>
  <li><b>Откройте 3D-вид</b> — нажмите кнопку «Показать 3D-вид»
      для визуализации карты отклонений.</li>
  <li><b>Сохраните отчёт</b> — нажмите «Сохранить отчёт PDF»
      для формирования PDF-документа.</li>
</ol>
<div class="tip">
  <b>Совет:</b> Файлы можно перетащить прямо в окно программы
  (Drag &amp; Drop). Программа определит тип по расширению автоматически.
</div>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>2. Поддерживаемые форматы</h2>
<table>
  <tr><th>Тип данных</th><th>Форматы</th><th>Примечание</th></tr>
  <tr>
    <td>CAD-модель</td><td><code>STL, OBJ</code></td>
    <td>Треугольная сетка. Рекомендуется водонепроницаемый (watertight) меш.</td>
  </tr>
  <tr>
    <td>Облако точек (скан)</td><td><code>PLY, PCD, XYZ, PTS</code></td>
    <td>Минимум 100 точек. Рекомендуется &gt; 10 000 точек.</td>
  </tr>
  <tr>
    <td>Проект</td><td><code>JSON</code></td>
    <td>Сохраняет пути к файлам, параметры и статистику.</td>
  </tr>
  <tr>
    <td>Отчёт</td><td><code>PDF</code></td>
    <td>Содержит статистику и параметры анализа.</td>
  </tr>
</table>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>3. Описание параметров</h2>

<p><b>Предобработка</b></p>
<table>
  <tr><th>Параметр</th><th>Описание</th><th>Рекомендуемые значения</th></tr>
  <tr>
    <td>Воксель (мм, 0=авто)</td>
    <td>Размер ячейки прореживания облака точек.
        0 — автоматический расчёт (1.5% от размера детали).</td>
    <td>0 (авто) для большинства задач</td>
  </tr>
  <tr>
    <td>SOR k (соседей)</td>
    <td>Число ближайших соседей для фильтрации шума.
        Больше — мягче фильтрация, медленнее.</td>
    <td>20–30 (стандарт), 40–50 (зашумлённый скан)</td>
  </tr>
  <tr>
    <td>SOR σ (строгость)</td>
    <td>Порог отсева шумовых точек в стандартных отклонениях.
        Меньше — строже, удаляет больше точек.</td>
    <td>2.0 (стандарт), 1.0–1.5 (сильный шум)</td>
  </tr>
</table>

<p><b>Регистрация</b></p>
<table>
  <tr><th>Параметр</th><th>Описание</th><th>Рекомендуемые значения</th></tr>
  <tr>
    <td>Попытки RANSAC</td>
    <td>Число независимых запусков глобальной регистрации.
        Больше — надёжнее, но дольше.</td>
    <td>3–5 (быстро), 7–10 (сложная геометрия)</td>
  </tr>
  <tr>
    <td>Грубый ICP (%)</td>
    <td>Порог первого прохода ICP в % от размера детали.
        Устраняет крупные ошибки RANSAC.</td>
    <td>3–5% (точная деталь), 6–10% (крупная)</td>
  </tr>
  <tr>
    <td>Точный ICP (%)</td>
    <td>Порог второго прохода ICP — финальная точность совмещения.</td>
    <td>0.5–1% (точная деталь), 1.5–3% (крупная)</td>
  </tr>
  <tr>
    <td>Итераций ICP</td>
    <td>Максимальное число итераций точного прохода ICP.</td>
    <td>100–150 (обычно достаточно)</td>
  </tr>
</table>

<p><b>Расчёт отклонений</b></p>
<table>
  <tr><th>Параметр</th><th>Описание</th><th>Рекомендуемые значения</th></tr>
  <tr>
    <td>Допуск ±(мм)</td>
    <td>Допустимое отклонение от CAD-модели.
        Точки в пределах ±допуска считаются соответствующими норме.</td>
    <td>Из технических условий на деталь</td>
  </tr>
  <tr>
    <td>Цветовая шкала</td>
    <td>Палитра раскраски карты отклонений.</td>
    <td>coolwarm или RdYlGn_r</td>
  </tr>
</table>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>4. Интерпретация результатов</h2>

<table>
  <tr><th>Метрика</th><th>Значение</th></tr>
  <tr>
    <td>RMSE совмещения</td>
    <td>Точность регистрации скана с CAD-моделью (мм).
        Хорошее значение: &lt; 0.1 мм. Если &gt; 1 мм — регистрация ненадёжна.</td>
  </tr>
  <tr>
    <td>Среднее отклонение</td>
    <td>Знаковое среднее. «+» — деталь в среднем больше эталона,
        «−» — меньше. Близкое к нулю — систематического смещения нет.</td>
  </tr>
  <tr>
    <td>Стд. отклонение</td>
    <td>Разброс отклонений. Малое значение — отклонения равномерны.</td>
  </tr>
  <tr>
    <td>Макс. |отклонение|</td>
    <td>Наибольшее отклонение по модулю — самая «плохая» точка детали.</td>
  </tr>
  <tr>
    <td>95-й перцентиль</td>
    <td>95% точек имеют отклонение меньше этого значения.
        Более надёжная характеристика, чем максимум.</td>
  </tr>
  <tr>
    <td>В допуске (%)</td>
    <td>Доля точек, отклонение которых не превышает заданный допуск.
        Значение ≥ 95% обычно считается соответствием норме.</td>
  </tr>
</table>

<p><b>Цвета на карте отклонений</b> (палитра coolwarm/RdYlGn_r):</p>
<ul>
  <li><b>Синий / Красный</b> — отклонение достигает −допуска / +допуска</li>
  <li><b>Белый / Жёлтый / Зелёный</b> — отклонение близко к нулю (норма)</li>
  <li>Точки за пределами шкалы окрашены в крайние цвета</li>
</ul>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>5. Управление 3D-видом (мышь)</h2>
<table>
  <tr><th>Действие</th><th>Эффект</th></tr>
  <tr>
    <td>ЛКМ + движение</td>
    <td>Вращение модели вокруг фокальной точки</td>
  </tr>
  <tr>
    <td>ПКМ + движение</td>
    <td>Перемещение (pan) — сдвигает сцену влево/вправо/вверх/вниз.
        Используйте, чтобы подвести интересующую область
        (например угол детали) в центр обзора.</td>
  </tr>
  <tr>
    <td>Колесо мыши</td>
    <td>Зум к центру обзора (к фокальной точке камеры).
        После pan фокальная точка оказывается там, куда вы сдвинули модель —
        поэтому колесо приближает именно то, что в центре экрана.</td>
  </tr>
  <tr>
    <td>Кнопка «↺ Сброс»</td>
    <td>Возврат камеры к виду «вся модель в кадре»</td>
  </tr>
</table>

<div class="tip">
  <b>Совет:</b> Чтобы рассмотреть дефект на углу детали:
  <ol>
    <li>Зажмите ПКМ и сдвиньте угол к центру обзора.</li>
    <li>Крутите колесо — приближение пойдёт к этому углу.</li>
    <li>ЛКМ-вращение тоже будет идти вокруг новой точки в центре.</li>
  </ol>
</div>

<h2>6. Горячие клавиши</h2>
<table>
  <tr><th>Клавиша</th><th>Действие</th></tr>
  <tr><td><kbd>Ctrl+O</kbd></td><td>Загрузить CAD-модель</td></tr>
  <tr><td><kbd>Ctrl+Shift+O</kbd></td><td>Загрузить облако точек</td></tr>
  <tr><td><kbd>Ctrl+S</kbd></td><td>Сохранить проект</td></tr>
  <tr><td><kbd>Ctrl+P</kbd></td><td>Открыть проект</td></tr>
  <tr><td><kbd>Ctrl+R</kbd></td><td>Сохранить отчёт PDF</td></tr>
  <tr><td><kbd>F1</kbd></td><td>Открыть руководство пользователя</td></tr>
  <tr><td><kbd>Ctrl+Q</kbd></td><td>Выход</td></tr>
</table>

<!-- ═══════════════════════════════════════════════════════════════ -->
<h2>7. Решение проблем</h2>

<div class="warn">
  <b>Программа долго работает (более 5 минут)</b><br/>
  Причина: слишком плотное облако точек или большое число итераций RANSAC.<br/>
  Решение: уменьшите число попыток RANSAC (1–3), увеличьте размер вокселя
  (например, 1–2 мм), или уменьшите плотность облака перед загрузкой.
</div>

<div class="err">
  <b>Большие отклонения при визуально похожем совмещении</b><br/>
  Причина: скан и модель загружены с разными единицами измерения
  (например, скан в мм, модель в метрах — разница в 1000 раз).<br/>
  Решение: до загрузки файлов выберите правильные единицы в группе
  <b>«Единицы измерения»</b> левой панели
  (мм / см / м / дюйм / как есть).
  Программа автоматически приведёт оба набора данных к мм.
</div>

<div class="err">
  <b>Регистрация не сходится (RMSE совмещения &gt; 1 мм)</b><br/>
  Причина 1: скан и модель — это разные детали или детали сильно отличаются.<br/>
  Причина 2: скан содержит только фрагмент детали (частичное перекрытие).<br/>
  Причина 3: деталь симметрична (цилиндр, сфера) — RANSAC может ошибиться.<br/>
  Решение: проверьте правильность файлов, увеличьте число попыток RANSAC
  и порог грубого ICP.
</div>

<div class="warn">
  <b>Предупреждение «Модель не является замкнутой (watertight)»</b><br/>
  Причина: CAD-файл содержит дыры или незамкнутые грани.<br/>
  Решение: анализ продолжится, но знаки отклонений (внутри/снаружи)
  могут быть неточными. Рекомендуется исправить меш в CAD-системе.
</div>

<div class="warn">
  <b>Программа завершилась с ошибкой при загрузке файла</b><br/>
  Причина: файл повреждён, неполный или в неподдерживаемом формате.<br/>
  Решение: откройте файл в другом ПО (MeshLab, CloudCompare) и
  переэкспортируйте в STL или PCD.
</div>

</body>
</html>
"""


class HelpDialog(QDialog):
    """Окно руководства пользователя с HTML-содержимым."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Руководство пользователя")
        self.resize(820, 620)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        browser = QTextBrowser()
        browser.setHtml(_HELP_HTML)
        browser.setOpenExternalLinks(False)
        browser.setReadOnly(True)
        layout.addWidget(browser)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Закрыть")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


class AboutDialog(QDialog):
    """Окно «О программе»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setFixedSize(420, 260)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(8)

        title = QLabel(
            "Программный модуль определения\n"
            "отклонений геометрии деталей от 3D-модели"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPointSize(11)
        title.setFont(font_title)
        layout.addWidget(title)

        sep_line = "─" * 48
        layout.addWidget(QLabel(sep_line))

        info_lines = [
            ("Версия:",       "1.0"),
            ("Автор:",        "Отряхина В.Л."),
            ("Организация:",  "РГАТУ им. П.А. Соловьёва"),
            ("Год:",          "2026"),
            ("Стек:",         "Python · Open3D · PyQt6 · ReportLab"),
        ]
        for label_text, value_text in info_lines:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(100)
            font_lbl = QFont()
            font_lbl.setBold(True)
            lbl.setFont(font_lbl)
            val = QLabel(value_text)
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val)
            layout.addLayout(row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("ОК")
        ok_btn.setFixedWidth(80)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)
