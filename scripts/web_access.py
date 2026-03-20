#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.7.1 (2026-03-20)
更新: 真正的层级深入查找 - AI判断哪些链接需要点击

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
    '--disable-images',
]

# 反检测脚本
ANTIDETECT_SCRIPT = '''
    Object.defineProperty(navigator, "webdriver", {get: () => undefined});
    window.chrome = {runtime: {}};
'''

# CDE导航URL映射 - 初始入口页面
CDE_ENTRY_PAGES = {
    '首页': 'https://www.cde.org.cn',
    '指导原则专栏': 'https://www.cde.org.cn/zdyz/index',
    '指导原则数据库': 'https://www.cde.org.cn/zdyz/domestic',
    '国内指导原则': 'https://www.cde.org.cn/zdyz/listpage/9cd8db3b7530c6fa0c86485e563f93c7',
    '发布通告': 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d',
    '征求意见': 'https://www.cde.org.cn/main/news/listpage/9f9c239c4e4f9f6708a079ec6443f60e',
    '沟通交流': 'https://www.cde.org.cn/main/xxgk/listpage/2f78f372d351c6851af7431c7710286e',
    '政策法规': 'https://www.cde.org.cn/main/policy/',
}

# 关键词缩短策略
KEYWORD_SHORTEN_STRATEGY = [
    lambda k: k,  # 原始关键词
    lambda k: k.replace('指导原则', '').replace('技术要求', '').replace('技术指南', '').strip(),
    lambda k: k.replace('征求意见稿', '').replace('公开征求', '').replace('（征求意见稿）', '').strip(),
    # 日期处理：保留"月"和"日"
    lambda k: re.sub(r'\d+', '', k).replace('年月日', '').strip() if k else k,
    # 保留数字中的关键部分
    lambda k: re.sub(r'[年月日]', '', k).strip() if k else k,
    # 只取第一个词
    lambda k: k.split()[0] if k and k.split() else k,
    # 如果是日期格式，尝试搜索"发布"
    lambda k: '发布' if re.search(r'\d+月\d*日?', k) else k,
]

# 中文到英文翻译映射（常用医药术语）
CN_TO_EN = {
    '指导原则': 'guidance',
    '技术要求': 'technical requirements',
    '技术指南': 'guideline',
    '沟通交流': 'communication',
    '临床试验': 'clinical trial',
    '征求意见': 'draft',
    '药品': 'drug',
    '注册': 'registration',
    '生物制品': 'biological',
    '疫苗': 'vaccine',
    '抗肿瘤': 'anti-tumor',
    '罕见病': 'rare disease',
    '儿童': 'pediatric',
}

# 英文到中文翻译映射
EN_TO_CN = {
    'guidance': '指导原则',
    'guideline': '指导原则',
    'technical requirements': '技术要求',
    'communication': '沟通交流',
    'clinical trial': '临床试验',
    'draft': '征求意见',
    'drug': '药品',
    'registration': '注册',
    'biological': '生物制品',
    'vaccine': '疫苗',
    'rare disease': '罕见病',
    'pediatric': '儿童',
    'ANDA': '仿制药申请',
    'NDA': '新药申请',
    'BLA': '生物制品许可申请',
}

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
    """生成搜索关键词列表（缩短 + 翻译）"""
    keywords = []

    # 1. 先尝试缩短策略
    for strategy in KEYWORD_SHORTEN_STRATEGY:
        kw = strategy(keyword)
        if kw and kw not in keywords:
            keywords.append(kw)

    # 2. 翻译策略：如果原始关键词是中文，尝试翻译成英文
    if any('\u4e00' <= c <= '\u9fff' for c in keyword):  # 包含中文
        # 翻译成英文
        en_translations = []
        for cn, en in CN_TO_EN.items():
            if cn in keyword:
                en_translations.append(en)
        # 添加组合翻译
        if en_translations:
            combined_en = ' '.join(en_translations)
            if combined_en not in keywords:
                keywords.append(combined_en)
            # 添加单个翻译
            for en in en_translations:
                if en not in keywords:
                    keywords.append(en)

    # 3. 翻译策略：如果原始关键词是英文，尝试翻译成中文
    else:  # 可能是英文
        for en, cn in EN_TO_CN.items():
            if en.lower() in keyword.lower():
                if cn not in keywords:
                    keywords.append(cn)

    return keywords

