# -*- coding: utf-8 -*-
"""
Unified prompt center metadata, default resources, and render helpers.
"""

from __future__ import annotations

import copy
import json
import time
from string import Formatter

from modules.runtime_paths import resolve_resource_path


PROMPT_MODE_TEMPLATE = 'template'
PROMPT_MODE_INSTRUCTION = 'instruction'  # 仅用于识别历史数据并迁移，不再出现在新记录里
PROMPT_SOURCE_SYSTEM = 'system'
PROMPT_SOURCE_USER = 'user'
PROMPT_MODES = (PROMPT_MODE_TEMPLATE,)
PROMPT_SOURCES = (PROMPT_SOURCE_SYSTEM, PROMPT_SOURCE_USER)

PAGE_ORDER = (
    'paper_write',
    'ai_reduce',
    'plagiarism',
    'polish',
    'correction',
)

PAGE_META = {
    'paper_write': {'label': '论文写作'},
    'ai_reduce': {'label': '降AI检测'},
    'plagiarism': {'label': '降查重率'},
    'polish': {'label': '学术润色'},
    'correction': {'label': '智能纠错'},
}

SCENE_DEFS = {
    'paper_write.outline': {
        'page_id': 'paper_write',
        'page_label': '论文写作',
        'label': '生成大纲',
        'variables': (
            ('topic', '论文标题'),
            ('style', '论文类型'),
            ('reference_style', '引用格式'),
            ('subject', '学科/方向'),
        ),
        'required_variables': ('topic', 'style', 'reference_style'),
    },
    'paper_write.section': {
        'page_id': 'paper_write',
        'page_label': '论文写作',
        'label': '撰写章节',
        'variables': (
            ('outline', '完整大纲'),
            ('section_title', '当前章节'),
            ('context', '已有上下文'),
            ('word_count', '目标字数'),
            ('reference_style', '引用格式'),
        ),
        'required_variables': ('outline', 'section_title', 'word_count', 'reference_style'),
    },
    'paper_write.abstract': {
        'page_id': 'paper_write',
        'page_label': '论文写作',
        'label': '生成摘要',
        'variables': (
            ('full_text', '论文全文'),
            ('language', '摘要语言'),
        ),
        'required_variables': ('full_text',),
    },
    'paper_write.import_outline': {
        'page_id': 'paper_write',
        'page_label': '论文写作',
        'label': '导入识别',
        'variables': (
            ('document_blocks', '文档结构块'),
        ),
        'required_variables': ('document_blocks',),
        'warning': '该提示词仅影响论文写作页的 AI 导入识别，不影响本地导入识别。',
    },
    'polish.run_task': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '统一任务',
        'variables': (
            ('text', '待处理文本'),
            ('task_type', '任务类型'),
            ('polish_type', '润色方式'),
            ('execution_mode', '执行模式'),
            ('topic', '主题/章节'),
            ('notes', '补充说明'),
        ),
        'required_variables': ('text', 'task_type', 'polish_type', 'execution_mode'),
    },
    'polish.translate': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '翻译润色',
        'variables': (
            ('text', '待翻译文本'),
            ('target_lang', '目标语言'),
        ),
        'required_variables': ('text', 'target_lang'),
    },
    'polish.grammar': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '语法标点修正',
        'variables': (
            ('text', '待校对文本'),
        ),
        'required_variables': ('text',),
    },
    'polish.academic_vocab': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '学术词汇优化',
        'variables': (
            ('text', '待优化文本'),
        ),
        'required_variables': ('text',),
    },
    'polish.logic': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '逻辑段落优化',
        'variables': (
            ('text', '待优化文本'),
        ),
        'required_variables': ('text',),
    },
    'polish.full': {
        'page_id': 'polish',
        'page_label': '学术润色',
        'label': '全面润色',
        'variables': (
            ('text', '待润色文本'),
        ),
        'required_variables': ('text',),
    },
    'ai_reduce.transform': {
        'page_id': 'ai_reduce',
        'page_label': '降AI检测',
        'label': '文本改写',
        'variables': (
            ('text', '待处理原文'),
            ('mode', '模式值'),
            ('mode_label', '处理模式'),
        ),
        'required_variables': ('text', 'mode', 'mode_label'),
    },
    'plagiarism.transform': {
        'page_id': 'plagiarism',
        'page_label': '降查重率',
        'label': '文本改写',
        'variables': (
            ('text', '待降重原文'),
            ('source_text', '查重报告/重复源'),
            ('mode', '模式值'),
            ('mode_label', '处理模式'),
        ),
        'required_variables': ('text', 'mode', 'mode_label'),
    },
    'correction.ai_review': {
        'page_id': 'correction',
        'page_label': '智能纠错',
        'label': 'AI 纠错',
        'variables': (
            ('text', '待检查文本'),
            ('citation_style', '引用规范'),
        ),
        'required_variables': ('text',),
        'warning': '该提示词仅影响 AI 补充识别，不影响本地规则检测。',
    },
}

