#!/usr/bin/env python3
"""
通用网页访问工具(全要素泛化版)
版本: 3.0.3 (2026-03-26)
核心逻辑:语义级文件名智能判定 + 主体词/限定词语义分级 + 通用文本内容提取（v3.0.0 全扫描+关键词匹配方案）
核心逻辑：语义级文件名智能判定 + 主体词/限定词语义分级 + 通用文本内容提取（v2.9.0 AI协同决策）
更新:翻译变体由AI助手直接提供(不在脚本内调用LLM),translatable:true时生效
"""

import asyncio, sys, re, os, random, time, subprocess, yaml
from pathlib import Path
from playwright.async_api import async_playwright

# ==================== 配置 ====================
CONFIG = { 'headless': True, 'timeout': 60000 }
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
# 核心升级:从"关键词堆砌"升级为"主谓理解"
# 主体词(如"指导原则")决定搜索范围,限定词(如"沟通交流")负责结果过滤

PRIMARY_KEYWORDS = ['指导原则', '法规', '征求意见', '通告', '指导原则', '公告']
QUALIFIER_KEYWORDS = ['沟通交流', '化药', '生物制品', '中药', '仿制药', '创新药', '通用', '通用技术']

def extract_task_intent(task_keyword):
    """语义分级提取:区分主体词与限定词"""
    # 1. 提取日期
    date_match = re.search(r'(\d{1,2})月(\d{1,2})', task_keyword)
    target_date = f"{time.strftime('%Y')}-{date_match.group(1).zfill(2)}-{date_match.group(2).zfill(2)}" if date_match else None
    raw_date_str = re.sub(r'[^0-9月日]', '', task_keyword) if date_match else ''

    # 2. 语义分级:区分主体词 vs 限定词
    primary_kws = [k for k in PRIMARY_KEYWORDS if k in task_keyword]
    qualifier_kws = [k for k in QUALIFIER_KEYWORDS if k in task_keyword]

    # 3. 如果没有主体词,检查是否全是限定词(如"沟通交流"单独出现)
    if not primary_kws:
        primary_kws = [task_keyword]  # 回退:整句作为主体
        qualifier_kws = []

    # 4. 决定主搜索词(用于 override 匹配和入口选择)
    primary = primary_kws[0] if len(primary_kws) == 1 else (primary_kws[0] if primary_kws else task_keyword)

    # 5. 构建查询:主体词 + 日期(限定词不参与入口搜索,用于结果过滤)
    search_query_parts = [primary]
    if qualifier_kws:
        search_query_parts.extend(qualifier_kws)
    if date_match:
        search_query_parts.append(raw_date_str)

    return {
        'date': target_date,
        'query': " ".join(search_query_parts),
        'original': task_keyword,
        'primary': primary,            # 主体词:用于 override 匹配
        'qualifiers': qualifier_kws,   # 限定词列表:用于结果过滤
        'date_only': raw_date_str,
        'has_qualifier_only': bool(qualifier_kws) and not primary_kws  # 只有限定词,无主体
    }

def extract_var_from_match(pattern, keyword):
    """从 pattern 和 keyword 中提取变量(变量部分)"""
    try:
        var_match = re.search(pattern, keyword)
        if var_match and var_match.lastindex is not None:
            return var_match.group(1)
        # 如果 pattern 包含 XX 占位符,替换为 (.*) 再匹配
        if 'XX' in pattern:
            var_pattern = pattern.replace('XX', '(.*)')
            var_match = re.search(var_pattern, keyword)
            if var_match and var_match.lastindex is not None:
                return var_match.group(1)
    except Exception:
        pass
    return None

# v2.7.5: 翻译变体由 AI 助手直接提供(不在脚本内调用 LLM)
# translatable=True 时,由 AI 根据上下文判断并给出翻译候选,
# 脚本只输出 [TRANSLATION_REQUESTED] 标记供 AI 识别并响应。
TRANSLATION_REQUEST_MARKER = "[TRANSLATION_REQUESTED]"

def request_translation(cn_query):
    """
    v2.7.5: 输出翻译请求标记,通知 AI 助手提供翻译变体。
    AI 助手看到此标记后,直接在会话中返回翻译结果。
    """
    log(f"    {TRANSLATION_REQUEST_MARKER} 中文关键词需要英文翻译: '{cn_query}'")
    log(f"    💡 请在会话中直接回复英文翻译候选词(多个,用逗号分隔)")
    return None  # 翻译由 AI 助手直接提供,脚本不继续执行翻译逻辑

