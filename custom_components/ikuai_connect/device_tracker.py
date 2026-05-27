"""Support for iKuai Connect device trackers with auto-cleanup."""
from __future__ import annotations

import logging
from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er # 导入实体注册表
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_TRACKER_CONFIG
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai trackers."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    
    # 1. 获取当前配置中需要追踪的 MAC 列表
    tracker_config = entry.options.get(CONF_TRACKER_CONFIG, {})
    current_tracking_macs = [mac.lower().replace(":", "") for mac in tracker_config.keys()]

    # 2. 【核心功能】：清理幽灵实体
    # 获取实体注册表
    ent_reg = er.async_get(hass)
    # 查找所有属于当前集成、当前配置条目、且属于 device_tracker 平台的实体
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    
    for entity in entries:
        if entity.domain != "device_tracker":
            continue
        
        # 从 unique_id 中提取 MAC (假设 ID 格式为 ik_t_MAC_HOST)
        # 我们的 unique_id 格式: f"ik_t_{mac_clean}_{host_id}"
        # 这里通过检查 unique_id 是否包含当前配置中的 MAC 来判断
        is_still_configured = False
        for mac in current_tracking_macs:
            if mac in entity.unique_id:
                is_still_configured = True
                break
        
        if not is_still_configured:
            _LOGGER.info("移除幽灵实体: %s", entity.entity_id)
            ent_reg.async_remove(entity.entity_id)

    # 3. 创建当前需要的实体
    if not tracker_config:
        return

    async_add_entities(
        [IkuaiTracker(coordinator, mac.lower(), conf) for mac, conf in tracker_config.items()],
        True
    )

class IkuaiTracker(CoordinatorEntity[IkuaiCoordinator], TrackerEntity):
    """iKuai 终端追踪实体."""

    _attr_has_entity_name = True
    _attr_translation_key = "ikuai_tracker" 

    def __init__(self, coordinator: IkuaiCoordinator, mac: str, config: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._mac = mac
        self._attr_name = config.get("name")
        
        host_id = coordinator.host.split("//")[-1].replace(".", "_").replace(":", "_")
        # 保持这个 ID 格式稳定，以便清理逻辑识别
        self._attr_unique_id = f"ik_t_{self._mac.replace(':', '')}_{host_id}"
        
        self._attr_device_info = coordinator.device_info

    @property
    def is_connected(self) -> bool:
        """判断是否在线."""
        if not self.coordinator.data or "clients" not in self.coordinator.data:
            return False
        return self._mac in self.coordinator.data.get("clients", {})

    @property
    def state(self) -> str:
        """转换状态."""
        return STATE_HOME if self.is_connected else STATE_NOT_HOME

    @property
    def source_type(self) -> SourceType:
        return SourceType.ROUTER

    @property
    def extra_state_attributes(self) -> dict:
        """返回详细信息."""
        if not self.coordinator.data or "clients" not in self.coordinator.data:
            return {}
        
        client = self.coordinator.data.get("clients", {}).get(self._mac, {})
        if not client:
            return {"mac": self._mac}

        return {
            "mac_address": self._mac,
            "ip_address": client.get("ip_addr"),
            "ap_mac": client.get("apmac"),
            "uplink_addr": client.get("uplink_addr"),
        }