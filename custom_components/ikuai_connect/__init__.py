"""ikuai connect 集成入口."""
from __future__ import annotations

from datetime import timedelta
import logging
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_TOKEN, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
import homeassistant.util.dt as dt_util

from .api import IkuaiAPI
from .const import DOMAIN, PLATFORMS, DEFAULT_SCAN_INTERVAL
from .coordinator import IkuaiCoordinator

_LOGGER = logging.getLogger(__name__)

type IkuaiConfigEntry = ConfigEntry[IkuaiCoordinator]

async def async_setup_entry(hass: HomeAssistant, entry: IkuaiConfigEntry) -> bool:
    """设置集成入口."""
    # 实例 API
    api = IkuaiAPI(hass, entry.data[CONF_HOST], entry.data[CONF_TOKEN])
    
    # 实例协调器
    coordinator = IkuaiCoordinator(
        hass, 
        api, 
        entry.data[CONF_HOST], 
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    coordinator.config_entry = entry

    # 强制执行第一次成功刷新，确保平台加载时有数据
    await coordinator.async_config_entry_first_refresh()

    # 存入 runtime_data，供平台访问和服务调用使用
    entry.runtime_data = coordinator

    # ---获取流量排行 (优化单位为 MB) ---
    async def async_get_traffic_ranking(call) -> ServiceResponse:
        api = coordinator.api
        res = await api.get_client_traffic_summary()
        return {
            "total_flow_mb": round(res.get("terminal_total_flow", 0) / 1024 / 1024, 2),
            "devices": [
                {
                    "name": d.get("comment") or d.get("termname") or d.get("mac"),
                    "ip": d.get("ip_addr"),
                    "mac": d.get("mac"),
                    "total_mb": round(d.get("sum_total", 0) / 1024 / 1024, 2),
                    "up_mb": round(d.get("sum_total_up", 0) / 1024 / 1024, 2),
                    "down_mb": round(d.get("sum_total_down", 0) / 1024 / 1024, 2),
                }
                for d in res.get("terminal", [])
            ]
        }

    # ---获取特定设备的协议分布 (响应式服务) ---
    async def async_get_protocol_stats(call) -> ServiceResponse:
        mac = call.data["mac"].lower().replace("-", ":")
        ip = call.data.get("ip")
        
        # 如果用户没传 IP，我们尝试从当前的协调器缓存中自动寻找该 MAC 对应的 IP
        if not ip:
            client_info = coordinator.data.get("clients", {}).get(mac)
            if client_info:
                ip = client_info.get("ip_addr")
        
        if not ip:
            return {"error": "无法获取该设备的IP地址，请手动输入IP"}

        res = await coordinator.api.get_client_protocol_stats(mac, ip)
        
        # 整理返回协议列表
        protocol_data = [
            {
                "name": p.get("proto_name"),
                "total_mb": round(p.get("total", 0) / 1024 / 1024, 2)
            }
            for p in res.get("data", [])
            if p.get("total", 0) > 0 # 过滤掉没流量的协议
        ]
        
        return {
            "mac": mac,
            "ip": ip,
            "protocols": sorted(protocol_data, key=lambda x: x["total_mb"], reverse=True)
        }

    # --- 注册服务：查询离线历史 ---
    async def async_get_offline_history(call) -> ServiceResponse:

        res = await coordinator.api.get_offline_history()
        
        raw_history = res.get("offline_data", [])
        history_list = []
        
        for d in raw_history:
            # 提取名称 (应用优先级逻辑)
            name = (
                d.get("termname") 
                or d.get("client_model") 
                or d.get("comment") 
                or f"Client {d.get('mac', '')[-5:]}"
            )
            
            # 计算流量 (MB)
            total_bytes = int(d.get("total_up", 0)) + int(d.get("total_down", 0))
            total_mb = round(total_bytes / 1048576, 2)
            
            # 转换下线时间
            logout_ts = d.get("logout_time", 0)
            offline_time = dt_util.as_local(
                dt_util.utc_from_timestamp(logout_ts)
            ).strftime("%Y-%m-%d %H:%M:%S") if logout_ts else "Unknown"

            history_list.append({
                "name": name,
                "mac": d.get("mac"),
                "ip": d.get("ip_addr"),
                "offline_at": offline_time,
                "total_usage_mb": total_mb,
                "client_type": d.get("client_type"),
                "vendor": d.get("client_vendor")
            })
            
        return {"history": history_list}

    # 注册服务
    hass.services.async_register(
        DOMAIN, "get_traffic_ranking", async_get_traffic_ranking,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "get_protocol_stats", async_get_protocol_stats,
        supports_response=SupportsResponse.ONLY,
    )
    
    hass.services.async_register(
        DOMAIN, "get_offline_history", async_get_offline_history,
        supports_response=SupportsResponse.ONLY,
    )

    # ---注册服务：添加 MAC 访问控制规则 ---
    async def async_add_mac_rule(call) -> None:
        mac = call.data["mac"].lower().replace("-", ":")
        payload = {
            "mac": mac,
            "enabled": "yes",
            "tagname": call.data.get("tagname", f"HA_{mac[-5:]}"),
            "comment": call.data.get("comment", "Added by HA"),
            "expires": call.data.get("expires", 0),
            "strategy": "day", "cycle_time": "all", "time": "00:00-23:59"
        }
        
        await coordinator.api.add_mac_rule(payload)
        # 立即刷新，让 switch.py 动态生成新开关
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, "add_mac_rule", async_add_mac_rule,
        schema=vol.Schema({
            vol.Required("mac"): cv.string,
            vol.Optional("tagname"): cv.string,
            vol.Optional("comment"): cv.string,
            vol.Optional("expires"): cv.positive_int,
        })
    )

    # ---注册服务：删除 MAC 访问控制规则 ---
    async def async_delete_mac_rule(call) -> None:
        """根据 ID 彻底删除规则."""
        rule_id = call.data["rule_id"]
        await coordinator.api.delete_mac_rule(rule_id)
        # 立即刷新，触发 switch.py 的自动清理逻辑，删除对应实体
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, "delete_mac_rule", async_delete_mac_rule,
        schema=vol.Schema({
            vol.Required("rule_id"): cv.positive_int,
        })
    )

    # 转发平台
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 监听选项更新
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def update_listener(hass: HomeAssistant, entry: IkuaiConfigEntry) -> None:
    """当 Options 或 Data 变更时重载."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: IkuaiConfigEntry) -> bool:
    """卸载集成."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)