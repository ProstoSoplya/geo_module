"""
main.py — Точка входа в приложение.

Запуск:
    python main.py

Порядок инициализации:
    1. Настраиваем логирование (в файл + в консоль)
    2. Загружаем конфигурацию из config.json
    3. Создаём QApplication (обязательно до любых виджетов)
    4. Создаём MainWindow
    5. Запускаем цикл событий app.exec()
"""

import json
import logging
import logging.handlers
import sys
import os

from PyQt6.QtWidgets import QApplication, QMessageBox

_DARK_QSS = """
QMainWindow, QDialog {
    background-color: #2b2b2b;
    color: #ffffff;
}
QWidget {
    background-color: #2b2b2b;
    color: #c0c0c0;
    font-family: "Segoe UI", "Arial";
    font-size: 10pt;
}
QMenuBar {
    background-color: #323232;
    color: #ffffff;
    border-bottom: 1px solid #444;
}
QMenuBar::item:selected {
    background-color: #3c3c3c;
}
QMenu {
    background-color: #2e2e2e;
    color: #ffffff;
    border: 1px solid #555;
}
QMenu::item:selected {
    background-color: #c2185b;
    color: white;
}
QToolBar {
    background-color: #2e2e2e;
    border-bottom: 1px solid #444;
    spacing: 4px;
    padding: 3px;
}
QToolBar::separator {
    background-color: #555;
    width: 1px;
    margin: 3px 2px;
}
QPushButton {
    background-color: #3d3d3d;
    color: #ffffff;
    border: 1px solid #5a5a5a;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover {
    background-color: #4e4e4e;
    border-color: #888;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #282828;
}
QPushButton:disabled {
    background-color: #303030;
    color: #606060;
    border-color: #404040;
}
QPushButton:checked {
    background-color: #ad1457;
    color: white;
    border-color: #e91e63;
}
QGroupBox {
    border: 1px solid #525252;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 6px;
    color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #ffffff;
    font-weight: bold;
}
QSpinBox, QDoubleSpinBox {
    background-color: #383838;
    color: #ffffff;
    border: 1px solid #5a5a5a;
    border-radius: 3px;
    padding: 2px 4px;
    selection-background-color: #ad1457;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #e91e63;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #484848;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #585858;
}
QComboBox {
    background-color: #383838;
    color: #ffffff;
    border: 1px solid #5a5a5a;
    border-radius: 3px;
    padding: 2px 6px;
    selection-background-color: #ad1457;
}
QComboBox:focus {
    border-color: #e91e63;
}
QComboBox::drop-down {
    border: none;
    background: #484848;
    width: 18px;
}
QComboBox QAbstractItemView {
    background-color: #383838;
    color: #ffffff;
    selection-background-color: #ad1457;
    border: 1px solid #5a5a5a;
}
QCheckBox {
    color: #ffffff;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #666;
    background: #383838;
    border-radius: 2px;
}
QCheckBox::indicator:checked {
    background-color: #ad1457;
    border-color: #e91e63;
}
QTextEdit {
    background-color: #181818;
    color: #c0c0c0;
    border: 1px solid #484848;
    border-radius: 3px;
}
QScrollBar:vertical {
    background: #2b2b2b;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #585858;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #787878;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #2b2b2b;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #585858;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover {
    background: #787878;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QProgressBar {
    background-color: #383838;
    border: 1px solid #5a5a5a;
    border-radius: 4px;
    text-align: center;
    color: #ffffff;
    font-size: 9pt;
}
QProgressBar::chunk {
    background-color: #ad1457;
    border-radius: 3px;
}
QStatusBar {
    background-color: #252525;
    color: #c0c0c0;
    border-top: 1px solid #3a3a3a;
}
QStatusBar QLabel {
    color: #c0c0c0;
}
QSplitter::handle {
    background-color: #3a3a3a;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}
QLabel {
    color: #c0c0c0;
    background: transparent;
}
QFrame {
    color: #505050;
}
QScrollArea {
    background-color: #2b2b2b;
    border: none;
    color: #ffffff;
}
QScrollArea > QWidget > QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
}
QAbstractScrollArea {
    color: #ffffff;
}
QToolTip {
    background-color: #1e1e2e;
    color: #f0f0f0;
    border: 1px solid #555;
    padding: 4px;
    border-radius: 3px;
}
"""


def _resolve_log_path() -> str:
    """app.log в user_log_dir; fallback — текущая директория. Создаёт каталог."""
    log_dir = ""
    try:
        import platformdirs
        log_dir = platformdirs.user_log_dir("GeoDeviation", appauthor=False)
    except ImportError:
        log_dir = ""
    if not log_dir:
        log_dir = os.getcwd()
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = os.getcwd()
    return os.path.join(log_dir, "app.log")