def generate_truncated_variants(keyword):
    """生成关键词截短变体,从长到短逐步简化,用于结果少时降级搜索"""
    if not keyword or len(keyword) <= 1:
        return [keyword] if keyword else []
    variants = []
    # 原始词
    variants.append(keyword)
    # 去掉常见结尾修饰词(按优先级从低到高排列,先去掉的放后面)
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
    # 逐步缩短:每次去掉尾部1个字符(直到只剩2字)
    for i in range(len(keyword) - 1, 1, -1):
        v = keyword[:i]
        if v not in variants:
            variants.append(v)
    # 去重,保持顺序
    seen = set(); unique = []
    for v in variants:
        if v not in seen: seen.add(v); unique.append(v)
    return unique

def match_override(keyword, primary=None):
    """升级版 override 匹配:支持变量提取 + 方法明确性"""
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
# ================================================================
async def get_links_by_text_content_v2(page, search_keyword=None):
    """
    v3.0.0: 全扫描+关键词匹配 - 最通用方案
    
    原理:遍历页面所有链接,获取每个链接周围一定范围的文本,
    检查是否包含关键词,有则提取。
    
    适用场景:
    - 表格结构(关键词在TD-A,链接在TD-B)
    - 列表结构(关键词在LI内任何位置)
    - 块级结构(关键词和链接在同一div)
    - 瀑布流/网格(关键词在块内任意位置)
    - 单链接块(关键词紧邻链接)
    - 任何DOM结构
    
    优势:不依赖DOM层级关系,不依赖结构假设,只关心"链接"和"关键词是否在同区域"。
    """
    return await page.evaluate(r'''
        (searchKeyword) => {
        const keyword = searchKeyword || '';
        const kwLower = keyword.toLowerCase();
        
        // =============================================
        // 步骤1: 收集所有链接及其上下文
        // =============================================
        const allLinks = Array.from(document.querySelectorAll('a[href]'));
        
        if (allLinks.length === 0) {
            return [];
        }
        
        const results = [];
        const seenHrefs = new Set();
        
        for (const link of allLinks) {
            const href = link.href;
            
            // 过滤无效链接
            if (!href || !href.startsWith('http') || href.includes('javascript')) continue;
            if (seenHrefs.has(href)) continue;
            
            const linkText = (link.innerText || '').trim();
            if (linkText.length < 2) continue;
            
            // =============================================
            // 步骤2: 获取链接的上下文文本
            // 向上遍历最多8层,收集周围所有文本
            // =============================================
            let context = '';
            let container = link.parentElement;
            for (let depth = 0; depth < 8; depth++) {
                if (!container || container === document.body) break;
                context += ' ' + (container.innerText || '');
                container = container.parentElement;
            }
            
            const fullText = context.replace(/\s+/g, ' ').trim();
            
            // 提取日期(从链接文本或周围文本)
            let date = null;
            const textForDate = linkText + ' ' + fullText;
            const dateM = textForDate.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
            if (dateM) {
                date = dateM[1] + '.' + dateM[2].padStart(2,'0') + '.' + dateM[3].padStart(2,'0');
            }
            
            // =============================================
            // 步骤3: 关键词过滤
            // - 有关键词时:链接周围文本包含关键词
            // - 无关键词时:提取所有链接
            // =============================================
            if (kwLower && !fullText.toLowerCase().includes(kwLower) && !linkText.toLowerCase().includes(kwLower)) {
                continue;
            }
            
            seenHrefs.add(href);
            
            results.push({
                href: href,
                text: linkText,
                full_row: fullText,
                date: date
            });
        }
        
        // =============================================
        // 步骤4: 内容质量过滤
        // =============================================
        // 噪音链接:导航/页脚/版权等非内容链接
        const noiseIndicators = ['copyright', '版权所有', '登录', '注册', '更多>', '网站地图', '联系我们', '京公网安备', '首页', '指导原则专栏', '指导原则数据库', '发布通告', '征求意见', 'ICH指导原则', '国外参考', '机构职能', 'CDE邮箱'];
        
        // 内容词:确认是有效内容链接的标志
        const contentIndicators = ['指导原则', '办法', '规程', '通知', '公告', '意见稿', '规范', '准则', '要求', '技术', '指引', '原则', '关于', '征求意见', '管理程序', '研发', '注册', '申报', '药学', '临床', '试验', '评价', '复方', '创新药'];
        
        const filtered = results.filter(r => {
            const row = (r.full_row || '') + (r.text || '');
            const rowLower = row.toLowerCase();
            
            // 规则1: 强噪音词直接过滤(即使有内容词)
            const strongNoise = ['网站地图', '联系我们', '京公网安备', '京ICP备', 'CDE邮箱', '机构职能', '首页'];
            if (strongNoise.some(n => row.includes(n))) {
                return false;
            }
            
            // 规则2: 有噪音词但没有任何内容词,过滤
            if (noiseIndicators.some(n => row.includes(n)) && !contentIndicators.some(c => row.includes(c))) {
                return false;
            }
            
            // 规则3: 内容词必须达到一定长度(排除纯标题链接)
            if (contentIndicators.some(c => row.includes(c)) && row.length < 10) {
                return false;
            }
            
            // 规则4: 文本太短且无内容词,过滤
            if (!contentIndicators.some(c => row.includes(c)) && row.length < 20) {
                return false;
            }
            
            return true;
        });
        
        return filtered;
    }''', search_keyword)

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

