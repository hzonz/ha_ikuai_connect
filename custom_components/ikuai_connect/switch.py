"""Support for iKuai Connect dynamic switches."""
from __future__ import annotations
import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    
    # 1. 自动清理已删除的规则
    rules_data = coordinator.data.get("security", {}).get("mac_rules", {})
    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    
    for entity in entries:
        if "mac_rule_" in entity.unique_id:
            rule_id = entity.unique_id.split("mac_rule_")[-1].split("_")[0]
            if rule_id not in rules_data:
                ent_reg.async_remove(entity.entity_id)

    # 2. 添加当前规则
    async_add_entities(
        [IkuaiMacRuleSwitch(coordinator, rid) for rid in rules_data],
        True
    )

class IkuaiMacRuleSwitch(CoordinatorEntity, SwitchEntity):
    """动态 MAC 规则开关."""
    _attr_has_entity_name = True

    def __init__(self, coordinator, rule_id):
        super().__init__(coordinator)
        self._rule_id = str(rule_id)
        # 获取规则详情
        rule = coordinator.data["security"]["mac_rules"].get(self._rule_id, {})
        self._attr_name = f"MAC过滤: {rule.get('tagname')} ({rule.get('mac')})"
        self._attr_unique_id = f"{coordinator.host}_mac_rule_{self._rule_id}"
        self._attr_device_info = coordinator.security_device_info

    @property
    def is_on(self) -> bool:
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        return rule.get("enabled") == "yes"

    async def async_turn_on(self, **kwargs):
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), False)
        await self.coordinator.async_request_refresh()