PAGE_SCENE_MAP = {}
for _scene_id, _scene_def in SCENE_DEFS.items():
    PAGE_SCENE_MAP.setdefault(_scene_def['page_id'], []).append(_scene_id)

DEFAULTS_PATH = resolve_resource_path('modules', 'prompt_defaults.json')
SYSTEM_DEFAULT_SYNC_SCENE_IDS = ('paper_write.outline', 'paper_write.import_outline', 'polish.run_task')


# 冻结的历史 instruction_wrapper：仅用于把旧版本的"纯说明文本"用户提示词一次性迁移为完整模板。
# 不要参与正常渲染路径，也不要在 UI 里暴露。
LEGACY_INSTRUCTION_WRAPPERS = {
    'paper_write.outline': (
        '请根据以下论文信息完成大纲生成。\n'
        '论文标题：{topic}\n'
        '论文类型：{style}\n'
        '学科/方向：{subject}\n'
        '引用格式：{reference_style}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出最终大纲正文。'
    ),
    'paper_write.section': (
        '请根据以下信息撰写论文章节。\n\n'
        '完整大纲：\n{outline}\n\n'
        '当前章节：{section_title}\n'
        '已有上下文：\n{context}\n'
        '目标字数：约 {word_count} 字\n'
        '引用格式：{reference_style}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出最终章节正文。'
    ),
    'paper_write.abstract': (
        '请根据以下论文内容生成摘要。\n\n'
        '论文内容：\n{full_text}\n'
        '摘要语言：{language}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出最终摘要与关键词。'
    ),
    'ai_reduce.transform': (
        '请对以下论文文本执行 AI 痕迹消除改写。\n\n'
        '处理模式：{mode_label}（{mode}）\n'
        '原文：\n{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出处理后的正文。'
    ),
    'plagiarism.transform': (
        '请对以下论文内容执行降重。\n\n'
        '处理模式：{mode_label}（{mode}）\n'
        '待降重原文：\n{text}\n\n'
        '查重报告/重复源文本：\n{source_text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出降重后的正文。'
    ),
    'polish.run_task': (
        '请根据以下任务设置处理学术文本。\n'
        '任务类型：{task_type}\n'
        '润色方式：{polish_type}\n'
        '执行模式：{execution_mode}\n'
        '主题/章节：{topic}\n'
        '待处理文本：\n{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '补充说明：\n{notes}\n\n'
        '请直接输出最终处理后的文本。'
    ),
    'polish.translate': (
        '请将以下学术文本翻译为指定语言：\n\n'
        '{text}\n\n'
        '目标语言：{target_lang}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出翻译后的正文。'
    ),
    'polish.grammar': (
        '请对以下文本进行语法和标点校对：\n\n'
        '{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出校对后的文本，并在末尾用【修改说明】列出主要改动。'
    ),
    'polish.academic_vocab': (
        '请对以下文本进行学术词汇优化：\n\n'
        '{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出优化后的文本。'
    ),
    'polish.logic': (
        '请对以下文本进行逻辑和结构优化：\n\n'
        '{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出优化后的文本。'
    ),
    'polish.full': (
        '请对以下论文内容进行全面学术润色：\n\n'
        '{text}\n\n'
        '附加提示词：\n{instruction}\n\n'
        '请直接输出润色后的文本。'
    ),
    'correction.ai_review': (
        '请对下面的论文文本做智能纠错，只返回 JSON 数组，不要输出 Markdown。\n\n'
        '附加提示词：\n{instruction}\n\n'
        '引用规范上下文：{citation_style}\n\n'
        '待检查文本：\n{text}'
    ),
}


