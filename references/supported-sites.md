# 已验证网站列表

本文档列出 web-access 技能已验证支持的网站。

## 状态说明

| 状态 | 含义 |
|------|------|
| ✅ 完全支持 | 可直接使用所有功能 |
| ⚠️ 需要VPN | 需要先连接VPN |
| ❌ 不支持 | 暂未验证或无法访问 |

## 国内网站

### ✅ CDE - 药品审评中心

- **URL**: https://www.cde.org.cn/
- **支持功能**: 全文搜索、指导原则下载、审评动态
- **推荐命令**: `cde-download` / `cde-date`
- **成功率**: 高
- **备注**: 国内访问无限制，有专用下载命令

### ✅ NMPA - 国家药品监督管理局

- **URL**: https://www.nmpa.gov.cn/
- **支持功能**: 药品信息、政策法规查询
- **推荐命令**: `download`
- **成功率**: 高

### ✅ 医药之光

- **URL**: https://www.yiguangzhi.cn/
- **支持功能**: 指导原则下载
- **推荐命令**: `download`
- **成功率**: 高

## 国外网站

### ⚠️ FDA - 美国食品药品监督管理局

- **URL**: https://www.fda.gov/
- **支持功能**: Guidance 搜索、下载
- **推荐命令**: `fda`
- **成功率**: 需要VPN
- **备注**: 国内直接访问受限

### ⚠️ EMA - 欧洲药品管理局

- **URL**: https://www.ema.europa.eu/
- **支持功能**: 指南下载
- **推荐命令**: `download`
- **成功率**: 需要VPN

### ⚠️ ICH

- **URL**: https://www.ich.org/
- **支持功能**: ICH 指南
- **推荐命令**: `download`
- **成功率**: 需要VPN

### ⚠️ WHO

- **URL**: https://www.who.int/
- **支持功能**: 指南下载
- **推荐命令**: `download`
- **成功率**: 需要VPN

## 其他网站

| 网站 | 状态 | 说明 |
|------|------|------|
| Google | ❌ | 需要VPN |
| YouTube | ❌ | 需要VPN |
| GitHub | ⚠️ | 部分功能需要VPN |
| Stack Overflow | ⚠️ | 需要VPN |

## 新网站测试

如需测试新网站是否支持：

```bash
# 1. 先尝试简单访问
python3 scripts/web_fetch.py title "https://example.com"

# 2. 尝试获取链接
python3 scripts/web_fetch.py links "https://example.com"

# 3. 尝试下载
python3 scripts/web_access.py download "https://example.com/page"
```

如遇问题，可参考 [anti-bot.md](./anti-bot.md) 和 [error-handling.md](./error-handling.md)。
