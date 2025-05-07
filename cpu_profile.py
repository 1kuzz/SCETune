"""
Модуль с классом CPUProfile - модель данных для CPU-профиля.
Содержит настройки BIOS и результаты тестирования.
"""
import json
import os
import logging
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from copy import deepcopy

logger = logging.getLogger("cpu_tuner")

@dataclass
class BiosParameter:
    """Класс, представляющий отдельный параметр BIOS"""
    name: str                   # Полное название параметра
    current_value: Any          # Текущее значение
    default_value: Any          # Значение по умолчанию
    modified: bool = False      # Было ли изменено значение
    tested_values: List[Any] = field(default_factory=list)  # Список протестированных значений
    best_value: Any = None      # Лучшее найденное значение
    category: str = ""          # Категория параметра (CPU, память, питание...)
    description: str = ""       # Описание параметра
    impact: float = 0.0         # Измеренное влияние на производительность (проценты)
    stability_impact: bool = False  # Влияет ли на стабильность
    
    def __post_init__(self):
        if self.best_value is None:
            self.best_value = self.current_value
    
    def as_dict(self):
        """Преобразует параметр в словарь для сериализации"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data):
        """Создает объект параметра из словаря"""
        return cls(**data)

@dataclass
class StressTestResult:
    """Результаты стресс-теста"""
    operations_per_second: float     # Количество операций в секунду
    max_temperature: float           # Максимальная температура во время теста (°C)
    avg_temperature: float           # Средняя температура во время теста (°C)
    max_power: float = 0.0           # Максимальное энергопотребление (Вт)
    avg_power: float = 0.0           # Среднее энергопотребление (Вт)
    test_duration: float = 0.0       # Длительность теста (сек)
    cpu_frequency: float = 0.0       # Средняя частота CPU (МГц)
    completed: bool = True           # Был ли тест завершен успешно
    
    def as_dict(self):
        """Преобразует результаты теста в словарь для сериализации"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data):
        """Создает объект результатов теста из словаря"""
        return cls(**data)