def is_relevant_link(link_text, keyword):
    """AI判断链接是否与关键词相关"""
    text = link_text.lower()
    kw = keyword.lower()

    # 提取关键词中的核心词
    core_words = []
    if '沟通' in kw or '交流' in kw:
        core_words = ['沟通', '交流', '会议']
    elif '3月' in kw or '日' in kw:
        core_words = ['发布', '通告', '2026']
    elif '征求' in kw:
        core_words = ['征求', '草案']
    else:
        # 提取搜索词中的名词
        core_words = [w for w in kw.split() if len(w) >= 2]

    # 如果有核心词，检查是否包含
    if core_words:
        return any(word in text for word in core_words)

    # 默认：检查是否包含相关关键词
    return any(k in text for k in CDE_RELEVANT_KEYWORDS)

def score_link(link_text, keyword):
    """给链接打分，决定是否值得深入点击"""
    text = link_text.lower()
    kw = keyword.lower()
    score = 0

    # 高分：包含搜索关键词
    for word in kw.split():
        if word in text:
            score += 10

    # 中等分数：包含相关关键词
    important_words = ['指导原则', '技术要求', '沟通交流', '会议', '征求意见', '发布', '通告']
    for word in important_words:
        if word in text:
            score += 5

    # 低分：其他相关词
    for word in CDE_RELEVANT_KEYWORDS:
        if word in text:
            score += 1

    return score

async def get_all_links(page, source_name):
    """获取页面所有链接"""
    results = []
    seen = set()

    try:
        links = await page.evaluate('''(sourceName) => {
            return Array.from(document.querySelectorAll('a[href*="/main/"], a[href*="/zdyz/"]'))
                .filter(a => a.innerText && a.innerText.trim().length > 2)
                .slice(0, 50).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
        }''', source_name)

        for link in links:
            # 过滤掉无效链接
            if not link['href'] or 'cde.org.cn' not in link['href']:
                continue
            if link['href'] in seen:
                continue
            seen.add(link['href'])
            results.append({**link, 'source': source_name})
    except Exception as e:
        pass

    return results

