"""ikuai 配置流实现."""
from __future__ import annotations

import logging
import re
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_TOKEN, CONF_SCAN_INTERVAL, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import translation  # 引入翻译模块
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import IkuaiAPI
from .const import (
    DOMAIN,
    CONF_TRACKER_CONFIG,
    CONF_OFFLINE_GRACE_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_OFFLINE_GRACE_PERIOD,
)

from .helpers import extract_name_from_label

_LOGGER = logging.getLogger(__name__)


class IkuaiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """处理初次配置和重新配置."""
    VERSION = 1

    async def _get_localized_default_name(self) -> str:
        """从翻译文件中动态获取默认设备名称."""
        lang = self.hass.config.language
        translations = await translation.async_get_translations(
            self.hass, lang, "config", [DOMAIN]
        )
        return translations.get(
            f"component.{DOMAIN}.config.default_name", 
            "iKuai Connect" # 如果找不到翻译时的英文保底名称
        )

    async def _get_login_schema(self, defaults: dict[str, Any] | None = None, is_reconfigure: bool = False) -> vol.Schema:
        """异步生成带动态翻译默认值的登录 Schema."""
        if defaults is None: 
            defaults = {}
        
        schema = {}
        
        # 只有在初次安装时才显示“名称”输入框
        if not is_reconfigure:
            # 动态获取默认名称
            default_name = defaults.get(CONF_NAME)
            if not default_name:
                default_name = await self._get_localized_default_name()
                
            schema[vol.Required(CONF_NAME, default=default_name)] = TextSelector(
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


    async def async_step_user(self, user_input=None) -> FlowResult:
        """初次安装步骤."""
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
        
        # 异步调用动态 Schema
        schema = await self._get_login_schema(user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

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

        # 异步调用动态 Schema，并标记为 reconfigure 以隐藏名称字段
        schema = await self._get_login_schema(
            defaults={
                CONF_HOST: reconfig_entry.data[CONF_HOST],
                CONF_TOKEN: reconfig_entry.data[CONF_TOKEN]
            },
            is_reconfigure=True
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return IkuaiOptionsFlowHandler()

class IkuaiOptionsFlowHandler(config_entries.OptionsFlow):
    """优雅的选项管理界面."""

    def __init__(self) -> None:
        self._selected_devices: list[str] = []
        self._discovered_map: dict[str, str] = {}
        self._temp_options: dict[str, Any] = {} # 声明一个持久存储

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """配置主界面：基础设置 + 任务跳转."""
        
        # 动态初始化实例变量，防止在返回修改时报错
        self._selected_devices = getattr(self, "_selected_devices", [])
        self._discovered_map = getattr(self, "_discovered_map", {})
        
        if not self._temp_options:
            self._temp_options = dict(self.config_entry.options)
        if user_input is not None:
            next_action = user_input.get("manage_action", "none")
            self._temp_options.update({
                CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                CONF_OFFLINE_GRACE_PERIOD: user_input[CONF_OFFLINE_GRACE_PERIOD]
            })
            # 根据跳转指令进入不同页面
            if next_action == "add":
                return await self.async_step_scan()
            if next_action == "remove":
                return await self.async_step_remove()
            # 如果没有选择额外动作 (none)，直接保存当前合并后的 _temp_options 并退出
            return self.async_create_entry(title="", data=self._temp_options)

        # 获取当前值用于默认显示
        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_period = self.config_entry.options.get(CONF_OFFLINE_GRACE_PERIOD, DEFAULT_OFFLINE_GRACE_PERIOD)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # 基础设置区
                vol.Required(CONF_SCAN_INTERVAL, default=current_interval): NumberSelector(
                    NumberSelectorConfig(min=5, max=300, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_OFFLINE_GRACE_PERIOD, default=current_period): NumberSelector(
                    NumberSelectorConfig(min=30, max=1800, mode=NumberSelectorMode.BOX)
                ),
                # 任务操作区：使用单选或下拉
                vol.Required("manage_action", default="none"): SelectSelector(
                    SelectSelectorConfig(
                        options=["none", "add", "remove"],
                        translation_key="manage_action",
                        mode=SelectSelectorMode.LIST,
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
            existing_trackers = self.config_entry.options.get(CONF_TRACKER_CONFIG, {})
            
            self._discovered_map = {}
            for item in lan_list:
                mac = item.get("mac", "").lower()
                if not mac or mac in existing_trackers: continue
                
                ip = item.get("ip_addr", "")
                termname = item.get("termname", "")
                model = item.get("client_model", "")
                comment = extract_name_from_label(item.get("comment", ""))
                name_priority = termname or model or comment
                # 构造标准格式，供下一步正则提取
                label = f"{mac} | {ip} ({name_priority})" if name_priority else f"{mac} | {ip}"
                self._discovered_map[mac] = label

            if not self._discovered_map:
                errors["base"] = "no_new_devices_found"
        except Exception as err:
            _LOGGER.error("Scan error: %s", err)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema({
                vol.Optional("devices"): cv.multi_select(self._discovered_map)
            }),
            errors=errors
        )

    async def async_step_configure_devices(self, user_input=None) -> FlowResult:
        """迭代配置每一个选中的设备，保持 Key 的纯净."""
        # 检查是否还有待处理的设备
        if not self._selected_devices:
            # 全部配完，保存最终的 _temp_options
            return self.async_create_entry(title="", data=self._temp_options)

        current_mac = self._selected_devices[0]

        # 处理当前页面的提交
        if user_input is not None:
            # 确保初始化并追加，而不是覆盖
            tracker_config = dict(self._temp_options.get(CONF_TRACKER_CONFIG, {}))
            tracker_config[current_mac.lower()] = {
                "name": user_input[CONF_NAME],
                "buffer": user_input[CONF_OFFLINE_GRACE_PERIOD]
            }
            self._temp_options[CONF_TRACKER_CONFIG] = tracker_config            
            # 处理完一个，移除一个
            self._selected_devices.pop(0)
            
            # 显式传入 user_input=None，强制下一轮显示表单
            return await self.async_step_configure_devices(user_input=None)

        # 准备表单显示逻辑
        label_info = self._discovered_map.get(current_mac, "")
        
        # 提取终端名称
        name_match = re.search(r'\((.*?)\)', label_info)
        
        if name_match and name_match.group(1).strip():
            default_name = name_match.group(1).strip()
        else:
            # 2. 保底逻辑：如果所有字段都为空，使用 MAC 末尾
            default_name = f"Client {current_mac.replace(':', '')[-4:]}"

        return self.async_show_form(
            step_id="configure_devices",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=default_name): str,
                vol.Required(CONF_OFFLINE_GRACE_PERIOD, default=DEFAULT_OFFLINE_GRACE_PERIOD): NumberSelector(
                    NumberSelectorConfig(min=30, max=3600, unit_of_measurement="s", mode=NumberSelectorMode.BOX)
                ),
            }),
            description_placeholders={
                "device": f"{default_name} ({current_mac})",
                "remaining": str(len(self._selected_devices))
            }
        )

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