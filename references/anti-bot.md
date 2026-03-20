# 反爬绕过技术详解

本文档详细介绍 web-access 技能使用的反爬绕过技术。

## 核心策略

### 1. Cookie 预获取（轻量级）

**原理**：先访问网站轻量级页面（robots.txt/favicon.ico）获取Cookie，避免加载大量资源

**优化策略**（按优先级）：
1. 先尝试访问 `/robots.txt`（最小、最快，通常必存在）
2. 失败则访问 `/favicon.ico`（图标文件，很小）
3. 再失败才访问首页作为后备

**实现**：
```python
# 轻量级获取Cookie函数
async def get_cookie_light(context, base_url):
    light_pages = ["/robots.txt", "/favicon.ico"]
    for light_page in light_pages:
        # 尝试访问轻量页面
        resp = await context.request.get(urljoin(base_url, light_page))
        if resp.status in [200, 304, 404]:  # 即使404也说明会话建立了
            cookies = await context.cookies()
            if cookies:
                return {c['name']: c['value'] for c in cookies}
    # 后备：访问首页
    return await fallback_get_cookie(context, base_url)
```

**优势**：
- 减少网络请求量
- 降低被反爬检测的概率
- 加快整体获取速度

### 2. 随机 User-Agent

**原理**：从 UA 池随机选择，模拟不同浏览器

**常用 UA 池**：
```python
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0",
]
```

### 3. 随机视口

**原理**：使用不同尺寸视口，模拟不同设备

```python
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]
```

### 4. 简化反检测

**原则**：避免复杂脚本导致加载异常

- 优先使用 requests 而非 Playwright（除非必要）
- 简化浏览器设置，减少可检测特征
- 避免使用过于"完美"的配置

## 高级技术

### 5. 请求间隔

添加随机延迟：
```python
import time
import random

delay = random.uniform(1, 3)
time.sleep(delay)
```

### 6. 失败重试

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_with_retry(url):
    return session.get(url)
```

### 7. VPN信号机制（AI决策）

不再硬编码VPN调用，改为信号机制让AI决定：

```python
# 检测到需要VPN时，记录信号
need_vpn(url, error_type, error_msg, context="下载失败")

# AI读取信号
signals = vpn_signal_manager.get_signals()
# 输出示例:
# [1] fda.gov | 403 | 建议: 调用 vpn-control skill，连接 美国 节点
```

**节点推荐映射**：
- FDA/NIH/CDC → 美国
- EMA/ICH → 欧洲/德国
- WHO → 欧洲/瑞士
- PMDA → 日本

### 8. IP 轮换

通过 VPN 切换节点：
```bash
python3 scripts/web_access.py vpn rotate
```

## 网站特定策略

### CDE (药品审评中心)

- **Cookie 获取**：访问 `https://www.cde.org.cn/` 首页
- **无需复杂反爬**：国内网站反爬相对宽松
- **PDF 验证**：下载后验证文件完整性

### NMPA (国家药监局)

- **Cookie 获取**：访问 `https://www.nmpa.gov.cn/`
- **需要验证**：部分页面有访问限制

### FDA

- **必须 VPN**：国内直接访问会被拦截
- **推荐方式**：先连接 VPN 再访问

### 国外药企官网

- **常见反爬**：Cloudflare、Akamai
- **解决方案**：使用 Playwright 渲染模式