async def explore_with_pagination(page, intent, exploration_points, search_var=None, translatable=False):
    """search_var: 传入提取的变量,优先作为搜索词使用;translatable: 是否启用翻译变体(国外网站)"""
    all_results = []
    seen = set()
    for name, url in exploration_points.items():
        log(f"🚀 探索: {name}")
        try:
            await page.goto(url, wait_until='domcontentloaded')
            # 等待搜索表单动态加载(最多等15秒)
            for _wait in range(15):
                try:
                    inputs_check = await page.evaluate(r'''() => {
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
                log(f"    ⚠️ 等待表单超时,尝试继续...")
            # 策略 1:正常搜(search_var 优先,如"沟通交流")
            filled = await smart_interact(page, intent, search_var=search_var)

            # =============================================
            # 稳定性检测：等待内容加载完成
            # 原理：连续2次检测到相同数量的内容项，认为加载完成
            # =============================================
            log(f"    ⏳ 等待内容加载稳定...")
            prev_count = 0
            stable_count = 0
            for _wait in range(15):  # 最多等15秒
                try:
                    count = await page.evaluate('document.querySelectorAll("a").length')
                    if count > 10 and count == prev_count:
                        stable_count += 1
                        if stable_count >= 2:  # 连续2次稳定
                            log(f"    ✅ 内容已稳定加载（{_wait}秒），检测到 {count} 个链接")
                            break
                    else:
                        stable_count = 0
                    prev_count = count
                except Exception as e:
                    log(f"    ⚠️ 稳定性检测异常: {e}")
                await asyncio.sleep(1)
            else:
                log(f"    ⚠️ 等待超时（15秒），继续执行...")

            # 首次扫描(基于搜索结果)
            page_links = await get_links_by_text_content_v2(page, search_var)
            # 调试:打印页面中所有链接文本
            try:
                all_text = await page.evaluate(r'''() => {
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
            # 调试:打印前3条的标题
            for debug_l in page_links[:3]:
                log(f"       - {debug_l['text'][:50]} | date={debug_l.get('date')}")
            for l in page_links:
                if l['href'] not in seen: all_results.append(l); seen.add(l['href'])

            # 如果结果少,降级重试(翻译变体 + 截短策略)
            if len(all_results) < 5:
                # v2.7.5: 翻译变体由 AI 助手直接提供(脚本只输出标记)
                if translatable and search_var:
                    request_translation(search_var)
                    log(f"    💡 翻译变体及后续搜索由 AI 助手接管")
                elif search_var:
                    # 先尝试完整关键词
                    await page.goto(url); await asyncio.sleep(5)
                    await smart_interact(page, intent, search_var=search_var)
                    await asyncio.sleep(3)
                    page_links = await get_links_by_text_content_v2(page, search_var)
                    log(f"    📋 关键词'{search_var}'扫描: 找到 {len(page_links)} 条")
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                    # 如果仍少,启用截短策略
                    if len(all_results) < 5:
                        variants = generate_truncated_variants(search_var)
                        log(f"    💡 结果仍少({len(all_results)}条),启动截短策略: {variants}")
                        for var in variants[1:]:  # 跳过第一个(就是完整关键词,已试过)
                            if var == search_var:
                                continue
                            log(f"    🔄 截短重试: '{var}'")
                            await page.goto(url); await asyncio.sleep(5)
                            await smart_interact(page, intent, search_var=var)
                            await asyncio.sleep(3)
                            page_links = await get_links_by_text_content_v2(page, search_var)
                            log(f"    📋 截短'{var}'扫描: 找到 {len(page_links)} 条")
                            for l in page_links:
                                if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                            if len(all_results) >= 5:
                                log(f"    ✅ 截短成功,获得足够结果")
                                break
                elif intent.get('date'):
                    log(f"    💡 结果较少({len(all_results)}条),尝试仅用日期重搜...")
                    await page.goto(url); await asyncio.sleep(5)
                    await smart_interact(page, intent, try_date_only=True)
                    await asyncio.sleep(3)
                    page_links = await get_links_by_text_content_v2(page, search_var)
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])

            # 翻页
            for p_idx in range(2, 6):
                next_btn = await page.query_selector('text="下一页"') or await page.query_selector('a:has-text(">")')
                if next_btn and p_idx < 6:
                    await next_btn.click(); await asyncio.sleep(5)
                    page_links = await get_links_by_text_content_v2(page, search_var)
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                else: break
        except Exception as e:
            log(f"⚠️ 探索异常: {e}")
    return all_results

