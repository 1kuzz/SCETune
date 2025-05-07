"""
Модуль для мониторинга аппаратных параметров системы.
Предоставляет функционал для чтения температуры, энергопотребления и нагрузки CPU.
"""
import time
import logging
import platform
import os
import json
import re
import subprocess
from typing import Dict, Tuple, List, Optional, Union, Any
import wmi
import pythoncom
import psutil
import cpuinfo

logger = logging.getLogger("cpu_tuner")

class HardwareMonitorService:
    """
    Сервис для мониторинга аппаратных параметров системы.
    Использует wmi и psutil для доступа к аппаратной информации.
    """
    
    def __init__(self):
        """Инициализация сервиса мониторинга"""
        logger.info("Инициализация HardwareMonitorService")
        
        # Инициализация WMI (необходимо вызывать в том же потоке, где будет использоваться)
        pythoncom.CoInitialize()
        
        # Пытаемся различными способами получить доступ к датчикам температуры
        self.w = wmi.WMI(namespace="root\\wmi")
        self.base_wmi = wmi.WMI()
        
        # Попытка получить доступ к MSAcpi_ThermalZoneTemperature для температуры CPU
        try:
            self.temp_sensors = self.w.MSAcpi_ThermalZoneTemperature() if hasattr(self.w, 'MSAcpi_ThermalZoneTemperature') else []
            if self.temp_sensors:
                logger.info("Найдены ACPI датчики температуры")
        except Exception as e:
            logger.warning(f"Не удалось инициализировать ACPI датчики температуры: {e}")
            self.temp_sensors = []
        
        # Пытаемся получить доступ к OpenHardwareMonitor, если он запущен
        try:
            self.ohm = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            sensors = self.ohm.Sensor()
            if sensors:
                logger.info(f"OpenHardwareMonitor доступен. Найдено {len(sensors)} датчиков")
                self.has_ohm = True
            else:
                logger.warning("OpenHardwareMonitor запущен, но датчики не найдены")
                self.has_ohm = False
        except Exception as e:
            logger.warning(f"OpenHardwareMonitor недоступен: {e}")
            self.has_ohm = False
        
        # Инициализация информации о CPU
        self.cpu_info = self._get_cpu_info()
        logger.info(f"CPU: {self.cpu_info.get('brand_raw', 'Unknown')}")
        
        # Кэширование данных, доступных из psutil
        self.psutil_has_sensors = hasattr(psutil, 'sensors_temperatures')
        if self.psutil_has_sensors:
            logger.info("psutil поддерживает датчики температуры")
            # Проверяем, какие датчики доступны
            temps = psutil.sensors_temperatures()
            logger.info(f"Доступные датчики через psutil: {list(temps.keys())}")
        
        # Для отслеживания максимальных значений в течение сеанса
        self.max_temp_session = 0.0
        self.max_power_session = 0.0
        self.last_read_success = True
        
        # Предварительное чтение данных для проверки доступности
        test_data = self.read_cpu_data()
        logger.info(f"Тестовое чтение данных: temp={test_data[0]:.1f}°C, power={test_data[1]:.1f}W, load={test_data[2]:.1f}%")
    
    def _get_cpu_info(self) -> Dict[str, str]:
        """
        Получает подробную информацию о CPU.
        
        Returns:
            Словарь с информацией о CPU
        """
        try:
            info = cpuinfo.get_cpu_info()
            
            # Определяем, Intel или AMD
            brand = info.get('brand_raw', '').lower()
            if 'intel' in brand:
                cpu_type = 'intel'
            elif 'amd' in brand:
                cpu_type = 'amd'
            else:
                cpu_type = 'unknown'
                
            # Дополнительно получаем информацию из WMI
            wmi_cpu_info = {}
            try:
                cpu_wmi = self.base_wmi.Win32_Processor()[0]
                wmi_cpu_info = {
                    'name': cpu_wmi.Name,
                    'socket': cpu_wmi.SocketDesignation,
                    'manufacturer': cpu_wmi.Manufacturer,
                    'current_clock': cpu_wmi.CurrentClockSpeed,
                    'max_clock': cpu_wmi.MaxClockSpeed
                }
            except Exception as e:
                logger.warning(f"Не удалось получить CPU информацию через WMI: {e}")
            
            # Объединяем информацию
            result = {
                **info,
                'type': cpu_type,
                'core_count': psutil.cpu_count(logical=False),
                'thread_count': psutil.cpu_count(logical=True),
                **wmi_cpu_info
            }
            
            return result
        except Exception as e:
            logger.error(f"Ошибка при получении информации о CPU: {e}")
            return {'brand_raw': 'Unknown CPU', 'type': 'unknown'}
    
    def read_cpu_data(self) -> Tuple[float, float, float]:
        """
        Считывает текущие данные о CPU: температуру (°C), мощность (Вт) и нагрузку (%).
        
        Returns:
            Кортеж (температура, мощность, нагрузка)
        """
        # Получение загрузки CPU
        load = psutil.cpu_percent(interval=0.2)
        
        # Инициализация значений
        temp = 0.0
        power = 0.0
        
        # Попытки получить температуру из разных источников
        temp_sources_tried = []
        
        # 1. Попытка использовать OpenHardwareMonitor (если доступен)
        if self.has_ohm:
            try:
                # Обновляем список сенсоров перед чтением
                cpu_temps = self.ohm.Sensor(["Temperature"])
                temp_sources_tried.append("OpenHardwareMonitor")
                
                # Ищем CPU package сенсор
                for sensor in cpu_temps:
                    if "CPU" in sensor.Name and "Package" in sensor.Name:
                        temp = float(sensor.Value)
                        logger.debug(f"Температура из OHM: {temp}°C (сенсор: {sensor.Name})")
                        break
                
                # Если не нашли Package, попробуем любой CPU сенсор
                if temp == 0.0:
                    for sensor in cpu_temps:
                        if "CPU" in sensor.Name:
                            temp = float(sensor.Value)
                            logger.debug(f"Температура из OHM (alternative): {temp}°C (сенсор: {sensor.Name})")
                            break
                
                # Попытка получить мощность CPU
                cpu_powers = self.ohm.Sensor(["Power"])
                for sensor in cpu_powers:
                    if "CPU" in sensor.Name and "Package" in sensor.Name:
                        power = float(sensor.Value)
                        logger.debug(f"Мощность из OHM: {power}W (сенсор: {sensor.Name})")
                        break
            except Exception as e:
                logger.debug(f"Ошибка при чтении данных из OpenHardwareMonitor: {e}")
        
        # 2. Если OHM не дал результатов, пробуем psutil sensors
        if temp == 0.0 and self.psutil_has_sensors:
            try:
                temp_sources_tried.append("psutil")
                temps = psutil.sensors_temperatures()
                
                # Проверяем различные источники температуры
                temp_sources = ['coretemp', 'k10temp', 'acpitz', 'it8686', 'it8688', 'it8655']
                
                for source in temp_sources:
                    if source in temps and temps[source]:
                        # Ищем сначала 'Package id 0' или 'Tdie' для AMD
                        for entry in temps[source]:
                            if 'package' in entry.label.lower() or 'tdie' in entry.label.lower():
                                temp = entry.current
                                logger.debug(f"Температура из psutil ({source}): {temp}°C (сенсор: {entry.label})")
                                break
                        
                        # Если не нашли package, берем первый доступный
                        if temp == 0.0 and temps[source]:
                            temp = temps[source][0].current
                            logger.debug(f"Температура из psutil ({source}, fallback): {temp}°C")
                        
                        # Выходим после первого удачного источника
                        if temp > 0:
                            break
            except Exception as e:
                logger.debug(f"Ошибка при чтении температуры через psutil: {e}")
        
        # 3. Если до сих пор не получили температуру, пробуем WMI ACPI
        if temp == 0.0 and self.temp_sensors:
            try:
                temp_sources_tried.append("WMI ACPI")
                # Температура в WMI дается в десятых долях Кельвина, конвертируем в Цельсий
                temp = (self.temp_sensors[0].CurrentTemperature / 10.0) - 273.15
                logger.debug(f"Температура из WMI ACPI: {temp}°C")
            except Exception as e:
                logger.debug(f"Ошибка при чтении температуры через WMI: {e}")
        
        # 4. Если все методы не работают, делаем грубую оценку
        if temp == 0.0:
            temp_sources_tried.append("estimation")
            # Очень грубая оценка на основе загрузки
            freq = psutil.cpu_freq()
            if freq and freq.current:
                # Предполагаем диапазон температур от 35 до 85°C
                max_temp = 85.0
                base_temp = 35.0
                freq_ratio = freq.current / freq.max if freq.max else 0.5
                temp = base_temp + (max_temp - base_temp) * freq_ratio * (load / 100.0)
                logger.debug(f"Оценочная температура: {temp}°C (на основе загрузки и частоты)")
            else:
                # Совсем простая оценка только по нагрузке
                temp = 35.0 + (load / 100.0) * 45.0
                logger.debug(f"Оценочная температура (только загрузка): {temp}°C")
        
        # Если не смогли получить мощность, делаем оценку на основе TDP
        if power == 0.0:
            # Предполагаемый TDP
            if hasattr(self, 'estimated_tdp'):
                tdp = self.estimated_tdp
            else:
                # Оценка TDP на основе типа CPU, для Intel обычно TDP указан в названии
                # Например, для Core i7-8700K TDP = 95W
                cpu_name = self.cpu_info.get('brand_raw', '')
                tdp_match = re.search(r'(\d+)[WT]', cpu_name)
                if tdp_match:
                    tdp = int(tdp_match.group(1))
                else:
                    # Если TDP не найден в названии, используем типичные значения
                    if 'i9' in cpu_name:
                        tdp = 125
                    elif 'i7' in cpu_name:
                        tdp = 95
                    elif 'i5' in cpu_name:
                        tdp = 65
                    elif 'i3' in cpu_name:
                        tdp = 45
                    elif 'ryzen 9' in cpu_name.lower():
                        tdp = 105
                    elif 'ryzen 7' in cpu_name.lower():
                        tdp = 95
                    elif 'ryzen 5' in cpu_name.lower():
                        tdp = 65
                    elif 'ryzen 3' in cpu_name.lower():
                        tdp = 45
                    else:
                        tdp = 65  # Среднее значение для большинства десктопных CPU
                
                self.estimated_tdp = tdp
                logger.info(f"Оценка TDP: {tdp}W для {cpu_name}")
            
            # Оценка на основе загрузки (с коэффициентом эффективности)
            power = tdp * (load / 100.0) * 0.8
            logger.debug(f"Оценочная мощность: {power}W (на основе TDP={tdp}W и загрузки={load}%)")
        
        # Обновление максимальных значений сессии
        if temp > self.max_temp_session:
            self.max_temp_session = temp
        if power > self.max_power_session:
            self.max_power_session = power
        
        # Логирование только если были проблемы с прошлым чтением или чтение температуры из другого источника
        if not self.last_read_success or temp == 0.0:
            logger.warning(f"Данные CPU: temp={temp:.1f}°C, power={power:.1f}W, load={load:.1f}%")
            logger.warning(f"Попытки чтения температуры из: {', '.join(temp_sources_tried)}")
            self.last_read_success = (temp > 0)
        
        return (temp, power, load)
    
    def get_cpu_frequencies(self) -> Dict[str, float]:
        """
        Получает текущие частоты CPU для всех ядер.
        
        Returns:
            Словарь с частотами ядер
        """
        result = {}
        
        # Попытка получить через psutil
        try:
            freq = psutil.cpu_freq(percpu=True)
            if freq:
                for i, f in enumerate(freq):
                    result[f"core_{i}"] = f.current
        except Exception as e:
            logger.debug(f"Ошибка при получении частот CPU через psutil: {e}")
        
        # Если не удалось получить для каждого ядра, хотя бы средняя частота
        if not result:
            try:
                freq = psutil.cpu_freq()
                if freq:
                    result["average"] = freq.current
            except Exception as e:
                logger.debug(f"Ошибка при получении средней частоты CPU: {e}")
        
        # Попытка получить через OpenHardwareMonitor
        if self.has_ohm and not result:
            try:
                cpu_clocks = self.ohm.Sensor(["Clock"])
                for sensor in cpu_clocks:
                    if "CPU" in sensor.Name:
                        name = sensor.Name.replace(' ', '_').lower()
                        result[name] = float(sensor.Value)
            except Exception as e:
                logger.debug(f"Ошибка при получении частот CPU через OHM: {e}")
        
        return result
    
    def get_memory_usage(self) -> Dict[str, float]:
        """
        Получает информацию об использовании памяти.
        
        Returns:
            Словарь с данными использования памяти
        """
        memory = psutil.virtual_memory()
        return {
            "total_gb": memory.total / (1024**3),
            "used_gb": memory.used / (1024**3),
            "percent": memory.percent
        }
    
    def collect_system_info(self) -> Dict[str, Any]:
        """
        Собирает полную информацию о системе.
        
        Returns:
            Словарь с системной информацией
        """
        system_info = {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu": self.cpu_info,
            "memory": self.get_memory_usage(),
            "cpu_frequencies": self.get_cpu_frequencies()
        }
        
        # Добавляем данные по нагрузке и температуре
        temp, power, load = self.read_cpu_data()
        system_info.update({
            "cpu_temperature": temp,
            "cpu_power": power,
            "cpu_load": load
        })
        
        return system_info
    
    def close(self):
        """Освобождает ресурсы мониторинга"""
        try:
            pythoncom.CoUninitialize()
        except:
            pass
        logger.info(f"HardwareMonitorService завершен. Макс. температура: {self.max_temp_session:.1f}°C")