#!/usr/bin/env python3
"""
智能导航工具 (smart_navigate) - 增强版
====================================
AI驱动的智能网页导航 - 自动选择最优策略找到目标内容

🆕 增强功能：
- 详细的执行过程日志
- 每步决策记录
- 链接分析详情
- 策略切换原因

使用方式：
    python3 scripts/smart_navigate.py "要找的内容" --site cde --verbose
"""

import asyncio
import sys
import os
import re
import json
import random
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ============ 增强日志系统 ============
class ExecutionLogger:
    """执行过程日志记录器"""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.steps = []
        self.current_step = 0
    
    def log(self, message: str, level: str = "INFO"):
        """记录日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "STEP": "👉",
            "ACTION": "  🔹",
            "DECISION": "  💡",
            "RESULT": "  ✅",
            "ERROR": "  ❌",
            "WARN": "  ⚠️",
            "INFO": "  ℹ️"
        }.get(level, "  ")
        
        log_line = f"[{timestamp}] {prefix} {message}"
        print(log_line)
        
        self.steps.append({
            "step": self.current_step,
            "level": level,
            "message": message,
            "timestamp": timestamp
        })
    
    def step(self, message: str):
        """记录步骤"""
        self.current_step += 1
        self.log(f"【步骤 {self.current_step}】{message}", "STEP")
    
    def action(self, message: str):
        """记录动作"""
        self.log(message, "ACTION")
    
    def decision(self, message: str):
        """记录决策"""
        self.log(message, "DECISION")
    
    def result(self, message: str):
        """记录结果"""
        self.log(message, "RESULT")
    
    def error(self, message: str):
        """记录错误"""
        self.log(message, "ERROR")
    
    def warn(self, message: str):
        """记录警告"""
        self.log(message, "WARN")
    
    def summary(self):
        """打印执行摘要"""
        print(f"\n{'='*60}")
        print(f"📊 执行摘要 - 共 {len(self.steps)} 个步骤")
        print(f"{'='*60}")
        for s in self.steps[-10:]:  # 显示最后10步
            print(f"  [{s['timestamp']}] {s['message'][:80]}")

logger = ExecutionLogger(verbose=True)

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ============ 配置 ============
VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--disable-setuid-sandbox",
    "--disable-background-networking",
    "--disable-extensions",
    "--disable-sync",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--ignore-certificate-errors",
    "--disable-http2",
    "--disable-features=TranslateUI",
    "--disable-ipc-flooding-protection",
    "--disable-renderer-backgrounding",
    "--enable-features=NetworkService,NetworkServiceInProcess",
    "--force-color-profile=srgb",
    "--metrics-recording-only",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-default-apps",
    "--disable-hang-monitor",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-speech-api",
    "--disable-web-security",
    "--enable-async-dns",
    "--enable-features=SameSiteByDefaultCookies",
    "--exclude-switches",
    "--in-process-gpu",
    "--no-default-browser-check",
    "--no-pings",
    "--password-store=basic",
]

CONFIG = {
    'headless': True,
    'timeout': 90000,
}

# ============ 读取导航配置 ============
import yaml

def load_navigation_config():
    """读取网站导航配置文件"""
    config_path = Path(__file__).parent.parent / "references" / "site_navigation.yaml"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warn(f"无法读取配置文件: {e}")
        return {}

def get_site_urls(site: str) -> dict:
    """获取网站的关键URL"""
    config = load_navigation_config()
    return config.get(site, {})

# ============ 辅助函数 ============

def get_random_ua():
    return random.choice(UA_POOL)

def get_viewport():
    return random.choice(VIEWPORT_POOL)

async def create_context(p):
    """创建浏览器上下文"""
    browser = await p.chromium.launch(
        headless=CONFIG['headless'],
        args=BROWSER_ARGS
    )
    
    context = await browser.new_context(
        user_agent=get_random_ua(),
        viewport=get_viewport(),
        ignore_https_errors=True
    )
    
    page = await context.new_page()
    
    # 设置更长的超时
    page.set_default_timeout(CONFIG['timeout'])
    
    return context, browser, page

async def safe_scroll(page):
    """安全滚动页面"""
    try:
        await page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                const scrollHeight = document.body.scrollHeight;
                const viewportHeight = window.innerHeight;
                let pos = 0;
                const step = viewportHeight * 0.5;
                
                while (pos < scrollHeight) {
                    window.scrollBy(0, step);
                    pos += step;
                    await delay(800 + Math.random() * 500);
                }
            }
        """)
    except:
        pass

