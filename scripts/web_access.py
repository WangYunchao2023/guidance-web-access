#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.8.1 (2026-03-21)
更新: 
- 改进关键词缩短策略（始终尝试多个关键词）
- 添加意图识别（从任务中提取核心需求）
- 改进层级查找（先分析页面所有链接再决策）
- 添加PDF验证功能
- 使用Playwright下载功能

"""

import asyncio
import sys
import re
import os
import random
import time
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests

# ==================== PDF验证功能 ====================
def verify_pdf(filepath):
    """验证PDF是否能正常打开"""
    try:
        # 方法1: 检查文件头
        with open(filepath, 'rb') as f:
            header = f.read(5)
            if header == b'%PDF-':
                return True, "OK"
        return False, "Invalid header"
    except Exception as e:
        return False, str(e)

# ==================== 配置 ====================
CONFIG = {
    'headless': False,  # CDE网站检测headless模式，必须使用可见浏览器
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

import yaml

# ==================== 记忆加载与干预处理 ====================
def get_user_overrides():
    """从 user_overrides.yaml 加载人工干预记录"""
    overrides_path = Path(__file__).parent.parent / "references" / "user_overrides.yaml"
    if not overrides_path.exists():
        return []
    try:
        with open(overrides_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('overrides', [])
    except Exception as e:
        log(f"加载干预记忆失败: {e}")
        return []

def match_override(keyword):
    """检查是否有匹配的任务干预"""
    overrides = get_user_overrides()
    for entry in overrides:
        pattern = entry.get('task_pattern')
        if pattern and re.search(pattern, keyword):
            log(f"🧠 触发干预记忆: '{pattern}' -> {entry.get('note')}")
            return entry.get('target_url')
    return None

def save_new_override(keyword, target_url, note=""):
    """保存新的人工干预记忆"""
    overrides_path = Path(__file__).parent.parent / "references" / "user_overrides.yaml"
    overrides = []
    if overrides_path.exists():
        try:
            with open(overrides_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                overrides = data.get('overrides', [])
        except: pass
    
    overrides.append({
        'task_pattern': f".*{keyword}.*",
        'target_url': target_url,
        'note': note or f"由用户干预添加: {keyword}"
    })
    
    with open(overrides_path, 'w', encoding='utf-8') as f:
        yaml.dump({'overrides': overrides}, f, allow_unicode=True)
    log(f"💾 已保存干预记忆: {keyword}")

# ==================== 增强版搜索策略 ====================
async def get_ai_keywords(keyword, current_page_text=""):
    """
    (模拟) 调用 LLM 生成更聪明的搜索词。
    在实际运行中，如果是主程序调用，我会在这里动态思考。
    """
    # 基础策略
    variants = generate_search_keywords(keyword)
    
    # 补充：根据当前页面内容动态生成的关键词 (待集成 LLM 逻辑)
    return variants

# 用户任务类型定义
TASK_TYPES = {
    '指导原则': ['指导原则', '技术要求', '技术指南', 'guidance', 'guideline'],
    '公示': ['公示', '公示信息', '审批公示', '审评公示'],
    '征求意见': ['征求意见', '草案', '试行', '公开征求'],
    '政策法规': ['政策法规', '法规', '管理办法', '规定'],
    '下载': ['下载', 'pdf', 'doc', '附件'],
}

# 链接类型判断关键词
LINK_TYPE_PATTERNS = {
    '指导原则': ['指导原则', '技术要求', '技术指南', 'guidance', 'guideline'],
    '公示': ['公示', '公示信息', '审批', '优先审评', '突破性治疗', '沟通交流公示'],
    '征求意见': ['征求意见', '草案', '试行', '公开征求'],
    '政策法规': ['政策法规', '法规', '管理办法', '规定', 'policy', 'regulat'],
    '新闻': ['新闻', '动态', '通知', '活动', '党建'],
}

def extract_task_intent(task_keyword):
    """
    从用户任务中提取核心意图
    返回: (核心需求类型, 保留的关键词)
    """
    task = task_keyword.lower()
    
    # 找出用户明确提到的内容类型
    found_types = []
    for ttype, patterns in TASK_TYPES.items():
        for pattern in patterns:
            if pattern.lower() in task:
                found_types.append(ttype)
                break
    
    # 提取核心关键词（去除类型词后保留的）
    core_keywords = []
    
    # 如果用户提到了"指导原则"，保留它作为核心需求
    if '指导原则' in task_keyword or 'guidance' in task:
        core_keywords.append('指导原则')
    
    # 如果用户提到了"公示"，保留它
    if '公示' in task_keyword:
        core_keywords.append('公示')
    
    # 如果用户提到了"征求意见"，保留它
    if '征求意见' in task_keyword or '草案' in task:
        core_keywords.append('征求意见')
    
    # 如果用户没有明确提到类型，尝试提取其他关键词
    if not core_keywords:
        # 保留原始关键词
        core_keywords.append(task_keyword)
    
    # 返回识别的类型和核心关键词
    intent_type = found_types[0] if found_types else '通用'
    
    return intent_type, core_keywords

def filter_links_by_intent(links, intent_type, core_keywords):
    """
    根据意图过滤和排序链接
    - intent_type: 识别的用户意图类型
    - core_keywords: 核心关键词
    """
    if not links:
        return links
    
    # 为每个链接打分
    scored_links = []
    for link in links:
        text = link.get('text', '').lower()
        href = link.get('href', '').lower()
        score = 0
        
        # 如果识别到特定意图，增加相关链接的分数
        if intent_type == '指导原则':
            # 优先选择包含"指导原则"的链接，排除"公示"
            if any(k in text for k in ['指导原则', '技术要求', '技术指南']):
                score += 100
            if '公示' in text and '指导原则' not in text:
                score -= 100
        
        elif intent_type == '公示':
            # 优先选择包含"公示"的链接
            if '公示' in text:
                score += 100
        
        elif intent_type == '征求意见':
            # 优先选择包含"征求意见"的链接
            if any(k in text for k in ['征求意见', '草案', '试行', '公开征求']):
                score += 100
        
        # 核心关键词匹配加分
        for kw in core_keywords:
            if kw.lower() in text or kw.lower() in href:
                score += 10
        
        scored_links.append((score, link))
    
    # 按分数排序，返回链接
    scored_links.sort(reverse=True, key=lambda x: x[0])
    return [link for score, link in scored_links]

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
    """搜索框搜索 - 优化版：减少重复访问首页，快速失败"""
    results = []
    seen = set()
    keywords = generate_search_keywords(keyword, target_site)
    log(f"  🔑 关键词: {keywords}")

    # 只在第一次访问首页，后续使用页面内搜索
    first_search = True
    
    for kw in keywords:
        if not kw:
            continue
        try:
            log(f"    搜索: '{kw}'")
            
            if first_search:
                # 第一次访问首页
                await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
                await asyncio.sleep(3)
                first_search = False
            else:
                # 后续搜索：点击清除按钮或刷新搜索框
                try:
                    clear_btn = await page.query_selector('input[placeholder*="关键词"]')
                    if clear_btn:
                        await clear_btn.click()
                        await asyncio.sleep(0.5)
                except:
                    pass

            search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)
            await search_input.fill(kw)
            await asyncio.sleep(0.5)
            await search_input.press('Enter')
            
            # 等待JavaScript加载
            await asyncio.sleep(30)

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
                
        except Exception as e:
            log(f"      搜索 '{kw}' 失败: {str(e)[:30]}")
            # 失败时尝试返回首页重试
            try:
                await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=30000)
                first_search = True
            except:
                pass
            continue

    return results

async def deep_navigate_cde(keyword, page):
    """层级深入查找 - 改进版：先分析再决策"""
    results = []
    seen = set()

    # 提取用户意图
    intent_type, core_keywords = extract_task_intent(keyword)
    log(f"  🧠 层级深入查找...")
    log(f"    🎯 意图识别: {intent_type}, 核心关键词: {core_keywords}")

    # 访问各个专栏
    for page_name, page_url in CDE_ENTRY_PAGES.items():
        log(f"    → {page_name}")
        try:
            await page.goto(page_url, wait_until='networkidle', timeout=60000)
            await asyncio.sleep(30)  # 等待JavaScript加载

            # 1. 先尝试页面搜索
            search_results = await search_on_page(page, keyword)
            for r in search_results:
                if r['href'] not in seen and r['text']:
                    seen.add(r['href'])
                    results.append(r)

            # 2. 获取所有链接
            all_items = await get_page_links_with_text(page, page_name)
            link_items = [i for i in all_items if i.get('type') == 'link' and i.get('href')]
            log(f"      发现 {len(link_items)} 个链接")
            
            # 3. 根据意图过滤链接（不依赖预设关键词，而是根据任务动态调整）
            if core_keywords:
                # 使用意图过滤
                filtered_items = filter_links_by_intent(link_items, intent_type, core_keywords)
                log(f"      意图过滤后: {len(filtered_items)} 个相关链接")
                
                # 打印前几个候选链接供调试
                for i, item in enumerate(filtered_items[:5]):
                    log(f"        候选{i+1}: {item.get('text', '')[:40]}")
                
                # 选择得分最高的几个链接
                top_links = filtered_items[:8]
            else:
                # 没有核心关键词时使用原有评分
                scored = [(score_link(l['text'], keyword), l) for l in link_items]
                scored.sort(reverse=True, key=lambda x: x[0])
                top_links = [l for s, l in scored if s > 5][:8]

            # 4. 访问选中的链接
            for link_info in top_links:
                if link_info['href'] in seen:
                    continue
                try:
                    log(f"        → {link_info['text'][:25]}...")
                    await page.goto(link_info['href'], wait_until='networkidle', timeout=60000)
                    await asyncio.sleep(15)  # 等待详情页加载

                    # 获取详情页内容
                    detail_items = await get_page_links_with_text(page, f'{page_name}-详情')
                    for item in detail_items:
                        if item.get('type') == 'link' and item.get('href'):
                            if item['href'] not in seen and item['text']:
                                seen.add(item['href'])
                                results.append(item)
                        elif item.get('type') == 'date':
                            results.append({**item, 'href': link_info['href'], 'source': f'{page_name}-日期'})

                    # 翻页
                    for p in range(2, 4):
                        try:
                            next_btn = await page.query_selector('a:has-text("下一页")')
                            if next_btn:
                                await next_btn.click()
                                await asyncio.sleep(10)
                                detail_items = await get_page_links_with_text(page, f'{page_name}-页{p}')
                                for item in detail_items:
                                    if item.get('type') == 'link' and item.get('href'):
                                        if item['href'] not in seen and item['text']:
                                            seen.add(item['href'])
                                            results.append(item)
                        except:
                            break

                except Exception as e:
                    log(f"        访问失败: {str(e)[:30]}")

            page_count = len([r for r in results if page_name in r.get('source', '')])
            log(f"      {page_name}: +{page_count} 条")

        except Exception as e:
            log(f"      {page_name} 失败: {str(e)[:30]}")

    return results

def filter_by_date(links, keyword):
    """根据日期过滤结果"""
    # 检查是否包含日期关键词
    date_match = re.search(r'(\d{1,2})月(\d{1,2})', keyword)
    if not date_match:
        return links  # 没有日期关键词，返回全部

    target_month = int(date_match.group(1))
    target_day = int(date_match.group(2))

    filtered = []
    for link in links:
        text = link.get('text', '')
        # 在文本中查找日期
        dates = re.findall(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})', text)
        matched = False
        for d in dates:
            month = int(d[1])
            day = int(d[2])
            if month == target_month and day == target_day:
                filtered.append(link)
                matched = True
                break
        # 也检查链接标题中的日期
        if not matched and ('指导原则' in text or '通告' in text or '发布' in text):
            filtered.append(link)

    return filtered

def filter_relevant(links, keyword):
    relevant = []
    kw = keyword.lower()
    has_core = any(k in kw for k in ['指导原则', '技术要求', '沟通交流', '通告', '发布'])

    # 检查是否有日期
    has_date = bool(re.search(r'\d+月\d+日', keyword))

    for link in links:
        text = link.get('text', '').lower()

        if has_core:
            if any(k in text for k in CDE_RELEVANT_KEYWORDS):
                relevant.append(link)
        else:
            if sum(1 for k in CDE_RELEVANT_KEYWORDS if k in text) >= 2:
                relevant.append(link)

    # 如果有关键词包含日期，进行日期过滤
    if has_date:
        relevant = filter_by_date(relevant, keyword)

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

        # 提取用户意图
        intent_type, core_keywords = extract_task_intent(keyword)
        log(f"🎯 意图识别: {intent_type}, 核心关键词: {core_keywords}")

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

        # 使用意图过滤结果
        relevant = filter_links_by_intent(unique_results, intent_type, core_keywords)
        
        # 额外相关性过滤
        relevant = filter_relevant(relevant, keyword)
        log(f"✓ 意图过滤后: {len(relevant)} 条")

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

        # 下载功能
        if relevant and len(relevant) > 0:
            # 修改：在自动化环境下默认下载，或通过参数控制
            should_download = True 
            if should_download:
                log("\n开始下载PDF文件...")
                download_count = await download_pdfs_from_results(page, relevant, context)
                log(f"下载完成: {download_count} 个文件")

        await browser.close()

    return relevant

async def download_pdfs_from_results(page, results, context):
    """从搜索结果下载PDF文件 - 使用Playwright下载功能"""
    import os
    
    save_dir = os.path.expanduser("~/Documents/工作/法规指导原则")
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    downloaded_count = 0
    
    for i, result in enumerate(results[:10]):  # 最多下载前10个
        title = result.get('text', '')[:50]
        href = result.get('href', '')
        
        if not href:
            continue
        
        log(f"\n[{i+1}] 处理: {title}")
        
        try:
            # 访问详情页
            await page.goto(href, wait_until='load', timeout=60000)
            await asyncio.sleep(30)  # 等待JavaScript加载
            
            # 查找PDF下载链接 - CDE的下载链接包含 "/main/att/download/"
            download_links = await page.query_selector_all('a[href*="/main/att/download/"]')
            
            if not download_links:
                log(f"    未找到下载链接")
                continue
            
            log(f"    找到 {len(download_links)} 个下载链接")
            
            # 处理每个下载链接
            for j, link in enumerate(download_links):
                try:
                    link_text = await link.inner_text()
                    link_href = await link.get_attribute('href')
                    
                    # 只处理PDF文件
                    if link_text and '.pdf' in link_text.lower():
                        full_url = f"https://www.cde.org.cn{link_href}" if link_href.startswith('/') else link_href
                        
                        # 清理文件名
                        filename = link_text.strip()[:60].replace('/', '_').replace('\\', '')
                        if not filename.endswith('.pdf'):
                            filename += '.pdf'
                        
                        save_path = os.path.join(save_dir, filename)
                        log(f"    下载: {filename}")
                        
                        # 方法1: 使用Playwright下载
                        try:
                            async with page.expect_download(timeout=30000) as download_info:
                                await link.click()
                            
                            download = await download_info.value
                            await download.save_as(save_path)
                            
                            # 验证PDF
                            is_valid, msg = verify_pdf(save_path)
                            if is_valid:
                                size = os.path.getsize(save_path)
                                log(f"    ✓ 下载成功! 大小: {size} bytes")
                                downloaded_count += 1
                            else:
                                log(f"    ✗ PDF验证失败: {msg}")
                                try:
                                    os.remove(save_path)
                                except:
                                    pass
                        except Exception as e:
                            log(f"    Playwright下载失败: {str(e)[:30]}, 尝试curl...")
                            
                            
                            # 方法2: 降级到curl
                            cookies = await context.cookies()
                            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                            
                            result = subprocess.run(
                                ['curl', '-L', '-o', save_path, 
                                 '-H', f'Cookie: {cookie_str}',
                                 '-A', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                 full_url],
                                capture_output=True, timeout=60
                            )
                            
                            if os.path.exists(save_path):
                                is_valid, msg = verify_pdf(save_path)
                                if is_valid:
                                    size = os.path.getsize(save_path)
                                    log(f"    ✓ curl下载成功! 大小: {size} bytes")
                                    downloaded_count += 1
                                else:
                                    log(f"    ✗ PDF验证失败: {msg}")
                                    try:
                                        os.remove(save_path)
                                    except:
                                        pass
                        
                        break  # 找到一个PDF就处理下一个结果
                        
                except Exception as e:
                    log(f"    处理下载链接错误: {str(e)[:30]}")
                    continue
            
            # 返回列表页继续
            await page.goto("https://www.cde.org.cn", wait_until='load', timeout=30000)
            await asyncio.sleep(5)
                
        except Exception as e:
            log(f"    错误: {str(e)[:50]}")
    
    return downloaded_count

async def main():
    print("=" * 50)
    print("web-access skill v1.8.1 (2026-03-21)")
    print("  改进版: 意图识别 + 关键词策略 + PDF下载")
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
