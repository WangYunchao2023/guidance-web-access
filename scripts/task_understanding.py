#!/usr/bin/env python3
"""
任务理解模块 - TaskUnderstanding
版本: 1.0.1 (2026-03-26)

功能：
1. AI理解用户任务，生成核心实体和关键词列表
2. 基于语义分析生成搜索变体
3. 制定过滤策略
4. 评估经验规则匹配度
"""

import re
from typing import Dict, List, Optional, Tuple

class TaskUnderstanding:
    """任务理解类"""
    
    def __init__(self):
        self.version = "1.0.1"
    
    def analyze(self, keyword: str) -> Dict:
        """
        分析用户任务
        
        输入: "中药注射剂相关的指导原则"
        输出: 任务理解结果字典
        """
        result = {
            "original": keyword,
            "core_task": keyword,
            "entities": [],           # 核心实体列表
            "compound_entity": "",     # 复合实体（如"中药注射剂"）
            "search_variants": [],     # 搜索变体
            "filter_criteria": [],     # 过滤条件
            "matched_override": None,  # 匹配的经验
            "search_plan": [],        # 搜索计划
            "confidence": 0.0
        }
        
        # 1. 提取核心实体
        entities, compound = self._extract_entities(keyword)
        result["entities"] = entities
        result["compound_entity"] = compound
        
        # 2. 生成搜索变体和过滤条件
        result["search_variants"], result["filter_criteria"] = self._generate_variants_and_filters(
            entities, compound
        )
        
        # 3. 生成搜索计划
        result["search_plan"] = self._generate_search_plan(
            result["search_variants"], 
            result["filter_criteria"]
        )
        
        # 4. 核心任务描述
        result["core_task"] = self._generate_core_task_description(entities, compound)
        
        return result
    
    def _extract_entities(self, keyword: str) -> Tuple[List[str], str]:
        """
        提取核心实体（基于语义理解，不使用预定义列表）
        
        策略：
        1. 移除通用词
        2. 识别复合词（如"中药注射剂"）
        3. 拆解复合词为独立实体
        
        返回: (独立实体列表, 复合实体)
        """
        # 通用词列表（这些不是核心实体）
        common_words = [
            '指导原则', '法规', '相关的', '有关', '技术指导原则',
            '管理办法', '试行', '征求意见稿', '通知', '公告',
            '通告', '申报资料', '研究技术', '一般原则', '基本要求',
            '药物', '药品', '产品', '注册', '审评', '研发', '申报',
            '安全性', '有效性'
        ]
        
        # 移除通用词
        text = keyword
        for word in common_words:
            text = re.sub(word, ' ', text)
        
        # 清理空白
        text = ' '.join(text.split()).strip()
        
        entities = []
        compound = ""
        
        if text:
            compound = text  # 完整复合词
            
            # 尝试拆解为独立实体
            # 方法：基于常见组合模式
            split_entities = self._split_compound(text)
            entities = [e for e in split_entities if len(e) >= 2]
            
            # 如果拆分失败，保留完整词
            if not entities:
                entities = [text]
        
        return entities, compound
    
    def _split_compound(self, text: str) -> List[str]:
        """
        拆分复合词为独立实体
        
        策略：
        1. 常见领域词组识别
        2. 字符级拆分尝试
        """
        # 领域术语词组
        domain_terms = [
            '中药', '化药', '生物制品', '疫苗', '抗体', '细胞', '基因',
            '注射剂', '口服', '外用', '制剂', '原料药',
            '沟通交流', '临床试验', '药代动力学', '生物等效性',
            '稳定性', '杂质', '质量标准', '生产工艺',
            '儿童用药', '老年用药', '孕妇用药'
        ]
        
        # 先尝试匹配已知词组
        matched = []
        remaining = text
        
        for term in domain_terms:
            if term in remaining:
                matched.append(term)
                remaining = remaining.replace(term, ' ')
        
        if matched:
            # 进一步拆分剩余字符
            for word in remaining.split():
                if len(word) >= 2:
                    matched.append(word)
            return matched
        
        # 如果没有匹配，返回字符级拆分
        return list(text)
    
    def _generate_variants_and_filters(self, entities: List[str], compound: str) -> Tuple[List[Dict], List[str]]:
        """
        生成搜索变体和过滤条件
        
        策略：
        1. 完整复合词作为第一搜索词（无需过滤）
        2. 单个实体作为搜索词时，用其他实体过滤
        3. 生成有意义的截短变体
        """
        variants = []
        filters = entities.copy()  # 过滤条件 = 所有独立实体
        
        # 1. 完整复合词（优先级最高，无需过滤）
        if compound:
            variants.append({
                "keyword": compound,
                "filter": None,
                "priority": 1
            })
        
        # 2. 如果有多个实体，生成交叉搜索+过滤
        if len(entities) >= 2:
            for i, entity in enumerate(entities):
                # 用当前实体搜索，用其他实体过滤
                other_entities = [e for j, e in enumerate(entities) if j != i]
                variants.append({
                    "keyword": entity,
                    "filter": other_entities,
                    "priority": len(variants) + 1
                })
        
        # 3. 如果只有一个实体，生成截短变体
        elif len(entities) == 1 and len(entities[0]) > 3:
            entity = entities[0]
            # 生成不同长度的前缀
            for length in [len(entity)-1, len(entity)-2]:
                if length >= 2:
                    partial = entity[:length]
                    variants.append({
                        "keyword": partial,
                        "filter": None,  # 截短词不用额外过滤
                        "priority": len(variants) + 1
                    })
        
        # 去重
        seen = set()
        unique_variants = []
        for v in variants:
            key = (v["keyword"], tuple(v["filter"]) if v["filter"] else None)
            if key not in seen:
                seen.add(key)
                unique_variants.append(v)
        
        return unique_variants, filters
    
    def _generate_search_plan(self, variants: List[Dict], filter_criteria: List[str]) -> List[Dict]:
        """
        生成搜索计划
        """
        plan = []
        for v in variants:
            filter_display = v["filter"] if v["filter"] else filter_criteria
            plan.append({
                "关键词": v["keyword"],
                "过滤条件": filter_display,
                "优先级": v["priority"]
            })
        return plan
    
    def _generate_core_task_description(self, entities: List[str], compound: str) -> str:
        """
        生成核心任务描述
        """
        if compound:
            return f"{compound}相关指导原则"
        elif entities:
            return f"{' + '.join(entities)}相关指导原则"
        else:
            return "未知主题指导原则"
    
    def evaluate_override_match(self, keyword: str, overrides: List[Dict]) -> Dict:
        """
        评估多个经验规则匹配度，选择最合适的
        """
        scored = []
        
        for override in overrides:
            pattern = override.get('task_pattern', '')
            
            if re.search(pattern, keyword):
                score = 50  # 基础分
                
                # 捕获组长度
                var_match = re.search(pattern, keyword)
                if var_match and var_match.lastindex:
                    var_len = len(var_match.group(1)) if var_match.lastindex >= 1 else 0
                    score += min(var_len, 20)
                
                # 模式复杂度
                complexity_bonus = pattern.count('(') * 5
                score += complexity_bonus
                
                # 方法明确性
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
        生成AI任务理解报告
        """
        lines = []
        lines.append("=" * 60)
        lines.append("🎯 AI任务理解报告")
        lines.append("=" * 60)
        lines.append(f"原始输入: {analysis_result['original']}")
        lines.append(f"核心任务: {analysis_result['core_task']}")
        lines.append(f"复合实体: {analysis_result['compound_entity']}")
        lines.append(f"独立实体: {analysis_result['entities']}")
        lines.append(f"过滤条件: {analysis_result['filter_criteria']}")
        lines.append("")
        lines.append("📋 搜索计划:")
        for i, plan in enumerate(analysis_result['search_plan'], 1):
            if i == 1:
                filter_str = " (完整匹配，无需过滤)"
            elif plan['过滤条件']:
                filter_str = f" + 过滤{plan['过滤条件']}"
            else:
                filter_str = ""
            lines.append(f"   {i}. \"{plan['关键词']}\"{filter_str}")
        
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
        "生物制品临床试验技术指导原则",
    ]
    
    for test in test_cases:
        print(f"\n{'='*60}")
        print(f"测试输入: {test}")
        result = tu.analyze(test)
        print(tu.generate_report(result))
