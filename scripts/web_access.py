#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.7.3 (2026-03-20)
更新: 修复层级深入查找 - 正确获取详情页日期

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
    'headless': False,
}

BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-plugins',
    '--disable-images',
]

ANTIDETECT_SCRIPT = '''
    Object.defineProperty(navigator, "webdriver", {get: () => undefined});
    window.chrome = {runtime: {}};
'''

CDE_ENTRY_PAGES = {
    '首页': 'https://www.cde.org.cn',
    '指导原则专栏': 'https://www.cde.org.cn/zdyz/index',
    '指导原则数据库': 'https://www.cde.org.cn/zdyz/domestic',
    '发布通告': 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d',
    '征求意见': 'https://www.cde.org.cn/main/news/listpage/9f9c239c4e4f9f6708a079ec6443f60e',
}

KEYWORD_SHORTEN_STRATEGY = [
    lambda k: k,
    lambda k: k.replace('指导原则', '').replace('技术要求', '').replace('技术指南', '').strip(),
    lambda k: k.replace('征求意见稿', '').replace('公开征求', '').replace('（征求意见稿）', '').strip(),
    lambda k: re.sub(r'\d+', '', k).replace('年月日', '').strip() if k else k,
    lambda k: k.split()[0] if k and k.split() else k,
    lambda k: '发布' if re.search(r'\d+月\d*日?', k) else k,
]

CN_TO_EN_VARIANTS = {
    '指导原则': ['guidance', 'guideline', 'document'],
    '沟通交流': ['communication', 'meeting', 'consultation'],
    '临床试验': ['clinical trial', 'clinical study'],
}

CDE_RELEVANT_KEYWORDS = [
    '指导原则', '技术指导原则', '技术要求', '技术指南',
    '征求意见稿', '草案', '试行',
    '药品', '药物', '制剂', '仿制药', '新药', '创新药',
    '生物制品', '疫苗', '细胞治疗', '抗体', '蛋白',
    '肿瘤', '罕见病', '儿童', '临床', '研发', '质量', '审评', '注册',
    '沟通交流', '会议', '交流', '通告', '发布',
]

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def generate_search_keywords(keyword, target_site=''):
    keywords = []
    for strategy in KEYWORD_SHORTEN_STRATEGY:
        kw = strategy(keyword)
        if kw and kw not in keywords:
            keywords.append(kw)
    if target_site:
        for cn, en_list in CN_TO_EN_VARIANTS.items():
            if cn in keyword:
                for en in en_list:
                    if en not in keywords:
                        keywords.append(en)
    return keywords

def should_translate(target_site):
    foreign_sites = ['fda.gov', 'ema.europa.eu', 'who.int', 'ich.org']
    return any(site in target_site.lower() for site in foreign_sites)

def generate_translated_keywords(keyword, target_site):
    keywords = []
    if target_site and should_translate(target_site):
        for cn, en_list in CN_TO_EN_VARIANTS.items():
            if cn in keyword:
                keywords.extend([e for e in en_list if e not in keywords])
    return keywords

def score_link(link_text, keyword):
    text = link_text.lower()
    kw = keyword.lower()
    score = 0
    for word in kw.split():
        if word in text:
            score += 10
    for word in ['指导原则', '技术要求', '沟通交流', '会议', '征求意见', '发布', '通告']:
        if word in text:
            score += 5
    for word in CDE_RELEVANT_KEYWORDS:
        if word in text:
            score += 1
    if re.search(r'\d+月\d*日?', link_text):
        score += 20
    return score