async def wait_random(min_sec=1, max_sec=3):
    """随机等待"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# ============ AI策略分析 ============

CONTENT_TYPES = {
    'guidance': {
        'keywords': ['指导原则', '技术要求', 'guidance', 'guideline', 'policy', 'regulation', '要求', '规范'],
        'priority': 'search',
    },
    'report': {
        'keywords': ['报告', '审评', '评审', 'report', 'review', 'approval', '结论', '结果'],
        'priority': 'navigate',
    },
    'data': {
        'keywords': ['数据', '临床试验', '临床研究', 'data', 'trial', 'study', '研究'],
        'priority': 'navigate',
    },
    'drug': {
        'keywords': ['药品', '药物', 'drug', 'medicine', '制剂', '注射液', '上市'],
        'priority': 'navigate',
    },
    'news': {
        'keywords': ['新闻', '公告', '通知', 'news', 'announcement', 'update', '发布'],
        'priority': 'search',
    },
    'general': {
        'keywords': [],
        'priority': 'search',
    }
}

def analyze_content_type(query: str) -> dict:
    """AI分析用户需求，判断内容类型"""
    query_lower = query.lower()
    
    matched_type = 'general'
    max_matches = 0
    
    for content_type, config in CONTENT_TYPES.items():
        matches = sum(1 for kw in config['keywords'] if kw in query_lower)
        if matches > max_matches:
            max_matches = matches
            matched_type = content_type
    
    result = {
        'type': matched_type,
        'priority': CONTENT_TYPES[matched_type]['priority'],
        'confidence': min(max_matches * 0.3, 1.0),
        'reasoning': f"检测到关键词匹配数: {max_matches}"
    }
    
    if matched_type == 'general':
        if len(query) < 10:
            result['priority'] = 'search'
            result['reasoning'] = "查询较短，优先搜索"
        else:
            result['priority'] = 'navigate'
            result['reasoning'] = "查询较详细，尝试导航遍历"
    
    return result

def select_site_strategy(site: str, content_type: str) -> dict:
    """根据网站和内容类型选择最优策略"""
    strategies = {
        'cde': {
            'name': 'CDE药品审评中心',
            'search_url': 'https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d',
            'home_url': 'https://www.cde.org.cn',
            'search_selector': 'input#keyword',
            'result_selector': '.list_item a, .news_list a, table a, a[href*="xxgk"]'
        },
        'fda': {
            'name': 'FDA',
            'search_url': 'https://www.fda.gov/drugs/guidance-compliance-regulatory-information',
            'home_url': 'https://www.fda.gov',
            'search_selector': '#search',
            'result_selector': '.dc-card a, .list-left a'
        },
        'nmpa': {
            'name': 'NMPA国家药监局',
            'search_url': 'https://www.nmpa.gov.cn',
            'home_url': 'https://www.nmpa.gov.cn',
            'search_selector': '#keyword',
            'result_selector': '.list_item a'
        }
    }
    
    return strategies.get(site.lower(), strategies['cde'])

async def analyze_page_links(page, target_keyword: str) -> list:
    """分析页面所有链接，筛选与目标相关的链接"""
    links_info = await page.evaluate(f"""
        () => {{
            const links = Array.from(document.querySelectorAll('a[href]'));
            const target = "{target_keyword}".toLowerCase();
            
            return links
                .filter(a => a.href && (a.href.startsWith('http') || a.href.startsWith('/')))
                .map(a => {{
                    const text = (a.innerText || '').trim().substring(0, 100);
                    let href = a.href;
                    // 相对路径转绝对路径
                    if (href.startsWith('/')) {{
                        href = 'https://www.cde.org.cn' + href;
                    }}
                    
                    let score = 0;
                    const combined = (text + ' ' + href).toLowerCase();
                    
                    if (target && combined.includes(target)) {{
                        score += 10;
                    }}
                    
                    if (text && text.length > 5) {{
                        score += 2;
                    }}
                    
                    const ignore_patterns = ['更多', 'more', 'next', 'prev', 'page', '上一页', '下一页', '返回', 'back'];
                    if (ignore_patterns.some(p => text.toLowerCase().includes(p.toLowerCase())) && score < 5) {{
                        score = 0;
                    }}
                    
                    return {{ text, href, score }};
                }})
                .filter(l => l.score > 0)
                .sort((a, b) => b.score - a.score)
                .slice(0, 20);
        }}
    """)
    
    return links_info

async def smart_search(page, site: str, query: str, content_analysis: dict) -> dict:
    """智能搜索 - 尝试网站搜索功能"""
    global logger
    strategy = select_site_strategy(site, content_analysis['type'])
    
    logger.decision(f"策略: 搜索优先 (内容类型: {content_analysis['type']})")
    logger.action(f"目标网站: {strategy['name']}")
    logger.action(f"搜索URL: {strategy['search_url']}")
    
    try:
        logger.action(f"正在访问搜索页面...")
        await page.goto(strategy['search_url'], timeout=30000, wait_until='networkidle')
        await wait_random(2, 4)
        logger.result(f"页面加载完成，当前URL: {page.url}")
        
        # 尝试多种搜索框选择器
        selectors = [
            'input#keyword',
            '#keyword',
            '#search',
            'input[type="text"]',
            'input[name="keyword"]',
            'input[name="q"]',
            'input[name="search"]',
            '.search-input input',
            'input[placeholder*="搜索"]',
            'input[placeholder*="Search"]',
        ]
        
        search_box = None
        found_selector = None
        for sel in selectors:
            try:
                search_box = await page.query_selector(sel)
                if search_box:
                    found_selector = sel
                    break
            except:
                continue
        
        if search_box:
            logger.action(f"找到搜索框，使用选择器: {found_selector}")
            await search_box.click()
            await asyncio.sleep(0.5)
            await search_box.fill(query)
            logger.action(f"输入搜索关键词: {query}")
            await asyncio.sleep(0.3)
            
            try:
                await page.keyboard.press('Enter')
                logger.action("按Enter键提交搜索")
            except:
                pass
            
            await wait_random(3, 5)
            logger.result(f"搜索完成，跳转到: {page.url}")
            
            # 获取搜索结果
            results = await page.query_selector_all('a')
            
            if results:
                logger.result(f"搜索成功，找到 {len(results)} 个链接")
                logger.action("正在提取页面内容...")
                return {
                    'success': True,
                    'method': 'search',
                    'results_count': len(results),
                    'url': page.url,
                    'content': await page.content()
                }
        
        logger.warn("未找到搜索框，尝试导航策略...")
        return {'success': False, 'method': 'search', 'reason': 'search_box_not_found'}
        
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return {'success': False, 'method': 'search', 'error': str(e)}

async def smart_navigate(page, site: str, query: str, content_analysis: dict, max_depth: int = 3) -> dict:
    """智能导航 - 分析页面链接结构，逐级点击找到目标"""
    global logger
    strategy = select_site_strategy(site, content_analysis['type'])
    
    logger.decision(f"策略: 链接遍历 (内容类型: {content_analysis['type']})")
    logger.action(f"目标关键词: {query}")
    logger.action(f"最大导航深度: {max_depth}")
    
    # ============ 优先使用配置文件中的URL ============
    site_config = get_site_urls(site)
    
    # 检查是否有专门的指导原则URL
    if site_config and 'guidance_url' in site_config:
        start_url = site_config['guidance_url']
        logger.action(f"📍 使用配置文件中的指导原则URL: {start_url}")
    else:
        start_url = strategy.get('home_url', strategy['search_url'])
    
    logger.action(f"起始URL: {start_url}")
    
    async def visit_and_search(url: str, depth: int) -> dict:
        if depth > max_depth:
            logger.warn(f"已达到最大深度 {max_depth}，停止导航")
            return {'success': False, 'reason': 'max_depth_reached'}
        
        try:
            indent = "  " * depth
            logger.action(f"{indent}访问页面 (深度 {depth}/{max_depth}): {url[:50]}...")
            await page.goto(url, timeout=30000, wait_until='networkidle')
            logger.result(f"{indent}页面加载完成: {page.url}")
            
            await safe_scroll(page)
            await wait_random(1, 3)
            
            # 分析页面链接
            logger.action(f"{indent}分析页面链接，查找与 '{query}' 相关的内容...")
            links = await analyze_page_links(page, query)
            
            if not links:
                logger.warn(f"{indent}页面无相关链接")
                return {'success': False, 'reason': 'no_links_found'}
            
            logger.result(f"{indent}找到 {len(links)} 个相关链接")
            
            # 显示找到的相关链接（详细）
            if logger.verbose:
                logger.action(f"{indent}相关链接列表:")
                for i, link in enumerate(links[:5]):
                    logger.action(f"{indent}  [{i+1}] {link['text'][:40]}... (相关度:{link['score']})")
            
            # 检查是否有直接匹配的结果
            for i, link in enumerate(links[:5]):
                if query.lower() in link['text'].lower() or query.lower() in link['href'].lower():
                    logger.result(f"{indent}🎯 找到精确匹配链接: {link['text'][:40]}...")
                    logger.action(f"{indent}  URL: {link['href']}")
                    return {
                        'success': True,
                        'method': 'navigate',
                        'depth': depth,
                        'url': link['href'],
                        'title': link['text'],
                        'content': await page.content()
                    }
            
            # 继续点击下一个层级的链接
            logger.action(f"{indent}未找到精确匹配，继续深入查找...")
            for i, link in enumerate(links[:3]):
                logger.action(f"{indent}尝试链接 {i+1}: {link['text'][:30]}...")
                result = await visit_and_search(link['href'], depth + 1)
                if result.get('success'):
                    return result
            
            logger.warn(f"{indent}该分支未找到匹配内容")
            return {'success': False, 'reason': 'no_deeper_match'}
            
        except Exception as e:
            logger.error(f"访问失败: {e}")
            return {'success': False, 'error': str(e)}
    
    return await visit_and_search(start_url, 0)

async def smart_find_content(query: str, site: str = 'cde', target_type: str = 'content') -> dict:
    """主入口：智能查找内容"""
    global logger
    
    print(f"\n{'='*60}")
    print(f"🧠 智能导航 - 增强版")
    print(f"{'='*60}")
    
    # Step 1: AI分析内容类型
    logger.step("AI分析需求")
    content_analysis = analyze_content_type(query)
    logger.action(f"查询内容: {query}")
    logger.action(f"识别类型: {content_analysis['type']}")
    logger.action(f"推荐策略: {content_analysis['priority']}")
    logger.action(f"置信度: {content_analysis['confidence']}")
    logger.action(f"分析理由: {content_analysis['reasoning']}")
    
    async with async_playwright() as p:
        context, browser, page = await create_context(p)
        
        try:
            priority = content_analysis['priority']
            logger.step("开始执行策略")
            
            if priority == 'search':
                logger.decision("选择策略: 搜索优先 → 失败后切换导航")
                result = await smart_search(page, site, query, content_analysis)
                
                if not result.get('success'):
                    logger.warn("搜索策略失败，切换到导航策略...")
                    logger.step("执行备选策略: 链接遍历")
                    result = await smart_navigate(page, site, query, content_analysis)
            else:
                logger.decision("选择策略: 导航优先 → 失败后切换搜索")
                result = await smart_navigate(page, site, query, content_analysis)
                
                if not result.get('success'):
                    logger.warn("导航策略失败，切换到搜索策略...")
                    logger.step("执行备选策略: 搜索")
                    result = await smart_search(page, site, query, content_analysis)
            
            logger.step("执行完成")
            return result
            
        finally:
            await browser.close()
            await context.close()

async def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='🧠 智能网页导航工具')
    parser.add_argument('query', help='要查找的内容关键词')
    parser.add_argument('--site', default='cde', help='目标网站: cde/fda/nmpa')
    parser.add_argument('--target', default='content', help='目标类型: content/pdf/all')
    parser.add_argument('--depth', type=int, default=3, help='最大导航深度')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细执行过程')
    
    args = parser.parse_args()
    
    # 设置日志级别
    global logger
    logger = ExecutionLogger(verbose=args.verbose)
    
    logger.step(f"开始智能查找: {args.query}")
    logger.action(f"目标网站: {args.site}")
    logger.action(f"导航深度: {args.depth}")
    
    # 执行智能查找
    result = await smart_find_content(args.query, args.site)
    
    # 输出结果
    if result.get('success'):
        logger.result(f"找到内容!")
        logger.result(f"  方法: {result.get('method')}")
        logger.result(f"  URL: {result.get('url', 'N/A')}")
        if 'title' in result:
            logger.result(f"  标题: {result.get('title', 'N/A')}")
        
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if args.target == 'pdf':
                logger.action("目标类型为PDF，需要更复杂的处理...")
            else:
                content = result.get('content', '')
                output_path.write_text(content, encoding='utf-8')
                logger.result(f"已保存到: {output_path}")
        else:
            content = result.get('content', '')
            preview = content[:500] if content else '无内容'
            logger.result(f"内容预览: {preview}...")
    else:
        logger.error(f"未找到内容")
        logger.error(f"  原因: {result.get('reason', result.get('error', 'unknown'))}")
    
    # 打印执行摘要
    if args.verbose:
        logger.summary()

if __name__ == '__main__':
    asyncio.run(main())
