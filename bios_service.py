"""
Сервис для взаимодействия с BIOS через AMI SCEWIN.
Позволяет читать и изменять настройки BIOS.
"""
import os
import re
import time
import logging
import subprocess
import tempfile
from typing import Dict, List, Any, Tuple, Optional, Set

logger = logging.getLogger("cpu_tuner")

class BiosService:
    """
    Сервис для взаимодействия с BIOS через AMI SCEWIN.
    Позволяет читать и изменять настройки BIOS.
    """
    
    # Ключевые слова для категоризации параметров
    PERFORMANCE_KEYWORDS = [
        'cpu', 'power', 'limit', 'ratio', 'turbo', 'boost', 'overclock', 'xmp', 'docp',
        'performance', 'frequency', 'clock', 'c-state', 'voltage', 'vcore', 'offset',
        'c-states', 'multiplier', 'tdp', 'pl1', 'pl2', 'ppt', 'tdc', 'edc', 'smt',
        'hyper-threading', 'threading', 'avx', 'memory', 'dram', 'timing', 'speed',
        'bclk', 'base clock', 'intel speed step', 'speedstep', 'coolnquiet', 'cool n quiet'
    ]
    
    # Категории параметров
    PARAM_CATEGORIES = {
        'cpu_power': ['power limit', 'pl1', 'pl2', 'ppt', 'tdc', 'edc', 'tdp'],
        'cpu_freq': ['ratio', 'multiplier', 'turbo', 'boost', 'frequency', 'clock', 'bclk'],
        'cpu_voltage': ['voltage', 'vcore', 'offset', 'vid'],
        'memory': ['memory', 'dram', 'ram', 'xmp', 'docp', 'timing'],
        'cpu_features': ['c-state', 'hyper', 'threading', 'smt', 'avx', 'speedstep', 'coolnquiet']
    }
    
    # Параметры, требующие перезагрузку
    REBOOT_REQUIRED_PARAMS = [
        'memory', 'xmp', 'docp', 'bclk', 'base clock', 'smt', 'hyper-threading'
    ]
    
    def __init__(self, scewin_path: str):
        """
        Инициализация сервиса BIOS.
        
        Args:
            scewin_path: Путь к утилите SCEWIN_x64.exe
        """
        self.tool_path = scewin_path
        self.dump_file = os.path.join(tempfile.gettempdir(), "bios_out.txt")
        self.script_file = os.path.join(tempfile.gettempdir(), "bios_set.txt")
        self.backup_file = os.path.join(tempfile.gettempdir(), "bios_backup.txt")
        
        # Проверка наличия утилиты SCEWIN
        if not os.path.exists(self.tool_path):
            error_msg = f"Утилита SCEWIN не найдена по пути: {self.tool_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        logger.info(f"BiosService инициализирован. SCEWIN: {self.tool_path}")
        
        # Создаем backup текущего BIOS при инициализации
        try:
            script = self._export_all(self.backup_file)
            logger.info(f"Создан бэкап настроек BIOS в {self.backup_file}")
        except Exception as e:
            logger.warning(f"Не удалось создать бэкап настроек BIOS: {e}")
    
    def _export_all(self, out_file: str) -> str:
        """
        Экспортирует все настройки BIOS в указанный файл и возвращает содержимое.
        
        Args:
            out_file: Путь для сохранения настроек BIOS
            
        Returns:
            Содержимое экспортированного файла
            
        Raises:
            IOError: Если экспорт не удался
        """
        logger.debug(f"Экспорт настроек BIOS в {out_file}")
        
        try:
            result = subprocess.run(
                [self.tool_path, "/o", "/s", out_file],
                capture_output=True,
                text=True,
                check=True
            )
            
            if not os.path.exists(out_file):
                error_msg = f"Экспорт AMISCE не удался: выходной файл {out_file} не создан"
                logger.error(error_msg)
                raise IOError(error_msg)
                
            with open(out_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                
            if not content.strip():
                error_msg = "Экспорт AMISCE вернул пустой файл"
                logger.error(error_msg)
                raise IOError(error_msg)
                
            logger.debug(f"Экспорт настроек BIOS успешен: {len(content)} байт")
            return content
        except subprocess.CalledProcessError as e:
            error_msg = f"Ошибка вызова AMISCE: код {e.returncode}, сообщение: {e.stderr}"
            logger.error(error_msg)
            raise IOError(error_msg)
        except Exception as e:
            error_msg = f"Ошибка при экспорте настроек BIOS: {str(e)}"
            logger.error(error_msg)
            raise IOError(error_msg)
    
    def get_setting_value(self, question_name: str) -> int:
        """
        Получает текущее значение параметра BIOS.
        
        Args:
            question_name: Название параметра BIOS
            
        Returns:
            Текущее значение параметра как целое число
            
        Raises:
            KeyError: Если параметр не найден
            ValueError: Если не удалось распарсить значение
        """
        script = self._export_all(self.dump_file)
        lines = script.splitlines()
        
        # Поиск секции для запрошенного параметра
        found_section = False
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith("Setup Question") and question_name.lower() in line.lower():
                found_section = True
                # Поиск строки Value в следующих 10 строках
                for j in range(i, min(i+10, len(lines))):
                    val_line = lines[j].strip()
                    if val_line.startswith("Value"):
                        # Парсинг значения
                        val_parts = val_line.split('=')
                        if len(val_parts) < 2:
                            raise ValueError(f"Некорректный формат строки Value для {question_name}")
                        
                        val_str = val_parts[1].strip()
                        
                        # Обработка шестнадцатеричных форматов
                        if val_str.lower().startswith("0x"):
                            return int(val_str[2:], 16)
                        if val_str.lower().endswith("h"):
                            return int(val_str[:-1], 16)
                            
                        # Обработка десятичных значений
                        try:
                            return int(val_str)
                        except ValueError:
                            # Если это не целое число, пробуем преобразовать float и округлить
                            try:
                                return int(float(val_str))
                            except ValueError:
                                # Если это текстовое значение, возвращаем хэш строки как число
                                # Это хак для обработки неожиданных форматов
                                logger.warning(f"Нечисловое значение для {question_name}: {val_str}")
                                return hash(val_str) % 10000
        
        if not found_section:
            raise KeyError(f"Параметр BIOS '{question_name}' не найден")
        else:
            raise ValueError(f"Найден параметр '{question_name}', но не удалось определить его значение")
    
    def get_setting_type(self, question_name: str) -> str:
        """
        Определяет тип параметра BIOS (целое число, строка, булево значение).
        
        Args:
            question_name: Название параметра BIOS
            
        Returns:
            Тип параметра ('int', 'str', 'bool')
            
        Raises:
            KeyError: Если параметр не найден
        """
        script = self._export_all(self.dump_file)
        lines = script.splitlines()
        
        # Поиск секции для запрошенного параметра
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith("Setup Question") and question_name.lower() in line.lower():
                # Поиск строки Value в следующих 10 строках
                for j in range(i, min(i+10, len(lines))):
                    val_line = lines[j].strip()
                    if val_line.startswith("Value"):
                        val_str = val_line.split('=')[1].strip()
                        
                        # Проверка на булево значение
                        if val_str in ['0', '1']:
                            return 'bool'
                        
                        # Проверка на шестнадцатеричное или десятичное число
                        if val_str.lower().startswith("0x") or val_str.lower().endswith("h"):
                            return 'int'
                        
                        try:
                            int(val_str)
                            return 'int'
                        except ValueError:
                            try:
                                float(val_str)
                                return 'float'
                            except ValueError:
                                return 'str'
        
        raise KeyError(f"Параметр BIOS '{question_name}' не найден")
    
    def set_setting_value(self, question_name: str, new_value: Any) -> None:
        """
        Устанавливает новое значение параметра BIOS.
        
        Args:
            question_name: Название параметра BIOS
            new_value: Новое значение
            
        Raises:
            KeyError: Если параметр не найден
            IOError: Если импорт не удался
        """
        script = self._export_all(self.dump_file)
        lines = script.splitlines()
        
        section_lines = []
        in_section = False
        found = False
        
        # Поиск и модификация секции параметра
        for i, line in enumerate(lines):
            line_trimmed = line.strip()
            
            if not in_section:
                if line_trimmed.startswith("Setup Question") and question_name.lower() in line.lower():
                    # Начинаем захват блока настройки
                    in_section = True
                    found = True
                    section_lines.append(line)
            else:
                # Мы внутри целевой секции
                if line_trimmed.startswith("Setup Question") or len(line_trimmed) == 0:
                    # Достигнут следующий вопрос или пустая строка - конец секции
                    break
                
                if line_trimmed.startswith("Value"):
                    # Заменяем строку Value на новое значение
                    prefix = line[:line.index('=')+1]
                    old_val_str = line.split('=')[1].strip()
                    
                    # Форматируем новое значение в том же формате, что и старое
                    if isinstance(new_value, bool):
                        # Для булевых значений (0 или 1)
                        new_val_str = "1" if new_value else "0"
                    elif old_val_str.lower().startswith("0x") or old_val_str.lower().endswith("h"):
                        # Для шестнадцатеричных значений
                        new_val_str = f"0x{int(new_value):X}"
                    else:
                        # Для других значений
                        new_val_str = str(new_value)
                    
                    section_lines.append(f"{prefix} {new_val_str}")
                    logger.debug(f"Изменяем значение {question_name}: {old_val_str} -> {new_val_str}")
                else:
                    # Остальные строки (Token, Offset, Width и т.д.) оставляем без изменений
                    section_lines.append(line)
        
        if not found:
            error_msg = f"Параметр '{question_name}' не найден, невозможно установить значение"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Запись блока в временный скрипт
        with open(self.script_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(section_lines))
        
        # Импорт (применение) скрипта с измененным значением
        logger.info(f"Применение изменения параметра BIOS: {question_name} = {new_value}")
        try:
            result = subprocess.run(
                [self.tool_path, "/i", "/s", self.script_file],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"Параметр BIOS {question_name} успешно изменен на {new_value}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Ошибка импорта AMISCE: код {e.returncode}, сообщение: {e.stderr}"
            logger.error(error_msg)
            raise IOError(error_msg)
        except Exception as e:
            error_msg = f"Ошибка при установке значения BIOS: {str(e)}"
            logger.error(error_msg)
            raise IOError(error_msg)
    
    def parse_all_bios_settings(self) -> Dict[str, Dict[str, Any]]:
        """
        Парсит все настройки BIOS и возвращает их в виде словаря.
        
        Returns:
            Словарь вида {название_параметра: {value, type, description, ...}}
        """
        logger.info("Парсинг всех настроек BIOS")
        script = self._export_all(self.dump_file)
        lines = script.splitlines()
        
        settings = {}
        current_setting = None
        setting_data = {}
        
        for line in lines:
            line = line.strip()
            
            # Начало нового параметра
            if line.startswith("Setup Question"):
                # Сохраняем предыдущий параметр, если он был
                if current_setting and setting_data:
                    settings[current_setting] = setting_data
                
                # Начинаем новый параметр
                parts = line.split("=", 1)
                if len(parts) == 2:
                    current_setting = parts[1].strip()
                    setting_data = {
                        "name": current_setting,
                        "raw_name": current_setting,
                        "category": self._categorize_parameter(current_setting),
                        "requires_reboot": self._requires_reboot(current_setting),
                        "is_performance_related": self._is_performance_related(current_setting)
                    }
            
            # Детали текущего параметра
            elif current_setting and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                
                if key == "Value":
                    # Парсинг значения
                    if value.lower().startswith("0x"):
                        try:
                            setting_data["value"] = int(value[2:], 16)
                            setting_data["value_raw"] = value
                            setting_data["type"] = "hex"
                        except ValueError:
                            setting_data["value"] = value
                            setting_data["type"] = "str"
                    elif value.lower().endswith("h"):
                        try:
                            setting_data["value"] = int(value[:-1], 16)
                            setting_data["value_raw"] = value
                            setting_data["type"] = "hex"
                        except ValueError:
                            setting_data["value"] = value
                            setting_data["type"] = "str"
                    else:
                        try:
                            setting_data["value"] = int(value)
                            setting_data["value_raw"] = value
                            setting_data["type"] = "int"
                        except ValueError:
                            try:
                                setting_data["value"] = float(value)
                                setting_data["value_raw"] = value
                                setting_data["type"] = "float"
                            except ValueError:
                                if value == "0" or value == "1":
                                    setting_data["value"] = value == "1"
                                    setting_data["value_raw"] = value
                                    setting_data["type"] = "bool"
                                else:
                                    setting_data["value"] = value
                                    setting_data["value_raw"] = value
                                    setting_data["type"] = "str"
                elif key == "BIOS Default":
                    setting_data["default"] = value
                elif key == "Token":
                    setting_data["token"] = value
                elif key == "Offset":
                    setting_data["offset"] = value
                elif key == "Width":
                    setting_data["width"] = value
                else:
                    setting_data[key.lower().replace(" ", "_")] = value
        
        # Сохраняем последний параметр
        if current_setting and setting_data:
            settings[current_setting] = setting_data
        
        logger.info(f"Найдено {len(settings)} параметров BIOS")
        return settings
    
    def find_power_limit_parameters(self) -> List[str]:
        """
        Находит параметры, связанные с лимитами мощности CPU.
        
        Returns:
            Список названий найденных параметров
        """
        settings = self.parse_all_bios_settings()
        power_params = []
        
        # Ключевые слова для поиска лимитов мощности
        power_keywords = [
            'power limit', 'tdp', 'thermal design power', 'pl1', 'pl2', 
            'long duration', 'short duration', 'package power', 'ppt', 
            'tdc', 'edc', 'power target'
        ]
        
        for name, data in settings.items():
            name_lower = name.lower()
            if data.get("is_performance_related") and any(kw in name_lower for kw in power_keywords):
                power_params.append(name)
        
        logger.info(f"Найдены следующие параметры лимитов мощности: {power_params}")
        return power_params
    
    def find_voltage_parameters(self) -> List[str]:
        """
        Находит параметры, связанные с напряжением CPU.
        
        Returns:
            Список названий найденных параметров
        """
        settings = self.parse_all_bios_settings()
        voltage_params = []
        
        # Ключевые слова для поиска настроек напряжения
        voltage_keywords = [
            'voltage', 'vcore', 'offset', 'vid', 'core volt'
        ]
        
        for name, data in settings.items():
            name_lower = name.lower()
            if data.get("is_performance_related") and any(kw in name_lower for kw in voltage_keywords):
                voltage_params.append(name)
        
        logger.info(f"Найдены следующие параметры напряжения: {voltage_params}")
        return voltage_params
    
    def find_xmp_parameters(self) -> List[str]:
        """
        Находит параметры, связанные с профилями памяти XMP/DOCP.
        
        Returns:
            Список названий найденных параметров
        """
        settings = self.parse_all_bios_settings()
        xmp_params = []
        
        # Ключевые слова для поиска настроек XMP/DOCP
        xmp_keywords = [
            'xmp', 'docp', 'memory profile', 'extreme memory profile'
        ]
        
        for name, data in settings.items():
            name_lower = name.lower()
            if any(kw in name_lower for kw in xmp_keywords):
                xmp_params.append(name)
        
        logger.info(f"Найдены следующие параметры XMP/DOCP: {xmp_params}")
        return xmp_params
    
    def find_cstate_parameters(self) -> List[str]:
        """
        Находит параметры, связанные с C-States CPU.
        
        Returns:
            Список названий найденных параметров
        """
        settings = self.parse_all_bios_settings()
        cstate_params = []
        
        # Ключевые слова для поиска настроек C-States
        cstate_keywords = [
            'c-state', 'c state', 'c1e', 'c3', 'c6', 'c7', 'package c state'
        ]
        
        for name, data in settings.items():
            name_lower = name.lower()
            if any(kw in name_lower for kw in cstate_keywords):
                cstate_params.append(name)
        
        logger.info(f"Найдены следующие параметры C-States: {cstate_params}")
        return cstate_params
    
    def find_turbo_boost_parameters(self) -> List[str]:
        """
        Находит параметры, связанные с Turbo Boost / Precision Boost.
        
        Returns:
            Список названий найденных параметров
        """
        settings = self.parse_all_bios_settings()
        turbo_params = []
        
        # Ключевые слова для поиска настроек Turbo
        turbo_keywords = [
            'turbo', 'boost', 'intel turbo', 'precision boost', 'core performance'
        ]
        
        for name, data in settings.items():
            name_lower = name.lower()
            if data.get("is_performance_related") and any(kw in name_lower for kw in turbo_keywords):
                turbo_params.append(name)
        
        logger.info(f"Найдены следующие параметры Turbo Boost: {turbo_params}")
        return turbo_params
    
    def find_all_performance_parameters(self) -> Dict[str, List[str]]:
        """
        Находит все параметры, влияющие на производительность, по категориям.
        
        Returns:
            Словарь {категория: [список_параметров]}
        """
        settings = self.parse_all_bios_settings()
        performance_params = {
            "power": [],
            "voltage": [],
            "memory": [],
            "cpu_features": [],
            "turbo": [],
            "cstates": [],
            "other": []
        }
        
        for name, data in settings.items():
            if not data.get("is_performance_related"):
                continue
                
            category = data.get("category", "").lower()
            name_lower = name.lower()
            
            # Категоризация параметров
            if any(kw in name_lower for kw in ['power', 'limit', 'tdp', 'pl1', 'pl2', 'ppt']):
                performance_params["power"].append(name)
            elif any(kw in name_lower for kw in ['voltage', 'vcore', 'offset', 'vid']):
                performance_params["voltage"].append(name)
            elif any(kw in name_lower for kw in ['memory', 'ram', 'xmp', 'docp']):
                performance_params["memory"].append(name)
            elif any(kw in name_lower for kw in ['c-state', 'c state', 'c1e', 'c3', 'c6']):
                performance_params["cstates"].append(name)
            elif any(kw in name_lower for kw in ['turbo', 'boost']):
                performance_params["turbo"].append(name)
            elif any(kw in name_lower for kw in ['smt', 'hyper', 'thread', 'virtualization']):
                performance_params["cpu_features"].append(name)
            else:
                performance_params["other"].append(name)
        
        return performance_params
    
    def restore_defaults(self) -> bool:
        """
        Восстанавливает настройки BIOS из резервной копии.
        
        Returns:
            True, если восстановление успешно, иначе False
        """
        if not os.path.exists(self.backup_file):
            logger.error("Файл резервной копии BIOS не найден")
            return False
        
        try:
            logger.info("Восстановление настроек BIOS из резервной копии")
            result = subprocess.run(
                [self.tool_path, "/i", "/s", self.backup_file],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info("Настройки BIOS успешно восстановлены")
            return True
        except Exception as e:
            logger.error(f"Ошибка при восстановлении настроек BIOS: {e}")
            return False
    
    def _categorize_parameter(self, param_name: str) -> str:
        """
        Определяет категорию параметра BIOS.
        
        Args:
            param_name: Название параметра
            
        Returns:
            Категория параметра
        """
        param_lower = param_name.lower()
        
        for category, keywords in self.PARAM_CATEGORIES.items():
            if any(kw in param_lower for kw in keywords):
                return category
        
        # Если не нашли подходящую категорию
        return "other"
    
    def _is_performance_related(self, param_name: str) -> bool:
        """
        Определяет, влияет ли параметр на производительность.
        
        Args:
            param_name: Название параметра
            
        Returns:
            True, если параметр влияет на производительность, иначе False
        """
        param_lower = param_name.lower()
        return any(kw in param_lower for kw in self.PERFORMANCE_KEYWORDS)
    
    def _requires_reboot(self, param_name: str) -> bool:
        """
        Определяет, требует ли изменение параметра перезагрузку.
        
        Args:
            param_name: Название параметра
            
        Returns:
            True, если требуется перезагрузка, иначе False
        """
        param_lower = param_name.lower()
        return any(kw in param_lower for kw in self.REBOOT_REQUIRED_PARAMS)