async def get_page_links_with_text(page, source_name):
    """获取页面中的链接和文本内容"""
    results = []
    try:
        # 获取链接
        links = await page.evaluate('''() => {
            const selectors = [
                'a[href*="/main/news/viewInfoCommon/"]',
                'a[href*="/main/viewinfo/"]',
                'a[href*="/zdyz/"]'
            ];
            let items = [];
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(a => {
                    if (a.innerText && a.innerText.trim().length > 2) {
                        items.push({
                            href: a.href,
                            text: a.innerText.trim(),
                            type: 'link'
                        });
                    }
                });
            });
            // 也获取页面中可能包含日期的文本
            const textSelectors = ['span', 'p', 'div', 'font', 'li'];
            textSelectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const text = el.innerText || '';
                    if (/\d{1,2}月\d{1,2}日/.test(text) || /\d{4}-\d{2}-\d{2}/.test(text)) {
                        if (text.length > 5 && text.length < 50) {
                            items.push({
                                href: '',
                                text: text.trim(),
                                type: 'date'
                            });
                        }
                    }
                });
            });
            return items.slice(0, 50);
        }''')
        results = [{**l, 'source': source_name} for l in links]
    except Exception as e:
        log(f"    获取页面内容失败: {str(e)[:30]}")
    return results

