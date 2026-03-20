#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.7.0 (2026-03-20)
更新: 优化搜索关键词策略、专栏内搜索、翻页查找、结果合并过滤

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

# CDE导航URL映射（根据意图智能选择）- 改进版本
CDE_NAV_INTENTS = {
    '指导原则': [
        ('指导原则专栏', 'https://www.cde.org.cn/zdyz/index'),
        ('指导原则数据库', 'https://www.cde.org.cn/zdyz/domestic'),
        ('国内指导原则', 'https://www.cde.org.cn/zdyz/listpage/9cd8db3b7530c6fa0c86485e563f93c7'),
    ],
    '沟通交流': [
        ('沟通交流', 'https://www.cde.org.cn/main/xxgk/listpage/2f78f372d351c6851af7431c7710286e'),
        ('指导原则', 'https://www.cde.org.cn/zdyz/index'),  # 沟通交流相关指导原则
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
    '发布通告': [
        ('发布通告', 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d'),
    ],
}

# 关键词缩短策略 - 搜索失败时按此顺序尝试
KEYWORD_SHORTEN_STRATEGY = [
    lambda k: k,                          # 原始关键词
    lambda k: k.replace('指导原则', '').replace('技术要求', '').replace('技术指南', '').strip(),
    lambda k: k.replace('征求意见稿', '').replace('公开征求', '').replace('（征求意见稿）', '').strip(),
    lambda k: ''.join([c for c in k if not c.isdigit]).replace('年月日', '').strip(),  # 去掉日期
    lambda k: k.split()[0] if k.split() else k,  # 只取第一个词
]

# 相关性关键词
CDE_RELEVANT_KEYWORDS = [
    '指导原则', '技术指导原则', '技术要求', '技术指南',
    '征求意见稿', '草案', '试行',
    '法律法规', '管理办法', '规定', '细则',
    '药品', '药物', '制剂', '仿制药', '新药', '创新药',
    '生物制品', '疫苗', '细胞治疗', '抗体', '蛋白',
    '肿瘤', '罕见病', '儿童', '临床', '研发', '质量', '审评', '注册',
    '沟通交流', '会议', '交流', '通告', '发布',
]

# User-Agent池
UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def generate_search_keywords(keyword):
    """生成搜索关键词列表（按优先级）"""
    keywords = []
    for strategy in KEYWORD_SHORTEN_STRATEGY:
        kw = strategy(keyword)
        if kw and kw not in keywords:
            keywords.append(kw)
    return keywords

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

    # 优先级判断 - 根据关键词判断最相关的意图
    if '沟通' in kw or '交流' in kw:
        intents = ['沟通交流', '指导原则', '发布通告']
    elif '3月' in kw or '9日' in kw or '2026' in kw:
        intents = ['发布通告', '指导原则']
    elif '征求' in kw or '草案' in kw:
        intents = ['征求意见', '指导原则']
    elif '法规' in kw or '政策' in kw:
        intents = ['政策法规', '指导原则']
    elif '注册' in kw or '申报' in kw:
        intents = ['注册', '政策法规']
    else:
        intents = ['指导原则', '发布通告', '征求意见']

    return intents

async def search_in_page(page, keyword):
    """在当前页面内搜索"""
    results = []
    seen = set()

    try:
        # 尝试找到搜索框
        search_input = await page.query_selector('input[placeholder*="关键词"]')
        if not search_input:
            search_input = await page.query_selector('input[type="text"]')

        if search_input:
            await search_input.fill(keyword)
            await asyncio.sleep(1)
            await search_input.press('Enter')
            await asyncio.sleep(8)

            # 获取搜索结果
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                    .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
            }''')

            for link in links:
                if link['href'] not in seen and link['text']:
                    seen.add(link['href'])
                    results.append({**link, 'source': '页面搜索'})
    except Exception as e:
        pass

    return results

async def get_page_links(page, source_name):
    """获取当前页面的所有链接"""
    results = []
    seen = set()

    try:
        links = await page.evaluate('''(sourceName) => {
            return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                .slice(0, 50).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
        }''', source_name)

        for link in links:
            if link['href'] not in seen and link['text']:
                seen.add(link['href'])
                results.append({**link, 'source': source_name})
    except Exception as e:
        log(f"    获取链接失败: {str(e)[:30]}")

    return results

async def navigate_and_search_in_column(page, keyword, column_name, column_url, max_pages=3):
    """在专栏内导航+搜索+翻页"""
    results = []
    seen = set()

    try:
        log(f"    → 进入{column_name}...")
        await page.goto(column_url, wait_until='networkidle', timeout=60000)
        await asyncio.sleep(5)

        # 尝试在专栏内搜索
        search_results = await search_in_page(page, keyword)
        for link in search_results:
            if link['href'] not in seen:
                seen.add(link['href'])
                results.append(link)

        # 如果搜索没结果，获取页面所有链接
        if not results:
            page_links = await get_page_links(page, f'专栏-{column_name}')
            results.extend(page_links)

        # 翻页查找
        for page_num in range(2, max_pages + 1):
            try:
                # 尝试点击下一页
                next_btn = await page.query_selector('a:has-text("下一页"), button:has-text("下一页")')
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(5)

                    page_links = await get_page_links(page, f'专栏-{column_name}[{page_num}]')
                    for link in page_links:
                        if link['href'] not in seen:
                            seen.add(link['href'])
                            results.append(link)

                    log(f"      第{page_num}页: +{len(page_links)} 条")
            except:
                break

        log(f"      {column_name}: 共 +{len(results)} 条")

    except Exception as e:
        log(f"      {column_name} 失败: {str(e)[:30]}")

    return results

async def search_cde(keyword, page):
    """CDE搜索框搜索 - 带关键词缩短策略"""
    results = []
    seen = set()

    # 生成关键词列表（按优先级尝试）
    keywords = generate_search_keywords(keyword)
    log(f"  🔑 关键词策略: {keywords}")

    for kw in keywords:
        if kw:
            try:
                log(f"    尝试搜索: '{kw}'")
                await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
                await asyncio.sleep(3)

                search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)

                # 搜索
                await search_input.fill(kw)
                await asyncio.sleep(1)
                await search_input.press('Enter')
                await asyncio.sleep(8)

                # 获取结果
                links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                        .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
                }''')

                new_count = 0
                for link in links:
                    if link['href'] not in seen and link['text']:
                        seen.add(link['href'])
                        results.append({**link, 'source': '搜索'})
                        new_count += 1

                log(f"      搜索'{kw}': +{new_count} 条")

                # 如果找到结果就停止
                if new_count > 0:
                    break

            except Exception as e:
                log(f"      搜索'{kw}'失败: {str(e)[:30]}")
                continue

    return results

