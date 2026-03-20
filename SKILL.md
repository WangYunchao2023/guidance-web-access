---
name: web-access
version: "1.7.1"
changelog: CHANGELOG.md
description: |
  网页访问、下载能力。支持任意网站访问，反爬绕过、VPN信号机制、文件下载，智能导航。
  激活条件：用户提到"访问网站"、"打开网页"、"获取网页内容"、"截图"、"下载"、"CDE"、"药品审评中心"、"FDA"、"搜索不到"、"找不到内容"等。

  ## v1.7.1 重要更新 (2026-03-20)

  ### 真正的层级深入查找
  - **AI判断点击哪些链接**：分析页面所有链接，根据关键词打分
  - **按分数排序**：优先点击相关性最高的链接
  - **逐层深入**：点击后继续分析新页面，递归深入（最大深度2层）
  - **自动翻页**：在每个层级自动翻页查找

  ### 搜索关键词策略优化
  - 直接使用用户关键词，失败时逐级缩短

  ## v1.7.0 重要更新 (2026-03-20)

  ### 搜索关键词策略优化
  - **直接使用用户关键词**
  - **关键词缩短策略**：搜索失败时按顺序尝试简化

  ## v1.6.4 重要更新 (2026-03-20)
  
  ### 搜索+导航并行
  - **方式1**: 搜索框搜索
  - **方式2**: 网站导航（首页、指导原则、征求意见、发布通告、信息公开等）
  - 两种方式**并行执行**，最后**合并去重**
  - 防止遗漏，提高覆盖率
  
  ## v1.6.3 重要更新 (2026-03-20)
  
  ### 多策略搜索合并
  - 主题查询同时使用"原始关键词"和"扩展关键词"搜索
  - 合并两个策略的结果，统一去重
  - 相关性分析后返回最终列表
  
  ### 搜索稳定性优化
  - 修复搜索框搜索失败问题
  - 增加等待时间确保页面加载
  - 添加反检测脚本确保搜索正常
  
  ## v1.6.0 重要更新 (2026-03-20)
  
  ### AI智能分流
  - 国内网站（cde.org.cn等）→ 直连，不走VPN
  - 国外网站（fda.gov等）→ VPN代理
  - 自动判断网站类型，智能选择网络路径
  
  ### 搜索优化
  - 默认关键词：指导原则 法规 征求意见稿
  - 多渠道搜索：搜索框 + 指导原则专栏 + 征求意见 + 发布通告
  - 相关性分析：50+医药关键词过滤
  
  ### 其他优化
  - 禁用自动VPN切换（需手动确认）
  - 发布日期自动添加到文件名
  
  ## v1.5.0 重要更新
  
  ### 核心优化
  - **CDE反爬解决方案**: 使用非headless模式 + 增强反检测脚本绕过JS混淆反爬
  - **日期匹配优化**: 支持多种格式（2026.03.09、2026.03 09、20260309、2026年3月9日等）
  - **页面加载优化**: 增加等待时间(10秒)确保动态内容加载完成
  - **Cookie携带**: 自动获取并携带Cookie下载附件
  
  ### 日志优化（v1.5.0新增）
  - **详细执行过程**: 显示采用的skill、访问URL、搜索策略
  - **匹配过程透明**: 显示扫描页面数、匹配结果、有效链接数
  - **下载状态清晰**: 显示每个文件的下载进度、文件大小、验证状态
  - **执行摘要**: 完成后显示扫描/匹配/下载/验证的完整统计
  
  ### 自动重试机制 + AI智能分流
  - **AI智能判断网站类型**：
    - 国内网站（cde.org.cn, nmpa.gov.cn等）→ 优先直连，不走VPN
    - 国外网站（fda.gov, google.com等）→ 需要VPN代理，推荐最佳节点
    - 未知网站 → 先尝试直连，失败后再尝试VPN
  - **默认禁用自动VPN切换**：需要用户手动确认后切换节点
  - **新增国内网站直连策略**：访问国内网站失败时，自动尝试直连（不关VPN）
  - 下载失败自动重试3次（不含VPN切换）
  
  > 配置选项（修改 `scripts/web_access.py`）：
  > - `AUTO_VPN_SWITCH = False` # 禁用/启用自动VPN切换
  > - `AUTO_DIRECT_FOR_CN = True` # 禁用/启用国内网站直连
  > - `CN_SITES = [...]` # 国内网站列表
  > - `FOREIGN_SITES = [...]` # 国外网站列表
  
  ### 文件验证
  - **PDF验证**: 自动验证PDF能否正常打开（使用PyPDF2/pdfminer）
  - **Office验证**: 自动验证docx/xlsx文件头格式
  - **验证失败处理**: 文件自动删除，不保存损坏文件
  
  ### 拓展能力
  - 相同策略可应用于其他高反爬网站（需根据目标网站调整）
  - 反爬策略：非headless模式 + 增强反检测 + 随机UA + 慢速操作
  
  ### 后台运行
  - 浏览器窗口自动移至屏幕外（x=10000），不影响用户操作
  - 可在电脑上进行其他任务时静默执行下载