async def search_on_page(page, keyword):
    """在当前页面搜索"""
    results = []
    seen = set()

    try:
        search_input = await page.query_selector('input[placeholder*="关键词"]')
        if not search_input:
            search_input = await page.query_selector('input[type="text"]')

        if search_input:
            await search_input.fill(keyword)
            await asyncio.sleep(1)
            await search_input.press('Enter')
            await asyncio.sleep(8)

            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                    .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
            }''')

            for link in links:
                if link['href'] not in seen and link['text']:
                    seen.add(link['href'])
                    results.append({**link, 'source': '页面搜索'})
    except:
        pass
    return results

async def search_cde(keyword, page, target_site='cde.org.cn'):
    """搜索框搜索"""
    results = []
    seen = set()
    keywords = generate_search_keywords(keyword, target_site)
    log(f"  🔑 关键词: {keywords}")

    for kw in keywords:
        if not kw:
            continue
        try:
            log(f"    搜索: '{kw}'")
            await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
            await asyncio.sleep(3)

            search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)
            await search_input.fill(kw)
            await asyncio.sleep(1)
            await search_input.press('Enter')
            await asyncio.sleep(8)

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

            log(f"      '{kw}': +{new_count} 条")
            if new_count > 0:
                break
        except:
            continue

    return results

async def deep_navigate_cde(keyword, page):
    """层级深入查找"""
    results = []
    seen = set()

    log(f"  🧠 层级深入查找...")

    # 访问各个专栏
    for page_name, page_url in CDE_ENTRY_PAGES.items():
        log(f"    → {page_name}")
        try:
            await page.goto(page_url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(4)

            # 1. 先尝试页面搜索
            search_results = await search_on_page(page, keyword)
            for r in search_results:
                if r['href'] not in seen and r['text']:
                    seen.add(r['href'])
                    results.append(r)

            # 2. 获取所有链接
            all_items = await get_page_links_with_text(page, page_name)
            log(f"      发现 {len([i for i in all_items if i.get('type') == 'link'])} 个链接")

            # 3. 按分数排序，选择高分的点击
            link_items = [i for i in all_items if i.get('type') == 'link' and i.get('href')]
            scored = [(score_link(l['text'], keyword), l) for l in link_items]
            scored.sort(reverse=True, key=lambda x: x[0])

            top_links = [l for s, l in scored if s > 5][:8]  # 提高阈值

            for link_info in top_links:
                if link_info['href'] in seen:
                    continue
                try:
                    log(f"        → {link_info['text'][:25]}...")
                    await page.goto(link_info['href'], wait_until='networkidle', timeout=60000)
                    await asyncio.sleep(3)

                    # 获取详情页内容
                    detail_items = await get_page_links_with_text(page, f'{page_name}-详情')
                    for item in detail_items:
                        if item.get('type') == 'link' and item.get('href'):
                            if item['href'] not in seen and item['text']:
                                seen.add(item['href'])
                                results.append(item)
                        elif item.get('type') == 'date':
                            # 保存日期信息
                            results.append({**item, 'href': link_info['href'], 'source': f'{page_name}-日期'})

                    # 翻页
                    for p in range(2, 4):
                        try:
                            next_btn = await page.query_selector('a:has-text("下一页")')
                            if next_btn:
                                await next_btn.click()
                                await asyncio.sleep(3)
                                detail_items = await get_page_links_with_text(page, f'{page_name}-页{p}')
                                for item in detail_items:
                                    if item.get('type') == 'link' and item.get('href'):
                                        if item['href'] not in seen and item['text']:
                                            seen.add(item['href'])
                                            results.append(item)
                        except:
                            break

                except:
                    pass

            page_count = len([r for r in results if page_name in r.get('source', '')])
            log(f"      {page_name}: +{page_count} 条")

        except Exception as e:
            log(f"      {page_name} 失败")

    return results

def filter_relevant(links, keyword):
    relevant = []
    kw = keyword.lower()
    has_core = any(k in kw for k in ['指导原则', '技术要求', '沟通交流', '通告', '发布'])
    for link in links:
        text = link.get('text', '').lower()
        if has_core:
            if any(k in text for k in CDE_RELEVANT_KEYWORDS):
                relevant.append(link)
        else:
            if sum(1 for k in CDE_RELEVANT_KEYWORDS if k in text) >= 2:
                relevant.append(link)
    return relevant

def merge_and_deduplicate(all_results):
    seen = set()
    unique = []
    for link in all_results:
        if link.get('href') and link['href'] not in seen:
            seen.add(link['href'])
            unique.append(link)
    return unique

async def download_cde(keyword, target_site='cde.org.cn'):
    log(f"🔍 CDE搜索: {keyword}")
    log(f"📂 保存到: ~/Documents/工作/法规指导原则")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(user_agent=random.choice(UA_POOL))
        page = await context.new_page()
        await page.add_init_script(ANTIDETECT_SCRIPT)

        all_results = []

        # 方式1: 搜索框搜索
        log("→ 方式1: 搜索框搜索...")
        search_results = await search_cde(keyword, page, target_site)
        all_results.extend(search_results)
        log(f"    搜索结果: {len(search_results)} 条")

        # 方式2: 层级深入查找
        log("→ 方式2: 层级深入查找...")
        deep_results = await deep_navigate_cde(keyword, page)
        all_results.extend(deep_results)
        log(f"    深层结果: {len(deep_results)} 条")

        # 合并去重
        unique_results = merge_and_deduplicate(all_results)
        log(f"✓ 合并后共 {len(unique_results)} 条")

        # 相关性过滤
        relevant = filter_relevant(unique_results, keyword)
        log(f"✓ 相关内容: {len(relevant)} 条")

        # 显示结果
        print("\n" + "=" * 60)
        print("📋 搜索结果")
        print("=" * 60)

        sources = {}
        for r in relevant:
            src = r.get('source', '未知')[:30]
            if src not in sources:
                sources[src] = []
            sources[src].append(r['text'][:70])

        for src, texts in sources.items():
            print(f"\n【{src}】({len(texts)}条)")
            for t in texts[:10]:
                print(f"  • {t}")

        log(f"\n✓ 最终 {len(relevant)} 个结果")

        await browser.close()

    return relevant

async def main():
    print("=" * 50)
    print("web-access skill v1.7.3 (2026-03-20)")
    print("  修复版: 层级深入查找")
    print("=" * 50)

    if len(sys.argv) < 3:
        print("\n使用方法:")
        print("  python web_access.py cde <关键词>")
        return

    action = sys.argv[1]
    keyword = sys.argv[2] if len(sys.argv) > 2 else ""
    target_site = sys.argv[3] if len(sys.argv) > 3 else 'cde.org.cn'

    if action == "cde":
        await download_cde(keyword, target_site)
    else:
        print(f"未知动作: {action}")

    print("\n✅ 完成")

if __name__ == "__main__":
    asyncio.run(main())