# v2.7.5: 支持 per-URL 搜索词的探索函数
async def explore_with_pagination_v2(page, intent, exploration_points, translatable=False):
    """
    exploration_points: dict{name: {"url": str, "sv": str|None}}
      sv=None  → 不填搜索框,由 smart_interact 的 date+primary 逻辑决定填什么
      sv=str   → 用指定字符串填搜索框
    """
    all_results = []
    seen = set()
    for name, pt in exploration_points.items():
        url = pt["url"]
        sv = pt.get("sv")  # None means use date+primary logic in smart_interact
        log(f"🚀 探索: {name} (sv={repr(sv)})")
        try:
            await page.goto(url, wait_until='domcontentloaded')
            # 等待动态内容加载
            for _wait in range(15):
                try:
                    cnt = await page.evaluate(r'''() => document.querySelectorAll('.news_item, li, tr').length''')
                    if cnt > 0:
                        log(f"    ⏳ 等待{_wait+1}秒后检测到内容节点")
                        break
                except: pass
                await asyncio.sleep(1)

            # 填充搜索(sv=None 时 smart_interact 会用 date+primary 逻辑)
            await smart_interact(page, intent, search_var=sv)
            
            # 稳定性检测：等待搜索结果加载完成
            log(f"    ⏳ 等待搜索结果稳定...")
            prev_count = 0
            prev_text_len = 0
            stable_count = 0
            for _wait in range(20):
                try:
                    count = await page.evaluate('document.querySelectorAll("a").length')
                    text_len = await page.evaluate('document.body.innerText.length')
                    if count > 10 and text_len > 500 and count == prev_count and text_len == prev_text_len:
                        stable_count += 1
                        if stable_count >= 2:
                            log(f"    ✅ 搜索结果已稳定（{_wait}秒），{count}个链接，{text_len}字符")
                            break
                    else:
                        stable_count = 0
                    prev_count = count
                    prev_text_len = text_len
                except Exception as e:
                    log(f"    ⚠️ 搜索稳定性检测异常: {e}")
                await asyncio.sleep(1)
            else:
                log(f"    ⚠️ 搜索结果等待超时（20秒），继续执行...")

            page_links = await get_links_by_text_content_v2(page, sv)
            log(f"    📋 首次扫描: 找到 {len(page_links)} 条")
            # 调试:打印前5条的日期
            for dl in page_links[:5]:
                log(f"       [{dl.get('date','无日期')}] {dl['text'][:60]}")
            for l in page_links:
                if l['href'] not in seen:
                    all_results.append(l); seen.add(l['href'])

            # 结果少时:降级策略
            if len(all_results) < 5:
                effective_sv = sv if sv else (intent.get('primary') or intent.get('query', ''))
                if translatable and effective_sv:
                    request_translation(effective_sv)
                    log(f"    💡 翻译变体及后续搜索由 AI 助手接管")
                elif effective_sv:
                    # v2.9.0: 首次搜索返回0时，不盲目截短，输出AI报告等我决策
                    if len(all_results) == 0:
                        log("=" * 60)
                        log("🤖 AI_REPORT: 首次搜索(sv={!r})结果为0，需AI决策".format(sv))
                        log(f"   intent.query: {intent.get('query', '')!r}")
                        log(f"   intent.primary: {intent.get('primary', '')!r}")
                        log(f"   建议: 重新调用时使用 --extra-filter <二级关键词> 进行二次过滤，")
                        log(f"         或使用 --search-var <搜索词> 指定不同的搜索词")
                        log("=" * 60)
                    else:
                        # 结果>0但<5时，尝试截短（保留原逻辑）
                        variants = generate_truncated_variants(effective_sv)
                        log(f"    💡 结果仍少({len(all_results)}条),启动截短策略: {variants}")
                        for var in variants[1:]:
                            if len(all_results) >= 5:
                                break
                            log(f"    🔄 截短重试: '{var}'")
                            await page.goto(url); await asyncio.sleep(5)
                            await smart_interact(page, intent, search_var=var)
                            # 稳定性检测
                            prev_count = 0
                            prev_text_len = 0
                            stable_count = 0
                            for _wait2 in range(15):
                                try:
                                    count2 = await page.evaluate('document.querySelectorAll("a").length')
                                    text_len2 = await page.evaluate('document.body.innerText.length')
                                    if count2 > 10 and text_len2 > 500 and count2 == prev_count and text_len2 == prev_text_len:
                                        stable_count += 1
                                        if stable_count >= 2:
                                            log(f"    ✅ 截短结果已稳定（{_wait2}秒）")
                                            break
                                    else:
                                        stable_count = 0
                                    prev_count = count2
                                    prev_text_len = text_len2
                                except:
                                    pass
                                await asyncio.sleep(1)

                            page_links = await get_links_by_text_content_v2(page, var)
                            log(f"    📋 '{var}'扫描: {len(page_links)} 条")
                            for l in page_links:
                                if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                    if len(all_results) >= 5:
                        log(f"    ✅ 截短成功")
                elif intent.get('date'):
                    # 无关键词时,尝试仅用日期
                    await page.goto(url); await asyncio.sleep(5)
                    await smart_interact(page, intent, try_date_only=True)
                    await asyncio.sleep(3)
                    page_links = await get_links_by_text_content_v2(page, None)
                    for l in page_links:
                        if l['href'] not in seen: all_results.append(l); seen.add(l['href'])

            # 翻页
            for p_idx in range(2, 6):
                next_btn = await page.query_selector('text="下一页"') or await page.query_selector('a:has-text(">")')
                if next_btn:
                    cls = await next_btn.get_attribute('class') or ''
                    txt = (await next_btn.inner_text()).strip()
                    if 'layui-disabled' not in cls and txt:
                        await next_btn.click(); await asyncio.sleep(5)
                        page_links = await get_links_by_text_content_v2(page, None)
                        for l in page_links:
                            if l['href'] not in seen: all_results.append(l); seen.add(l['href'])
                    else:
                        break
                else:
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