def setup_logging():
    """
    Настраивает логирование.

    Два handler'а:
    - StreamHandler        — вывод в консоль (удобно при разработке)
    - RotatingFileHandler  — запись в app.log (5 МБ × 3 бэкапа) в user_log_dir,
      чтобы лог не рос неограниченно и не писался в системные каталоги.
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"

    log_path = _resolve_log_path()
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            file_handler,
        ]
    )
    logging.getLogger("main").info("Лог-файл: %s", log_path)


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Рекурсивное слияние двух словарей.
    Берёт base как основу и накладывает значения из override поверх.
    Если оба значения — словари, рекурсивно сливает их (не заменяет секцию целиком).
    Возвращает новый словарь; base и override не мутируются.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _validate_config_ranges(config: dict) -> None:
    """
    Валидирует диапазоны числовых полей config in-place. При нарушении —
    сбрасывает поле к дефолту и пишет warning в лог.
    Контракт диапазонов:
      analysis.tolerance_mm          > 0
      analysis.conformance_threshold ∈ [0, 100]
      preprocessing.sor_neighbors    >= 1
      preprocessing.voxel_size       >= 0 (отрицательные значения = sentinel «не использовать»? в коде -1 имеет смысл sentinel)
    Поэтому voxel_size валидируем мягче: разрешаем -1 как sentinel, иначе >= 0.
    """
    rules = [
        (["analysis", "tolerance_mm"],
         0.5, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0,
         "должно быть > 0"),
        (["analysis", "conformance_threshold"],
         95, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100,
         "должно быть в диапазоне [0, 100]"),
        (["preprocessing", "sor_neighbors"],
         20, lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
         "должно быть целым >= 1"),
        (["preprocessing", "voxel_size"],
         -1, lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and (v >= 0 or v == -1),
         "должно быть >= 0 (либо -1 как sentinel)"),
    ]
    for key_path, default, predicate, description in rules:
        section = config
        for k in key_path[:-1]:
            if not isinstance(section, dict) or k not in section:
                section = None
                break
            section = section[k]
        if not isinstance(section, dict):
            continue
        leaf = key_path[-1]
        if leaf not in section:
            continue
        value = section[leaf]
        if not predicate(value):
            logging.warning(
                f"config[{'.'.join(key_path)}]={value!r} вне допустимого диапазона "
                f"({description}) — сброшено к дефолту {default}"
            )
            section[leaf] = default


def load_config(path: str = "config.json") -> dict:
    """
    Загружает конфигурацию из JSON-файла.
    Если файл не найден — возвращает значения по умолчанию.
    Если файл есть, но содержит только часть ключей — недостающие
    восстанавливаются из дефолтов через глубокое слияние.
    """
    from core.defaults import BASIC_DEFAULTS

    defaults = {
        **BASIC_DEFAULTS,
        "analysis": {
            "tolerance_mm": 0.5,
            "conformance_threshold": 95,
            "worst_points_n": 10,
        },
        "ui": {
            "advanced_mode": False,
            "last_dir": ""
        },
        "units": {
            "cad":  "mm",
            "scan": "mm"
        }
    }

    if not os.path.exists(path):
        logging.warning(f"config.json не найден, используются параметры по умолчанию")
        _validate_config_ranges(defaults)
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        logging.info(f"Конфигурация загружена из {path}")
        merged = _deep_merge(defaults, config)
        _validate_config_ranges(merged)
        return merged
    except Exception as e:
        logging.error(f"Ошибка чтения config.json: {e}")
        _validate_config_ranges(defaults)
        return defaults


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("=" * 60)
    logger.info("Запуск приложения")

    config = load_config()

    # QApplication — ДОЛЖЕН создаваться до любых виджетов
    app = QApplication(sys.argv)
    app.setApplicationName("Модуль анализа отклонений геометрии")
    app.setOrganizationName("РГАТУ")

    # Стиль — Fusion как основа для тёмной темы
    app.setStyle("Fusion")
    app.setStyleSheet(_DARK_QSS)

    # Импортируем MainWindow ПОСЛЕ создания QApplication
    from ui.main_window import MainWindow

    try:
        window = MainWindow(config)
        window.show()
        logger.info("Главное окно открыто")
    except Exception as e:
        logger.exception("Критическая ошибка при запуске")
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Ошибка запуска")
        msg.setText(f"Не удалось запустить приложение:\n{e}")
        msg.exec()
        sys.exit(1)

    # Запускаем цикл событий PyQt6
    # app.exec() не возвращает управление, пока не закрыто главное окно
    exit_code = app.exec()
    logger.info(f"Приложение завершено с кодом {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
