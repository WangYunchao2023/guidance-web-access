#!/usr/bin/env python3
"""
通用网页访问工具（优化版）
版本: 1.6.5 (2026-03-20)
更新: AI智能分流、多渠道搜索、默认关键词优化

优化方向：
1. 超时优化：从60秒增加到90秒，针对医药网站更长
2. 反爬增强：更多UA、请求间隔、随机滚动、鼠标模拟
3. 错误处理：增强异常捕获、分类错误、更好的重试
4. 页面加载：多种wait_until、懒加载等待、动态内容
5. [新增] playwright-stealth集成，更强反检测
6. [新增] 412/400错误专项处理
7. [新增] 更多等待策略和JS执行等待
"""

import asyncio
import sys
import os
import re
import subprocess
import random
import time
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# 尝试导入playwright-stealth
try:
    from playwright_stealth import stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("[警告] playwright-stealth未安装，反检测能力减弱")

# ============ 配置 ============

# VPN自动切换开关 (2026-03-20: 用户要求禁用自动切换)
# True = 检测到错误时自动切换VPN重试
# False = 检测到错误时记录信号，等待用户手动确认
AUTO_VPN_SWITCH = False

# 国内网站直连开关 (2026-03-20: 用户建议)
# True = 访问国内网站(cde.org.cn等)时，如果网络不稳定，自动尝试直连（不关VPN，只绕过VPN）
# False = 不自动直连
AUTO_DIRECT_FOR_CN = True

# 全局直连模式（由force_direct参数设置，影响requests库）
# 当为True时，所有requests调用都将禁用代理
REQUESTS_FORCE_DIRECT = False

# ============ CDE搜索默认关键词配置 (2026-03-20) ============

# 如果用户没指定关键词，默认搜索这些内容
CDE_DEFAULT_KEYWORDS = "指导原则 法规 征求意见稿"

# CDE网站各频道URL（用于多渠道搜索）
CDE_CHANNELS = {
    'zdyz': 'https://www.cde.org.cn/zdyz/index',           # 指导原则专栏
    'zdyz_db': 'https://www.cde.org.cn/zdyz/domestic',     # 指导原则数据库(国内)
    'zdyz_ich': 'https://www.cde.org.cn/zdyz/ich',         # ICH指导原则
    'fbtt': 'https://www.cde.org.cn/main/news/listpage/f1b85f03689d513e5cce1c6a3185a5a',  # 发布通告
    'zqyj': 'https://www.cde.org.cn/main/news/listpage/9f9c239c4e4f9f6708a079ec6443f60e',  # 征求意见
    'policy': 'https://www.cde.org.cn/main/policy/',        # 政策文件
}

# 相关性关键词（用于过滤结果）
CDE_RELEVANT_KEYWORDS = [
    # 核心类型
    '指导原则', '技术指导原则', '技术要求', '技术指南', 
    '征求意见稿', '草案', '试行',
    '法律法规', '管理办法', '规定', '细则',
    # 药品类型
    '药品', '药物', '制剂', '注射剂', '口服', '仿制药', '新药', '创新药',
    '生物制品', '疫苗', '血液制品', '细胞治疗', '基因治疗', '抗体', '蛋白',
    # 治疗领域
    '肿瘤', '癌症', '罕见病', '儿童', '老年', '精神', '心血管', '糖尿病',
    # 研究阶段
    '研发', '临床', '非临床', '药学', '药代', '药效', '毒理', '质量',
    '一致性评价', '生物等效性', '注册', '审评', '审批',
]

# ============ 网站分类配置 (2026-03-20: AI智能分流) ============

# 国内网站域名列表（这些网站应该直连访问，不走VPN）
CN_SITES = [
    # 医药监管
    'cde.org.cn', 'cde.org', 'nmpa.gov.cn', 'nmpa.org.cn', 'drugs.org.cn',
    'pharmacodia.com', '药智网.com', 'chinadrugtrials.org.cn',
    # 搜索引擎/门户
    'baidu.com', 'sina.com.cn', 'qq.com', '163.com', '126.com',
    'sohu.com', 'ifeng.com', 'zhao', 'alipay.com', 'taobao.com',
    'jd.com', 'tmall.com', 'alibaba.com', 'bilibili.com',
    # 视频/社交
    'youku.com', 'iqiyi.com', 'douban.com', 'weibo.com',
    'zhihu.com', 'csdn.net', 'jianshu.com', 'cnblogs.com',
    # 其他国内常用
    'aliyun.com', 'tencent.com', 'huawei.com', 'baidu.com',
]

# 需要VPN的国外网站（访问这些网站时需要VPN代理）
FOREIGN_SITES = [
    # 医药监管
    'fda.gov', 'ema.europa.eu', 'pmda.go.jp', 'hc-sc.gc.ca',
    'who.int', 'nist.gov', 'nih.gov', 'pubmed.gov',
    # 搜索引擎
    'google.com', 'google.', 'bing.com', 'duckduckgo.com',
    # 社交/AI
    'openai.com', 'anthropic.com', 'chatgpt.com', 'claude.ai',
    'twitter.com', 'x.com', 'facebook.com', 'instagram.com',
    'youtube.com', 'reddit.com', 'linkedin.com',
    # 学术
    'scholar.google', 'sciencedirect.com', 'springer.com',
    'nature.com', 'cell.com', 'nejm.org', 'thelancet.com',
    # 其他
    'github.com', 'stackoverflow.com', 'wikipedia.org',
]

# 常用VPN节点地区（用于AI决策）
VPN_REGIONS = {
    'us': '美国',
    'uk': '英国',
    'jp': '日本',
    'sg': '新加坡',
    'hk': '香港',
    'kr': '韩国',
    'de': '德国',
    'au': '澳大利亚',
}

VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 2560, "height": 1440},
    {"width": 1280, "height": 800},
]

# 扩展User-Agent池 - 包含更多浏览器版本和平台
UA_POOL = [
    # Chrome Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    # Chrome macOS
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Firefox
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0',
    # Edge
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    # 移动端 (偶尔使用)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
]

# 增强反检测脚本 - 针对CDE等高反爬网站
ANTIDETECT_SCRIPT = '''
// 移除webdriver属性
Object.defineProperty(navigator, "webdriver", {get: () => undefined});

// 模拟真实浏览器属性
window.chrome = {runtime: {}};

// 修改navigator属性
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en']
});

// 移除自动化检测标志
window.navigator.chrome = true;

// 添加假的permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({state: Notification.permission}) :
    originalQuery(parameters)
);

// 修改Notification
window.Notification = function() {};
window.Notification.permission = 'default';

// 添加假的webgl
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    if (parameter === 37446) {
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.apply(this, arguments);
};

// 模拟console
console.debug = () => {};
console.info = () => {};
'''

# 浏览器启动参数 - [优化] 禁用HTTP2对反爬网站很重要
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
    "--disable-http2",  # [关键] 禁用HTTP2 - 对反爬网站很重要!
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
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--disable-component-update",
    "--disable-default-extension",
    "--disable-domain-reliability",
    "--disable-fre",
    "--disable-hincr-tabs",
    "--disable-client-side-phishing-detection",
    "--disable-clir",
    "--disable-voice-input",
    "--disable-webrtc-encryption",
    "--disable-webrtc-hw-decoding",
    "--disable-webrtc-hw-encoding",
    "--disable-webrtc-multiple-routes",
    "--disable-webrtc-pipe-exchange",
    "--enable-features=WebRTC-H264WithSRTPConditional",
    "--force-webrtc-ip-handling-policy=default_public_interface_only",
]

# 超时配置 - 针对不同网站类型
TIMEOUT_CONFIGS = {
    'default': 90000,      # 默认90秒
    'pharma': 120000,     # 医药类网站120秒
    'slow': 150000,       # 慢速网站150秒
    'fast': 60000,        # 简单页面60秒
}

CONFIG = {
    'headless': True,
    'timeout': TIMEOUT_CONFIGS['default'],
    'max_retries': 5,       # 增加到5次重试
    'min_wait': 2,          # 最小等待秒数
    'max_wait': 8,          # 最大等待秒数
    'scroll_min': 3,        # 最小滚动次数
    'scroll_max': 8,        # 最大滚动次数
}

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    print(f"[{get_timestamp()}] {msg}")

# ============ 输出目录配置 ============

import os

def get_output_dir(config_type="pharma_manual"):
    """
    从 SKILL.md 读取输出目录配置
    config_type: pharma_scheduled(定时任务), pharma_manual(手动), general(通用)
    """
    skill_dir = Path(__file__).parent.parent
    skill_md = skill_dir / "SKILL.md"

    # 默认目录
    default_dirs = {
        "pharma_scheduled": Path.home() / "Documents" / "工作" / "法规指导原则更新",
        "pharma_manual": Path.home() / "Documents" / "工作" / "法规指导原则",
        "general": Path.home() / "Documents" / "OpenClaw下载",
    }

    if not skill_md.exists():
        log(f"⚠️ SKILL.md不存在，使用默认目录")
        return default_dirs.get(config_type, default_dirs["cde_manual"])

    try:
        content = skill_md.read_text(encoding='utf-8')

        # 解析配置
        config = {}
        in_config = False
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('output:'):
                in_config = True
                continue
            # 遇到output_end或---结束配置
            if in_config and (line == 'output_end' or line == '---'):
                break
            if in_config:
                if line.startswith('#') or not line:
                    continue
                if ':' in line:
                    # 只读取顶级配置（无缩进）
                    if not line.startswith(' ') and ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().strip('"').strip("'")
                        value = value.strip().strip('"').strip("'")
                        # 替换 ~
                        if value.startswith('~'):
                            value = str(Path.home() / value[2:])
                        config[key] = value

        # 返回对应类型的目录
        if config_type in config:
            result = Path(config[config_type])
            result.mkdir(parents=True, exist_ok=True)
            return result

    except Exception as e:
        log(f"⚠️ 读取配置失败: {e}，使用默认目录")

    return default_dirs.get(config_type, default_dirs["pharma_manual"])


# ============ 辅助函数 ============

def detect_site_type(url):
    """检测网站类型，返回对应的超时配置"""
    url_lower = url.lower()

    # 医药类网站特征
    pharma_keywords = [
        'pharma', 'drug', 'medicine', 'medical', 'health', 'fda', 'cde',
        'nmpa', 'ema', 'who', 'clinical', 'trial', 'regulatory', '药',
        '医药', '药品', '医院', 'cn', 'gov.cn'
    ]

    for kw in pharma_keywords:
        if kw in url_lower:
            return 'pharma'

    return 'default'

def get_timeout(url):
    """获取网站对应的超时时间"""
    site_type = detect_site_type(url)
    return TIMEOUT_CONFIGS.get(site_type, TIMEOUT_CONFIGS['default'])

# ============ VPN控制模块 ============

