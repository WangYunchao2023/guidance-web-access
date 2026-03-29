#!/usr/bin/env python3
"""
通用网页访问工具(全要素泛化版)
版本: 3.9.0 (2026-03-27)  # 页面稳定性检测升级为多维度版本：同时监控文本+节点+链接三维增量，解决"壳先稳但内容后出"问题
核心逻辑:语义级文件名智能判定 + 主体词/限定词语义分级 + 通用文本内容提取（v3.0.0 全扫描+关键词匹配方案）
核心逻辑：语义级文件名智能判定 + 主体词/限定词语义分级 + 通用文本内容提取（v2.9.0 AI协同决策）
更新:Cortana全程主导探索
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

# ==================== 🛠️ 辅助函数 ====================

# ==================== 🧠 智能化感知与提取 ====================

async def get_links_by_text_content_v2(page, search_keyword=None):
    """
    v2.9.1: 改进版内容提取器 - 基于"整行提取"策略，适用于表格/列表结构。
    
    原理:不再依赖"文本节点→向上找链接"的树遍历方式,
    而是先识别页面中的列表/表格结构(行级元素),
    再在每行内同时查找文本和链接,确保关键词与链接在同一条目时能正确提取。
    
    适用于CDE等网站的结果页,关键词文本和下载链接可能在同一行的不同单元格中。
    """
    return await page.evaluate(r'''
        (searchKeyword) => {
        const keyword = searchKeyword || '';
        const kwLower = keyword.toLowerCase();

        // =============================================
        // 步骤1: 获取 body innerText
        // =============================================
        const bodyText = (document.body.innerText || document.body.textContent || '');
        const bodyLen = bodyText.trim().length;
        if (bodyLen === 0) return [];

        // =============================================
        // 步骤2: 用TreeWalker遍历所有文本节点
        // =============================================
        const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null
        );

        const allTextNodes = [];
        let node;
        while (node = walker.nextNode()) {
            const text = (node.nodeValue || '').trim();
            if (text.length > 2 && text.length < 500) {
                allTextNodes.push({
                    node: node,
                    text: text,
                    parent: node.parentElement
                });
            }
        }

        // =============================================
        // 步骤2: 找到包含关键词的文本节点
        // 注意:关键词可能被拆到多个节点,需要用"节点组"方式匹配
        // 策略:先按父子关系对相邻节点分组,再检查整组文本是否包含关键词
        // =============================================
        const keywordNodes = [];

        if (kwLower) {
            // 方案A:直接匹配(大多数情况下有效)
            const directMatch = allTextNodes.filter(tn => tn.text.toLowerCase().includes(kwLower));
            if (directMatch.length > 0) {
                keywordNodes.push(...directMatch);
            } else {
                // 方案B:节点组匹配 - 遍历文本节点,检查其父容器内是否有关键词
                // 思路:如果文本节点的父容器(如div/span)的innerText包含关键词,则该节点算匹配
                for (const tn of allTextNodes) {
                    let container = tn.parent;
                    let depth = 0;
                    while (container && depth < 5) {
                        const containerText = (container.innerText || '').toLowerCase();
                        if (containerText.includes(kwLower)) {
                            keywordNodes.push(tn);
                            break;
                        }
                        container = container.parentElement;
                        depth++;
                    }
                }
            }
        } else {
            // 无关键词时:返回所有文本节点
            keywordNodes.push(...allTextNodes);
        }

        if (keywordNodes.length === 0) {
            return [];
        }

        // =============================================
        // 步骤3: 对每个关键词节点,提取完整条目
        // =============================================
        // 策略:文本节点 → 向上找最近的 Block 容器 → 提取块内所有链接
        const results = [];
        const seenHrefs = new Set();

        for (const kNode of keywordNodes) {
            // 向上找块容器(div/li/tr/td/article)
            let block = kNode.parent;
            let depth = 0;
            while (block && depth < 10) {
                const tag = block.tagName;
                if (tag === 'DIV' || tag === 'LI' || tag === 'TR' || tag === 'TD' || tag === 'A' || tag === 'ARTICLE') {
                    break;
                }
                block = block.parentElement;
                depth++;
            }
            // 找不到合适容器就用 body
            const container = block || document.body;

            // 从容器内提取日期
            const containerText = container.innerText || '';
            let date = null;
            const dateM = containerText.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
            if (dateM) {
                date = dateM[1] + '.' + dateM[2].padStart(2,'0') + '.' + dateM[3].padStart(2,'0');
            }

            // 从容器内提取所有有效链接
            const links = container.querySelectorAll('a[href]');
            for (const link of links) {
                const href = link.href;
                const linkText = (link.innerText || '').trim();
                // 过滤无效链接
                if (!href || !href.startsWith('http') || href.includes('javascript')) continue;
                if (linkText.length < 3) continue;
                // 跳过相同 href
                if (seenHrefs.has(href)) continue;
                seenHrefs.add(href);

                results.push({
                    href: href,
                    text: linkText,
                    full_row: (container.innerText || '').replace(/\s+/g, ' ').trim(),
                    date: date
                });
            }
        }

        // =============================================
        // 步骤4: 内容质量过滤
        // =============================================
        const noiseIndicators = ['copyright', '版权所有', '登录', '注册', '更多', '更多>'];
        const contentIndicators = ['指导原则', '办法', '规程', '通知', '公告', '意见', '规范', '准则', '要求', '技术', '指引', '原则'];

        const filtered = results.filter(r => {
            const row = (r.full_row || '') + (r.text || '');
            // 纯噪音
            if (noiseIndicators.every(n => !row.includes(n))) {
                // 但没有内容指示词时,文本要足够长
                if (!contentIndicators.some(c => row.includes(c)) && r.text.length < 15) {
                    return false;
                }
            }
            return row.length >= 10;
        });

        return filtered;
    }''', search_keyword)

# ================================================================
# v3.0.0: 全扫描+关键词匹配 - 最通用方案
async def smart_interact(page, intent, try_date_only=False, search_var=None, search_field=None):
    """search_var: 传入提取的变量作为搜索词;search_field: 搜索字段类型(title/content/date)"""
    try:
        current_url = page.url
        inputs = await page.evaluate(r'''() => {
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
        query = search_var  # 变量优先:如"沟通交流"
        log(f"    [smart_interact] using search_var query: {query!r}")
    elif intent.get('date') and intent.get('primary'):
        # v2.7.3: 有日期时,标题框只填主体词,不填日期
        # 日期由专用日期字段处理,避免"3月9日"被当成标题内容搜索
        query = intent['primary']
        log(f"    [smart_interact] 日期+主体词:标题填'{query}',日期由专用字段处理")
    else:
        query = intent['query']
        log(f"    [smart_interact] using intent query: {query!r}")

    log(f"🧠 感知到 {len(inputs)} 个输入框: {[i['placeholder'] or i['id'] or i['name'] for i in inputs if i['visible']]}")
    for i in inputs:
        # v2.6.5: 安全字符串拼接,防止 NoneType 导致崩溃
        meta = (str(i['id'] or '') + str(i['name'] or '') + str(i['placeholder'] or '')).lower()
        if any(k in meta for k in ['keyword', '关键词', '标题', 'search']) and i['visible']:
            selector = f"input[placeholder='{i['placeholder']}']" if i['placeholder'] else (f"input[name='{i['name']}']" if i['name'] else f"input[id='{i['id']}']")
            log(f"    ✏️ 填充搜索框: {selector} (填入: {query})")
            await page.fill(selector, query)
            # 尝试点击搜索按钮(如果存在)
            search_btn = await page.query_selector('button:has-text("搜索"), .search-btn, #searchBtn, .btn-search')
            if search_btn:
                await search_btn.click()
                log("    🖱️ 点击搜索按钮")
            else:
                await page.keyboard.press('Enter')
                log("    ⌨️ 按下回车")
            filled = True
        # v2.7.3: layui readonly 日期组件--JS 设置值 + 触发 laydate 事件
        if intent['date'] and any(k in meta for k in ['date', 'time', '日期']):
            try:
                selector = f"input[name='{i['name']}']" if i['name'] else f"input[id='{i['id']}']"
                await page.evaluate(r'''(args) => {
                    const el = document.querySelector(args.selector);
                    if (!el) return;
                    // 绕过 readonly:直接用 Object.getOwnPropertyDescriptor 设置值
                    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    nativeSetter.call(el, args.value);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    // 额外触发 layui laydate 事件(如果有)
                    if (window.layui && window.layui.laydate) {
                        try { window.layui.laydate.render({ elem: el, value: args.value }); } catch(e) {}
                    }
                }''', {"selector": selector, "value": intent['date']})
                filled = True
            except: pass
    if filled:
        # 等待搜索结果加载
        await asyncio.sleep(5)
    return filled


# ==================== 🧬 模糊语义匹配 ====================

# ================================================================
# 有经验分支：页面稳定性检测（多维度版本）
# 原理：同时监控文本增量、节点增量、链接增量，三维度同时稳定 quiet_rounds 轮则认为内容区加载完成
# 优势：避开轮播/广告/时间刷新等"壳先稳、内容后出"的假阳性问题
# v3.9.1: 节点数稳定优先（替换三维同时稳定），解决渐进式加载页面的超时问题
# ================================================================
async def wait_page_stable_exp(page, quiet_rounds=3, check_interval=1, max_rounds=60):
    """
    有经验分支专用页面稳定性检测（多维度版）
    同时监控：文本长度 + 内容节点数 + 链接数
    三个维度同时稳定 quiet_rounds 轮 → 认为内容区加载完成
    """
    prev_text_len = 0
    prev_node_count = 0
    prev_link_count = 0
    stable_rounds = 0
    for _round in range(max_rounds):
        await asyncio.sleep(check_interval)
        try:
            metrics = await page.evaluate(r'''() => {
                    const nodeCount = document.querySelectorAll(
                        '.news_item, li, tr, .article-item, .list-item, .item, .result-item'
                    ).length;
                    const linkCount = document.querySelectorAll('a[href]').length;
                    return {
                        text_len: (document.body.innerText || '').length,
                        node_count: nodeCount,
                        link_count: linkCount
                    };
                }
            ''')
        except:
            break

        text_delta = abs(metrics['text_len'] - prev_text_len)
        node_delta = abs(metrics['node_count'] - prev_node_count)
        link_delta = abs(metrics['link_count'] - prev_link_count)

        text_stable = text_delta < 100
        node_stable = node_delta < 3
        link_stable = link_delta < 5

        if text_stable and node_stable and link_stable:
            stable_rounds += 1
            if stable_rounds >= quiet_rounds:
                log(f"    ✅ 内容区已稳定 (文本约{metrics['text_len']}字, 节点约{metrics['node_count']}个, 链接约{metrics['link_count']}个)")
                return True
        else:
            stable_rounds = 0
            log(f"    ⏳ 加载中... 文本{prev_text_len}→{metrics['text_len']}(+{text_delta}), 节点{prev_node_count}→{metrics['node_count']}(+{node_delta}), 链接{prev_link_count}→{metrics['link_count']}(+{link_delta})")

        prev_text_len = metrics['text_len']
        prev_node_count = metrics['node_count']
        prev_link_count = metrics['link_count']

    log(f"    ⚠️ 页面稳定性等待超时({max_rounds}轮)，强制继续")
    return False



# ================================================================
# 有经验分支：探索函数
# ================================================================
async def explore_with_pagination_v2(page, intent, exploration_points):
    """
    有经验分支专用探索函数：按 Cortana 制订的完整计划执行，不中途决策。
    
    exploration_points: dict{name: {"url": str, "sv": str|None}}
      sv=None  → 不填搜索框，由 smart_interact 的 date+primary 逻辑决定填什么
      sv=str   → 用指定字符串填搜索框
    
    执行流程：依次执行每个探索点 → 翻页提取 → 合并去重 → 返回所有结果
    """
    all_results = []
    seen = set()
    for name, pt in exploration_points.items():
        url = pt["url"]
        sv = pt.get("sv")  # None means use date+primary logic in smart_interact
        log(f"🚀 探索: {name} (sv={repr(sv)})")
        try:
            await page.goto(url, wait_until='domcontentloaded')
            await wait_page_stable_exp(page)

            # 填充搜索(sv=None 时 smart_interact 会用 date+primary 逻辑)
            await smart_interact(page, intent, search_var=sv)
            await wait_page_stable_exp(page)

            page_links = await get_links_by_text_content_v2(page, sv)
            log(f"    📋 首次扫描: 找到 {len(page_links)} 条")
            # 调试:打印前5条的日期
            for dl in page_links[:5]:
                log(f"       [{dl.get('date','无日期')}] {dl['text'][:60]}")
            for l in page_links:
                if l['href'] not in seen:
                    all_results.append(l); seen.add(l['href'])

            # 翻页（增强版）
            for p_idx in range(2, 6):
                try:
                    # 多种选择器检测"下一页"按钮
                    next_btn = (
                        await page.query_selector('text="下一页"') or
                        await page.query_selector('a:has-text("下一页")') or
                        await page.query_selector('button:has-text("下一页")') or
                        await page.query_selector('a:has-text(">")') or
                        await page.query_selector('.layui-laypage-next') or
                        await page.query_selector('[aria-label="下一页"]')
                    )
                    
                    if not next_btn:
                        log(f"    📄 第{p_idx-1}页已完成，未找到下一页按钮，停止翻页")
                        break
                    
                    # 检查按钮是否可点击
                    is_disabled = await next_btn.get_attribute('disabled')
                    cls = await next_btn.get_attribute('class') or ''
                    txt = (await next_btn.inner_text()).strip()
                    
                    # 判断是否禁用：class包含disabled或aria-disabled，或有disabled属性
                    if is_disabled is not None or 'layui-disabled' in cls or 'disabled' in cls:
                        if 'layui-disabled' not in cls:
                            pass  # 可能只是最后一页
                        log(f"    📄 第{p_idx-1}页已完成，翻页按钮已禁用，停止翻页")
                        break
                    
                    if not txt:
                        log(f"    📄 第{p_idx-1}页已完成，按钮无文本，停止翻页")
                        break
                    
                    log(f"    📄 翻到第{p_idx}页...")
                    await next_btn.click()
                    await wait_page_stable_exp(page)
                    
                    # 扫描当前页
                    page_links = await get_links_by_text_content_v2(page, None)
                    log(f"    📄 第{p_idx}页: 找到 {len(page_links)} 条")
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                        
                except Exception as e:
                    log(f"    ⚠️ 翻页异常: {e}")
                    break
        except Exception as e:
            log(f"⚠️ 探索异常: {e}")
    return all_results

# ==================== 🧬 模糊语义匹配 ====================


def fuzzy_semantic_filter(results, intent):
    """语义过滤:日期硬匹配 或 关键词匹配"""
    m = re.search(r'(\d{1,2})月(\d{1,2})', intent['original'])
    if m:
        mon, day = m.group(1), m.group(2)
        targets = [f"{int(mon)}月{int(day)}日", f"{mon.zfill(2)}-{day.zfill(2)}", f"{mon.zfill(2)}.{day.zfill(2)}", f"{int(mon)}-{int(day)}", f"{int(mon)}.{int(day)}"]
        # 日期命中模式
        return [r for r in results if any(t in (r['text'] + (r['date'] or '') + r['full_row']).replace(' ', '') for t in targets)]

    # 无日期模式:使用 intent 中的关键词进行语义匹配
    query_parts = intent['query'].split()
    filtered = [r for r in results if any(q in (r['text'] + r['full_row']) for q in query_parts)]
    # v2.9.0: 支持二次过滤关键词（用于复合关键词场景，如"化药+稳定性"）
    extra_filter = intent.get('extra_filter')
    if extra_filter and filtered:
        before = len(filtered)
        filtered = [r for r in filtered if extra_filter in (r['text'] + r['full_row'])]
        log(f"🔍 二次过滤'{extra_filter}': {before} → {len(filtered)} 条")
    return filtered

# ==================== 📥 全要素下载逻辑 ====================

async def final_download(page, results, keyword="", custom_save_dir=None):
    # v3.0.2: 默认目录 + 用户指定目录支持
    if custom_save_dir:
        save_dir = os.path.expanduser(custom_save_dir)
        log(f"📁 使用指定保存目录: {save_dir}")
    else:
        save_dir = os.path.expanduser("~/Documents/工作/法规指导原则/沟通交流")
        log(f"📁 默认保存目录: {save_dir}")
    os.makedirs(save_dir, exist_ok=True)
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

                    # v2.6.1 精准判定逻辑:
                    # 1. 独立正文:含有指导原则/征求意见稿,但排除辅助性关键词
                    is_main_doc = any(k in clean_attach for k in ['指导原则', '征求意见稿', '试行', '正式']) \
                                  and not any(k in clean_attach for k in ['起草说明', '反馈表', '修订说明', '附件', '说明'])

                    # 2. 判定标题是否已经"你中有我"(针对那种附件名就是通告全名的情况)
                    core_title = re.sub(r'^关于公开征求《?|》?等.*$', '', clean_title)
                    is_already_contained = core_title[:10] in clean_attach or clean_attach[:10] in core_title

                    if is_main_doc or is_already_contained:
                        # 正文文件,或附件名已包含主旨 -> 直接用附件名
                        fname = f"{publish_date} - {clean_attach}"
                    else:
                        # 辅助文件(如起草说明、反馈表) -> 必须挂载主标题前缀
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

async def cortana_execute_flow(cortana_plan):
    """
    Cortana 主导的执行入口
    接收 Cortana 制订的完整执行计划，直接执行
    
    cortana_plan 格式:
    {
        "task": "任务描述",
        "search_url": "搜索页URL（可选）",
        "search_var": "搜索关键词（可选）",
        "filter_criteria": ["过滤条件1", "过滤条件2"],
        "list_urls": ["列表页URL1", "列表页URL2"],  # 用于层级导航
        "method": "search_only" | "navigate_only" | "both",
        "extra_filter": "额外过滤条件（可选）",
        "save_dir": "保存目录"
    }
    """
    log(f"🎯 Cortana 执行计划: {cortana_plan.get('task', '')}")
    
    task = cortana_plan.get('task', '')
    search_url = cortana_plan.get('search_url')
    search_var = cortana_plan.get('search_var')
    filter_criteria = cortana_plan.get('filter_criteria', [])
    list_urls = cortana_plan.get('list_urls', [])
    method = cortana_plan.get('method', 'both')
    extra_filter = cortana_plan.get('extra_filter')
    save_dir = cortana_plan.get('save_dir')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        page = await browser.new_page()
        await page.add_init_script('''() => {
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
        }''')
        
        # 构建探索点
        pts = {}
        
        # 层级导航：列表页
        if list_urls:
            for idx, url in enumerate(list_urls):
                pts[f"列表{idx+1}"] = {"url": url, "sv": None}
        
        # 搜索页
        if search_url:
            pts["搜索页"] = {"url": search_url, "sv": search_var}
        
        log(f"📌 执行方式: {method}")
        log(f"📌 探索点: {list(pts.keys())}")
        log(f"📌 搜索词: {repr(search_var)}")
        log(f"📌 过滤条件: {filter_criteria}")
        
        # Cortana 主导模式下，使用更宽松的过滤逻辑
        # 不使用 fuzzy_semantic_filter（它会用 intent['query'] 过滤，导致误杀）
        # 直接使用探索结果，只用 filter_criteria 过滤
        
        # 构建 intent（用于 explore_with_pagination_v2 内部）
        intent_for_explore = {
            'query': search_var or task,
            'original': task,
            'primary': search_var or task,
            'qualifiers': filter_criteria,
            'date': None,
            'extra_filter': None  # Cortana模式不使用这个
        }
        
        # 执行探索
        raw_list = await explore_with_pagination_v2(page, intent_for_explore, pts)
        
        # Cortana 模式下，只用 filter_criteria 过滤
        final_list = raw_list
        if filter_criteria and final_list:
            before = len(final_list)
            final_list = [r for r in final_list if any(
                q in (r['text'] + r['full_row']) for q in filter_criteria
            )]
            log(f"🔍 Cortana过滤条件 {filter_criteria}: {before} → {len(final_list)} 条")
        
        if not final_list:
            log("❌ 未发现匹配项。")
        else:
            log(f"📋 发现 {len(final_list)} 条通告,提取全量附件...")
            downloaded = await final_download(page, final_list, task, custom_save_dir=save_dir)
            log(f"🎉 任务完成:共下载 {downloaded} 个关联文件。")
        
        await browser.close()




# ==================== 🚀 无经验自感知探索辅助函数 ====================

async def perception_next_page(page, max_pages=10):
    """
    在感知模式下翻页
    返回: (成功标志, 新页面URL)
    """
    selectors = [
        'text="下一页"', 'a:has-text("下一页")', 'a:has-text(">")',
        '.layui-laypage-next', '[aria-label="下一页"]',
        'button:has-text("下一页")', 'text="后一页"', 'a:has-text("后一页")'
    ]
    
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                cls = await btn.get_attribute('class') or ''
                disabled = await btn.get_attribute('disabled')
                if 'disabled' in cls.lower() or disabled:
                    log(f"📄 翻页按钮已禁用")
                    return False, None
                await btn.click()
                log(f"📄 已点击翻页")
                await asyncio.sleep(3)
                return True, page.url
        except:
            continue
    log(f"📄 未找到翻页按钮")
    return False, None


def match_keyword_to_selector(search_inputs, keyword):
    """
    智能匹配：找到最适合关键词的搜索框
    """
    if not search_inputs:
        return None
    if len(search_inputs) == 1:
        return search_inputs[0].get('selector')
    
    kw_lower = keyword.lower()
    is_title_word = any(kw in kw_lower for kw in ['指导原则', '法规', '公告', '通告', '管理办法'])
    is_content_word = any(kw in kw_lower for kw in ['沟通交流', '稳定性', '临床试验', '药学', '毒理'])
    
    best, best_score = None, -1
    for inp in search_inputs:
        ph = (inp.get('placeholder') or '').lower()
        score = 0
        if ('标题' in ph or 'title' in ph):
            score += 10 if is_title_word else 2
        if ('关键词' in ph or 'keyword' in ph):
            score += 10 if is_content_word else 2
        if '内容' in ph or 'content' in ph:
            score += 1
        if '搜索' in ph or 'search' in ph or '查询' in ph:
            score += 3
        if score > best_score:
            best_score = score
            best = inp.get('selector')
    
    log(f"🔍 关键词'{keyword}'匹配选择器: {best} (得分: {best_score})")
    return best


def filter_results_by_criteria(results, filter_criteria):
    """根据过滤条件过滤结果"""
    if not filter_criteria:
        return results
    filtered = []
    for result in results:
        text = result.get('title', '') + ' '
        for f in result.get('files', []):
            text += f.get('text', '') + ' '
        text_lower = text.lower()
        if all(c.lower() in text_lower for c in filter_criteria):
            filtered.append(result)
    return filtered


def deduplicate_results(existing, new_results):
    """去重新结果"""
    seen_urls = set(r.get('href', '') for r in existing)
    merged = list(existing)
    added = 0
    for r in new_results:
        href = r.get('href', '')
        if href and href not in seen_urls:
            merged.append(r)
            seen_urls.add(href)
            added += 1
    return merged, added



# ==================== 🚀 无经验分支：Cortana 全程感知探索引擎 ====================
# 完全独立于有经验分支
# 核心理念：感知 → Cortana决策 → 执行，循环往复直至找全

# ---------- 页面感知 ----------
async def perceive_current_page(page):
    """感知当前页面结构，返回所有可用信息"""
    try:
        page_info = await page.evaluate(r'''
            () => {
                const result = {
                    'url': window.location.href,
                    'title': document.title || '',
                    'search_inputs': [],
                    'nav_links': [],
                    'content_links': [],
                    'content_count': 0,
                    'text_length': 0
                };
                const inputSelectors = [
                    'input[type="text"]', 'input[placeholder*="搜索"]',
                    'input[placeholder*="keyword"]', 'input[placeholder*="查询"]',
                    'input[name*="keyword"]', 'input[name*="search"]'
                ];
                const urlSet = new Set();
                for (const sel of inputSelectors) {
                    const inputs = document.querySelectorAll(sel);
                    inputs.forEach(inp => {
                        if (inp.offsetWidth > 0) {
                            result.search_inputs.push({
                                'selector': inp.id ? '#'+inp.id : inp.name ? '[name="'+inp.name+'"]' : inp.placeholder ? '[placeholder="'+inp.placeholder+'"]' : sel,
                                'placeholder': inp.placeholder || inp.name || inp.id || 'text input'
                            });
                        }
                    });
                }
                const navSelectors = ['nav a', '.nav a', '.menu a', '.sidebar a', 'header a', '.left-nav a', '.guide-nav a'];
                for (const sel of navSelectors) {
                    const links = document.querySelectorAll(sel);
                    links.forEach(link => {
                        if (link.href && link.innerText.trim().length > 0 && !urlSet.has(link.href)) {
                            urlSet.add(link.href);
                            result.nav_links.push({
                                'name': link.innerText.trim().substring(0, 60),
                                'url': link.href
                            });
                        }
                    });
                }
                const allLinks = document.querySelectorAll('a[href]');
                const exclude = ['javascript', 'login', 'register', 'logout', 'copyright'];
                let count = 0;
                allLinks.forEach(link => {
                    if (count >= 200) return;
                    const href = link.href || '';
                    const text = (link.innerText || '').trim();
                    if (!href || text.length < 3) return;
                    if (exclude.some(p => href.toLowerCase().includes(p))) return;
                    if (href.startsWith('http') && !urlSet.has(href)) {
                        urlSet.add(href);
                        result.content_links.push({'name': text.substring(0, 80), 'url': href});
                        count++;
                    }
                });
                result.content_count = document.querySelectorAll('.news_item, li, tr, .article-item, .list-item').length;
                result.text_length = (document.body.innerText || '').length;
                return result;
            }
        ''')
        log("    📡 感知: url={}".format(page_info['url']))
        log("    📡 感知: 标题={}".format(page_info['title'][:50]))
        log("    📡 感知: 搜索框{}个, 内容链接{}个".format(len(page_info['search_inputs']), len(page_info['content_links'])))
        log("    📡 感知: 内容节点约{}个".format(page_info['content_count']))
        return page_info
    except Exception as e:
        log("    ⚠️ 感知异常: {}".format(e))
        return {'url': page.url, 'title': '', 'search_inputs': [], 'nav_links': [], 'content_links': [], 'content_count': 0, 'text_length': 0}


# ================================================================
# 无经验分支：页面稳定性检测（多维度版本）
# 原理：同时监控文本增量、节点增量、链接增量，三维度同时稳定 quiet_rounds 轮则认为内容区加载完成
# 优势：避开轮播/广告/时间刷新等"壳先稳、内容后出"的假阳性问题
# ================================================================
async def wait_page_stable_noexp(page, quiet_rounds=3, check_interval=1, max_rounds=60):
    """
    无经验分支专用页面稳定性检测（多维度版）
    同时监控：文本长度 + 内容节点数 + 链接数
    三个维度同时稳定 quiet_rounds 轮 → 认为内容区加载完成
    """
    prev_text_len = 0
    prev_node_count = 0
    prev_link_count = 0
    stable_rounds = 0
    for _round in range(max_rounds):
        await asyncio.sleep(check_interval)
        try:
            metrics = await page.evaluate(r'''
                () => {
                    const nodeCount = document.querySelectorAll(
                        '.news_item, li, tr, .article-item, .list-item, .item, .result-item'
                    ).length;
                    const linkCount = document.querySelectorAll('a[href]').length;
                    return {
                        text_len: (document.body.innerText || '').length,
                        node_count: nodeCount,
                        link_count: linkCount
                    };
                }
            ''')
        except:
            break

        text_delta = abs(metrics['text_len'] - prev_text_len)
        node_delta = abs(metrics['node_count'] - prev_node_count)
        link_delta = abs(metrics['link_count'] - prev_link_count)

        text_stable = text_delta < 100
        node_stable = node_delta < 3
        link_stable = link_delta < 5

        if text_stable and node_stable and link_stable:
            stable_rounds += 1
            if stable_rounds >= quiet_rounds:
                log(f"    ✅ 内容区已稳定 (文本约{metrics['text_len']}字, 节点约{metrics['node_count']}个, 链接约{metrics['link_count']}个)")
                return True
        else:
            stable_rounds = 0
            log(f"    ⏳ 加载中... 文本{prev_text_len}→{metrics['text_len']}(+{text_delta}), 节点{prev_node_count}→{metrics['node_count']}(+{node_delta}), 链接{prev_link_count}→{metrics['link_count']}(+{link_delta})")

        prev_text_len = metrics['text_len']
        prev_node_count = metrics['node_count']
        prev_link_count = metrics['link_count']

    log(f"    ⚠️ 页面稳定性等待超时({max_rounds}轮)，强制继续")
    return False


# ---------- 等待动态内容稳定（已废弃，仅保留签名兼容） ----------
async def wait_for_content_ready(page, timeout=15):
    """⚠️ 已废弃，请使用 wait_page_stable_noexp"""
    return await wait_page_stable_noexp(page, quiet_rounds=3, max_rounds=timeout)


# ---------- 多重过滤 ----------
def apply_filters(results, filter_criteria, date_enabled=False, date_value=None):
    """多重过滤：关键词AND匹配 + 噪音过滤 + 日期过滤（仅当任务明确指定日期时）"""
    if not results:
        return results
    filtered = results
    # 关键词过滤（所有 filter_criteria 词都要出现）
    if filter_criteria:
        before = len(filtered)
        filtered = [r for r in filtered if all(
            q in (r.get('text', '') + r.get('full_row', ''))
            for q in filter_criteria
        )]
        log("    🔍 关键词过滤 {}: {} -> {} 条".format(filter_criteria, before, len(filtered)))
    # 噪音过滤
    if filtered:
        noise = ['党建', '获奖', '招聘', '版权', 'copyright', '注册', '登录']
        before = len(filtered)
        filtered = [r for r in filtered if not any(np in (r.get('text', '') + r.get('full_row', '')) for np in noise)]
        if len(filtered) < before:
            log("    🔇 噪音过滤: {} -> {} 条".format(before, len(filtered)))
    # 日期过滤（仅当任务明确指定日期时生效）
    if date_enabled and date_value and filtered:
        before = len(filtered)
        dv = date_value.replace('-', '.').replace('/', '.')
        filtered = [r for r in filtered if dv in (r.get('date', '') + r.get('text', '') + r.get('full_row', '')).replace(' ', '')]
        log("    📅 日期过滤 {}: {} -> {} 条".format(date_value, before, len(filtered)))
    return filtered


# ---------- 探索分支主逻辑 ----------
async def explore_branch(page, url, depth, state, intent, filter_criteria, date_enabled, date_value):
    """
    探索一个分支：跳转 → 感知 → 输出AI_REPORT供Cortana决策
    
    state: {
        'visited_urls': set,
        'search_history': list,
        'all_results': list,
        'pending_candidates': list
    }
    """
    if depth > 5:
        log("    ⚠️ 超过最大深度限制({})，停止深入".format(depth))
        return []
    if not url or url in state['visited_urls']:
        return []

    log("\n{}".format("="*60))
    log("🔍 探索 [{}] (depth={})".format(url[:80], depth))
    log("{}".format("="*60))
    state['visited_urls'].add(url)

    try:
        await page.goto(url, wait_until='domcontentloaded')
    except Exception as e:
        log("    ⚠️ 跳转失败: {}".format(e))
        return []

    await wait_page_stable_noexp(page)
    page_info = await perceive_current_page(page)

    # 相似搜索检测
    similar = None
    primary = intent.get('primary', '')
    if primary:
        for hist in state['search_history']:
            if hist.get('sv') == primary:
                similar = hist
                break

    # AI_REPORT - 供 Cortana 分析并传入下一步决策
    log("\n{}".format("="*60))
    log("🤖 AI_REPORT: 页面感知完成，等待Cortana决策")
    log("   page_url: {}".format(page_info['url'][:80]))
    log("   page_title: {}".format(page_info.get('title', '')[:60]))
    log("   search_inputs: {} 个".format(len(page_info.get('search_inputs', []))))
    log("   nav_links: {} 个".format(len(page_info.get('nav_links', []))))
    log("   content_links: {} 个".format(len(page_info.get('content_links', []))))
    for lk in page_info.get('nav_links', [])[:8]:
        log("      [NAV] {} -> {}".format(lk['name'][:30], lk['url'][:60]))
    for lk in page_info.get('content_links', [])[:8]:
        log("      [LINK] {} -> {}".format(lk['name'][:40], lk['url'][:60]))
    log("   已探索URL: {} 个".format(len(state['visited_urls'])))
    log("   已搜索: {} 次".format(len(state['search_history'])))
    log("   当前结果: {} 条".format(len(state['all_results'])))
    log("   intent.query: {!r}".format(intent.get('query', '')))
    log("   intent.primary: {!r}".format(intent.get('primary', '')))
    log("   filter_criteria: {}".format(filter_criteria))
    log("   date_filter: {} (enabled={})".format(date_value, date_enabled))
    log("   similar_search: {}".format('是 - "'+similar['sv']+'"' if similar else '否'))
    log("{}".format("="*60))
    log("💡 Cortana分析以上感知结果后，传入下一步决策参数:")
    log("   next_action: 'search'|'click'|'return_home'|'stop'")
    log("   sv: '搜索词' (search时)")
    log("   target_url: 'URL' (click时)")
    log("   candidates: [{name,url,relevance}] (下步待探索链接)")
    log("   filter_criteria_override: [] (可选)")
    log("{}".format("="*60))

    return []


# ---------- cortana_auto_flow ----------
async def cortana_auto_flow(cortana_plan):
    """
    无经验分支主入口：Cortana 全程感知 + 决策探索

    cortana_plan 格式:
    {
        "task": "任务描述",
        "base_url": "起始URL（必填）",
        "filter_criteria": ["词1", "词2"],        // 可选，全局过滤
        "date_filter": "2025-03-09",               // 可选，仅任务明确指定日期时填
        "intent": {
            "query": "完整任务描述",
            "primary": "核心搜索词",               // 可选
            "date": "日期描述",                    // 可选
            "original": "原始任务"
        },
        "initial_candidates": [                     // 可选，Cortana感知首页后认为高相关的链接
            {"name": "链接名", "url": "https://...", "relevance": "high|medium|low"}
        ],
        "save_dir": "~/Documents/...",             // 可选
        "download_enabled": true                   // 任务是否要求下载
    }

    执行流程（每步都感知 → Cortana决策 → 执行）:
        1. 打开首页 → 感知
        2. Cortana 分析感知结果 → 决策
        3. 按决策执行（点击链接 / 搜索 / 返回）
        4. 每步都感知 → Cortana决策 → 执行（循环）
        5. 直到所有分支遍历完毕
        6. 汇总所有结果 → 多重过滤
        7. 根据 download_enabled 决定是否下载
    """
    log("🎯 Cortana 全程感知探索: {}".format(cortana_plan.get('task', '')))

    base_url = cortana_plan.get('base_url')
    filter_criteria = cortana_plan.get('filter_criteria', [])
    date_filter = cortana_plan.get('date_filter')
    date_enabled = date_filter is not None
    intent = cortana_plan.get('intent', {})
    save_dir = cortana_plan.get('save_dir')
    download_enabled = cortana_plan.get('download_enabled', False)
    initial_candidates = cortana_plan.get('initial_candidates', [])

    if not base_url:
        log("❌ cortana_auto_flow 需要 base_url 参数")
        return

    log("📌 base_url: {}".format(base_url))
    log("📌 filter_criteria: {}".format(filter_criteria))
    log("📌 date_filter: {} (enabled={})".format(date_filter, date_enabled))
    log("📌 download_enabled: {}".format(download_enabled))
    log("📌 initial_candidates: {} 个".format(len(initial_candidates)))

    # 探索状态（纯内存，过程结束后自动销毁）
    state = {
        'visited_urls': set(),
        'search_history': [],
        'all_results': [],
        'pending_candidates': []
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        page = await browser.new_page()
        await page.add_init_script('''() => {
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
        }''')

        # Step 1: 打开首页 → 感知
        log("\n🚀 打开首页...")
        await page.goto(base_url, wait_until='domcontentloaded')
        await wait_page_stable_noexp(page)
        home_info = await perceive_current_page(page)
        state['visited_urls'].add(home_info['url'])

        # 首页 AI_REPORT
        log("\n{}".format("="*60))
        log("🤖 AI_REPORT: 首页感知完成，等待Cortana决策")
        log("   page_title: {}".format(home_info.get('title', '')[:60]))
        log("   search_inputs: {} 个".format(len(home_info.get('search_inputs', []))))
        nav_list = home_info.get('nav_links', [])
        content_list = home_info.get('content_links', [])
        log("   nav_links: {} 个".format(len(nav_list)))
        for lk in nav_list[:10]:
            log("      - {} -> {}".format(lk['name'][:30], lk['url'][:60]))
        log("   content_links: {} 个".format(len(content_list)))
        for lk in content_list[:10]:
            log("      - {} -> {}".format(lk['name'][:40], lk['url'][:60]))
        log("   intent.query: {!r}".format(intent.get('query', '')))
        log("   intent.primary: {!r}".format(intent.get('primary', '')))
        log("   filter_criteria: {}".format(filter_criteria))
        log("   date_filter: {} (enabled={})".format(date_filter, date_enabled))
        log("{}".format("="*60))
        log("💡 Cortana请分析以上首页感知结果，决策下一步:")
        log("   - 是否使用搜索框搜索？")
        log("   - 点击哪些链接深入探索？")
        log("   - initial_candidates中的链接是否都高相关？")
        log("   请传入: next_action, sv, candidates 等决策参数")
        log("{}".format("="*60))

        # Step 2: 探索 initial_candidates
        if initial_candidates:
            sorted_cands = sorted(initial_candidates,
                key=lambda x: {'high': 0, 'medium': 1, 'low': 2}.get(x.get('relevance', 'medium'), 1))
            for cand in sorted_cands:
                if not cand.get('url') or cand['url'] in state['visited_urls']:
                    continue
                results = await explore_branch(
                    page, cand['url'], depth=1,
                    state=state, intent=intent,
                    filter_criteria=filter_criteria,
                    date_enabled=date_enabled,
                    date_value=date_filter
                )
                state['all_results'].extend(results)

        # Step 3: 汇总
        log("\n{}".format("="*60))
        log("📊 探索汇总:")
        log("   已探索URL数: {}".format(len(state['visited_urls'])))
        log("   已搜索次数: {}".format(len(state['search_history'])))
        log("   找到结果总数: {}".format(len(state['all_results'])))
        log("{}".format("="*60))

        # Step 4: 多重过滤
        if state['all_results']:
            filtered = apply_filters(state['all_results'], filter_criteria, date_enabled, date_filter)
            log("   多重过滤后: {} 条".format(len(filtered)))
            if filtered and download_enabled:
                log("📋 开始下载 {} 个文件...".format(len(filtered)))
                downloaded = await final_download(page, filtered,
                    cortana_plan.get('task', ''), custom_save_dir=save_dir)
                log("🎉 任务完成: 共下载 {} 个文件".format(downloaded))
            elif filtered:
                log("📋 任务为查找类，不执行下载，共找到 {} 条相关结果".format(len(filtered)))
            else:
                log("❌ 多重过滤后无匹配结果")
        else:
            log("❌ 未找到任何匹配结果")

        await browser.close()


async def cortana_perception_flow(cortana_plan):
    """
    Cortana 自感知页面结构的探索入口
    
    接收基础URL，让 Cortana 分析页面结构后决定下一步操作
    
    cortana_plan 格式:
    {
        "task": "任务描述",
        "base_url": "起始URL（如CDE首页）",
        "search_var": "搜索关键词（可选）",
        "filter_criteria": ["过滤条件"],
        "save_dir": "保存目录"
    }
    
    工作流程：
    1. 打开 base_url
    2. 感知页面结构（导航菜单、搜索框、分类链接）
    3. 输出感知结果供 Cortana 分析
    4. 返回感知结果和当前页面状态
    """
    task = cortana_plan.get('task', '')
    base_url = cortana_plan.get('base_url')
    search_var = cortana_plan.get('search_var')
    filter_criteria = cortana_plan.get('filter_criteria', [])
    save_dir = cortana_plan.get('save_dir')
    
    if not base_url:
        log("❌ cortana_perception_flow 需要 base_url 参数")
        return
    
    log(f"🎯 Cortana 自感知探索: {task}")
    log(f"📌 起始URL: {base_url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        page = await browser.new_page()
        await page.add_init_script('''() => {
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
        }''')
        
        # 打开起始页面
        await page.goto(base_url, wait_until='domcontentloaded')
        await asyncio.sleep(3)
        
        # 感知页面结构
        page_structure = await page.evaluate(r'''() => {
            const result = {
                'title': document.title,
                'url': window.location.href,
                'nav_links': [],
                'search_inputs': [],
                'main_links': [],
                'content_summary': ''
            };
            
            // 收集导航链接
            const navSelectors = ['nav a', '.nav a', '.menu a', '.sidebar a', 'header a'];
            for (const sel of navSelectors) {
                const links = document.querySelectorAll(sel);
                links.forEach(link => {
                    if (link.href && link.innerText.trim()) {
                        result.nav_links.push({
                            'text': link.innerText.trim().substring(0, 50),
                            'href': link.href
                        });
                    }
                });
            }
            
            // 收集搜索输入框
            const inputs = document.querySelectorAll('input[type="text"], input[placeholder*="搜索"], input[placeholder*="keyword"]');
            inputs.forEach(inp => {
                if (inp.offsetWidth > 0) {
                    result.search_inputs.push({
                        'placeholder': inp.placeholder || inp.name || inp.id || 'text input',
                        'selector': inp.id ? `#${inp.id}` : inp.name ? `[name="${inp.name}"]` : inp.placeholder ? `[placeholder="${inp.placeholder}"]` : 'input'
                    });
                }
            });
            
            // 收集主要内容链接（在前1000字符内）
            const bodyText = document.body.innerText.substring(0, 1000);
            const links = document.querySelectorAll('a[href]');
            links.forEach(link => {
                if (link.href && link.hostname === window.location.hostname && link.innerText.trim()) {
                    result.main_links.push({
                        'text': link.innerText.trim().substring(0, 50),
                        'href': link.href
                    });
                }
            });
            
            result.content_summary = document.body.innerText.substring(0, 500);
            
            return result;
        }''')
        
        # 输出感知结果
        log(f"\n{'='*60}")
        log(f"📄 页面结构感知报告")
        log(f"{'='*60}")
        log(f"标题: {page_structure.get('title', 'N/A')}")
        log(f"URL: {page_structure.get('url', 'N/A')}")
        log(f"\n🔍 搜索框 ({len(page_structure.get('search_inputs', []))}个):")
        for inp in page_structure.get('search_inputs', [])[:5]:
            log(f"   - {inp['selector']} (placeholder: {inp['placeholder']})")
        log(f"\n🧭 导航链接 ({len(page_structure.get('nav_links', []))}个):")
        for link in page_structure.get('nav_links', [])[:10]:
            log(f"   - [{link['text']}] -> {link['href']}")
        log(f"\n📄 主要内容链接 ({len(page_structure.get('main_links', []))}个):")
        for link in page_structure.get('main_links', [])[:10]:
            log(f"   - [{link['text']}] -> {link['href']}")
        log(f"\n📝 内容摘要:")
        log(f"   {page_structure.get('content_summary', 'N/A').replace(chr(10), ' ').substring(0, 200)}...")
        log(f"{'='*60}")
        
        log(f"\n💡 Cortana 分析建议:")
        log(f"   1. 根据感知结果，决定下一步操作")
        log(f"   2. 可使用 search_var='{search_var}' 在搜索框中搜索")
        log(f"   3. 可使用 filter_criteria={filter_criteria} 过滤结果")
        log(f"   4. 可继续探索 nav_links 或 main_links 中的链接")
        
        # 返回感知结果供 Cortana 决策
        return {
            'success': True,
            'page': page,
            'structure': page_structure,
            'browser': browser
        }


if __name__ == "__main__":
    import json
    
    cortana_plan_arg = None
    auto_flow_arg = None
    perception_arg = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--cortana-plan' and i + 1 < len(args):
            cortana_plan_arg = args[i + 1]
            i += 2
        elif arg == '--auto-flow' and i + 1 < len(args):
            auto_flow_arg = args[i + 1]
            i += 2
        elif arg == '--perception' and i + 1 < len(args):
            perception_arg = args[i + 1]
            i += 2
        else:
            i += 1

    if cortana_plan_arg:
        # 有经验分支
        try:
            plan = json.loads(cortana_plan_arg)
            asyncio.run(cortana_execute_flow(plan))
        except json.JSONDecodeError:
            print("❌ Cortana计划 JSON 格式错误")
    elif auto_flow_arg:
        # 无经验分支：多策略自动探索
        try:
            plan = json.loads(auto_flow_arg)
            asyncio.run(cortana_auto_flow(plan))
        except json.JSONDecodeError:
            print("❌ 多策略计划 JSON 格式错误")
    elif perception_arg:
        # 无经验分支：感知式探索（交互式）
        try:
            plan = json.loads(perception_arg)
            asyncio.run(cortana_perception_flow(plan))
        except json.JSONDecodeError:
            print("❌ 自感知计划 JSON 格式错误")
    else:
        print("用法:")
        print("  python web_access.py --cortana-plan '<JSON执行计划>'    # 有经验分支")
        print("  python web_access.py --auto-flow '<JSON多策略计划>'     # 无经验分支")
        print("  python web_access.py --perception '<JSON感知计划>'      # 无经验分支（感知式）")
        print("")
        print("示例（有经验-url已知）:")
        print("  --cortana-plan '{\"task\":\"下载沟通交流指导原则\",\"search_url\":\"https://www.cde.org.cn/zdyz/fullsearchpage\",\"search_var\":\"沟通交流\"}'")
        print("")
        print("示例（无经验-多策略找全）:")
        print("  --auto-flow '{\"task\":\"下载某类指导原则\",\"strategies\":[{\"name\":\"策略1\",\"url\":\"https://...\",\"sv\":\"词1\",\"filter_criteria\":[\"词1\"]}],\"save_dir\":\"~/...\"}'")
    print("\n✅ 完成")
