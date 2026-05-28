"""Support for iKuai Connect event entities."""
from __future__ import annotations

import logging
from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, EVENT_TYPES, IkuaiEventEntityDescription
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai event entities."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    async_add_entities(IkuaiEvent(coordinator, desc) for desc in EVENT_TYPES)


class IkuaiEvent(CoordinatorEntity[IkuaiCoordinator], EventEntity):
    """iKuai 事件实体实现 - 支持动态描述性事件."""

    entity_description: IkuaiEventEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiEventEntityDescription):
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_device_info = coordinator.device_info
        
        # 初始事件类型列表，设为空，后续动态填充
        self._attr_event_types = []

    @callback
    def _handle_coordinator_update(self) -> None:
        """解析 Coordinator 传来的新事件并动态触发."""
        if not self.coordinator.data:
            return

        events = self.coordinator.data.get("events", {})
        fired = False

        # --- 处理消息中心 ---
        if self.entity_description.key == "message_center":
            new_msgs = events.get("messages", [])
            for msg in new_msgs:
                # 构造动态事件名：例如 "系统告警: 自动备份成功"
                dynamic_type = f"{msg.get('title')}"
                
                # 【核心逻辑】：动态注入类型
                if dynamic_type not in self._attr_event_types:
                    self._attr_event_types.append(dynamic_type)
                
                self._trigger_event(dynamic_type, {"detail": msg.get("detail")})
                fired = True

        # --- 处理终端上下线 ---
        elif self.entity_description.key == "terminal_presence":
            presences = events.get("presence", [])
            for p in presences:

                device_name = p.get("termname") or p.get("comment") or p.get("mac")
                
                # 动态维护事件类型列表，防止 ValueError
                if device_name not in self._attr_event_types:
                    # 保留最近 100 个终端名，防止列表过大
                    if len(self._attr_event_types) > 100:
                        self._attr_event_types.pop(0)
                    self._attr_event_types.append(device_name)

                # 3. 计算流量单位 (转为更易读的 MB)
                up_mb = round(p.get("total_up", 0) / 1048576, 2)
                down_mb = round(p.get("total_down", 0) / 1048576, 2)

                # 4. 触发事件并写入所有属性
                self._trigger_event(
                    device_name,
                    {
                        "mac": p.get("mac"),
                        "ip": p.get("ip_addr"),
                        "action": "下线/结算" if p.get("logout_time", 0) > 0 else "上线",
                        "online_seconds": p.get("online_time"),
                        "upload_mb": up_mb,
                        "download_mb": down_mb,
                        "os": p.get("systype"),
                        "vendor": p.get("devtype"),
                        "model": p.get("client_model"),
                        "interface": p.get("interface"),
                        "timestamp": p.get("date_time")
                    }
                )
                fired = True

        if fired:
            # 强制写入状态，使 UI 上的时间戳和事件类型立即刷新
            self.async_write_ha_state()

        super()._handle_coordinator_update()