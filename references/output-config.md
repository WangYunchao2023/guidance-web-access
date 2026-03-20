# 输出目录配置

## 配置原理

下载目录从统一配置文件读取，方便统一管理和修改。

## YAML 配置格式

```yaml
output:
  # 医药相关（法规/指导原则/审评动态/药品信息等）- 定时任务（自动监测）
  pharma_scheduled: "~/Documents/工作/法规指导原则更新"
  
  # 医药相关（法规/指导原则/审评动态/药品信息等）- 手动下载
  pharma_manual: "~/Documents/工作/法规指导原则"
  
  # 通用下载（非医药类）
  general: "~/Documents/OpenClaw下载"
```

## 实际输出目录

| 类型 | 位置 |
|------|------|
| 医药相关 - 更新监测 | `~/Documents/工作/法规指导原则更新/` |
| 医药相关 - 手动下载 | `~/Documents/工作/法规指导原则/` |
| 通用下载 | `~/Documents/OpenClaw下载/` |

## 使用方式

### 命令行指定

```bash
# 手动下载（默认）
python3 scripts/web_access.py cde-download "URL"
# → 保存到: ~/Documents/工作/法规指导原则/

# 检查更新（定时任务）
python3 scripts/web_access.py cde-download "URL" --keyword "检查更新"
# → 保存到: ~/Documents/工作/法规指导原则更新/

# 通用下载
python3 scripts/web_access.py download "URL"
# → 保存到: ~/Documents/OpenClaw下载/
```

### keyword 关键词映射

| keyword | 输出目录 |
|---------|----------|
| 检查更新 / 监测 / 定时 | 法规指导原则更新 |
| 手动 / 下载 / 其他 | 法规指导原则 |
| (非医药类) | OpenClaw下载 |

## 修改配置

如需修改默认目录，编辑 `scripts/web_access.py` 中的配置：

```python
OUTPUT_CONFIG = {
    "pharma_scheduled": "~/Documents/工作/法规指导原则更新",
    "pharma_manual": "~/Documents/工作/法规指导原则",
    "general": "~/Documents/OpenClaw下载"
}
```
