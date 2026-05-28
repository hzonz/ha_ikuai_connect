"""Support for iKuai Connect select entities."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAC_MODE_SELECT, MAC_ACL_MODES, MAC_ACL_MODES_REVERSE
from .coordinator import IkuaiCoordinator

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up iKuai Connect select entities."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    
    # 注册模式选择实体
    async_add_entities([IkuaiMacModeSelect(coordinator, MAC_MODE_SELECT)])


class IkuaiMacModeSelect(CoordinatorEntity[IkuaiCoordinator], SelectEntity):
    """MAC 访问控制模式选择器实现."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IkuaiCoordinator, description: SelectEntityDescription) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.host}_mac_mode"
        self._attr_translation_key = description.translation_key
        self._attr_device_info = coordinator.security_device_info

    @property
    def current_option(self) -> str | None:
        """从协调器数据中获取当前模式."""
        # 增加容错检查
        security_data = self.coordinator.data.get("security", {})
        mode_code = security_data.get("mac_mode_code", 0)
        return MAC_ACL_MODES.get(mode_code, "blacklist")

    async def async_select_option(self, option: str) -> None:
        """更改路由器模式并立即刷新数据."""
        mode_code = MAC_ACL_MODES_REVERSE.get(option, 0)
        
        # 调用 API 执行切换
        await self.coordinator.api.set_mac_mode(mode_code)
        
        if "security" in self.coordinator.data:
            self.coordinator.data["security"]["mac_mode_code"] = mode_code

        await self.coordinator.async_request_refresh()