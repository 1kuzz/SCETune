"""
Графический интерфейс для CPU Profile Tuner.
Предоставляет минималистичный интерфейс для запуска и мониторинга процесса тюнинга.
"""
import os
import time
import logging
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
from typing import Optional, Callable, Dict, Any

from hardware_monitor import HardwareMonitorService
from bios_service import BiosService
from tuning_engine import TuningEngine
from cpu_profile import CPUProfile

logger = logging.getLogger("cpu_tuner")

class MainWindow:
    """
    Основной класс графического интерфейса для CPU Profile Tuner.
    """
    
    def __init__(self, root, recovery_checkpoint: str = None, 
                 state_callback: Optional[Callable] = None,
                 checkpoint_dir: str = "checkpoints"):
        """
        Инициализация графического интерфейса.
        
        Args:
            root: Корневое окно Tkinter
            recovery_checkpoint: Имя файла точки восстановления (опционально)
            state_callback: Функция обратного вызова для обновления состояния (опционально)
            checkpoint_dir: Директория для точек восстановления
        """
        self.root = root
        self.recovery_checkpoint = recovery_checkpoint
        self.state_callback = state_callback
        self.checkpoint_dir = checkpoint_dir
        
        # Настройка основного окна
        root.title("CPU Profile Tuner")
        root.geometry("800x600")
        root.minsize(640, 480)
        
        # Настройка стилей
        self._setup_styles()
        
        # Флаги состояния
        self.is_tuning_running = False
        self.is_services_initialized = False
        self.requires_reboot = False
        
        # Переменные Tkinter
        self.status_var = tk.StringVar(value="Готов к работе")
        self.progress_var = tk.DoubleVar(value=0.0)
        
        # Текущий профиль
        self.current_profile = None
        
        # Создаем виджеты
        self._create_widgets()
        
        # Инициализируем сервисы в отдельном потоке
        self.init_thread = threading.Thread(target=self._init_services)
        self.init_thread.daemon = True
        self.init_thread.start()
        
        # Устанавливаем обработчик закрытия окна
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Периодическое обновление статуса
        self._schedule_status_update()
    
    def _setup_styles(self):
        """Настройка стилей интерфейса"""
        style = ttk.Style()
        
        # Настройка стиля кнопок
        style.configure('TButton', font=('Segoe UI', 10))
        style.configure('Primary.TButton', font=('Segoe UI', 11, 'bold'))
        
        # Настройка стиля меток
        style.configure('TLabel', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Status.TLabel', font=('Segoe UI', 10, 'italic'))
    
    def _create_widgets(self):
        """Создание виджетов интерфейса"""
        # Главный фрейм с отступами
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Заголовок
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        title_label = ttk.Label(
            header_frame, 
            text="CPU Profile Tuner - Автоматическая оптимизация BIOS",
            style='Title.TLabel'
        )
        title_label.pack(side=tk.LEFT)
        
        # Фрейм с кнопками управления
        buttons_frame = ttk.Frame(main_frame)
        buttons_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_button = ttk.Button(
            buttons_frame,
            text="Запустить тюнинг",
            style='Primary.TButton',
            command=self._on_start_tuning,
            state=tk.DISABLED
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(
            buttons_frame,
            text="Остановить",
            command=self._on_stop_tuning,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.load_button = ttk.Button(
            buttons_frame,
            text="Загрузить профиль",
            command=self._on_load_profile,
            state=tk.DISABLED
        )
        self.load_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.save_button = ttk.Button(
            buttons_frame,
            text="Сохранить профиль",
            command=self._on_save_profile,
            state=tk.DISABLED
        )
        self.save_button.pack(side=tk.LEFT, padx=(0, 5))
        
        # Кнопки безопасности
        safety_frame = ttk.Frame(buttons_frame)
        safety_frame.pack(side=tk.RIGHT)
        
        self.restore_button = ttk.Button(
            safety_frame,
            text="Восстановить настройки",
            command=self._on_restore_defaults,
            state=tk.DISABLED
        )
        self.restore_button.pack(side=tk.RIGHT)
        
        # Фрейм статуса
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(0, 5))
        
        status_label = ttk.Label(status_frame, text="Статус:")
        status_label.pack(side=tk.LEFT)
        
        self.status_value_label = ttk.Label(
            status_frame, 
            textvariable=self.status_var,
            style='Status.TLabel'
        )
        self.status_value_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # Индикатор прогресса
        self.progress_bar = ttk.Progressbar(
            main_frame,
            variable=self.progress_var,
            mode='indeterminate'
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        # Notebook с вкладками
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Вкладка лога
        log_frame = ttk.Frame(self.notebook)
        self.notebook.add(log_frame, text='Лог')
        
        # Текстовое поле для лога
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            font=('Consolas', 10)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)
        
        # Вкладка результатов
        results_frame = ttk.Frame(self.notebook)
        self.notebook.add(results_frame, text='Результаты')
        
        # Текстовое поле для результатов
        self.results_text = scrolledtext.ScrolledText(
            results_frame,
            wrap=tk.WORD,
            font=('Consolas', 10)
        )
        self.results_text.pack(fill=tk.BOTH, expand=True)
        self.results_text.config(state=tk.DISABLED)
        
        # Вкладка системной информации
        sysinfo_frame = ttk.Frame(self.notebook)
        self.notebook.add(sysinfo_frame, text='Система')
        
        # Текстовое поле для системной информации
        self.sysinfo_text = scrolledtext.ScrolledText(
            sysinfo_frame,
            wrap=tk.WORD,
            font=('Consolas', 10)
        )
        self.sysinfo_text.pack(fill=tk.BOTH, expand=True)
        self.sysinfo_text.config(state=tk.DISABLED)
        
        # Предупреждение внизу
        warning_frame = ttk.Frame(main_frame)
        warning_frame.pack(fill=tk.X, pady=(10, 0))
        
        warning_label = ttk.Label(
            warning_frame,
            text="⚠️ Внимание: изменение настроек BIOS может привести к нестабильности системы. "
                "Используйте на свой страх и риск.",
            foreground='#d32f2f',
            font=('Segoe UI', 9)
        )
        warning_label.pack()
    
    def _init_services(self):
        """Инициализация сервисов в фоновом потоке"""
        try:
            self._update_status("Инициализация сервисов...")
            self._set_progress_indeterminate(True)
            
            # Инициализация сервиса мониторинга
            self.append_log("Инициализация сервиса мониторинга железа...")
            self.monitor = HardwareMonitorService()
            
            # Инициализация сервиса BIOS
            self.append_log("Инициализация сервиса BIOS...")
            scewin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SCEWIN_x64.exe")
            
            if not os.path.exists(scewin_path):
                self.append_log(f"⚠️ SCEWIN не найден по пути: {scewin_path}")
                # Пытаемся найти в текущей директории
                alt_path = "SCEWIN_x64.exe"
                if os.path.exists(alt_path):
                    scewin_path = alt_path
                    self.append_log(f"Найден SCEWIN в текущей директории")
                else:
                    # Предлагаем выбрать файл
                    self.root.after(0, self._ask_for_scewin_path)
                    return
            
            self.bios = BiosService(scewin_path)
            
            # Инициализация движка тюнинга
            self.append_log("Инициализация движка тюнинга...")
            self.tuner = TuningEngine(self.monitor, self.bios, checkpoint_dir=self.checkpoint_dir)
            self.tuner.log_callback = self.append_log
            
            # Получаем информацию о системе
            self.append_log("Получение информации о системе...")
            system_info = self.monitor.collect_system_info()
            self._update_system_info(system_info)
            
            # Все сервисы инициализированы
            self.is_services_initialized = True
            self._update_status("Готов к работе")
            self._set_progress_indeterminate(False)
            
            # Включаем кнопки
            self.root.after(0, self._enable_buttons)
            
            # Проверяем наличие точки восстановления
            if self.recovery_checkpoint:
                self.root.after(0, lambda: self._show_recovery_dialog(self.recovery_checkpoint))
            
        except Exception as e:
            logger.error(f"Ошибка при инициализации сервисов: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при инициализации сервисов: {str(e)}")
            self._update_status("Ошибка инициализации")
            self._set_progress_indeterminate(False)
            
            # Показываем диалог с ошибкой
            error_message = str(e)  # Сохраняем сообщение об ошибке в переменную
            self.root.after(0, lambda: messagebox.showerror(
                "Ошибка инициализации",
                f"Не удалось инициализировать сервисы:\n\n{error_message}\n\n"
                f"Проверьте наличие файла SCEWIN_x64.exe и права администратора."
            ))
    
    def _ask_for_scewin_path(self):
        """Запрашивает у пользователя путь к SCEWIN"""
        messagebox.showinfo(
            "SCEWIN не найден",
            "Для работы программы требуется утилита SCEWIN_x64.exe от AMI.\n\n"
            "Пожалуйста, укажите путь к файлу SCEWIN_x64.exe."
        )
        
        filepath = filedialog.askopenfilename(
            title="Выберите SCEWIN_x64.exe",
            filetypes=[("Исполняемые файлы", "*.exe"), ("Все файлы", "*.*")]
        )
        
        if filepath and os.path.exists(filepath):
            # Перезапускаем инициализацию с указанным путем
            self.append_log(f"Выбран SCEWIN: {filepath}")
            init_thread = threading.Thread(
                target=lambda: self._continue_init_with_scewin(filepath)
            )
            init_thread.daemon = True
            init_thread.start()
        else:
            self.append_log("❌ SCEWIN не выбран, невозможно продолжить")
            self._update_status("Ошибка инициализации")
            
            messagebox.showerror(
                "Ошибка инициализации",
                "SCEWIN не выбран. Программа не может работать без SCEWIN.\n\n"
                "Перезапустите программу и укажите путь к SCEWIN_x64.exe."
            )
    
    def _continue_init_with_scewin(self, scewin_path):
        """Продолжает инициализацию с указанным путем к SCEWIN"""
        try:
            self.bios = BiosService(scewin_path)
            self.tuner = TuningEngine(self.monitor, self.bios, checkpoint_dir=self.checkpoint_dir)
            self.tuner.log_callback = self.append_log
            
            # Получаем информацию о системе
            system_info = self.monitor.collect_system_info()
            self._update_system_info(system_info)
            
            # Все сервисы инициализированы
            self.is_services_initialized = True
            self._update_status("Готов к работе")
            self._set_progress_indeterminate(False)
            
            # Включаем кнопки
            self.root.after(0, self._enable_buttons)
            
            # Проверяем наличие точки восстановления
            if self.recovery_checkpoint:
                self.root.after(0, lambda: self._show_recovery_dialog(self.recovery_checkpoint))
                
        except Exception as e:
            logger.error(f"Ошибка при инициализации с указанным SCEWIN: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при инициализации с указанным SCEWIN: {str(e)}")
            self._update_status("Ошибка инициализации")
            
            error_message = str(e)  # Сохраняем сообщение об ошибке в переменную
            self.root.after(0, lambda: messagebox.showerror(
                "Ошибка инициализации",
                f"Не удалось инициализировать BIOS с указанным SCEWIN:\n\n{error_message}"
            ))
    
    def _show_recovery_dialog(self, checkpoint_file):
        """Показывает диалог восстановления после сбоя"""
        result = messagebox.askyesno(
            "Восстановление после сбоя",
            f"Обнаружена точка восстановления после предыдущего сбоя.\n\n"
            f"Хотите продолжить тюнинг с этой точки восстановления?"
        )
        
        if result:
            self._on_start_tuning(checkpoint_file)
    
    def _enable_buttons(self):
        """Включает кнопки интерфейса"""
        self.start_button.config(state=tk.NORMAL)
        self.load_button.config(state=tk.NORMAL)
        self.restore_button.config(state=tk.NORMAL)
    
    def _update_status(self, status):
        """Обновляет статус программы"""
        self.status_var.set(status)
    
    def _set_progress_indeterminate(self, indeterminate):
        """Управляет режимом индикатора прогресса"""
        if indeterminate:
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.start(15)
        else:
            self.progress_bar.stop()
            self.progress_bar.config(mode='determinate')
            self.progress_var.set(0)
    
    def _schedule_status_update(self):
        """Планирует периодическое обновление статуса"""
        # Обновляем информацию о системе каждые 10 секунд, если не идет тюнинг
        if not self.is_tuning_running and self.is_services_initialized:
            try:
                # Получаем текущие данные
                temp, power, load = self.monitor.read_cpu_data()
                
                # Обновляем статус
                status_text = f"Готов к работе | CPU: {load:.0f}% | Темп: {temp:.1f}°C | Мощность: {power:.1f}W"
                self._update_status(status_text)
                
            except Exception as e:
                logger.debug(f"Ошибка при обновлении статуса: {e}")
        
        # Перепланируем через 2 секунды
        self.root.after(2000, self._schedule_status_update)
    
    def append_log(self, message):
        """Добавляет сообщение в лог"""
        # Убедимся, что выполняется в UI потоке
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, lambda: self.append_log(message))
            return
        
        # Текущее время
        timestamp = time.strftime("%H:%M:%S")
        
        # Добавляем сообщение в лог
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)  # Прокрутка к концу
        self.log_text.config(state=tk.DISABLED)
    
    def _update_results(self, profile):
        """Обновляет вкладку результатов с данными из профиля"""
        if not profile:
            return
        
        # Генерируем отчет
        report = profile.generate_report()
        
        # Обновляем текстовое поле
        self.results_text.config(state=tk.NORMAL)
        self.results_text.delete(1.0, tk.END)
        self.results_text.insert(tk.END, report)
        self.results_text.config(state=tk.DISABLED)
    
    def _update_system_info(self, system_info):
        """Обновляет информацию о системе"""
        if not system_info:
            return
        
        # Форматируем информацию
        info_text = [
            "=== Информация о системе ===",
            f"Платформа: {system_info.get('platform', 'Неизвестно')}",
            f"Процессор: {system_info.get('cpu', {}).get('brand_raw', 'Неизвестно')}",
            f"Ядра/потоки: {system_info.get('cpu', {}).get('core_count', 0)}/{system_info.get('cpu', {}).get('thread_count', 0)}",
            f"Архитектура: {system_info.get('cpu', {}).get('arch', 'Неизвестно')}",
            "",
            "=== Оперативная память ===",
            f"Всего: {system_info.get('memory', {}).get('total_gb', 0):.1f} ГБ",
            f"Использовано: {system_info.get('memory', {}).get('used_gb', 0):.1f} ГБ ({system_info.get('memory', {}).get('percent', 0)}%)",
            "",
            "=== Текущее состояние ===",
            f"Температура CPU: {system_info.get('cpu_temperature', 0):.1f}°C",
            f"Мощность CPU: {system_info.get('cpu_power', 0):.1f}W",
            f"Загрузка CPU: {system_info.get('cpu_load', 0):.1f}%",
        ]
        
        # Добавляем частоты, если доступны
        if 'cpu_frequencies' in system_info and system_info['cpu_frequencies']:
            info_text.append("")
            info_text.append("=== Частоты CPU ===")
            
            for core, freq in system_info['cpu_frequencies'].items():
                info_text.append(f"{core}: {freq:.0f} МГц")
        
        # Обновляем текстовое поле
        self.sysinfo_text.config(state=tk.NORMAL)
        self.sysinfo_text.delete(1.0, tk.END)
        self.sysinfo_text.insert(tk.END, "\n".join(info_text))
        self.sysinfo_text.config(state=tk.DISABLED)
    
    def _on_start_tuning(self, recovery_checkpoint=None):
        """Обработчик нажатия кнопки 'Запустить тюнинг'"""
        if not self.is_services_initialized:
            messagebox.showerror(
                "Ошибка",
                "Сервисы не инициализированы. Невозможно запустить тюнинг."
            )
            return
        
        if self.is_tuning_running:
            messagebox.showinfo(
                "Тюнинг уже запущен",
                "Процесс тюнинга уже запущен."
            )
            return
        
        # Подтверждение
        confirm = messagebox.askyesno(
            "Подтверждение запуска тюнинга",
            "ВНИМАНИЕ: Тюнинг будет изменять настройки BIOS, что может привести "
            "к нестабильности системы.\n\n"
            "Убедитесь, что у вас нет открытых важных программ и сохранены все данные.\n\n"
            "Продолжить запуск тюнинга?"
        )
        
        if not confirm:
            return
        
        # Начинаем тюнинг
        self.is_tuning_running = True
        self._update_status("Запуск тюнинга...")
        self._set_progress_indeterminate(True)
        
        # Обновляем состояние кнопок
        self.start_button.config(state=tk.DISABLED)
        self.load_button.config(state=tk.DISABLED)
        self.save_button.config(state=tk.DISABLED)
        self.restore_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        # Обновляем статус через колбек
        if self.state_callback:
            self.state_callback('in_progress')
        
        # Запускаем процесс тюнинга в отдельном потоке
        tuning_thread = threading.Thread(
            target=self._run_tuning_process,
            args=(recovery_checkpoint,)
        )
        tuning_thread.daemon = True
        tuning_thread.start()
    
    def _run_tuning_process(self, recovery_checkpoint=None):
        """Запускает процесс тюнинга в отдельном потоке"""
        try:
            # Запускаем тюнинг
            self.append_log("Запуск процесса тюнинга...")
            
            # Выполняем тюнинг
            self.current_profile = self.tuner.execute_tuning(recovery_checkpoint)
            
            # Проверяем, не требуется ли перезагрузка
            if self.current_profile.requires_reboot:
                self.requires_reboot = True
                self.root.after(0, self._show_reboot_required_dialog)
            
            # Обновляем результаты
            self.root.after(0, lambda: self._update_results(self.current_profile))
            
            # Обновляем состояние
            self.root.after(0, self._on_tuning_completed)
            
        except Exception as e:
            logger.error(f"Ошибка в процессе тюнинга: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка в процессе тюнинга: {str(e)}")
            
            # Обновляем состояние
            error_message = str(e)  # Сохраняем сообщение об ошибке в переменную
            self.root.after(0, lambda: self._on_tuning_error(error_message))
    
    def _on_tuning_completed(self):
        """Вызывается при успешном завершении тюнинга"""
        self.is_tuning_running = False
        self._update_status("Тюнинг завершен")
        self._set_progress_indeterminate(False)
        
        # Обновляем состояние кнопок
        self.start_button.config(state=tk.NORMAL)
        self.load_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        # Если есть профиль, включаем кнопку сохранения
        if self.current_profile:
            self.save_button.config(state=tk.NORMAL)
        
        self.restore_button.config(state=tk.NORMAL)
        
        # Обновляем статус через колбек
        if self.state_callback:
            self.state_callback('completed')
        
        # Переключаемся на вкладку результатов
        self.notebook.select(1)  # Индекс вкладки результатов
        
        # Показываем сообщение о завершении
        messagebox.showinfo(
            "Тюнинг завершен",
            "Процесс тюнинга успешно завершен.\n\n"
            "Рекомендуется выполнить финальное тестирование системы "
            "для проверки стабильности.\n\n"
            "Не забудьте сохранить профиль для дальнейшего использования."
        )
    
    def _on_tuning_error(self, error_message):
        """Вызывается при ошибке в процессе тюнинга"""
        self.is_tuning_running = False
        self._update_status("Ошибка тюнинга")
        self._set_progress_indeterminate(False)
        
        # Обновляем состояние кнопок
        self.start_button.config(state=tk.NORMAL)
        self.load_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.restore_button.config(state=tk.NORMAL)
        
        # Обновляем статус через колбек
        if self.state_callback:
            self.state_callback('failed')
        
        # Показываем сообщение об ошибке
        messagebox.showerror(
            "Ошибка тюнинга",
            f"В процессе тюнинга произошла ошибка:\n\n{error_message}\n\n"
            f"Проверьте лог для получения дополнительной информации."
        )
    
    def _show_reboot_required_dialog(self):
        """Показывает диалог о необходимости перезагрузки"""
        result = messagebox.askyesno(
            "Требуется перезагрузка",
            "Для применения некоторых настроек (XMP/DOCP) требуется перезагрузка.\n\n"
            "Хотите перезагрузить компьютер сейчас?\n\n"
            "После перезагрузки запустите программу снова для продолжения тюнинга."
        )
        
        if result:
            # Сохраняем состояние перед перезагрузкой
            if self.state_callback:
                self.state_callback('reboot_pending')
            
            # Запускаем перезагрузку
            try:
                os.system("shutdown /r /t 5 /c \"Перезагрузка для применения настроек BIOS\"")
                messagebox.showinfo(
                    "Перезагрузка",
                    "Компьютер будет перезагружен через 5 секунд.\n\n"
                    "После перезагрузки запустите программу снова."
                )
            except Exception as e:
                logger.error(f"Ошибка при перезагрузке: {e}", exc_info=True)
                messagebox.showerror(
                    "Ошибка перезагрузки",
                    f"Не удалось выполнить перезагрузку: {str(e)}\n\n"
                    f"Перезагрузите компьютер вручную."
                )
    
    def _on_stop_tuning(self):
        """Обработчик нажатия кнопки 'Остановить'"""
        if not self.is_tuning_running:
            return
        
        confirm = messagebox.askyesno(
            "Подтверждение остановки",
            "Вы уверены, что хотите остановить процесс тюнинга?\n\n"
            "Текущее состояние будет сохранено, но тюнинг прервется."
        )
        
        if not confirm:
            return
        
        # Отправляем сигнал остановки тюнеру
        if hasattr(self, 'tuner') and self.tuner:
            self.append_log("Запрос на остановку тюнинга...")
            self.tuner.abort()
            
            # Обновляем статус
            self._update_status("Остановка тюнинга...")
    
    def _on_load_profile(self):
        """Обработчик нажатия кнопки 'Загрузить профиль'"""
        if not self.is_services_initialized:
            messagebox.showerror(
                "Ошибка",
                "Сервисы не инициализированы. Невозможно загрузить профиль."
            )
            return
        
        # Открываем диалог выбора файла
        filepath = filedialog.askopenfilename(
            title="Загрузить профиль CPU",
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")]
        )
        
        if not filepath:
            return  # Пользователь отменил выбор
        
        try:
            # Загружаем профиль
            self.append_log(f"Загрузка профиля из {filepath}...")
            profile = CPUProfile.load_from_file(filepath)
            
            # Спрашиваем о применении
            confirm = messagebox.askyesno(
                "Применить профиль",
                f"Загружен профиль: {profile.profile_name}\n"
                f"CPU: {profile.cpu_model}\n"
                f"Создан: {profile.creation_date}\n\n"
                f"Хотите применить настройки этого профиля?"
            )
            
            if not confirm:
                self.append_log("Загрузка профиля отменена пользователем")
                return
            
            # Применяем настройки профиля
            self._apply_profile_settings(profile)
            
            # Сохраняем текущий профиль
            self.current_profile = profile
            
            # Обновляем результаты
            self._update_results(profile)
            
            # Включаем кнопку сохранения
            self.save_button.config(state=tk.NORMAL)
            
            # Переключаемся на вкладку результатов
            self.notebook.select(1)  # Индекс вкладки результатов
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке профиля: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при загрузке профиля: {str(e)}")
            
            messagebox.showerror(
                "Ошибка загрузки профиля",
                f"Не удалось загрузить профиль: {str(e)}"
            )
    
    def _apply_profile_settings(self, profile):
        """Применяет настройки из загруженного профиля"""
        if not profile:
            return
        
        self.append_log(f"Применение настроек профиля {profile.profile_name}...")
        self._update_status("Применение профиля...")
        self._set_progress_indeterminate(True)
        
        try:
            # Получаем измененные параметры
            modified_params = profile.get_modified_parameters()
            
            if not modified_params:
                self.append_log("⚠️ В профиле нет измененных параметров")
                messagebox.showwarning(
                    "Предупреждение",
                    "В профиле нет измененных параметров BIOS."
                )
                return
            
            # Применяем настройки
            for param, value in modified_params.items():
                try:
                    self.append_log(f"Установка {param} = {value}")
                    self.bios.set_setting_value(param, value)
                except Exception as e:
                    logger.error(f"Ошибка при установке {param}: {e}", exc_info=True)
                    self.append_log(f"⚠️ Не удалось установить {param}: {str(e)}")
            
            self.append_log("✅ Профиль успешно применен")
            
            # Проверяем, требуется ли перезагрузка
            if profile.requires_reboot:
                self.requires_reboot = True
                self._show_reboot_required_dialog()
            else:
                messagebox.showinfo(
                    "Профиль применен",
                    "Настройки профиля успешно применены к BIOS."
                )
            
        except Exception as e:
            logger.error(f"Ошибка при применении профиля: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при применении профиля: {str(e)}")
            
            messagebox.showerror(
                "Ошибка применения профиля",
                f"Не удалось применить профиль: {str(e)}"
            )
        finally:
            self._update_status("Готов к работе")
            self._set_progress_indeterminate(False)
    
    def _on_save_profile(self):
        """Обработчик нажатия кнопки 'Сохранить профиль'"""
        if not self.current_profile:
            messagebox.showinfo(
                "Нет профиля",
                "Нет текущего профиля для сохранения.\n\n"
                "Сначала выполните тюнинг или загрузите профиль."
            )
            return
        
        # Открываем диалог сохранения файла
        filepath = filedialog.asksaveasfilename(
            title="Сохранить профиль CPU",
            defaultextension=".json",
            filetypes=[("JSON файлы", "*.json"), ("Все файлы", "*.*")],
            initialfile=f"{self.current_profile.profile_name}.json"
        )
        
        if not filepath:
            return  # Пользователь отменил сохранение
        
        try:
            # Сохраняем профиль
            self.current_profile.save_to_file(filepath)
            self.append_log(f"Профиль сохранен в {filepath}")
            
            messagebox.showinfo(
                "Профиль сохранен",
                f"Профиль успешно сохранен в файл:\n{filepath}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении профиля: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при сохранении профиля: {str(e)}")
            
            messagebox.showerror(
                "Ошибка сохранения профиля",
                f"Не удалось сохранить профиль: {str(e)}"
            )
    
    def _on_restore_defaults(self):
        """Обработчик нажатия кнопки 'Восстановить настройки'"""
        if not self.is_services_initialized:
            messagebox.showerror(
                "Ошибка",
                "Сервисы не инициализированы. Невозможно восстановить настройки."
            )
            return
        
        confirm = messagebox.askyesno(
            "Подтверждение восстановления",
            "Вы уверены, что хотите восстановить настройки BIOS до исходных значений?\n\n"
            "Все изменения, сделанные тюнером, будут сброшены."
        )
        
        if not confirm:
            return
        
        # Восстанавливаем настройки
        self.append_log("Восстановление исходных настроек BIOS...")
        self._update_status("Восстановление настроек...")
        self._set_progress_indeterminate(True)
        
        try:
            # Вызываем метод восстановления в BiosService
            result = self.bios.restore_defaults()
            
            if result:
                self.append_log("✅ Настройки BIOS успешно восстановлены")
                messagebox.showinfo(
                    "Настройки восстановлены",
                    "Исходные настройки BIOS успешно восстановлены."
                )
            else:
                self.append_log("⚠️ Не удалось восстановить настройки BIOS")
                messagebox.showwarning(
                    "Предупреждение",
                    "Не удалось восстановить исходные настройки BIOS.\n\n"
                    "Проверьте лог для получения дополнительной информации."
                )
            
        except Exception as e:
            logger.error(f"Ошибка при восстановлении настроек: {e}", exc_info=True)
            self.append_log(f"❌ Ошибка при восстановлении настроек: {str(e)}")
            
            messagebox.showerror(
                "Ошибка восстановления",
                f"Не удалось восстановить настройки: {str(e)}"
            )
        finally:
            self._update_status("Готов к работе")
            self._set_progress_indeterminate(False)
    
    def _on_close(self):
        """Обработчик закрытия окна"""
        # Если идет тюнинг, спрашиваем подтверждение
        if self.is_tuning_running:
            confirm = messagebox.askyesno(
                "Прервать тюнинг?",
                "В данный момент идет процесс тюнинга.\n\n"
                "Вы уверены, что хотите закрыть программу и прервать тюнинг?"
            )
            
            if not confirm:
                return
            
            # Останавливаем тюнинг
            if hasattr(self, 'tuner') and self.tuner:
                self.tuner.abort()
        
        # Закрываем сервисы
        if hasattr(self, 'monitor') and self.monitor:
            try:
                self.monitor.close()
            except:
                pass
        
        # Закрываем окно
        self.root.destroy()