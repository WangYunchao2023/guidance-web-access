---
name: guidance-web-access
description: 医药法规网页访问与自动下载工具。用于指导原则页面探索、精准搜索、界面感知输入与增量下载。触发条件：用户提到"网页访问"、"下载法规"、"指导原则"、"搜索法规"、"web-access"时使用。
version: 3.9.14
---

# SKILL.md - Guidance Web Access

## ⚠️ 执行前提

执行脚本前，必须设置显示凭证环境变量（否则浏览器无法打开）：

```bash
export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority
```

## 🌟 核心理念

- **Cortana 先理解 (Cortana First)**：接到任务后先分析，制定策略，再协调执行。
- **经验优先 (Experience First)**：优先检索 `user_overrides.yaml`，命中则放弃默认路径。
- **智能化感知 (Interface Perception)**：不硬编码输入框 ID，自动扫描页面感知字段。
- **语义过滤 (Semantic Filter)**：智能过滤结果，确保只下载与任务高度相关的内容。

## 🚦 两个执行入口（必须分清）

脚本有两个完全独立的执行入口，参数互不兼容：

### 入口一：`--cortana-plan`（有经验分支）

对应函数：`cortana_execute_flow()`

**参数格式**：
```json
{
  "task": "任务描述",
  "search_url": "搜索页URL（可选）",
  "search_var": "搜索关键词（可选）",
  "filter_criteria": ["关键词1", "关键词2"],
  "list_urls": ["列表页URL（可选）"],
  "method": "search_only" | "navigate_only" | "both",
  "extra_filter": "额外过滤词（可选）",
  "save_dir": "保存目录"
}
```

**使用场景**：已知目标网站（通过经验匹配或人工指定 URL）。

### 入口二：`--auto-flow`（无经验分支）

对应函数：`cortana_auto_flow()`

**参数格式**：
```json
{
  "task": "任务描述",
  "strategies": [
    {"name": "策略1", "url": "URL", "sv": "搜索词", "filter_criteria": ["词1", "词2"]},
    {"name": "策略2", "url": "URL", "sv": null, "filter_criteria": ["词1"]}
  ],
  "filter_criteria": ["全局过滤词"],
  "intent": {"query": "任务描述", "primary": "核心词", "original": "原始任务"},
  "save_dir": "保存目录",
  "download_enabled": true
}
```

**使用场景**：Cortana 自主感知目标网站结构，制定多策略序列。

### 常见错误

> ⚠️ **不要把 `strategies` 参数传给 `--cortana-plan`**，这会导致 Cortana 决策混乱。`strategies` 只在 `--auto-flow` 入口中有效。

## 🤖 Cortana 任务理解流程（固化）

### 接到任务后，Cortana 先分析：

1. **理解任务本质**：核心实体（如"中药"+"稳定性"）、是否有简称。
2. **检查人工经验**：`user_overrides.yaml` 用原始任务文本匹配，命中则使用经验 URL。
3. **制定执行策略**：
   - 有经验：直接使用经验 URL + `search_var` + `filter_criteria`
   - 无经验：制定多策略序列（`strategies`），每个策略包含 URL、搜索词、过滤条件
4. **生成完整执行方案**，输出标准格式报告。

### 标准化报告格式

```
🎯 AI任务理解: 下载中药稳定性相关指导原则
📋 核心实体: 中药 + 稳定性
🔍 简称识别: 无简称
🔍 搜索策略: sv="中药", 过滤=["中药", "稳定性"]
📌 匹配经验: (.*)相关的指导原则 → 使用经验URL
💡 建议: 执行搜索 → 多块翻页提取 → 附件过滤 → 下载
```

## 执行示例

### 有经验分支（`--cortana-plan`）

```bash
export DISPLAY=:0 && export XAUTHORITY=/run/user/1000/gdm/Xauthority
cd ~/.openclaw/workspace/skills/guidance-web-access/scripts
python3 web_access.py --cortana-plan '{
  "task": "下载中药注射剂相关指导原则",
  "search_url": "https://www.cde.org.cn/zdyz/fullsearchpage",
  "search_var": "中药注射剂",
  "filter_criteria": ["中药", "注射剂"],
  "method": "search_only",
  "save_dir": "~/Documents/工作/法规指导原则/中药注射剂"
}'
```