---

# 运行时配置

> 以下配置在代码中动态读取，可根据需要修改：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| pharma_manual | ~/Documents/工作/法规指导原则 | 手动下载（医药法规）保存目录 |
| pharma_scheduled | ~/Documents/工作/法规指导原则更新 | 监测更新（医药法规）保存目录 |
| general | ~/Documents/OpenClaw下载 | 通用下载保存目录 |

# 通用网页访问工具 (web-access)

## 文件保存规则

### 保存目录

| 类型 | 目录 | 说明 |
|------|------|------|
| 手动下载（医药法规） | `~/Documents/工作/法规指导原则/` | 非监测更新的手动下载 |
| 监测更新（医药法规） | `~/Documents/工作/法规指导原则更新/` | 包含"更新"、"监测"、"最新"等关键词 |
| 通用下载 | `~/Documents/工作/OpenClaw下载/` | 非医药类文件 |

**自动判断**：根据任务关键词判断是手动下载还是监测更新
- 关键词包含：更新、最新、监测、定期、check、new、update、monitor → 保存到"法规指导原则更新"
- 其他 → 保存到"法规指导原则"

### 文件命名格式

**医药相关文件**：`发布日期 - 完整文件标题`

示例：
```
20260318 - 药品注册管理办法.pdf
20260315 - 化学药品注射剂仿制药质量和疗效一致性评价技术要求.docx
```

## 快速开始

```bash
# 访问页面
python3 scripts/web_fetch.py visit <url>

# 获取链接
python3 scripts/web_fetch.py links <url>

# 页面截图
python3 scripts/web_fetch.py screenshot <url>
```

## 能力清单

| **VPN控制** | `vpn status/connect/rotate` | VPN操作 + 信号机制 |

## 能力清单（详细）

| 功能 | 命令 | 说明 |
|------|------|------|
| **智能导航** | `smart <关键词>` | AI智能选择最优策略找到内容 |
| **CDE下载** | `cde-date <日期>` | 按日期下载（推荐） |
| **CDE下载** | `cde-download <url>` | 通过URL下载 |
| **通用下载** | `download <url>` | 自动Cookie后下载 |
| **CDE搜索** | `cde <关键词>` | 搜索CDE指导原则 |
| **FDA搜索** | `fda <关键词>` | 搜索FDA Guidance |
| **VPN状态** | `vpn status` | 检查VPN控制是否可用 |
| **VPN切换** | `vpn rotate/random` | 手动切换节点 |
| **VPN信号** | `vpn signals` | 获取AI决策用信号 |
| **清空信号** | `vpn clear` | 清空VPN信号 |

## 使用示例

### CDE 下载（推荐）

```bash
# 按日期下载
python3 scripts/web_access.py cde-date "20260311"

# 通过URL下载
python3 scripts/web_access.py cde-download "https://www.cde.org.cn/main/..."

# 带关键词（自动判断保存位置）
python3 scripts/web_access.py cde-download "URL" --keyword "检查更新"
```

