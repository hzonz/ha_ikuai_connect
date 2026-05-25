"""Data Coordinator for iKuai Connect."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class IkuaiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """处理 OpenAPI 数据清洗."""

    def __init__(self, hass, api, host, interval):
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_{host}",
            update_interval=timedelta(seconds=interval),
        )
        self.api = api
        self.host = host
        self.last_msg_id = None
        self.last_presence_id = None

    async def _async_update_data(self) -> dict[str, Any]:
        """抓取并清洗数据."""
        try:
            # 异步并发抓取所有端点的数据
            results = await self.api.get_all_data()
            
            # 任务预检逻辑
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    # 核心任务：0:系统信息, 1:终端监控, 6:接口实时状态, 7:接口物理配置
                    # 这些任务失败意味着基础数据链断裂，必须中止更新
                    if i in [0, 1, 6, 7]:
                        _LOGGER.error(
                            "iKuai 核心监控任务 %s (Critical) 执行失败，本次数据更新已中止: %s", 
                            i, res
                        )
                        raise res
                    
                    # 可选任务：2,3:无线统计/评分, 4:消息中心, 5:上下线日志, 
                    # 8:IPv6流量, 9:备份, 10,11:升级, 12:磁盘, 13,14:安全/MAC
                    # 这些任务失败可能是由于固件版本较低（未开放该接口）或硬件不支持（如无磁盘/无AP）
                    else:
                        _LOGGER.debug(
                            "iKuai 可选功能任务 %s (Optional) 执行失败（可能固件版本不支持或硬件未就绪）: %s", 
                            i, res
                        )

            # --- 1. 正确解包 15 个变量 (顺序必须与 api.py 完全一致) ---
            (sys_res, clients_res, wifi_stats_res, wifi_score_res, 
             msg_center_res, presence_log_res,
             iface_status_res, iface_config_res, v6_res, 
             backup_res, up_info_res, up_status_res, 
             disks_res, mac_mode_res, mac_rules_res) = results

            # --- 2. 基础元数据提取 --- 包括主机名、系统版本、硬件版本等 (供设备信息使用)
            sysinfo = (sys_res or {}).get("sysinfo", {})
            verinfo = sysinfo.get("verinfo", {})
            self._hostname = sysinfo.get("hostname", "iKuai")
            self._sw_version = sysinfo.get("verinfo", {}).get("version", "Unknown")
            self._hw_version = sysinfo.get("verinfo", {}).get("arch", "Unknown")
            ver_string = verinfo.get("verstring", "Unknown")
            
            mem = sysinfo.get("memory", {})
            users = sysinfo.get("online_user", {})
            stream = sysinfo.get("stream", {})

            # --- 3. WAN IPv4 提取 (物理网口 wan1) ---
            iface_check_list = (iface_status_res or {}).get("iface_check", [])
            wan_v4_ip = "Disconnected"
            for check in iface_check_list:
                if check.get("parent_interface") == "wan1":
                    ip = check.get("ip_addr")
                    if ip and ip != "--":
                        wan_v4_ip = ip
                        if check.get("result") == "success": break

            # --- 4. IPv6 流量与连接数汇总 ---
            v6_data_list = (v6_res or {}).get("data", [])
            v6_total = {"up": 0, "down": 0, "t_up": 0, "t_down": 0, "conn": 0}
            for v6_item in v6_data_list:
                v6_total["up"] += int(v6_item.get("upload", 0))
                v6_total["down"] += int(v6_item.get("download", 0))
                v6_total["t_up"] += int(v6_item.get("total_upload", 0))
                v6_total["t_down"] += int(v6_item.get("total_download", 0))
                v6_total["conn"] += int(v6_item.get("conn", 0))

            # --- 5. 构建 processed_sys (主设备) ---
            processed_sys = {
                "cpu_load": float(sysinfo.get("cpu", ["0%"])[0].replace("%", "")),
                "memory_usage": float(mem.get("used", "0%").replace("%", "")),
                "memory_detail": {k: v for k, v in mem.items() if k != "used"},
                "uptime": int(sysinfo.get("uptime", 0)),
                "temperature": float(sysinfo.get("cputemp", [0])[0]) if sysinfo.get("cputemp") else 0.0,
                "ver_string": ver_string,
                "wan_ip_v4": wan_v4_ip,
                "online_users": int(users.get("count", 0)),
                "online_user_detail": {k: v for k, v in users.items() if k != "count"},
                "connection_count": int(stream.get("connect_num", 0)),
                "connect_detail": {
                    "tcp": stream.get("tcp_connect_num"), "udp": stream.get("udp_connect_num"), 
                    "icmp": stream.get("icmp_connect_num"), "ipv6": v6_total["conn"]
                },
                "upload": int(stream.get("upload", 0)), "download": int(stream.get("download", 0)),
                "total_up": int(stream.get("total_up", 0)), "total_down": int(stream.get("total_down", 0)),
                "v6_stats": {
                    "upload_speed_v6": v6_total["up"], "download_speed_v6": v6_total["down"], 
                    "total_upload_v6": v6_total["t_up"], "total_download_v6": v6_total["t_down"]
                }
            }

            # --- 6. 处理无线监控 (AP) ---
            wifi_data = wifi_stats_res if isinstance(wifi_stats_res, dict) else {}
            ap_status = wifi_data.get("ap_status", {})
            clt_status = wifi_data.get("clt_status", {})
            wifi_score_data = wifi_score_res if isinstance(wifi_score_res, dict) else {}
            net_score = wifi_score_data.get("total_count_net_status", {})
            processed_sys.update({
                "ap_online": int(ap_status.get("ap_online", 0)),
                "wireless_detail": {
                    # AP 状态详情
                    "total_ap": ap_status.get("ap_count"),
                    "offline_ap": ap_status.get("ap_offline"),
                    "roaming_supported": ap_status.get("ap_roaming"),
                    "prefer_5g_aps": ap_status.get("ap_perfer_5g"),
                    # 无线终端分布
                    "clients_2g": clt_status.get("clt_count_2g"),
                    "clients_5g": clt_status.get("clt_count_5g"),
                    "active_clients": clt_status.get("clt_active"),
                    # 无线质量评分属性
                    "signal_coverage": f"{net_score.get('coverage', 0)}%",
                    "network_delay": f"{net_score.get('delay', 0)}ms",
                    "packet_loss": f"{net_score.get('dropptk', 0)}%",
                    "airtime_health_score": net_score.get("score_chutil_load"),
                }
            })

            # --- 7. 处理消息与事件 ---
            new_messages = []
            msg_data = (msg_center_res or {}).get("data", [])
            if msg_data:
                latest_id = msg_data[0].get("id")
                if self.last_msg_id is None: self.last_msg_id = latest_id
                elif latest_id > self.last_msg_id:
                    new_messages = [m for m in msg_data if m.get("id") > self.last_msg_id]
                    self.last_msg_id = latest_id

            # ---处理终端上下线事件 ---
            new_presence = []
            presence_data = (presence_log_res or {}).get("data", [])
            if presence_data:
                latest_p_id = presence_data[0].get("id")
                if self.last_presence_id is None:
                    self.last_presence_id = latest_p_id
                elif latest_p_id > self.last_presence_id:
                    new_presence = [p for p in presence_data if p.get("id") > self.last_presence_id]
                    self.last_presence_id = latest_p_id

            # --- 8. 处理网口监控 (Interfaces) ---
            processed_ifaces = {}
            iface_stream_list = (iface_status_res or {}).get("iface_stream", [])
            iface_to_parent = {i.get("interface"): i.get("parent_interface") for i in iface_check_list}

            for s in iface_stream_list:
                logic_name = s.get("interface")
                parent_port = iface_to_parent.get(logic_name, logic_name)
                if not (parent_port.startswith("wan") or parent_port.startswith("lan")): continue
                if any(logic_name.startswith(p) for p in ["vwan", "adsl", "vlan", "pppoe"]):
                    if parent_port in processed_ifaces: continue 
                    continue
                processed_ifaces[parent_port] = {
                    "ip": s.get("ip_addr") if s.get("ip_addr") != "--" else "0.0.0.0",
                    "upload_speed": int(s.get("upload", 0)), "download_speed": int(s.get("download", 0)),
                    "total_up": int(s.get("total_up", 0)), "total_down": int(s.get("total_down", 0)),
                }

            # --- 9. 处理维护数据 (Backup/Upgrade) ---
            latest_backup = {}
            if isinstance(backup_res, dict):
                b_info = backup_res.get("backup_info", [])
                if b_info:
                    top = sorted(b_info, key=lambda x: x.get("timestamp", 0), reverse=True)[0]
                    latest_backup = {"latest_filename": top.get("filename"), "detail": {"size": top.get("filesize"), "ver": top.get("version")}}

            up_data = (up_info_res or {}).get("data", {})
            up_stat = (up_status_res or {}).get("auto_upgrade", {})
            display_up = "最新"
            if up_stat.get("status", 0) != 0: display_up = up_stat.get("status_msg", "升级中")
            elif up_data.get("new_system_ver") and up_data.get("new_system_ver") != up_data.get("system_ver"):
                display_up = f"可升级: {up_data.get('new_system_ver')}"
            
            processed_maint = {
                "upgrade_state": display_up,
                "upgrade_detail": {"curr": up_data.get("system_ver"), "new": up_data.get("new_system_ver"), "log": up_data.get("update_content")}
            }

            # --- 10. 处理磁盘存储 (Storage) ---
            processed_disks = {}
            disk_raw = (disks_res or {}).get("data", [])
            for d in disk_raw:
                disk_id = d.get("disk")
                t_b, u_b, p_list = 0, 0, []
                for p in d.get("partition", []):
                    m = p.get("mounted", {})
                    if m and m.get("mt_total"):
                        t_b += int(m.get("mt_total", 0)); u_b += int(m.get("mt_used", 0))
                        p_list.append({"name": p.get("name"), "usage": f"{m.get('mt_uses')}%", "mount": m.get("mt_name")})
                processed_disks[disk_id] = {
                    "base_info": {"model": d.get("model"), "disk": disk_id, "system": d.get("system")},
                    "state": {"disk_physical_size": d.get("size"), "disk_usage_pct": round((u_b/t_b*100),1) if t_b > 0 else 0, "disk_used_size": u_b},
                    "partitions": p_list
                }

            # --- 11. 处理安全管理 (Security) ---
            processed_security = {
                "mac_mode_code": (mac_mode_res or {}).get("acl_mac", 0),
                "mac_rules": {str(r["id"]): r for r in (mac_rules_res or {}).get("data", []) if "id" in r}
            }

            # --- 12. 终端映射 (Clients) ---
            client_list = (clients_res or {}).get("data", [])
            clients_map = {str(c["mac"]).lower().replace("-", ":"): c for c in client_list if "mac" in c}

            # --- 【最终唯一返回点】：整合所有模块 ---
            return {
                "system": processed_sys,
                "clients": clients_map,
                "interfaces": processed_ifaces,
                "backup": latest_backup,
                "maintenance": processed_maint,
                "disks": processed_disks,
                "security": processed_security,
                "events": {"messages": new_messages, "presence": new_presence}
            }

        except Exception as err:
            _LOGGER.exception("iKuai Coordinator 数据清洗关键错误")
            raise UpdateFailed(f"API 错误: {err}") from err
      
    # 主设备        
    @property
    def device_info(self) -> DeviceInfo:

        device_name = self.config_entry.title

        return DeviceInfo(
            identifiers={(DOMAIN, self.host)},
            name=f"{self._hostname} {device_name}",
            manufacturer="iKuai",
            model="iKuai Router",
            sw_version=self._sw_version,
            hw_version=self._hw_version,
            configuration_url=self.host,
        )
    
    #接口管理子设备    
    @property
    def iface_mgmt_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_iface_mgmt")},
            name=f"{self.config_entry.title} 接口监控管理",
            manufacturer="iKuai",
            model="Interface Monitor",
            via_device=(DOMAIN, self.host),
        )
    
    # 升级与备份管理子设备    
    @property
    def maintenance_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_maintenance")},
            name=f"{self.config_entry.title} 升级与备份管理",
            manufacturer="iKuai",
            model="System Maintenance",
            via_device=(DOMAIN, self.host),
        )

    # 定义安全管理子设备
    @property
    def security_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.host}_security")},
            name=f"{self.config_entry.title} 安全管理",
            manufacturer="iKuai",
            model="Security & Firewall",
            via_device=(DOMAIN, self.host),
        )