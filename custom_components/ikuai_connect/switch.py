"""Support for iKuai Connect dynamic MAC ACL switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import translation

from .const import DOMAIN
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iKuai MAC switches."""
    coordinator: IkuaiCoordinator = entry.runtime_data
    
    # 记录已经添加到 HA 的实体 Unique ID，防止重复添加
    added_unique_ids: set[str] = set()

    @callback
    def _async_check_entities() -> None:
        """检查并添加新规则实体的回调函数."""
        rules_data = coordinator.data.get("security", {}).get("mac_rules", {})
        
        # 1. 检查是否存在新规则
        new_entities = []
        for rid, rule in rules_data.items():
            # 构造 Unique ID (必须与类内部一致)
            uid = f"{coordinator.host}_mac_rule_{rid}"
            if uid not in added_unique_ids:
                new_entities.append(IkuaiMacRuleSwitch(coordinator, rid))
                added_unique_ids.add(uid)
        
        if new_entities:
            async_add_entities(new_entities)

        # 2. 清理已在爱快后台删除的规则实体 (幽灵清理)
        ent_reg = er.async_get(hass)
        entity_entries = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        for entity in entity_entries:
            if "mac_rule_" in entity.unique_id and entity.unique_id not in [
                f"{coordinator.host}_mac_rule_{rid}" for rid in rules_data
            ]:
                _LOGGER.info("检测到 MAC 规则已删除，注销实体: %s", entity.entity_id)
                ent_reg.async_remove(entity.entity_id)
                if entity.unique_id in added_unique_ids:
                    added_unique_ids.remove(entity.unique_id)

    # 初次加载执行一次检查
    _async_check_entities()

    # 每当 coordinator.async_set_updated_data 被调用，此监听器就会触发
    entry.async_on_unload(coordinator.async_add_listener(_async_check_entities))


class IkuaiMacRuleSwitch(CoordinatorEntity[IkuaiCoordinator], SwitchEntity):
    """动态 MAC 规则开关类."""

    _attr_has_entity_name = True
    _attr_translation_key = "mac_rule"

    def __init__(self, coordinator: IkuaiCoordinator, rule_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._rule_id = str(rule_id)
        
        # 唯一 ID
        self._attr_unique_id = f"{coordinator.host}_mac_rule_{self._rule_id}"
        self._attr_device_info = coordinator.security_device_info
        self._labels = {
            "every_week": "Every {weekdays}",
            "specific_date": "Specific Date",
            "all_day": "All Day",
            "permanent": "Permanent"
        }

    async def async_added_to_hass(self) -> None:
        """实体被添加时，异步加载翻译好的标签."""
        await super().async_added_to_hass()
        
        # 获取当前系统语言
        lang = self.hass.config.language
        # 抓取当前集成下的翻译
        translations = await translation.async_get_translations(
            self.hass, lang, "entity", [DOMAIN]
        )
        
        # 匹配 JSON 路径并更新本地标签
        base_path = f"component.{DOMAIN}.entity.switch.mac_rule.state_attributes"
        
        mapping = {
            "every_week": f"{base_path}.schedule.state.every_week",
            "specific_date": f"{base_path}.schedule.state.specific_date",
            "all_day": f"{base_path}.schedule.state.all_day",
            "permanent": f"{base_path}.expires.state.permanent",
        }
        
        for key, path in mapping.items():
            if path in translations:
                self._labels[key] = translations[path]


    @property
    def name(self) -> str:
        """从数据中获取 tagname."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        return rule.get("tagname") or f"MAC Rule {self._rule_id}"

    @property
    def is_on(self) -> bool:
        """判断规则是否启用."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        return rule.get("enabled") == "yes"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """启用规则."""
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """禁用规则."""
        await self.coordinator.api.toggle_mac_rule(int(self._rule_id), False)
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """返回格式化后的属性."""
        rule = self.coordinator.data.get("security", {}).get("mac_rules", {}).get(self._rule_id, {})
        
        # 1. 处理时间计划
        time_rules = rule.get("time", {}).get("custom", [])
        formatted_times = []
        
        for t in time_rules:
            if t.get("type") == "weekly":
                # 使用翻译好的“每周”模板，填入数字
                formatted_times.append(
                    self._labels["every_week"].format(weekdays=t.get('weekdays'))
                )
            else:
                formatted_times.append(
                    f"{self._labels['specific_date']} {t.get('start_time')}-{t.get('end_time')}"
                )

        # 2. 处理过期逻辑
        expires_val = rule.get("expires", 0)
        expires_label = self._labels["permanent"] if expires_val == 0 else expires_val

        return {
            "mac_address": rule.get("mac"),
            "terminal_name": rule.get("termname"),
            "comment": rule.get("comment"),
            "schedule": "; ".join(formatted_times) if formatted_times else self._labels["all_day"],
            "expires": expires_label,
            "rule_id": self._rule_id
        }