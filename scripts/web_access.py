#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.6.5 (2026-03-20)
更新: 搜索+导航并行，AI智能导航

"""

import asyncio
import sys
import re
import os
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests

# ==================== 配置 ====================
CONFIG = {
    'headless': False,  # 设置为True可隐藏浏览器
}

# 浏览器参数
BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-plugins',
    '--disable-images',  # 禁用图片加速加载
]

# 反检测脚本
ANTIDETECT_SCRIPT = '''
    Object.defineProperty(navigator, "webdriver", {get: () => undefined});
    window.chrome = {runtime: {}};
'''

# CDE默认关键词
CDE_DEFAULT_KEYWORDS = "指导原则 法规 征求意见稿"

# CDE导航URL映射（根据意图智能选择）
CDE_NAV_INTENTS = {
    '指导原则': [
        ('指导原则专栏', 'https://www.cde.org.cn/zdyz/index'),
        ('指导原则数据库', 'https://www.cde.org.cn/zdyz/domestic'),
    ],
    '沟通交流': [
        ('政策法规', 'https://www.cde.org.cn/main/policy/'),
    ],
    '征求意见': [
        ('征求意见', 'https://www.cde.org.cn/main/news/listpage/9f9c239c4e4f9f6708a079ec6443f60e'),
    ],
    '政策法规': [
        ('政策法规', 'https://www.cde.org.cn/main/policy/'),
    ],
    '注册': [
        ('注册受理', 'https://www.cde.org.cn/main/xxgk/listpage/2f78f372d351c6851af7431c7710286e'),
    ],
}

# 相关性关键词
CDE_RELEVANT_KEYWORDS = [
    '指导原则', '技术指导原则', '技术要求', '技术指南', 
    '征求意见稿', '草案', '试行',
    '法律法规', '管理办法', '规定', '细则',
    '药品', '药物', '制剂', '仿制药', '新药', '创新药',
    '生物制品', '疫苗', '细胞治疗', '抗体', '蛋白',
    '肿瘤', '罕见病', '儿童', '临床', '研发', '质量', '审评', '注册',
]

# User-Agent池
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

async def get_cookie_light(context, base_url):
    """轻量级获取Cookie"""
    try:
        resp = await context.request.get(base_url, timeout=10000)
        cookies = await context.cookies()
        return {c['name']: c['value'] for c in cookies}
    except:
        return {}

def detect_intent(keyword):
    """AI识别用户搜索意图"""
    kw = keyword.lower()
    intents = []
    
    intent_map = {
        '指导原则': ['指导原则', '技术要求', '技术指南'],
        '沟通交流': ['沟通交流', '会议', '申请', '交流'],
        '征求意见': ['征求意见', '草案', '征求'],
        '政策法规': ['法规', '政策', '办法', '细则'],
        '注册': ['注册', '申报', '审批'],
    }
    
    for intent, keywords in intent_map.items():
        if any(k in kw for k in keywords):
            intents.append(intent)
    
    return intents if intents else ['指导原则', '政策法规']

async def search_cde(keyword, page):
    """CDE搜索框搜索"""
    results = []
    seen = set()
    
    try:
        # 访问首页
        await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
        await asyncio.sleep(3)
        
        search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)
        
        # 搜索
        await search_input.fill(keyword)
        await asyncio.sleep(1)
        await search_input.press('Enter')
        await asyncio.sleep(8)
        
        # 获取结果
        links = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'))
                .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
        }''')
        
        for link in links:
            if link['href'] not in seen:
                seen.add(link['href'])
                results.append({**link, 'source': '搜索'})
        
        log(f"  搜索'{keyword}': +{len(links)} 条")
    except Exception as e:
        log(f"  搜索失败: {str(e)[:30]}")
    
    return results

async def navigate_cde(keyword, page):
    """CDE智能导航"""
    results = []
    seen = set()
    
    # 识别意图
    intents = detect_intent(keyword)
    log(f"  🤖 识别意图: {intents}")
    
    # 收集导航URL
    nav_pages = []
    for intent in intents:
        if intent in CDE_NAV_INTENTS:
            nav_pages.extend(CDE_NAV_INTENTS[intent])
    
    # 去重
    nav_pages = list(dict.fromkeys(nav_pages))
    
    log(f"  📍 智能导航: {len(nav_pages)} 个位置")
    
    for nav_name, nav_url in nav_pages:
        try:
            await page.goto(nav_url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(3)
            
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'))
                    .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
            }''')
            
            new_count = 0
            for link in links:
                if link['href'] not in seen:
                    seen.add(link['href'])
                    results.append({**link, 'source': f'导航-{nav_name}'})
                    new_count += 1
            
            if new_count > 0:
                log(f"      {nav_name}: +{new_count} 条")
        except Exception as e:
            log(f"      {nav_name} 失败")
    
    return results

def filter_relevant(links):
    """相关性过滤"""
    relevant = []
    for link in links:
        text = link.get('text', '').lower()
        if any(kw in text for kw in CDE_RELEVANT_KEYWORDS):
            relevant.append(link)
    return relevant

async def download_cde(keyword):
    """CDE搜索+导航主函数"""
    log(f"🔍 CDE搜索: {keyword}")
    log(f"📂 保存到: ~/Documents/工作/法规指导原则")
    
    async with asyncio.Lock():
        async with asyncio.Lock():
            pass
    
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(user_agent=random.choice(UA_POOL))
        page = await context.new_page()
        await page.add_init_script(ANTIDETECT_SCRIPT)
        
        all_results = []
        seen = set()
        
        # 方式1: 搜索框搜索
        log("→ 方式1: 搜索框搜索...")
        search_results = await search_cde(keyword, page)
        for link in search_results:
            if link['href'] not in seen:
                seen.add(link['href'])
                all_results.append(link)
        
        # 方式2: 智能导航
        log("→ 方式2: 智能导航...")
        nav_results = await navigate_cde(keyword, page)
        for link in nav_results:
            if link['href'] not in seen:
                seen.add(link['href'])
                all_results.append(link)
        
        log(f"✓ 共收集 {len(all_results)} 条记录")
        
        # 相关性过滤
        relevant = filter_relevant(all_results)
        log(f"✓ 相关内容: {len(relevant)} 条")
        
        # 显示结果
        print("\n" + "=" * 60)
        print("📋 搜索结果")
        print("=" * 60)
        
        # 按来源分组显示
        sources = {}
        for r in relevant:
            src = r.get('source', '未知')
            if src not in sources:
                sources[src] = []
            sources[src].append(r['text'][:60])
        
        for src, texts in sources.items():
            print(f"\n【{src}】({len(texts)}条)")
            for t in texts[:8]:
                print(f"  • {t}")
        
        # 去重
        unique = []
        seen = set()
        for r in relevant:
            if r['href'] not in seen:
                seen.add(r['href'])
                unique.append(r)
        
        log(f"\n✓ 去重后共 {len(unique)} 个待下载链接")
        
        await browser.close()
    
    return unique

async def main():
    print("=" * 50)
    print("web-access skill v1.6.5 (2026-03-20)")
    print("=" * 50)
    
    if len(sys.argv) < 3:
        print("\n使用方法:")
        print("  python web_access.py cde <关键词>")
        print("  python web_access.py cde 沟通交流")
        print("  python web_access.py cde 3月9日")
        print("  python web_access.py cde 临床试验")
        return
    
    action = sys.argv[1]
    keyword = sys.argv[2] if len(sys.argv) > 2 else ""
    
    if action == "cde":
        await download_cde(keyword)
    else:
        print(f"未知动作: {action}")
    
    print("\n✅ 完成")

if __name__ == "__main__":
    asyncio.run(main())
