"""Official OpenAPI Client for iKuai Connect with Detailed Documentation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import datetime
from typing import Any

from aiohttp import ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# 定义缓存时长（秒）
CACHE_TTL = {
    "/api/v4.0/monitoring/system": 0,               # 系统负载：实时
    "/api/v4.0/monitoring/clients-online": 10,       # 终端列表：10秒
    "/api/v4.0/monitoring/wireless-statistics": 30,  # 无线统计：30秒
    "/api/v4.0/monitoring/wireless-score": 60,       # 无线评分：1分钟
    "/api/v4.0/log/message-center?limit=5": 60,      # 消息中心：1分钟
    "/api/v4.0/log/terminal-presence?limit=5": 30,   # 上下线日志：30秒
    "/api/v4.0/monitoring/interfaces-status": 5,     # 线路状态：5秒
    "/api/v4.0/monitoring/interfaces-config": 3600,  # 线路配置：1小时
    "/api/v4.0/monitoring/interfaces-traffic-v6": 10, # IPv6流量：10秒
    "/api/v4.0/system/backup": 300,                  # 备份列表：5分钟
    "/api/v4.0/system/upgrade": 3600,                # 固件信息：1小时
    "/api/v4.0/system/upgrade:status": 0,            # 升级进度：实时
    "/api/v4.0/system/disks": 3600,                  # 磁盘信息：1小时
    "/api/v4.0/security/mac-mode": 60,               # MAC模式：1分钟
    "/api/v4.0/security/mac-rules?limit=100": 60,    # MAC规则：1分钟
}

class IkuaiAPI:
    """iKuai OpenAPI 异步客户端."""

    def __init__(self, hass: HomeAssistant, host: str, token: str) -> None:
        self.host = host.rstrip("/")
        self.token = token
        self._session: ClientSession = async_get_clientsession(hass)
        self._semaphore = asyncio.Semaphore(2)
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _make_request(self, method: str, endpoint: str, json_data: dict | None = None) -> dict[str, Any]:
        """统一鉴权请求封装（含404处理、非法JSON修复、缓存控制）."""
        now = time.time()
        if method == "GET" and endpoint in self._cache:
            last_time, cached_data = self._cache[endpoint]
            if now - last_time < CACHE_TTL.get(endpoint, 0):
                return cached_data

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        async with self._semaphore:
            try:
                async with asyncio.timeout(10):
                    async with self._session.request(
                        method, f"{self.host}{endpoint}", headers=headers, json=json_data, ssl=False
                    ) as response:
                        if response.status == 404: return {}
                        if response.status in (401, 403):
                            _LOGGER.error("iKuai API 鉴权失败 %s: %s", response.status, endpoint)
                            raise Exception(f"Auth Error: {response.status}")
                        
                        response.raise_for_status()
                        raw_text = await response.text()
                        if '"data":timeout' in raw_text:
                            raw_text = raw_text.replace('"data":timeout', '"data":[]')
                        
                        data = json.loads(raw_text, strict=False)
                        results = data.get("results", {})
                        if method == "GET" and CACHE_TTL.get(endpoint, 0) > 0:
                            self._cache[endpoint] = (now, results)
                        return results
            except Exception as err:
                _LOGGER.debug("请求异常 %s: %s", endpoint, err)
                if endpoint in self._cache: return self._cache[endpoint][1]
                raise

    # --- 基础监控类 (System Monitoring) ---

    async def get_system_info(self) -> dict[str, Any]:
        """
        获取系统实时状态 (/api/v4.0/monitoring/system)
        返回字段说明:
        - sysinfo.cpu: [核心平均, 核心1, ...] (str 数组, 带%)
        - sysinfo.memory: {total, available, free, used(str)}
        - sysinfo.uptime: 运行秒数 (int)
        - sysinfo.cputemp: [温度1, ...] (int 数组)
        - sysinfo.verinfo: {version, verstring, arch, sysbit}
        - sysinfo.online_user: {count, count_2g, count_5g, count_wired, count_wireless}
        - sysinfo.stream: {upload, download, total_up, total_down, connect_num}
        """
        return await self._make_request("GET", "/api/v4.0/monitoring/system")

    async def get_lan_devices(self) -> dict[str, Any]:
        """
        获取IPv4在线终端统计 (/api/v4.0/monitoring/clients-online)
        返回字段说明:
        - data: [ {mac, ip_addr, upload, download, total_up, total_down, termname, comment, client_vendor, interface} ]
        """
        return await self._make_request("GET", "/api/v4.0/monitoring/clients-online")

    async def get_wifi_stats(self) -> dict[str, Any]:
        """获取无线AP统计 (/api/v4.0/monitoring/wireless-statistics)"""
        return await self._make_request("GET", "/api/v4.0/monitoring/wireless-statistics")

    async def get_wifi_score(self) -> dict[str, Any]:
        """获取无线网络评分 (/api/v4.0/monitoring/wireless-score)"""
        return await self._make_request("GET", "/api/v4.0/monitoring/wireless-score")

    # --- 日志与事件类 (Logs & Events) ---

    async def get_message_center(self) -> dict[str, Any]:
        """获取消息中心列表 (/api/v4.0/log/message-center)"""
        return await self._make_request("GET", "/api/v4.0/log/message-center?limit=5")

    async def get_offline_history(self) -> dict[str, Any]:
        """获取终端上下线日志 (/api/v4.0/log/terminal-presence)"""
        return await self._make_request("GET", "/api/v4.0/log/terminal-presence?limit=20")

    # --- 接口与流量类 (Network Interfaces) ---

    async def get_iface_status(self) -> dict[str, Any]:
        """
        获取线路状态监控 (/api/v4.0/monitoring/interfaces-status)
        返回字段说明:
        - iface_check: [ {interface, parent_interface, ip_addr, result, internet} ]
        - iface_stream: [ {interface, upload, download, total_up, total_down, ip_addr} ]
        """
        return await self._make_request("GET", "/api/v4.0/monitoring/interfaces-status")

    async def get_iface_config(self) -> dict[str, Any]:
        """获取内外网接口配置 (/api/v4.0/monitoring/interfaces-config)"""
        return await self._make_request("GET", "/api/v4.0/monitoring/interfaces-config")

    async def get_v6_traffic(self) -> dict[str, Any]:
        """获取IPv6线路详情 (/api/v4.0/monitoring/interfaces-traffic-v6)"""
        return await self._make_request("GET", "/api/v4.0/monitoring/interfaces-traffic-v6")

    # --- 存储与维护类 (Storage & Maintenance) ---

    async def get_disks(self) -> dict[str, Any]:
        """
        获取系统磁盘信息 (/api/v4.0/system/disks)
        返回字段说明:
        - data: [ {disk, model, type, size, system, partition: [ {name, mounted: {mt_total, mt_used, mt_uses, mt_name, mt_purpose}} ]} ]
        """
        return await self._make_request("GET", "/api/v4.0/system/disks")

    async def get_backup_list(self) -> dict[str, Any]:
        """获取备份信息 (/api/v4.0/system/backup)"""
        return await self._make_request("GET", "/api/v4.0/system/backup")

    async def get_upgrade_info(self) -> dict[str, Any]:
        """获取系统版本及更新详情 (/api/v4.0/system/upgrade)"""
        return await self._make_request("GET", "/api/v4.0/system/upgrade")

    async def get_upgrade_status(self) -> dict[str, Any]:
        """获取固件升级进度状态 (/api/v4.0/system/upgrade:status)"""
        return await self._make_request("GET", "/api/v4.0/system/upgrade:status")

    # --- 服务支持查询接口 (Service Response Support) ---

    async def get_client_traffic_summary(self) -> dict[str, Any]:
        """
        获取终端当日流量统计排行 (/api/v4.0/monitoring/clients-traffic-summary)
        用于服务 ikuai_connect.get_traffic_ranking
        """
        return await self._make_request("GET", "/api/v4.0/monitoring/clients-traffic-summary?limit=100")

    async def get_client_protocol_stats(self, mac: str, ip: str) -> dict[str, Any]:
        """获取指定终端的协议分类流量统计 (/api/v4.0/monitoring/clients/protocols)"""
        endpoint = f"/api/v4.0/monitoring/clients/protocols?mac={mac}&ip={ip}"
        return await self._make_request("GET", endpoint)

    # --- 安全管理类 (Security) ---

    async def get_mac_mode(self) -> dict[str, Any]:
        """获取全局MAC访问控制模式 (/api/v4.0/security/mac-mode)"""
        return await self._make_request("GET", "/api/v4.0/security/mac-mode")

    async def get_mac_rules(self) -> dict[str, Any]:
        """获取MAC黑白名单策略列表 (/api/v4.0/security/mac-rules)"""
        return await self._make_request("GET", "/api/v4.0/security/mac-rules?limit=100")

    # --- 执行动作 (Control Actions) ---

    async def trigger_backup(self) -> bool:
        """立即执行备份 (POST)"""
        await self._make_request("POST", "/api/v4.0/system/backup")
        self._cache.pop("/api/v4.0/system/backup", None)
        return True

    async def check_upgrade(self) -> bool:
        """发起版本检测 (POST)"""
        await self._make_request("POST", "/api/v4.0/system/upgrade:check")
        self._cache.pop("/api/v4.0/system/upgrade", None)
        return True

    async def start_upgrade(self) -> bool:
        """立即升级 (POST)"""
        return await self._make_request("POST", "/api/v4.0/system/upgrade:start", json_data={"type": "system"})

    async def trigger_immediate_reboot(self) -> bool:
        """创建一次性计划实现1分钟内重启."""
        now = datetime.datetime.now()
        reboot_time = now + datetime.timedelta(minutes=1)
        payload = {
            "enabled": "yes", "event": "reboot", "strategy": "one",
            "cycle_time": reboot_time.strftime("%Y-%m-%d"),
            "time": reboot_time.strftime("%H:%M"),
            "tagname": "HA_Reboot", "comment": "Triggered by HA"
        }
        await self._make_request("POST", "/api/v4.0/system/reboot-schedules", json_data=payload)
        return True

    async def set_mac_mode(self, mode_code: int) -> bool:
        """设置黑白名单模式 (PUT)"""
        await self._make_request("PUT", "/api/v4.0/security/mac-mode", json_data={"acl_mac": mode_code})
        self._cache.pop("/api/v4.0/security/mac-mode", None)
        return True

    async def toggle_mac_rule(self, rule_id: int, enabled: bool) -> bool:
        """开关指定MAC规则 (PATCH)"""
        payload = {"enabled": "yes" if enabled else "no"}
        await self._make_request("PATCH", f"/api/v4.0/security/mac-rules/{rule_id}", json_data=payload)
        self._cache.pop("/api/v4.0/security/mac-rules?limit=100", None)
        return True

    async def add_mac_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建MAC规则 (POST)"""
        res = await self._make_request("POST", "/api/v4.0/security/mac-rules", json_data=payload)
        self._cache.pop("/api/v4.0/security/mac-rules?limit=100", None)
        return res

    async def delete_mac_rule(self, rule_id: int) -> bool:
        """彻底删除MAC规则 (DELETE)"""
        await self._make_request("DELETE", f"/api/v4.0/security/mac-rules/{rule_id}")
        self._cache.pop("/api/v4.0/security/mac-rules?limit=100", None)
        return True

    # --- 核心聚合抓取 (Coordinator 唯一调用入口) ---

    async def get_all_data(self) -> list[Any]:
        """
        并发抓取 15 个端点。
        注意：此处的顺序决定了 coordinator.py 的解包顺序，请勿随意变动！
        """
        return await asyncio.gather(
            self.get_system_info(),                                              # 0: sys_res
            self.get_lan_devices(),                                              # 1: clients_res
            self.get_wifi_stats(),                                               # 2: wifi_stats_res
            self.get_wifi_score(),                                               # 3: wifi_score_res
            self.get_message_center(),                                           # 4: msg_center_res
            self.get_offline_history(),                                          # 5: presence_log_res
            self.get_iface_status(),                                             # 6: iface_status_res
            self.get_iface_config(),                                             # 7: iface_config_res
            self.get_v6_traffic(),                                               # 8: v6_res
            self.get_backup_list(),                                              # 9: backup_res
            self.get_upgrade_info(),                                             # 10: up_info_res
            self.get_upgrade_status(),                                           # 11: up_status_res
            self.get_disks(),                                                    # 12: disks_res
            self.get_mac_mode(),                                                 # 13: mac_mode_res
            self.get_mac_rules(),                                                # 14: mac_rules_res
            return_exceptions=True
        )