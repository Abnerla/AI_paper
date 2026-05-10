# -*- coding: utf-8 -*-
"""
论文写作模块。
"""

import json

from modules.prompt_center import PromptCenter


class PaperWriter:
    SECTION_MAX_TOKENS = 3000

    def __init__(self, api_client, prompt_center=None):
        self.api = api_client
        self.prompt_center = prompt_center or PromptCenter(getattr(api_client, 'config', None))

    @staticmethod
    def _usage_context(scene_id='', action=''):
        return {
            'page_id': 'paper_write',
            'scene_id': scene_id,
            'action': action,
        }

    def _render_scene(self, scene_id, values):
        rendered = self.prompt_center.render_scene(scene_id, values)
        return rendered['system'], rendered['prompt']

    def generate_outline(self, topic, style='学术论文', reference_style='GB/T 7714', subject=''):
        """生成论文大纲。"""
        system, prompt = self._render_scene(
            'paper_write.outline',
            {
                'topic': topic,
                'style': style,
                'reference_style': reference_style,
                'subject': subject,
            },
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.outline', 'generate_outline'),
        )

    def import_outline_with_ai(self, document_blocks):
        """用模型识别导入文档的大纲结构。"""
        if isinstance(document_blocks, str):
            blocks_text = document_blocks
        else:
            blocks_text = json.dumps(document_blocks or [], ensure_ascii=False, separators=(',', ':'))
        system, prompt = self._render_scene(
            'paper_write.import_outline',
            {
                'document_blocks': blocks_text[:60000],
            },
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.import_outline', 'import_outline'),
        )

    def write_section(
        self,
        outline,
        section_title,
        context='',
        word_count=1000,
        reference_style='GB/T 7714',
        allow_tables=False,
    ):
        """按章节写作。"""
        system, prompt = self._render_scene(
            'paper_write.section',
            {
                'outline': outline,
                'section_title': section_title,
                'context': context[:500] if context else '',
                'word_count': word_count,
                'reference_style': reference_style,
            },
        )
        if allow_tables:
            prompt += (
                '\n\n补充要求：如内容适合使用表格表达，可以直接输出 Markdown 表格。'
                '表格必须结构完整、表头清楚，不要使用代码围栏。'
            )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'write_section'),
        )

    def generate_table(self, outline, section_title, context='', word_count=1000, reference_style='GB/T 7714'):
        """生成带表格的章节内容。"""
        system, prompt = self._render_scene(
            'paper_write.section',
            {
                'outline': outline,
                'section_title': section_title,
                'context': context[:500] if context else '',
                'word_count': word_count,
                'reference_style': reference_style,
            },
        )
        prompt += (
            '\n\n补充要求：本次只生成适合插入当前章节的结构化表格内容。'
            '优先输出一个 Markdown 表格，可以在表格前后保留必要的简短说明。'
            '表格必须为标准矩形结构，表头清楚，不要使用合并单元格、嵌套表格、公式或代码围栏。'
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'generate_table'),
        )

    def write_abstract(self, full_text, language='中文'):
        """生成摘要。"""
        system, prompt = self._render_scene(
            'paper_write.abstract',
            {
                'full_text': full_text[:12000],
                'language': language,
            },
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.abstract', 'write_abstract'),
        )

    def format_references(self, refs_text, style='GB/T 7714'):
        """格式化参考文献。"""
        system, prompt = self._render_scene(
            'paper_write.section',
            {
                'outline': '',
                'section_title': '参考文献格式化',
                'context': refs_text,
                'word_count': '',
                'reference_style': style,
            },
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'format_references'),
        )

    def improve_paragraph(self, paragraph, direction='学术化'):
        """改进段落。"""
        system, prompt = self._render_scene(
            'paper_write.section',
            {
                'outline': '',
                'section_title': f'{direction}改进',
                'context': paragraph,
                'word_count': '',
                'reference_style': '',
            },
        )
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'improve_paragraph'),
        )