async def navigate_cde(keyword, page):
    """CDE智能导航 - 改进版：进入专栏内搜索+翻页"""
    results = []
    seen = set()

    # 识别意图
    intents = detect_intent(keyword)
    log(f"  🤖 识别意图: {intents}")

    # 收集导航URL（根据意图排序）
    nav_pages = []
    for intent in intents:
        if intent in CDE_NAV_INTENTS:
            for item in CDE_NAV_INTENTS[intent]:
                if item not in nav_pages:
                    nav_pages.append(item)

    log(f"  📍 智能导航: {len(nav_pages)} 个位置")

    # 在每个专栏内搜索+翻页
    for nav_name, nav_url in nav_pages:
        col_results = await navigate_and_search_in_column(page, keyword, nav_name, nav_url, max_pages=3)
        for link in col_results:
            if link['href'] not in seen:
                seen.add(link['href'])
                results.append(link)

    return results

def filter_relevant(links, keyword):
    """相关性过滤 - 结合关键词"""
    relevant = []
    keyword_lower = keyword.lower()

    # 核心关键词（必须包含）
    core_keywords = ['指导原则', '技术要求', '技术指南', '沟通交流', '会议', '通告']

    # 检查关键词是否包含核心词
    has_core = any(kw in keyword_lower for kw in core_keywords)

    for link in links:
        text = link.get('text', '').lower()

        if has_core:
            # 如果搜索有关键词，必须包含搜索词
            if any(kw in text for kw in CDE_RELEVANT_KEYWORDS):
                relevant.append(link)
        else:
            # 没有核心关键词，只保留高相关度
            match_count = sum(1 for kw in CDE_RELEVANT_KEYWORDS if kw in text)
            if match_count >= 2:
                relevant.append(link)

    return relevant

def merge_and_deduplicate(all_results):
    """合并结果并去重"""
    seen = set()
    unique = []

    for link in all_results:
        if link['href'] not in seen:
            seen.add(link['href'])
            unique.append(link)

    return unique

async def download_cde(keyword):
    """CDE搜索+导航主函数 - 改进版"""
    log(f"🔍 CDE搜索: {keyword}")
    log(f"📂 保存到: ~/Documents/工作/法规指导原则")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(user_agent=random.choice(UA_POOL))
        page = await context.new_page()
        await page.add_init_script(ANTIDETECT_SCRIPT)

        all_results = []

        # 方式1: 搜索框搜索（带关键词缩短策略）
        log("→ 方式1: 搜索框搜索...")
        search_results = await search_cde(keyword, page)
        all_results.extend(search_results)

        # 方式2: 智能导航（在专栏内搜索+翻页）
        log("→ 方式2: 智能导航（专栏内搜索+翻页）...")
        nav_results = await navigate_cde(keyword, page)
        all_results.extend(nav_results)

        log(f"✓ 共收集 {len(all_results)} 条记录")

        # 合并去重
        unique_results = merge_and_deduplicate(all_results)
        log(f"✓ 去重后: {len(unique_results)} 条")

        # 相关性过滤
        relevant = filter_relevant(unique_results, keyword)
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
            sources[src].append(r['text'][:70])

        for src, texts in sources.items():
            print(f"\n【{src}】({len(texts)}条)")
            for t in texts[:10]:
                print(f"  • {t}")

        log(f"\n✓ 最终 {len(relevant)} 个待下载链接")

        await browser.close()

    return relevant

async def main():
    print("=" * 50)
    print("web-access skill v1.7.0 (2026-03-20)")
    print("  优化版: 关键词策略+专栏搜索+翻页")
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
