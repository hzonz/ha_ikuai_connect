"""Support for iKuai Connect buttons."""
from __future__ import annotations

import asyncio
import logging
from typing import Final

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, BUTTON_TYPES, IkuaiButtonEntityDescription
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai Connect buttons from a config entry."""
    coordinator: IkuaiCoordinator = entry.runtime_data

    # 批量注册所有在 const.py 中定义的按钮
    async_add_entities(
        IkuaiButton(coordinator, description)
        for description in BUTTON_TYPES
    )


class IkuaiButton(CoordinatorEntity[IkuaiCoordinator], ButtonEntity):
    """iKuai 统一按钮类 (支持主设备与子设备)."""

    entity_description: IkuaiButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self, 
        coordinator: IkuaiCoordinator, 
        description: IkuaiButtonEntityDescription
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.entity_description = description
        
        # 构造唯一 ID
        host_id = coordinator.host.split("//")[-1].replace(".", "_").replace(":", "_")
        self._attr_unique_id = f"{DOMAIN}_btn_{description.key}_{host_id}"
        self._attr_translation_key = description.translation_key
        
        # 【核心逻辑】：根据按钮类型决定挂载到哪个设备
        if description.action_type == "reboot_main":
            # 重启按钮挂载在主设备 (Router)
            self._attr_device_info = coordinator.device_info
        else:
            # 升级与备份按钮挂载在子设备 (Maintenance)
            self._attr_device_info = coordinator.maintenance_device_info

    async def async_press(self) -> None:
        """根据 action_type 执行对应 API 动作."""
        action = self.entity_description.action_type
        api = self.coordinator.api

        try:
            if action == "reboot_main":
                await api.trigger_immediate_reboot()
                self.hass.components.persistent_notification.async_create(
                    "重启指令已下发。爱快将在 1 分钟内执行重启。",
                    title="iKuai Connect",
                    notification_id="ikuai_reboot_alert"
                )
            
            elif action == "check_upgrade":
                await api.check_upgrade()
                _LOGGER.info("iKuai: 正在向云端检测新版本...")
            
            elif action == "start_upgrade":
                await api.start_upgrade()
                _LOGGER.warning("iKuai: 已触发系统升级指令")
            
            elif action == "backup":
                await api.trigger_backup()
                _LOGGER.info("iKuai: 正在创建系统备份...")

            # 动作完成后处理
            # 对于升级和备份，给 API 2 秒反应时间再刷新数据
            if action in ["start_upgrade", "backup", "check_upgrade"]:
                await asyncio.sleep(2)
                await self.coordinator.async_request_refresh()

        except Exception as err:
            _LOGGER.error("iKuai 按钮动作 [%s] 执行失败: %s", action, err)