@dataclass
class CPUProfile:
    """
    Класс, представляющий профиль CPU.
    Содержит настройки CPU/BIOS и результаты их влияния на производительность.
    """
    # Базовые параметры CPU и результаты тестов
    power_limit1: int = 0                # Длительный лимит мощности (PL1/PPT) в ваттах
    power_limit2: int = 0                # Краткосрочный лимит мощности (PL2) в ваттах
    voltage_offset: int = 0              # Смещение напряжения ядра (мВ, отрицательное = андервольт)
    max_temperature: float = 0.0         # Максимальная температура при тесте (°C)
    measured_perf_score: float = 0.0     # Измеренная производительность (операций/сек)
    
    # Расширенные параметры профиля
    cpu_model: str = ""                  # Модель процессора
    creation_date: str = field(default_factory=lambda: datetime.now().isoformat())
    profile_name: str = "default_profile"
    description: str = ""
    
    # Подробные параметры BIOS
    bios_parameters: Dict[str, BiosParameter] = field(default_factory=dict)
    
    # История тестов
    test_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Флаги статуса профиля
    is_stable: bool = True
    requires_reboot: bool = False
    
    # Расширенные результаты тестирования
    baseline_results: Optional[StressTestResult] = None
    best_results: Optional[StressTestResult] = None
    
    def add_test_result(self, parameter_name: str, parameter_value: Any, test_result: StressTestResult):
        """
        Добавляет результат теста в историю.
        
        Args:
            parameter_name: Название измененного параметра
            parameter_value: Новое значение параметра
            test_result: Результаты стресс-теста
        """
        test_entry = {
            "timestamp": datetime.now().isoformat(),
            "parameter": parameter_name,
            "value": parameter_value,
            "result": test_result.as_dict(),
            "perf_diff_percent": self._calculate_perf_diff(test_result.operations_per_second)
        }
        self.test_history.append(test_entry)
        
        # Если это параметр BIOS, обновляем его данные
        if parameter_name in self.bios_parameters:
            param = self.bios_parameters[parameter_name]
            param.tested_values.append(parameter_value)
            
            # Если результат лучше предыдущего лучшего результата
            if (test_result.completed and 
                (self.best_results is None or 
                 test_result.operations_per_second > self.best_results.operations_per_second * 1.01)):
                param.best_value = parameter_value
                self.best_results = test_result
                logger.info(f"Новое лучшее значение для {parameter_name}: {parameter_value}")
    
    def _calculate_perf_diff(self, new_perf: float) -> float:
        """
        Вычисляет процентную разницу в производительности относительно базового уровня.
        
        Args:
            new_perf: Новый показатель производительности
            
        Returns:
            Процентное изменение производительности
        """
        if self.baseline_results and self.baseline_results.operations_per_second > 0:
            return ((new_perf - self.baseline_results.operations_per_second) / 
                   self.baseline_results.operations_per_second) * 100
        return 0.0
    
    def register_bios_parameter(self, name: str, current_value: Any, 
                                default_value: Any = None, category: str = "", 
                                description: str = ""):
        """
        Регистрирует параметр BIOS в профиле.
        
        Args:
            name: Название параметра
            current_value: Текущее значение
            default_value: Значение по умолчанию (если отличается от текущего)
            category: Категория параметра (CPU, память, питание...)
            description: Описание параметра
        """
        if default_value is None:
            default_value = current_value
            
        if name not in self.bios_parameters:
            self.bios_parameters[name] = BiosParameter(
                name=name,
                current_value=current_value,
                default_value=default_value,
                category=category,
                description=description
            )
            logger.debug(f"Зарегистрирован параметр BIOS: {name} = {current_value}")
        else:
            # Обновляем существующий параметр
            self.bios_parameters[name].current_value = current_value
            if default_value != current_value:
                self.bios_parameters[name].default_value = default_value
    
    def update_parameter(self, name: str, new_value: Any, mark_as_modified: bool = True):
        """
        Обновляет значение параметра BIOS.
        
        Args:
            name: Название параметра
            new_value: Новое значение
            mark_as_modified: Пометить параметр как измененный
        """
        if name in self.bios_parameters:
            old_value = self.bios_parameters[name].current_value
            self.bios_parameters[name].current_value = new_value
            if mark_as_modified:
                self.bios_parameters[name].modified = True
            logger.info(f"Обновлен параметр BIOS: {name} = {new_value} (было: {old_value})")
        else:
            logger.warning(f"Попытка обновить несуществующий параметр: {name}")
    
    def get_modified_parameters(self) -> Dict[str, Any]:
        """
        Возвращает словарь измененных параметров.
        
        Returns:
            Словарь {имя_параметра: текущее_значение} для всех измененных параметров
        """
        return {name: param.current_value 
                for name, param in self.bios_parameters.items() 
                if param.modified}
    
    def clone(self):
        """
        Создает копию профиля для экспериментов.
        
        Returns:
            Новый экземпляр CPUProfile с копированием всех данных
        """
        return deepcopy(self)
    
    def to_json(self):
        """
        Преобразует профиль в JSON-строку.
        
        Returns:
            JSON-строка с данными профиля
        """
        data = {
            "power_limit1": self.power_limit1,
            "power_limit2": self.power_limit2,
            "voltage_offset": self.voltage_offset,
            "max_temperature": self.max_temperature,
            "measured_perf_score": self.measured_perf_score,
            "cpu_model": self.cpu_model,
            "creation_date": self.creation_date,
            "profile_name": self.profile_name,
            "description": self.description,
            "is_stable": self.is_stable,
            "requires_reboot": self.requires_reboot,
            
            "bios_parameters": {name: param.as_dict() 
                               for name, param in self.bios_parameters.items()},
            
            "test_history": self.test_history,
            
            "baseline_results": self.baseline_results.as_dict() if self.baseline_results else None,
            "best_results": self.best_results.as_dict() if self.best_results else None
        }
        return json.dumps(data, indent=2)
    
    @classmethod
    def from_json(cls, json_str):
        """
        Создает профиль из JSON-строки.
        
        Args:
            json_str: JSON-строка с данными профиля
            
        Returns:
            Новый экземпляр CPUProfile
        """
        data = json.loads(json_str)
        profile = cls(
            power_limit1=data.get("power_limit1", 0),
            power_limit2=data.get("power_limit2", 0),
            voltage_offset=data.get("voltage_offset", 0),
            max_temperature=data.get("max_temperature", 0.0),
            measured_perf_score=data.get("measured_perf_score", 0.0),
            cpu_model=data.get("cpu_model", ""),
            creation_date=data.get("creation_date", datetime.now().isoformat()),
            profile_name=data.get("profile_name", "default_profile"),
            description=data.get("description", ""),
            is_stable=data.get("is_stable", True),
            requires_reboot=data.get("requires_reboot", False)
        )
        
        # Загрузка параметров BIOS
        for name, param_data in data.get("bios_parameters", {}).items():
            profile.bios_parameters[name] = BiosParameter.from_dict(param_data)
            
        # Загрузка истории тестов
        profile.test_history = data.get("test_history", [])
        
        # Загрузка результатов тестов
        if data.get("baseline_results"):
            profile.baseline_results = StressTestResult.from_dict(data["baseline_results"])
        if data.get("best_results"):
            profile.best_results = StressTestResult.from_dict(data["best_results"])
            
        return profile
    
    def save_to_file(self, filename):
        """
        Сохраняет профиль в JSON-файл.
        
        Args:
            filename: Путь к файлу для сохранения
        """
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.to_json())
            logger.info(f"Профиль сохранен в {filename}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении профиля: {e}")
    
    @classmethod
    def load_from_file(cls, filename):
        """
        Загружает профиль из JSON-файла.
        
        Args:
            filename: Путь к файлу для загрузки
            
        Returns:
            Новый экземпляр CPUProfile
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return cls.from_json(f.read())
        except Exception as e:
            logger.error(f"Ошибка при загрузке профиля: {e}")
            raise
    
    def generate_report(self):
        """
        Генерирует текстовый отчет по профилю.
        
        Returns:
            Строка с форматированным отчетом
        """
        report = [
            f"=== Отчет CPU Profile Tuner ===",
            f"Имя профиля: {self.profile_name}",
            f"Дата создания: {self.creation_date}",
            f"Модель CPU: {self.cpu_model}",
            f"",
            f"== Ключевые параметры ==",
            f"PL1 (постоянный лимит мощности): {self.power_limit1} Вт",
            f"PL2 (турбо-лимит мощности): {self.power_limit2} Вт",
            f"Смещение напряжения: {self.voltage_offset} мВ",
            f"Максимальная температура: {self.max_temperature:.1f}°C",
            f"",
            f"== Результаты производительности =="
        ]
        
        if self.baseline_results:
            report.append(f"Базовая производительность: {self.baseline_results.operations_per_second:.0f} оп/сек")
            report.append(f"Базовая температура: {self.baseline_results.max_temperature:.1f}°C")
        
        if self.best_results:
            report.append(f"Лучшая производительность: {self.best_results.operations_per_second:.0f} оп/сек")
            report.append(f"Температура при лучшей производительности: {self.best_results.max_temperature:.1f}°C")
            
            # Рассчитываем улучшение
            if self.baseline_results:
                perf_improvement = ((self.best_results.operations_per_second - 
                                    self.baseline_results.operations_per_sec) / 
                                   self.baseline_results.operations_per_sec * 100)
                report.append(f"Прирост производительности: {perf_improvement:.1f}%")
                
        report.append("")
        report.append("== Измененные параметры BIOS ==")
        
        modified_params = [(name, param) for name, param in self.bios_parameters.items() 
                         if param.modified]
        
        if modified_params:
            for name, param in modified_params:
                report.append(f"{name}: {param.default_value} -> {param.current_value}")
        else:
            report.append("Нет измененных параметров")
            
        return "\n".join(report)