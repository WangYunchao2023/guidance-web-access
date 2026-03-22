#!/usr/bin/env python3
"""
通用网页访问工具（全视野探索版）
版本: 2.6 (2026-03-22)
核心逻辑：翻页探索 + 模糊日期匹配 + 经验锁定
"""

import asyncio, sys, re, os, random, time, subprocess, yaml
from pathlib import Path
from playwright.async_api import async_playwright

# ==================== 配置与环境 ====================
CONFIG = { 'headless': False, 'timeout': 60000 }
BROWSER_ARGS = ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
UA_POOL = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36']
CDE_ENTRY_PAGES = {
    '发布通告': 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d',
    '指导原则': 'https://www.cde.org.cn/zdyz/index'
}

def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}")

# ==================== 🛠️ 记忆与解析 ====================

def get_user_overrides():
    p = Path(__file__).parent.parent / "references" / "user_overrides.yaml"
    try:
        with open(p, 'r') as f: return yaml.safe_load(f).get('overrides', [])
    except: return []

def match_override(keyword):
    for entry in get_user_overrides():
        if re.search(entry.get('task_pattern', ''), keyword): return entry
    return None

def extract_task_intent(task_keyword):
    date_match = re.search(r'(\d{1,2})月(\d{1,2})', task_keyword)
    target_date = f"{time.strftime('%Y')}-{date_match.group(1).zfill(2)}-{date_match.group(2).zfill(2)}" if date_match else None
    kws = [k for k in ['指导原则', '法规'] if k in task_keyword] or [task_keyword]
    return { 'date': target_date, 'query': " ".join(kws), 'original': task_keyword }

# ==================== 🧠 智能化感知与提取 ====================

async def get_links_with_full_context(page):
    """提取整行信息，关联日期与链接"""
    return await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('li, tr, .list_item')).map(row => {
            const link = row.querySelector('a');
            const rowText = row.innerText || '';
            // 匹配各种日期格式: 2026-03-09, 2026.03.09, 03-09
            const dateMatch = rowText.match(/(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2})|(\d{1,2}[-.]\d{1,2})/);
            return link ? { 
                href: link.href, 
                text: link.innerText.trim(), 
                full_row: rowText.replace(/\s+/g, ' '),
                date: dateMatch ? dateMatch[0] : null
            } : null;
        }).filter(i => i && i.text.length > 2);
    }''')

async def smart_interact(page, intent):
    """感知搜索框并填充"""
    inputs = await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('input')).map(i => ({
            id: i.id, name: i.name, placeholder: i.placeholder, visible: i.offsetWidth > 0
        }));
    }''')
    filled = False
    for i in inputs:
        meta = (i['id'] + i['name'] + i['placeholder']).lower()
        if any(k in meta for k in ['keyword', '关键词', '标题', '查询']) and i['visible']:
            try:
                await page.fill(f"input[placeholder='{i['placeholder']}']" if i['placeholder'] else f"input[name='{i['name']}']", intent['query'])
                filled = True
            except: pass
        if intent['date'] and any(k in meta for k in ['date', 'time', '日期', '时间']):
            try: await page.fill(f"input[name='{i['name']}']" if i['name'] else f"input[id='{i['id']}']", intent['date']); filled = True
            except: pass
    if filled:
        await page.keyboard.press('Enter'); await asyncio.sleep(10)
    return filled

# ==================== 🛠️ 全视野深度探索 ====================

async def explore_with_pagination(page, intent, exploration_points):
    """带翻页的深度探索"""
    all_results = []
    seen = set()
    for name, url in exploration_points.items():
        log(f"🚀 探索起始点: {name}")
        try:
            await page.goto(url, wait_until='networkidle'); await asyncio.sleep(5)
            await smart_interact(page, intent)
            
            # 🔄 翻页逻辑：扫描前 5 页 (确保不漏掉 3月9日)
            for p_idx in range(1, 6):
                log(f"  📄 正在扫描第 {p_idx} 页内容...")
                await asyncio.sleep(3)
                page_links = await get_links_with_full_context(page)
                for l in page_links:
                    if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                
                # 寻找下一页按钮
                next_btn = await page.query_selector('text="下一页"') or await page.query_selector('a:has-text(">")') or await page.query_selector(f'a:has-text("{p_idx + 1}")')
                if next_btn and p_idx < 5:
                    await next_btn.click(); await asyncio.sleep(5)
                else:
                    log("  ⏹️ 已无下一页或达到扫描上限。")
                    break
        except Exception as e: log(f"  ⚠️ 探索点访问失败: {str(e)[:50]}")
    return all_results

# ==================== 🧬 模糊语义匹配 ====================

def fuzzy_semantic_filter(results, intent):
    log("  🧬 执行模糊语义匹配 (兼容多种日期与补零格式)...")
    m = re.search(r'(\d{1,2})月(\d{1,2})', intent['original'])
    if not m: return results
    
    mon, day = m.group(1), m.group(2)
    # 构建所有可能的变体
    targets = [
        f"{int(mon)}月{int(day)}日",
        f"{mon.zfill(2)}-{day.zfill(2)}",
        f"{mon.zfill(2)}.{day.zfill(2)}",
        f"{int(mon)}-{int(day)}",
        f"{int(mon)}.{int(day)}"
    ]
    
    filtered = []
    for r in results:
        content = (r['text'] + (r['date'] or '') + r['full_row']).replace(' ', '')
        if any(t in content for t in targets):
            filtered.append(r)
    return filtered

# ==================== 📥 下载逻辑 ====================

async def final_download(page, results):
    save_dir = os.path.expanduser("~/Documents/工作/法规指导原则"); os.makedirs(save_dir, exist_ok=True)
    count = 0
    for r in results[:15]:
        log(f"📥 提取: {r['text'][:50]}")
        try:
            await page.goto(r['href']); await asyncio.sleep(8)
            d_links = await page.query_selector_all('a[href*="download"]')
            # 再次提取日期用于文件名
            d_m = re.search(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})', r['full_row'])
            if d_links and d_m:
                fname = f"{d_m.group(1)}{d_m.group(2).zfill(2)}{d_m.group(3).zfill(2)} - {r['text'][:60]}.pdf"
                fpath = os.path.join(save_dir, fname)
                if not os.path.exists(fpath):
                    async with page.expect_download() as di: await d_links[0].click()
                    d = await di.value; await d.save_as(fpath); log(f"  ✅ 成功: {fname}"); count += 1
        except: pass
    return count

# ==================== 🏁 入口 ====================

async def main_flow(keyword):
    intent = extract_task_intent(keyword)
    log(f"🎯 任务: {intent['query']} | 目标日期: {intent['original']}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        page = await browser.new_page()
        
        entry = match_override(keyword)
        pts = { "经验锁定": entry['target_url'] } if entry else CDE_ENTRY_PAGES
        if entry and entry.get('search_url'): pts["经验搜索"] = entry['search_url']
        
        # 1. 带翻页的全视野扫描
        raw_list = await explore_with_pagination(page, intent, pts)
        
        # 2. 模糊语义过滤
        final_list = fuzzy_semantic_filter(raw_list, intent)
        
        if not final_list:
            log(f"❌ 经过 5 页全深度扫描，仍未发现匹配日期 [{intent['original']}] 的内容。任务未完成。")
        else:
            log(f"📋 发现 {len(final_list)} 项匹配，执行下载...")
            await final_download(page, final_list)
            
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 2: asyncio.run(main_flow(sys.argv[2]))
    print("\n✅ 完成")
