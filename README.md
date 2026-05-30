# iKuai Connect for Home Assistant

[![Release](https://img.shields.io/github/v/release/hzonz/ha_ikuai_connect)](https://github.com/hzonz/ha_ikuai_connect/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/hzonzha_ikuai_connect/blob/main/LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

## iKuai Connect 是专为 Home Assistant 打造的爱快（iKuai）路由器深度集成插件。不同于传统的网页模拟登录，本项目完全基于 **iKuai OpenAPI 3.1 (v4.0接口)** 构建，提供极速、稳定且安全的网络监控与自动化体验。

## 重点：只支持 ikuai 4.0.222+ 以上版本。

## ✨ 核心特性

- 🚀 **超高性能**: 基于 Python 异步架构与 `aiohttp`，并引入 API 缓存与并发限流机制。
- 🏗️ **子设备架构**: 自动将主路由、网络接口、存储设备、维护管理拆分为独立子设备，保持实体列表井然有序。
- 📊 **深度监控**:
  - **系统负载**: CPU (多核)、内存详情、连接数 (IPv4/IPv6)、系统温度、运行时间。
  - **无线管理**: 在线 AP 统计、无线评分、丢包率、延迟及信号覆盖度。
  - **网络接口**: 自动识别物理网口 (WAN/LAN)，提供实时速率、累计流量统计及 IP 自动补全。
  - **存储管理**: 动态识别物理磁盘型号，监控各分区空间占用。
- 🛡️ **安全控制**: 
  - 支持 **MAC 访问控制** 全局模式切换（黑/白名单）。
  - 动态生成已有 MAC 规则开关，实现一键禁网。
- 🔔 **实时事件**: 对接爱快消息中心与终端上下线日志，支持 HA 事件总线自动化。
- 📍 **精准追踪**: 仅追踪你关心的终端设备，杜绝实体爆炸。
- 🔐 **工业级安全**: 采用爱快官方 **个人 API 令牌 (Bearer Token)**，无需暴露管理员密码。
  
## 📦 安装

### 通过HACS安装（推荐）

1. 在HACS的"集成"部分，点击右上角的三点菜单
2. 选择"自定义存储库"
3. 在存储库字段输入：`https://github.com/hzonz/ha_ikuai_connect`
4. 类别选择"集成"
5. 点击"添加"保存
6. 在HACS中找到"ikuai_connect"集成并点击安装
7. 重启Home Assistant

### 手动安装

1. 下载最新的: `https://github.com/hzonz/ha_ikuai_connect`
2. 解压并将`custom_components/ikuai_connect`文件夹放入Home Assistant的`custom_components`目录
3. 重启Home Assistant

## 📖 文档导航
- [🚀 详细配置与使用教程 (DOCS.md)](md/DOCS.md)
- [📜 版本更新历史 (CHANGELOG.md)](md/CHANGELOG.md)


## 📜 声明

- 本项目与 ikaui(爱快) 官方无直接隶属关系。
- 请遵守 ikuai(爱快) 的 API 使用协议。

## 🤝 贡献

欢迎贡献代码、报告问题或提出功能建议！

1. 提交Issues：报告问题或功能请求
2. 提交Pull Requests：贡献代码改进
3. 项目讨论：分享使用经验或建议

## 📄 许可证

本项目基于MIT许可证开源。详情请查看LICENSE文件。

## ❤️ 支持

如果这个项目对您有帮助，请给项目点个Star ⭐！

---
**兼容版本**:

Home Assistant 2024.5+.
ikuai 4.0.222+.
