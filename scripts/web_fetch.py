#!/usr/bin/env python3
"""
通用网页访问工具 - 统一入口（增强版）
使用 Playwright 进行浏览器自动化，支持任意网站访问和下载
整合了browser_tool.py的完整反检测功能
"""

import asyncio
import sys
import os
import re
import subprocess
import random
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ============ 增强反检测配置 ============
VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]

ANTIDETECT_SCRIPT = '''
// 移除webdriver属性
Object.defineProperty(navigator, "webdriver", {get: () => undefined});
// 模拟插件
const plugins = [];
for (let i = 0; i < Math.floor(Math.random() * 3) + 3; i++) {
    plugins.push({name: "Plugin " + i, filename: "plugin" + i + ".dll", description: "Plugin description"});
}
Object.defineProperty(navigator, "plugins", {get: () => plugins});
Object.defineProperty(navigator, "language", {get: () => "zh-CN"});
// 移除自动化特征
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
window.chrome = {runtime: {}};
'''

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--disable-setuid-sandbox",
    "--disable-background-networking",
    "--disable-extensions",
    "--disable-sync",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--ignore-certificate-errors",
]

CONFIG = {
    'headless': True,
    'timeout': 60000,
}

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    print(f"[{get_timestamp()}] {msg}")

def verify_pdf(filepath):
    """验证PDF是否能正常打开"""
    try:
        import PyPDF2
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            _ = reader.pages[0]
        return True, "OK"
    except:
        pass
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(filepath, maxpages=1)
        if len(text) > 10:
            return True, "OK"
    except:
        pass
    return False, "Invalid PDF"

async def visit_url(url, action='content'):
    """访问URL并执行操作（增强版）"""
    viewport = random.choice(VIEWPORT_POOL)
    user_agent = random.choice(UA_POOL)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale='zh-CN',
        )
        page = await context.new_page()
        
        # 注入反检测脚本
        await page.add_init_script(ANTIDETECT_SCRIPT)
        
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=CONFIG['timeout'])
            # 随机等待模拟真实用户
            await asyncio.sleep(random.uniform(2, 5))
            
            if action == 'content':
                content = await page.evaluate('''() => {
                    return document.body.innerText || document.body.textContent || '';
                }''')
                print(content[:5000])
                
            elif action == 'title':
                title = await page.title()
                print(title)
                
            elif action == 'links':
                links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({text: a.textContent?.trim() || '', href: a.href}))
                        .filter(l => l.href);
                }''')
                for link in links[:50]:
                    print(f"{link['text'][:50]}: {link['href']}")
            
            elif action == 'screenshot':
                filename = f"screenshot.png"
                await page.screenshot(path=filename)
                print(f"截图保存到: {filename}")
            
            elif action == 'pdf':
                pdf_links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href$=".pdf"]'))
                        .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
                }''')
                print(f"找到 {len(pdf_links)} 个PDF链接:")
                for link in pdf_links[:20]:
                    print(f"  {link['text'][:60]}: {link['href']}")
            
            elif action == 'download':
                # 下载当前页面或页面中的PDF链接
                output_dir = Path.home() / "Documents" / "下载文件"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # 获取PDF链接
                pdf_links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href$=".pdf"]'))
                        .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
                }''')
                
                log(f"找到 {len(pdf_links)} 个PDF链接")
                
                for i, link in enumerate(pdf_links[:10], 1):
                    href = link['href']
                    filename = re.sub(r'[<>:"/\\|?*]', '_', link['text'][:80]) + '.pdf'
                    if not filename.endswith('.pdf'):
                        filename = f"download_{i}.pdf"
                    
                    filepath = output_dir / filename
                    log(f"[{i}/{len(pdf_links)}] 下载: {filename}")
                    
                    try:
                        async with page.request.get(href) as response:
                            if response.status == 200:
                                content = await response.body()
                                with open(filepath, 'wb') as f:
                                    f.write(content)
                                
                                is_valid, msg = verify_pdf(str(filepath))
                                if is_valid:
                                    size = len(content)
                                    log(f"  ✓ {filename} ({size} bytes) - 验证通过")
                                else:
                                    log(f"  ✗ 损坏已删除: {msg}")
                                    filepath.unlink(missing_ok=True)
                            else:
                                log(f"  ✗ HTTP {response.status}")
                    except Exception as e:
                        log(f"  ✗ 错误: {str(e)[:50]}")
                    
                    await page.wait_for_timeout(500)
                
                log(f"完成! 文件保存在: {output_dir}")
                
        except Exception as e:
            print(f"错误: {e}", file=sys.stderr)
        finally:
            await browser.close()

async def main():
    if len(sys.argv) < 3:
        print("使用方法:")
        print("  python web_fetch.py visit <url>        # 访问页面")
        print("  python web_fetch.py title <url>      # 获取标题")
        print("  python web_fetch.py links <url>      # 获取链接")
        print("  python web_fetch.py screenshot <url>  # 截图")
        print("  python web_fetch.py pdf <url>         # 查找PDF链接")
        print("  python web_fetch.py download <url>     # 下载PDF文件")
        sys.exit(1)
    
    action = sys.argv[1]
    url = sys.argv[2]
    
    await visit_url(url, action)

if __name__ == "__main__":
    asyncio.run(main())
