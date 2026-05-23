"""Support for iKuai Connect select entities."""
from __future__ import annotations
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, MAC_MODE_SELECT, MAC_ACL_MODES, MAC_ACL_MODES_REVERSE

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([IkuaiMacModeSelect(coordinator, MAC_MODE_SELECT)])

class IkuaiMacModeSelect(CoordinatorEntity, SelectEntity):
    """MAC 访问控制模式选择器."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_mac_mode"
        self._attr_device_info = coordinator.security_device_info

    @property
    def current_option(self) -> str:
        mode_code = self.coordinator.data.get("security", {}).get("mac_mode_code", 0)
        return MAC_ACL_MODES.get(mode_code, "blacklist")

    async def async_select_option(self, option: str) -> None:
        """更改路由器模式."""
        mode_code = MAC_ACL_MODES_REVERSE.get(option, 0)
        await self.coordinator.api.set_mac_mode(mode_code)
        await self.coordinator.async_request_refresh()