def migrate_legacy_instruction(scene_id, content):
    """把旧 `instruction` 模式的用户内容用对应 wrapper 包成新模板文本。

    - 若 scene_id 没有 wrapper，原样返回（兜底，不丢失用户数据）。
    - content 作为 `{instruction}` 的替换值填入 wrapper；其它变量保持占位符，
      仍由调用端在 render_scene 里做 format_map 实际替换。
    """
    wrapper = LEGACY_INSTRUCTION_WRAPPERS.get(scene_id)
    if not wrapper:
        return content or ''
    return wrapper.replace('{instruction}', content or '')


class PromptCenterError(Exception):
    """Base prompt-center error."""


class PromptValidationError(PromptCenterError):
    """Raised when prompt content is invalid."""


class PromptSelectionError(PromptCenterError):
    """Raised when a scene has no active prompt."""


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ''


_cached_defaults = None

def load_prompt_defaults():
    global _cached_defaults
    if _cached_defaults is not None:
        return _cached_defaults
    with open(DEFAULTS_PATH, 'r', encoding='utf-8') as handle:
        _cached_defaults = json.load(handle)
    return _cached_defaults


def list_template_fields(content):
    fields = []
    for _literal, field_name, _format_spec, _conversion in Formatter().parse(content or ''):
        if field_name:
            fields.append(field_name)
    return fields


def render_template(content, values):
    try:
        return (content or '').format_map(_SafeFormatDict(values or {}))
    except Exception as exc:
        raise PromptValidationError(f'模板渲染失败：{exc}') from exc


def build_default_scene_payloads(now_ts=None):
    payload = {}
    now_ts = int(now_ts or time.time())
    defaults = load_prompt_defaults()
    for scene_id, resource in defaults.items():
        prompt_id = f'system_{scene_id.replace(".", "_")}'
        payload[scene_id] = {
            'active_prompt_id': prompt_id,
            'prompts': [
                {
                    'id': prompt_id,
                    'name': resource.get('default_name') or '系统默认提示词',
                    'description': resource.get('default_description') or '',
                    'mode': PROMPT_MODE_TEMPLATE,
                    'content': resource.get('default_prompt', ''),
                    'source': PROMPT_SOURCE_SYSTEM,
                    'created_at': now_ts,
                    'updated_at': now_ts,
                }
            ],
        }
    return payload


