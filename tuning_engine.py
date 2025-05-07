"""
Основной модуль оптимизации настроек BIOS для максимальной производительности.
Реализует алгоритмы автоматического тюнинга параметров CPU.
"""
import os
import time
import json
import logging
import threading
import multiprocessing
from typing import Dict, List, Tuple, Any, Optional, Callable
from datetime import datetime

from cpu_profile import CPUProfile, StressTestResult
from hardware_monitor import HardwareMonitorService
from bios_service import BiosService

logger = logging.getLogger("cpu_tuner")

class TuningEngine:
    """
    Основной класс оптимизации настроек BIOS.
    Реализует алгоритмы автоматического тюнинга параметров CPU.
    """
    
    def __init__(self, monitor: HardwareMonitorService, bios: BiosService, 
                checkpoint_dir: str = "checkpoints"):
        """
        Инициализация движка тюнинга.
        
        Args:
            monitor: Сервис мониторинга железа
            bios: Сервис работы с BIOS
            checkpoint_dir: Директория для сохранения точек восстановления
        """
        self.monitor = monitor
        self.bios = bios
        self.checkpoint_dir = checkpoint_dir
        self.log_callback: Optional[Callable[[str], None]] = None
        
        # Создаем директорию для чекпоинтов, если она не существует
        os.makedirs(checkpoint_dir, exist_ok=True)
        
        # Флаги и состояния
        self.is_running = False
        self.abort_requested = False
        self.current_stage = ""
        
        # Константы для тюнинга
        self.thermal_limit = 90.0  # Предельная температура в градусах Цельсия
        self.perf_improvement_threshold = 1.01  # Минимальное улучшение производительности (1%)
        self.acceptable_perf_loss = 0.98  # Допустимая потеря производительности (2%)
        
        # Настройки стресс-теста
        self.short_test_duration = 60  # Длительность короткого теста (сек)
        self.medium_test_duration = 120  # Длительность среднего теста (сек)
        self.final_test_duration = 180  # Длительность финального теста (сек)
        
        logger.info("TuningEngine инициализирован")
    
    def log(self, message: str) -> None:
        """Логирует сообщение через callback и в файл логов"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def abort(self) -> None:
        """Прерывает текущий процесс тюнинга"""
        self.abort_requested = True
        self.log("Получен запрос на прерывание тюнинга. Остановка после текущего теста...")
    
    def save_checkpoint(self, profile: CPUProfile, stage: str, detail: str = "") -> str:
        """
        Сохраняет точку восстановления.
        
        Args:
            profile: Текущий профиль CPU
            stage: Текущий этап тюнинга
            detail: Дополнительная информация о состоянии
            
        Returns:
            Имя файла точки восстановления
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"checkpoint_{stage}_{timestamp}.json"
        filepath = os.path.join(self.checkpoint_dir, filename)
        
        checkpoint = {
            "timestamp": timestamp,
            "stage": stage,
            "detail": detail,
            "profile": json.loads(profile.to_json())
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, indent=2)
            
        logger.info(f"Сохранена точка восстановления: {filename}")
        return filename
    
    def load_checkpoint(self, filename: str) -> Tuple[CPUProfile, str, str]:
        """
        Загружает точку восстановления.
        
        Args:
            filename: Имя файла точки восстановления
            
        Returns:
            Кортеж (профиль CPU, этап тюнинга, детали)
        """
        filepath = os.path.join(self.checkpoint_dir, filename)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            checkpoint = json.load(f)
        
        profile = CPUProfile.from_json(json.dumps(checkpoint["profile"]))
        stage = checkpoint.get("stage", "")
        detail = checkpoint.get("detail", "")
        
        logger.info(f"Загружена точка восстановления: {filename}")
        return (profile, stage, detail)
    
    def execute_tuning(self, recovery_checkpoint: str = None) -> CPUProfile:
        """
        Запускает полный процесс тюнинга.
        
        Args:
            recovery_checkpoint: Точка восстановления после сбоя (опционально)
            
        Returns:
            Оптимизированный профиль CPU
        """
        if self.is_running:
            raise RuntimeError("Процесс тюнинга уже запущен")
        
        self.is_running = True
        self.abort_requested = False
        start_time = time.time()
        
        try:
            # 1. Инициализация и базовый замер
            self.log("=== Запуск процесса тюнинга CPU ===")
            
            # Загрузка из чекпоинта или инициализация нового профиля
            if recovery_checkpoint:
                self.log(f"Восстановление из точки: {recovery_checkpoint}")
                profile, stage, detail = self.load_checkpoint(recovery_checkpoint)
                self.log(f"Восстановлено состояние: этап '{stage}', детали: '{detail}'")
                
                # Применяем сохраненные настройки профиля
                self._apply_saved_profile_settings(profile)
            else:
                # Создаем новый профиль
                profile = self._initialize_cpu_profile()
                stage = "initialization"
            
            # Если это новый профиль или у нас нет базовых результатов, выполняем базовый тест
            if not profile.baseline_results:
                self.log("Выполнение базового замера производительности...")
                self.current_stage = "baseline"
                
                baseline_result = self._run_stress_test(self.medium_test_duration)
                profile.baseline_results = baseline_result
                profile.best_results = baseline_result
                
                self.log(f"Базовый результат: {baseline_result.operations_per_second:.0f} оп/сек при "
                       f"максимальной температуре {baseline_result.max_temperature:.1f}°C")
                
                # Сохраняем чекпоинт после базового измерения
                self.save_checkpoint(profile, "baseline", "Выполнен базовый замер")
            
            # Проверяем запрос на прерывание
            if self.abort_requested:
                self.log("Тюнинг прерван после базового замера")
                return profile
            
            # 2. Анализ доступных параметров BIOS
            if stage in ["initialization", "baseline"]:
                profile = self._analyze_bios_parameters(profile)
                stage = "analysis"
                self.save_checkpoint(profile, stage, "Проанализированы параметры BIOS")
            
            # Проверяем запрос на прерывание
            if self.abort_requested:
                self.log("Тюнинг прерван после анализа BIOS")
                return profile
            
            # 3. Андервольтинг - снижение напряжения CPU
            if stage in ["analysis", "power_limits", "undervolt_start"]:
                if stage != "undervolt_start" or detail == "":
                    stage = "undervolt"
                    profile = self._perform_undervolting(profile)
                    self.save_checkpoint(profile, stage, "Выполнен андервольтинг")
            
            # Проверяем запрос на прерывание
            if self.abort_requested:
                self.log("Тюнинг прерван после андервольтинга")
                return profile
            
            # 4. Оптимизация лимитов мощности
            if stage in ["analysis", "undervolt", "power_limits_start"]:
                if stage != "power_limits_start" or detail == "":
                    stage = "power_limits"
                    profile = self._optimize_power_limits(profile)
                    self.save_checkpoint(profile, stage, "Оптимизированы лимиты мощности")
            
            # Проверяем запрос на прерывание
            if self.abort_requested:
                self.log("Тюнинг прерван после оптимизации лимитов мощности")
                return profile
            
            # 5. Настройка C-States
            if stage in ["undervolt", "power_limits", "cstates_start"]:
                if stage != "cstates_start" or detail == "":
                    stage = "cstates"
                    profile = self._optimize_cstates(profile)
                    self.save_checkpoint(profile, stage, "Оптимизированы C-States")
            
            # Проверяем запрос на прерывание
            if self.abort_requested:
                self.log("Тюнинг прерван после настройки C-States")
                return profile
            
            # 6. Проверка XMP/DOCP профилей памяти
            if stage in ["power_limits", "cstates", "memory_start"]:
                if stage != "memory_start" or detail == "":
                    stage = "memory"
                    profile = self._check_memory_profiles(profile)
                    self.save_checkpoint(profile, stage, "Проверены профили памяти")
            
            # 7. Финализация - применение лучших найденных настроек
            self.log("=== Финализация оптимизированного профиля ===")
            self.current_stage = "finalization"
            
            # Запускаем финальный тест для подтверждения стабильности
            if not self.abort_requested:
                self.log("Запуск финального стресс-теста для проверки стабильности...")
                try:
                    final_result = self._run_stress_test(self.final_test_duration)
                    
                    # Обновляем результаты в профиле
                    if final_result.completed:
                        self.log(f"Финальный тест успешен: {final_result.operations_per_second:.0f} оп/сек, "
                                f"макс. температура {final_result.max_temperature:.1f}°C")
                        
                        # Если финальный результат лучше текущего лучшего, обновляем его
                        if profile.best_results is None or final_result.operations_per_second > profile.best_results.operations_per_second:
                            profile.best_results = final_result
                    else:
                        self.log("⚠️ Финальный тест не был завершен. Профиль может быть нестабильным.")
                        profile.is_stable = False
                except Exception as e:
                    self.log(f"❌ Ошибка при проведении финального теста: {e}")
                    profile.is_stable = False
            
            # Применяем лучшие настройки, если они есть
            self._apply_best_settings(profile)
            
            # Сохраняем финальный профиль
            profile_path = "best_profile.json"
            profile.save_to_file(profile_path)
            
            # Генерируем отчет
            report = profile.generate_report()
            self.log("\n=== Отчет о тюнинге ===\n" + report)
            
            # Сводка результатов
            elapsed_time = time.time() - start_time
            self.log(f"Тюнинг завершен за {elapsed_time:.1f} секунд")
            if profile.baseline_results and profile.best_results:
                perf_gain = ((profile.best_results.operations_per_second / profile.baseline_results.operations_per_second) - 1) * 100
                self.log(f"Прирост производительности: {perf_gain:.2f}%")
                self.log(f"Температура снизилась на: {profile.baseline_results.max_temperature - profile.best_results.max_temperature:.1f}°C")
            
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка в процессе тюнинга: {e}", exc_info=True)
            self.log(f"❌ Ошибка в процессе тюнинга: {str(e)}")
            
            # В случае ошибки возвращаем последний сохраненный профиль или пустой
            if 'profile' in locals():
                return profile
            else:
                return CPUProfile()
        finally:
            self.is_running = False
            self.current_stage = ""
    
    def _initialize_cpu_profile(self) -> CPUProfile:
        """
        Инициализирует новый профиль CPU с текущими настройками.
        
        Returns:
            Новый профиль CPU
        """
        profile = CPUProfile()
        
        # Получаем информацию о CPU
        self.log("Получение информации о CPU...")
        system_info = self.monitor.collect_system_info()
        profile.cpu_model = system_info.get('cpu', {}).get('brand_raw', 'Unknown CPU')
        
        # Читаем базовые настройки BIOS
        self.log("Чтение текущих настроек BIOS...")
        
        try:
            # Пытаемся прочитать PL1/PL2
            pl1_names = ["Long Duration Power Limit", "Package Power Limit 1", "PPT"]
            pl2_names = ["Short Duration Power Limit", "Package Power Limit 2", "PPT Limit"]
            
            pl1_found = False
            pl2_found = False
            
            for name in pl1_names:
                try:
                    profile.power_limit1 = self.bios.get_setting_value(name)
                    profile.register_bios_parameter(
                        name, 
                        profile.power_limit1, 
                        category="cpu_power",
                        description="Длительный лимит мощности CPU"
                    )
                    pl1_found = True
                    self.log(f"Обнаружен PL1: {name} = {profile.power_limit1}W")
                    break
                except (KeyError, ValueError):
                    continue
            
            for name in pl2_names:
                try:
                    profile.power_limit2 = self.bios.get_setting_value(name)
                    profile.register_bios_parameter(
                        name, 
                        profile.power_limit2, 
                        category="cpu_power",
                        description="Краткосрочный турбо-лимит мощности CPU"
                    )
                    pl2_found = True
                    self.log(f"Обнаружен PL2: {name} = {profile.power_limit2}W")
                    break
                except (KeyError, ValueError):
                    continue
            
            # Если не нашли, установим значения по умолчанию
            if not pl1_found:
                # Оценка TDP по модели CPU (как упрощенный вариант)
                cpu_name = profile.cpu_model.lower()
                if 'i9' in cpu_name or 'ryzen 9' in cpu_name:
                    profile.power_limit1 = 125
                elif 'i7' in cpu_name or 'ryzen 7' in cpu_name:
                    profile.power_limit1 = 95
                elif 'i5' in cpu_name or 'ryzen 5' in cpu_name:
                    profile.power_limit1 = 65
                else:
                    profile.power_limit1 = 65
                self.log(f"PL1 не найден, используется оценка: {profile.power_limit1}W")
            
            if not pl2_found:
                # PL2 обычно выше PL1
                profile.power_limit2 = profile.power_limit1 * 1.25
                self.log(f"PL2 не найден, используется оценка: {profile.power_limit2}W")
            
            # Проверка параметра смещения напряжения
            voltage_names = ["Core Voltage Offset", "CPU Core Voltage Offset", "Vcore Offset"]
            voltage_found = False
            
            for name in voltage_names:
                try:
                    profile.voltage_offset = self.bios.get_setting_value(name)
                    profile.register_bios_parameter(
                        name, 
                        profile.voltage_offset, 
                        category="cpu_voltage",
                        description="Смещение напряжения ядра CPU"
                    )
                    voltage_found = True
                    self.log(f"Обнаружен Voltage Offset: {name} = {profile.voltage_offset}mV")
                    break
                except (KeyError, ValueError):
                    continue
            
            if not voltage_found:
                profile.voltage_offset = 0
                self.log("Параметры смещения напряжения не найдены")
            
        except Exception as e:
            logger.warning(f"Ошибка при чтении настроек BIOS: {e}")
            self.log(f"⚠️ Не удалось прочитать некоторые настройки BIOS: {str(e)}")
            
            # Используем безопасные значения по умолчанию
            if not hasattr(profile, 'power_limit1') or profile.power_limit1 == 0:
                profile.power_limit1 = 65
            if not hasattr(profile, 'power_limit2') or profile.power_limit2 == 0:
                profile.power_limit2 = 95
            if not hasattr(profile, 'voltage_offset'):
                profile.voltage_offset = 0
        
        self.log(f"Инициализирован профиль CPU: PL1={profile.power_limit1}W, "
                f"PL2={profile.power_limit2}W, Offset={profile.voltage_offset}mV")
        
        return profile
    
    def _analyze_bios_parameters(self, profile: CPUProfile) -> CPUProfile:
        """
        Анализирует доступные параметры BIOS и добавляет в профиль.
        
        Args:
            profile: Текущий профиль CPU
            
        Returns:
            Обновленный профиль CPU
        """
        self.log("Анализ доступных параметров BIOS...")
        self.current_stage = "analysis"
        
        try:
            # Находим все параметры по категориям
            performance_params = self.bios.find_all_performance_parameters()
            
            self.log("Обнаружены следующие категории параметров производительности:")
            for category, params in performance_params.items():
                if params:
                    self.log(f"- {category}: {len(params)} параметров")
                    
                    # Добавляем первые 3 параметра в лог для примера
                    if len(params) > 0:
                        sample = params[:min(3, len(params))]
                        self.log(f"  Примеры: {', '.join(sample)}")
                    
                    # Регистрируем параметры в профиле
                    for param in params:
                        try:
                            value = self.bios.get_setting_value(param)
                            profile.register_bios_parameter(
                                param, value, category=category
                            )
                        except Exception as e:
                            logger.debug(f"Не удалось получить значение для {param}: {e}")
            
            # Проверяем наличие критически важных параметров
            if not performance_params.get("power"):
                self.log("⚠️ Не найдены параметры лимитов мощности CPU")
            if not performance_params.get("voltage"):
                self.log("⚠️ Не найдены параметры напряжения CPU")
            
            # Проверка XMP/DOCP
            xmp_params = self.bios.find_xmp_parameters()
            if xmp_params:
                self.log(f"Обнаружены профили памяти XMP/DOCP: {len(xmp_params)}")
                for param in xmp_params:
                    try:
                        value = self.bios.get_setting_value(param)
                        profile.register_bios_parameter(
                            param, value, category="memory",
                            description="Профиль памяти XMP/DOCP"
                        )
                        if "profile" in param.lower() and value == 0:
                            self.log("ℹ️ XMP/DOCP в данный момент отключен")
                    except Exception as e:
                        logger.debug(f"Не удалось получить значение для {param}: {e}")
            
            # Проверка C-States
            cstate_params = self.bios.find_cstate_parameters()
            if cstate_params:
                self.log(f"Обнаружены параметры C-States: {len(cstate_params)}")
                for param in cstate_params:
                    try:
                        value = self.bios.get_setting_value(param)
                        profile.register_bios_parameter(
                            param, value, category="cpu_features",
                            description="Управление энергосберегающими состояниями CPU"
                        )
                    except Exception as e:
                        logger.debug(f"Не удалось получить значение для {param}: {e}")
            
            self.log(f"Анализ BIOS завершен. Всего найдено {len(profile.bios_parameters)} параметров")
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка при анализе параметров BIOS: {e}", exc_info=True)
            self.log(f"❌ Ошибка при анализе параметров BIOS: {str(e)}")
            return profile
    
    def _perform_undervolting(self, profile: CPUProfile) -> CPUProfile:
        """
        Выполняет андервольтинг CPU.
        
        Args:
            profile: Текущий профиль CPU
            
        Returns:
            Профиль с оптимальным напряжением
        """
        self.log("=== Начало андервольтинга CPU ===")
        self.current_stage = "undervolt"
        
        # Находим параметры напряжения
        voltage_params = self.bios.find_voltage_parameters()
        if not voltage_params:
            self.log("Параметры напряжения CPU не найдены, пропуск этапа андервольтинга")
            return profile
        
        # Выбираем наиболее вероятный параметр смещения напряжения
        offset_param = None
        for param in voltage_params:
            if "offset" in param.lower():
                offset_param = param
                break
        
        # Если параметр смещения не найден, используем первый из доступных
        if not offset_param and voltage_params:
            offset_param = voltage_params[0]
        
        if not offset_param:
            self.log("Не найден подходящий параметр для андервольтинга, этап пропущен")
            return profile
        
        self.log(f"Параметр для андервольтинга: {offset_param}")
        
        # Текущее значение и шаги андервольтинга
        try:
            current_offset = self.bios.get_setting_value(offset_param)
            self.log(f"Текущее значение смещения: {current_offset}mV")
            
            # Обычно отрицательные значения означают снижение напряжения
            # Шаги андервольтинга (mV)
            undervolt_steps = []
            
            # Если текущее смещение положительное или нулевое,
            # начинаем с небольшого отрицательного значения
            if current_offset >= 0:
                undervolt_steps = [-20, -40, -60, -80, -100]
            # Если уже есть отрицательное смещение, начинаем от него
            # и идем дальше с шагом 20mV
            else:
                step = -20
                start = ((current_offset // step) * step)  # Округление до ближайшего кратного шагу
                while start >= current_offset - 100:  # Не уходим дальше -100mV от текущего
                    if start < current_offset:  # Только значения ниже текущего
                        undervolt_steps.append(start)
                    start += step
            
            # Если получился пустой список шагов, используем стандартные
            if not undervolt_steps:
                undervolt_steps = [-20, -40, -60, -80, -100]
            
            # Сортируем по убыванию (от меньшего андервольта к большему)
            undervolt_steps.sort(reverse=True)
            
            self.log(f"Запланированные шаги андервольтинга: {undervolt_steps}")
            
            # Начальное тестирование для отправной точки
            self.log(f"Тест базовой производительности при текущем напряжении...")
            baseline_result = self._run_stress_test(self.short_test_duration)
            
            if not baseline_result.completed:
                self.log("⚠️ Базовый тест не завершился, проблемы со стабильностью системы")
                return profile
            
            self.log(f"Базовый результат: {baseline_result.operations_per_second:.0f} оп/сек при "
                    f"максимальной температуре {baseline_result.max_temperature:.1f}°C")
            
            # Добавляем в историю тестов
            profile.add_test_result(offset_param, current_offset, baseline_result)
            
            # Для отслеживания лучшего результата
            best_offset = current_offset
            best_perf = baseline_result.operations_per_second
            
            # Перебор значений андервольтинга
            for offset in undervolt_steps:
                # Проверка запроса на прерывание
                if self.abort_requested:
                    self.log("Андервольтинг прерван по запросу пользователя")
                    break
                
                self.log(f"[Undervolt] Тестирование смещения {offset} mV...")
                checkpoint_file = self.save_checkpoint(profile, "undervolt_start", f"Testing offset {offset}")
                
                try:
                    # Устанавливаем новое значение смещения
                    self.bios.set_setting_value(offset_param, offset)
                    profile.update_parameter(offset_param, offset)
                    
                    # Даем системе стабилизироваться
                    time.sleep(2)
                    
                    # Запускаем стресс-тест
                    result = self._run_stress_test(self.short_test_duration)
                    
                    # Добавляем результат в историю
                    profile.add_test_result(offset_param, offset, result)
                    
                    if not result.completed:
                        self.log(f"⚠️ Тест при смещении {offset}mV не завершился - нестабильность")
                        # Возвращаемся к предыдущему стабильному значению
                        self.bios.set_setting_value(offset_param, best_offset)
                        profile.update_parameter(offset_param, best_offset)
                        
                        # Обновляем сохраненное смещение в профиле
                        profile.voltage_offset = best_offset
                        
                        self.log(f"Возврат к стабильному смещению: {best_offset}mV")
                        break
                    
                    self.log(f"Результат: {result.operations_per_second:.0f} оп/сек, "
                           f"максимальная температура {result.max_temperature:.1f}°C")
                    
                    # Проверяем, не ухудшилась ли производительность существенно
                    perf_ratio = result.operations_per_second / best_perf
                    
                    if perf_ratio >= self.acceptable_perf_loss:
                        # Производительность в допустимых пределах
                        self.log(f"Андервольтинг {offset}mV успешен. "
                               f"Изменение производительности: {(perf_ratio-1)*100:.2f}%")
                        
                        # Если производительность лучше предыдущей, обновляем лучший результат
                        if result.operations_per_second > best_perf:
                            best_perf = result.operations_per_second
                            best_offset = offset
                            
                        # Обновляем значение в профиле
                        profile.voltage_offset = offset
                    else:
                        # Производительность упала слишком сильно
                        self.log(f"⚠️ Смещение {offset}mV вызвало существенное падение производительности "
                               f"({(perf_ratio-1)*100:.2f}%). Возврат к {best_offset}mV")
                        
                        # Возвращаемся к лучшему значению
                        self.bios.set_setting_value(offset_param, best_offset)
                        profile.update_parameter(offset_param, best_offset)
                        
                        # Обновляем профиль
                        profile.voltage_offset = best_offset
                        break
                    
                except Exception as e:
                    logger.error(f"Ошибка при тестировании смещения {offset}mV: {e}", exc_info=True)
                    self.log(f"❌ Ошибка при тестировании смещения {offset}mV: {str(e)}")
                    
                    # Возвращаемся к последнему стабильному значению
                    try:
                        self.bios.set_setting_value(offset_param, best_offset)
                        profile.update_parameter(offset_param, best_offset)
                        profile.voltage_offset = best_offset
                    except Exception as restore_error:
                        logger.error(f"Не удалось восстановить настройки: {restore_error}")
                    
                    break
            
            # Финальный результат андервольтинга
            self.log(f"=== Андервольтинг завершен ===")
            self.log(f"Лучшее значение смещения напряжения: {profile.voltage_offset}mV")
            
            # Сохраняем чекпоинт после андервольтинга
            self.save_checkpoint(profile, "undervolt", f"Completed with best offset {profile.voltage_offset}mV")
            
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка в процессе андервольтинга: {e}", exc_info=True)
            self.log(f"❌ Ошибка в процессе андервольтинга: {str(e)}")
            return profile
    
    def _optimize_power_limits(self, profile: CPUProfile) -> CPUProfile:
        """
        Оптимизирует лимиты мощности CPU.
        
        Args:
            profile: Текущий профиль CPU
            
        Returns:
            Профиль с оптимальными лимитами мощности
        """
        self.log("=== Начало оптимизации лимитов мощности CPU ===")
        self.current_stage = "power_limits"
        
        # Находим параметры лимитов мощности
        power_params = self.bios.find_power_limit_parameters()
        
        if not power_params:
            self.log("Параметры лимитов мощности не найдены, пропуск этапа")
            return profile
        
        # Определяем параметры PL1 и PL2
        pl1_param = None
        pl2_param = None
        
        # Поиск подходящих параметров для PL1 и PL2
        for param in power_params:
            param_lower = param.lower()
            if 'long' in param_lower or 'pl1' in param_lower or 'package power limit 1' in param_lower:
                pl1_param = param
            elif 'short' in param_lower or 'pl2' in param_lower or 'package power limit 2' in param_lower:
                pl2_param = param
            # Для AMD PPT может быть одновременно и PL1 и PL2
            elif 'ppt' in param_lower and not pl1_param:
                pl1_param = param
        
        if not pl1_param:
            # Если не нашли явно PL1, берем первый параметр из списка мощности
            if power_params:
                pl1_param = power_params[0]
                self.log(f"PL1 не найден явно, используем параметр: {pl1_param}")
            else:
                self.log("⚠️ Не найдены параметры лимитов мощности, пропуск этапа")
                return profile
        
        self.log(f"Параметр PL1: {pl1_param}")
        if pl2_param:
            self.log(f"Параметр PL2: {pl2_param}")
        else:
            self.log("Параметр PL2 не найден, будет использоваться только PL1")
        
        try:
            # Текущие значения
            current_pl1 = self.bios.get_setting_value(pl1_param)
            self.log(f"Текущее значение PL1: {current_pl1}W")
            
            current_pl2 = None
            if pl2_param:
                current_pl2 = self.bios.get_setting_value(pl2_param)
                self.log(f"Текущее значение PL2: {current_pl2}W")
            
            # Шаги увеличения мощности
            power_steps = []
            
            # Начинаем с текущего значения и увеличиваем с шагом 5W
            # Не идем выше +50% от исходного значения
            max_pl1 = int(current_pl1 * 1.5)
            step = 5
            
            for pl1 in range(current_pl1 + step, max_pl1 + 1, step):
                power_steps.append(pl1)
            
            self.log(f"Запланированные шаги увеличения PL1: {power_steps}")
            
            # Тест базовой производительности при текущих настройках
            self.log(f"Тест базовой производительности при текущих лимитах мощности...")
            baseline_result = self._run_stress_test(self.medium_test_duration)
            
            if not baseline_result.completed:
                self.log("⚠️ Базовый тест не завершился, возможны проблемы со стабильностью")
                return profile
            
            self.log(f"Базовый результат: {baseline_result.operations_per_second:.0f} оп/сек при "
                    f"максимальной температуре {baseline_result.max_temperature:.1f}°C")
            
            # Добавляем в историю тестов
            profile.add_test_result(pl1_param, current_pl1, baseline_result)
            
            # Лучшие значения
            best_pl1 = current_pl1
            best_perf = baseline_result.operations_per_second
            
            # Перебор значений лимитов мощности
            for pl1 in power_steps:
                # Проверка запроса на прерывание
                if self.abort_requested:
                    self.log("Оптимизация лимитов мощности прервана по запросу пользователя")
                    break
                
                self.log(f"[Power] Тестирование PL1 = {pl1}W...")
                checkpoint_file = self.save_checkpoint(profile, "power_limits_start", f"Testing PL1 {pl1}W")
                
                try:
                    # Устанавливаем новое значение PL1
                    self.bios.set_setting_value(pl1_param, pl1)
                    profile.update_parameter(pl1_param, pl1)
                    
                    # Если есть PL2, устанавливаем его не ниже PL1
                    if pl2_param and current_pl2:
                        pl2 = max(current_pl2, pl1)
                        self.bios.set_setting_value(pl2_param, pl2)
                        profile.update_parameter(pl2_param, pl2)
                        self.log(f"PL2 установлен на {pl2}W")
                    
                    # Даем системе стабилизироваться
                    time.sleep(2)
                    
                    # Запускаем стресс-тест
                    result = self._run_stress_test(self.medium_test_duration)
                    
                    # Добавляем результат в историю
                    profile.add_test_result(pl1_param, pl1, result)
                    
                    if not result.completed:
                        self.log(f"⚠️ Тест при PL1={pl1}W не завершился - возможна нестабильность")
                        # Возвращаемся к предыдущему стабильному значению
                        self.bios.set_setting_value(pl1_param, best_pl1)
                        profile.update_parameter(pl1_param, best_pl1)
                        
                        # Восстанавливаем PL2 если нужно
                        if pl2_param and current_pl2:
                            self.bios.set_setting_value(pl2_param, current_pl2)
                            profile.update_parameter(pl2_param, current_pl2)
                        
                        # Обновляем профиль
                        profile.power_limit1 = best_pl1
                        if pl2_param and current_pl2:
                            profile.power_limit2 = current_pl2
                        
                        self.log(f"Возврат к стабильным лимитам: PL1={best_pl1}W")
                        break
                    
                    self.log(f"Результат: {result.operations_per_second:.0f} оп/сек, "
                           f"максимальная температура {result.max_temperature:.1f}°C")
                    
                    # Проверяем температуру
                    if result.max_temperature > self.thermal_limit:
                        self.log(f"⚠️ Достигнут тепловой предел {result.max_temperature:.1f}°C > {self.thermal_limit}°C")
                        # Возвращаемся к предыдущему значению
                        self.bios.set_setting_value(pl1_param, best_pl1)
                        profile.update_parameter(pl1_param, best_pl1)
                        
                        # Восстанавливаем PL2 если нужно
                        if pl2_param and current_pl2:
                            self.bios.set_setting_value(pl2_param, max(current_pl2, best_pl1))
                            profile.update_parameter(pl2_param, max(current_pl2, best_pl1))
                        
                        # Обновляем профиль
                        profile.power_limit1 = best_pl1
                        if pl2_param and current_pl2:
                            profile.power_limit2 = max(current_pl2, best_pl1)
                        
                        self.log(f"Останавливаем увеличение мощности на PL1={best_pl1}W")
                        break
                    
                    # Проверяем прирост производительности
                    perf_ratio = result.operations_per_second / best_perf
                    
                    if perf_ratio >= self.perf_improvement_threshold:
                        # Есть значимый прирост производительности
                        self.log(f"Увеличение PL1 до {pl1}W успешно. "
                               f"Прирост производительности: +{(perf_ratio-1)*100:.2f}%")
                        
                        best_perf = result.operations_per_second
                        best_pl1 = pl1
                        
                        # Обновляем профиль
                        profile.power_limit1 = pl1
                        if pl2_param and current_pl2:
                            profile.power_limit2 = max(current_pl2, pl1)
                    else:
                        # Нет значимого прироста
                        self.log(f"Увеличение PL1 до {pl1}W не дало значимого прироста производительности "
                               f"({(perf_ratio-1)*100:.2f}% < {(self.perf_improvement_threshold-1)*100:.2f}%)")
                        
                        # Возвращаемся к лучшему значению
                        self.bios.set_setting_value(pl1_param, best_pl1)
                        profile.update_parameter(pl1_param, best_pl1)
                        
                        # Восстанавливаем PL2 если нужно
                        if pl2_param and current_pl2:
                            self.bios.set_setting_value(pl2_param, max(current_pl2, best_pl1))
                            profile.update_parameter(pl2_param, max(current_pl2, best_pl1))
                        
                        # Обновляем профиль
                        profile.power_limit1 = best_pl1
                        if pl2_param and current_pl2:
                            profile.power_limit2 = max(current_pl2, best_pl1)
                        
                        self.log("Останавливаем увеличение мощности, дальнейший прирост не значителен")
                        break
                    
                except Exception as e:
                    logger.error(f"Ошибка при тестировании PL1={pl1}W: {e}", exc_info=True)
                    self.log(f"❌ Ошибка при тестировании PL1={pl1}W: {str(e)}")
                    
                    # Возвращаемся к последнему стабильному значению
                    try:
                        self.bios.set_setting_value(pl1_param, best_pl1)
                        profile.update_parameter(pl1_param, best_pl1)
                        profile.power_limit1 = best_pl1
                        
                        if pl2_param and current_pl2:
                            self.bios.set_setting_value(pl2_param, max(current_pl2, best_pl1))
                            profile.update_parameter(pl2_param, max(current_pl2, best_pl1))
                            profile.power_limit2 = max(current_pl2, best_pl1)
                    except Exception as restore_error:
                        logger.error(f"Не удалось восстановить настройки: {restore_error}")
                    
                    break
            
            # Финальный результат оптимизации лимитов мощности
            self.log(f"=== Оптимизация лимитов мощности завершена ===")
            self.log(f"Лучшее значение PL1: {profile.power_limit1}W")
            if pl2_param and current_pl2:
                self.log(f"Лучшее значение PL2: {profile.power_limit2}W")
            
            # Сохраняем чекпоинт
            self.save_checkpoint(profile, "power_limits", f"Completed with best PL1={profile.power_limit1}W")
            
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка в процессе оптимизации лимитов мощности: {e}", exc_info=True)
            self.log(f"❌ Ошибка в процессе оптимизации лимитов мощности: {str(e)}")
            return profile
    
    def _optimize_cstates(self, profile: CPUProfile) -> CPUProfile:
        """
        Оптимизирует настройки C-States.
        
        Args:
            profile: Текущий профиль CPU
            
        Returns:
            Профиль с оптимальными настройками C-States
        """
        self.log("=== Начало оптимизации C-States ===")
        self.current_stage = "cstates"
        
        # Находим параметры C-States
        cstate_params = self.bios.find_cstate_parameters()
        
        if not cstate_params:
            self.log("Параметры C-States не найдены, пропуск этапа")
            return profile
        
        # Находим основной параметр управления C-States
        main_cstate_param = None
        
        # Приоритетный поиск главного параметра C-States
        priority_keywords = [
            'c state', 'c-state', 'c states', 'c-states', 'package c', 'cpu c state'
        ]
        
        for keyword in priority_keywords:
            for param in cstate_params:
                if keyword in param.lower():
                    main_cstate_param = param
                    break
            if main_cstate_param:
                break
        
        # Если не нашли по приоритетным ключевым словам, выбираем первый из списка
        if not main_cstate_param and cstate_params:
            main_cstate_param = cstate_params[0]
        
        if not main_cstate_param:
            self.log("Основной параметр C-States не найден, пропуск этапа")
            return profile
        
        self.log(f"Основной параметр C-States: {main_cstate_param}")
        
        try:
            # Проверяем текущее значение
            current_value = self.bios.get_setting_value(main_cstate_param)
            self.log(f"Текущее значение: {current_value}")
            
            # Определяем тип параметра
            param_type = self.bios.get_setting_type(main_cstate_param)
            self.log(f"Тип параметра: {param_type}")
            
            # Для максимальной производительности обычно нужно отключить C-States
            # Для булевых параметров это обычно 0 (Disabled)
            # Для других типов может быть специальное значение (Disabled, No Control и т.д.)
            
            # Сначала тестируем текущую производительность
            self.log("Тест производительности с текущими настройками C-States...")
            baseline_result = self._run_stress_test(self.short_test_duration)
            
            if not baseline_result.completed:
                self.log("⚠️ Базовый тест не завершился, проблемы со стабильностью")
                return profile
            
            self.log(f"Базовый результат: {baseline_result.operations_per_second:.0f} оп/сек при "
                    f"максимальной температуре {baseline_result.max_temperature:.1f}°C")
            
            # Добавляем в историю тестов
            profile.add_test_result(main_cstate_param, current_value, baseline_result)
            
            # Пробуем отключить C-States для максимальной производительности
            # Значение для отключения зависит от типа параметра
            disable_value = None
            
            if param_type == 'bool':
                disable_value = 0  # Обычно 0 = Disabled
            else:
                # Для других типов ищем по ключевым словам в имени параметра
                param_lower = main_cstate_param.lower()
                if 'enable' in param_lower or 'package c' in param_lower:
                    disable_value = 0  # Обычно 0 = Disabled
                elif 'limit' in param_lower or 'control' in param_lower:
                    # Для C-State Limit может быть несколько вариантов
                    # 0 = No C-States, 1 = C1, 2 = C3, 3 = C6 и т.д.
                    disable_value = 0  # Предполагаем, что 0 = No C-States
            
            if disable_value is None:
                self.log("Не удалось определить значение для отключения C-States, пропуск этапа")
                return profile
            
            # Если текущее значение уже равно отключающему, нет смысла тестировать
            if current_value == disable_value:
                self.log(f"C-States уже отключены (значение {disable_value}), пропуск тестирования")
                return profile
            
            # Тестируем с отключенными C-States
            self.log(f"[C-States] Тестирование с отключенными C-States (значение {disable_value})...")
            checkpoint_file = self.save_checkpoint(profile, "cstates_start", f"Testing disabled C-States")
            
            try:
                # Устанавливаем новое значение
                self.bios.set_setting_value(main_cstate_param, disable_value)
                profile.update_parameter(main_cstate_param, disable_value)
                
                # Даем системе стабилизироваться
                time.sleep(2)
                
                # Запускаем стресс-тест
                result = self._run_stress_test(self.short_test_duration)
                
                # Добавляем результат в историю
                profile.add_test_result(main_cstate_param, disable_value, result)
                
                if not result.completed:
                    self.log(f"⚠️ Тест с отключенными C-States не завершился - возвращаем исходное значение")
                    # Возвращаемся к исходному значению
                    self.bios.set_setting_value(main_cstate_param, current_value)
                    profile.update_parameter(main_cstate_param, current_value)
                    return profile
                
                self.log(f"Результат: {result.operations_per_second:.0f} оп/сек, "
                       f"максимальная температура {result.max_temperature:.1f}°C")
                
                # Сравниваем с базовым результатом
                perf_ratio = result.operations_per_second / baseline_result.operations_per_seconds
                
                if perf_ratio >= self.perf_improvement_threshold:
                    # Есть значимый прирост
                    self.log(f"Отключение C-States дало прирост производительности: "
                           f"+{(perf_ratio-1)*100:.2f}%. Сохраняем изменения.")
                    # Изменения уже применены, просто обновляем профиль
                    profile.bios_parameters[main_cstate_param].best_value = disable_value
                else:
                    # Нет значимого прироста или даже падение
                    self.log(f"Отключение C-States не дало значимого прироста производительности "
                           f"({(perf_ratio-1)*100:.2f}%). Возвращаем исходное значение.")
                    # Возвращаемся к исходному значению
                    self.bios.set_setting_value(main_cstate_param, current_value)
                    profile.update_parameter(main_cstate_param, current_value)
            
            except Exception as e:
                logger.error(f"Ошибка при тестировании отключения C-States: {e}", exc_info=True)
                self.log(f"❌ Ошибка при тестировании отключения C-States: {str(e)}")
                
                # Возвращаемся к исходному значению
                try:
                    self.bios.set_setting_value(main_cstate_param, current_value)
                    profile.update_parameter(main_cstate_param, current_value)
                except Exception as restore_error:
                    logger.error(f"Не удалось восстановить настройки: {restore_error}")
            
            # Финальный результат оптимизации C-States
            self.log("=== Оптимизация C-States завершена ===")
            
            # Сохраняем чекпоинт
            self.save_checkpoint(profile, "cstates", "Completed C-States optimization")
            
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка в процессе оптимизации C-States: {e}", exc_info=True)
            self.log(f"❌ Ошибка в процессе оптимизации C-States: {str(e)}")
            return profile
    
    def _check_memory_profiles(self, profile: CPUProfile) -> CPUProfile:
        """
        Проверяет и оптимизирует профили памяти (XMP/DOCP).
        
        Args:
            profile: Текущий профиль CPU
            
        Returns:
            Профиль с оптимальными настройками памяти
        """
        self.log("=== Проверка профилей памяти (XMP/DOCP) ===")
        self.current_stage = "memory"
        
        # Находим параметры XMP/DOCP
        xmp_params = self.bios.find_xmp_parameters()
        
        if not xmp_params:
            self.log("Профили памяти XMP/DOCP не найдены, пропуск этапа")
            return profile
        
        # Находим основной параметр выбора профиля
        xmp_profile_param = None
        
        for param in xmp_params:
            param_lower = param.lower()
            if 'profile' in param_lower and ('xmp' in param_lower or 'docp' in param_lower):
                xmp_profile_param = param
                break
        
        # Если не нашли явно параметр выбора профиля, используем первый из списка
        if not xmp_profile_param and xmp_params:
            xmp_profile_param = xmp_params[0]
        
        if not xmp_profile_param:
            self.log("Параметр выбора профиля памяти не найден, пропуск этапа")
            return profile
        
        self.log(f"Параметр профиля памяти: {xmp_profile_param}")
        
        try:
            # Проверяем текущее значение
            current_value = self.bios.get_setting_value(xmp_profile_param)
            self.log(f"Текущее значение: {current_value}")
            
            # Проверяем тип параметра
            param_type = self.bios.get_setting_type(xmp_profile_param)
            
            # Обычно XMP/DOCP включается установкой значения 1 или 2
            # 0 = Disabled, 1 = Profile 1, 2 = Profile 2
            
            # Если профиль уже включен, пропускаем этап
            if current_value > 0:
                self.log(f"Профиль памяти уже включен (значение {current_value}), пропуск этапа")
                
                # Профиль требует перезагрузку, указываем это в профиле
                profile.requires_reboot = True
                return profile
            
            # Подтверждаем, что хотим включить XMP/DOCP
            self.log(f"Профиль памяти XMP/DOCP в данный момент выключен. Включение профиля "
                   f"требует перезагрузку компьютера!")
            self.log(f"⚠️ После включения профиля XMP/DOCP необходимо будет перезагрузить компьютер "
                   f"и снова запустить тюнер для продолжения оптимизации.")
            
            # Устанавливаем профиль 1
            enable_value = 1  # Обычно 1 = Profile 1
            
            try:
                # Устанавливаем новое значение
                self.bios.set_setting_value(xmp_profile_param, enable_value)
                profile.update_parameter(xmp_profile_param, enable_value)
                
                self.log(f"✅ Профиль памяти XMP/DOCP включен (значение {enable_value}). "
                       f"Необходима перезагрузка для применения.")
                
                # Отмечаем, что требуется перезагрузка
                profile.requires_reboot = True
                
            except Exception as e:
                logger.error(f"Ошибка при включении профиля памяти: {e}", exc_info=True)
                self.log(f"❌ Ошибка при включении профиля памяти: {str(e)}")
            
            # Сохраняем чекпоинт
            self.save_checkpoint(profile, "memory", f"XMP/DOCP profile enabled, reboot required")
            
            return profile
            
        except Exception as e:
            logger.error(f"Ошибка в процессе проверки профилей памяти: {e}", exc_info=True)
            self.log(f"❌ Ошибка в процессе проверки профилей памяти: {str(e)}")
            return profile
    
    def _apply_saved_profile_settings(self, profile: CPUProfile) -> None:
        """
        Применяет сохраненные настройки профиля к BIOS.
        
        Args:
            profile: Профиль CPU с настройками для применения
        """
        self.log("Применение сохраненных настроек профиля...")
        
        # Получаем все измененные параметры
        modified_params = profile.get_modified_parameters()
        
        for param_name, value in modified_params.items():
            try:
                self.log(f"Восстановление параметра: {param_name} = {value}")
                self.bios.set_setting_value(param_name, value)
            except Exception as e:
                logger.error(f"Не удалось восстановить параметр {param_name}: {e}")
                self.log(f"⚠️ Не удалось восстановить параметр {param_name}: {str(e)}")
    
    def _apply_best_settings(self, profile: CPUProfile) -> None:
        """
        Применяет лучшие найденные настройки к BIOS.
        
        Args:
            profile: Профиль CPU с лучшими настройками
        """
        self.log("Применение лучших найденных настроек...")
        
        try:
            # Применяем настройки напряжения
            voltage_params = self.bios.find_voltage_parameters()
            if voltage_params and profile.voltage_offset != 0:
                for param in voltage_params:
                    if "offset" in param.lower():
                        self.log(f"Устанавливаем {param} = {profile.voltage_offset} mV")
                        self.bios.set_setting_value(param, profile.voltage_offset)
                        break
            
            # Применяем настройки лимитов мощности
            power_params = self.bios.find_power_limit_parameters()
            pl1_set = False
            pl2_set = False
            
            if power_params:
                for param in power_params:
                    param_lower = param.lower()
                    if ('long' in param_lower or 'pl1' in param_lower) and not pl1_set:
                        self.log(f"Устанавливаем {param} = {profile.power_limit1} W")
                        self.bios.set_setting_value(param, profile.power_limit1)
                        pl1_set = True
                    elif ('short' in param_lower or 'pl2' in param_lower) and not pl2_set:
                        self.log(f"Устанавливаем {param} = {profile.power_limit2} W")
                        self.bios.set_setting_value(param, profile.power_limit2)
                        pl2_set = True
            
            # Применяем остальные наилучшие параметры из профиля
            for name, param in profile.bios_parameters.items():
                if param.modified and param.best_value is not None:
                    # Пропускаем параметры, которые уже применили выше
                    if ('voltage' in param.category and 'offset' in name.lower()) or \
                       ('cpu_power' in param.category and ('pl1' in name.lower() or 'long' in name.lower())) or \
                       ('cpu_power' in param.category and ('pl2' in name.lower() or 'short' in name.lower())):
                        continue
                    
                    try:
                        self.log(f"Устанавливаем {name} = {param.best_value}")
                        self.bios.set_setting_value(name, param.best_value)
                    except Exception as e:
                        logger.error(f"Не удалось установить параметр {name}: {e}")
                        self.log(f"⚠️ Не удалось установить параметр {name}: {str(e)}")
            
            self.log("✅ Лучшие настройки успешно применены")
            
        except Exception as e:
            logger.error(f"Ошибка при применении лучших настроек: {e}", exc_info=True)
            self.log(f"❌ Ошибка при применении лучших настроек: {str(e)}")
    
    def _run_stress_test(self, duration_seconds: int = 60) -> StressTestResult:
        """
        Запускает стресс-тест CPU на указанное время.
        
        Args:
            duration_seconds: Длительность теста в секундах
            
        Returns:
            Результаты стресс-теста
        """
        self.log(f"Запуск стресс-теста на {duration_seconds} секунд...")
        
        # Количество процессов = количество ядер CPU
        num_workers = multiprocessing.cpu_count()
        
        # Событие для сигнала остановки
        stop_event = threading.Event()
        
        # Разделяемый счетчик операций (используем список как изменяемый контейнер)
        total_ops = [0]
        
        # Запускаем потоки нагрузки на все ядра CPU
        workers = []
        for _ in range(num_workers):
            thread = threading.Thread(
                target=self._stress_worker,
                args=(stop_event, total_ops)
            )
            thread.daemon = True
            thread.start()
            workers.append(thread)
        
        # Мониторинг во время стресс-теста
        max_temp = 0.0
        avg_temp = 0.0
        max_power = 0.0
        avg_power = 0.0
        temp_readings = []
        power_readings = []
        
        start_time = time.time()
        completed = True
        
        try:
            # Мониторинг каждую секунду
            for _ in range(duration_seconds):
                if self.abort_requested:
                    self.log("Стресс-тест прерван по запросу пользователя")
                    completed = False
                    break
                
                time.sleep(1.0)
                temp, power, load = self.monitor.read_cpu_data()
                
                max_temp = max(max_temp, temp)
                max_power = max(max_power, power)
                
                temp_readings.append(temp)
                power_readings.append(power)
                
                # Вывод прогресса каждые 10 секунд
                elapsed = time.time() - start_time
                if int(elapsed) % 10 == 0:
                    self.log(f"Прогресс: {int(elapsed)}/{duration_seconds} сек, "
                           f"температура: {temp:.1f}°C, нагрузка: {load:.0f}%")
            
            # Вычисляем средние значения
            if temp_readings:
                avg_temp = sum(temp_readings) / len(temp_readings)
            if power_readings:
                avg_power = sum(power_readings) / len(power_readings)
        except Exception as e:
            logger.error(f"Ошибка во время мониторинга стресс-теста: {e}", exc_info=True)
            self.log(f"⚠️ Ошибка во время мониторинга: {str(e)}")
            completed = False
        finally:
            # Останавливаем стресс-тест
            stop_event.set()
            
            # Ждем завершения всех потоков
            for thread in workers:
                thread.join(timeout=1.0)
        
        # Вычисляем результат
        elapsed = time.time() - start_time
        ops_per_sec = total_ops[0] / elapsed if elapsed > 0 else 0
        
        # Получаем информацию о частоте CPU
        cpu_freq = 0.0
        try:
            frequencies = self.monitor.get_cpu_frequencies()
            if frequencies:
                if "average" in frequencies:
                    cpu_freq = frequencies["average"]
                else:
                    # Среднее по всем ядрам
                    cpu_freq = sum(frequencies.values()) / len(frequencies)
        except Exception as e:
            logger.debug(f"Не удалось получить частоту CPU: {e}")
        
        # Создаем объект результатов
        result = StressTestResult(
            operations_per_second=ops_per_sec,
            max_temperature=max_temp,
            avg_temperature=avg_temp,
            max_power=max_power,
            avg_power=avg_power,
            test_duration=elapsed,
            cpu_frequency=cpu_freq,
            completed=completed
        )
        
        self.log(f"Стресс-тест завершен: {ops_per_sec:.0f} оп/сек, "
               f"макс. температура {max_temp:.1f}°C, "
               f"средняя частота CPU {cpu_freq:.0f} МГц")
        
        return result
    
    def _stress_worker(self, stop_event: threading.Event, total_ops: List[int]) -> None:
        """
        Функция-рабочий, выполняющая CPU-интенсивные вычисления.
        
        Args:
            stop_event: Событие для сигнала остановки
            total_ops: Список с одним элементом для отслеживания количества операций
        """
        ops = 0
        dummy = 0.0
        
        while not stop_event.is_set():
            # Выполняем вычисления с плавающей точкой
            for j in range(100_000):
                dummy += (j ** 0.5)
            ops += 100_000
        
        # Добавляем операции этого потока к общему счетчику
        with threading.Lock():
            total_ops[0] += ops