async def click_and_collect(page, link_info, keyword, max_depth=2):
    """点击链接深入查找"""
    results = []

    try:
        # 点击链接
        await page.goto(link_info['href'], wait_until='networkidle', timeout=60000)
        await asyncio.sleep(3)

        # 获取当前页面结果
        current_links = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
        }''')

        for link in current_links:
            if link['text']:
                results.append({**link, 'source': f"深入-{link_info['text'][:20]}"})

        # 如果深度未达上限，尝试继续点击
        if max_depth > 0:
            # 获取更多链接
            sub_links = await get_all_links(page, f"子页面")
            # 按分数排序，优先点击相关的
            scored_links = [(score_link(l['text'], keyword), l) for l in sub_links]
            scored_links.sort(reverse=True, key=lambda x: x[0])

            for score, sub_link in scored_links[:3]:  # 最多点击3个
                if score > 0:
                    sub_results = await click_and_collect(page, sub_link, keyword, max_depth - 1)
                    results.extend(sub_results)

    except Exception as e:
        pass

    return results

async def deep_navigate_cde(keyword, page):
    """真正的层级深入查找 - AI判断哪些链接需要点击"""
    results = []
    seen = set()
    visited_urls = set()

    log(f"  🧠 开始层级深入查找...")

    # 第一步：访问初始页面
    initial_pages = [
        ('首页', 'https://www.cde.org.cn'),
        ('指导原则专栏', 'https://www.cde.org.cn/zdyz/index'),
        ('发布通告', 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d'),
    ]

    for page_name, page_url in initial_pages:
        if page_url in visited_urls:
            continue

        log(f"    → 访问: {page_name}")
        visited_urls.add(page_url)

        try:
            await page.goto(page_url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(3)

            # 获取页面所有链接
            all_links = await get_all_links(page, page_name)
            log(f"      发现 {len(all_links)} 个链接")

            # 第二步：AI判断哪些链接需要点击深入
            # 按分数排序
            scored_links = [(score_link(l['text'], keyword), l) for l in all_links]
            scored_links.sort(reverse=True, key=lambda x: x[0])

            # 选择最高分的链接进行深入（最多5个）
            top_links = [l for s, l in scored_links if s > 0][:5]
            log(f"      选取 {len(top_links)} 个相关链接深入查找")

            for link_info in top_links:
                if link_info['href'] in visited_urls:
                    continue

                log(f"        → 点击: {link_info['text'][:30]}...")
                visited_urls.add(link_info['href'])

                try:
                    await page.goto(link_info['href'], wait_until='networkidle', timeout=60000)
                    await asyncio.sleep(3)

                    # 获取详情页结果
                    detail_links = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                            .slice(0, 20).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
                    }''')

                    for link in detail_links:
                        if link['href'] not in seen and link['text']:
                            seen.add(link['href'])
                            results.append({**link, 'source': f'深入-{link_info["text"][:15]}'})

                    # 尝试翻页
                    for page_num in range(2, 4):
                        try:
                            next_btn = await page.query_selector('a:has-text("下一页")')
                            if next_btn:
                                await next_btn.click()
                                await asyncio.sleep(3)

                                page_links = await page.evaluate('''() => {
                                    return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"], a[href*="/main/viewinfo/"]'))
                                        .slice(0, 20).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
                                }''')

                                for link in page_links:
                                    if link['href'] not in seen and link['text']:
                                        seen.add(link['href'])
                                        results.append({**link, 'source': f'深入-{page_name}[{page_num}]'})
                        except:
                            break

                except Exception as e:
                    pass

            page_results = [r for r in results if page_name in r.get("source", "")]
            log(f"      {page_name}: +{len(page_results)} 条")

        except Exception as e:
            log(f"      {page_name} 失败: {str(e)[:30]}")

    return results

async def search_cde(keyword, page):
    """CDE搜索框搜索"""
    results = []
    seen = set()

    keywords = generate_search_keywords(keyword)
    log(f"  🔑 关键词策略: {keywords}")

    for kw in keywords:
        if kw:
            try:
                log(f"    尝试搜索: '{kw}'")
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

                log(f"      搜索'{kw}': +{new_count} 条")

                if new_count > 0:
                    break

            except Exception as e:
                log(f"      搜索'{kw}'失败")
                continue

    return results

def filter_relevant(links, keyword):
    """相关性过滤"""
    relevant = []
    keyword_lower = keyword.lower()

    core_keywords = ['指导原则', '技术要求', '技术指南', '沟通交流', '会议', '通告']
    has_core = any(kw in keyword_lower for kw in core_keywords)

    for link in links:
        text = link.get('text', '').lower()

        if has_core:
            if any(kw in text for kw in CDE_RELEVANT_KEYWORDS):
                relevant.append(link)
        else:
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
    """CDE搜索主函数 - v1.7.1"""
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
        search_results = await search_cde(keyword, page)
        all_results.extend(search_results)

        # 方式2: 层级深入查找（AI判断点击哪些链接）
        log("→ 方式2: 层级深入查找（AI判断点击哪些链接）...")
        deep_results = await deep_navigate_cde(keyword, page)
        all_results.extend(deep_results)

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
    print("web-access skill v1.7.1 (2026-03-20)")
    print("  优化版: 层级深入查找（AI判断点击）")
    print("=" * 50)

    if len(sys.argv) < 3:
        print("\n使用方法:")
        print("  python web_access.py cde <关键词>")
        print("  python web_access.py cde 沟通交流")
        print("  python web_access.py cde 3月9日")
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