class PromptCenter:
    def __init__(self, config_mgr):
        self.config = config_mgr
        self._memory_center = {
            'seeded': False,
            'scenes': {},
        }

    def _has_config_storage(self):
        return bool(
            self.config
            and hasattr(self.config, 'ensure_prompt_center_seeded')
            and hasattr(self.config, 'get_prompt_scene')
            and hasattr(self.config, 'set_prompt_scene')
        )

    def _get_all_scene_states(self):
        self.ensure_seeded()
        if self._has_config_storage():
            return self.config.get_all_prompt_scenes()
        return copy.deepcopy(self._memory_center.get('scenes', {}))

    def _set_scene_state(self, scene_id, scene_data):
        if self._has_config_storage():
            self.config.set_prompt_scene(scene_id, scene_data)
            return
        self._memory_center.setdefault('scenes', {})[scene_id] = copy.deepcopy(scene_data)

    def _persist(self):
        if self._has_config_storage() and hasattr(self.config, 'save'):
            self.config.save()

    def _generate_prompt_id(self):
        if self._has_config_storage() and hasattr(self.config, 'generate_prompt_id'):
            return self.config.generate_prompt_id()

        scenes = self._get_all_scene_states()
        existing = {
            prompt.get('id')
            for scene in scenes.values()
            for prompt in scene.get('prompts', [])
            if isinstance(prompt, dict)
        }
        while True:
            prompt_id = f"prompt_{int(time.time() * 1000)}_{int(time.time() * 1000000) % 1000:03d}"
            if prompt_id not in existing:
                return prompt_id

    def ensure_seeded(self):
        scene_payloads = build_default_scene_payloads()
        if self._has_config_storage():
            seeded = self.config.ensure_prompt_center_seeded(scene_payloads)
            synced = False
            if hasattr(self.config, 'sync_prompt_scene_defaults'):
                synced = bool(self.config.sync_prompt_scene_defaults(scene_payloads, scene_ids=SYSTEM_DEFAULT_SYNC_SCENE_IDS))
            if seeded or synced:
                self._persist()
            return seeded or synced

        if self._memory_center.get('seeded'):
            return False

        self._memory_center = {
            'seeded': True,
            'scenes': scene_payloads,
        }
        return True

    def list_pages(self):
        pages = []
        for page_id in PAGE_ORDER:
            pages.append(
                {
                    'page_id': page_id,
                    'label': PAGE_META.get(page_id, {}).get('label', page_id),
                    'scenes': [self.get_scene_def(scene_id) for scene_id in PAGE_SCENE_MAP.get(page_id, ())],
                }
            )
        return pages

    def get_scene_def(self, scene_id):
        scene = SCENE_DEFS.get(scene_id)
        if not scene:
            raise PromptCenterError(f'未知场景：{scene_id}')
        return dict(scene)

    def get_scene_resource(self, scene_id):
        defaults = load_prompt_defaults()
        if scene_id not in defaults:
            raise PromptCenterError(f'默认资源缺失：{scene_id}')
        return copy.deepcopy(defaults[scene_id])

    def get_scene_state(self, scene_id):
        self.ensure_seeded()
        if self._has_config_storage():
            scene = self.config.get_prompt_scene(scene_id)
        else:
            scene = self._memory_center.get('scenes', {}).get(scene_id, {'active_prompt_id': '', 'prompts': []})
        return copy.deepcopy(scene)

    def get_active_prompt(self, scene_id):
        scene = self.get_scene_state(scene_id)
        prompts = scene.get('prompts', [])
        if not prompts:
            return None
        active_id = scene.get('active_prompt_id', '')
        for prompt in prompts:
            if prompt.get('id') == active_id:
                return prompt
        return prompts[0] if prompts else None

    def scene_has_active_prompt(self, scene_id):
        return bool(self.get_active_prompt(scene_id))

    def count_summary(self, page_id=None):
        scenes = self._get_all_scene_states()
        total = 0
        active = 0
        groups = 0
        scene_ids = PAGE_SCENE_MAP.get(page_id, ()) if page_id else SCENE_DEFS.keys()
        for scene_id in scene_ids:
            scene = scenes.get(scene_id) or {'prompts': [], 'active_prompt_id': ''}
            prompts = scene.get('prompts', [])
            total += len(prompts)
            groups += 1
            if prompts and scene.get('active_prompt_id'):
                active += 1
        return {'total': total, 'active_groups': active, 'groups': groups}

    def validate_prompt(self, scene_id, mode, content):
        # 新架构只保留 template 模式；mode 参数仅作为向后兼容的占位，统一按模板校验。
        content = (content or '').strip()
        if not content:
            raise PromptValidationError('提示词内容不能为空')

        scene_def = self.get_scene_def(scene_id)
        supported_fields = {name for name, _label in scene_def.get('variables', ())}

        fields = list_template_fields(content)
        unknown_fields = [field for field in fields if field not in supported_fields]
        if unknown_fields:
            joined = '、'.join(sorted(set(unknown_fields)))
            raise PromptValidationError(f'模板中包含未定义变量：{joined}')

        missing = [field for field in scene_def.get('required_variables', ()) if field not in fields]
        if missing:
            joined = '、'.join(missing)
            raise PromptValidationError(f'提示词缺少必需变量：{joined}')

        render_template(content, {field: '示例' for field in supported_fields})
        return {
            'fields': fields,
            'required': list(scene_def.get('required_variables', ())),
            'supported': list(supported_fields),
        }

    def save_prompt(self, scene_id, prompt_id=None, *, name, description='', mode, content, source=PROMPT_SOURCE_USER):
        self.ensure_seeded()
        if source not in PROMPT_SOURCES:
            source = PROMPT_SOURCE_USER

        name = (name or '').strip()
        if not name:
            raise PromptValidationError('提示词名称不能为空')

        self.validate_prompt(scene_id, mode, content)
        now_ts = int(time.time())
        scene = self.get_scene_state(scene_id)
        prompts = list(scene.get('prompts', []))
        target = None
        for prompt in prompts:
            if prompt.get('id') == prompt_id:
                target = prompt
                break

        if target is None:
            prompt_id = self._generate_prompt_id()
            target = {
                'id': prompt_id,
                'created_at': now_ts,
            }
            prompts.append(target)

        target.update(
            {
                'id': prompt_id,
                'name': name,
                'description': (description or '').strip(),
                'mode': mode,
                'content': content,
                'source': source,
                'updated_at': now_ts,
            }
        )
        if not target.get('created_at'):
            target['created_at'] = now_ts

        active_id = scene.get('active_prompt_id', '')
        if not active_id:
            active_id = prompt_id

        self._set_scene_state(
            scene_id,
            {
                'active_prompt_id': active_id,
                'prompts': prompts,
            },
        )
        self._persist()
        return self.get_scene_state(scene_id)

    @staticmethod
    def _build_copy_name(source_name, existing_names):
        base_name = (source_name or '').strip() or '未命名提示词'
        existing = {str(name or '').strip() for name in (existing_names or ()) if str(name or '').strip()}

        candidate = f'{base_name}（副本）'
        if candidate not in existing:
            return candidate

        index = 2
        while True:
            candidate = f'{base_name}（副本 {index}）'
            if candidate not in existing:
                return candidate
            index += 1

    def duplicate_prompt(self, scene_id, prompt_id):
        self.ensure_seeded()
        scene = self.get_scene_state(scene_id)
        prompts = list(scene.get('prompts', []))
        source_prompt = None
        source_index = -1
        for index, prompt in enumerate(prompts):
            if prompt.get('id') == prompt_id:
                source_prompt = prompt
                source_index = index
                break

        if source_prompt is None:
            raise PromptCenterError('要复制的提示词不存在')

        now_ts = int(time.time())
        duplicated_prompt = copy.deepcopy(source_prompt)
        duplicated_prompt.update(
            {
                'id': self._generate_prompt_id(),
                'name': self._build_copy_name(
                    source_prompt.get('name', ''),
                    [item.get('name', '') for item in prompts],
                ),
                'source': PROMPT_SOURCE_USER,
                'created_at': now_ts,
                'updated_at': now_ts,
            }
        )

        insert_at = source_index + 1 if source_index >= 0 else len(prompts)
        prompts.insert(insert_at, duplicated_prompt)
        self._set_scene_state(
            scene_id,
            {
                'active_prompt_id': scene.get('active_prompt_id', ''),
                'prompts': prompts,
            },
        )
        self._persist()
        return copy.deepcopy(duplicated_prompt)

    def activate_prompt(self, scene_id, prompt_id):
        self.ensure_seeded()
        if self._has_config_storage():
            self.config.set_active_prompt(scene_id, prompt_id)
        else:
            scene = self.get_scene_state(scene_id)
            prompt_ids = {prompt.get('id') for prompt in scene.get('prompts', [])}
            if prompt_id in prompt_ids:
                scene['active_prompt_id'] = prompt_id
                self._set_scene_state(scene_id, scene)
        self._persist()
        return self.get_scene_state(scene_id)

    def delete_prompt(self, scene_id, prompt_id):
        self.ensure_seeded()
        if self._has_config_storage():
            self.config.delete_prompt(scene_id, prompt_id)
        else:
            scene = self.get_scene_state(scene_id)
            prompts = [prompt for prompt in scene.get('prompts', []) if prompt.get('id') != prompt_id]
            active_prompt_id = scene.get('active_prompt_id', '')
            if active_prompt_id == prompt_id:
                active_prompt_id = prompts[0]['id'] if prompts else ''
            self._set_scene_state(
                scene_id,
                {
                    'active_prompt_id': active_prompt_id,
                    'prompts': prompts,
                },
            )
        self._persist()
        return self.get_scene_state(scene_id)

    def render_scene(self, scene_id, values):
        self.ensure_seeded()
        prompt = self.get_active_prompt(scene_id)
        if not prompt:
            raise PromptSelectionError('当前场景没有可用的提示词，请先创建或选择一条提示词。')

        resource = self.get_scene_resource(scene_id)
        scene_def = self.get_scene_def(scene_id)
        supported_fields = {field for field, _label in scene_def.get('variables', ())}
        values = values or {}
        render_values = {field: values.get(field, '') for field in supported_fields}

        rendered_prompt = render_template(prompt.get('content', ''), render_values)

        return {
            'system': resource.get('system', ''),
            'prompt': rendered_prompt,
            'record': copy.deepcopy(prompt),
            'scene': scene_def,
        }
