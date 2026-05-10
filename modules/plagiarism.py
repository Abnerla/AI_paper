# -*- coding: utf-8 -*-
"""
降查重模块。
"""

import difflib
import re

from modules.knowledge_base import append_knowledge_context
from modules.prompt_center import PromptCenter
from modules.report_importer import ParagraphAnnotation, split_document_paragraphs


class PlagiarismReducer:
    """降低论文查重率并模拟重复风险。"""

    def __init__(self, api_client, prompt_center=None):
        self.api = api_client
        self.prompt_center = prompt_center or PromptCenter(getattr(api_client, 'config', None))

    @staticmethod
    def _usage_context(action):
        return {
            'page_id': 'plagiarism',
            'scene_id': 'plagiarism.transform',
            'action': action,
        }

    def detect_repetitive(self, text: str) -> dict:
        """本地检测文本内部的重复风险。"""
        results = {
            'repeated_phrases': [],
            'long_sentences': [],
            'risk_paragraphs': [],
        }

        words = re.findall(r'[\u4e00-\u9fff]{4,}', text)
        seen = {}
        for word in words:
            seen[word] = seen.get(word, 0) + 1

        repeated = [(word, count) for word, count in seen.items() if count >= 3]
        repeated.sort(key=lambda item: (-item[1], -len(item[0])))
        results['repeated_phrases'] = repeated[:20]

        sentences = re.split(r'[。！？?!]', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 100:
                results['long_sentences'].append(sentence[:80] + '...' if len(sentence) > 80 else sentence)

        paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]
        for paragraph in paragraphs:
            repeat_count = sum(paragraph.count(word) for word, _count in repeated[:5])
            if repeat_count > 3:
                results['risk_paragraphs'].append(paragraph[:100] + '...' if len(paragraph) > 100 else paragraph)

        return results

    def simulate_repeat_risk(self, text: str, source_text: str = '') -> dict:
        """结合源文本估算重复风险。"""
        local = self.detect_repetitive(text)
        source_text = (source_text or '').strip()

        similarity = self.compare_similarity(source_text, text) if source_text else {
            'similarity': 0.0,
            'common_words': [],
            'unique_in_1': 0,
            'unique_in_2': 0,
        }

        matched_fragments = []
        matched_chars = 0
        if source_text:
            matcher = difflib.SequenceMatcher(None, source_text, text)
            for block in matcher.get_matching_blocks():
                if block.size < 8:
                    continue
                fragment = text[block.b:block.b + block.size].strip()
                if len(fragment) < 6:
                    continue
                matched_chars += block.size
                matched_fragments.append(fragment[:60] + '...' if len(fragment) > 60 else fragment)
            matched_fragments = self._dedupe_keep_order(matched_fragments)[:6]

        source_overlap = round(matched_chars / max(len(text), 1) * 100, 1) if source_text else 0.0
        local_risk = min(100.0, len(local['repeated_phrases']) * 5 + len(local['long_sentences']) * 6 + len(local['risk_paragraphs']) * 10)

        if source_text:
            simulated_rate = round(min(100.0, similarity['similarity'] * 0.45 + source_overlap * 0.55), 1)
        else:
            simulated_rate = round(min(100.0, local_risk * 0.9), 1)

        risk_level = (
            '高风险' if simulated_rate >= 35 else
            '中风险' if simulated_rate >= 18 else
            '低风险'
        )

        return {
            'simulated_rate': simulated_rate,
            'risk_level': risk_level,
            'repeated_phrases': local['repeated_phrases'],
            'long_sentences': local['long_sentences'],
            'risk_paragraphs': local['risk_paragraphs'],
            'matched_fragments': matched_fragments,
            'source_overlap': source_overlap,
            'token_similarity': similarity['similarity'],
        }

    def check_citation_format(self, text: str) -> dict:
        """检查正文引用与参考文献的对应关系。"""
        content = str(text or '')
        section_match = re.search(r'(参考文献|引用文献|参考资料)\s*[:：]?', content)
        body_text = content[:section_match.start()] if section_match else content
        reference_text = content[section_match.end():] if section_match else ''

        citation_numbers = sorted({int(num) for num in re.findall(r'\[(\d+)\]', body_text)})
        reference_numbers = sorted({int(num) for num in re.findall(r'^\s*\[(\d+)\]', reference_text, flags=re.M)})
        author_year_marks = re.findall(r'[（(][^()（）]{1,20}[,，]\s*(?:19|20)\d{2}[a-z]?[）)]', body_text)

        issues = []
        missing_references = []
        unused_references = []

        if len(body_text.strip()) > 300 and not citation_numbers and not author_year_marks:
            issues.append('正文暂未发现引用标记，查重时可能因引用缺失而被整体判重。')

        if citation_numbers and not section_match:
            issues.append('正文已有引用编号，但未发现参考文献列表。')

        if section_match and not citation_numbers and not author_year_marks:
            issues.append('末尾存在参考文献区，但正文未见对应引用标记。')

        if section_match and not reference_numbers and not re.search(r'^\s*\d+[\.、]', reference_text, flags=re.M):
            issues.append('参考文献区缺少清晰编号格式，建议统一为 [1] 或 1. 的条目样式。')

        if citation_numbers and reference_numbers:
            missing_references = [num for num in citation_numbers if num not in reference_numbers]
            unused_references = [num for num in reference_numbers if num not in citation_numbers]
            if missing_references:
                issues.append('正文引用编号缺少对应参考文献条目：' + '、'.join(str(num) for num in missing_references[:8]))
            if unused_references:
                issues.append('参考文献列表存在未在正文出现的编号：' + '、'.join(str(num) for num in unused_references[:8]))

            expected = list(range(reference_numbers[0], reference_numbers[-1] + 1))
            if reference_numbers != expected:
                issues.append('参考文献编号不连续，建议重新核对排序。')

        return {
            'citation_count': len(citation_numbers),
            'reference_count': len(reference_numbers),
            'author_year_count': len(author_year_marks),
            'issues': issues,
            'missing_references': missing_references,
            'unused_references': unused_references,
            'has_reference_section': bool(section_match),
        }

    def _render_reduce_prompt(self, text, source_text, mode, mode_label, knowledge_context=None):
        rendered = self.prompt_center.render_scene(
            'plagiarism.transform',
            {
                'text': text,
                'source_text': source_text,
                'mode': mode,
                'mode_label': mode_label,
            },
        )
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return rendered['system'], prompt

    def reduce_light(self, text: str, source_text: str = '', knowledge_context=None) -> str:
        """轻度降重。"""
        system, prompt = self._render_reduce_prompt(text, source_text, 'light', '轻度降重', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.72,
            usage_context=self._usage_context('reduce_light'),
        )

    def reduce_medium(self, text: str, source_text: str = '', knowledge_context=None) -> str:
        """中度降重。"""
        system, prompt = self._render_reduce_prompt(text, source_text, 'medium', '中度降重', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.78,
            usage_context=self._usage_context('reduce_medium'),
        )

    def reduce_deep(self, text: str, source_text: str = '', knowledge_context=None) -> str:
        """深度降重。"""
        system, prompt = self._render_reduce_prompt(text, source_text, 'deep', '深度降重', knowledge_context)
        return self.api.call_sync(
            prompt,
            system,
            temperature=0.84,
            usage_context=self._usage_context('reduce_deep'),
        )

    def reduce_with_annotations(
        self,
        text: str,
        annotations: list[ParagraphAnnotation],
        mode: str,
        source_text: str = '',
        knowledge_context=None,
    ) -> str:
        """仅处理被标注且纳入执行的正文段落。"""
        paragraph_map = {item.paragraph_id: item for item in annotations or []}
        global_source_text = str(source_text or '').strip()
        parts = []
        last_end = 0
        for paragraph in split_document_paragraphs(text):
            parts.append(text[last_end:paragraph.start])
            annotation = paragraph_map.get(paragraph.paragraph_id)
            updated_text = paragraph.text
            if paragraph.kind == 'body' and annotation and annotation.include_in_run and annotation.risk_level != 'safe':
                source_excerpt = annotation.source_excerpt or ''
                local_start = max(0, int(annotation.start or paragraph.start) - paragraph.start)
                local_end = max(local_start, int(annotation.end or paragraph.end) - paragraph.start)
                can_reduce_partial = (
                    paragraph.start <= int(annotation.start or paragraph.start) < int(annotation.end or paragraph.end) <= paragraph.end
                    and 0 <= local_start < local_end <= len(paragraph.text)
                    and (local_end - local_start) < len(paragraph.text)
                )
                if can_reduce_partial:
                    focus_text = paragraph.text[local_start:local_end]
                    rewritten_focus = self._reduce_by_mode(
                        focus_text,
                        source_excerpt or focus_text,
                        mode,
                        knowledge_context=knowledge_context,
                    )
                    if self._preserves_citation_marks(focus_text, rewritten_focus) and str(rewritten_focus or '').strip():
                        updated_text = paragraph.text[:local_start] + rewritten_focus + paragraph.text[local_end:]
                else:
                    updated_text = self._reduce_by_mode(
                        paragraph.text,
                        source_excerpt or global_source_text,
                        mode,
                        knowledge_context=knowledge_context,
                    )
                    if not self._preserves_citation_marks(paragraph.text, updated_text):
                        updated_text = paragraph.text
                    if not str(updated_text or '').strip():
                        updated_text = paragraph.text
            parts.append(updated_text)
            last_end = paragraph.end
        parts.append(text[last_end:])
        return ''.join(parts)

    def compare_similarity(self, text1: str, text2: str) -> dict:
        """对比两段文本的词汇相似度。"""
        words1 = set(re.findall(r'[\u4e00-\u9fff]+|[A-Za-z]+', text1 or ''))
        words2 = set(re.findall(r'[\u4e00-\u9fff]+|[A-Za-z]+', text2 or ''))
        if not words1 or not words2:
            return {
                'similarity': 0.0,
                'common_words': [],
                'unique_in_1': len(words1),
                'unique_in_2': len(words2),
            }

        common = words1 & words2
        similarity = len(common) / max(len(words1), len(words2)) * 100
        return {
            'similarity': round(similarity, 1),
            'common_words': list(common)[:20],
            'unique_in_1': len(words1 - words2),
            'unique_in_2': len(words2 - words1),
        }

    @staticmethod
    def _dedupe_keep_order(items):
        seen = set()
        result = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    def _reduce_by_mode(self, text: str, source_text: str, mode: str, knowledge_context=None) -> str:
        if mode == 'light':
            return self.reduce_light(text, source_text, knowledge_context=knowledge_context)
        if mode == 'medium':
            return self.reduce_medium(text, source_text, knowledge_context=knowledge_context)
        return self.reduce_deep(text, source_text, knowledge_context=knowledge_context)

    @staticmethod
    def _preserves_citation_marks(source_text: str, result_text: str) -> bool:
        required_marks = set(re.findall(r'\[\d+\]', source_text or ''))
        if not required_marks:
            return True
        current_marks = set(re.findall(r'\[\d+\]', result_text or ''))
        return required_marks.issubset(current_marks)
