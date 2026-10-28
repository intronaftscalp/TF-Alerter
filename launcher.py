#!/usr/bin/env python3
"""
TF-Alerter Launcher - Безопасный запуск main.py
Защита от бесконечного цикла процессов
"""

import sys
import os
import runpy
from pathlib import Path


def get_script_dir():
    """Определяем директорию где находится этот скрипт/exe"""
    if getattr(sys, "frozen", False):
        # Запуск из PyInstaller exe
        return Path(sys.argv[0]).parent.resolve()
    else:
        # Запуск обычного скрипта
        return Path(__file__).parent.resolve()


def is_already_running():
    """Проверяем что TF-Alerter еще не запущен"""
    try:
        import psutil

        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                # Ищем другие TF-Alerter процессы
                if proc.pid != current_pid:
                    if proc.name() == "TF-Alerter.exe":
                        return True
                    # Также проверяем по main.py если это Python процесс
                    cmdline = proc.cmdline()
                    if cmdline and "main.py" in str(cmdline):
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        # psutil не установлен, пропускаем эту проверку
        pass
    return False


if __name__ == "__main__":
    try:
        script_dir = get_script_dir()
        main_script = script_dir / "main.py"

        # ЗАЩИТА 1: main.py должен существовать
        if not main_script.exists():
            print(f"ОШИБКА: main.py не найден в {script_dir}")
            print(f"Script dir: {script_dir}")
            print(f"Files in dir: {list(script_dir.glob('*.py'))[:5]}")
            sys.exit(1)

        # ЗАЩИТА 2: Проверка повторного запуска
        if is_already_running():
            print("TF-Alerter уже запущен. Второй экземпляр отменен.")
            sys.exit(0)

        # Подготовка окружения
        env = os.environ.copy()
        env["TFALER_HOME"] = str(script_dir)
        env["PYTHONPATH"] = str(script_dir)
        os.environ.update(env)

        # ЗАЩИТА 4: No infinite loop - используем абсолютный путь main.py
        main_script_str = str(main_script.resolve())
        if not main_script_str.lower().endswith("main.py"):
            print(f"ОШИБКА: Неверный путь скрипта: {main_script_str}")
            sys.exit(1)

        # ЗАЩИТА 5: Запускаем main.py в текущем процессе (без лишнего дочернего процесса)
        os.chdir(str(script_dir))
        runpy.run_path(main_script_str, run_name="__main__")
        sys.exit(0)

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА В LAUNCHER: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
