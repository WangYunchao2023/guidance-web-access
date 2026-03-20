#!/usr/bin/env python3
"""
web-access skill - 简化版 v1.6.5
"""

import asyncio
import sys
import re
import os
from pathlib import Path

print("=" * 50)
print("web-access skill v1.6.5 (2026-03-20)")
print("=" * 50)

async def main():
    if len(sys.argv) < 3:
        print("使用方法: python web_access.py cde <关键词>")
        print("示例: python web_access.py cde 沟通交流")
        return
    
    action = sys.argv[1]
    keyword = sys.argv[2] if len(sys.argv) > 2 else ""
    
    if action == "cde":
        from playwright.async_api import async_playwright
        import random
        
        print(f"🔍 搜索CDE: {keyword}")
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            
            # 访问首页
            await page.goto("https://www.cde.org.cn", timeout=60000)
            await asyncio.sleep(5)
            
            # 搜索
            search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)
            await search_input.fill(keyword)
            await asyncio.sleep(1)
            await search_input.press('Enter')
            await asyncio.sleep(8)
            
            # 获取结果
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'))
                    .slice(0, 20).map(a => ({text: a.innerText?.trim() || '', href: a.href}));
            }''')
            
            print(f"\n找到 {len(links)} 条结果:\n")
            for i, l in enumerate(links[:15], 1):
                print(f"{i}. {l['text'][:60]}")
            
            await browser.close()
    
    print("\n✅ 完成")

if __name__ == "__main__":
    asyncio.run(main())
