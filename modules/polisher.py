# -*- coding: utf-8 -*-
"""
学术润色模块。
"""

from modules.knowledge_base import append_knowledge_context
from modules.prompt_center import PromptCenter


class AcademicPolisher:
    """学术论文润色。"""

    TEMPERATURE_MAP = {
        '标准模式': 0.4,
        '学术强化': 0.45,
        '结构重组': 0.55,
        '精炼压缩': 0.35,
    }

    def __init__(self, api_client, prompt_center=None):
        self.api = api_client
        self.prompt_center = prompt_center or PromptCenter(getattr(api_client, 'config', None))

    @staticmethod
    def _usage_context(action, scene_id='polish.run_task'):
        return {
            'page_id': 'polish',
            'scene_id': scene_id,
            'action': action,
        }

    def run_task(
        self,
        text: str,
        task_type: str = '章节正文',
        polish_type: str = 'full',
        execution_mode: str = '标准模式',
        topic: str = '',
        notes: str = '',
        knowledge_context=None,
    ) -> str:
        """统一任务入口。"""
        text = (text or '').strip()
        if not text:
            raise ValueError('待处理文本不能为空')

        task_type = task_type or '章节正文'
        polish_type = polish_type or 'full'
        execution_mode = execution_mode or '标准模式'
        topic = (topic or '').strip()
        notes = (notes or '').strip()

        rendered = self.prompt_center.render_scene(
            'polish.run_task',
            {
                'text': text,
                'task_type': task_type,
                'polish_type': polish_type,
                'execution_mode': execution_mode,
                'topic': topic,
                'notes': notes,
            },
        )
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        temperature = self.TEMPERATURE_MAP.get(execution_mode, 0.4)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=temperature,
            usage_context=self._usage_context('run_task'),
        )

    def polish_grammar(self, text: str, knowledge_context=None) -> str:
        """语法和标点修正。"""
        rendered = self.prompt_center.render_scene('polish.grammar', {'text': text})
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=0.3,
            usage_context=self._usage_context('polish_grammar', scene_id='polish.grammar'),
        )

    def polish_academic_vocab(self, text: str, knowledge_context=None) -> str:
        """学术词汇替换。"""
        rendered = self.prompt_center.render_scene('polish.academic_vocab', {'text': text})
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=0.4,
            usage_context=self._usage_context('polish_academic_vocab', scene_id='polish.academic_vocab'),
        )

    def polish_logic(self, text: str, knowledge_context=None) -> str:
        """逻辑和段落优化。"""
        rendered = self.prompt_center.render_scene('polish.logic', {'text': text})
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=0.5,
            usage_context=self._usage_context('polish_logic', scene_id='polish.logic'),
        )

    def polish_full(self, text: str, knowledge_context=None) -> str:
        """全面润色。"""
        rendered = self.prompt_center.render_scene('polish.full', {'text': text})
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=0.5,
            usage_context=self._usage_context('polish_full', scene_id='polish.full'),
        )

    def translate_polish(self, text: str, target_lang: str = '英文', knowledge_context=None) -> str:
        """翻译润色。"""
        rendered = self.prompt_center.render_scene(
            'polish.translate',
            {
                'text': text,
                'target_lang': target_lang,
            },
        )
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        return self.api.call_sync(
            prompt,
            rendered['system'],
            temperature=0.4,
            usage_context=self._usage_context('translate_polish', scene_id='polish.translate'),
        )

    def check_format(self, text: str, style: str = '学术论文') -> dict:
        """格式规范检查。"""
        import re

        issues = []

        if ',' in text and '，' not in text:
            issues.append('建议使用中文逗号（，）替代英文逗号（,）。')
        if '.' in text.replace('...', '') and '。' not in text:
            issues.append('建议使用中文句号（。）替代英文句号（.）。')

        cn_nums = re.findall(r'[一二三四五六七八九十百千万]+', text)
        if cn_nums:
            issues.append(f'发现 {len(cn_nums)} 处中文数字，学术论文建议优先使用阿拉伯数字。')

        paragraphs = [p for p in text.split('\n') if len(p.strip()) > 0]
        short_paras = [p for p in paragraphs if 0 < len(p.strip()) < 50]
        if short_paras:
            issues.append(f'发现 {len(short_paras)} 个过短段落，建议合并或扩充。')

        has_ref = bool(re.search(r'\[\d+\]', text))
        if not has_ref and len(text) > 500:
            issues.append('未发现参考文献引用标记，建议补充文献引用。')

        return {
            'issues': issues,
            'issue_count': len(issues),
            'word_count': len(text),
            'para_count': len(paragraphs),
            'sentence_count': len(re.split(r'[。！？?!]', text)),
        }
