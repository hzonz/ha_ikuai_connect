"""Constants for iKuai Connect."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Final, Callable, Any

from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.button import ButtonEntityDescription, ButtonDeviceClass
from homeassistant.components.event import EventEntityDescription
from homeassistant.components.select import SelectEntityDescription
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTime,
    UnitOfTemperature,
    Platform,
)

DOMAIN: Final = "ikuai_connect"
PLATFORMS: Final = [
    Platform.SENSOR, 
    Platform.DEVICE_TRACKER, 
    Platform.BUTTON, 
    Platform.EVENT, 
    Platform.SELECT,
    Platform.SWITCH
]

CONF_TRACKER_CONFIG: Final = "tracker_config"
CONF_ACT_BUFFER: Final = "act_buffer"

# MAC 访问控制模式映射
MAC_ACL_MODES = {
    0: "blacklist",
    1: "whitelist"
}
MAC_ACL_MODES_REVERSE = {v: k for k, v in MAC_ACL_MODES.items()}

@dataclass(frozen=True, kw_only=True)
class IkuaiSensorEntityDescription(SensorEntityDescription):
    """自定义描述符：增加数据提取和属性提取函数."""
    value_fn: Callable[[dict[str, Any]], Any] | None = None
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None

@dataclass(frozen=True, kw_only=True)
class IkuaiButtonEntityDescription(ButtonEntityDescription):
    """描述按钮动作."""
    # 允许在描述符中直接定义动作
    action_type: str 

@dataclass(frozen=True, kw_only=True)
class IkuaiEventEntityDescription(EventEntityDescription):
    """描述 iKuai 事件实体."""

# 1. 系统负载传感器 (挂载在主设备下)
SYSTEM_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="cpu_load",
        name="CPU Load",
        translation_key="cpu_load",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("cpu_load"),
    ),
    IkuaiSensorEntityDescription(
        key="memory_usage",
        name="Memory Usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("memory_usage"),
        attr_fn=lambda d: d.get("system", {}).get("memory_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="online_users",
        name="Online Users",
        translation_key="online_users",
        icon="mdi:account-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("online_users"),
        attr_fn=lambda d: d.get("system", {}).get("online_user_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="connection_count",
        name="Connection Count",
        translation_key="connection_count",
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("connection_count"),
        attr_fn=lambda d: {
            "tcp": d.get("system", {}).get("connect_detail", {}).get("tcp"),
            "udp": d.get("system", {}).get("connect_detail", {}).get("udp"),
            "icmp": d.get("system", {}).get("connect_detail", {}).get("icmp"),
            "ipv6": d.get("system", {}).get("connect_detail", {}).get("ipv6"),
        },
    ),
    # 系统级实时流统计
    IkuaiSensorEntityDescription(
        key="sys_upload",
        name="System Upload Speed",
        translation_key="sys_upload_speed",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("upload"),
        attr_fn=lambda d: {"ipv6_upload_speed": d.get("system", {}).get("v6_stats", {}).get("upload_speed_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_download",
        name="System Download Speed",
        translation_key="sys_download_speed",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("download"),
        attr_fn=lambda d: {"ipv6_download_speed": d.get("system", {}).get("v6_stats", {}).get("download_speed_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_total_up",
        name="System Total Upload",
        translation_key="sys_total_up",
        icon="mdi:upload",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.get("system", {}).get("total_up"),
        attr_fn=lambda d: {"ipv6_total_upload": d.get("system", {}).get("v6_stats", {}).get("total_upload_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="sys_total_down",
        name="System Total Download",
        translation_key="sys_total_down",
        icon="mdi:download",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.get("system", {}).get("total_down"),
        attr_fn=lambda d: {"ipv6_total_download": d.get("system", {}).get("v6_stats", {}).get("total_download_v6")},
    ),
    IkuaiSensorEntityDescription(
        key="uptime",
        name="Uptime",
        translation_key="uptime",
        icon="mdi:clock-time-eight",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: d.get("system", {}).get("uptime"),
        attr_fn=lambda d: {
            "wan_ipv4": d.get("system", {}).get("wan_ip_v4"),
            "firmware_version": d.get("system", {}).get("ver_string"),
        },    
    ),
    IkuaiSensorEntityDescription(
        key="temperature",
        name="Temperature",
        translation_key="temperature",
        icon="mdi:thermometer",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("temperature"),
    ),
        IkuaiSensorEntityDescription(
        key="ap_online",
        name="Wireless AP Online",
        translation_key="ap_online",
        icon="mdi:access-point-check",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get("system", {}).get("ap_online"),
        attr_fn=lambda d: d.get("system", {}).get("wireless_detail", {}),
    )
)

# 事件实体定义
EVENT_TYPES: Final[tuple[IkuaiEventEntityDescription, ...]] = (
    IkuaiEventEntityDescription(
        key="message_center",
        name="System Notifications",
        translation_key="message_center",
        icon="mdi:bell-ring",
    ),
    IkuaiEventEntityDescription(
        key="terminal_presence",
        name="Terminal Activity",
        translation_key="terminal_presence",
        icon="mdi:account-clock",
    ),
)

# 定义所有按钮
BUTTON_TYPES: Final[tuple[IkuaiButtonEntityDescription, ...]] = (
    IkuaiButtonEntityDescription(
        key="reboot",
        name="Reboot",
        translation_key="reboot",
        icon="mdi:restart",
        device_class=ButtonDeviceClass.RESTART,
        action_type="reboot_main",
        entity_registry_enabled_default=False,
    ),
    IkuaiButtonEntityDescription(
        key="check_upgrade",
        name="Check for Updates",
        translation_key="check_update",
        icon="mdi:update",
        action_type="check_upgrade",
    ),
    IkuaiButtonEntityDescription(
        key="start_upgrade",
        name="Start Upgrade",
        translation_key="start_upgrade",
        icon="mdi:cloud-download",
        action_type="start_upgrade",
    ),
    IkuaiButtonEntityDescription(
        key="create_backup",
        name="Create Backup",
        translation_key="create_backup",
        icon="mdi:database-export",
        action_type="backup",
    ),
)

# 模式选择器描述符
MAC_MODE_SELECT: Final = SelectEntityDescription(
    key="mac_acl_mode",
    name="MAC Access Mode",
    translation_key="mac_acl_mode",
    icon="mdi:shield-check",
    options=["blacklist", "whitelist"],
)

# 接口监控设备传感器模板
INTERFACE_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="upload_speed",
        name="Upload Speed",
        translation_key="upload_speed",
        icon="mdi:upload-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="download_speed",
        name="Download Speed",
        translation_key="download_speed",
        icon="mdi:download-network",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        suggested_display_precision=2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="total_up",
        name="Total Upload",
        translation_key="total_up",
        icon="mdi:upload",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    IkuaiSensorEntityDescription(
        key="total_down",
        name="Total Download",
        icon="mdi:download",
        translation_key="total_down",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)

# 升级与备份传感器组 (挂载在“升级与备份”子设备下)
MAINTENANCE_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="upgrade_status",
        name="Update Status",
        translation_key="upgrade_status",
        icon="mdi:update",
        value_fn=lambda d: d.get("maintenance", {}).get("upgrade_display_state"),
        attr_fn=lambda d: d.get("maintenance", {}).get("upgrade_detail", {}),
    ),
    IkuaiSensorEntityDescription(
        key="backup_status",
        name="Latest Backup",
        translation_key="latest_backup",
        icon="mdi:database-check",
        value_fn=lambda d: d.get("backup", {}).get("latest_filename"),
        attr_fn=lambda d: d.get("backup", {}).get("detail", {}),
    ),
)

# 增加或更新磁盘描述符
DISK_SENSORS: Final[tuple[IkuaiSensorEntityDescription, ...]] = (
    IkuaiSensorEntityDescription(
        key="disk_physical_size",
        name="Total Capacity",
        translation_key="disk_total_capacity",
        icon="mdi:database",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement = "GB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="disk_usage_pct",
        name="Usage Rate",
        translation_key="disk_usage_rate",
        icon="mdi:chart-arc",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    IkuaiSensorEntityDescription(
        key="disk_used_size",
        name="Used Capacity",
        translation_key="disk_used_capacity",
        icon="mdi:database-minus",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement = "GB",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)