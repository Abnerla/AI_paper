# -*- coding: utf-8 -*-
"""
技能运行时、安装管理与请求钩子。
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from modules.app_metadata import APP_VERSION
from modules.prompt_center import SCENE_DEFS
from modules.remote_content import compare_versions, normalize_version


SKILL_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9._-]{1,63}$')
ALLOWED_ACTION_FIELD_TYPES = ('text', 'textarea', 'select', 'number', 'checkbox')
BLOCKED_FILE_EXTENSIONS = {
    '.bat',
    '.bin',
    '.cmd',
    '.com',
    '.dll',
    '.dylib',
    '.exe',
    '.msi',
    '.ps1',
    '.pyd',
    '.pyc',
    '.pyo',
    '.sh',
    '.so',
}
BLOCKED_FILE_NAMES = {
    'pipfile',
    'pipfile.lock',
    'poetry.lock',
    'pyproject.toml',
    'requirements-dev.txt',
    'requirements.txt',
    'setup.cfg',
    'setup.py',
}
ALLOWED_STATIC_EXTENSIONS = {
    '.csv',
    '.css',
    '.gif',
    '.html',
    '.ico',
    '.ini',
    '.jpeg',
    '.jpg',
    '.json',
    '.md',
    '.png',
    '.py',
    '.svg',
    '.toml',
    '.txt',
    '.yaml',
    '.yml',
}
DEFAULT_REGISTRY_PAYLOAD = {
    'id': '',
    'updated_at': '',
    'skills': [],
}


class SkillValidationError(ValueError):
    """技能包校验失败。"""


class SkillExecutionError(RuntimeError):
    """技能执行失败。"""


def _now_ts():
    return int(time.time())


def _safe_copy_json(value):
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    return {}


def _coerce_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _coerce_number(value):
    if value in (None, ''):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if '.' in text:
            return float(text)
        return int(text)
    except Exception:
        return None


def _normalize_rel_path(path):
    raw = str(path or '').strip().replace('\\', '/')
    if not raw:
        return ''
    normalized = os.path.normpath(raw).replace('\\', '/')
    while normalized.startswith('./'):
        normalized = normalized[2:]
    return '' if normalized == '.' else normalized


def _unique_text_list(items, *, allowed=None):
    result = []
    seen = set()
    for item in list(items or []):
        value = str(item or '').strip()
        if not value or value in seen:
            continue
        if allowed is not None and value not in allowed:
            continue
        seen.add(value)
        result.append(value)
    return result


class SkillHost:
    """为技能暴露受控宿主能力。"""

    def __init__(self, manager, skill_id, action_id=''):
        self._manager = manager
        self._skill_id = str(skill_id or '').strip()
        self._action_id = str(action_id or '').strip()

    def _build_usage_context(self, usage_context=None):
        payload = {
            'page_id': 'skills',
            'scene_id': '',
            'action': f'skill.{self._skill_id}.{self._action_id or "host_call"}',
            'skip_skills': True,
        }
        if isinstance(usage_context, dict):
            payload.update(dict(usage_context))
        payload['skip_skills'] = True
        return payload

    def call_llm(
        self,
        prompt,
        system='',
        *,
        api_name=None,
        temperature=None,
        max_tokens=None,
        request_timeout=None,
        model_override=None,
        usage_context=None,
    ):
        if not getattr(self._manager, 'api_client', None):
            raise SkillExecutionError('当前技能宿主未绑定 API 客户端。')
        return self._manager.api_client.call_sync(
            str(prompt or ''),
            system=str(system or ''),
            api_name=api_name,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            model_override=model_override,
            usage_context=self._build_usage_context(usage_context),
            disable_skills=True,
        )

    def call_llm_json(
        self,
        prompt,
        system='',
        *,
        api_name=None,
        temperature=None,
        max_tokens=None,
        request_timeout=None,
        model_override=None,
        schema_name='',
        usage_context=None,
    ):
        if not getattr(self._manager, 'api_client', None):
            raise SkillExecutionError('当前技能宿主未绑定 API 客户端。')
        return self._manager.api_client.call_json_sync(
            str(prompt or ''),
            system=str(system or ''),
            api_name=api_name,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            model_override=model_override,
            schema_name=str(schema_name or '').strip(),
            usage_context=self._build_usage_context(usage_context),
            disable_skills=True,
        )

    def log(self, message, level='INFO'):
        self._manager._log(f'[skill:{self._skill_id}] {message}', level=level)

    def resolve_skill_data_path(self, *parts):
        return self._manager.resolve_skill_data_path(self._skill_id, *parts)


class SkillManager:
    """技能安装、查询与执行入口。"""

    PACKAGES_DIR_NAME = 'packages'
    DATA_DIR_NAME = 'data'
    TEMP_DIR_NAME = '_tmp'
    REGISTRY_CACHE_FILE_NAME = 'registry_cache.json'
    SKILLS_DIR_NAME = 'skills'

    def __init__(self, config_mgr, *, api_client=None, log_callback=None):
        self.config = config_mgr
        self.api_client = api_client
        self.log_callback = log_callback
        self._lock = threading.RLock()
        self._instance_cache = {}
        self.ensure_storage_dirs()

    def set_api_client(self, api_client):
        self.api_client = api_client

    def set_log_callback(self, log_callback):
        self.log_callback = log_callback

    def _log(self, message, level='INFO'):
        if callable(self.log_callback):
            try:
                self.log_callback(message, level=level)
            except Exception:
                pass

    @property
    def app_dir(self):
        raw = getattr(self.config, 'app_dir', '') or getattr(self.config, 'data_dir', '') or '.'
        return os.path.abspath(raw)

    def resolve_skills_root(self):
        return os.path.join(self.app_dir, self.SKILLS_DIR_NAME)

    def resolve_packages_dir(self):
        return os.path.join(self.resolve_skills_root(), self.PACKAGES_DIR_NAME)

    def resolve_data_dir(self):
        return os.path.join(self.resolve_skills_root(), self.DATA_DIR_NAME)

    def resolve_temp_dir(self):
        return os.path.join(self.resolve_skills_root(), self.TEMP_DIR_NAME)

    def resolve_registry_cache_path(self):
        return os.path.join(self.resolve_skills_root(), self.REGISTRY_CACHE_FILE_NAME)

    def resolve_skill_package_dir(self, skill_id):
        return os.path.join(self.resolve_packages_dir(), str(skill_id or '').strip())

    def resolve_skill_data_dir(self, skill_id):
        return os.path.join(self.resolve_data_dir(), str(skill_id or '').strip())

    def resolve_skill_data_path(self, skill_id, *parts):
        base_dir = self.resolve_skill_data_dir(skill_id)
        os.makedirs(base_dir, exist_ok=True)
        current = base_dir
        for part in parts:
            token = str(part or '').strip()
            if not token:
                continue
            current = os.path.join(current, token)
        return os.path.abspath(current)

    def ensure_storage_dirs(self):
        os.makedirs(self.resolve_packages_dir(), exist_ok=True)
        os.makedirs(self.resolve_data_dir(), exist_ok=True)
        os.makedirs(self.resolve_temp_dir(), exist_ok=True)

    def _create_managed_temp_dir(self, prefix):
        parent_dir = self.resolve_temp_dir()
        os.makedirs(parent_dir, exist_ok=True)
        for _ in range(20):
            temp_dir = os.path.join(parent_dir, f'{prefix}{uuid.uuid4().hex}')
            try:
                os.makedirs(temp_dir)
                return temp_dir
            except FileExistsError:
                continue
        raise SkillExecutionError('技能临时目录创建失败。')

    @staticmethod
    def _validate_skill_id(skill_id):
        value = str(skill_id or '').strip()
        if not SKILL_ID_PATTERN.match(value):
            raise SkillValidationError('skill.json 中的 id 非法，只允许小写字母、数字、点、下划线和中划线。')
        return value

    @staticmethod
    def _sanitize_action_field(field):
        if not isinstance(field, dict):
            raise SkillValidationError('动作字段定义无效。')
        field_id = str(field.get('id', '') or '').strip()
        label = str(field.get('label', '') or '').strip()
        field_type = str(field.get('type', '') or '').strip().lower()
        if not field_id:
            raise SkillValidationError('动作字段缺少 id。')
        if not label:
            raise SkillValidationError(f'动作字段 {field_id} 缺少 label。')
        if field_type not in ALLOWED_ACTION_FIELD_TYPES:
            raise SkillValidationError(f'动作字段 {field_id} 的 type 不受支持：{field_type}')

        payload = {
            'id': field_id,
            'label': label,
            'type': field_type,
            'required': bool(field.get('required', False)),
            'default': field.get('default'),
            'placeholder': str(field.get('placeholder', '') or '').strip(),
            'help': str(field.get('help', '') or '').strip(),
            'min': field.get('min', None),
            'max': field.get('max', None),
            'options': [],
        }

        if field_type == 'select':
            options = []
            seen_values = set()
            for option in list(field.get('options', []) or []):
                if isinstance(option, dict):
                    option_value = str(option.get('value', '') or '').strip()
                    option_label = str(option.get('label', '') or option_value).strip()
                else:
                    option_value = str(option or '').strip()
                    option_label = option_value
                if not option_value or option_value in seen_values:
                    continue
                seen_values.add(option_value)
                options.append({'label': option_label or option_value, 'value': option_value})
            if not options:
                raise SkillValidationError(f'动作字段 {field_id} 的下拉选项不能为空。')
            payload['options'] = options
            default_value = str(field.get('default', '') or '').strip()
            if default_value and default_value not in {item['value'] for item in options}:
                raise SkillValidationError(f'动作字段 {field_id} 的默认值不在 options 中。')
            if not default_value:
                payload['default'] = options[0]['value']
        elif field_type == 'checkbox':
            payload['default'] = bool(field.get('default', False))
        elif field_type == 'number':
            default_number = _coerce_number(field.get('default'))
            if field.get('default', None) not in (None, '') and default_number is None:
                raise SkillValidationError(f'动作字段 {field_id} 的默认值不是有效数字。')
            payload['default'] = default_number
            payload['min'] = _coerce_number(field.get('min'))
            payload['max'] = _coerce_number(field.get('max'))
            if payload['min'] is not None and payload['max'] is not None and payload['min'] > payload['max']:
                raise SkillValidationError(f'动作字段 {field_id} 的 min 不能大于 max。')
        else:
            payload['default'] = '' if field.get('default', None) is None else str(field.get('default'))

        return payload

    @classmethod
    def _sanitize_action_definition(cls, action):
        if not isinstance(action, dict):
            raise SkillValidationError('动作定义无效。')
        action_id = str(action.get('id', '') or '').strip()
        label = str(action.get('label', '') or '').strip()
        if not action_id:
            raise SkillValidationError('动作定义缺少 id。')
        if not label:
            raise SkillValidationError(f'动作 {action_id} 缺少 label。')

        input_schema = action.get('input_schema', {}) or {}
        if not isinstance(input_schema, dict):
            raise SkillValidationError(f'动作 {action_id} 的 input_schema 无效。')

        seen_field_ids = set()
        fields = []
        for field in list(input_schema.get('fields', []) or []):
            payload = cls._sanitize_action_field(field)
            if payload['id'] in seen_field_ids:
                raise SkillValidationError(f'动作 {action_id} 存在重复的字段 id：{payload["id"]}')
            seen_field_ids.add(payload['id'])
            fields.append(payload)

        return {
            'id': action_id,
            'label': label,
            'description': str(action.get('description', '') or '').strip(),
            'input_schema': {
                'fields': fields,
            },
        }

    @classmethod
    def sanitize_skill_manifest(cls, payload):
        if not isinstance(payload, dict):
            raise SkillValidationError('skill.json 内容必须是对象。')

        required_keys = (
            'id',
            'name',
            'version',
            'description',
            'min_app_version',
            'entry',
            'priority',
            'actions',
            'scene_bindings',
            'global_hook',
        )
        for key in required_keys:
            if key not in payload:
                raise SkillValidationError(f'skill.json 缺少必填字段：{key}')

        skill_id = cls._validate_skill_id(payload.get('id', ''))
        entry = payload.get('entry', {}) or {}
        if not isinstance(entry, dict):
            raise SkillValidationError('skill.json 中的 entry 必须是对象。')
        entry_module = str(entry.get('module', '') or '').strip()
        entry_class = str(entry.get('class', '') or '').strip()
        if not entry_module or not entry_class:
            raise SkillValidationError('skill.json 中的 entry.module 和 entry.class 不能为空。')

        actions = []
        seen_action_ids = set()
        for action in list(payload.get('actions', []) or []):
            action_payload = cls._sanitize_action_definition(action)
            if action_payload['id'] in seen_action_ids:
                raise SkillValidationError(f'skill.json 中存在重复的动作 id：{action_payload["id"]}')
            seen_action_ids.add(action_payload['id'])
            actions.append(action_payload)

        scene_bindings = _unique_text_list(payload.get('scene_bindings', []), allowed=SCENE_DEFS.keys())
        raw_scene_bindings = _unique_text_list(payload.get('scene_bindings', []))
        unknown_scene_ids = [scene_id for scene_id in raw_scene_bindings if scene_id not in SCENE_DEFS]
        if unknown_scene_ids:
            joined = '、'.join(unknown_scene_ids)
            raise SkillValidationError(f'skill.json 中存在未知场景：{joined}')

        return {
            'id': skill_id,
            'name': str(payload.get('name', '') or '').strip(),
            'version': normalize_version(payload.get('version', '')),
            'description': str(payload.get('description', '') or '').strip(),
            'min_app_version': normalize_version(payload.get('min_app_version', '')),
            'entry': {
                'module': entry_module,
                'class': entry_class,
            },
            'priority': _coerce_int(payload.get('priority', 0), 0),
            'actions': actions,
            'scene_bindings': scene_bindings,
            'global_hook': bool(payload.get('global_hook', False)),
            'publisher': str(payload.get('publisher', '') or '').strip(),
            'homepage': str(payload.get('homepage', '') or '').strip(),
            'icon': str(payload.get('icon', '') or '').strip(),
        }

    @classmethod
    def sanitize_registry_payload(cls, payload):
        if not isinstance(payload, dict):
            return copy.deepcopy(DEFAULT_REGISTRY_PAYLOAD)
        result = {
            'id': str(payload.get('id', '') or '').strip(),
            'updated_at': str(payload.get('updated_at', '') or payload.get('publish_date', '') or '').strip(),
            'skills': [],
        }
        seen = set()
        for item in list(payload.get('skills', []) or payload.get('items', []) or []):
            if not isinstance(item, dict):
                continue
            skill_id = str(item.get('id', '') or '').strip()
            if not skill_id or skill_id in seen:
                continue
            try:
                cls._validate_skill_id(skill_id)
            except SkillValidationError:
                continue
            seen.add(skill_id)
            result['skills'].append(
                {
                    'id': skill_id,
                    'name': str(item.get('name', '') or '').strip() or skill_id,
                    'version': normalize_version(item.get('version', '')),
                    'description': str(item.get('description', '') or '').strip(),
                    'min_app_version': normalize_version(item.get('min_app_version', 'v0.0.0')),
                    'download_url': str(item.get('download_url', '') or '').strip(),
                    'publisher': str(item.get('publisher', '') or '').strip(),
                    'homepage': str(item.get('homepage', '') or '').strip(),
                    'global_hook': bool(item.get('global_hook', False)),
                    'scene_bindings': _unique_text_list(item.get('scene_bindings', [])),
                }
            )
        return result

    def _load_json_file(self, path, *, default=None):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except Exception:
            return copy.deepcopy(default)

    def _write_json_file(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def load_registry_cache(self):
        raw = self._load_json_file(self.resolve_registry_cache_path(), default=DEFAULT_REGISTRY_PAYLOAD)
        return self.sanitize_registry_payload(raw)

    def save_registry_cache(self, payload):
        cleaned = self.sanitize_registry_payload(payload)
        self._write_json_file(self.resolve_registry_cache_path(), cleaned)
        return cleaned

    def get_installed_skill_records(self):
        if not self.config or not hasattr(self.config, 'get_skills_center_records'):
            return {}
        records = self.config.get_skills_center_records()
        return records if isinstance(records, dict) else {}

    def get_installed_skill_record(self, skill_id):
        records = self.get_installed_skill_records()
        return copy.deepcopy(records.get(str(skill_id or '').strip(), {}))

    def _set_installed_skill_record(self, skill_id, record):
        if not self.config or not hasattr(self.config, 'set_skills_center_record'):
            return
        self.config.set_skills_center_record(skill_id, record)

    def _delete_installed_skill_record(self, skill_id):
        if not self.config or not hasattr(self.config, 'delete_skills_center_record'):
            return
        self.config.delete_skills_center_record(skill_id)

    def _save_config(self):
        if self.config and hasattr(self.config, 'save'):
            self.config.save()

    def _iter_package_files(self, root_dir):
        result = []
        for current_root, _dirs, files in os.walk(root_dir):
            for file_name in files:
                abs_path = os.path.join(current_root, file_name)
                rel_path = os.path.relpath(abs_path, root_dir).replace('\\', '/')
                result.append((abs_path, rel_path))
        return sorted(result, key=lambda item: item[1])

    def _find_openskills_root(self, source_dir):
        discovered = []
        for current_root, _dirs, files in os.walk(source_dir):
            if 'skill.json' in files:
                continue
            file_names = {name.lower(): name for name in files}
            if 'skill.md' in file_names or '.openskills.json' in file_names:
                discovered.append(os.path.abspath(current_root))
        if len(discovered) == 1:
            return discovered[0]
        return ''

    @staticmethod
    def _parse_skill_markdown_metadata(path):
        metadata = {}
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                lines = handle.read(8192).splitlines()
        except Exception:
            return metadata
        if not lines or lines[0].strip() != '---':
            return metadata
        for line in lines[1:]:
            if line.strip() == '---':
                break
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            metadata[key.strip()] = value.strip().strip('"').strip("'")
        return metadata

    @staticmethod
    def _normalize_skill_id_from_text(text, default='imported-skill'):
        value = str(text or '').strip().lower()
        value = re.sub(r'[^a-z0-9._-]+', '-', value)
        value = re.sub(r'[-_.]{2,}', '-', value).strip('-_.')
        if not value or not re.match(r'^[a-z0-9]', value):
            value = default
        return value[:64].rstrip('-_.') or default

    def _load_openskills_metadata(self, root_dir):
        payload = self._load_json_file(os.path.join(root_dir, '.openskills.json'), default={})
        payload = payload if isinstance(payload, dict) else {}
        markdown_meta = self._parse_skill_markdown_metadata(os.path.join(root_dir, 'SKILL.md'))
        name = str(payload.get('name') or markdown_meta.get('name') or os.path.basename(root_dir)).strip()
        version = normalize_version(payload.get('version') or 'v1.0.0')
        description = str(payload.get('description') or markdown_meta.get('description') or name).strip()
        return {
            'id': self._normalize_skill_id_from_text(name),
            'name': name or 'Imported Skill',
            'version': version,
            'description': description,
            'publisher': str(payload.get('author') or '').strip(),
            'homepage': str(payload.get('homepage') or '').strip(),
        }

    def _remove_blocked_package_files(self, root_dir):
        for abs_path, _rel_path in self._iter_package_files(root_dir):
            lower_name = os.path.basename(abs_path).lower()
            ext = os.path.splitext(lower_name)[1]
            if lower_name in BLOCKED_FILE_NAMES or ext in BLOCKED_FILE_EXTENSIONS:
                try:
                    os.remove(abs_path)
                except OSError:
                    pass

    def _write_openskills_adapter_files(self, root_dir, metadata):
        scene_bindings = [
            scene_id
            for scene_id in (
                'paper_write.outline',
                'paper_write.section',
                'paper_write.abstract',
                'ai_reduce.transform',
                'plagiarism.transform',
                'polish.run_task',
            )
            if scene_id in SCENE_DEFS
        ]
        manifest = {
            'id': metadata['id'],
            'name': metadata['name'],
            'version': metadata['version'],
            'description': metadata['description'],
            'min_app_version': 'v1.0.0',
            'entry': {'module': 'entry', 'class': 'OpenSkillsAdapterSkill'},
            'priority': 20,
            'actions': [
                {
                    'id': 'run_with_topic',
                    'label': '按主题执行',
                    'description': '根据主题和补充要求调用原始 Skill 指令。',
                    'input_schema': {
                        'fields': [
                            {
                                'id': 'topic',
                                'label': '主题',
                                'type': 'text',
                                'required': True,
                                'placeholder': '输入论文主题或处理目标',
                            },
                            {
                                'id': 'requirements',
                                'label': '补充要求',
                                'type': 'textarea',
                                'required': False,
                                'placeholder': '输入格式、字数、学校规范或其他限制',
                            },
                        ]
                    },
                },
                {
                    'id': 'rewrite_text',
                    'label': '改写文本',
                    'description': '按原始 Skill 指令改写输入文本。',
                    'input_schema': {
                        'fields': [
                            {
                                'id': 'text',
                                'label': '待处理文本',
                                'type': 'textarea',
                                'required': True,
                                'placeholder': '粘贴需要处理的文本',
                            }
                        ]
                    },
                },
            ],
            'scene_bindings': scene_bindings,
            'global_hook': False,
            'publisher': metadata.get('publisher', ''),
            'homepage': metadata.get('homepage', ''),
        }
        self._write_json_file(os.path.join(root_dir, 'skill.json'), manifest)
        adapter_code = r'''# -*- coding: utf-8 -*-
from __future__ import annotations

import os


class OpenSkillsAdapterSkill:
    """将 SKILL.md 格式的技能适配到本应用运行时。"""

    def _read_text(self, relative_path, limit=12000):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, *str(relative_path or '').split('/'))
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return handle.read()[:limit].strip()
        except Exception:
            return ''

    def _collect_guides(self, scene_id):
        parts = [self._read_text('SKILL.md', limit=12000)]
        if str(scene_id or '').startswith('paper_write.'):
            for path in (
                'prompts/writer_guidelines.md',
                'prompts/thesis_structure.md',
                'prompts/reference_citation_prompt.md',
            ):
                text = self._read_text(path, limit=6000)
                if text:
                    parts.append(text)
        elif scene_id in {'ai_reduce.transform', 'plagiarism.transform', 'polish.run_task'}:
            for path in (
                'prompts/aigc_reducer_prompt.md',
                'prompts/humanizer_guidelines.md',
                'prompts/reducer_guidelines.md',
            ):
                text = self._read_text(path, limit=6000)
                if text:
                    parts.append(text)
        return '\n\n'.join(part for part in parts if part)

    def before_request(self, ctx):
        usage = ctx.get('usage_context', {}) or {}
        scene_id = str(usage.get('scene_id', '') or '')
        guides = self._collect_guides(scene_id)
        if not guides:
            return {}
        return {
            'system_append': '执行当前任务时，遵循已导入 Skill 的约束、流程和写作规范。',
            'prompt_append': '以下是已导入 Skill 的相关说明：\n\n' + guides,
            'metadata': {'adapter': 'openskills'},
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        guides = self._collect_guides('')
        if action_id == 'run_with_topic':
            prompt = self._join_sections(
                '请根据已导入 Skill 的说明执行任务。',
                self._format_block('Skill 说明', guides),
                '主题：\n' + inputs.get('topic', ''),
                '补充要求：\n' + inputs.get('requirements', ''),
            )
            return {'action_id': action_id, 'result': host.call_llm(prompt)}
        if action_id == 'rewrite_text':
            prompt = self._join_sections(
                '请根据已导入 Skill 的说明处理文本。',
                self._format_block('Skill 说明', guides),
                '待处理文本：\n' + inputs.get('text', ''),
            )
            return {'action_id': action_id, 'result': host.call_llm(prompt)}
        return {'error': f'unknown action: {action_id}'}

    @staticmethod
    def _format_block(title, content):
        return f'【{title}】\n{content}' if content else ''

    @staticmethod
    def _join_sections(*sections):
        return '\n\n'.join(str(section).strip() for section in sections if str(section or '').strip())
'''
        with open(os.path.join(root_dir, 'entry.py'), 'w', encoding='utf-8') as handle:
            handle.write(adapter_code)

    def _adapt_openskills_package(self, source_dir):
        root_dir = self._find_openskills_root(source_dir)
        if not root_dir:
            return ''
        metadata = self._load_openskills_metadata(root_dir)
        self._remove_blocked_package_files(root_dir)
        self._write_openskills_adapter_files(root_dir, metadata)
        return root_dir

    def _resolve_source_root(self, source_dir):
        direct_manifest = os.path.join(source_dir, 'skill.json')
        if os.path.isfile(direct_manifest):
            return os.path.abspath(source_dir)

        discovered = []
        for current_root, _dirs, files in os.walk(source_dir):
            if 'skill.json' in files:
                discovered.append(os.path.abspath(current_root))
        if len(discovered) == 1:
            return discovered[0]
        if not discovered:
            raise SkillValidationError('未找到 skill.json。请确认 ZIP 或目录中包含技能包根目录。')
        raise SkillValidationError('发现多个 skill.json，无法判断技能包根目录。')

    def _validate_package_files(self, root_dir):
        rel_paths = []
        for abs_path, rel_path in self._iter_package_files(root_dir):
            normalized = _normalize_rel_path(rel_path)
            if (
                not normalized
                or normalized == '..'
                or normalized.startswith('../')
                or normalized.startswith('/')
                or re.match(r'^[A-Za-z]:/', normalized)
            ):
                raise SkillValidationError(f'技能包包含非法路径：{rel_path}')
            if os.path.islink(abs_path):
                raise SkillValidationError(f'技能包不允许包含符号链接：{rel_path}')
            lower_name = os.path.basename(normalized).lower()
            ext = os.path.splitext(lower_name)[1]
            if lower_name in BLOCKED_FILE_NAMES or ext in BLOCKED_FILE_EXTENSIONS:
                raise SkillValidationError(f'技能包包含被禁止的文件：{rel_path}')
            if ext and ext not in ALLOWED_STATIC_EXTENSIONS:
                raise SkillValidationError(f'技能包包含不受支持的文件类型：{rel_path}')
            rel_paths.append(normalized)
        if 'skill.json' not in rel_paths:
            raise SkillValidationError('技能包缺少 skill.json。')
        return rel_paths

    def _load_manifest_from_dir(self, root_dir):
        manifest_path = os.path.join(root_dir, 'skill.json')
        payload = self._load_json_file(manifest_path, default=None)
        if payload is None:
            raise SkillValidationError('skill.json 无法读取。')
        return self.sanitize_skill_manifest(payload)

    def _resolve_entry_file(self, root_dir, module_name):
        rel_module_path = str(module_name or '').strip().replace('.', os.sep)
        candidates = [
            os.path.join(root_dir, f'{rel_module_path}.py'),
            os.path.join(root_dir, rel_module_path, '__init__.py'),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return os.path.abspath(path)
        raise SkillValidationError(f'入口模块不存在：{module_name}')

    def _build_module_spec(self, skill_id, entry_file, module_name):
        module_key = f'paperlab_skill_{str(skill_id).replace(".", "_").replace("-", "_")}_{module_name.replace(".", "_")}'
        if os.path.basename(entry_file) == '__init__.py':
            return importlib.util.spec_from_file_location(
                module_key,
                entry_file,
                submodule_search_locations=[os.path.dirname(entry_file)],
            )
        return importlib.util.spec_from_file_location(module_key, entry_file)

    def _load_skill_class(self, root_dir, manifest):
        entry_module = manifest.get('entry', {}).get('module', '')
        entry_class_name = manifest.get('entry', {}).get('class', '')
        entry_file = self._resolve_entry_file(root_dir, entry_module)
        spec = self._build_module_spec(manifest.get('id', ''), entry_file, entry_module)
        if spec is None or spec.loader is None:
            raise SkillValidationError(f'入口模块无法加载：{entry_module}')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        skill_class = getattr(module, entry_class_name, None)
        if skill_class is None:
            raise SkillValidationError(f'入口类不存在：{entry_class_name}')
        return skill_class

    def validate_skill_directory(self, source_dir):
        root_dir = self._resolve_source_root(source_dir)
        self._validate_package_files(root_dir)
        manifest = self._load_manifest_from_dir(root_dir)
        if compare_versions(APP_VERSION, manifest.get('min_app_version', 'v0.0.0')) < 0:
            raise SkillValidationError(
                f'当前程序版本为 {APP_VERSION}，低于技能要求的最低版本 {manifest.get("min_app_version", "v0.0.0")}。'
            )
        self._load_skill_class(root_dir, manifest)
        return root_dir, manifest

    def _safe_extract_zip(self, zip_path, temp_dir):
        with zipfile.ZipFile(zip_path, mode='r') as archive:
            for member in archive.infolist():
                normalized = _normalize_rel_path(member.filename)
                if not normalized:
                    continue
                if (
                    normalized == '..'
                    or normalized.startswith('../')
                    or normalized.startswith('/')
                    or re.match(r'^[A-Za-z]:/', normalized)
                ):
                    raise SkillValidationError(f'ZIP 中包含非法路径：{member.filename}')
                target_path = os.path.join(temp_dir, normalized)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                if member.is_dir():
                    os.makedirs(target_path, exist_ok=True)
                    continue
                with archive.open(member, 'r') as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        return temp_dir

    def _copy_skill_package(self, source_root, target_root):
        if os.path.exists(target_root):
            shutil.rmtree(target_root)
        shutil.copytree(source_root, target_root)

    def _build_installed_record(self, manifest, previous_record=None, *, source_type, source_label=''):
        previous_record = dict(previous_record or {})
        available_scenes = list(manifest.get('scene_bindings', []))
        bound_scene_ids = previous_record.get('bound_scene_ids', previous_record.get('scene_bindings', []))
        bound_scene_ids = _unique_text_list(bound_scene_ids)
        if not bound_scene_ids:
            bound_scene_ids = list(available_scenes)

        installed_at = _coerce_int(previous_record.get('installed_at', 0), 0) or _now_ts()
        return {
            'id': manifest.get('id', ''),
            'name': manifest.get('name', '') or manifest.get('id', ''),
            'version': manifest.get('version', ''),
            'description': manifest.get('description', ''),
            'min_app_version': manifest.get('min_app_version', 'v0.0.0'),
            'priority': _coerce_int(manifest.get('priority', 0), 0),
            'source_type': str(source_type or 'local').strip() or 'local',
            'source_label': str(source_label or '').strip(),
            'installed_at': installed_at,
            'updated_at': _now_ts(),
            'last_checked_at': _coerce_int(previous_record.get('last_checked_at', 0), 0),
            'enabled': bool(previous_record.get('enabled', False)),
            'global_enabled': bool(previous_record.get('global_enabled', False)) and bool(manifest.get('global_hook', False)),
            'global_hook': bool(manifest.get('global_hook', False)),
            'scene_bindings': available_scenes,
            'bound_scene_ids': bound_scene_ids,
            'actions_count': len(list(manifest.get('actions', []) or [])),
            'entry_module': manifest.get('entry', {}).get('module', ''),
            'entry_class': manifest.get('entry', {}).get('class', ''),
            'publisher': manifest.get('publisher', ''),
            'homepage': manifest.get('homepage', ''),
        }

    def clear_skill_cache(self, skill_id=None):
        with self._lock:
            if skill_id is None:
                self._instance_cache.clear()
                return
            self._instance_cache.pop(str(skill_id or '').strip(), None)

    def install_skill_from_directory(self, source_dir, *, source_type='directory', source_label=''):
        source_root, manifest = self.validate_skill_directory(source_dir)
        skill_id = manifest.get('id', '')
        target_root = self.resolve_skill_package_dir(skill_id)
        temp_target = f'{target_root}__tmp__'
        backup_target = f'{target_root}__bak__'
        previous_record = self.get_installed_skill_record(skill_id)
        replaced = bool(previous_record)

        if os.path.exists(temp_target):
            shutil.rmtree(temp_target)
        if os.path.exists(backup_target):
            shutil.rmtree(backup_target)

        self._copy_skill_package(source_root, temp_target)
        try:
            if os.path.exists(target_root):
                os.replace(target_root, backup_target)
            os.replace(temp_target, target_root)
        except Exception:
            if os.path.exists(temp_target):
                shutil.rmtree(temp_target, ignore_errors=True)
            if os.path.exists(backup_target) and not os.path.exists(target_root):
                os.replace(backup_target, target_root)
            raise
        finally:
            if os.path.exists(backup_target):
                shutil.rmtree(backup_target, ignore_errors=True)

        record = self._build_installed_record(
            manifest,
            previous_record=previous_record,
            source_type=source_type,
            source_label=source_label or os.path.abspath(source_dir),
        )
        self._set_installed_skill_record(skill_id, record)
        self._save_config()
        self.clear_skill_cache(skill_id)
        self._log(
            f'[skills_install] skill={skill_id} version={manifest.get("version", "")} replaced={int(replaced)} source={source_type}'
        )
        return self.build_skill_view(record, manifest=manifest)

    def install_skill_from_zip(self, zip_path):
        temp_dir = self._create_managed_temp_dir('zip_')
        try:
            self._safe_extract_zip(zip_path, temp_dir)
            self._adapt_openskills_package(temp_dir)
            return self.install_skill_from_directory(
                temp_dir,
                source_type='zip',
                source_label=os.path.abspath(zip_path),
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def inspect_skill_zip(self, zip_path):
        temp_dir = self._create_managed_temp_dir('inspect_zip_')
        try:
            self._safe_extract_zip(zip_path, temp_dir)
            self._adapt_openskills_package(temp_dir)
            _source_root, manifest = self.validate_skill_directory(temp_dir)
            return manifest
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def delete_skill(self, skill_id):
        skill_id = str(skill_id or '').strip()
        if not skill_id:
            raise SkillValidationError('技能 id 不能为空。')
        package_dir = self.resolve_skill_package_dir(skill_id)
        data_dir = self.resolve_skill_data_dir(skill_id)
        if os.path.isdir(package_dir):
            shutil.rmtree(package_dir, ignore_errors=True)
        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir, ignore_errors=True)
        self._delete_installed_skill_record(skill_id)
        self._save_config()
        self.clear_skill_cache(skill_id)
        self._log(f'[skills_delete] skill={skill_id}')

    def update_skill_state(self, skill_id, *, enabled=None, global_enabled=None, bound_scene_ids=None, last_checked_at=None):
        skill_id = str(skill_id or '').strip()
        record = self.get_installed_skill_record(skill_id)
        if not record:
            raise SkillValidationError('目标技能不存在。')
        if enabled is not None:
            record['enabled'] = bool(enabled)
        if global_enabled is not None:
            record['global_enabled'] = bool(global_enabled) and bool(record.get('global_hook', False))
        if bound_scene_ids is not None:
            record['bound_scene_ids'] = _unique_text_list(bound_scene_ids)
        if last_checked_at is not None:
            record['last_checked_at'] = _coerce_int(last_checked_at, 0)
        record['updated_at'] = _now_ts()
        self._set_installed_skill_record(skill_id, record)
        self._save_config()
        return record

    def get_skill_manifest(self, skill_id):
        skill_id = str(skill_id or '').strip()
        if not skill_id:
            return None
        package_dir = self.resolve_skill_package_dir(skill_id)
        manifest_path = os.path.join(package_dir, 'skill.json')
        if not os.path.isfile(manifest_path):
            return None
        payload = self._load_json_file(manifest_path, default=None)
        if payload is None:
            return None
        try:
            return self.sanitize_skill_manifest(payload)
        except SkillValidationError:
            return None

    def build_skill_view(self, record, *, manifest=None, registry_entry=None):
        record = dict(record or {})
        manifest = manifest or self.get_skill_manifest(record.get('id', ''))
        if manifest:
            record.update(
                {
                    'name': manifest.get('name', record.get('name', '')),
                    'version': manifest.get('version', record.get('version', '')),
                    'description': manifest.get('description', record.get('description', '')),
                    'priority': manifest.get('priority', record.get('priority', 0)),
                    'scene_bindings': list(manifest.get('scene_bindings', [])),
                    'global_hook': bool(manifest.get('global_hook', record.get('global_hook', False))),
                    'actions_count': len(list(manifest.get('actions', []) or [])),
                }
            )
        skill_id = str(record.get('id', '') or '').strip()
        registry_entry = dict(registry_entry or {})
        installed_version = normalize_version(record.get('version', 'v0.0.0'))
        latest_version = normalize_version(registry_entry.get('version', installed_version or 'v0.0.0'))
        has_update = bool(registry_entry) and compare_versions(installed_version, latest_version) < 0
        return {
            **record,
            'id': skill_id,
            'package_dir': self.resolve_skill_package_dir(skill_id),
            'data_dir': self.resolve_skill_data_dir(skill_id),
            'manifest': copy.deepcopy(manifest) if manifest else None,
            'registry_entry': registry_entry or None,
            'latest_version': latest_version,
            'has_update': has_update,
            'is_installed': bool(skill_id),
            'is_local_only': bool(record.get('source_type') in {'zip', 'directory'} and not registry_entry),
            'bound_scene_ids': _unique_text_list(record.get('bound_scene_ids', []), allowed=record.get('scene_bindings', [])),
        }

    def list_installed_skills(self, registry_payload=None):
        registry_map = {
            item['id']: item
            for item in list((registry_payload or self.load_registry_cache()).get('skills', []) or [])
            if isinstance(item, dict) and item.get('id')
        }
        result = []
        for skill_id, record in sorted(self.get_installed_skill_records().items(), key=lambda item: item[0]):
            view = self.build_skill_view(record, registry_entry=registry_map.get(skill_id))
            view['is_missing_package'] = not os.path.isdir(view['package_dir'])
            result.append(view)
        result.sort(key=lambda item: (str(item.get('name', '') or '').lower(), item.get('id', '')))
        return result

    def list_registry_skills(self, payload=None):
        payload = self.sanitize_registry_payload(payload or self.load_registry_cache())
        installed = self.get_installed_skill_records()
        result = []
        for item in payload.get('skills', []):
            skill_id = item.get('id', '')
            if skill_id in installed:
                result.append(self.build_skill_view(installed[skill_id], registry_entry=item))
            else:
                result.append(
                    {
                        'id': skill_id,
                        'name': item.get('name', skill_id),
                        'version': item.get('version', ''),
                        'latest_version': item.get('version', ''),
                        'description': item.get('description', ''),
                        'min_app_version': item.get('min_app_version', ''),
                        'publisher': item.get('publisher', ''),
                        'homepage': item.get('homepage', ''),
                        'global_hook': bool(item.get('global_hook', False)),
                        'scene_bindings': list(item.get('scene_bindings', [])),
                        'registry_entry': item,
                        'manifest': None,
                        'is_installed': False,
                        'has_update': False,
                        'enabled': False,
                        'global_enabled': False,
                        'bound_scene_ids': [],
                        'source_type': 'registry',
                        'source_label': item.get('download_url', ''),
                        'actions_count': 0,
                    }
                )
        result.sort(key=lambda item: (str(item.get('name', '') or '').lower(), item.get('id', '')))
        return result

    def count_updates(self, payload=None):
        return sum(1 for item in self.list_installed_skills(registry_payload=payload) if item.get('has_update'))

    def mark_all_checked(self, checked_at=None):
        timestamp = _coerce_int(checked_at, 0) or _now_ts()
        for skill_id in list(self.get_installed_skill_records().keys()):
            self.update_skill_state(skill_id, last_checked_at=timestamp)
        return timestamp

    def _load_skill_instance(self, skill_id):
        skill_id = str(skill_id or '').strip()
        if not skill_id:
            raise SkillExecutionError('技能 id 不能为空。')
        with self._lock:
            cached = self._instance_cache.get(skill_id)
            if cached is not None:
                return cached

            manifest = self.get_skill_manifest(skill_id)
            if not manifest:
                raise SkillExecutionError('技能清单缺失或无效。')
            package_dir = self.resolve_skill_package_dir(skill_id)
            skill_class = self._load_skill_class(package_dir, manifest)
            try:
                instance = skill_class()
            except Exception as exc:
                raise SkillExecutionError(f'技能实例化失败：{exc}') from exc
            self._instance_cache[skill_id] = instance
            return instance

    def _iter_applicable_skill_views(self, usage_context, *, scope):
        usage_context = dict(usage_context or {})
        if usage_context.get('skip_skills'):
            return []
        scene_id = str(usage_context.get('scene_id', '') or '').strip()
        records = self.list_installed_skills()
        result = []
        for record in records:
            if record.get('is_missing_package'):
                continue
            if not record.get('enabled', False):
                continue
            if scope == 'global':
                if not record.get('global_enabled', False) or not record.get('global_hook', False):
                    continue
            elif scope == 'scene':
                if not scene_id:
                    continue
                if scene_id not in set(record.get('bound_scene_ids', [])):
                    continue
            else:
                continue
            result.append(record)
        result.sort(key=lambda item: (_coerce_int(item.get('priority', 0), 0), item.get('id', '')))
        return result

    @staticmethod
    def _sanitize_before_request_patch(patch):
        if not isinstance(patch, dict):
            return {
                'system_append': '',
                'prompt_append': '',
                'temperature': None,
                'max_tokens': None,
                'metadata': {},
            }
        temperature = _coerce_number(patch.get('temperature'))
        max_tokens = _coerce_int(patch.get('max_tokens'), 0) if patch.get('max_tokens', None) not in (None, '') else None
        return {
            'system_append': str(patch.get('system_append', '') or ''),
            'prompt_append': str(patch.get('prompt_append', '') or ''),
            'temperature': temperature,
            'max_tokens': max_tokens if max_tokens and max_tokens > 0 else None,
            'metadata': _safe_copy_json(patch.get('metadata', {})),
        }

    @staticmethod
    def _sanitize_after_response_patch(patch):
        if not isinstance(patch, dict):
            return {
                'response_text': None,
                'metadata': {},
            }
        response_text = patch.get('response_text', None)
        return {
            'response_text': str(response_text) if response_text is not None else None,
            'metadata': _safe_copy_json(patch.get('metadata', {})),
        }

    def _merge_skill_metadata(self, metadata, skill_id, patch_metadata):
        if not patch_metadata:
            return metadata
        metadata = _safe_copy_json(metadata)
        skill_bucket = metadata.setdefault('skills', {})
        current = skill_bucket.get(skill_id, {})
        if isinstance(current, dict) and isinstance(patch_metadata, dict):
            merged = dict(current)
            merged.update(copy.deepcopy(patch_metadata))
            skill_bucket[skill_id] = merged
        else:
            skill_bucket[skill_id] = copy.deepcopy(patch_metadata)
        return metadata

    def prepare_request(self, prompt, system='', *, temperature=None, max_tokens=None, usage_context=None):
        usage_context = dict(usage_context or {})
        result = {
            'prompt': str(prompt or ''),
            'system': str(system or ''),
            'temperature': temperature,
            'max_tokens': max_tokens,
            'metadata': {},
            'applied_skills': [],
        }
        if usage_context.get('skip_skills'):
            return result

        for scope in ('global', 'scene'):
            for skill_view in self._iter_applicable_skill_views(usage_context, scope=scope):
                skill_id = skill_view.get('id', '')
                try:
                    instance = self._load_skill_instance(skill_id)
                except Exception as exc:
                    self._log(f'[skills_hook_error] stage=load skill={skill_id} error={exc}', level='WARN')
                    continue
                hook = getattr(instance, 'before_request', None)
                if not callable(hook):
                    continue
                ctx = {
                    'skill_id': skill_id,
                    'scope': scope,
                    'usage_context': copy.deepcopy(usage_context),
                    'prompt': result['prompt'],
                    'system': result['system'],
                    'temperature': result['temperature'],
                    'max_tokens': result['max_tokens'],
                    'metadata': copy.deepcopy(result['metadata']),
                }
                try:
                    patch = self._sanitize_before_request_patch(hook(copy.deepcopy(ctx)))
                except Exception as exc:
                    self._log(f'[skills_hook_error] stage=before_request skill={skill_id} error={exc}', level='WARN')
                    continue

                if patch['system_append']:
                    result['system'] = f'{result["system"]}\n{patch["system_append"]}'.strip() if result['system'] else patch['system_append']
                if patch['prompt_append']:
                    result['prompt'] = f'{result["prompt"]}\n{patch["prompt_append"]}'.strip() if result['prompt'] else patch['prompt_append']
                if patch['temperature'] is not None:
                    result['temperature'] = patch['temperature']
                if patch['max_tokens'] is not None:
                    result['max_tokens'] = patch['max_tokens']
                result['metadata'] = self._merge_skill_metadata(result['metadata'], skill_id, patch['metadata'])
                result['applied_skills'].append({'id': skill_id, 'scope': scope, 'stage': 'before_request'})
        return result

    def finalize_response(self, response_text, *, request_state=None, usage_context=None):
        usage_context = dict(usage_context or {})
        request_state = dict(request_state or {})
        result_text = str(response_text or '')
        result = {
            'text': result_text,
            'metadata': _safe_copy_json(request_state.get('metadata', {})),
            'applied_skills': list(request_state.get('applied_skills', [])),
        }
        if usage_context.get('skip_skills'):
            return result

        for scope in ('scene', 'global'):
            for skill_view in self._iter_applicable_skill_views(usage_context, scope=scope):
                skill_id = skill_view.get('id', '')
                try:
                    instance = self._load_skill_instance(skill_id)
                except Exception as exc:
                    self._log(f'[skills_hook_error] stage=load skill={skill_id} error={exc}', level='WARN')
                    continue
                hook = getattr(instance, 'after_response', None)
                if not callable(hook):
                    continue
                ctx = {
                    'skill_id': skill_id,
                    'scope': scope,
                    'usage_context': copy.deepcopy(usage_context),
                    'prompt': str(request_state.get('prompt', '') or ''),
                    'system': str(request_state.get('system', '') or ''),
                    'temperature': request_state.get('temperature', None),
                    'max_tokens': request_state.get('max_tokens', None),
                    'metadata': copy.deepcopy(result['metadata']),
                }
                try:
                    patch = self._sanitize_after_response_patch(hook(copy.deepcopy(ctx), result['text']))
                except Exception as exc:
                    self._log(f'[skills_hook_error] stage=after_response skill={skill_id} error={exc}', level='WARN')
                    continue
                if patch['response_text'] is not None:
                    result['text'] = patch['response_text']
                result['metadata'] = self._merge_skill_metadata(result['metadata'], skill_id, patch['metadata'])
                result['applied_skills'].append({'id': skill_id, 'scope': scope, 'stage': 'after_response'})
        return result

    @staticmethod
    def _validate_action_inputs(action, inputs):
        inputs = dict(inputs or {})
        payload = {}
        for field in action.get('input_schema', {}).get('fields', []):
            field_id = field.get('id', '')
            field_type = field.get('type', 'text')
            raw_value = inputs.get(field_id, field.get('default'))
            if field_type == 'checkbox':
                value = bool(raw_value)
            elif field_type == 'number':
                value = _coerce_number(raw_value)
                if raw_value not in (None, '') and value is None:
                    raise SkillExecutionError(f'字段「{field.get("label", field_id)}」不是有效数字。')
                if value is not None and field.get('min', None) is not None and value < field['min']:
                    raise SkillExecutionError(f'字段「{field.get("label", field_id)}」不能小于 {field["min"]}。')
                if value is not None and field.get('max', None) is not None and value > field['max']:
                    raise SkillExecutionError(f'字段「{field.get("label", field_id)}」不能大于 {field["max"]}。')
            else:
                value = '' if raw_value is None else str(raw_value)
                if field_type == 'select':
                    allowed_values = {item['value'] for item in field.get('options', [])}
                    if value and value not in allowed_values:
                        raise SkillExecutionError(f'字段「{field.get("label", field_id)}」包含无效选项。')
            if field.get('required', False):
                if field_type == 'checkbox':
                    pass
                elif value in (None, ''):
                    raise SkillExecutionError(f'字段「{field.get("label", field_id)}」不能为空。')
            payload[field_id] = value
        return payload

    def run_action(self, skill_id, action_id, inputs=None):
        skill_view = next((item for item in self.list_installed_skills() if item.get('id') == skill_id), None)
        if not skill_view:
            raise SkillExecutionError('目标技能不存在。')
        if not skill_view.get('enabled', False):
            raise SkillExecutionError('该技能尚未启用。')
        manifest = skill_view.get('manifest') or self.get_skill_manifest(skill_id)
        if not manifest:
            raise SkillExecutionError('技能清单缺失或无效。')
        action = next((item for item in manifest.get('actions', []) if item.get('id') == action_id), None)
        if not action:
            raise SkillExecutionError('目标动作不存在。')
        action_inputs = self._validate_action_inputs(action, inputs or {})
        instance = self._load_skill_instance(skill_id)
        runner = getattr(instance, 'run_action', None)
        if not callable(runner):
            raise SkillExecutionError('该技能未实现 run_action。')
        host = SkillHost(self, skill_id, action_id)
        try:
            result = runner(action_id, action_inputs, host)
        except Exception as exc:
            self._log(f'[skills_action_error] skill={skill_id} action={action_id} error={exc}', level='WARN')
            raise SkillExecutionError(str(exc)) from exc
        self._log(f'[skills_action] skill={skill_id} action={action_id}')
        return result

    def download_registry_skill_zip(self, registry_entry):
        if not isinstance(registry_entry, dict):
            raise SkillExecutionError('远程技能条目无效。')
        download_url = str(registry_entry.get('download_url', '') or '').strip()
        if not download_url:
            raise SkillExecutionError('当前技能没有可用的下载地址。')
        parsed = urllib.parse.urlsplit(download_url)
        if parsed.scheme not in {'http', 'https'}:
            raise SkillExecutionError('下载地址必须使用 http 或 https。')
        temp_dir = self._create_managed_temp_dir('download_')
        try:
            zip_path = os.path.join(temp_dir, 'skill.zip')
            request = urllib.request.Request(download_url, method='GET')
            request.add_header('User-Agent', f'PaperLab/{APP_VERSION}')
            with urllib.request.urlopen(request, timeout=30) as response, open(zip_path, 'wb') as handle:
                shutil.copyfileobj(response, handle)
            return self.install_skill_from_zip(zip_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
