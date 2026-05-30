"""Support for iKuai Connect event entities."""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import EVENT_TYPES, IkuaiEventEntityDescription
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


class IkuaiEvent(EventEntity, CoordinatorEntity[IkuaiCoordinator]):
    """iKuai 固定事件模型实现."""

    entity_description: IkuaiEventEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: IkuaiCoordinator, description: IkuaiEventEntityDescription) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_{description.key}"
        self._attr_device_info = coordinator.maintenance_device_info

        # 固定事件类型池
        self._registered_types = {"message", "online", "offline", "ddns", "wifi"}
        self._attr_event_types = list(self._registered_types)

        # 查重集合
        self._seen_event_ids: set[str] = set()

    async def async_added_to_hass(self) -> None:
        """实体加入系统，处理初次同步."""
        await super().async_added_to_hass()
        self._process_incoming_events()

    @callback
    def _handle_coordinator_update(self) -> None:
        """响应协调器数据刷新."""
        self._process_incoming_events()
        super()._handle_coordinator_update()

    @callback
    def _process_incoming_events(self) -> None:
        """核心解析逻辑."""
        if not self.coordinator.data or "events" not in self.coordinator.data:
            return

        key = self.entity_description.key
        events_data = self.coordinator.data["events"]
        fired = False

        # 根据实体 Key 路由到不同处理器
        if key == "message_center":
            fired = self._handle_messages(events_data.get("messages", []))
        elif key == "terminal_presence_log":
            fired = self._handle_presence(events_data.get("presence", []))
        elif key == "dynamic_ddns_log":
            fired = self._handle_ddns(events_data.get("ddns", []))
        elif key == "wireless_terminal_log":
            fired = self._handle_wifi(events_data.get("wifi", []))

        if fired:
            self.async_write_ha_state()

    # --- 具体的处理器逻辑 ---

    def _handle_messages(self, items: Iterable[dict[str, Any]]) -> bool:
        has_fired = False
        for item in items:
            event_id = f"m_{item.get('id')}"
            if self._is_duplicate(event_id):
                continue

            title = item.get("title", "notification")
            self._fire_smart_event(title, {
                "detail": item.get("detail"),
                "status": "read" if item.get("status") == 1 else "unread",
                "id": item.get("id")
            })
            has_fired = True
        return has_fired

    def _handle_presence(self, items: Iterable[dict[str, Any]]) -> bool:
        has_fired = False
        for item in items:
            event_id = f"p_{item.get('id')}"
            if self._is_duplicate(event_id):
                continue

            device_label = item.get("termname") or item.get("client_model") or item.get("mac")
            is_off = int(item.get("logout_time", 0)) > 0
            action = "offline" if is_off else "online"

            self._fire_smart_event(device_label, {
                "mac": item.get("mac"),
                "ip": item.get("ip_addr"),
                "action": action,
                "online_time": item.get("online_time"),
                "today_total": item.get("today_total"),
                "os": item.get("systype"),
                "vendor": item.get("devtype"),
                "model": item.get("client_model"),
                "id": item.get("id"),               
                "timestamp": item.get("date_time")
            })
            has_fired = True
        return has_fired

    def _handle_ddns(self, items: Iterable[dict[str, Any]]) -> bool:
        has_fired = False
        for item in items:
            event_id = f"d_{item.get('id')}"
            if self._is_duplicate(event_id):
                continue

            display_name = item.get("domain", "ddns")
            self._fire_smart_event(display_name, {
                "domain": item.get("domain"),
                "status": item.get("result"),
                "message": item.get("event"),
                "ip": item.get("ip_addr"),
                "mac": item.get("interface"),
                "id": item.get("id"),
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.get("timestamp", 0)))
            })
            has_fired = True
        return has_fired

    def _handle_wifi(self, items: Iterable[dict[str, Any]]) -> bool:
        has_fired = False
        for item in items:
            event_id = f"w_{item.get('id')}"
            if self._is_duplicate(event_id):
                continue

            name = item.get("termname")
            if not name or name == "--":
                name = item.get("mac")

            self._fire_smart_event(name, {
                "mac": item.get("mac"),
                "ssid": item.get("ssid"),
                "signal": f"{item.get('signal')} dBm",
                "ap_mac": item.get("apmac"),
                "ap_name": item.get("apmac_comment"),
                "action": item.get("action"),
                "reason": item.get("errmsg"),
                "id": item.get("id")
            })
            has_fired = True
        return has_fired

    # --- 辅助方法 ---

    def _fire_smart_event(self, event_type: str, data: dict) -> None:
        """动态注册并触发事件，确保 UI 显示名称."""
        if event_type not in self._registered_types:
            self._registered_types.add(event_type)
            self._attr_event_types = list(self._registered_types)

        self._trigger_event(event_type, data)

    def _is_duplicate(self, event_id: str) -> bool:
        """查重逻辑."""
        if event_id in self._seen_event_ids:
            return True
        self._seen_event_ids.add(event_id)
        if len(self._seen_event_ids) > 1000:
            self._seen_event_ids = set(list(self._seen_event_ids)[-500:])
        return False
