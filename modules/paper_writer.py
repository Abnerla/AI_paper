# -*- coding: utf-8 -*-
"""
论文写作模块。
"""

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

    def write_section(self, outline, section_title, context='', word_count=1000, reference_style='GB/T 7714'):
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
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'write_section'),
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
        system = '你是一位专业的学术规范助手，精通各类参考文献格式。'
        prompt = f'''请将以下参考文献整理为{style}格式：
{refs_text}

要求：
1. 严格按照{style}标准格式。
2. 按照引用顺序编号。
3. 信息补全时明确标注待补充项。
4. 保持格式统一规范。

请直接输出格式化后的参考文献列表。'''
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.references', 'format_references'),
        )

    def improve_paragraph(self, paragraph, direction='学术化'):
        """改进段落。"""
        system = '你是一位专业的学术写作助手。'
        prompt = f'''请对以下段落进行{direction}改进：
{paragraph}

要求：
1. 保持原有观点和信息。
2. 提升学术表达水平。
3. 增强逻辑连贯性。
4. 使用更专业的学术词汇。

请直接输出改进后的段落。'''
        return self.api.call_sync(
            prompt,
            system,
            usage_context=self._usage_context('paper_write.section', 'improve_paragraph'),
        )
