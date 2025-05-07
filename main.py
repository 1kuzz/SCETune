"""
Главный модуль CPU Profile Tuner.
Проверяет права администратора, запускает GUI и обрабатывает восстановление после сбоев.
"""
import os
import sys
import tkinter as tk
import ctypes
import logging
import json
import traceback
from pathlib import Path
from datetime import datetime

from main_window import MainWindow
from cpu_profile import CPUProfile

# Настройка логирования
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"tuner_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("cpu_tuner")

# Файл для хранения состояния тюнинга
STATE_FILE = "tuning_state.json"
CHECKPOINT_DIR = "checkpoints"
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

def is_admin():
    """Проверка наличия прав администратора"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def run_as_admin():
    """Повторный запуск программы с повышенными правами"""
    try:
        if sys.argv[0].endswith('.py'):
            # Если запуск из .py файла
            script = sys.argv[0]
            params = ' '.join(sys.argv[1:])
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}" {params}', None, 1
            )
        else:
            # Если запуск из .exe или другого исполняемого файла
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.argv[0], ' '.join(sys.argv[1:]), None, 1
            )
    except Exception as e:
        logger.error(f"Не удалось запустить с правами администратора: {e}")
        print(f"ОШИБКА: Не удалось запустить с правами администратора: {e}")

def check_for_crash_recovery():
    """
    Проверяет, не произошел ли сбой во время предыдущего запуска тюнинга.
    Возвращает имя точки восстановления, если найдена, иначе None.
    """
    if not os.path.exists(STATE_FILE):
        return None
    
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        if state.get('status') == 'in_progress':
            logger.info("Обнаружено незавершенное состояние тюнинга")
            checkpoint_file = state.get('last_checkpoint')
            if checkpoint_file and os.path.exists(os.path.join(CHECKPOINT_DIR, checkpoint_file)):
                return checkpoint_file
    except Exception as e:
        logger.error(f"Ошибка при проверке состояния восстановления: {e}")
    
    return None

def save_tuning_state(status, checkpoint=None):
    """
    Сохраняет текущее состояние тюнинга.
    
    Args:
        status: Статус тюнинга ('in_progress', 'completed', 'failed')
        checkpoint: Имя файла последней точки восстановления
    """
    state = {
        'status': status,
        'timestamp': datetime.now().isoformat(),
        'last_checkpoint': checkpoint
    }
    
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Ошибка при сохранении состояния тюнинга: {e}")

def main():
    """Основная функция запуска приложения"""
    logger.info("Запуск CPU Profile Tuner")
    
    # Проверка прав администратора
    if not is_admin():
        logger.warning("Программа запущена без прав администратора")
        print("Для изменения настроек BIOS требуются права администратора.")
        print("Запрашиваю повышение привилегий...")
        run_as_admin()
        return
    
    # Проверка на наличие прерванного тюнинга для восстановления
    recovery_checkpoint = check_for_crash_recovery()
    
    # Создание GUI
    root = tk.Tk()
    app = MainWindow(
        root, 
        recovery_checkpoint=recovery_checkpoint,
        state_callback=save_tuning_state,
        checkpoint_dir=CHECKPOINT_DIR
    )
    
    # Если нет точки восстановления, сбрасываем состояние
    if not recovery_checkpoint:
        save_tuning_state('idle')
    
    try:
        root.mainloop()
    except Exception as e:
        logger.error(f"Необработанное исключение в главном цикле: {e}")
        logger.error(traceback.format_exc())
        save_tuning_state('failed')
    finally:
        # Закрытие логгера
        logging.shutdown()

if __name__ == "__main__":
    main()