async def main_flow(keyword, extra_filter=None, save_dir=None):
    intent = extract_task_intent(keyword)
    log(f"🎯 任务: {intent['query']} | 主体: {intent['primary']} | 限定: {intent.get('qualifiers', [])}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        page = await browser.new_page()
        # v2.8.1: 注入反检测脚本,防止CDE等网站因 navigator.webdriver 检测而拒绝渲染
        await page.add_init_script('''() => {
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
        }''')

        # 升级:优先用主体词匹配 override
        entry = match_override(keyword, primary=intent.get('primary'))

        if entry:
            log(f"🧠 经验命中: {entry.get('note', '')} (匹配依据: {entry.get('_matched_on', '')})")

            # 根据 method 决定执行方式,不再双轨并行
            method = entry.get('method', 'both')
            list_urls = entry.get('list_urls', [])
            search_url = entry.get('search_url')
            search_var = entry.get('_var') if entry else None
            translatable = entry.get('translatable', False)

            # v2.7.5: pts 改为 dict{name: {"url": str, "sv": str|None}}
            # sv=None 表示不填搜索框(由 smart_interact 的 date+primary 逻辑决定填什么)
            # sv=str 表示用该字符串填搜索框
            pts = {}
            if list_urls:
                for idx, url in enumerate(list_urls):
                    # 列表页:用 intent['primary'] 填标题(sv=None 时 smart_interact 会走 date+primary 分支)
                    pts[f"列表{idx+1}"] = {"url": url, "sv": None}
            if search_url:
                pts["搜索页"] = {"url": search_url, "sv": search_var}
        else:
            # 无经验时:默认双轨并行
            method = 'both'
            primary = intent.get('primary', keyword)
            target_url = CDE_ENTRY_PAGES.get(primary)
            default_pts = {"默认入口": target_url} if target_url else CDE_ENTRY_PAGES
            pts = {k: {"url": v, "sv": None} for k, v in default_pts.items()}
            search_var = None
            translatable = False

        log(f"📌 执行方式: {method} {'(仅使用经验指定方式,不再双轨并行)' if entry and method != 'both' else '(默认双轨并行)'}")
        log(f"    🔍 search_var = {repr(search_var)}, translatable = {translatable}")

        # v2.9.0: 支持 extra_filter（复合关键词二次过滤）
        intent['extra_filter'] = extra_filter

        raw_list = await explore_with_pagination_v2(page, intent, pts, translatable=translatable)

        # v2.9.0: AI 决策报告点
        # 如果原始结果为0，输出结构化报告供 AI 分析决策
        if not raw_list:
            log("=" * 60)
            log("🤖 AI_REPORT: 首次搜索结果为 0，AI 决策点")
            log(f"   关键词: search_var={repr(search_var)}")
            log(f"   intent.query: {intent.get('query', '')!r}")
            log(f"   intent.primary: {intent.get('primary', '')!r}")
            log(f"   intent.qualifiers: {intent.get('qualifiers', [])}")
            log(f"   intent.date: {intent.get('date')}")
            log(f"   可用截短变体: {generate_truncated_variants(search_var) if search_var else []}")
            log(f"   可用 CDE 入口: {list(CDE_ENTRY_PAGES.keys())}")
            log(f"   建议: 尝试复合关键词拆分搜索+二次过滤，")
            log(f"         或使用 --extra-filter <二级关键词> 进行二次过滤")
            log("=" * 60)

        final_list = fuzzy_semantic_filter(raw_list, intent)

        # 如果有限定词,进一步过滤结果
        qualifiers = intent.get('qualifiers', [])
        if qualifiers and final_list:
            before = len(final_list)
            final_list = [r for r in final_list if any(
                q in (r['text'] + r['full_row']) for q in qualifiers
            )]
            log(f"🔍 限定词过滤 '{qualifiers}':{before} → {len(final_list)} 条")

        if not final_list: log("❌ 未发现匹配项。")
        else:
            log(f"📋 发现 {len(final_list)} 条通告,提取全量附件...")
            downloaded = await final_download(page, final_list, keyword, custom_save_dir=save_dir)
            log(f"🎉 任务完成:共下载 {downloaded} 个关联文件。")
        await browser.close()

if __name__ == "__main__":
    # v3.0.2: 支持 --save-dir 参数
    keyword_arg = None
    extra_filter_arg = None
    save_dir_arg = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--extra-filter' and i + 1 < len(args) and not args[i + 1].startswith('--'):
            extra_filter_arg = args[i + 1]
            i += 2
        elif arg == '--save-dir' and i + 1 < len(args) and not args[i + 1].startswith('--'):
            save_dir_arg = args[i + 1]
            i += 2
        elif not arg.startswith('--'):
            keyword_arg = arg
            i += 1
        else:
            i += 1
    if keyword_arg:
        asyncio.run(main_flow(keyword_arg, extra_filter=extra_filter_arg, save_dir=save_dir_arg))
    else:
        print("用法: python web_access.py <关键词> [--extra-filter <二级过滤关键词>] [--save-dir <保存目录>]")
    print("\n✅ 完成")