def get_vpn_script_path():
    """获取VPN控制脚本路径（优先使用vpn-control skill）"""
    paths = [
        os.path.expanduser("~/.openclaw/skills/vpn-control/scripts/aurora_vpn.py"),  # [优化] 使用skill
        os.path.expanduser("~/.openclaw/skills/vpn-control/scripts/vpn_control.py"),
        os.path.expanduser("~/.openclaw/scripts/vpn_control.py"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def check_vpn_available():
    """检查VPN控制是否可用"""
    return get_vpn_script_path() is not None

def connect_vpn():
    """连接VPN"""
    vpn_script = get_vpn_script_path()
    if vpn_script:
        try:
            subprocess.run(["python3", vpn_script, "connect"], timeout=30, capture_output=True)
            log("VPN已连接")
            return True
        except Exception as e:
            log(f"VPN连接失败: {e}")
    return False

def rotate_vpn():
    """轮换VPN节点 - [已废弃，改用信号机制]
    现在不再直接调用VPN，而是通过VPN信号让AI决定如何处理
    """
    pass

# ============ VPN信号模块（供AI决策）============

class VPNSignalManager:
    """VPN信号管理器 - 记录需要VPN的情况，供AI读取并决策"""
    
    def __init__(self):
        self.signals = []  # 存储VPN信号
        self.last_signal = None
    
    def clear(self):
        """清空信号"""
        self.signals = []
        self.last_signal = None
    
    def add_signal(self, url, error_type, error_msg, context=""):
        """添加VPN信号"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # 根据网站类型推荐节点
        suggested_node = self._get_suggested_node(domain)
        
        signal = {
            'domain': domain,
            'url': url,
            'error_type': error_type,
            'error_msg': error_msg[:200] if error_msg else "",
            'suggested_node': suggested_node,
            'reason': self._get_reason(error_type),
            'context': context,
            'action': f"调用 vpn-control skill，连接 {suggested_node} 节点"
        }
        
        self.signals.append(signal)
        self.last_signal = signal
        log(f"  📡 [VPN信号] {domain} - {error_type} - 建议: {signal['action']}")
        return signal
    
    def _get_suggested_node(self, domain):
        """根据网站类型推荐VPN节点"""
        node_mapping = {
            # 美国
            'fda.gov': '美国',
            'nih.gov': '美国', 
            'cdc.gov': '美国',
            'clinicaltrials.gov': '美国',
            # 欧洲
            'ema.europa.eu': '欧洲',
            'europa.eu': '欧洲',
            'who.int': '欧洲/瑞士',
            'ich.org': '欧洲/德国',
            # 亚洲其他
            'pmda.go.jp': '日本',
            'mhlw.go.jp': '日本',
        }
        
        for key, node in node_mapping.items():
            if key in domain:
                return node
        
        # 默认返回"随机"
        return '随机可用节点'
    
    def _get_reason(self, error_type):
        """获取错误原因说明"""
        reasons = {
            '403': '访问被拒绝，可能IP被封锁',
            'blocked': '访问被拦截，可能需要更换IP',
            '412': '反爬触发，需要更换IP',
            '400': '请求异常，可能需要更换IP',
            'timeout': '访问超时，网络可能不稳定',
            'network': '网络连接问题',
        }
        return reasons.get(error_type, '未知错误')
    
    def get_signals(self):
        """获取所有信号"""
        return self.signals
    
    def get_last_signal(self):
        """获取最新信号"""
        return self.last_signal
    
    def has_signals(self):
        """是否有信号"""
        return len(self.signals) > 0

# 全局信号管理器
vpn_signal_manager = VPNSignalManager()

def need_vpn(url, error_type, error_msg, context=""):
    """记录需要VPN的信号（供AI读取后决策）"""
    return vpn_signal_manager.add_signal(url, error_type, error_msg, context)

# ============ 错误检测与处理 ============

class AccessError(Exception):
    """访问错误异常"""
    def __init__(self, msg, error_type='unknown', recoverable=True):
        super().__init__(msg)
        self.error_type = error_type
        self.recoverable = recoverable

ERROR_TYPES = {
    'timeout': {'recoverable': True, 'vpn_needed': True},
    'network': {'recoverable': True, 'vpn_needed': True},
    '403': {'recoverable': True, 'vpn_needed': True},
    '404': {'recoverable': False, 'vpn_needed': False},
    '500': {'recoverable': True, 'vpn_needed': False},
    '412': {'recoverable': True, 'vpn_needed': True},    # 新增: Precondition Failed - 反爬
    '400': {'recoverable': True, 'vpn_needed': True},    # 新增: Bad Request - 反爬
    'blocked': {'recoverable': True, 'vpn_needed': True},
    'parse': {'recoverable': True, 'vpn_needed': False},
    'unknown': {'recoverable': True, 'vpn_needed': False},
}

def classify_error(error_msg):
    """分类错误类型"""
    error_lower = error_msg.lower()

    if 'timeout' in error_lower or 'timed out' in error_lower:
        return 'timeout'
    elif 'connection' in error_lower or 'network' in error_lower or 'econnrefused' in error_lower:
        return 'network'
    elif '403' in error_lower or 'forbidden' in error_lower or 'access denied' in error_lower:
        return '403'
    elif '412' in error_lower or 'precondition failed' in error_lower:
        return '412'  # 反爬
    elif '400' in error_lower or 'bad request' in error_lower:
        return '400'  # 反爬
    elif '404' in error_lower or 'not found' in error_lower:
        return '404'
    elif '500' in error_lower or 'internal server' in error_lower:
        return '500'
    elif 'blocked' in error_lower or 'captcha' in error_lower or 'challenge' in error_lower:
        return 'blocked'
    elif 'parse' in error_lower or 'extract' in error_lower:
        return 'parse'
    else:
        return 'unknown'

def should_use_vpn(error_msg, error_type):
    """判断是否需要使用VPN"""
    error_info = ERROR_TYPES.get(error_type, ERROR_TYPES['unknown'])
    return error_info.get('vpn_needed', False)

# ============ PDF验证 ============

def verify_pdf(filepath):
    """验证PDF是否能正常打开"""
    try:
        import PyPDF2
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            _ = reader.pages[0]
        return True, "OK"
    except:
        pass
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(filepath, maxpages=1)
        if len(text) > 10:
            return True, "OK"
    except:
        pass
    return False, "Invalid PDF"


def verify_office(filepath):
    """验证Office文件(docx, xlsx)是否能正常打开"""
    try:
        ext = filepath.lower().split('.')[-1]
        if ext == 'docx' or ext == 'doc':
            # 验证docx文件头 (PK\x03\x04 for docx, \xd0\xcf\x11\xe0 for old doc)
            with open(filepath, 'rb') as f:
                header = f.read(4)
                return header[:2] == b'PK' or header[:4] == b'\xd0\xcf\x11\xe0'
        elif ext in ['xlsx', 'xls']:
            with open(filepath, 'rb') as f:
                header = f.read(4)
                return header[:2] == b'PK' or header[:4] == b'\xd0\xcf\x11\xe0'
        return True
    except:
        return False


def extract_pdf_text(filepath, max_pages=3):
    """提取PDF正文内容用于比较"""
    text = ""
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(filepath, maxpages=max_pages)
    except:
        try:
            import PyPDF2
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(reader.pages[:max_pages]):
                    text += page.extract_text() or ""
        except:
            pass
    # 清理文本：去除多余空白
    text = ' '.join(text.split())
    return text


def compare_pdf_content(file1, file2):
    """
    比较两个PDF内容是否一致
    返回: (是否一致, 相似度百分比)
    """
    text1 = extract_pdf_text(file1)
    text2 = extract_pdf_text(file2)

    if not text1 or not text2:
        return False, 0

    # 计算相似度
    if text1 == text2:
        return True, 100

    # 简单的相似度计算
    len1, len2 = len(text1), len(text2)
    min_len = min(len1, len2)
    if min_len == 0:
        return False, 0

    # 计算相同字符数
    same = sum(1 for a, b in zip(text1, text2) if a == b)
    similarity = (same / min_len) * 100

    # 相似度>95%认为一致（允许少量差异如页眉页脚）
    return similarity > 95, similarity


def check_existing_file(filepath):
    """
    检查是否已有同名文件，比较内容
    返回: (是否相同, 处理建议)
    """
    if not filepath.exists():
        return None, "新文件"

    # 检查文件类型
    ext = filepath.suffix.lower()

    if ext in ['.pdf']:
        # PDF文件：比较正文内容
        # 创建一个临时文件来下载比较
        return "compare_content", "需要比较内容"

    elif ext in ['.docx', '.doc', '.xlsx', '.xls']:
        # Office文件：简单比较大小
        return "compare_size", "比较文件大小"

    else:
        # 其他文件：默认比较
        return "compare_size", "比较文件大小"

# ============ 页面行为模拟 ============

async def simulate_human_behavior(page):
    """模拟人类浏览行为：滚动、鼠标移动、随机等待"""
    try:
        # 随机等待一段时间
        wait_time = random.uniform(CONFIG['min_wait'], CONFIG['max_wait'])
        await asyncio.sleep(wait_time)

        # 随机滚动 - 模拟阅读
        scroll_count = random.randint(CONFIG['scroll_min'], CONFIG['scroll_max'])

        for _ in range(scroll_count):
            # 随机滚动距离
            scroll_amount = random.randint(200, 800)

            # 随机选择滚动方向（大部分向下，偶尔向上）
            direction = 1 if random.random() > 0.2 else -1

            await page.evaluate(f'''
                window.scrollBy(0, {scroll_amount * direction});
            ''')

            # 滚动后随机等待
            await asyncio.sleep(random.uniform(0.5, 1.5))

            # 偶尔随机鼠标移动
            if random.random() > 0.5:
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.2, 0.5))

        # 滚动到页面顶部（模拟开始阅读）
        if random.random() > 0.5:
            await page.evaluate('window.scrollTo(0, 0);')
            await asyncio.sleep(random.uniform(0.5, 1))

    except Exception as e:
        # 行为模拟失败不影响主流程
        log(f"  ⚠️ 行为模拟异常: {str(e)[:50]}")

async def wait_for_lazy_content(page, timeout=10000):
    """等待懒加载内容"""
    try:
        # 等待常见懒加载元素出现
        await page.wait_for_function('''
            () => {
                // 检查是否有图片、iframe或其他懒加载内容
                const images = document.querySelectorAll('img[src], img[data-src]');
                const lazyImages = document.querySelectorAll('img[data-src]');
                const iframes = document.querySelectorAll('iframe');

                // 如果有懒加载图片，尝试触发加载
                if (lazyImages.length > 0) {
                    lazyImages.forEach(img => {
                        if (img.dataset.src) {
                            img.src = img.dataset.src;
                        }
                    });
                }

                return true;
            }
        ''', timeout=timeout)
    except Exception:
        pass  # 懒加载等待失败不影响主流程

async def try_multiple_wait_strategies(page, url):
    """尝试多种页面加载策略"""
    strategies = ['networkidle', 'domcontentloaded', 'load', 'commit']

    for strategy in strategies:
        try:
            await page.goto(url, wait_until=strategy, timeout=CONFIG['timeout'])
            return True, strategy
        except Exception as e:
            log(f"  ⚠️ 策略 {strategy} 失败: {str(e)[:50]}")
            continue

    return False, None

# ============ 浏览器访问 ============

async def visit_with_retry(url, action='content', use_vpn=True):
    """带重试和VPN切换的访问"""
    last_error = None
    error_count = 0

    for attempt in range(CONFIG['max_retries']):
        try:
            return await visit_url(url, action)
        except Exception as e:
            error_msg = str(e)
            error_type = classify_error(error_msg)
            error_info = ERROR_TYPES.get(error_type, ERROR_TYPES['unknown'])
            last_error = f"[{error_type}] {error_msg}"

            error_count += 1
            log(f"  ⚠️ 第{attempt+1}次尝试失败 ({error_type}): {error_msg[:80]}")

            # [优化] 检测到需要VPN，记录信号供AI决策
            if use_vpn and should_use_vpn(error_msg, error_type):
                need_vpn(url, error_type, error_msg, context=f"第{attempt+1}次重试")
                # 不再直接调用VPN，等待AI处理信号

            # [优化] 针对反爬网站，增加等待时间
            wait_time = 5 if error_type in ['412', '400', 'blocked'] else 3
            if not error_info.get('recoverable', True):
                wait_time = 8

            # 最后一次尝试失败
            if attempt < CONFIG['max_retries'] - 1:
                await asyncio.sleep(wait_time)

    raise AccessError(f"访问失败（已重试{CONFIG['max_retries']}次）: {last_error}",
                     error_type=classify_error(last_error),
                     recoverable=False)

async def visit_url(url, action='content'):
    """访问URL并执行操作 - 优化版"""
    viewport = random.choice(VIEWPORT_POOL)
    user_agent = random.choice(UA_POOL)

    # 根据URL类型设置超时
    timeout = get_timeout(url)
    log(f"  🌐 访问 {url[:60]}... (超时: {timeout//1000}秒)")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=CONFIG['headless'],
                args=BROWSER_ARGS
                # 移除slow_mo - 会导致反爬网站获取不到内容
            )
        except Exception as e:
            log(f"  ⚠️ 浏览器启动失败: {e}")
            raise

        context = await browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            permissions=['geolocation'],
        )

        # [简化] 移除额外的HTTP头 - 可能导致问题
        # await context.set_extra_http_headers({...})

        page = await context.new_page()

        # [关键] 先访问空白页 - 对反爬网站很重要！
        try:
            await page.goto('about:blank', timeout=5000)
            await asyncio.sleep(0.5)
            log("  ✓ 空白页预加载")
        except:
            pass

        # [优化] 对于 pdf/download 动作，使用轻量级方式获取Cookie
        if action in ['pdf', 'download']:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}/"
            try:
                log(f"  📥 轻量级获取Cookie: {base_url}")
                cookie_dict = await get_cookie_light(context, base_url)
                log(f"  ✓ 获取 {len(cookie_dict)} 个Cookies")
            except Exception as e:
                log(f"  ⚠ 获取Cookie失败: {e}")

        # [简化] 移除反检测脚本注入 - 可能导致页面加载问题
        # await page.add_init_script(ANTIDETECT_SCRIPT)

        # 设置默认超时
        page.set_default_timeout(timeout)

        # [简化] 移除响应监听器 - 可能导致问题
        # blocked_urls = []
        # def handle_response(response):
        #     if response.status in [412, 400, 403] and 'nmpa' in response.url.lower():
        #         blocked_urls.append({'url': response.url, 'status': response.status})
        # page.on("response", handle_response)

        try:
            # [关键] 先访问空白页 - 对反爬网站很重要
            await page.goto('about:blank', timeout=5000)
            await asyncio.sleep(0.5)

            # [优化] 使用networkidle策略 - 对反爬网站更有效
            response = await page.goto(url, wait_until='networkidle', timeout=timeout)
            log(f"  ✓ networkidle完成 (status: {response.status if response else 'None'})")

            # [简化] 移除额外的等待和JS执行
            # await asyncio.sleep(3)
            # try:
            #     await page.evaluate(...)

            log(f"  ✓ 页面加载完成")

            # 等待页面稳定
            await asyncio.sleep(1)

            if action == 'content':
                content = await page.evaluate('''() => {
                    // 尝试获取主要内容
                    const main = document.querySelector('main') ||
                                 document.querySelector('.main') ||
                                 document.querySelector('#main') ||
                                 document.body;

                    // 移除脚本和样式
                    const clone = main.cloneNode(true);
                    const scripts = clone.querySelectorAll('script, style, nav, header, footer');
                    scripts.forEach(s => s.remove());

                    return clone.innerText || clone.textContent || '';
                }''')
                # 清理内容
                content = re.sub(r'\s+', ' ', content).strip()
                print(content[:8000])  # 限制输出长度

            elif action == 'title':
                title = await page.title()
                print(title)

            elif action == 'links':
                links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({
                            text: (a.textContent?.trim() || '').substring(0, 100),
                            href: a.href
                        }))
                        .filter(l => l.href && l.text.length > 0)
                        .slice(0, 50);
                }''')
                for link in links:
                    print(f"{link['text'][:50]}: {link['href']}")

            elif action == 'screenshot':
                filename = f"screenshot_{int(time.time())}.png"
                await page.screenshot(path=filename, full_page=True)
                print(f"截图保存到: {filename}")

            elif action == 'pdf':
                # 扩展PDF链接选择器，支持多种格式
                pdf_links = await page.evaluate('''() => {
                    const links = [];
                    // 标准PDF链接
                    document.querySelectorAll('a[href$=".pdf"], a[href*=".pdf?"]').forEach(a => {
                        links.push({text: a.textContent?.trim() || '', href: a.href});
                    });
                    // CDE/政府网站常用格式：包含download或att的链接
                    if (links.length === 0) {
                        document.querySelectorAll('a[href*="download"], a[href*="/att/"]').forEach(a => {
                            const text = a.textContent?.trim() || '';
                            const href = a.href || '';
                            if (href && !href.includes('javascript')) {
                                links.push({text: text, href: href});
                            }
                        });
                    }
                    // 表格中的下载链接
                    if (links.length === 0) {
                        document.querySelectorAll('table a').forEach(a => {
                            const text = a.textContent?.trim() || '';
                            const href = a.href || '';
                            if (href && text && !href.includes('javascript') && text.length > 2) {
                                links.push({text: text, href: href});
                            }
                        });
                    }
                    return links;
                }''')
                print(f"找到 {len(pdf_links)} 个PDF/下载链接:")
                for link in pdf_links[:20]:
                    print(f"  {link['text'][:60]}: {link['href']}")

            elif action == 'download':
                await download_files(page)

            else:
                # 默认当作content处理
                content = await page.evaluate('''() => document.body.innerText''')
                print(content[:8000])

        except PlaywrightTimeout:
            raise AccessError(f"页面加载超时 ({timeout//1000}秒)", error_type='timeout')
        except Exception as e:
            error_str = str(e)
            if 'net::' in error_str:
                raise AccessError(f"网络错误: {error_str}", error_type='network')
            elif '403' in error_str:
                raise AccessError(f"访问被拒绝: {error_str}", error_type='403')
            else:
                raise AccessError(f"访问错误: {error_str}", error_type='parse')
        finally:
            await browser.close()

async def download_files(page):
    """下载文件"""
    output_dir = get_output_dir("general")
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_links = await page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a[href$=".pdf"], a[href*=".pdf?"]'))
            .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
    }''')

    log(f"找到 {len(pdf_links)} 个PDF链接")

    for i, link in enumerate(pdf_links[:10], 1):
        href = link['href']
        # [优化] 保留完整文件名
        filename_text = link.get('text', '') or f"download_{i}"
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename_text) + '.pdf'
        if not filename.endswith('.pdf'):
            filename = f"download_{i}.pdf"

        filepath = output_dir / filename
        log(f"[{i}/{min(len(pdf_links), 10)}] 下载: {filename}")

        try:
            async with page.request.get(href) as response:
                if response.status == 200:
                    content = await response.body()
                    with open(filepath, 'wb') as f:
                        f.write(content)

                    is_valid, msg = verify_pdf(str(filepath))
                    if is_valid:
                        size = len(content)
                        log(f"  ✓ {filename} ({size} bytes)")
                    else:
                        log(f"  ✗ 验证失败: {msg}")
                        filepath.unlink(missing_ok=True)
                else:
                    log(f"  ✗ HTTP {response.status}")
        except Exception as e:
            log(f"  ✗ 错误: {str(e)[:50]}")

        # 请求间隔
        await asyncio.sleep(random.uniform(1, 3))

    # 清理临时目录
    if download_dir.exists():
        try:
            import shutil
            shutil.rmtree(download_dir)
        except:
            pass

    log(f"完成! 文件保存在: {output_dir}")

# ============ CDE下载（增强版，支持JS加密下载） ============

async def download_cde_by_date(date_str, task_keyword=None):
    """
    按日期下载CDE指导原则
    自动查找该日期发布的所有指导原则并下载
    
    参数:
        date_str: 日期字符串，格式如 "20260311" 或 "2026-03-11" 或 "3月11日"
        task_keyword: 任务关键词
    """
    global REQUESTS_FORCE_DIRECT
    import requests  # 添加requests导入
    
    # CDE是国内网站，默认启用直连模式
    REQUESTS_FORCE_DIRECT = True
    log("  🤖 AI判断: CDE为国内网站，启用直连模式")
    
    # 解析日期
    import re
    date_clean = date_str.replace('-', '').replace('年', '').replace('月', '').replace('日', '')
    # 如果是 MMDD 格式前面加当年
    if len(date_clean) == 4:
        from datetime import datetime
        date_clean = f"{datetime.now().year}{date_clean}"
    
    # 根据任务关键词判断配置类型
    if task_keyword:
        keyword_lower = task_keyword.lower()
        if any(k in keyword_lower for k in ['更新', '最新', '监测', '定期', 'check', 'new', 'update', 'monitor']):
            config_type = "pharma_scheduled"
            log(f"🔄 检测到更新监测任务，使用: pharma_scheduled")
        else:
            config_type = "pharma_manual"
    else:
        config_type = "pharma_manual"
    
    output_dir = get_output_dir(config_type)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ========== 详细日志显示 ==========
    log("=" * 60)
    log("🌐 web-access Skill 执行详情")
    log("=" * 60)
    log(f"📋 任务: 按日期查找CDE指导原则")
    log(f"📅 目标日期: {date_str}")
    log(f"📂 保存目录: {output_dir}")
    
    # CDE网站需要非headless模式才能正常加载
    use_headless = False  # 强制使用非headless模式
    log(f"🖥️ 浏览器模式: {'非headless (窗口移至后台)' if not use_headless else 'headless'}")
    log("-" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=use_headless, 
            args=BROWSER_ARGS,
            slow_mo=50  # 添加延迟模拟人类操作
        )
        
        # 窗口处理：如果非headless模式，将窗口移到屏幕外不影响用户
        if not use_headless:
            try:
                # 获取浏览器窗口并移到屏幕外（x=10000，超出大部分显示器）
                async def move_window():
                    await asyncio.sleep(2)  # 等待页面加载
                    try:
                        # 使用JavaScript将窗口移到屏幕外
                        await page.evaluate('''() => {
                            // 尝试移动窗口到屏幕外
                            if (window.screen) {
                                window.moveTo(10000, 0);
                                window.innerWidth = 1920;
                                window.innerHeight = 1080;
                            }
                        }''')
                    except:
                        pass
                
                # 启动窗口移动任务（不阻塞主流程）
                asyncio.create_task(move_window())
            except:
                pass
        
        context = await browser.new_context(
            user_agent=random.choice(UA_POOL),
            locale='zh-CN',
            viewport=random.choice(VIEWPORT_POOL),
            extra_http_headers={
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }
        )
        page = await context.new_page()
        
        # 使用增强版反检测脚本
        await page.add_init_script(ANTIDETECT_SCRIPT)

        try:
            # 访问工作动态列表页
            log(f"🔗 访问URL: https://www.cde.org.cn/main/news/listpage/3cc45b396497b598341ce3af000490e5")
            log(f"⏳ 等待页面加载...")
            await page.goto("https://www.cde.org.cn/main/news/listpage/3cc45b396497b598341ce3af000490e5", 
                          wait_until='networkidle', timeout=60000)
            await asyncio.sleep(10)  # 等待页面完全加载
            
            # 获取Cookie
            cookies = await context.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            log(f"✓ 获取 {len(cookie_dict)} 个Cookies (用于后续下载)")
            log("-" * 60)

            # 查找包含指定日期的所有链接
            log(f"🔍 搜索策略: 在页面中查找包含日期 '{date_str}' 的链接")
            log(f"⏳ 正在分析页面内容...")
            
            # 获取页面所有链接
            all_links = await page.evaluate('''(date_clean) => {
                const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
                return links.map(a => ({
                    href: a.href,
                    text: a.innerText?.trim() || '',
                    parent: a.parentElement?.innerText?.trim() || ''
                }));
            }''', date_clean)

            # 筛选包含指定日期的链接
            # 日期格式: '2026.03 09' 或 '2026.03.09' 或 '20260309'
            date_links = []
            
            # 将日期转换为各种可能的格式
            year = date_clean[:4]
            month = date_clean[4:6]
            day = date_clean[6:8]
            
            # 尝试多种日期格式匹配
            date_patterns = [
                f"{year}.{month} {day}",      # 2026.03 09
                f"{year}.{month}.{day}",       # 2026.03.09
                f"{year}{month}{day}",         # 20260309
                f"{year}年{int(month)}月{int(day)}日",  # 2026年3月9日
                f"{year}年{month}月{day}日",  # 2026年03月09日
            ]
            
            for link in all_links:
                # 检查链接文本或父元素文本中是否包含日期
                text_content = link['text'] + ' ' + link['parent']
                for pattern in date_patterns:
                    if pattern in text_content:
                        date_links.append(link)
                        break

            log(f"✓ 找到 {len(date_links)} 条与 '{date_str}' 相关的指导原则")
            log("-" * 60)
            
            if not date_links:
                log("⚠️ 未找到匹配结果，尝试其他方式...")
                # 尝试直接访问工作动态页
                news_url = f"https://www.cde.org.cn/main/news/listpage/3cc45b396497b598341ce3af000490e5?date={date_clean}"
                await page.goto(news_url, wait_until='networkidle', timeout=30000)
                await asyncio.sleep(2)
                
                # 再次尝试查找
                all_links = await page.evaluate('''
                    () => {
                        const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
                        return links.map(a => ({
                            href: a.href,
                            text: a.innerText?.trim() || '',
                        }));
                    }
                ''')
                
                for link in all_links:
                    if date_clean[:4] in link['text']:
                        date_links.append(link)
                
                log(f"✓ 再次查找，找到 {len(date_links)} 条")
            
            # 去重
            seen_urls = set()
            unique_links = []
            for link in date_links:
                if link['href'] not in seen_urls:
                    seen_urls.add(link['href'])
                    unique_links.append(link)
            
            log(f"✓ 去重后: {len(unique_links)} 条有效链接")
            log("-" * 60)
            log(f"📥 开始下载附件...")
            log("=" * 60)
            
            # 逐个下载
            downloaded_count = 0
            verified_count = 0
            for i, link in enumerate(unique_links[:10], 1):  # 最多下载10个
                detail_url = link['href']
                title = link['text'][:60]
                log(f"\n[{i}/{len(unique_links)}] 📄 标题: {title}")
                log(f"    🔗 URL: {detail_url}")
                
                try:
                    # 访问详情页
                    await page.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
                    await asyncio.sleep(2)
                    
                    # 查找PDF附件
                    pdf_links = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href*="/att/download/"]'))
                            .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
                    }''')
                    
                    if pdf_links:
                        log(f"    ✓ 发现 {len(pdf_links)} 个附件:")
                        
                        # 获取发布日期
                        publish_date = date_clean
                        
                        for pdf_link in pdf_links:
                            pdf_url = pdf_link['href']
                            # [优化] 保留完整文件名
                            filename = pdf_link.get('text', '') or f"附件_{i}.pdf"
                            
                            # 添加日期前缀
                            filename = f"{publish_date} - {filename}"
                            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                            
                            filepath = output_dir / filename
                            
                            # 下载
                            headers = {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                'Referer': 'https://www.cde.org.cn/',
                            }
                            
                            # 检查是否需要直连（禁用代理）
                            proxies = None
                            if getattr(download_generic_page, 'force_direct', False):
                                proxies = {'http': None, 'https': None}
                                log(f"      [直连] 下载: {filename}")
                            
                            # 检查是否需要直连（禁用代理）
                            if REQUESTS_FORCE_DIRECT:
                                log(f"      [直连] 下载")
                                # 创建不使用代理的session
                                session = requests.Session()
                                session.trust_env = False  # 禁用环境变量中的代理
                                r = session.get(pdf_url, headers=headers, cookies=cookie_dict, timeout=60)
                            else:
                                r = requests.get(pdf_url, headers=headers, cookies=cookie_dict, timeout=60)
                            if r.status_code == 200 and len(r.content) > 500:
                                with open(filepath, 'wb') as f:
                                    f.write(r.content)

                                # 验证文件
                                filename_lower = filename.lower()
                                if filename_lower.endswith('.pdf'):
                                    is_valid, msg = verify_pdf(str(filepath))
                                elif filename_lower.endswith(('.docx', '.doc', '.xlsx', '.xls')):
                                    # Office文件简单验证：检查文件头
                                    is_valid = verify_office(str(filepath))
                                    msg = "OK" if is_valid else "Invalid Office file"
                                else:
                                    is_valid, msg = True, "OK"  # 其他文件默认通过
                                
                                if is_valid:
                                    size = len(r.content)
                                    log(f"      ✓ 下载成功: {filename} ({size:,} bytes) [已验证]")
                                    downloaded_count += 1
                                    verified_count += 1
                                else:
                                    log(f"      ✗ 验证失败: {filename} ({msg}) - 已删除")
                                    filepath.unlink(missing_ok=True)
                            else:
                                log(f"      ✗ 下载失败: HTTP {r.status_code}")
                    else:
                        log(f"  ✗ 未找到附件")
                        
                except Exception as e:
                    log(f"      ✗ 处理失败: {e}")
                    continue
            
            log("=" * 60)
            log("📊 执行摘要")
            log("=" * 60)
            log(f"✓ 扫描页面: {len(all_links)} 个链接")
            log(f"✓ 匹配结果: {len(date_links)} 条相关")
            log(f"✓ 有效链接: {len(unique_links)} 条")
            log(f"✓ 下载成功: {downloaded_count} 个文件")
            log(f"✓ 验证通过: {verified_count} 个文件")
            log(f"📂 保存位置: {output_dir}")
            log("=" * 60)

        finally:
            await browser.close()


async def search_cde_multi_channel(keyword, page, browser):
    """
    CDE多渠道搜索 - 合并去重
    搜索多个渠道并合并结果
    
    Args:
        keyword: 用户指定的关键词
        page: Playwright page对象
        browser: Playwright browser对象
    
    Returns:
        list: 去重后的相关链接列表
    """
    import re
    
    all_links = []
    seen_urls = set()
    
    # 扩展关键词：如果用户没指定，默认包含更多内容
    if keyword.strip() in ['', '指导原则', 'search', 'searching']:
        search_keyword = CDE_DEFAULT_KEYWORDS
        log(f"  ℹ️ 未指定关键词，使用默认: {CDE_DEFAULT_KEYWORDS}")
    else:
        # 用户指定了关键词，扩展搜索
        search_keyword = f"{keyword} {CDE_DEFAULT_KEYWORDS}"
    
    log(f"  🔍 多渠道搜索关键词: {search_keyword}")
    
    # ============ 渠道1: 搜索框搜索 ============
    log("  → 渠道1: 搜索框搜索...")
    try:
        # 访问首页
        await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=30000)
        await asyncio.sleep(2)
        
        # 尝试找到搜索框
        searchSelectors = [
            'input[placeholder*="关键词"]',
            'input[type="text"][name*="search"]',
            'input[type="text"][id*="search"]',
        ]
        
        search_input = None
        for sel in searchSelectors:
            try:
                search_input = await page.wait_for_selector(sel, timeout=3000)
                if search_input:
                    break
            except:
                continue
        
        if search_input:
            await search_input.fill(search_keyword)
            await asyncio.sleep(1)
            
            # 点击搜索
            try:
                await page.click('button:has-text("搜索")', timeout=3000)
            except:
                await page.keyboard.press('Enter')
            
            await asyncio.sleep(5)
            
            # 获取搜索结果
            search_links = await page.evaluate('''() => {
                const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
                return links.slice(0, 30).map(a => ({
                    href: a.href,
                    text: a.innerText?.trim() || ''
                }));
            }''')
            
            for link in search_links:
                if link['href'] not in seen_urls:
                    seen_urls.add(link['href'])
                    all_links.append({**link, 'source': '搜索框'})
            
            log(f"    搜索框找到: {len(search_links)} 条")
    except Exception as e:
        log(f"    搜索框失败: {str(e)[:30]}")
    
    # ============ 渠道2: 指导原则专栏 ============
    log("  → 渠道2: 指导原则专栏...")
    try:
        await page.goto(CDE_CHANNELS['zdyz'], wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        
        # 在指导原则页面搜索
        try:
            search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=5000)
            if search_input:
                await search_input.fill(search_keyword)
                await asyncio.sleep(1)
                await page.click('button:has-text("搜索")')
                await asyncio.sleep(5)
        except:
            pass
        
        # 获取链接
        guide_links = await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
            return links.slice(0, 30).map(a => ({
                href: a.href,
                text: a.innerText?.trim() || ''
            }));
        }''')
        
        for link in guide_links:
            if link['href'] not in seen_urls:
                seen_urls.add(link['href'])
                all_links.append({**link, 'source': '指导原则专栏'})
        
        log(f"    指导原则专栏找到: {len(guide_links)} 条")
    except Exception as e:
        log(f"    指导原则专栏失败: {str(e)[:30]}")
    
    # ============ 渠道3: 征求意见 ============
    log("  → 渠道3: 征求意见...")
    try:
        await page.goto(CDE_CHANNELS['zqyj'], wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        
        # 获取征求意见列表
        draft_links = await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
            return links.slice(0, 30).map(a => ({
                href: a.href,
                text: a.innerText?.trim() || ''
            }));
        }''')
        
        for link in draft_links:
            if link['href'] not in seen_urls:
                seen_urls.add(link['href'])
                all_links.append({**link, 'source': '征求意见'})
        
        log(f"    征求意见找到: {len(draft_links)} 条")
    except Exception as e:
        log(f"    征求意见失败: {str(e)[:30]}")
    
    # ============ 渠道4: 发布通告 ============
    log("  → 渠道4: 发布通告...")
    try:
        await page.goto(CDE_CHANNELS['fbtt'], wait_until='networkidle', timeout=30000)
        await asyncio.sleep(3)
        
        # 获取发布通告
        news_links = await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'));
            return links.slice(0, 30).map(a => ({
                href: a.href,
                text: a.innerText?.trim() || ''
            }));
        }''')
        
        for link in news_links:
            if link['href'] not in seen_urls:
                seen_urls.add(link['href'])
                all_links.append({**link, 'source': '发布通告'})
        
        log(f"    发布通告找到: {len(news_links)} 条")
    except Exception as e:
        log(f"    发布通告失败: {str(e)[:30]}")
    
    # ============ 合并去重结果 ============
    log(f"  → 共收集到 {len(all_links)} 条链接，开始相关性分析...")
    
    # 相关性分析
    relevant_links = []
    for link in all_links:
        text = link.get('text', '').lower()
        # 检查是否包含相关关键词
        is_relevant = any(kw in text for kw in CDE_RELEVANT_KEYWORDS)
        if is_relevant:
            relevant_links.append(link)
    
    log(f"  ✓ 相关链接: {len(relevant_links)} 条")
    
    return relevant_links


async def download_cde(keyword, task_keyword=None):
    """
    下载CDE指导原则 - 智能搜索模式
    1. 先用搜索框搜索
    2. 如果没找到，去列表页逐级查找
    3. 访问详情页下载附件
    """
    global REQUESTS_FORCE_DIRECT
    
    # CDE是国内网站，默认启用直连模式
    REQUESTS_FORCE_DIRECT = True
    log("  🤖 AI判断: CDE为国内网站，启用直连模式")
    
    # 根据任务关键词判断配置类型
    if task_keyword:
        keyword_lower = task_keyword.lower()
        if any(k in keyword_lower for k in ['更新', '最新', '监测', '定期', 'check', 'new', 'update', 'monitor']):
            config_type = "pharma_scheduled"
            log(f"🔄 检测到更新监测任务，使用: pharma_scheduled")
        else:
            config_type = "pharma_manual"
    else:
        config_type = "pharma_manual"
    
    output_dir = get_output_dir(config_type)
    output_dir.mkdir(parents=True, exist_ok=True)

    # [泛化+合并] 智能搜索策略
    original_keyword = keyword
    
    # 检测是否为日期查询
    date_patterns = ['月', '日', '号', '2026', '2025', '年']
    is_date_query = any(p in keyword for p in date_patterns)
    
    # 构建搜索策略列表
    search_keywords = []
    
    if is_date_query:
        # 日期查询：只用原始关键词
        search_keywords.append(keyword)
        log(f"  ℹ️ 检测为日期查询: {keyword}")
    elif keyword.strip() in ['', '指导原则', 'search', 'searching', '研发', '技术']:
        # 空查询：使用默认关键词
        search_keywords.append(CDE_DEFAULT_KEYWORDS)
        log(f"  ℹ️ 未指定关键词，使用默认: {CDE_DEFAULT_KEYWORDS}")
    else:
        # 主题查询：使用扩展关键词
        search_keywords.append(f"{keyword} {CDE_DEFAULT_KEYWORDS}")
        log(f"  ℹ️ 主题查询: {keyword}")
    
    log(f"🔍 CDE搜索 + 导航，将并行执行")
    log(f"📂 将保存到: {output_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=random.choice(UA_POOL),
            locale='zh-CN',
        )
        page = await context.new_page()
        await page.add_init_script(ANTIDETECT_SCRIPT)

        # [优化] 使用轻量级获取Cookie
        log("→ 轻量级获取CDE Cookie...")
        cookie_dict = await get_cookie_light(context, "https://www.cde.org.cn")
        log(f"✓ 获取 {len(cookie_dict)} 个Cookies")
        
        # 重新访问CDE首页（搜索需要加载完整页面）
        log("→ 重新访问CDE首页...")
        await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
        await asyncio.sleep(3)
        
        # 注入反检测脚本
        await page.add_init_script('''
            Object.defineProperty(navigator, "webdriver", {get: () => undefined});
        ''')

        # [搜索 + 导航 并行执行]
        all_results = []
        seen_urls = set()
        
        # ========== 方式1: 搜索框搜索 ==========
        log(f"→ 方式1: 搜索框搜索...")
        try:
            await page.goto("https://www.cde.org.cn", wait_until='networkidle', timeout=60000)
            await asyncio.sleep(3)
            
            # 找到搜索框
            search_input = await page.wait_for_selector('input[placeholder*="关键词"]', timeout=10000)
            
            # 执行搜索
            for kw in search_keywords:
                log(f"    搜索: {kw}")
                await search_input.fill(kw)
                await asyncio.sleep(1)
                await search_input.press('Enter')
                await asyncio.sleep(8)
                
                # 获取结果
                links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'))
                        .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
                }''')
                
                # 合并
                for link in links:
                    if link['href'] not in seen_urls:
                        seen_urls.add(link['href'])
                        all_results.append({**link, 'source': '搜索'})
                
                log(f"      找到 {len(links)} 条")
            
            log(f"  ✓ 搜索完成，当前共 {len(all_results)} 条")
        except Exception as e:
            log(f"  ✗ 搜索失败: {str(e)[:40]}")
        
        # ========== 方式2: 智能网站导航 ==========
        log(f"→ 方式2: 智能网站导航...")
        
        # [AI决策] 根据用户搜索意图选择正确的导航路径
        # 定义导航意图分类
        intent_keywords = {
            '指导原则': ['指导原则', '技术要求', '技术指南', '技术指导'],
            '沟通交流': ['沟通交流', '会议', '申请', '交流办法'],
            '征求意见': ['征求意见', '草案', '征求'],
            '政策法规': ['法规', '政策', '办法', '细则', '规定'],
            '注册': ['注册', '申报', '审批', '上市'],
        }
        
        # 识别用户意图
        detected_intents = []
        search_text = original_keyword.lower()
        for intent, keywords in intent_keywords.items():
            if any(kw in search_text for kw in keywords):
                detected_intents.append(intent)
        
        # 如果没有识别到意图，默认添加通用意图
        if not detected_intents:
            detected_intents = ['指导原则', '政策法规']
        
        log(f"    🤖 识别到搜索意图: {detected_intents}")
        
        # 根据意图选择对应的导航URL
        # 导航URL映射表
        intent_nav_urls = {
            '指导原则': [
                ('指导原则专栏', 'https://www.cde.org.cn/zdyz/index'),
                ('指导原则数据库', 'https://www.cde.org.cn/zdyz/domestic'),
            ],
            '沟通交流': [
                ('政策法规-沟通交流', 'https://www.cde.org.cn/main/policy/'),
                ('政策文件列表', 'https://www.cde.org.cn/main/policy/listpage'),
            ],
            '征求意见': [
                ('征求意见', 'https://www.cde.org.cn/main/news/listpage/9f9c239c4e4f9f6708a079ec6443f60e'),
            ],
            '政策法规': [
                ('政策法规', 'https://www.cde.org.cn/main/policy/'),
                ('政策文件', 'https://www.cde.org.cn/main/policy/listpage'),
            ],
            '注册': [
                ('注册受理', 'https://www.cde.org.cn/main/xxgk/listpage/2f78f372d351c6851af7431c7710286e'),
            ],
        }
        
        # 构建智能导航列表
        nav_pages = []
        for intent in detected_intents:
            if intent in intent_nav_urls:
                for nav_name, nav_url in intent_nav_urls[intent]:
                    nav_pages.append((nav_name, nav_url))
        
        # 去重
        nav_pages = list(dict.fromkeys(nav_pages))
        
        log(f"    📍 智能选择 {len(nav_pages)} 个导航位置: {[n[0] for n in nav_pages]}")
        
        for nav_name, nav_url in nav_pages:
                try:
                    log(f"    导航: {nav_name}...")
                    await page.goto(nav_url, wait_until='networkidle', timeout=60000)
                    await asyncio.sleep(3)
                    
                    # 获取该页面的所有链接
                    links = await page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href*="/main/news/viewInfoCommon/"]'))
                            .slice(0, 30).map(a => ({href: a.href, text: a.innerText?.trim() || ''}));
                    }''')
                    
                    # 合并
                    new_count = 0
                    for link in links:
                        if link['href'] not in seen_urls:
                            seen_urls.add(link['href'])
                            all_results.append({**link, 'source': f'导航-{nav_name}'})
                            new_count += 1
                    
                    if new_count > 0:
                        log(f"      {nav_name}: +{new_count} 条")
                        
            except Exception as e:
                log(f"      {nav_name} 失败: {str(e)[:20]}")
        
        log(f"  ✓ 导航完成")
        
        # ========== 合并结果 ==========
        log(f"✓ 搜索+导航并行完成，共 {len(all_results)} 条记录")
        
        # 去重
        seen = set()
        unique_urls = []
        for link in all_results:
            if link['href'] not in seen:
                seen.add(link['href'])
                unique_urls.append(link)
        
        log(f"✓ 去重后共 {len(unique_urls)} 个待下载链接")
        
        # 逐个访问详情页下载附件
        download_success_count = 0
        total_pages = len(unique_urls)
        
        for i, link in enumerate(unique_urls[:10], 1):  # 最多处理10个
            detail_url = link['href']
            title = link['text'][:60] if link['text'] else f"第{i}个"
            log(f"→ [{i}/{total_pages}] 访问详情页: {title}")
            
            try:
                await page.goto(detail_url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(2)
                
                # 查找PDF附件
                pdf_links = await page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href*="/att/download/"]'))
                        .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
                }''')
                
                if pdf_links:
                    log(f"  ✓ 找到 {len(pdf_links)} 个附件")
                    
                    # 获取发布日期
                    publish_date = await page.evaluate('''() => {
                        const selectors = ['span.publishDate', 'span.date', 'div.date', '.publishDate'];
                        for (const sel of selectors) {{
                            const el = document.querySelector(sel);
                            if (el) {{
                                const text = el.innerText || '';
                                const match = text.match(/(\\d{{4}})[-年]?(\\d{{1,2}})[-月]?(\\d{{1,2}})/);
                                if (match) return match[1] + match[2].padStart(2, '0') + match[3].padStart(2, '0');
                            }}
                        }}
                        return '';
                    }''')
                    
                    for pdf_link in pdf_links:
                        pdf_url = pdf_link['href']
                        # [优化] 保留完整文件名
                        filename = pdf_link.get('text', '') or "附件.pdf"
                        
                        if publish_date:
                            filename = f"{publish_date} - {filename}"
                        
                        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                        filepath = output_dir / filename
                        
                        # 下载
                        import requests
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': 'https://www.cde.org.cn/',
                        }
                        
                        # 检查是否需要直连
                        if REQUESTS_FORCE_DIRECT:
                            session = requests.Session()
                            session.trust_env = False
                            r = session.get(pdf_url, headers=headers, cookies=cookie_dict, timeout=60)
                        else:
                            r = requests.get(pdf_url, headers=headers, cookies=cookie_dict, timeout=60)
                        if r.status_code == 200 and len(r.content) > 500:
                            with open(filepath, 'wb') as f:
                                f.write(r.content)
                            log(f"  ✓ 下载: {filename}")
                            download_success_count += 1
                        else:
                            log(f"  ✗ 下载失败")
                else:
                    log(f"  ✗ 未找到附件")
                    
            except Exception as e:
                log(f"  ✗ 处理失败: {e}")
                continue
        
        # 检查是否有遗漏
        if total_pages > 0:
            if download_success_count > 0:
                log(f"✓ 全部完成! 处理了 {total_pages} 个页面，成功下载 {download_success_count} 个附件")
            else:
                log(f"⚠️ 警告: 找到 {total_pages} 个链接，但未能下载任何附件")
        
        log(f"✅ 完成! 文件保存在: {output_dir}")

        await browser.close()


async def download_cde_by_url(news_url, output_path=None, task_keyword=None):
    """
    通过CDE新闻详情页URL下载PDF附件
    使用浏览器点击下载，解决JS加密问题

    参数:
        news_url: CDE新闻详情页URL，如 https://www.cde.org.cn/main/news/viewInfoCommon/xxx
        output_path: 可选的输出目录
        task_keyword: 任务关键词，用于自动判断配置类型

    使用示例:
        python web_access.py cde-download "https://www.cde.org.cn/main/news/viewInfoCommon/2c071191f3a2ef45068b665e302fe494"

    自动判断逻辑:
        - 任务包含"更新"、"最新"、"监测"、"定期"等关键词 → pharma_scheduled (指导原则更新)
        - 否则默认 → pharma_manual (手动下载的指导原则)
    """
    global REQUESTS_FORCE_DIRECT
    
    # 检测是否是国内网站，如果是则启用直连模式
    if is_cn_site(news_url):
        REQUESTS_FORCE_DIRECT = True
        log("  🤖 AI判断: 国内网站，启用直连模式")
    
    # 根据任务关键词自动判断配置类型
    if task_keyword:
        keyword_lower = task_keyword.lower()
        # 更新监测类任务
        if any(k in keyword_lower for k in ['更新', '最新', '监测', '定期', 'check', 'new', 'update', 'monitor']):
            config_type = "pharma_scheduled"
            log(f"🔄 检测到更新监测任务，使用: pharma_scheduled")
        else:
            config_type = "pharma_manual"
    else:
        config_type = "pharma_manual"

    if output_path:
        output_dir = Path(output_path)
    else:
        # 从 SKILL.md 读取配置
        output_dir = get_output_dir(config_type)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建临时下载目录
    download_dir = output_dir / "temp_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    log(f"🔍 使用 web-access skill 访问CDE详情页: {news_url}")
    log(f"📂 将保存到: {output_dir}")

    async with async_playwright() as p:
        # 使用headless模式，但先访问首页获取cookie
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        # [优化] 使用轻量级获取Cookie
        log("轻量级获取CDE Cookie...")
        cookie_dict = await get_cookie_light(context, "https://www.cde.org.cn")
        log(f"获取 {len(cookie_dict)} 个Cookies")

        try:
            # 访问新闻详情页 - 先访问空白页再跳转，避免反爬
            await page.goto('about:blank')
            await asyncio.sleep(0.5)
            await page.goto(news_url, wait_until='domcontentloaded', timeout=120000)
            # 等待页面加载完成
            await page.wait_for_load_state('networkidle', timeout=30000)
            await asyncio.sleep(2)

            # 获取页面标题和发布日期
            title = await page.title()
            log(f"页面标题: {title}")

            # 提取发布日期 (格式: 20260309 或 2026-03-09)
            publish_date = await page.evaluate('''() => {
                // 尝试多种方式获取日期
                const selectors = [
                    'span.publishDate',
                    'span.date',
                    'div.date',
                    'div.publish-time',
                    'div.time',
                    '.publishDate',
                    '[class*="date"]'
                ];

                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = el.innerText || '';
                        const match = text.match(/(\\d{4})[-年]?(\\d{1,2})[-月]?(\\d{1,2})/);
                        if (match) {
                            return match[1] + match[2].padStart(2, '0') + match[3].padStart(2, '0');
                        }
                    }
                }

                // 从页面文本中查找
                const bodyText = document.body.innerText || '';
                const dateMatch = bodyText.match(/(\\d{4})[-年]?(\\d{1,2})[-月]?(\\d{1,2})/);
                if (dateMatch) {
                    return dateMatch[1] + dateMatch[2].padStart(2, '0') + dateMatch[3].padStart(2, '0');
                }

                return '';
            }''')

            if publish_date:
                log(f"发布日期: {publish_date}")
            else:
                # 尝试从URL中提取日期
                log("未找到发布日期")

            # 查找PDF下载链接 - 使用更精确的选择器
            pdf_links = await page.evaluate('''() => {
                const links = [];
                // 方式1: 查找表格中的下载链接 (CDE常用结构)
                const tableLinks = document.querySelectorAll('table a[href*="download"]');
                tableLinks.forEach(a => {
                    const text = a.textContent?.trim() || '';
                    const href = a.href || a.getAttribute('href') || '';
                    if (href) {
                        links.push({ text: text, href: href });
                    }
                });

                // 方式2: 查找所有包含 /main/att/download/ 的链接
                if (links.length === 0) {
                    document.querySelectorAll('a[href*="/main/att/download/"]').forEach(a => {
                        const text = a.textContent?.trim() || '';
                        links.push({ text: text || 'PDF附件', href: a.href || '' });
                    });
                }

                // 方式3: 查找任何包含download的链接
                if (links.length === 0) {
                    document.querySelectorAll('a[href*="download"]').forEach(a => {
                        const text = a.textContent?.trim() || '';
                        if (text && text.includes('.pdf')) {
                            links.push({ text: text, href: a.href || '' });
                        }
                    });
                }
                return links;
            }''')

            if not pdf_links:
                log("未找到PDF下载链接，尝试获取整个页面内容分析...")
                # 最后尝试：直接获取所有链接
                all_links = await page.evaluate('''() => {
                    const links = [];
                    document.querySelectorAll('a').forEach(a => {
                        if (a.href && a.href.includes('att') && a.href.includes('download')) {
                            links.push({
                                text: a.textContent?.trim() || '',
                                href: a.href
                            });
                        }
                    });
                    return links;
                }''')
                pdf_links = all_links
                log(f"找到 {len(pdf_links)} 个可能的相关链接")

            log(f"找到 {len(pdf_links)} 个附件")
            
            # 跟踪下载成功数量
            total_attachments = len(pdf_links)

            # 使用requests下载（更可靠），支持自动重试
            import requests
            
            # 重试配置
            max_retries = 3
            retry_delay = 2  # 秒
            
            # 记录失败的附件，留作重试用
            failed_downloads = []
            
            for attempt in range(max_retries):
                if attempt == 0:
                    # 第一次尝试，下载所有附件
                    links_to_download = pdf_links
                    log(f"开始下载附件...")
                else:
                    # 重试失败的附件
                    if not failed_downloads:
                        break
                    links_to_download = failed_downloads
                    failed_downloads = []
                    log(f"重试下载失败的附件 (第{attempt+1}次)...")
                
                for i, link in enumerate(links_to_download, 1):
                    href = link.get('href', '')
                    if not href:
                        continue

                    # 构建完整URL
                    if href.startswith('/'):
                        full_url = 'https://www.cde.org.cn' + href
                    else:
                        full_url = href

                    filename = link.get('text', '') or f"附件_{i}.pdf"
                    # [优化] 保留完整文件名，只清理非法字符
                    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

                # 判断实际文件类型（优先从原始文件名判断）
                actual_ext = None
                filename_lower = filename.lower()
                if '.docx' in filename_lower:
                    actual_ext = '.docx'
                elif '.doc' in filename_lower:
                    actual_ext = '.doc'
                elif '.xlsx' in filename_lower:
                    actual_ext = '.xlsx'
                elif '.xls' in filename_lower:
                    actual_ext = '.xls'
                # 其次从href判断
                elif '.docx' in href.lower():
                    actual_ext = '.docx'
                elif '.doc' in href.lower():
                    actual_ext = '.doc'
                elif '.xlsx' in href.lower():
                    actual_ext = '.xlsx'
                elif '.xls' in href.lower():
                    actual_ext = '.xls'

                # 如果有发布日期，添加到文件名开头
                if publish_date:
                    filename = f"{publish_date} - {filename}"

                # 修正后缀：移除已有的错误后缀，添加正确的
                if actual_ext:
                    # 移除可能存在的错误后缀（如.pdf）
                    for ext in ['.pdf', '.PDF']:
                        if filename_lower.endswith(ext):
                            filename = filename[:-len(ext)]
                            break
                    # 添加正确后缀
                    if not filename.lower().endswith(actual_ext):
                        filename = filename + actual_ext
                elif not filename.endswith('.pdf'):
                    filename += '.pdf'

                filepath = output_dir / filename
                log(f"开始下载: {filename}")
                log(f"  URL: {full_url}")

                try:
                    # 使用requests下载（携带cookie）
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
                        'Referer': 'https://www.cde.org.cn/',
                    }

                    # 检查是否需要直连
                    if REQUESTS_FORCE_DIRECT:
                        session = requests.Session()
                        session.trust_env = False
                        r = session.get(full_url, headers=headers, cookies=cookie_dict, timeout=60)
                    else:
                        r = requests.get(full_url, headers=headers, cookies=cookie_dict, timeout=60)

                    if r.status_code == 200 and len(r.content) > 500:
                        # 检查文件类型
                        content_type = r.headers.get('Content-Type', '')
                        file_ext = filename.split('.')[-1].lower() if '.' in filename else ''

                        # 如果URL包含明确的后缀，使用URL中的后缀
                        if '.docx' in href.lower() or '.doc' in href.lower():
                            file_ext = 'docx'
                            # 修正文件名
                            if not filename.lower().endswith(('.docx', '.doc')):
                                filename = filename.replace('.pdf', '.docx')
                                filepath = output_dir / filename
                        elif '.xlsx' in href.lower() or '.xls' in href.lower():
                            file_ext = 'xlsx'
                            if not filename.lower().endswith(('.xlsx', '.xls')):
                                filename = filename.replace('.pdf', '.xlsx')
                                filepath = output_dir / filename

                        with open(filepath, 'wb') as f:
                            f.write(r.content)

                        # 根据文件类型验证
                        if file_ext in ['docx', 'doc', 'xlsx', 'xlsx']:
                            # Word/Excel文件只检查文件头
                            with open(filepath, 'rb') as f:
                                header = f.read(4)
                                # DOCX = PK (504B), XLSX = PK, DOC = D0CF, XLS = D0CF
                                if header[:2] == b'PK' or header[:2] in [b'\xd0\xcf']:
                                    log(f"  ✓ {filename} ({len(r.content)} bytes) - 验证通过")
                                else:
                                    log(f"  ⚠ {filename} 可能损坏但保留")
                                    failed_downloads.append(link)  # 重试
                        else:
                            # PDF验证
                            is_valid, msg = verify_pdf(str(filepath))
                            if is_valid:
                                log(f"  ✓ {filename} ({len(r.content)} bytes) - 验证通过")
                            else:
                                log(f"  ✗ 损坏已删除: {msg}")
                                filepath.unlink(missing_ok=True)
                                failed_downloads.append(link)  # 重试
                    else:
                        log(f"  ✗ HTTP {r.status_code}, {len(r.content)} bytes")
                        failed_downloads.append(link)  # 重试

                except Exception as e:
                    log(f"  ✗ 下载失败: {e}")
                    failed_downloads.append(link)  # 重试
                    continue
                
                # 重试之间等待一下
                if attempt < max_retries - 1 and failed_downloads:
                    await asyncio.sleep(retry_delay)

        finally:
            await browser.close()

    # 清理临时目录
    if download_dir.exists():
        try:
            import shutil
            shutil.rmtree(download_dir)
        except:
            pass

    # 检查是否有遗漏
    downloaded_count = total_attachments - len(failed_downloads)
    if total_attachments > 0:
        if failed_downloads:
            log(f"⚠️ 警告: 页面显示 {total_attachments} 个附件，经过 {max_retries} 次重试后仍有 {len(failed_downloads)} 个下载失败")
        else:
            log(f"✓ 全部 {total_attachments} 个附件下载成功")
    
    log(f"完成! 文件保存在: {output_dir}")


# ============ FDA下载 ============

async def download_fda(keyword, task_keyword=None):
    """下载FDA Guidance
    
    Args:
        keyword: 搜索关键词
        task_keyword: 任务关键词，用于判断是手动下载还是监测更新
    """
    fda_url = "https://www.fda.gov/drugs/guidance-compliance-regulatory-information/guidances-drugs"
    
    # 根据任务关键词判断保存目录
    config_type = "pharma_manual"  # 默认手动下载
    if task_keyword:
        keyword_lower = task_keyword.lower()
        if any(k in keyword_lower for k in ['更新', '最新', '监测', '定期', 'check', 'new', 'update', 'monitor']):
            config_type = "pharma_scheduled"
            log(f"🔄 检测到更新监测任务，FDA文件保存到: pharma_scheduled")
    
    output_dir = get_output_dir(config_type)
    output_dir.mkdir(parents=True, exist_ok=True)
    log(f"FDA下载保存目录: {output_dir}")

    log(f"访问FDA搜索: {keyword}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=CONFIG['headless'], args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=random.choice(UA_POOL),
            locale='zh-CN',
        )
        page = await context.new_page()
        await page.add_init_script(ANTIDETECT_SCRIPT)

        try:
            await page.goto(fda_url, wait_until='networkidle', timeout=120000)
            await asyncio.sleep(5)

            # 搜索
            await page.fill('#search', keyword)
            await page.press('#search', 'Enter')
            await asyncio.sleep(5)

            # 查找PDF链接
            pdf_links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href$=".pdf"], a[href*=".pdf?"]'))
                    .map(a => ({text: a.textContent?.trim() || '', href: a.href}));
            }''')

            log(f"找到 {len(pdf_links)} 个PDF")

            for i, link in enumerate(pdf_links[:5], 1):
                href = link['href']
                filename = re.sub(r'[<>:"/\\|?*]', '_', link['text'][:60]) + '.pdf'
                filepath = output_dir / filename

                try:
                    async with page.request.get(href) as response:
                        if response.status == 200:
                            content = await response.body()
                            with open(filepath, 'wb') as f:
                                f.write(content)
                            log(f"  ✓ {filename}")
                except Exception as e:
                    log(f"  ✗ {e}")

        finally:
            await browser.close()
            # 清理临时目录
            if download_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(download_dir)
                except:
                    pass

# ============ 主入口 ============

# 专用网站处理器
SPECIAL_HANDLERS = {
    'cde.org.cn': {
        'name': 'CDE',
        'download_func': 'download_cde_by_url',
    },
    'fda.gov': {
        'name': 'FDA',
        'download_func': 'download_fda',
    },
    'nmpa.gov.cn': {
        'name': 'NMPA',
        'download_func': None,  # 暂未实现
    },
}

def detect_special_site(url):
    """检测是否是已知专用网站"""
    for domain, handler in SPECIAL_HANDLERS.items():
        if domain in url:
            return handler
    return None


def is_pharma_site(url):
    """检测是否是医药类网站"""
    pharma_domains = ['cde.org.cn', 'fda.gov', 'nmpa.gov.cn', 'who.int', 'ema.europa.eu',
                     'pmda.go.jp', 'healthcanada.gc.ca', 'medicinesauthority.eu',
                     'gov.cn', 'gov.uk', 'gov.au']
    return any(domain in url for domain in pharma_domains)


async def get_cookie_light(context, base_url):
    """
    轻量级获取Cookie - 访问空白页而非首页
    优化策略：先访问robots.txt/favicon.ico等轻量页面，避免加载大量资源
    """
    from urllib.parse import urljoin
    import asyncio
    
    # 尝试访问的页面列表（按优先级从轻到重）
    light_pages = [
        "/robots.txt",       # 通常很小，必需文件
        "/favicon.ico",      # 图标文件，很小
    ]
    
    cookie_dict = {}
    
    for light_page in light_pages:
        test_url = urljoin(base_url, light_page)
        try:
            log(f"  📥 尝试获取Cookie: {test_url}")
            resp = await context.request.get(test_url, timeout=10000)
            if resp.status in [200, 304, 404]:  # 即使404也说明会话建立了
                cookies = await context.cookies()
                cookie_dict = {c['name']: c['value'] for c in cookies}
                if cookie_dict:
                    log(f"  ✓ 通过 {light_page} 获取 {len(cookie_dict)} 个Cookies")
                    return cookie_dict
        except Exception as e:
            log(f"  ⚠ {light_page} 获取失败: {e}")
    
    # 如果轻量页面都失败，访问首页作为后备
    try:
        log(f"  📥 后备：访问首页获取Cookie: {base_url}")
        await context.request.get(base_url, timeout=20000)
        cookies = await context.cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies}
        log(f"  ✓ 通过首页获取 {len(cookie_dict)} 个Cookies")
    except Exception as e:
        log(f"  ⚠ 首页获取Cookie失败: {e}")
    
    return cookie_dict


async def get_cookies(url, force_direct=False):
    """获取网站Cookie
    
    Args:
        url: 要获取Cookie的URL
        force_direct: 是否强制直连（暂未实现，仅作日志提示）
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    home_url = f"{parsed.scheme}://{parsed.netloc}/"
    cookie_dict = {}

    if force_direct:
        log(f"  [直连模式] 获取Cookie: {home_url}")
    else:
        log(f"获取Cookie: {home_url}")

    try:
        async with async_playwright() as p:
            # 构建浏览器参数
            browser_args = [
                '--disable-blink-features=AutomationControlled', 
                '--no-sandbox'
            ]
            
            # 如果是直连模式，禁用代理
            if force_direct:
                browser_args.extend([
                    '--proxy-bypass-list=<-loopback>',
                ])
            
            browser = await p.chromium.launch(
                headless=True,
                args=browser_args
            )
            
            # 如果是直连模式，明确禁用代理
            if force_direct:
                context = await browser.new_context(
                    user_agent=random.choice(UA_POOL),
                    proxy={'server': 'direct://'}
                )
            else:
                context = await browser.new_context(user_agent=random.choice(UA_POOL))
            
            page = await context.new_page()

            await page.goto(home_url, timeout=20000, wait_until='domcontentloaded')
            await asyncio.sleep(2)

            cookies = await context.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            mode = "直连" if force_direct else "VPN"
            log(f"  [{mode}] 获取 {len(cookie_dict)} 个Cookies")

            await browser.close()
    except Exception as e:
        log(f"获取Cookie失败: {e}")

    return cookie_dict


async def download_generic(url, output_dir=None, task_keyword=None):
    """
    通用网站文件下载器
    适用于：NMPA、FDA、WHO、NMPA等有反爬的网站

    核心思路：
    1. 先访问网站首页获取Cookie
    2. 导航到目标页面
    3. 查找PDF/下载链接
    4. 使用requests下载（携带Cookie）
    5. 失败时自动尝试专用方法
    """
    from urllib.parse import urlparse

    # 解析URL获取域名
    parsed = urlparse(url)
    domain = parsed.netloc

    # 检测是否是已知专用网站
    special_handler = detect_special_site(url)
    if special_handler:
        log(f"检测到专用网站: {special_handler['name']}，将优先尝试专用方法")

    # 根据任务关键词判断配置类型
    if task_keyword:
        keyword_lower = task_keyword.lower()
        if any(k in keyword_lower for k in ['更新', '最新', '监测', '定期', 'check', 'new', 'update', 'monitor']):
            config_type = "pharma_scheduled"
            log(f"🔄 检测到更新监测任务，使用: pharma_scheduled")
        else:
            config_type = "pharma_manual"
    else:
        config_type = None

    # 确定输出目录
    if output_dir:
        output_path = Path(output_dir)
    else:
        # 根据域名和网站类型选择目录
        if is_pharma_site(url):
            # 医药类网站：根据任务类型选择目录
            if config_type:
                output_path = get_output_dir(config_type)
            else:
                output_path = get_output_dir("pharma_manual")
        else:
            # 通用网站
            output_path = get_output_dir("general")
    output_path.mkdir(parents=True, exist_ok=True)

    log(f"通用下载器启动: {url}")
    log(f"输出目录: {output_path}")

    # 检查VPN是否可用
    vpn_available = check_vpn_available()
    if vpn_available:
        if AUTO_VPN_SWITCH:
            log("✓ VPN可用，遇到地域限制将自动切换")
        else:
            log("✓ VPN可用（如需切换请手动执行 'python web_access.py vpn rotate'）")

    # 检查URL是否直接是下载链接
    url_lower = url.lower()
    is_direct_download = any(ext in url_lower for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '/download', '/att/', '/file/'])

    # 医药类网站：需要使用页面模式来获取日期前缀
    is_pharma = is_pharma_site(url)

    # 先获取Cookie
    home_url = f"{parsed.scheme}://{parsed.netloc}/"

    # 尝试下载，最多3次（含VPN切换）
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            cookie_dict = await get_cookies(url)

            # 如果是直接下载链接
            if is_direct_download and not is_pharma:
                # 非医药类网站：使用直接下载
                log(f"检测到直接下载链接，尝试直接下载... (尝试 {attempt+1}/{max_attempts})")
                result = await direct_download(url, output_path, cookie_dict, home_url)
                if result:
                    return result
            elif is_pharma and '/att/download/' in url:
                # 医药类下载链接：先尝试用新闻页面获取日期
                # 从 /main/att/download/xxx 转换为新闻页面
                # 需要先找到对应的新闻页面，或者直接用日期获取逻辑
                log(f"检测到医药类下载链接，使用带日期的下载模式...")

                # 尝试访问新闻详情页获取日期
                # CDE: /main/att/download/xxx -> /main/news/viewInfoCommon/yyy
                # 由于ID不同，这里使用简化的方式：先尝试通用下载，如果失败再尝试其他方法
                result = await direct_download(url, output_path, cookie_dict, home_url)
                if result:
                    return result
            else:
                # 页面模式：使用页面模式下载（可以获取日期）
                log(f"使用页面模式下载... (尝试 {attempt+1}/{max_attempts})")
                result = await download_generic_page(url, output_path, cookie_dict, home_url)
                if result:
                    return result

            # 如果第一次失败且检测到需要VPN，记录信号
            if attempt == 0 and vpn_available and should_use_vpn(str(e), classify_error(str(e))):
                need_vpn(url, classify_error(str(e)), str(e), context="CDE下载第一次失败")
                if not AUTO_VPN_SWITCH:
                    log("  ⚠️ 自动VPN切换已禁用，如需切换请手动执行 'python web_access.py vpn rotate'")

        except Exception as e:
            error_str = str(e).lower()
            if vpn_available and attempt < max_attempts - 1:
                # 检测是否地域限制错误
                if any(kw in error_str for kw in ['403', 'blocked', 'forbidden', 'access denied', '地域', 'region']):
                    log(f"⚠️ 检测到地域限制错误: {e}")
                    need_vpn(url, 'blocked', str(e), context="检测到地域限制")
                    if not AUTO_VPN_SWITCH:
                        log("  ⚠️ 自动VPN切换已禁用，如需切换请手动执行 'python web_access.py vpn rotate'")
                        continue
                    else:
                        continue
            log(f"下载失败: {e}")

    # Fallback：如果有专用处理器，尝试专用方法
    if special_handler and special_handler.get('download_func'):
        log(f"⚠️ 通用方法失败，尝试专用方法: {special_handler['name']}")

        if 'cde' in url and special_handler['name'] == 'CDE':
            # 尝试CDE专用方法
            try:
                await download_cde_by_url(url, str(output_path))
                return str(output_path)
            except Exception as e:
                log(f"  ✗ CDE专用方法也失败: {e}")

        elif 'fda' in url and special_handler['name'] == 'FDA':
            # 尝试FDA专用方法
            try:
                await download_fda(parsed.netloc.split('.')[0])
                return str(output_path)
            except Exception as e:
                log(f"  ✗ FDA专用方法也失败: {e}")

    # 所有方法都失败了，进行智能诊断
    log("⚠️ 所有方法尝试完毕，开始智能诊断...")
    diagnosis_result = diagnose_and_suggest(url, domain, special_handler)

    if diagnosis_result['can_resolve']:
        log(f"💡 找到可能的解决方案: {diagnosis_result['suggestion']}")

        # 自动尝试解决方案（传入task_keyword帮助AI判断）
        resolved = await auto_resolve(url, output_path, domain, diagnosis_result, vpn_available, task_keyword)
        if resolved:
            log("✅ 问题已解决！")
            return str(output_path)

        log("⚠️ 自动解决尝试失败，将记录到待处理列表")
    else:
        log("⚠️ 暂时无法自动解决此网站的问题")
        log(f"   原因分析: {diagnosis_result['reason']}")
        log(f"   网站: {domain}")

    return None


def is_cn_site(url_or_domain):
    """检测是否是国内网站"""
    url_lower = url_or_domain.lower()
    for cn_site in CN_SITES:
        if cn_site in url_lower:
            return True
    return False

def is_foreign_site(url_or_domain):
    """检测是否是需要VPN的国外网站"""
    url_lower = url_or_domain.lower()
    for foreign_site in FOREIGN_SITES:
        if foreign_site in url_lower:
            return True
    return False

def classify_site(url_or_domain, context_hint=None):
    """
    智能分类网站类型（支持AI上下文提示）
    
    Args:
        url_or_domain: 网站域名或URL
        context_hint: AI提供的上下文提示（如用户任务描述），可帮助判断
    
    返回: 'cn' (国内), 'foreign' (国外), 'unknown' (未知)
    """
    # 1. 先检查预定义列表
    if is_cn_site(url_or_domain):
        return 'cn'
    elif is_foreign_site(url_or_domain):
        return 'foreign'
    
    # 2. 如果有AI上下文提示，分析它
    if context_hint:
        context_lower = context_hint.lower()
        # 根据任务描述判断
        cn_keywords = ['cde', '药监局', 'nmpa', '国产', '国内', '中国', '药品注册', '仿制药', '一致性评价']
        foreign_keywords = ['fda', 'ema', 'fda', '美国', '欧洲', '日本pmda', '进口', '境外']
        
        for kw in cn_keywords:
            if kw in context_lower:
                return 'cn'
        for kw in foreign_keywords:
            if kw in context_lower:
                return 'foreign'
    
    # 3. 通过域名特征推断
    domain = url_or_domain.lower()
    
    # 3.1 常见国内域名后缀
    cn_tlds = ['.cn', '.中国', '.公司', '.网络', '.gov.cn', '.edu.cn', '.org.cn']
    for tld in cn_tlds:
        if domain.endswith(tld) or '.' + tld in domain:
            return 'cn'
    
    # 3.2 常见国内平台
    cn_platforms = ['baidu', 'alibaba', 'tencent', 'jd', 'taobao', 'tmall', 'bilibili', 
                   'douban', 'zhihu', 'weibo', 'youku', 'iqiyi', 'csdn', 'aliyun', 'huawei']
    for platform in cn_platforms:
        if platform in domain:
            return 'cn'
    
    # 3.3 常见国外平台
    foreign_platforms = ['google', 'microsoft', 'apple', 'amazon', 'facebook', 'twitter', 
                       'youtube', 'instagram', 'reddit', 'github', 'stackoverflow',
                       'openai', 'anthropic', 'netflix', 'amazon', 'wikipedia']
    for platform in foreign_platforms:
        if platform in domain:
            return 'foreign'
    
    # 4. 无法确定，记录并返回unknown
    log(f"  ⚠️ 未知网站类型: {url_or_domain} (请告知我，我会添加到列表中)")
    return 'unknown'

def suggest_vpn_region(site_type, url_or_domain):
    """
    根据网站类型推荐VPN节点地区
    返回: 推荐的地区代码
    """
    url_lower = url_or_domain.lower()
    
    # 根据具体网站推荐
    if 'fda' in url_lower or 'nih' in url_lower or 'pubmed' in url_lower:
        return 'us'  # 美国
    elif 'ema' in url_lower:
        return 'uk'  # 英国
    elif 'pmda' in url_lower:
        return 'jp'  # 日本
    elif 'google' in url_lower or 'youtube' in url_lower:
        return 'us'  # 美国或香港
    elif 'github' in url_lower:
        return 'us'
    elif 'openai' in url_lower or 'anthropic' in url_lower:
        return 'us'
    
    # 默认
    return 'us'

async def auto_resolve(url, output_path, domain, diagnosis_result, vpn_available, task_keyword=None):
    """
    根据诊断结果自动尝试解决问题 - AI智能策略选择
    返回: 是否成功
    
    AI决策逻辑:
    1. 国内网站 → 优先直连（不走VPN）
    2. 国外网站 → 记录信号，等待手动切换VPN节点
    3. 未知网站 → 尝试直连，失败后再尝试VPN
    
    Args:
        url: 目标URL
        output_path: 输出目录
        domain: 域名
        diagnosis_result: 诊断结果
        vpn_available: VPN是否可用
        task_keyword: 任务关键词（可选），帮助AI判断网站类型
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)

    log(f"🔧 开始自动解决问题...")
    
    # 如果有任务关键词，一并显示
    if task_keyword:
        log(f"  📋 任务关键词: {task_keyword}")

    # AI智能判断网站类型
    site_type = classify_site(domain, context_hint=task_keyword)
    is_cn = site_type == 'cn'
    is_foreign = site_type == 'foreign'
    is_unknown = site_type == 'unknown'
    
    # 根据网站类型给出AI建议
    if is_cn:
        log(f"  🤖 AI判断: 国内网站 ({domain})")
        log(f"     策略: 优先直连，不走VPN")
    elif is_foreign:
        log(f"  🤖 AI判断: 国外网站 ({domain})")
        log(f"     策略: 需要VPN代理")
    else:
        log(f"  🤖 AI判断: 未知网站 ({domain})")
        log(f"     策略: 尝试直连，失败后使用VPN")
    
    # 定义不同的尝试策略
    strategies = []

    # ==================== AI策略选择 ====================
    
    # 场景1: 国内网站 → 优先直连
    if is_cn:
        log("  📡 优先尝试直连（国内网站）...")
        strategies.extend([
            ('直连+短等待', {'direct': True, 'wait': 3}),
            ('直连+中等待', {'direct': True, 'wait': 5}),
            ('直连+长等待', {'direct': True, 'wait': 10}),
        ])
        # 国内网站失败后不再尝试VPN（国内网站走VPN反而可能更慢）
        
    # 场景2: 国外网站 → 使用VPN
    elif is_foreign:
        recommended_region = suggest_vpn_region(site_type, domain)
        log(f"  🌐 推荐VPN节点: {VPN_REGIONS.get(recommended_region, '美国')}")
        
        if AUTO_VPN_SWITCH:
            strategies.extend([
                (f'VPN({recommended_region})+短等待', {'vpn': True, 'region': recommended_region, 'wait': 3}),
                (f'VPN({recommended_region})+中等待', {'vpn': True, 'region': recommended_region, 'wait': 5}),
                (f'VPN({recommended_region})+长等待', {'vpn': True, 'region': recommended_region, 'wait': 10}),
            ])
        else:
            # 记录VPN信号，等待手动切换
            need_vpn(url, 'foreign_site', f"国外网站需要VPN，推荐{recommended_region}节点", 
                     context=f"AI判断:{domain}需要VPN访问")
            log(f"  ⚠️ 自动VPN切换已禁用，请手动切换到 {VPN_REGIONS.get(recommended_region, '美国')} 节点后重试")
            # 仍然尝试基础策略
            strategies.extend([
                ('短等待', {'vpn': False, 'wait': 3}),
                ('中等待', {'vpn': False, 'wait': 5}),
            ])
            
    # 场景3: 未知网站 → 智能尝试
    else:  # is_unknown
        log("  🔀 未知网站，智能尝试...")
        if AUTO_DIRECT_FOR_CN and vpn_available:
            # 先尝试直连
            strategies.extend([
                ('直连+短等待', {'direct': True, 'wait': 3}),
                ('直连+中等待', {'direct': True, 'wait': 5}),
            ])
        
        # 未知网站也可以尝试VPN
        if AUTO_VPN_SWITCH and vpn_available:
            strategies.extend([
                ('VPN+短等待', {'vpn': True, 'wait': 3}),
                ('VPN+中等待', {'vpn': True, 'wait': 5}),
            ])
        elif vpn_available:
            # 记录信号
            need_vpn(url, 'unknown_site', "未知网站可能需要VPN", context=f"AI判断:{domain}未知")
            strategies.extend([
                ('短等待', {'vpn': False, 'wait': 3}),
                ('中等待', {'vpn': False, 'wait': 5}),
            ])

    # 尝试不同策略
    for strategy_name, params in strategies:
        try:
            log(f"  尝试 {strategy_name}...")

            # 仅在AUTO_VPN_SWITCH为True时才自动调用VPN
            if params.get('vpn') and vpn_available and AUTO_VPN_SWITCH:
                need_vpn(url, 'strategy_retry', f"策略{strategy_name}需要VPN", context=f"尝试{strategy_name}")

            cookie_dict = await get_cookies(url, force_direct=params.get('direct', False))
            wait_time = params.get('wait', 5)

            # 尝试下载
            result = await download_generic_page(url, output_path, cookie_dict,
                                               f"{parsed.scheme}://{parsed.netloc}/",
                                               extended_wait=wait_time,
                                               force_direct=params.get('direct', False))

            if result:
                strategy_desc = "直连" if params.get('direct') else strategy_name
                log(f"✅ {strategy_desc} 成功！")
                save_special_handler(parsed.netloc.replace('.', '_'), diagnosis_result)
                return True

        except Exception as e:
            log(f"    ✗ {strategy_name} 失败: {str(e)[:50]}")

        await asyncio.sleep(1)

    log("⚠️ 所有策略都尝试完毕")
    if is_cn and AUTO_DIRECT_FOR_CN and vpn_available:
        log("   提示: 访问国内网站失败，可尝试手动关闭VPN后重试")
    return False


def save_special_handler(site_name, diagnosis_result):
    """
    保存专用处理方法到代码和文档
    """
    skill_dir = Path(__file__).parent.parent
    web_access_file = Path(__file__)
    skill_md = skill_dir / "SKILL.md"

    # 1. 记录日志，说明需要手动添加专用方法
    log(f"📝 检测到新网站类型: {site_name}")
    log(f"   问题: {diagnosis_result.get('reason', '未知')}")
    log(f"   解决方案: {diagnosis_result.get('suggestion', '待确定')}")
    log(f"   需要手动添加专用处理方法")

    # 保存失败记录供后续处理
    pending_file = skill_dir / "pending_downloads.txt"
    try:
        with open(pending_file, 'a', encoding='utf-8') as f:
            f.write(f"\n# {site_name} - {diagnosis_result.get('reason', '未知')}\n")
            f.write(f"# 解决方案: {diagnosis_result.get('suggestion', '待确定')}\n")
            f.write(f"# 时间: {datetime.now()}\n")
    except:
        pass

    # 2. 更新 SKILL.md
    try:
        md_content = skill_md.read_text(encoding='utf-8')

        # 添加到已验证网站表格
        new_site = f"| **{site_name.upper()}** | ⭐ | 需要专用方法 |"

        if site_name.upper() not in md_content:
            md_content = md_content.replace(
                '| **CDE** | ✅ | 专用下载命令成功率最高 |',
                new_site + "\n| **CDE** | ✅ | 专用下载命令成功率最高 |"
            )
            skill_md.write_text(md_content, encoding='utf-8')
            log(f"✓ 已更新 SKILL.md 记录此网站")
    except Exception as e:
        log(f"⚠️ 更新SKILL.md失败: {e}")


def diagnose_and_suggest(url, domain, special_handler):
    """
    智能诊断：分析失败原因，给出建议
    """
    from urllib.parse import urlparse

    result = {
        'can_resolve': False,
        'reason': '未知',
        'suggestion': ''
    }

    parsed = urlparse(url)
    site_name = parsed.netloc

    # 检查常见问题
    issues = []

    # 1. 强反爬网站
    anti_crawl = ['who.int', 'ema.europa.eu', 'pmda.go.jp', 'healthcanada.gc.ca']
    if any(s in domain for s in anti_crawl):
        issues.append(('强反爬网站', '使用VPN+更长等待时间'))

    # 2. 需要登录
    if any(kw in url.lower() for kw in ['login', 'signin', 'account']):
        issues.append(('需要登录', '提供Cookie或使用已登录浏览器'))

    # 3. 政府网站
    if '.gov.' in domain:
        issues.append(('政府网站', '可能需要VPN切换IP'))

    # 4. 检查是否已添加专用方法
    if special_handler and special_handler.get('download_func'):
        issues.append(('专用方法存在但失败', '可能是网站结构变化'))

    # 生成结果
    if issues:
        issue_text = '; '.join([i[0] for i in issues])
        solution = issues[0][1]
        result['reason'] = issue_text
        result['suggestion'] = solution
        result['can_resolve'] = True
    else:
        result['reason'] = '未能确定具体原因'
        result['suggestion'] = '可能是网络问题或未知反爬机制'

    return result
    log(f"下载: {filename}")

    try:
        headers = {
            'User-Agent': random.choice(UA_POOL),
            'Referer': home_url,
        }
        # 使用系统代理，跟随重定向
        session = requests.Session()
        # 不禁用代理，保持系统设置
        r = session.get(url, headers=headers, cookies=cookie_dict, timeout=60, allow_redirects=True)

        if r.status_code == 200 and len(r.content) > 500:
            # 检查是否是HTML
            if r.content[:100].strip().startswith((b'<!DOCTYPE', b'<html', b'<!HTML', b'<!')):
                log(f"⚠ 返回HTML而非文件")
                return None

            with open(filepath, 'wb') as f:
                f.write(r.content)

            is_valid, msg = verify_pdf(str(filepath))
            if is_valid:
                log(f"✓ {filename} ({len(r.content)} bytes) - 下载成功")
            else:
                log(f"⚠ {filename} 下载完成: {msg}")
            log(f"文件保存在: {output_path}")
            return filepath
        else:
            log(f"✗ HTTP {r.status_code}")
    except Exception as e:
        log(f"✗ 下载失败: {e}")

    return None


async def direct_download(url, output_path, cookie_dict, home_url):
    """直接下载模式 - 直接下载已知文件URL"""
    import requests
    import os
    import re
    from urllib.parse import urlparse, unquote, urljoin
    
    # 从URL提取文件名
    parsed = urlparse(url)
    filename = unquote(parsed.path.split('/')[-1])
    if not filename or '.' not in filename:
        filename = "downloaded_file"
    
    # [优化] 保留完整文件名，只清理非法字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # 如果是医药类网站(CDE/FDA/NMPA)，尝试获取发布日期
    if is_pharma_site(url):
        try:
            import requests
            session = requests.Session()
            session.headers.update({'User-Agent': random.choice(UA_POOL)})
            
            # 尝试访问网站首页获取内容来匹配日期
            log(f"医药网站尝试获取发布日期...")
            
            # 对于CDE，尝试从新闻列表页获取相关日期
            if 'cde.org.cn' in url:
                # 尝试访问新闻列表页面
                search_urls = [
                    home_url + "main/news/listpage/1f78d372d351c6851af7431c7710286e",  # 指导原则
                    home_url + "main/news/listpage/3cc45b396497b598341ce3af000490e5",  # 工作动态
                ]
                
                for search_url in search_urls:
                    try:
                        resp = session.get(search_url, timeout=10)
                        if resp.status_code == 200:
                            text = resp.text
                            # 尝试匹配日期
                            import re
                            # 查找包含文件名的行中的日期
                            pattern = rf'(\d{{4}})[\s\-年]+(\d{{1,2}})[\s\-月]+(\d{{1,2}})[^\d].*{re.escape(filename[:20])}'
                            match = re.search(pattern, text)
                            if match:
                                publish_date = f"{match.group(1)}{match.group(2).zfill(2)}{match.group(3).zfill(2)}"
                                log(f"从列表页找到发布日期: {publish_date}")
                                filename = f"{publish_date} - {filename}"
                                break
                    except:
                        continue
                        
        except Exception as e:
            log(f"日期获取失败: {e}")

    # 确保输出目录存在
    os.makedirs(output_path, exist_ok=True)
    filepath = os.path.join(output_path, filename)

    log(f"直接下载: {filename}")

    try:
        headers = {
            'User-Agent': random.choice(UA_POOL),
            'Referer': home_url,
        }

        session = requests.Session()
        r = session.get(url, headers=headers, cookies=cookie_dict, timeout=60, allow_redirects=True)

        if r.status_code == 200 and len(r.content) > 500:
            # 检查是否是HTML
            if r.content[:100].strip().startswith((b'<!DOCTYPE', b'<html', b'<!HTML', b'<!')):
                log(f"⚠ 返回HTML而非文件")
                return None

            with open(filepath, 'wb') as f:
                f.write(r.content)

            # 验证文件
            is_valid, msg = verify_pdf(str(filepath))
            if is_valid:
                log(f"✅ 下载成功: {filepath}")
                return filepath
            else:
                log(f"⚠ 文件验证失败: {msg}")
                # 尝试重命名为正确扩展名
                if b'PK' in r.content[:10]:  # ZIP/Office格式
                    base, _ = os.path.splitext(filepath)
                    new_path = base + '.docx' if 'doc' not in base.lower() else base + '.zip'
                    os.rename(filepath, new_path)
                    log(f"✅ 下载成功(重命名): {new_path}")
                    return new_path
                return None
        else:
            log(f"✗ HTTP {r.status_code}")
    except Exception as e:
        log(f"✗ 下载失败: {e}")

    return None


async def download_generic_page(url, output_path, cookie_dict, home_url, extended_wait=3, force_direct=False):
    """页面模式 - 需要从页面中查找下载链接
    
    Args:
        url: 目标URL
        output_path: 输出目录
        cookie_dict: Cookie字典
        home_url: 首页URL
        extended_wait: 额外等待时间（秒）
        force_direct: True时禁用代理，强制直连
    """
    global REQUESTS_FORCE_DIRECT
    
    mode_desc = "直连" if force_direct else "VPN"
    log(f"  [{mode_desc}] 页面模式下载: {url}")
    
    # 设置全局变量，影响requests库
    if force_direct:
        REQUESTS_FORCE_DIRECT = True
    
    async with async_playwright() as p:
        # 构建浏览器启动参数
        browser_args = [
            '--disable-blink-features=AutomationControlled', 
            '--no-sandbox'
        ]
        
        # 如果是直连模式，禁用代理（真正的不走VPN）
        if force_direct:
            browser_args.extend([
                '--proxy-bypass-list=<-loopback>',  # 绕过代理列表，只代理loopback
                '--disable-extensions',
                '--disable-plugins',
            ])
        
        browser = await p.chromium.launch(
            headless=True,
            args=browser_args
        )
        
        # 如果是直连模式，明确设置不使用代理
        if force_direct:
            context = await browser.new_context(
                user_agent=random.choice(UA_POOL),
                proxy={'server': 'direct://'}  # 禁用代理，直连
            )
        else:
            context = await browser.new_context(
                user_agent=random.choice(UA_POOL)
            )
        page = await context.new_page()

        # 步骤1: [优化] 使用轻量级获取Cookie
        if not cookie_dict:
            log(f"  [{mode_desc}] 轻量级获取Cookie: {home_url}")
            try:
                cookie_dict = await get_cookie_light(context, home_url)
                log(f"  [{mode_desc}] 获取 {len(cookie_dict)} 个Cookies")
            except Exception as e:
                log(f"获取Cookie失败: {e}")

        # 步骤2: 访问目标页面
        log(f"访问目标页面: {url}")
        try:
            await page.goto(url, timeout=60000, wait_until='domcontentloaded')
            await asyncio.sleep(extended_wait)

            # 获取页面标题
            title = await page.title()
            log(f"页面标题: {title[:60]}")
        except Exception as e:
            log(f"访问目标页面失败: {e}")
            await browser.close()
            return

        # 步骤3: 查找PDF/下载链接
        pdf_links = await page.evaluate('''() => {
            const links = [];
            // 查找所有包含pdf/download/附件的链接
            const selectors = [
                'a[href$=".pdf"]',
                'a[href*="download"]',
                'a[href*="att"]',
                'a[href*="file"]',
                'a[href*="attachment"]'
            ];

            for (const sel of selectors) {
                document.querySelectorAll(sel).forEach(a => {
                    const text = a.textContent?.trim() || '';
                    const href = a.href || a.getAttribute('href') || '';
                    if (href && text && !href.includes('javascript')) {
                        links.push({ text: text, href: href });
                    }
                });
            }

            // 去重
            const seen = new Set();
            return links.filter(l => {
                const key = l.href.split('?')[0];
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }''')

        log(f"找到 {len(pdf_links)} 个可能的下行链接")

        if not pdf_links:
            log("未找到下载链接，尝试获取所有链接...")
            all_links = await page.evaluate('''() => {
                const links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const text = a.textContent?.trim() || '';
                    const href = a.href || '';
                    if (href && text.length > 5 && !href.includes('javascript') && !href.startsWith('#')) {
                        links.push({ text: text.substring(0, 50), href: href });
                    }
                });
                return links.slice(0, 20);
            }''')
            log(f"页面链接: {len(all_links)} 个")
            for link in all_links[:5]:
                log(f"  - {link['text']}: {link['href']}")
            await browser.close()
            return

        # 步骤4: 下载文件
        import requests

        for i, link in enumerate(pdf_links[:5], 1):
            href = link.get('href', '')
            if not href:
                continue

            # 构建完整URL
            if href.startswith('/'):
                full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
            elif href.startswith('http'):
                full_url = href
            else:
                continue

            # 生成文件名
            filename = link.get('text', '') or f"附件_{i}"
            # [优化] 保留完整文件名，只清理非法字符
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)

            # 如果是医药类网站，尝试添加日期前缀
            if is_pharma_site(url):
                # 从页面获取发布日期
                publish_date = await page.evaluate('''() => {
                    const bodyText = document.body.innerText || '';
                    const match = bodyText.match(/(\\d{4})[-年]?(\\d{1,2})[-月]?(\\d{1,2})/);
                    if (match) {
                        return match[1] + match[2].padStart(2, '0') + match[3].padStart(2, '0');
                    }
                    return '';
                }''')
                if publish_date:
                    filename = f"{publish_date} - {filename}"

            if not filename.lower().endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx')):
                filename += '.pdf'

            filepath = output_path / filename

            # 检查是否已有同名文件 - 如果有则跳过（不重复下载）
            if filepath.exists():
                log(f"  ⏭️ 已有同名文件，跳过下载: {filename}")
                continue

            log(f"[{i}/{len(pdf_links[:5])}] 下载: {filename}")

            # 尝试下载并验证（最多重试5次：前3次常规，后2次换方法）
            download_success = False
            retry_strategies = [
                ('常规', {}),
                ('常规', {}),
                ('常规', {}),
                ('换UA', {'change_ua': True}),
                ('换Cookie', {'change_cookie': True}),
            ]

            for download_attempt, (strategy_name, params) in enumerate(retry_strategies):
                try:
                    # 每次重试更换不同参数
                    headers = {
                        'User-Agent': random.choice(UA_POOL),
                        'Referer': home_url,
                    }

                    # 检查是否需要直连
                    if REQUESTS_FORCE_DIRECT:
                        session = requests.Session()
                        session.trust_env = False
                        log(f"  [{strategy_name}] 下载: {filename} (尝试 {download_attempt+1}/5) [直连]")
                        r = session.get(full_url, headers=headers, cookies=cookie_dict, timeout=60)
                    else:
                        log(f"  [{strategy_name}] 下载: {filename} (尝试 {download_attempt+1}/5)")
                        r = requests.get(full_url, headers=headers, cookies=cookie_dict, timeout=60)

                    if r.status_code == 200 and len(r.content) > 500:
                        # 检查是否是HTML
                        if r.content[:100].strip().startswith((b'<!DOCTYPE', b'<html', b'<!HTML', b'<!')):
                            if download_attempt < 4:
                                log(f"    ⚠ 返回HTML，重试 {download_attempt+2}/5...")
                                # 重新获取Cookie
                                cookie_dict = await get_cookies(url)
                                await asyncio.sleep(2)
                                continue
                            else:
                                log(f"    ⚠ 返回HTML而非文件，跳过")
                                break

                        with open(filepath, 'wb') as f:
                            f.write(r.content)

                        # 验证
                        is_valid, msg = verify_pdf(str(filepath))
                        if is_valid:
                            size = len(r.content)
                            log(f"  ✓ {filename} ({size} bytes) - 验证通过")
                            download_success = True
                            break
                        else:
                            log(f"    ⚠ 验证失败: {msg}，重试 {download_attempt+2}/5...")
                            filepath.unlink(missing_ok=True)
                            # 重新获取Cookie
                            cookie_dict = await get_cookies(url)
                            if download_attempt < 4:
                                await asyncio.sleep(2)
                    else:
                        log(f"  ✗ HTTP {r.status_code}, {len(r.content)} bytes")
                        break

                except Exception as e:
                    log(f"  ⚠ 下载错误: {e}，重试 {download_attempt+1}/3...")
                    if download_attempt < 2:
                        await asyncio.sleep(2)
                    else:
                        log(f"  ✗ 下载失败: {e}")

            if not download_success and filepath.exists():
                filepath.unlink(missing_ok=True)

        await browser.close()

    log(f"完成! 文件保存在: {output_path}")


async def main():
    print("=" * 50)
    print("web-access skill v1.6.5 (2026-03-20)")
    print("=" * 50)
    
    if len(sys.argv) < 3:
        print("使用方法:")
        print("  python web_access.py visit <url>        # 访问页面")
        print("  python web_access.py title <url>        # 获取标题")
        print("  python web_access.py links <url>       # 获取链接")
        print("  python web_access.py screenshot <url> # 截图")
        print("  python web_access.py pdf <url>         # 查找PDF链接")
        print("  python web_access.py download <url>    # 通用下载（自动获取Cookie）")
        print("  python web_access.py cde <关键词>       # 搜索下载CDE指导原则")
        print("  python web_access.py cde-date <日期>     # 按日期下载（自动查找该日期所有指导原则）")
        print("  python web_access.py cde-download <url> # 通过新闻URL下载CDE PDF附件")
        print("  python web_access.py fda <关键词>       # 下载FDA Guidance")
        print("  python web_access.py vpn status         # VPN状态")
        print("  python web_access.py vpn connect        # 连接VPN")
        print("  python web_access.py vpn rotate         # 切换VPN节点")
        print("  python web_access.py vpn signals        # 获取VPN信号（供AI决策）")
        print("  python web_access.py vpn clear          # 清空VPN信号")
        print("")
        print("示例:")
        print("  python web_access.py download 'https://www.fda.gov/media/xxx'     # 通用下载")
        print("  python web_access.py cde-download 'https://www.cde.org.cn/main/news/viewInfoCommon/2c071191f3a2ef45068b665e302fe494'")
        sys.exit(1)

    # 解析命令行参数
    action = sys.argv[1]
    arg = ""
    task_keyword = None
    
    # 支持 --keyword 或 -k 传入任务关键词
    if len(sys.argv) > 2:
        if sys.argv[2] in ["--keyword", "-k"]:
            if len(sys.argv) > 4:
                task_keyword = sys.argv[3]
                arg = sys.argv[4]
        else:
            arg = sys.argv[2]

    # VPN操作
    if action == "vpn":
        if arg == "status":
            print("VPN状态检查...")
            if check_vpn_available():
                print("✓ VPN控制可用")
            else:
                print("✗ VPN控制不可用")
        elif arg == "connect":
            connect_vpn()
        elif arg == "rotate" or arg == "random":  # 用户手动调用VPN
            vpn_script = get_vpn_script_path()
            if vpn_script:
                subprocess.run(["python3", vpn_script, "random"], timeout=60, capture_output=True)
                print("✓ VPN节点已切换（随机）")
            else:
                print("✗ 未找到VPN控制脚本")
        elif arg == "signals":
            # 输出VPN信号（供AI读取）
            signals = vpn_signal_manager.get_signals()
            if signals:
                print("📡 VPN信号列表:")
                for i, s in enumerate(signals, 1):
                    print(f"  [{i}] {s['domain']} | {s['error_type']} | 建议: {s['action']}")
            else:
                print("✓ 无VPN信号")
        elif arg == "clear":
            vpn_signal_manager.clear()
            print("✓ VPN信号已清空")
        return

    # 通用下载 - 适用于任何网站
    if action == "download":
        if not arg:
            print("错误: 请提供要下载的页面URL")
            print("示例: python web_access.py download 'https://www.fda.gov/media/xxx'")
            print("      python web_access.py download 'URL' --keyword '检查更新'")
            sys.exit(1)
        if not arg.startswith("http"):
            arg = "https://" + arg
        await download_generic(arg, task_keyword=task_keyword)
        return

    # CDE下载 - 搜索模式
    if action == "cde":
        if not arg:
            print("错误: 请提供搜索关键词")
            print("示例: python web_access.py cde '流感疫苗'")
            print("      python web_access.py cde '关键词' --keyword '检查更新'")
            sys.exit(1)
        await download_cde(arg, task_keyword=task_keyword)
        return

    # CDE下载 - 按日期下载（自动查找该日期所有指导原则）
    if action == "cde-date":
        if not arg:
            print("错误: 请提供日期")
            print("示例: python web_access.py cde-date '20260311'")
            print("      python web_access.py cde-date '3月11日'")
            print("      python web_access.py cde-date '20260311' --keyword '检查更新'")
            sys.exit(1)
        await download_cde_by_date(arg, task_keyword=task_keyword)
        return

    # CDE下载 - 通过URL直接下载附件
    if action == "cde-download":
        if not arg:
            print("错误: 请提供CDE新闻详情页URL")
            print("示例: python web_access.py cde-download 'https://www.cde.org.cn/main/news/viewInfoCommon/xxx'")
            print("      python web_access.py cde-download 'URL' --keyword '更新监测'")
            sys.exit(1)
        await download_cde_by_url(arg, task_keyword=task_keyword)
        return

    # FDA下载
    if action == "fda":
        await download_fda(arg, task_keyword=task_keyword)
        return

    # 网页访问
    url = arg
    if not url.startswith("http"):
        url = "https://" + url

    await visit_with_retry(url, action)

if __name__ == "__main__":
    asyncio.run(main())