### 通用下载

```bash
# 从页面提取PDF
python3 scripts/web_access.py download "https://example.com/guidance"

# 直接下载
python3 scripts/web_access.py download "https://example.com/file.pdf"
```

### 搜索

```bash
# CDE搜索
python3 scripts/web_access.py cde "临床试验"

# FDA搜索
python3 scripts/web_access.py fda "ANDA"
```

### 🧠 智能导航（新增！）

当搜索功能找不到内容时，使用智能导航自动分析页面结构，逐级点击找到目标。

```bash
# 智能查找 - 自动选择最优策略
python3 scripts/smart_navigate.py "某药品审评报告" --site cde

# 指定目标类型
python3 scripts/smart_navigate.py "指导原则" --site cde --target pdf

# 设置最大导航深度
python3 scripts/smart_navigate.py "某内容" --site cde --depth 5

# 保存结果
python3 scripts/smart_navigate.py "某内容" --site cde -o output.html
```

#### AI智能分流（新增！）

当你（AI）调用下载任务时，可以传入 `--keyword` 参数帮助判断网站类型：

```bash
# 示例：告诉脚本任务是下载"FDA指南"
python3 scripts/web_access.py download "https://www.fda.gov/..." --keyword "FDA指南"

# 示例：告诉脚本任务是"CDE指导原则"
python3 scripts/web_access.py cde-download "https://www.cde.org.cn/..." --keyword "CDE指导原则"
```

**判断优先级：**
1. 预定义网站列表（CN_SITES / FOREIGN_SITES）
2. 任务关键词分析（--keyword 参数）
3. 域名特征推断（.cn → 国内，google → 国外）
4. 未知网站 → 记录日志，提示添加到列表

#### 智能导航工作原理

1. **AI理解需求** - 分析用户查询的内容类型（指导原则/报告/数据/药品/新闻）
2. **策略选择** - 根据内容类型决定搜索优先还是导航优先
   - 指导原则/新闻 → 搜索优先
   - 报告/数据/药品 → 导航优先
3. **智能执行** - 如果首选策略失败，自动切换到备选策略
4. **链接分析** - 分析页面链接相关性，优先点击高相关度链接

#### 内容类型识别

| 类型 | 关键词示例 | 推荐策略 |
|------|----------|---------|
| 指导原则 | 指导原则、技术要求、guidance | 搜索优先 |
| 审评报告 | 审评、报告、approval | 导航优先 |
| 临床数据 | 临床试验、数据、trial | 导航优先 |
| 药品信息 | 药品、药物、drug | 导航优先 |
| 新闻公告 | 新闻、公告、update | 搜索优先 |

### VPN 控制（信号机制）

当访问遇到封锁（403/blocked等）时，不再自动切换VPN，而是记录信号让AI决策。

```bash
# 查看状态
python3 scripts/web_access.py vpn status

# 手动切换节点
python3 scripts/web_access.py vpn rotate

# 查看VPN信号（AI读取）
python3 scripts/web_access.py vpn signals

# 清空信号
python3 scripts/web_access.py vpn clear
```

#### AI决策流程

1. **检测错误**：访问遇到403/blocked等错误
2. **记录信号**：web_access自动记录VPN信号（包含域名、错误类型、推荐节点）
3. **AI读取**：AI调用`vpn signals`获取信号
4. **选择节点**：根据网站类型选择合适节点（FDA→美国，EMA→欧洲）
5. **调用skill**：AI调用vpn-control skill切换节点

## 详细文档

- [反爬技术详解](./references/anti-bot.md)
- [输出目录配置](./references/output-config.md)
- [已验证网站](./references/supported-sites.md)
- [错误处理](./references/error-handling.md)
- [网站导航配置](./references/site_navigation.yaml) 🆕 - 常用网站导航路径

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `web_access.py` | 完整版 - 通用下载 + CDE专用 |
| `web_fetch.py` | 简化版 - 轻量级访问 |
| `smart_navigate.py` | 🧠 智能导航 - AI驱动的内容发现 |
