# -*- coding: utf-8 -*-
"""
降 AI 检测模块。
"""

import re

from modules.knowledge_base import append_knowledge_context
from modules.prompt_center import PromptCenter
from modules.report_importer import ParagraphAnnotation, split_document_paragraphs


class AIReducer:
    """降低 AI 检测率并提供轻量文本分析。"""

    AI_PATTERNS = [
        r'首先.*其次.*最后',
        r'综上所述',
        r'值得注意的是',
        r'不可否认',
        r'毋庸置疑',
        r'总而言之',
        r'由此可见',
        r'显而易见',
        r'众所周知',
        r'不言而喻',
        r'此外.*同时.*另外',
    ]

    FLOW_CONNECTORS = (
        '因此', '然而', '同时', '此外', '另外', '由此可见', '综上', '进一步说', '相较之下', '具体而言',
    )

    CONCLUSION_MARKERS = ('综上', '总体来看', '由此可见', '总之', '可以看出', '从上述分析可知')

    def __init__(self, api_client, prompt_center=None):
        self.api = api_client
        self.prompt_center = prompt_center or PromptCenter(getattr(api_client, 'config', None))

    @staticmethod
    def _usage_context(action):
        return {
            'page_id': 'ai_reduce',
            'scene_id': 'ai_reduce.transform',
            'action': action,
        }

    def scan_ai_features(self, text: str) -> dict:
        """扫描常见 AI 写作痕迹。"""
        results = {
            'score': 0,
            'features': [],
            'sentences_flagged': [],
        }

        for pattern in self.AI_PATTERNS:
            matches = re.findall(pattern, text)
            if matches:
                results['features'].append(f'发现高频模板表达：{pattern[:20]}')
                results['score'] += 5

        sentences = [s.strip() for s in re.split(r'[。！？?!]', text) if len(s.strip()) > 5]
        if sentences:
            lengths = [len(s) for s in sentences]
            avg_len = sum(lengths) / len(lengths)
            variance = sum((length - avg_len) ** 2 for length in lengths) / len(lengths)
            if variance < 100 and len(sentences) > 5:
                results['features'].append('句子长度分布过于均匀，存在模板化生成倾向')
                results['score'] += 10

        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
        if len(paragraphs) > 3:
            para_lengths = [len(p) for p in paragraphs]
            avg_length = sum(para_lengths) / len(para_lengths)
            if avg_length and all(abs(length - avg_length) < avg_length * 0.3 for length in para_lengths):
                results['features'].append('段落长度过于整齐，存在统一模板痕迹')
                results['score'] += 8

        connector_count = sum(text.count(connector) for connector in self.FLOW_CONNECTORS)
        if connector_count > len(sentences) * 0.4 and sentences:
            results['features'].append(f'连接词使用偏密集，共出现 {connector_count} 次')
            results['score'] += 8

        ai_words = ['综上所述', '不可否认', '毋庸置疑', '显而易见', '众所周知', '值得注意的是']
        for sentence in sentences[:20]:
            if any(word in sentence for word in ai_words):
                results['sentences_flagged'].append(sentence[:60] + '...' if len(sentence) > 60 else sentence)

        results['score'] = min(100, results['score'])
        results['risk_level'] = (
            '高风险' if results['score'] >= 30 else
            '中风险' if results['score'] >= 15 else
            '低风险'
        )
        return results

    def check_logic_flow(self, text: str) -> dict:
        """检查段落衔接与论证闭环。"""
        paragraphs = [p.strip() for p in re.split(r'\n+', text) if p.strip()]
        sentences = [s.strip() for s in re.split(r'[。！？?!]', text) if len(s.strip()) > 4]

        issues = []
        focus_segments = []

        long_sentences = [sentence for sentence in sentences if len(sentence) >= 70]
        if long_sentences:
            issues.append(f'发现 {len(long_sentences)} 句超过 70 字的长句，容易产生逻辑跳跃或信息堆叠。')
            focus_segments.extend(long_sentences[:2])

        connector_starts = []
        for sentence in sentences[:10]:
            matched = next((connector for connector in self.FLOW_CONNECTORS if sentence.startswith(connector)), '')
            if matched:
                connector_starts.append(matched)
        if len(connector_starts) >= 3 and len(set(connector_starts)) == 1:
            issues.append('多句连续使用相同衔接词开头，论证推进方式较为模板化。')

        weak_links = []
        for index in range(max(len(paragraphs) - 1, 0)):
            score = self._paragraph_link_score(paragraphs[index], paragraphs[index + 1])
            if score < 0.06:
                weak_links.append((index, score))
        if weak_links:
            issues.extend(
                f'第 {index + 1} 段与第 {index + 2} 段衔接偏弱，过渡不够自然。'
                for index, _score in weak_links[:2]
            )
            focus_segments.extend(paragraphs[index + 1][:80] for index, _score in weak_links[:2])

        transition_hits = sum(text.count(connector) for connector in self.FLOW_CONNECTORS)
        transition_rate = round(transition_hits / max(len(sentences), 1), 2)
        if len(sentences) >= 6 and transition_rate < 0.08:
            issues.append('跨句过渡词偏少，段内承接关系可能不够清晰。')

        if len(paragraphs) >= 3 and not any(marker in paragraphs[-1] for marker in self.CONCLUSION_MARKERS):
            issues.append('结尾段缺少明显收束句，论证闭环略弱。')

        flow_score = 100
        flow_score -= min(len(long_sentences) * 6, 24)
        flow_score -= max(0, len(issues) - 1) * 10
        flow_score = max(0, min(100, flow_score))

        return {
            'flow_score': flow_score,
            'paragraph_count': len(paragraphs),
            'sentence_count': len(sentences),
            'transition_hits': transition_hits,
            'transition_rate': transition_rate,
            'issues': issues[:6],
            'focus_segments': [segment[:80] + '...' if len(segment) > 80 else segment for segment in focus_segments[:4]],
            'long_sentence_count': len(long_sentences),
        }

    def _render_rewrite_prompt(self, text, mode, mode_label, knowledge_context=None):
        rendered = self.prompt_center.render_scene(
            'ai_reduce.transform',
            {
                'text': text,
                'mode': mode,
                'mode_label': mode_label,
            },
        )
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return rendered['system'], prompt

    def rewrite_light(self, text: str, knowledge_context=None) -> str:
        """轻度去痕。"""
        system, prompt = self._render_rewrite_prompt(text, 'light', '轻度去痕', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.75,
            usage_context=self._usage_context('rewrite_light'),
        )

    def rewrite_deep(self, text: str, knowledge_context=None) -> str:
        """深度重构。"""
        system, prompt = self._render_rewrite_prompt(text, 'deep', '深度重构', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.85,
            usage_context=self._usage_context('rewrite_deep'),
        )

    def rewrite_academic(self, text: str, knowledge_context=None) -> str:
        """学术拟合。"""
        system, prompt = self._render_rewrite_prompt(text, 'academic', '学术拟合', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.8,
            usage_context=self._usage_context('rewrite_academic'),
        )

    def rewrite_with_annotations(self, text: str, annotations: list[ParagraphAnnotation], mode: str, knowledge_context=None) -> str:
        """仅改写被标注且纳入执行的正文段落。"""
        paragraph_map = {item.paragraph_id: item for item in annotations or []}
        parts = []
        last_end = 0
        for paragraph in split_document_paragraphs(text):
            parts.append(text[last_end:paragraph.start])
            annotation = paragraph_map.get(paragraph.paragraph_id)
            updated_text = paragraph.text
            if paragraph.kind == 'body' and annotation and annotation.include_in_run and annotation.risk_level != 'safe':
                updated_text = self._rewrite_by_mode(paragraph.text, mode, knowledge_context=knowledge_context)
                if not self._preserves_citation_marks(paragraph.text, updated_text):
                    updated_text = paragraph.text
                if not str(updated_text or '').strip():
                    updated_text = paragraph.text
            parts.append(updated_text)
            last_end = paragraph.end
        parts.append(text[last_end:])
        return ''.join(parts)

    @staticmethod
    def _paragraph_link_score(left: str, right: str) -> float:
        left_grams = AIReducer._char_bigrams(left)
        right_grams = AIReducer._char_bigrams(right)
        if not left_grams or not right_grams:
            return 0.0
        overlap = left_grams & right_grams
        union = left_grams | right_grams
        return len(overlap) / max(len(union), 1)

    @staticmethod
    def _char_bigrams(text: str) -> set:
        cleaned = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', text or '')
        if len(cleaned) < 2:
            return {cleaned} if cleaned else set()
        return {cleaned[index:index + 2] for index in range(len(cleaned) - 1)}

    def _rewrite_by_mode(self, text: str, mode: str, knowledge_context=None) -> str:
        if mode == 'light':
            return self.rewrite_light(text, knowledge_context=knowledge_context)
        if mode == 'deep':
            return self.rewrite_deep(text, knowledge_context=knowledge_context)
        return self.rewrite_academic(text, knowledge_context=knowledge_context)

    @staticmethod
    def _preserves_citation_marks(source_text: str, result_text: str) -> bool:
        required_marks = set(re.findall(r'\[\d+\]', source_text or ''))
        if not required_marks:
            return True
        current_marks = set(re.findall(r'\[\d+\]', result_text or ''))
        return required_marks.issubset(current_marks)
