# 错误处理指南

本文档列出常见错误及其解决方案。

## 常见错误

### 1. Timeout (超时)

**错误信息**：
```
requests.exceptions.Timeout: HTTPSConnectionPool
```

**原因**：
- 网络连接慢
- 服务器响应慢
- 网站反爬限制

**解决方案**：
```python
# 增加超时时间
session.get(url, timeout=30)  # 默认10秒 → 30秒
```

### 2. 412 Precondition Failed

**错误信息**：
```
HTTP Error 412: Precondition Failed
```

**原因**：
- 网站检测到异常请求
- Cookie 过期
- 反爬触发

**解决方案**：
- 使用 `--wait` 参数增加等待时间
- 使用 `networkidle` 策略
- 重新获取 Cookie

### 3. 400 Bad Request

**错误信息**：
```
HTTP Error 400: Bad Request
```

**原因**：
- 请求格式不正确
- URL 编码问题
- 请求头异常

**解决方案**：
```python
# 规范化URL
from urllib.parse import urljoin, urlparse

# 检查Referer
headers["Referer"] = base_url
```

### 4. 返回 HTML 而非 PDF

**错误现象**：
- 下载的文件是 HTML
- 文件无法用 PDF 阅读器打开

**原因**：
- 目标需要登录
- 直接链接是页面而非文件
- Cookie 未正确传递

**解决方案**：
```bash
# 使用页面模式（自动从页面提取PDF链接）
python3 scripts/web_access.py download "https://example.com/guidance-page"

# 而不是直接下载
python3 scripts/web_access.py download "https://example.com/file.pdf"
```

### 5. VPN 不可用

**错误现象**：
- 连接被拒绝
- 无法解析域名

**解决方案**：
```bash
# 检查VPN状态
python3 scripts/web_access.py vpn status

# 连接VPN
python3 scripts/web_access.py vpn connect

# 切换节点
python3 scripts/web_access.py vpn rotate
```

### 6. SSL 证书错误

**错误信息**：
```
requests.exceptions.SSLError: certificate verify failed
```

**解决方案**：
```python
# 忽略SSL验证（仅开发环境使用）
session.verify = False
# 或
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
```

## 错误码速查

| 错误码 | 含义 | 解决思路 |
|--------|------|----------|
| 301 | 永久重定向 | 跟随重定向 |
| 302 | 临时重定向 | 跟随重定向 |
| 400 | 请求错误 | 检查URL和参数 |
| 401 | 需要认证 | 检查Cookie |
| 403 | 禁止访问 | 更换IP/Cookie |
| 404 | 页面不存在 | 检查URL |
| 412 | 反爬触发 | 增加等待/更换UA |
| 429 | 请求过多 | 降低频率 |
| 500 | 服务器错误 | 重试 |
| 502 | 网关错误 | 重试 |
| 503 | 服务不可用 | 重试 |

## 调试技巧

### 开启调试模式

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 打印请求详情

```python
# 打印响应头
print(response.headers)

# 打印请求头
print(response.request.headers)
```

### 保存调试信息

```bash
# 保存页面内容用于分析
python3 scripts/web_fetch.py visit "URL" > debug.html
```
