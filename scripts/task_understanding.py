#!/usr/bin/env python3
"""
任务理解模块 - TaskUnderstanding
版本: 1.1.0 (2026-03-26)

功能：
1. 调用 Gemini API 进行真正AI驱动的任务理解
2. 生成核心实体和关键词列表
3. 制定搜索+过滤策略
4. 评估经验规则匹配度
"""

import os
import json
import re
import urllib.request
import urllib.parse
from typing import Dict, List, Optional, Tuple

class TaskUnderstanding:
    """任务理解类 - AI驱动版本"""
    
    def __init__(self):
        self.version = "1.1.0"
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self.model = "gemini-2.0-flash"
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
    
    def analyze(self, keyword: str) -> Dict:
        """
        调用 Gemini API 进行任务理解
        
        输入: "中药注射剂相关的指导原则"
        输出: 任务理解结果字典
        """
        result = {
            "original": keyword,
            "core_task": keyword,
            "entities": [],
            "search_variants": [],
            "filter_criteria": [],
            "matched_override": None,
            "search_plan": [],
            "ai_reasoning": "",
            "confidence": 0.0,
            "error": None
        }
        
        # 调用AI理解任务
        prompt = self._build_prompt(keyword)
        ai_response = self._call_gemini(prompt)
        
        if ai_response:
            try:
                # 解析AI响应
                parsed = json.loads(ai_response)
                result["core_task"] = parsed.get("core_task", keyword)
                result["entities"] = parsed.get("entities", [])
                result["search_variants"] = parsed.get("search_variants", [])
                result["filter_criteria"] = parsed.get("filter_criteria", [])
                result["search_plan"] = parsed.get("search_plan", [])
                result["ai_reasoning"] = parsed.get("reasoning", "")
                result["confidence"] = parsed.get("confidence", 0.8)
            except json.JSONDecodeError:
                # 如果解析失败，回退到规则方式
                result["error"] = "AI响应解析失败"
                result = self._fallback_rule_based(keyword, result)
        else:
            # API调用失败，回退到规则方式
            result["error"] = "AI API调用失败"
            result = self._fallback_rule_based(keyword, result)
        
        return result
    
    def _build_prompt(self, keyword: str) -> str:
        """构建AI理解任务的Prompt"""
        return f"""你是一个专业的医药法规任务理解助手。请分析用户输入，提取关键信息。

用户输入: "{keyword}"

请分析：
1. 这是在找什么指导原则/法规？
2. 核心实体是什么（拆分为独立的关键词）？
3. 如何制定搜索策略？

请以JSON格式返回（只返回JSON，不要其他内容）：
{{
    "core_task": "核心任务描述",
    "entities": ["实体1", "实体2"],
    "search_variants": [
        {{"keyword": "完整关键词", "filter": [], "priority": 1}},
        {{"keyword": "关键词1", "filter": ["其他实体"], "priority": 2}}
    ],
    "filter_criteria": ["过滤条件1", "过滤条件2"],
    "reasoning": "你的理解过程说明",
    "confidence": 0.9
}}

示例：
输入: "中药注射剂相关的指导原则"
输出: {{
    "core_task": "中药注射剂相关指导原则",
    "entities": ["中药", "注射剂"],
    "search_variants": [
        {{"keyword": "中药注射剂", "filter": [], "priority": 1}},
        {{"keyword": "中药", "filter": ["注射剂"], "priority": 2}},
        {{"keyword": "注射剂", "filter": ["中药"], "priority": 3}}
    ],
    "filter_criteria": ["中药", "注射剂"],
    "reasoning": "将'中药注射剂'理解为'中药'+'注射剂'两个独立实体，搜索时可用单个实体配合其他实体过滤",
    "confidence": 0.95
}}"""
    
    def _call_gemini(self, prompt: str) -> Optional[str]:
        """调用Gemini API"""
        if not self.api_key:
            return None
        
        try:
            url = f"{self.api_url}?key={self.api_key}"
            data = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 2048
                }
            }
            
            json_data = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=json_data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                
                # 提取AI响应文本
                if 'candidates' in result and len(result['candidates']) > 0:
                    candidate = result['candidates'][0]
                    if 'content' in candidate and 'parts' in candidate['content']:
                        return candidate['content']['parts'][0]['text']
            
            return None
            
        except Exception as e:
            print(f"Gemini API调用失败: {e}")
            return None
    
    def _fallback_rule_based(self, keyword: str, result: Dict) -> Dict:
        """回退到规则方式（当AI调用失败时）"""
        # 简单规则提取
        common_words = [
            '指导原则', '法规', '相关的', '有关', '技术指导原则',
            '管理办法', '试行', '征求意见稿', '通知', '公告',
            '通告', '申报资料', '研究技术', '一般原则', '基本要求',
            '安全性', '有效性'
        ]
        
        text = keyword
        for word in common_words:
            text = text.replace(word, ' ')
        text = ' '.join(text.split()).strip()
        
        if text:
            result["entities"] = [text]
            result["compound_entity"] = text
            result["search_variants"] = [
                {"keyword": text, "filter": [], "priority": 1}
            ]
            result["filter_criteria"] = [text]
            result["search_plan"] = [
                {"关键词": text, "过滤条件": [], "优先级": 1}
            ]
            result["core_task"] = f"{text}相关指导原则"
        
        result["ai_reasoning"] = "[回退规则方式] AI不可用，使用简化规则"
        
        return result
    
    def evaluate_override_match(self, keyword: str, overrides: List[Dict]) -> Dict:
        """
        评估多个经验规则匹配度
        """
        scored = []
        
        for override in overrides:
            pattern = override.get('task_pattern', '')
            
            if re.search(pattern, keyword):
                score = 50
                
                var_match = re.search(pattern, keyword)
                if var_match and var_match.lastindex:
                    var_len = len(var_match.group(1)) if var_match.lastindex >= 1 else 0
                    score += min(var_len, 20)
                
                complexity_bonus = pattern.count('(') * 5
                score += complexity_bonus
                
                if override.get('method'):
                    score += 10
                
                scored.append({
                    "override": override,
                    "score": score,
                    "matched_var": var_match.group(1) if var_match and var_match.lastindex else None
                })
        
        if not scored:
            return {"override": None, "score": 0, "matched_var": None}
        
        best = max(scored, key=lambda x: x["score"])
        return best
    
    def generate_report(self, analysis_result: Dict) -> str:
        """
        生成人类可读的任务理解报告
        """
        lines = []
        lines.append("=" * 60)
        lines.append("🎯 AI任务理解报告")
        lines.append("=" * 60)
        lines.append(f"原始输入: {analysis_result['original']}")
        lines.append(f"核心任务: {analysis_result['core_task']}")
        lines.append(f"实体: {analysis_result['entities']}")
        lines.append(f"过滤条件: {analysis_result['filter_criteria']}")
        
        if analysis_result.get('ai_reasoning'):
            lines.append("")
            lines.append(f"💭 AI推理: {analysis_result['ai_reasoning']}")
        
        lines.append("")
        lines.append("📋 搜索计划:")
        for i, plan in enumerate(analysis_result.get('search_plan', []), 1):
            kw = plan.get('关键词', '')
            filters = plan.get('过滤条件', [])
            if i == 1:
                filter_str = " (完整匹配)"
            elif filters:
                filter_str = f" + 过滤{filters}"
            else:
                filter_str = ""
            lines.append(f"   {i}. \"{kw}\"{filter_str}")
        
        if analysis_result.get('error'):
            lines.append("")
            lines.append(f"⚠️ 注意: {analysis_result['error']}")
        
        if analysis_result.get('matched_override'):
            override = analysis_result['matched_override']
            lines.append("")
            lines.append(f"📌 匹配经验: {override.get('note', override.get('task_pattern', ''))}")
            lines.append(f"   执行方式: {override.get('method', 'both')}")
        
        lines.append("=" * 60)
        return "\n".join(lines)


# 测试
if __name__ == "__main__":
    tu = TaskUnderstanding()
    
    test_cases = [
        "中药注射剂相关的指导原则",
        "化药稳定性指导原则",
        "沟通交流相关的指导原则",
        "纳米药物递送系统相关的指导原则",  # 新领域测试
    ]
    
    for test in test_cases:
        print(f"\n{'='*60}")
        print(f"测试输入: {test}")
        result = tu.analyze(test)
        print(tu.generate_report(result))
