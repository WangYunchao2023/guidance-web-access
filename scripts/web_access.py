#!/usr/bin/env python3
"""
通用网页访问工具（全要素泛化版）
版本: 2.7.1 (2026-03-23)
核心逻辑：语义级文件名智能判定 + 主体词/限定词语义分级 + 经验方法明确性（v2.7.1 核心：经验指定 method 后不再双轨并行）
"""

import asyncio, sys, re, os, random, time, subprocess, yaml
from pathlib import Path
from playwright.async_api import async_playwright

# ==================== 配置 ====================
CONFIG = { 'headless': False, 'timeout': 60000 }
BROWSER_ARGS = ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
UA_POOL = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36']
CDE_ENTRY_PAGES = {
    '指导原则': 'https://www.cde.org.cn/zdyz/index',
    '发布通告': 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d'
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

# ==================== 🧠 语义分级引擎 (v2.7.0) ====================
# 核心升级：从"关键词堆砌"升级为"主谓理解"
# 主体词（如"指导原则"）决定搜索范围，限定词（如"沟通交流"）负责结果过滤

PRIMARY_KEYWORDS = ['指导原则', '法规', '征求意见', '通告', '指导原则', '公告']
QUALIFIER_KEYWORDS = ['沟通交流', '化药', '生物制品', '中药', '仿制药', '创新药', '通用', '通用技术']

def extract_task_intent(task_keyword):
    """语义分级提取：区分主体词与限定词"""
    # 1. 提取日期
    date_match = re.search(r'(\d{1,2})月(\d{1,2})', task_keyword)
    target_date = f"{time.strftime('%Y')}-{date_match.group(1).zfill(2)}-{date_match.group(2).zfill(2)}" if date_match else None
    raw_date_str = re.sub(r'[^0-9月日]', '', task_keyword) if date_match else ''

    # 2. 语义分级：区分主体词 vs 限定词
    primary_kws = [k for k in PRIMARY_KEYWORDS if k in task_keyword]
    qualifier_kws = [k for k in QUALIFIER_KEYWORDS if k in task_keyword]

    # 3. 如果没有主体词，检查是否全是限定词（如"沟通交流"单独出现）
    if not primary_kws:
        primary_kws = [task_keyword]  # 回退：整句作为主体
        qualifier_kws = []

    # 4. 决定主搜索词（用于 override 匹配和入口选择）
    primary = primary_kws[0] if len(primary_kws) == 1 else (primary_kws[0] if primary_kws else task_keyword)

    # 5. 构建查询：主体词 + 日期（限定词不参与入口搜索，用于结果过滤）
    search_query_parts = [primary]
    if qualifier_kws:
        search_query_parts.extend(qualifier_kws)
    if date_match:
        search_query_parts.append(raw_date_str)

    return {
        'date': target_date,
        'query': " ".join(search_query_parts),
        'original': task_keyword,
        'primary': primary,            # 主体词：用于 override 匹配
        'qualifiers': qualifier_kws,   # 限定词列表：用于结果过滤
        'date_only': raw_date_str,
        'has_qualifier_only': bool(qualifier_kws) and not primary_kws  # 只有限定词，无主体
    }

def extract_var_from_match(pattern, keyword):
    """从 pattern 和 keyword 中提取变量（变量部分）"""
    try:
        var_match = re.search(pattern, keyword)
        if var_match and var_match.lastindex is not None:
            return var_match.group(1)
        # 如果 pattern 包含 XX 占位符，替换为 (.*) 再匹配
        if 'XX' in pattern:
            var_pattern = pattern.replace('XX', '(.*)')
            var_match = re.search(var_pattern, keyword)
            if var_match and var_match.lastindex is not None:
                return var_match.group(1)
    except Exception:
        pass
    return None

def generate_truncated_variants(keyword):
    """生成关键词截短变体，从长到短逐步简化，用于结果少时降级搜索"""
    if not keyword or len(keyword) <= 1:
        return [keyword] if keyword else []
    variants = []
    # 原始词
    variants.append(keyword)
    # 去掉常见结尾修饰词（按优先级从低到高排列，先去掉的放后面）
    suffixes_to_try = [
        (r'(?:相关|指南|指导原则|技术指导原则|技术|工艺|方法|研究|评价|申报|注册|生产|制备|质量|控制|标准|规范).*$', ''),
        (r'(?:产品|制剂|药品|药物).*$', ''),
        (r'(?:生物|细胞|基因|蛋白|抗体|疫苗|化药|中药|天然产物).*$', ''),
        (r'(?:临床|非临床|药学|药理|毒理|临床前).*$', ''),
    ]
    for pattern, repl in suffixes_to_try:
        truncated = re.sub(pattern, '', keyword)
        if truncated and truncated != keyword and truncated not in variants:
            variants.append(truncated)
    # 逐步缩短：每次去掉尾部1个字符（直到只剩2字）
    for i in range(len(keyword) - 1, 1, -1):
        v = keyword[:i]
        if v not in variants:
            variants.append(v)
    # 去重，保持顺序
    seen = set(); unique = []
    for v in variants:
        if v not in seen: seen.add(v); unique.append(v)
    return unique

def match_override(keyword, primary=None):
    """升级版 override 匹配：支持变量提取 + 方法明确性"""
    match_key = primary if primary else keyword
    overrides = get_user_overrides()

    for entry in overrides:
        pattern = entry.get('task_pattern', '')
        for kw in [match_key, keyword]:
            if re.search(pattern, kw):
                entry_copy = dict(entry)
                entry_copy['_matched_on'] = pattern
                var = extract_var_from_match(pattern, kw)
                if var:
                    entry_copy['_var'] = var
                    log(f"    📌 提取变量: '{var}'")
                return entry_copy
    return None

# ==================== 🧠 智能化感知与提取 ====================

async def get_links_with_full_context(page):
    return await page.evaluate('''() => {
        // v2.6.2: 排除导航、页脚等非内容区域
        const contentArea = document.querySelector('.list_main, .list_con, .list_main_content, .list_box, #content') || document.body;
        const rows = Array.from(contentArea.querySelectorAll('li, tr, .list_item, .list_con_li'));

        const anyIn = (list, text) => list.some(k => text.includes(k));

        return rows.map(row => {
            const link = row.querySelector('a');
            const rowText = row.innerText || '';
            const dateMatch = rowText.match(/(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2})|(\d{1,2}[-.]\d{1,2})/);

            // v2.6.3: 内容关键词初步筛选（过滤非实质性通告链接，如"联系我们"等导航噪音）
            const linkText = link ? link.innerText : '';
            const isContent = anyIn(['指导原则', '通告', '公告', '管理办法', '意见', '征求'], linkText + rowText);

            if (!isContent) return null;

            return link ? {
                href: link.href,
                text: linkText.trim(),
                full_row: rowText.replace(/\s+/g, ' '),
                date: dateMatch ? dateMatch[0] : null
            } : null;
        }).filter(i => i && i.text.length > 2);
    }''')

async def smart_interact(page, intent, try_date_only=False, search_var=None, search_field=None):
    """search_var: 传入提取的变量作为搜索词；search_field: 搜索字段类型（title/content/date）"""
    try:
        current_url = page.url
        inputs = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('input')).map(i => ({ id: i.id, name: i.name, placeholder: i.placeholder, visible: i.offsetWidth > 0 }));
        }''')
        log(f"    [smart_interact] page_url={current_url}, found {len(inputs)} inputs")
    except Exception as e:
        log(f"⚠️ 页面元素扫描失败: {e}")
        try:
            log(f"    [smart_interact] current_url at failure: {page.url}")
        except:
            log(f"    [smart_interact] could not get page url")
        inputs = []
        return False
    filled = False
    log(f"    [smart_interact] try_date_only={try_date_only}, search_var={search_var!r}, search_field={search_field}")
    if try_date_only:
        query = intent['date_only']
        log(f"    [smart_interact] using date_only query: {query!r}")
    elif search_var:
        query = search_var  # 变量优先：如"沟通交流"
        log(f"    [smart_interact] using search_var query: {query!r}")
    else:
        query = intent['query']
        log(f"    [smart_interact] using intent query: {query!r}")

    log(f"🧠 感知到 {len(inputs)} 个输入框: {[i['placeholder'] or i['id'] or i['name'] for i in inputs if i['visible']]}")
    for i in inputs:
        # v2.6.5: 安全字符串拼接，防止 NoneType 导致崩溃
        meta = (str(i['id'] or '') + str(i['name'] or '') + str(i['placeholder'] or '')).lower()
        if any(k in meta for k in ['keyword', '关键词', '标题', 'search']) and i['visible']:
            selector = f"input[placeholder='{i['placeholder']}']" if i['placeholder'] else (f"input[name='{i['name']}']" if i['name'] else f"input[id='{i['id']}']")
            log(f"    ✏️ 填充搜索框: {selector} (填入: {query})")
            await page.fill(selector, query)
            # 尝试点击搜索按钮（如果存在）
            search_btn = await page.query_selector('button:has-text("搜索"), .search-btn, #searchBtn, .btn-search')
            if search_btn:
                await search_btn.click()
                log("    🖱️ 点击搜索按钮")
            else:
                await page.keyboard.press('Enter')
                log("    ⌨️ 按下回车")
            filled = True
        if intent['date'] and any(k in meta for k in ['date', 'time', '日期']):
            try: await page.fill(f"input[name='{i['name']}']" if i['name'] else f"input[id='{i['id']}']", intent['date']); filled = True
            except: pass
    if filled:
        # 等待搜索结果加载
        await asyncio.sleep(5)
    return filled

async def explore_with_pagination(page, intent, exploration_points, search_var=None):
    """search_var: 传入提取的变量，优先作为搜索词使用"""
    all_results = []
    seen = set()
    for name, url in exploration_points.items():
        log(f"🚀 探索: {name}")
        try:
            await page.goto(url, wait_until='networkidle')
            # 等待搜索表单动态加载（最多等15秒）
            for _wait in range(15):
                try:
                    inputs_check = await page.evaluate('''() => {
                        const ins = Array.from(document.querySelectorAll('input')).filter(i => i.offsetWidth > 0);
                        return ins.length;
                    }''')
                    if inputs_check > 0:
                        log(f"    ⏳ 等待表单渲染: {_wait+1}秒后检测到{inputs_check}个输入框")
                        break
                except:
                    pass
                await asyncio.sleep(1)
            else:
                log(f"    ⚠️ 等待表单超时，尝试继续...")
            # 策略 1：正常搜（search_var 优先，如"沟通交流"）
            filled = await smart_interact(page, intent, search_var=search_var)
            
            # 等待搜索结果加载
            await asyncio.sleep(5)
            
            # 首次扫描（基于搜索结果）
            page_links = await get_links_with_full_context(page)
            # 调试：打印页面中所有链接文本
            try:
                all_text = await page.evaluate('''() => {
                    const items = document.querySelectorAll('li, tr, .list_item, .list_con_li, .result_item');
                    const result = [];
                    items.forEach(i => { if(i.innerText.trim().length > 3) result.push(i.innerText.trim().substring(0, 80)); });
                    return result.slice(0, 20);
                }''')
                log(f"    🔍 页面片段: {all_text[:5]}")
            except Exception as e:
                log(f"    🔍 页面片段获取失败: {e}")
            except Exception as e:
                log(f"    🔍 页面片段获取失败: {e}")
            log(f"    📋 首次扫描: 找到 {len(page_links)} 条记录")
            # 调试：打印前3条的标题
            for debug_l in page_links[:3]:
                log(f"       - {debug_l['text'][:50]} | date={debug_l.get('date')}")
            for l in page_links:
                if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
            
            # 如果结果少，降级重试（截短策略）
            if len(all_results) < 5:
                if search_var:
                    # 先尝试完整关键词
                    await page.goto(url); await asyncio.sleep(5)
                    await smart_interact(page, intent, search_var=search_var)
                    await asyncio.sleep(3)
                    page_links = await get_links_with_full_context(page)
                    log(f"    📋 关键词'{search_var}'扫描: 找到 {len(page_links)} 条")
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                    # 如果仍少，启用截短策略
                    if len(all_results) < 5:
                        variants = generate_truncated_variants(search_var)
                        log(f"    💡 结果仍少({len(all_results)}条)，启动截短策略: {variants}")
                        for var in variants[1:]:  # 跳过第一个（就是完整关键词，已试过）
                            if var == search_var:
                                continue
                            log(f"    🔄 截短重试: '{var}'")
                            await page.goto(url); await asyncio.sleep(5)
                            await smart_interact(page, intent, search_var=var)
                            await asyncio.sleep(3)
                            page_links = await get_links_with_full_context(page)
                            log(f"    📋 截短'{var}'扫描: 找到 {len(page_links)} 条")
                            for l in page_links:
                                if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                            if len(all_results) >= 5:
                                log(f"    ✅ 截短成功，获得足够结果")
                                break
                elif intent.get('date'):
                    log(f"    💡 结果较少({len(all_results)}条)，尝试仅用日期重搜...")
                    await page.goto(url); await asyncio.sleep(5)
                    await smart_interact(page, intent, try_date_only=True)
                    await asyncio.sleep(3)
                    page_links = await get_links_with_full_context(page)
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
            
            # 翻页
            for p_idx in range(2, 6):
                next_btn = await page.query_selector('text="下一页"') or await page.query_selector('a:has-text(">")')
                if next_btn and p_idx < 6:
                    await next_btn.click(); await asyncio.sleep(5)
                    page_links = await get_links_with_full_context(page)
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                else: break
        except Exception as e:
            log(f"⚠️ 探索异常: {e}")
    return all_results

# ==================== 🧬 模糊语义匹配 ====================

def fuzzy_semantic_filter(results, intent):
    """语义过滤：日期硬匹配 或 关键词匹配"""
    m = re.search(r'(\d{1,2})月(\d{1,2})', intent['original'])
    if m:
        mon, day = m.group(1), m.group(2)
        targets = [f"{int(mon)}月{int(day)}日", f"{mon.zfill(2)}-{day.zfill(2)}", f"{mon.zfill(2)}.{day.zfill(2)}", f"{int(mon)}-{int(day)}", f"{int(mon)}.{int(day)}"]
        # 日期命中模式
        return [r for r in results if any(t in (r['text'] + (r['date'] or '') + r['full_row']).replace(' ', '') for t in targets)]

    # 无日期模式：使用 intent 中的关键词进行语义匹配
    query_parts = intent['query'].split()
    return [r for r in results if any(q in (r['text'] + r['full_row']) for q in query_parts)]

# ==================== 📥 全要素下载逻辑 ====================

async def final_download(page, results):
    save_dir = os.path.expanduser("~/Documents/工作/法规指导原则"); os.makedirs(save_dir, exist_ok=True)
    total_count = 0
    for r in results:
        log(f"🔍 详情页提取: {r['text'][:40]}...")
        try:
            await page.goto(r['href']); await asyncio.sleep(10)
            d_links = await page.query_selector_all('a[href*="download"], a[href*=".pdf"], a[href*=".doc"], a[href*=".xls"]')
            d_m = re.search(r'(\d{4})[年/-]?(\d{1,2})[月/-]?(\d{1,2})', r['full_row'] + await page.content())
            publish_date = f"{d_m.group(1)}{d_m.group(2).zfill(2)}{d_m.group(3).zfill(2)}" if d_m else time.strftime('%Y%m%d')
            for link in d_links:
                attachment_name = (await link.inner_text()).strip() or "附件"
                if any(ext in attachment_name.lower() for ext in ['.pdf', '.doc', '.xls', '指导原则', '表', '说明', '附件']):
                    clean_title = re.sub(r'[\\/:*?"<>|]', '_', r['text'][:50])
                    clean_attach = re.sub(r'[\\/:*?"<>|]', '_', attachment_name)

                    # v2.6.1 精准判定逻辑：
                    # 1. 独立正文：含有指导原则/征求意见稿，但排除辅助性关键词
                    is_main_doc = any(k in clean_attach for k in ['指导原则', '征求意见稿', '试行', '正式']) \
                                  and not any(k in clean_attach for k in ['起草说明', '反馈表', '修订说明', '附件', '说明'])

                    # 2. 判定标题是否已经"你中有我"（针对那种附件名就是通告全名的情况）
                    core_title = re.sub(r'^关于公开征求《?|》?等.*$', '', clean_title)
                    is_already_contained = core_title[:10] in clean_attach or clean_attach[:10] in core_title

                    if is_main_doc or is_already_contained:
                        # 正文文件，或附件名已包含主旨 -> 直接用附件名
                        fname = f"{publish_date} - {clean_attach}"
                    else:
                        # 辅助文件（如起草说明、反馈表） -> 必须挂载主标题前缀
                        fname = f"{publish_date} - {clean_title} - {clean_attach}"
                    if not fname.lower().endswith(('.pdf', '.docx', '.doc', '.xlsx', '.xls')): fname += ".pdf"
                    fpath = os.path.join(save_dir, fname)
                    if not os.path.exists(fpath):
                        log(f"    📥 下载: {fname}")
                        try:
                            async with page.expect_download(timeout=60000) as di: await link.click()
                            d = await di.value; await d.save_as(fpath); log(f"    ✅ 成功: {fname}"); total_count += 1
                        except: pass
                    else: log(f"    ⏩ 跳过: {fname}")
        except: pass
    return total_count

# ==================== 🏁 入口 ====================

async def main_flow(keyword):
    intent = extract_task_intent(keyword)
    log(f"🎯 任务: {intent['query']} | 主体: {intent['primary']} | 限定: {intent.get('qualifiers', [])}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        page = await browser.new_page()

        # 升级：优先用主体词匹配 override
        entry = match_override(keyword, primary=intent.get('primary'))

        if entry:
            log(f"🧠 经验命中: {entry.get('note', '')} (匹配依据: {entry.get('_matched_on', '')})")

            # 根据 method 决定执行方式，不再双轨并行
            method = entry.get('method', 'both')
            pts = {}

            if method == 'navigate_only':
                if entry.get('target_url'):
                    pts["经验导航"] = entry['target_url']
            elif method == 'search_only':
                # search_only：用 target_url 作为搜索入口
                if entry.get('target_url'):
                    pts["经验搜索"] = entry['target_url']
                elif entry.get('search_url'):
                    pts["经验搜索"] = entry['search_url']
            else:  # both
                if entry.get('target_url'):
                    pts["经验导航"] = entry['target_url']
                if entry.get('search_url'):
                    pts["经验搜索"] = entry['search_url']
        else:
            # 无经验时：默认双轨并行
            method = 'both'
            primary = intent.get('primary', keyword)
            target_url = CDE_ENTRY_PAGES.get(primary)
            pts = {"默认入口": target_url} if target_url else CDE_ENTRY_PAGES

        log(f"📌 执行方式: {method} {'(仅使用经验指定方式，不再双轨并行)' if entry and method != 'both' else '(默认双轨并行)'}")

        # 提取变量（用于 search_only 模式的搜索词）
        search_var = entry.get('_var') if entry else None
        log(f"    🔍 search_var = {repr(search_var)}")

        raw_list = await explore_with_pagination(page, intent, pts, search_var=search_var)
        final_list = fuzzy_semantic_filter(raw_list, intent)

        # 如果有限定词，进一步过滤结果
        qualifiers = intent.get('qualifiers', [])
        if qualifiers and final_list:
            before = len(final_list)
            final_list = [r for r in final_list if any(
                q in (r['text'] + r['full_row']) for q in qualifiers
            )]
            log(f"🔍 限定词过滤 '{qualifiers}'：{before} → {len(final_list)} 条")

        if not final_list: log("❌ 未发现匹配项。")
        else:
            log(f"📋 发现 {len(final_list)} 条通告，提取全量附件...")
            downloaded = await final_download(page, final_list)
            log(f"🎉 任务完成：共下载 {downloaded} 个关联文件。")
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) > 1: asyncio.run(main_flow(sys.argv[1]))
    else: print("用法: python web_access.py <关键词>")
    print("\n✅ 完成")
