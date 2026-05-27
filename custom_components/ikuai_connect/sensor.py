"""Sensor platform for iKuai Connect."""
from __future__ import annotations

from dataclasses import replace
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    SYSTEM_SENSORS,
    INTERFACE_SENSORS,
    MAINTENANCE_SENSORS,
    DISK_SENSORS,
    IkuaiSensorEntityDescription,
)
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai Connect sensors."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    # 1. 处理系统级传感器 (CPU/内存等)
    # 这些是核心数据，保持默认启用状态
    for description in SYSTEM_SENSORS:
        entities.append(IkuaiSystemSensor(coordinator, description))

    # 2. 批量处理【接口监控管理】子设备下的所有网口传感器
    interfaces = coordinator.data.get("interfaces", {})
    for iface_name in interfaces:
        for description in INTERFACE_SENSORS:
            entities.append(IkuaiIfaceSensor(coordinator, description, iface_name))

    # 3. 添加升级与备份传感器 (挂载在维护子设备)
    for description in MAINTENANCE_SENSORS:
        entities.append(IkuaiMaintenanceSensor(coordinator, description))

    # 4. 添加磁盘信息传感器 (挂载在维护子设备)
    disks_data = coordinator.data.get("disks", {})
    for disk_id, disk_info in disks_data.items():
        for description in DISK_SENSORS:
            entities.append(IkuaiDiskSensor(coordinator, description, disk_id))

    # 提交所有实体。True 表示在添加前先执行一次坐标器数据同步，确保一出来就有值
    async_add_entities(entities, True)


class IkuaiSystemSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """主设备负载传感器 (挂载在路由器主卡片下)."""

    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiSensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn:
            return {}
        return self.entity_description.attr_fn(self.coordinator.data)


class IkuaiIfaceSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """网络接口监控传感器 (子设备)."""

    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiSensorEntityDescription, iface_name: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._iface_name = iface_name
        
        self._attr_translation_placeholders = {"iface": iface_name}
        
        # 保持唯一 ID 不变，确保历史数据不丢失
        self._attr_unique_id = f"{coordinator.host}_{iface_name}_{description.key}"
        self._attr_device_info = coordinator.iface_mgmt_device_info

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        iface_data = self.coordinator.data.get("interfaces", {}).get(self._iface_name, {})
        return iface_data.get(self.entity_description.key)

class IkuaiMaintenanceSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """升级与备份管理 (子设备)."""
    _attr_has_entity_name = True
    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_device_info = coordinator.maintenance_device_info

    @property
    def native_value(self):
        if not self.coordinator.data: return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data or not self.entity_description.attr_fn: return {}
        return self.entity_description.attr_fn(self.coordinator.data)    

# 磁盘实体类
class IkuaiDiskSensor(CoordinatorEntity[IkuaiCoordinator], SensorEntity):
    """磁盘管理传感器."""
    entity_description: IkuaiSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiSensorEntityDescription, disk_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._disk_id = disk_id
        
        # 获取该硬盘的型号作为设备名参考
        disk_data = coordinator.data["disks"].get(disk_id, {})
        model = disk_data.get("base_info", {}).get("model", disk_id)
        
        # 1. 唯一 ID (包含 host, disk_id 和 实体 key)
        self._attr_unique_id = f"{coordinator.host}_{disk_id}_{description.key}"
        
        # 2. 定义子设备信息 (以型号命名)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.host}_disk_{disk_id}")},
            name=f"存储: {model}", # 例如：存储: QEMU HARDDISK
            manufacturer="iKuai",
            model=model,
            via_device=(DOMAIN, coordinator.host), # 挂载在主路由器下
        )

    @property
    def native_value(self):
        """从 coordinator 获取状态值."""
        if not self.coordinator.data: return None
        return self.coordinator.data["disks"].get(self._disk_id, {}).get("state", {}).get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        """根据实体类型注入属性."""
        if not self.coordinator.data: return {}
        disk_data = self.coordinator.data["disks"].get(self._disk_id, {})
        
        # 如果是“总容量”实体，展示磁盘基础信息
        if self.entity_description.key == "disk_physical_size":
            return disk_data.get("base_info", {})
        
        # 如果是“已用容量”实体，展示分区列表
        if self.entity_description.key == "disk_used_size":
            return {"partitions": disk_data.get("partitions", [])}
            
        return {}