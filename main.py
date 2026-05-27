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


def setup_logging():
    """
    Настраивает логирование.

    Два handler'а:
    - StreamHandler — вывод в консоль (удобно при разработке)
    - FileHandler   — запись в app.log (для диагностики)
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("app.log", encoding="utf-8")
        ]
    )


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


def load_config(path: str = "config.json") -> dict:
    """
    Загружает конфигурацию из JSON-файла.
    Если файл не найден — возвращает значения по умолчанию.
    Если файл есть, но содержит только часть ключей — недостающие
    восстанавливаются из дефолтов через глубокое слияние.
    """
    defaults = {
        "preprocessing": {
            "sor_neighbors": 20,
            "sor_std_ratio": 2.0,
            "voxel_size": 0
        },
        "registration": {
            # 200000 итераций — нижняя граница надёжной сходимости RANSAC;
            # 150 итераций ICP — достаточно для relative_fitness/rmse=1e-6.
            # Оба значения согласованы с логикой registration.py.
            "ransac_max_iter":  200000,
            "ransac_n_starts":  5,
            "ransac_top_k":     4,
            "icp_coarse_pct":   5.0,
            "icp_fine_pct":     1.0,
            "icp_max_iter":     150,
            "use_pca_seeds":    True,
            "reject_rmse_pct":  5.0,
            "alignment_mode":   "best_fit",
        },
        "analysis": {
            "tolerance_mm": 0.5,
            "conformance_threshold": 95,
            "worst_points_n": 10,
        },
        "ui": {
            "advanced_mode": False,
            "colormap": "RdYlGn_r",
            "last_dir": ""
        },
        "units": {
            "cad":  "mm",
            "scan": "mm"
        }
    }

    if not os.path.exists(path):
        logging.warning(f"config.json не найден, используются параметры по умолчанию")
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        logging.info(f"Конфигурация загружена из {path}")
        return _deep_merge(defaults, config)
    except Exception as e:
        logging.error(f"Ошибка чтения config.json: {e}")
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
