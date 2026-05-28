"""Data Coordinator for iKuai Connect."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from .const import (
    DOMAIN,
    CONF_TRACKER_CONFIG,
    CONF_OFFLINE_GRACE_PERIOD,
    DEFAULT_OFFLINE_GRACE_PERIOD,
)

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
        self._hostname = "iKuai"
        self._last_seen: dict[str, float] = {}


    async def _async_update_data(self) -> dict[str, Any]:
        """抓取并清洗数据."""
        try:
            
            # 异步并发抓取所有端点的数据
            results = await self.api.get_all_data()
            
            # 任务预检逻辑
            for i in [0, 1, 2]:
                if isinstance(results[i], Exception):
                    raise results[i]

            # --- 正确解包 14 个变量 (顺序必须与 api.py 完全一致) ---
            (sys_res, clients_res, wifi_stats_res, 
             iface_status_res, v6_res, wifi_score_res, 
             msg_center_res, presence_log_res, 
             mac_mode_res, mac_rules_res, 
             backup_res, up_info_res, up_status_res, disks_res) = results

            # ---基础元数据提取 --- 包括主机名、系统版本、硬件版本等 (供设备信息使用)
            sysinfo = sys_res.get("sysinfo", {}) if isinstance(sys_res, dict) else {}
            verinfo = sysinfo.get("verinfo", {})
            self._hostname = sysinfo.get("hostname", "iKuai")
            self._sw_version = verinfo.get("version", "Unknown")
            self._hw_version = verinfo.get("arch", "Unknown")
            ver_string = verinfo.get("verstring", "Unknown")

            mem = sysinfo.get("memory", {})
            users = sysinfo.get("online_user", {})
            stream = sysinfo.get("stream", {})

            # ---WAN IPv4 提取 (物理网口 wan1) ---
            iface_check_list = iface_status_res.get("iface_check", []) if isinstance(iface_status_res, dict) else []
            wan_v4_ip = "Disconnected"
            for check in iface_check_list:
                if check.get("parent_interface") == "wan1":
                    ip = check.get("ip_addr")
                    if ip and ip != "--":
                        wan_v4_ip = ip
                        if check.get("result") == "success": break

            # ---IPv6 流量与连接数汇总 ---
            v6_data_list = v6_res.get("data", []) if isinstance(v6_res, dict) else []
            v6_total = {"up": 0, "down": 0, "t_up": 0, "t_down": 0, "conn": 0}
            for v6_item in v6_data_list:
                v6_total["up"] += int(v6_item.get("upload", 0))
                v6_total["down"] += int(v6_item.get("download", 0))
                v6_total["t_up"] += int(v6_item.get("total_upload", 0))
                v6_total["t_down"] += int(v6_item.get("total_download", 0))
                v6_total["conn"] += int(v6_item.get("conn", 0))

            # ---构建 processed_sys (主设备) ---
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

            # ---处理无线监控 (AP) ---
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

            # ---处理系统消息中心事件 ---
            new_messages = []
            # 增加类型检查，防止 TimeoutError 对象调用 .get()
            msg_res_data = msg_center_res.get("data", []) if isinstance(msg_center_res, dict) else []
            if msg_res_data:
                # 获取当前最新的 ID (API返回通常是降序，所以取第一个)
                current_max_msg_id = msg_res_data[0].get("id", 0)
                
                if self.last_msg_id is None:
                    # 第一次运行：初始化 ID，不触发历史消息
                    self.last_msg_id = current_max_msg_id
                elif current_max_msg_id > self.last_msg_id:
                    # 找出所有比上次 ID 大的新消息，并按时间正序排列
                    new_messages = sorted(
                        [m for m in msg_res_data if m.get("id", 0) > self.last_msg_id],
                        key=lambda x: x.get("id", 0)
                    )
                    self.last_msg_id = current_max_msg_id

            # ---处理终端上下线事件 ---
            new_presence = []
            presence_res_data = presence_log_res.get("data", []) if isinstance(presence_log_res, dict) else []
            
            if presence_res_data:
                # 1. 找出所有 ID
                all_ids = [p.get("id", 0) for p in presence_res_data]
                current_max_p_id = max(all_ids) if all_ids else 0
                
                if self.last_presence_id is None:
                    # 初次启动，仅记录锚点 ID
                    self.last_presence_id = current_max_p_id
                elif current_max_p_id > self.last_presence_id:
                    # 2. 提取所有大于上次 ID 的新记录，并按 ID 升序排序（保证触发顺序正确）
                    new_presence = sorted(
                        [p for p in presence_res_data if p.get("id", 0) > self.last_presence_id],
                        key=lambda x: x.get("id", 0)
                    )
                    # 3. 更新锚点
                    self.last_presence_id = current_max_p_id

            # --- 终端映射 (Clients) ---
            now = time.time()
            tracker_config = self.config_entry.options.get(CONF_TRACKER_CONFIG, {})
            grace_seconds = self.config_entry.options.get(CONF_OFFLINE_GRACE_PERIOD, DEFAULT_OFFLINE_GRACE_PERIOD)            
            # 拿到 API 当前实时在线的列表
            api_online_map = {}
            if isinstance(clients_res, dict):
                for c in clients_res.get("data", []):
                    if "mac" not in c: continue
                    
                    mac_l = str(c["mac"]).lower().replace("-", ":")
                    
                    fallback_name = (
                        c.get("termname") 
                        or c.get("client_model") 
                        or extract_name_from_label(c.get("comment")) 
                        or f"Client {mac_l.replace(':', '')[-4:]}"
                    )
                    c["display_name"] = fallback_name
                    api_online_map[mac_l] = c

            previous_clients = self.data.get("clients", {}) if self.data and isinstance(self.data, dict) else {}
            final_clients_map = {}
            
            for mac_lower, device_conf in tracker_config.items():
                if mac_lower in api_online_map:
                    self._last_seen[mac_lower] = now
                    final_clients_map[mac_lower] = api_online_map[mac_lower]
                else:
                    last_seen_ts = self._last_seen.get(mac_lower, 0)
                    elapsed = now - last_seen_ts
                    dev_grace = device_conf.get("buffer", grace_seconds)
                    
                    if elapsed < dev_grace:
                        # 沿用缓存数据，如果没有则创建一个带基本名称的字典
                        final_clients_map[mac_lower] = previous_clients.get(
                            mac_lower, 
                            {"mac": mac_lower, "ip_addr": "Unknown", "offline_buffering": True}
                        )
                    else:
                        # 【真正离线】：不加入 final_clients_map
                        _LOGGER.debug("设备 %s 离线超时，设置为离开", mac_lower)

            # ---子设备 处理接口监控 (Interfaces) ---
            processed_ifaces = {}
            iface_stream_list = iface_status_res.get("iface_stream", []) if isinstance(iface_status_res, dict) else []
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

            # ---子设备 处理升级与备份 (Backup/Upgrade) ---
            # 备份列表中找最新的一个，提取文件名、大小、版本等信息
            latest_backup = {}
            if isinstance(backup_res, dict):
                b_info = backup_res.get("backup_info", [])
                if b_info:
                    top = sorted(b_info, key=lambda x: x.get("timestamp", 0), reverse=True)[0]
                    latest_backup = {"latest_filename": top.get("filename"), "detail": {"backtype": top.get("backtype"), "filesize": top.get("filesize"), "version": top.get("version")}}
            
            # 升级信息中提取当前版本、最新版本、升级日志等，并根据状态码判断是否正在升级或可升级
            up_data = up_info_res.get("data", {}) if isinstance(up_info_res, dict) else {}
            up_stat_info = up_status_res.get("auto_upgrade", {}) if isinstance(up_status_res, dict) else {}
            curr_ver = up_data.get("system_ver")
            new_ver = up_data.get("new_system_ver")
            # status: 0=空闲, 1=下载中, 2=安装中, <0=失败
            status_code = up_stat_info.get("status", 0)
            status_msg = up_stat_info.get("status_msg", "")
            # 计算显示状态逻辑
            if status_code != 0:
                # 正在升级（下载或安装）
                display_up = status_msg if status_msg else "正在处理升级..."
            elif new_ver and new_ver != curr_ver:
                # 有新版本
                display_up = f"发现新版本: {new_ver}"
            else:
                # 已是最新
                display_up = "已是最新版本"

            processed_maint = {

                "upgrade_display_state": display_up,
                "upgrade_detail": {
                    "current_version": curr_ver,
                    "latest_version": new_ver,
                    "version_type": up_data.get("version_type"),
                    "build_date": up_data.get("build_date"),
                    "update_content": up_data.get("update_content", "无更新说明"),
                    "last_check": time.strftime('%Y-%m-%d %H:%M:%S')
                }
            }

            # ---处理安全管理 (Security) ---
            processed_security = {
                "mac_mode_code": mac_mode_res.get("acl_mac", 0) if isinstance(mac_mode_res, dict) else 0,
                "mac_rules": {str(r["id"]): r for r in (mac_rules_res.get("data", []) if isinstance(mac_rules_res, dict) else []) if "id" in r}
            }

            # ---处理磁盘存储 (Storage) ---
            PURPOSE_MAP = {"0": "普通储存", "1": "有余繁星", "2": "视频缓存", "3": "行为记录", "4": "钉钉闪传"}

            processed_disks = {}
            disk_raw = disks_res.get("data", []) if isinstance(disks_res, dict) else []

            for d in disk_raw:
                disk_id = d.get("disk")
                total_bytes = 0
                used_bytes = 0
                partitions = []

                for p in d.get("partition", []):
                    m = p.get("mounted") or {}
                    mt_total = int(m.get("mt_total") or 0)
                    mt_used = int(m.get("mt_used") or 0)

                    # 累加磁盘总量与使用量
                    if mt_total > 0:
                        total_bytes += mt_total
                        used_bytes += mt_used

                    # 处理 usage 字段，避免重复百分号
                    mt_uses = m.get("mt_uses")
                    if isinstance(mt_uses, str) and mt_uses.endswith("%"):
                        usage = mt_uses
                    else:
                        usage = f"{mt_uses}%" if mt_uses is not None else "未知"

                    # purpose 映射，统一转字符串
                    purpose_key = str(m.get("mt_purpose"))
                    purpose = PURPOSE_MAP.get(purpose_key, "未知")

                    partitions.append({
                        "name": p.get("name"),
                        "usage": usage,
                        "mount": m.get("mt_name"),
                        "purpose": purpose
                    })

                # 计算磁盘使用率
                usage_pct = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0

                processed_disks[disk_id] = {
                    "base_info": {
                        "model": d.get("model"),
                        "disk": disk_id,
                        "system": d.get("system"),
                        "type": d.get("type"),
                        "block_size": d.get("block_size")
                    },
                    "state": {
                        "disk_physical_size": d.get("size"),
                        "disk_usage_pct": usage_pct,
                        "disk_used_size": used_bytes
                    },
                    "partitions": partitions
                }


            # --- 【最终唯一返回点】：整合所有模块 ---
            return {
                "system": processed_sys,
                "clients": final_clients_map,
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