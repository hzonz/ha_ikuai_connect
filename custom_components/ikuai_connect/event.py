"""Support for iKuai Connect event entities."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, EVENT_TYPES, IkuaiEventEntityDescription
from .coordinator import IkuaiCoordinator

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(IkuaiEvent(coordinator, desc) for desc in EVENT_TYPES)

class IkuaiEvent(CoordinatorEntity[IkuaiCoordinator], EventEntity):
    """iKuai 事件实体类."""

    entity_description: IkuaiEventEntityDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiEventEntityDescription):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_device_info = coordinator.device_info
        # 定义事件类型（2026 标准要求）
        if description.key == "message_center":
            self._attr_event_types = ["notification"]
        else:
            self._attr_event_types = ["online", "offline"]

    def _handle_coordinator_update(self) -> None:
        """当协调器有新数据时，检查是否有新事件需要触发."""
        events = self.coordinator.data.get("events", {})
        
        if self.entity_description.key == "message_center":
            for msg in events.get("messages", []):
                self._trigger_event(
                    "notification",
                    {
                        "title": msg.get("title"),
                        "message": msg.get("detail"),
                        "type": msg.get("type"),
                        "timestamp": msg.get("timestamp")
                    }
                )
        
        elif self.entity_description.key == "terminal_presence":
            for p in events.get("presence", []):
                # logout_time 为 0 表示上线，否则为下线
                action = "offline" if p.get("logout_time", 0) > 0 else "online"
                self._trigger_event(
                    action,
                    {
                        "mac": p.get("mac"),
                        "ip": p.get("ip_addr"),
                        "name": p.get("comment") or p.get("termname") or "Unknown",
                        "device_type": p.get("devtype"),
                        "online_time": p.get("online_time")
                    }
                )
        
        super()._handle_coordinator_update()