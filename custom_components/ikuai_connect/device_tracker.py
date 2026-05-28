"""iKuai 追踪器."""
from __future__ import annotations

import logging
from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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
    
    # 获取配置 (Options 存储)
    tracker_config = entry.options.get(CONF_TRACKER_CONFIG, {})
    host_id = coordinator.host.split("//")[-1].replace(".", "_").replace(":", "_")
    
    # 获取注册表用于最后的“删除”操作
    ent_reg = er.async_get(hass)
    existing_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)

    entities_to_add = []
    current_uids = set()

    # 【架构重构】：不管 Registry 是否存在，都为配置中的所有 MAC 创建对象
    for mac, conf in tracker_config.items():
        mac_lower = mac.lower()
        uid = f"ik_t_{mac_lower.replace(':', '')}_{host_id}"
        current_uids.add(uid)
        
        # 只要配置里有，我们就创建对象
        entities_to_add.append(IkuaiTracker(coordinator, mac_lower, conf, uid))

    # 【清理逻辑】：仅负责删除“配置中已消失”的实体
    for entity in existing_entries:
        if entity.domain == "device_tracker" and entity.unique_id not in current_uids:
            _LOGGER.info("注销已移除的追踪实体: %s", entity.entity_id)
            ent_reg.async_remove(entity.entity_id)

    # 将所有实体提交。HA 核心会自动处理：
    # 1. 发现 unique_id 已有的 -> 更新 runtime 对象
    # 2. 发现 unique_id 没有的 -> 创建新条目
    if entities_to_add:
        async_add_entities(entities_to_add, True)


class IkuaiTracker(CoordinatorEntity[IkuaiCoordinator], TrackerEntity):
    """iKuai 终端追踪实体."""

    _attr_has_entity_name = True
    _attr_translation_key = "ikuai_tracker" 

    def __init__(self, coordinator: IkuaiCoordinator, mac: str, config: dict, uid: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._mac = mac # 小写带冒号
        self._attr_name = config.get("name")
        self._attr_unique_id = uid
        
        # 关联到 iKuai 路由器主设备
        self._attr_device_info = coordinator.device_info

    @property
    def is_connected(self) -> bool:
        """判断是否在线."""
        if not self.coordinator.data or "clients" not in self.coordinator.data:
            return False
        return self._mac in self.coordinator.data.get("clients", {})

    @property
    def state(self) -> str:
        """返回状态 (STATE_HOME/STATE_NOT_HOME)."""
        return STATE_HOME if self.is_connected else STATE_NOT_HOME

    @property
    def source_type(self) -> SourceType:
        """定义为路由器追踪."""
        return SourceType.ROUTER

    @property
    def extra_state_attributes(self) -> dict:
        """附加详细信息."""
        if not self.coordinator.data or "clients" not in self.coordinator.data:
            return {}
        
        client = self.coordinator.data.get("clients", {}).get(self._mac, {})
        if not client:
            return {"mac_address": self._mac}

        return {
            "mac_address": self._mac,
            "ip_address": client.get("ip_addr"),
            "ap_mac": client.get("apmac"),
            "uplink_addr": client.get("uplink_addr"),
        }