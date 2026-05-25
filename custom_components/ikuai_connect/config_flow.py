"""Config flow for iKuai Connect."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_TOKEN, CONF_SCAN_INTERVAL, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import IkuaiAPI
from .const import DOMAIN, CONF_TRACKER_CONFIG, CONF_ACT_BUFFER
from .helpers import extract_name_from_label

_LOGGER = logging.getLogger(__name__)

def get_login_schema(defaults: dict[str, Any] | None = None, is_reconfigure: bool = False) -> vol.Schema:
    """生成登录表单 Schema."""
    if defaults is None:
        defaults = {}
    
    schema = {}
    
    # 只有在初次安装时才显示“名称”输入框
    if not is_reconfigure:
        schema[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "主路由"))] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        )
        
    schema.update({
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "https://10.10.10.1")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN)): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    })
    return vol.Schema(schema)

class IkuaiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            token = user_input[CONF_TOKEN]
            name = user_input[CONF_NAME]

            # ---校验集成名称是否重复 ---
            current_entries = self._async_current_entries()
            for entry in current_entries:
                if entry.title == name:
                    errors[CONF_NAME] = "name_exists" # 抛出名称已存在的错误
                    break

            if not errors:
                try:
                    api = IkuaiAPI(self.hass, host, token)
                    await api.get_system_info()
                    
                    # 设置物理唯一 ID (基于 Host)
                    await self.async_set_unique_id(host.lower())
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_TOKEN: token,
                            CONF_TRACKER_CONFIG: {},
                        }
                    )
                except Exception:
                    errors["base"] = "cannot_connect"
        
        return self.async_show_form(
            step_id="user", 
            data_schema=get_login_schema(user_input), # 传入 user_input 以保留用户已填内容
            errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """处理重新配置流程."""
        errors = {}
        reconfig_entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            token = user_input[CONF_TOKEN]
            
            try:
                api = IkuaiAPI(self.hass, host, token)
                await api.get_system_info()
                
                # 2026 标准：只更新数据字典，不改变 entry.title
                return self.async_update_reload_and_abort(
                    reconfig_entry, 
                    data={
                        **reconfig_entry.data,
                        CONF_HOST: host,
                        CONF_TOKEN: token,
                    }
                )
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=get_login_schema(
                defaults={
                    CONF_HOST: reconfig_entry.data[CONF_HOST],
                    CONF_TOKEN: reconfig_entry.data[CONF_TOKEN]
                },
                is_reconfigure=True # 告诉 Schema 隐藏名称字段
            ),
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return IkuaiOptionsFlowHandler()

class IkuaiOptionsFlowHandler(config_entries.OptionsFlow):
    """优雅的选项管理界面."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """配置主界面：基础设置 + 任务跳转."""
        if user_input is not None:
            # 获取用户选择的后续动作
            next_action = user_input.pop("manage_action", "none")
            
            # 1. 立即合并并保存基础设置 (频率、缓冲)
            new_options = dict(self.config_entry.options)
            new_options.update(user_input)
            
            # 这里先不执行 create_entry，因为如果是跳转流程，我们需要带上最新的 options 状态
            self._temp_options = new_options

            if next_action == "add":
                return await self.async_step_scan()
            if next_action == "remove":
                return await self.async_step_remove()
            
            # 如果没有选择额外动作，直接保存基础设置并退出
            return self.async_create_entry(title="", data=new_options)

        # 获取当前值用于默认显示
        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, 15)
        current_buffer = self.config_entry.options.get(CONF_ACT_BUFFER, 2)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # 基础设置区
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): NumberSelector(
                    NumberSelectorConfig(min=5, max=300, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_ACT_BUFFER, default=current_buffer): NumberSelector(
                    NumberSelectorConfig(min=0, max=20, mode=NumberSelectorMode.BOX)
                ),
                # 任务操作区：使用单选或下拉
                vol.Required("manage_action", default="none"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": "none", "label": "无 (直接保存并退出)"},
                            {"value": "add", "label": "➕ 添加新的追踪终端"},
                            {"value": "remove", "label": "➖ 移除现有的追踪"}
                        ],
                        mode="list", # 使用 list 模式在 UI 上显示为漂亮的单选卡片
                    )
                ),
            })
        )

    async def async_step_scan(self, user_input=None) -> FlowResult:
        """扫描在线终端."""
        errors = {}
        coordinator = self.config_entry.runtime_data

        if user_input is not None:
            self._selected_devices = user_input.get("devices", [])
            if not self._selected_devices:
                errors["base"] = "no_devices_selected"
            else:
                return await self.async_step_configure_devices()

        try:
            res = await coordinator.api.get_lan_devices()
            lan_list = res.get("data", [])
            # 兼容：从最新的临时配置或已有配置中读取
            existing_trackers = self._temp_options.get(CONF_TRACKER_CONFIG, {})
            
            self._discovered_map = {}
            for item in lan_list:
                mac = item.get("mac", "").lower()
                if not mac or mac in existing_trackers: continue
                
                ip = item.get("ip_addr", "")
                comment = extract_name_from_label(item.get("comment", "")) or item.get("termname", "")
                self._discovered_map[mac] = f"{mac} | {ip} ({comment})"

            if not self._discovered_map:
                errors["base"] = "no_new_devices_found"
        except Exception as err:
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema({
                vol.Optional("devices"): cv.multi_select(self._discovered_map)
            }),
            errors=errors
        )

    async def async_step_configure_devices(self, user_input=None) -> FlowResult:
        """保存并退出."""
        if user_input is not None:
            tracker_config = dict(self._temp_options.get(CONF_TRACKER_CONFIG, {}))

            for mac in self._selected_devices:
                safe_key = mac.replace(":", "_")
                tracker_config[mac.lower()] = {
                    "name": user_input.get(f"name_{safe_key}"),
                    "buffer": user_input.get(f"buffer_{safe_key}", 2)
                }
            
            self._temp_options[CONF_TRACKER_CONFIG] = tracker_config
            return self.async_create_entry(title="", data=self._temp_options)

        fields = {}
        for mac in self._selected_devices:
            safe_key = mac.replace(":", "_")
            label = self._discovered_map.get(mac, mac)
            default_name = label.split("(")[-1].replace(")", "") if "(" in label else f"Client {mac[-5:]}"
            fields[vol.Required(f"name_{safe_key}", default=default_name)] = str
            fields[vol.Optional(f"buffer_{safe_key}", default=2)] = int

        return self.async_show_form(step_id="configure_devices", data_schema=vol.Schema(fields))

    async def async_step_remove(self, user_input=None) -> FlowResult:
        """移除追踪."""
        tracker_config = dict(self._temp_options.get(CONF_TRACKER_CONFIG, {}))

        if user_input is not None:
            for mac in user_input.get("devices_to_remove", []):
                tracker_config.pop(mac, None)
            self._temp_options[CONF_TRACKER_CONFIG] = tracker_config
            return self.async_create_entry(title="", data=self._temp_options)

        options = {mac: f"{conf.get('name', mac)} ({mac})" for mac, conf in tracker_config.items()}
        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema({
                vol.Optional("devices_to_remove"): cv.multi_select(options)
            })
        )