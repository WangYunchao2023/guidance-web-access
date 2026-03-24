# CHANGELOG - web-access 版本变更日志

All notable changes to this skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.7.2] - 2026-03-24

### Changed
- 统一版本号至 2.7.1，与脚本头部及 CHANGELOG 保持一致

---

## [1.7.0] - 2026-03-24

### Added
- **截短策略** (`generate_truncated_variants`)：变量提取后若搜索结果少，自动逐步截短关键词重试。截短顺序：1) 去掉结尾修饰词（相关、指南、技术、产品等）2) 逐步去掉尾部字符

---

## [1.6.5] - 2026-03-20

### Added
- 智能导航能力 (smart_navigate.py)
- AI智能分流：自动判断网站类型选择最优网络路径
- VPN信号机制：访问失败时记录信号供AI决策
- 内容类型识别：根据关键词自动选择搜索/导航策略
- 文件验证机制：自动验证PDF/Office文件完整性

### Changed
- 默认禁用自动VPN切换，需手动确认
- 搜索+导航并行执行，合并去重
- 增强反爬检测和页面加载优化

### Fixed
- 修复搜索框搜索失败问题
- 优化日期匹配支持多种格式

---

## [1.5.0] - 2026-03-XX

### Added
- CDE反爬解决方案：非headless模式 + 增强反检测脚本
- Cookie自动携带下载
- PDF验证：使用PyPDF2/pdfminer验证可打开
- Office验证：验证docx/xlsx文件头格式

### Changed
- 增加等待时间(10秒)确保动态内容加载
- 下载失败自动重试3次

---

## [1.0.0] - 初始版本

### Added
- 基础网页访问和下载能力
- CDE网站专用下载
- FDA网站搜索
- 通用文件下载

---

## 版本号说明

- **主版本号 (1.x.x)**: 重大架构变更或新增核心功能
- **次版本号 (1.6.x)**: 新增功能或重要优化
- **修订号 (1.6.5)**: Bug修复或小优化

## 如何贡献

1. 每次修改 SKILL.md 时，在顶部更新 version 字段
2. 在本文件添加对应的版本变更记录
3. 使用 Git 提交并标注版本号

---

## [2.7.0] - 2026-03-23

### Added
- **语义分级引擎 (v2.7.0 核心)**：`extract_task_intent()` 升级为语义分级提取，区分主体词（如"指导原则"）与限定词（如"沟通交流"）
- **Override 精准匹配**：升级 `match_override()` 支持主体词匹配，"沟通交流指导原则" → 命中"指导原则"经验
- **限定词二次过滤**：结果在 fuzzy_semantic_filter 之后，增加限定词过滤（有限定词时）

### Changed
- `main_flow()` 日志增强：打印主体词和限定词，方便追踪匹配逻辑
- override 匹配时记录 `_matched_on`（匹配依据），用于日志追溯

### Root Cause (本次升级)
- 用户执行"沟通交流指导原则"时，理解反了：把"沟通交流"当主关键词，"指导原则"当限定词
- `task_pattern: "指导原则"` 无法匹配完整字符串，但主体词提取后可直接命中

## [2.7.1] - 2026-03-23

### Added
- **method 字段**：`user_overrides.yaml` 新增 `method` 字段，支持 `navigate_only`、`search_only`、`both`
- **经验方法明确性**：当经验指定了 method 时，脚本只执行该方式，不再双轨并行
- **变量通配符支持**：pattern 支持 `XX` 或 `.*` 提取任务中的变量部分

### Changed
- `match_override()` 支持变量提取（从 pattern 如 "XX相关的指导原则" 提取 "XX"）
- `main_flow()` 日志增强：打印执行方式，明确标注"仅使用经验指定方式"

### Root Cause (本次升级)
- 之前即使经验提供了方法，脚本仍然双轨并行（导航+搜索同时进行），导致效率低下且噪音多
- 用户期望：经验明确指定方法时，只执行该方法