### 无经验分支（`--auto-flow`）

```bash
export DISPLAY=:0 && export XAUTHORITY=/run/user/1000/gdm/Xauthority
cd ~/.openclaw/workspace/skills/guidance-web-access/scripts
python3 web_access.py --auto-flow '{
  "task": "下载中药注射剂相关指导原则",
  "strategies": [
    {"name": "完整匹配", "url": "https://目标网站/search", "sv": "中药注射剂", "filter_criteria": ["中药", "注射剂"]},
    {"name": "分词扩展", "url": "https://目标网站/search", "sv": "中药", "filter_criteria": ["中药", "注射剂"]}
  ],
  "intent": {"query": "下载中药注射剂相关指导原则", "primary": "中药注射剂", "original": "下载中药注射剂相关指导原则"},
  "save_dir": "~/Documents/工作/法规指导原则/中药注射剂",
  "download_enabled": true
}'
```

## 🧠 过滤机制

### 列表级过滤（每级实时过滤）

每块每次翻页提取后，立即用 `all()` 逻辑过滤：链接文本必须**同时包含所有过滤词**才加入结果集。

### 附件级过滤（下载前过滤）

进入详情页后，对附件文件名进行二次过滤：
- `filter_criteria`（如 `["中药","稳定性"]`）：附件名必须包含**所有**关键词
- `is_noise`（噪音附件）：含"反馈表"等，无论是否满足过滤条件都下载
- 正文文件（含"指导原则"/"征求意见稿"）：通过 filter_criteria 后下载

### 日期过滤

**默认关闭**。只有任务**明确指定日期**（如"2024年发布的"）时，日期过滤才生效；未指定则忽略所有日期条件。

## 📂 存储与增量规范

- **法规指导原则**：`~/Documents/工作/法规指导原则/`
- **命名规范**：`发布日期 - 完整文件标题.pdf`
- **增量去重**：下载前检测同名文件，已存在则跳过。

## 🛠️ 脚本结构

| 函数 | 入口 | 核心功能 |
|------|------|----------|
| `cortana_execute_flow()` | `--cortana-plan` | 有经验引导的精准执行（有经验时使用） |
| `explore_with_pagination_v2()` | 有经验分支 | 有经验专用探索引擎（含多块翻页） |
| `cortana_auto_flow()` | `--auto-flow` | 无经验分支主入口（Cortana 全程感知） |
| `explore_with_pagination_noexp()` | 无经验分支 | 无经验专用探索引擎（含多块翻页） |
| `find_content_blocks()` | 通用 | 识别页面7种内容块结构 |
| `find_next_button_for_block()` | 通用 | 块级隔离翻页按钮搜索 |
| `final_download()` | 通用 | 附件精准过滤下载 |
| `apply_filters()` | 通用 | 多重关键词 AND 过滤 |
| `user_overrides.yaml` | 有经验分支 | 人工经验库：URL + 执行方式 |

## 🚀 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v3.9.14 | 2026-04-01 | SKILL.md重构：入口参数分离(WAL入口两模式)/删除误导性strategies示例/WAF异常检测增强打印完整traceback/精简版本历史 |
| v3.9.13 | 2026-04-01 | UA池轮换（8个UA随机选取，降低反爬识别）+ find_content_blocks增强识别7种块类型（Tab面板/虚拟滚动/卡片列表等）+ find_next_button_for_block增强翻页按钮匹配 |
| v3.9.12 | 2026-04-01 | fc过滤只看附件名本身，不依赖通告标题，避免多主题同通告时的误判 |
| v3.9.11 | 2026-04-01 | 修复fc过滤被is_main_doc误绕过的bug：正文文件也需通过fc过滤 |
| v3.9.10 | 2026-04-01 | 修复find_next_button_for_block整页搜索bug，重构get_links_noexp为委托模式 |
| v3.9.9 | 2026-04-01 | 多块隔离提取（block_selector）+ 每级实时多重过滤 + final_download附件级filter_criteria精准过滤 |
| v3.9.8 | 2026-03-31 | 修复过滤逻辑：将`any()`改为`all()`，确保多关键词全部匹配 |
