#!/usr/bin/env python3
"""
智能内容发现与下载工具 (smart_crawl)
=====================================
通用化设计：访问任意网站，阅读页面，识别内容，按条件筛选，下载验证

核心流程：
1. 访问目标URL
2. 阅读页面，识别关键信息（日期、标题、链接）
3. 筛选匹配条件的内容
4. 点击进入详情页
5. 提取并下载目标文件
6. 验证文件完整性
7. 失败重试

使用方式：
    python3 scripts/smart_crawl.py "https://www.cde.org.cn/zdyz/index" --date "2026-03-09"
    python3 scripts/smart_crawl.py "URL" --date "2026-03-09" --filter "指导原则"
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

# ============ 日志系统 ============
class ExecutionLogger:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.steps = []
        self.current_step = 0
    
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "STEP": "👉", "ACTION": "  🔹", "DECISION": "  💡",
            "RESULT": "  ✅", "ERROR": "  ❌", "WARN": "  ⚠️", "INFO": "  ℹ️"
        }.get(level, "  ")
        print(f"[{timestamp}] {prefix} {message}")
        self.steps.append({"level": level, "message": message, "timestamp": timestamp})
    
    def step(self, message: str):
        self.current_step += 1
        self.log(f"【步骤 {self.current_step}】{message}", "STEP")
    
    def action(self, message: str):
        self.log(message, "ACTION")
    
    def decision(self, message: str):
        self.log(message, "DECISION")
    
    def result(self, message: str):
        self.log(message, "RESULT")
    
    def error(self, message: str):
        self.log(message, "ERROR")
    
    def warn(self, message: str):
        self.log(message, "WARN")

logger = ExecutionLogger(verbose=True)

# ============ 配置 ============
VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

BROWSER_ARGS = [
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled",
    "--disable-gpu", "--disable-setuid-sandbox", "--disable-background-networking",
    "--disable-extensions", "--disable-sync", "--mute-audio", "--no-first-run",
    "--ignore-certificate-errors", "--disable-http2",
]

CONFIG = {
    'headless': True,
    'timeout': 90000,
    'max_retries': 3,
}

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

async def create_browser(p):
    """创建浏览器"""
    browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
    return browser

async def create_context(browser):
    """创建浏览器上下文"""
    context = await browser.new_context(
        user_agent=random.choice(UA_POOL),
        viewport=random.choice(VIEWPORT_POOL),
        ignore_https_errors=True
    )
    return context

async def safe_scroll(page):
    """安全滚动"""
    try:
        await page.evaluate("""
            async () => {
                const delay = ms => new Promise(r => setTimeout(r, ms));
                const scrollHeight = document.body.scrollHeight;
                const viewportHeight = window.innerHeight;
                let pos = 0;
                while (pos < scrollHeight) {
                    window.scrollBy(0, viewportHeight * 0.5);
                    pos += viewportHeight * 0.5;
                    await delay(800);
                }
            }
        """)
    except:
        pass

async def wait_random(min_sec=1, max_sec=3):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# ============ 核心功能 ============

async def extract_page_info(page, query: str = None) -> dict:
    """
    提取页面关键信息：日期、标题、链接
    返回: {items: [{date, title, href, text, date_match}]}
    """
    query_str = query if query else ""
    query_lower = query_str.lower()
    
    page_info = await page.evaluate(f"""
        () => {{
            const items = [];
            const query = "{query_lower}";
            
            // 查找所有链接
            const links = Array.from(document.querySelectorAll('a[href]'));
            
            for (const link of links) {{
                const href = link.href;
                const text = (link.innerText || '').trim();
                const parentText = (link.parentElement?.innerText || '').trim().substring(0, 200);
                
                if (!href || !text || text.length < 5) continue;
                
                // 查找日期
                let date = null;
                const datePatterns = [
                    /(\\d{{4}})年(\\d{{1,2}})月(\\d{{1,2}})日/,
                    /(\\d{{4}})(\\d{{2}})(\\d{{2}})/,
                    /(\\d{{4}})-\\d{{1,2}}-\\d{{1,2}}/,
                ];
                
                for (const pattern of datePatterns) {{
                    const match = (text + parentText).match(pattern);
                    if (match) {{
                        if (match[2] && match[3]) {{
                            date = `${{match[1]}}-${{String(match[2]).padStart(2, '0')}}-${{String(match[3]).padStart(2, '0')}}`;
                        }}
                        break;
                    }}
                }}
                
                // 计算相关性
                let relevance = 0;
                const combined = (text + ' ' + href + ' ' + parentText).toLowerCase();
                if (query && combined.includes(query)) relevance += 10;
                if (date) relevance += 5;
                if (text.length > 10 && text.length < 200) relevance += 2;
                
                // 过滤无关链接
                const ignore = ['更多', 'more', 'next', 'prev', 'page', '返回', 'back', '登录', 'login'];
                if (ignore.some(w => text.toLowerCase().includes(w.toLowerCase())) && relevance < 10) continue;
                
                items.push({{
                    text: text.substring(0, 150),
                    href: href,
                    date: date,
                    date_str: date || 'unknown',
                    relevance: relevance,
                    parent_text: parentText.substring(0, 100)
                }});
            }}
            
            // 按相关性排序，返回前50个
            return items.sort((a, b) => b.relevance - a.relevance).slice(0, 50);
        }}
    """)
    
    return {"items": page_info}

async def filter_by_date(items: list, target_date: str) -> list:
    """
    按日期筛选匹配的内容
    target_date 格式: "2026-03-09" 或 "20260309"
    """
    # 标准化日期
    target_date = target_date.replace("-", "").replace("/", "")
    if len(target_date) == 8:
        target_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
    
    target_str = target_date.replace("-", "")
    
    matched = []
    for item in items:
        if not item.get('date'):
            continue
        
        item_date = item['date'].replace("-", "")
        
        # 完全匹配
        if target_str in item_date:
            item['date_match'] = 'exact'
            matched.append(item)
        # 同一天（年月相同）
        elif item_date[:6] == target_str[:6] and item_date[6:8] == target_str[6:8]:
            item['date_match'] = 'same_day'
            matched.append(item)
        # 同一月
        elif item_date[:6] == target_str[:6]:
            item['date_match'] = 'same_month'
            matched.append(item)
    
    return matched

async def find_downloadable_files(page) -> list:
    """
    查找页面中可下载的文件链接
    """
    files = await page.evaluate("""
        () => {
            const files = [];
            
            // 查找所有链接
            const links = Array.from(document.querySelectorAll('a[href]'));
            
            // 文件类型
            const extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.txt'];
            
            for (const link of links) {
                const href = link.href;
                const text = (link.innerText || '').trim();
                
                if (!href) continue;
                
                const lowerHref = href.toLowerCase();
                const lowerText = text.toLowerCase();
                
                // 检查是否是文件链接
                const isFile = extensions.some(ext => lowerHref.includes(ext) || lowerText.includes(ext));
                
                // 或者检查是否包含"附件"、"下载"等关键词
                const hasDownloadKeyword = lowerText.includes('附件') || 
                                          lowerText.includes('下载') || 
                                          lowerText.includes('pdf') ||
                                          lowerText.includes('word') ||
                                          lowerText.includes('excel');
                
                if (isFile || hasDownloadKeyword) {
                    // 过滤掉分页等
                    if (!lowerHref.includes('page=') && !lowerText.includes('更多')) {
                        files.push({
                            text: text.substring(0, 100),
                            href: href,
                            filename: href.split('/').pop().split('?')[0]
                        });
                    }
                }
            }
            
            return files.slice(0, 20);
        }
    """)
    
    return files

async def download_file(page, file_url: str, output_dir: Path, filename: str = None) -> dict:
    """
    下载文件
    """
    if not filename:
        filename = file_url.split('/')[-1].split('?')[0]
    
    # 清理文件名
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filepath = output_dir / filename
    
    logger.action(f"开始下载: {filename}")
    logger.action(f"URL: {file_url}")
    
    try:
        # 方法1: 直接通过page下载
        async with page.context.request as request:
            response = await request.get(file_url)
            if response.ok:
                content = await response.body()
                filepath.write_bytes(content)
                logger.result(f"下载成功: {filename} ({len(content)} bytes)")
                return {"success": True, "filepath": str(filepath), "size": len(content)}
        
        # 方法2: 通过点击链接下载
        await page.goto(file_url, timeout=30000)
        await asyncio.sleep(2)
        
        return {"success": False, "error": "download_failed"}
        
    except Exception as e:
        logger.error(f"下载失败: {e}")
        return {"success": False, "error": str(e)}

async def verify_file(filepath: Path) -> bool:
    """
    验证文件是否完整可打开
    """
    if not filepath.exists():
        logger.error(f"文件不存在: {filepath}")
        return False
    
    # 检查文件大小
    size = filepath.stat().st_size
    if size < 100:  # 文件太小可能不完整
        logger.error(f"文件太小，可能不完整: {size} bytes")
        return False
    
    # 检查文件类型
    suffix = filepath.suffix.lower()
    
    # PDF验证
    if suffix == '.pdf':
        try:
            with open(filepath, 'rb') as f:
                header = f.read(5)
                if header != b'%PDF-':
                    logger.error(f"PDF文件头不正确")
                    return False
            logger.result(f"PDF文件验证通过")
            return True
        except Exception as e:
            logger.error(f"PDF验证失败: {e}")
            return False
    
    # Word文档验证
    elif suffix in ['.docx', '.doc']:
        try:
            # docx是zip格式
            if suffix == '.docx':
                import zipfile
                with zipfile.ZipFile(filepath, 'r') as z:
                    pass
            logger.result(f"Word文件验证通过")
            return True
        except Exception as e:
            logger.error(f"Word文件验证失败: {e}")
            return False
    
    # Excel验证
    elif suffix in ['.xlsx', '.xls']:
        try:
            import zipfile
            with zipfile.ZipFile(filepath, 'r') as z:
                pass
            logger.result(f"Excel文件验证通过")
            return True
        except Exception as e:
            logger.error(f"Excel文件验证失败: {e}")
            return False
    
    logger.result(f"文件验证通过: {size} bytes")
    return True

# ============ 主流程 ============

async def smart_crawl(
    url: str,
    target_date: str = None,
    filter_keyword: str = None,
    output_dir: str = None,
    max_items: int = 10
) -> dict:
    """
    智能爬取主流程
    """
    logger.step(f"开始智能爬取任务")
    logger.action(f"目标URL: {url}")
    if target_date:
        logger.action(f"目标日期: {target_date}")
    if filter_keyword:
        logger.action(f"筛选关键词: {filter_keyword}")
    
    # 设置输出目录
    if output_dir:
        output_path = Path(output_dir)
    else:
        output_path = Path.home() / "Documents" / "OpenClaw下载"
    output_path.mkdir(parents=True, exist_ok=True)
    logger.action(f"保存目录: {output_path}")
    
    async with async_playwright() as p:
        browser = await create_browser(p)
        context = await create_context(browser)
        page = await context.new_page()
        
        try:
            # ============ 步骤1: 访问目标页面 ============
            logger.step("步骤1: 访问目标页面")
            await page.goto(url, timeout=CONFIG['timeout'], wait_until='networkidle')
            
            # 多次滚动以加载懒加载内容
            logger.action("等待页面加载...")
            await asyncio.sleep(3)
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1)
            
            await safe_scroll(page)
            await wait_random(2, 4)
            logger.result(f"页面加载完成: {page.url}")
            
            # ============ 步骤2: 提取页面信息 ============
            logger.step("步骤2: 分析页面内容")
            query = filter_keyword or ""
            page_info = await extract_page_info(page, query)
            items = page_info.get('items', [])
            logger.result(f"共找到 {len(items)} 个内容项")
            
            # 显示前10个
            for i, item in enumerate(items[:10]):
                date_info = f" 📅 {item.get('date', '无日期')}" if item.get('date') else ""
                logger.action(f"  [{i+1}] {item['text'][:50]}...{date_info}")
            
            # ============ 步骤3: 按日期筛选 ============
            filtered_items = items
            if target_date:
                logger.step(f"步骤3: 按日期筛选 ({target_date})")
                filtered_items = await filter_by_date(items, target_date)
                logger.result(f"日期匹配: {len(filtered_items)} 个")
                
                if not filtered_items:
                    logger.warn("没有精确匹配日期的内容，查看相近日期...")
                    # 显示所有有日期的内容
                    dated_items = [i for i in items if i.get('date')]
                    for item in dated_items[:5]:
                        logger.action(f"  📅 {item['date']}: {item['text'][:40]}...")
            
            # 如果没有日期筛选，使用关键词筛选
            if filter_keyword and not target_date:
                logger.step(f"步骤3: 按关键词筛选 ({filter_keyword})")
                filtered_items = [i for i in items if filter_keyword.lower() in i['text'].lower()]
                logger.result(f"关键词匹配: {len(filtered_items)} 个")
            
            # ============ 步骤4: 访问详情页 ============
            if filtered_items:
                logger.step("步骤4: 访问详情页")
                target_item = filtered_items[0]
                detail_url = target_item['href']
                logger.action(f"点击进入: {target_item['text'][:50]}...")
                logger.action(f"URL: {detail_url}")
                
                await page.goto(detail_url, timeout=CONFIG['timeout'], wait_until='networkidle')
                await safe_scroll(page)
                await wait_random(2, 4)
                logger.result("详情页加载完成")
            
            # ============ 步骤5: 查找可下载文件 ============
            logger.step("步骤5: 查找可下载文件")
            downloadable = await find_downloadable_files(page)
            logger.result(f"找到 {len(downloadable)} 个可下载文件")
            
            for i, f in enumerate(downloadable[:5]):
                logger.action(f"  [{i+1}] {f['text']} -> {f['filename']}")
            
            # ============ 步骤6: 下载并验证 ============
            if downloadable:
                logger.step("步骤6: 下载并验证文件")
                downloaded_files = []
                
                for i, file_info in enumerate(downloadable[:max_items]):
                    logger.action(f"处理文件 {i+1}/{len(downloadable[:max_items])}: {file_info['filename']}")
                    
                    # 下载文件
                    result = await download_file(
                        page, 
                        file_info['href'], 
                        output_path, 
                        file_info['filename']
                    )
                    
                    if result.get('success'):
                        filepath = Path(result['filepath'])
                        
                        # 验证文件
                        logger.action(f"验证文件: {filepath.name}")
                        is_valid = await verify_file(filepath)
                        
                        if is_valid:
                            downloaded_files.append(str(filepath))
                            logger.result(f"✅ 文件有效: {filepath.name}")
                        else:
                            # 删除并重试
                            logger.warn("文件验证失败，删除并重新下载...")
                            filepath.unlink(missing_ok=True)
                            await wait_random(1, 2)
                            # 重试下载
                            result2 = await download_file(page, file_info['href'], output_path, file_info['filename'])
                            if result2.get('success'):
                                filepath2 = Path(result2['filepath'])
                                if await verify_file(filepath2):
                                    downloaded_files.append(str(filepath2))
                                    logger.result(f"✅ 重试成功: {filepath2.name}")
                                else:
                                    logger.error(f"❌ 重试仍然失败")
                            else:
                                logger.error(f"❌ 重试下载失败")
                
                logger.step("任务完成")
                return {
                    "success": True,
                    "downloaded_files": downloaded_files,
                    "count": len(downloaded_files)
                }
            else:
                logger.error("未找到可下载文件")
                return {"success": False, "error": "no_downloadable_files"}
        
        finally:
            await browser.close()
            await context.close()

# ============ 命令行入口 ============

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='🔍 智能内容发现与下载工具')
    parser.add_argument('url', help='目标URL')
    parser.add_argument('--date', '-d', help='目标日期 (格式: 2026-03-09 或 20260309)')
    parser.add_argument('--filter', '-f', help='筛选关键词')
    parser.add_argument('--output', '-o', help='输出目录')
    parser.add_argument('--max', '-m', type=int, default=5, help='最大下载文件数')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细日志')
    
    args = parser.parse_args()
    
    global logger
    logger = ExecutionLogger(verbose=args.verbose)
    
    result = await smart_crawl(
        url=args.url,
        target_date=args.date,
        filter_keyword=args.filter,
        output_dir=args.output,
        max_items=args.max
    )
    
    print(f"\n{'='*60}")
    if result.get('success'):
        print(f"✅ 任务完成! 共下载 {result.get('count', 0)} 个文件:")
        for f in result.get('downloaded_files', []):
            print(f"   📄 {f}")
    else:
        print(f"❌ 任务失败: {result.get('error', 'unknown')}")
    print(f"{'='*60}")

if __name__ == '__main__':
    asyncio.run(main())
