# -*- coding: utf-8 -*-
"""
本地知识库存储与文本提取。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from modules.prompt_center import SCENE_DEFS


PAPER_WRITE_SCENE_IDS = tuple(
    scene_id for scene_id in SCENE_DEFS.keys() if str(scene_id).startswith('paper_write.')
)
ALL_KB_SCENE_IDS = tuple(SCENE_DEFS.keys())


def append_knowledge_context(prompt, knowledge_context=None):
    """将知识库上下文注入到提示词末尾。

    Args:
        prompt: 已渲染的用户提示词
        knowledge_context: build_context() 返回的字典，可为 None

    Returns:
        追加了知识库资料和使用约束的提示词
    """
    if not isinstance(knowledge_context, dict):
        return prompt
    context_text = str(knowledge_context.get('context_text', '') or '').strip()
    if not context_text:
        return prompt
    project_name = str(knowledge_context.get('project_name', '') or '').strip()
    header = '【知识库资料】'
    if project_name:
        header = f'{header}\n项目：{project_name}'
    constraints = (
        '【使用约束】\n'
        '1. 仅在资料与当前任务直接相关时使用知识库内容。\n'
        '2. 不得编造知识库资料中不存在的来源、数据或结论。\n'
        '3. 若资料不足以支持某个判断，应按常规要求处理，不要声称资料已经提供依据。'
    )
    return f'{prompt}\n\n{header}\n{context_text}\n\n{constraints}'.strip()
DEFAULT_TOTAL_CHAR_LIMIT = 12000
DEFAULT_PER_DOCUMENT_CHAR_LIMIT = 4000


class KnowledgeBaseError(Exception):
    """知识库操作失败。"""


def _now_ts() -> int:
    return int(time.time())


def _new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:12]}'


def _normalize_text(value) -> str:
    return str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()


def _unique_text_list(values, *, allowed=None) -> list[str]:
    allowed_set = set(allowed or [])
    result = []
    for value in list(values or []):
        text = str(value or '').strip()
        if not text:
            continue
        if allowed_set and text not in allowed_set:
            continue
        if text not in result:
            result.append(text)
    return result


def _parse_tags(value) -> list[str]:
    if isinstance(value, str):
        raw_items = value.replace('，', ',').replace(';', ',').replace('；', ',').split(',')
    else:
        raw_items = list(value or [])
    return _unique_text_list(raw_items)


class KnowledgeBaseStore:
    """以 JSON 索引和纯文本文件保存知识库项目与资料。"""

    INDEX_FILE_NAME = 'index.json'

    def __init__(self, data_dir, log_callback=None):
        self.data_dir = os.path.abspath(os.path.expanduser(str(data_dir or '').strip() or '.'))
        self.root_dir = os.path.join(self.data_dir, 'knowledge_base')
        self.documents_dir = os.path.join(self.root_dir, 'documents')
        self.index_path = os.path.join(self.root_dir, self.INDEX_FILE_NAME)
        self.log_callback = log_callback
        os.makedirs(self.documents_dir, exist_ok=True)

    def _log(self, message, level='INFO'):
        if callable(self.log_callback):
            self.log_callback(message, level=level)

    def _default_index(self):
        return {
            'version': 1,
            'projects': [],
            'documents': [],
        }

    def _load_index(self):
        if not os.path.exists(self.index_path):
            return self._default_index()
        try:
            with open(self.index_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        except Exception as exc:
            raise KnowledgeBaseError(f'读取知识库索引失败：{exc}') from exc
        return self._sanitize_index(payload)

    def _save_index(self, payload):
        payload = self._sanitize_index(payload)
        os.makedirs(self.root_dir, exist_ok=True)
        temp_path = f'{self.index_path}.tmp'
        with open(temp_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.index_path)

    def _sanitize_index(self, payload):
        if not isinstance(payload, dict):
            payload = {}
        projects = []
        seen_projects = set()
        for item in list(payload.get('projects', []) or []):
            if not isinstance(item, dict):
                continue
            project_id = str(item.get('id', '') or '').strip()
            if not project_id or project_id in seen_projects:
                continue
            seen_projects.add(project_id)
            now = _now_ts()
            raw_bound_scene_ids = item.get('bound_scene_ids', None)
            if raw_bound_scene_ids is None:
                bound_scene_ids = list(ALL_KB_SCENE_IDS)
            else:
                bound_scene_ids = _unique_text_list(raw_bound_scene_ids, allowed=SCENE_DEFS.keys())
            projects.append({
                'id': project_id,
                'name': str(item.get('name', '') or '').strip() or project_id,
                'description': str(item.get('description', '') or '').strip(),
                'active': bool(item.get('active', False)),
                'bound_scene_ids': bound_scene_ids,
                'created_at': int(item.get('created_at', now) or now),
                'updated_at': int(item.get('updated_at', now) or now),
            })

        active_projects = [p for p in projects if p['active']]
        if len(active_projects) > 1:
            for project in projects:
                project['active'] = False

        project_ids = {item['id'] for item in projects}
        documents = []
        seen_documents = set()
        for item in list(payload.get('documents', []) or []):
            if not isinstance(item, dict):
                continue
            document_id = str(item.get('id', '') or '').strip()
            project_id = str(item.get('project_id', '') or '').strip()
            if not document_id or document_id in seen_documents or project_id not in project_ids:
                continue
            seen_documents.add(document_id)
            now = _now_ts()
            raw_bound_scene_ids = item.get('bound_scene_ids', None)
            if raw_bound_scene_ids is None:
                bound_scene_ids = list(ALL_KB_SCENE_IDS)
            else:
                bound_scene_ids = _unique_text_list(raw_bound_scene_ids, allowed=SCENE_DEFS.keys())
            documents.append({
                'id': document_id,
                'project_id': project_id,
                'title': str(item.get('title', '') or '').strip() or document_id,
                'source_type': str(item.get('source_type', '') or '').strip().lower(),
                'source_path': str(item.get('source_path', '') or '').strip(),
                'text_path': str(item.get('text_path', '') or '').strip(),
                'tags': _parse_tags(item.get('tags', [])),
                'enabled': bool(item.get('enabled', True)),
                'bound_scene_ids': bound_scene_ids,
                'created_at': int(item.get('created_at', now) or now),
                'updated_at': int(item.get('updated_at', now) or now),
                'char_count': max(int(item.get('char_count', 0) or 0), 0),
            })

        return {
            'version': 1,
            'projects': projects,
            'documents': documents,
        }

    def list_projects(self):
        payload = self._load_index()
        return sorted(payload['projects'], key=lambda item: (item.get('updated_at', 0), item.get('name', '')), reverse=True)

    def get_project(self, project_id):
        project_id = str(project_id or '').strip()
        for project in self._load_index()['projects']:
            if project['id'] == project_id:
                return dict(project)
        return None

    def create_project(self, name, description=''):
        name = str(name or '').strip()
        if not name:
            raise KnowledgeBaseError('项目名称不能为空')
        payload = self._load_index()
        now = _now_ts()
        project = {
            'id': _new_id('proj'),
            'name': name,
            'description': str(description or '').strip(),
            'active': False,
            'bound_scene_ids': list(ALL_KB_SCENE_IDS),
            'created_at': now,
            'updated_at': now,
        }
        payload['projects'].append(project)
        self._save_index(payload)
        return dict(project)

    def update_project(self, project_id, *, name=None, description=None, bound_scene_ids=None, active=None):
        payload = self._load_index()
        for project in payload['projects']:
            if project['id'] != project_id:
                continue
            if name is not None:
                normalized_name = str(name or '').strip()
                if not normalized_name:
                    raise KnowledgeBaseError('项目名称不能为空')
                project['name'] = normalized_name
            if description is not None:
                project['description'] = str(description or '').strip()
            if bound_scene_ids is not None:
                project['bound_scene_ids'] = _unique_text_list(bound_scene_ids, allowed=SCENE_DEFS.keys())
            if active is not None:
                project['active'] = bool(active)
            project['updated_at'] = _now_ts()
            self._save_index(payload)
            return dict(project)
        raise KnowledgeBaseError('知识库项目不存在')

    def get_active_project(self):
        for project in self._load_index()['projects']:
            if project.get('active'):
                return dict(project)
        return None

    def set_active_project(self, project_id):
        project_id = str(project_id or '').strip()
        payload = self._load_index()
        found = False
        for project in payload['projects']:
            if project['id'] == project_id:
                project['active'] = True
                found = True
            else:
                project['active'] = False
        if not found:
            raise KnowledgeBaseError('知识库项目不存在')
        self._save_index(payload)

    def delete_project(self, project_id):
        payload = self._load_index()
        project_id = str(project_id or '').strip()
        if not any(project['id'] == project_id for project in payload['projects']):
            raise KnowledgeBaseError('知识库项目不存在')
        removed_docs = [doc for doc in payload['documents'] if doc.get('project_id') == project_id]
        payload['projects'] = [project for project in payload['projects'] if project['id'] != project_id]
        payload['documents'] = [doc for doc in payload['documents'] if doc.get('project_id') != project_id]
        self._save_index(payload)
        for document in removed_docs:
            self._delete_text_file(document)
        return True

    def list_documents(self, project_id=None, *, scene_id=None, enabled_only=False):
        payload = self._load_index()
        project_id = str(project_id or '').strip()
        scene_id = str(scene_id or '').strip()
        documents = []
        for document in payload['documents']:
            if project_id and document.get('project_id') != project_id:
                continue
            if enabled_only and not document.get('enabled', True):
                continue
            if scene_id and scene_id not in set(document.get('bound_scene_ids', [])):
                continue
            documents.append(dict(document))
        return sorted(documents, key=lambda item: (item.get('updated_at', 0), item.get('title', '')), reverse=True)

    def get_document(self, document_id):
        document_id = str(document_id or '').strip()
        for document in self._load_index()['documents']:
            if document['id'] == document_id:
                return dict(document)
        return None

    def import_document(
        self,
        project_id,
        source_path,
        *,
        title=None,
        tags=None,
        bound_scene_ids=None,
        enabled=True,
    ):
        project = self.get_project(project_id)
        if not project:
            raise KnowledgeBaseError('知识库项目不存在')
        normalized_path = os.path.abspath(os.path.expanduser(str(source_path or '').strip()))
        if not os.path.exists(normalized_path):
            raise KnowledgeBaseError('资料文件不存在')
        text, source_type = self._extract_document_text(normalized_path)
        if not text:
            raise KnowledgeBaseError('资料文件没有可导入的文本内容')

        payload = self._load_index()
        now = _now_ts()
        document_id = _new_id('doc')
        text_rel_path = f'documents/{document_id}.txt'
        text_abs_path = os.path.join(self.root_dir, text_rel_path)
        self._write_text_file(text_abs_path, text)
        if bound_scene_ids is None:
            normalized_scene_ids = list(ALL_KB_SCENE_IDS)
        else:
            normalized_scene_ids = _unique_text_list(bound_scene_ids, allowed=SCENE_DEFS.keys())
        document = {
            'id': document_id,
            'project_id': project['id'],
            'title': str(title or '').strip() or os.path.splitext(os.path.basename(normalized_path))[0],
            'source_type': source_type,
            'source_path': normalized_path,
            'text_path': text_rel_path,
            'tags': _parse_tags(tags or []),
            'enabled': bool(enabled),
            'bound_scene_ids': normalized_scene_ids,
            'created_at': now,
            'updated_at': now,
            'char_count': len(text),
        }
        payload['documents'].append(document)
        for project_item in payload['projects']:
            if project_item['id'] == project['id']:
                project_item['updated_at'] = now
                break
        self._save_index(payload)
        return dict(document)

    def update_document(
        self,
        document_id,
        *,
        title=None,
        tags=None,
        enabled=None,
        bound_scene_ids=None,
        text=None,
    ):
        payload = self._load_index()
        for document in payload['documents']:
            if document['id'] != document_id:
                continue
            if title is not None:
                normalized_title = str(title or '').strip()
                if not normalized_title:
                    raise KnowledgeBaseError('资料标题不能为空')
                document['title'] = normalized_title
            if tags is not None:
                document['tags'] = _parse_tags(tags)
            if enabled is not None:
                document['enabled'] = bool(enabled)
            if bound_scene_ids is not None:
                document['bound_scene_ids'] = _unique_text_list(bound_scene_ids, allowed=SCENE_DEFS.keys())
            if text is not None:
                normalized_text = _normalize_text(text)
                if not normalized_text:
                    raise KnowledgeBaseError('资料内容不能为空')
                self._write_text_file(self._resolve_text_path(document), normalized_text)
                document['char_count'] = len(normalized_text)
            document['updated_at'] = _now_ts()
            self._save_index(payload)
            return dict(document)
        raise KnowledgeBaseError('知识库资料不存在')

    def delete_document(self, document_id):
        payload = self._load_index()
        document = None
        remaining = []
        for item in payload['documents']:
            if item['id'] == document_id:
                document = item
            else:
                remaining.append(item)
        if not document:
            raise KnowledgeBaseError('知识库资料不存在')
        payload['documents'] = remaining
        self._save_index(payload)
        self._delete_text_file(document)
        return True

    def read_document_text(self, document):
        if isinstance(document, str):
            document = self.get_document(document)
        if not isinstance(document, dict):
            return ''
        path = self._resolve_text_path(document)
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return handle.read()
        except FileNotFoundError:
            return ''
        except Exception as exc:
            raise KnowledgeBaseError(f'读取资料文本失败：{exc}') from exc

    def build_context(
        self,
        project_id,
        document_ids,
        scene_id,
        *,
        total_char_limit=DEFAULT_TOTAL_CHAR_LIMIT,
        per_document_char_limit=DEFAULT_PER_DOCUMENT_CHAR_LIMIT,
    ):
        project = self.get_project(project_id)
        if not project:
            return {
                'project_id': '',
                'project_name': '',
                'documents': [],
                'scene_id': str(scene_id or '').strip(),
                'context_text': '',
                'truncated': False,
            }

        scene_id = str(scene_id or '').strip()
        available = {
            doc['id']: doc
            for doc in self.list_documents(project['id'], scene_id=scene_id, enabled_only=True)
        }
        ordered_ids = _unique_text_list(document_ids or [])
        selected_docs = [available[doc_id] for doc_id in ordered_ids if doc_id in available]
        parts = []
        used_documents = []
        remaining = max(int(total_char_limit or DEFAULT_TOTAL_CHAR_LIMIT), 1)
        per_doc_limit = max(int(per_document_char_limit or DEFAULT_PER_DOCUMENT_CHAR_LIMIT), 1)
        truncated = False
        any_truncated = False

        for index, document in enumerate(selected_docs, start=1):
            if remaining <= 0:
                truncated = True
                break
            text = self.read_document_text(document)
            if not text.strip():
                continue
            clipped_text = text[:per_doc_limit]
            doc_truncated = len(text) > len(clipped_text)
            header = f'【资料{index}】{document.get("title", "")}'
            tags = document.get('tags', [])
            if tags:
                header += f'\n标签：{"、".join(tags)}'
            body = f'{header}\n{clipped_text.strip()}'
            if doc_truncated:
                body += '\n[该资料已按单份资料长度上限截断]'
                any_truncated = True
            if len(body) > remaining:
                body = body[:remaining].rstrip()
                truncated = True
            remaining -= len(body)
            parts.append(body)
            used = dict(document)
            used['used_char_count'] = len(clipped_text)
            used['truncated'] = bool(doc_truncated or truncated)
            used_documents.append(used)
            if truncated:
                break

        return {
            'project_id': project['id'],
            'project_name': project['name'],
            'documents': used_documents,
            'scene_id': scene_id,
            'context_text': '\n\n'.join(parts).strip(),
            'truncated': bool(truncated or any_truncated),
        }

    def _resolve_text_path(self, document):
        text_path = str((document or {}).get('text_path', '') or '').strip().replace('\\', '/')
        if not text_path:
            text_path = f'documents/{document.get("id", _new_id("doc"))}.txt'
        if os.path.isabs(text_path):
            return text_path
        return os.path.join(self.root_dir, text_path)

    def _delete_text_file(self, document):
        path = self._resolve_text_path(document)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            self._log(f'删除知识库资料文本失败：{path} {exc}', level='WARN')

    @staticmethod
    def _write_text_file(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(_normalize_text(text))

    def _extract_document_text(self, path):
        suffix = Path(path).suffix.lower()
        if suffix in {'.txt', '.md'}:
            return self._read_plain_text(path), suffix.lstrip('.')
        if suffix == '.docx':
            return self._read_docx_text(path), 'docx'
        if suffix == '.pdf':
            return self._read_pdf_text(path), 'pdf'
        raise KnowledgeBaseError('仅支持导入 txt、md、docx、pdf 文件')

    @staticmethod
    def _read_plain_text(path):
        for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
            try:
                with open(path, 'r', encoding=encoding) as handle:
                    return _normalize_text(handle.read())
            except UnicodeDecodeError:
                continue
        with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
            return _normalize_text(handle.read())

    @staticmethod
    def _read_docx_text(path):
        try:
            import docx
        except Exception as exc:
            raise KnowledgeBaseError('缺少 python-docx，无法导入 DOCX 文件') from exc
        document = docx.Document(path)
        pieces = [str(paragraph.text or '').strip() for paragraph in document.paragraphs]
        return _normalize_text('\n'.join(piece for piece in pieces if piece))

    @staticmethod
    def _read_pdf_text(path):
        try:
            import fitz
        except Exception as exc:
            raise KnowledgeBaseError('缺少 PyMuPDF，无法导入 PDF 文件') from exc
        pieces = []
        with fitz.open(path) as document:
            for page in document:
                text = page.get_text('text')
                if text:
                    pieces.append(text.strip())
        return _normalize_text('\n\n'.join(piece for piece in pieces if piece))
