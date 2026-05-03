# -*- coding: utf-8 -*-
"""
Typed bridge between pages and the application shell.
"""


class AppBridge:
    """Expose app-level actions to pages without string-key dispatch."""

    def __init__(self, **callbacks):
        self._callbacks = dict(callbacks)

    def _call(self, name, *args, default=None, **kwargs):
        callback = self._callbacks.get(name)
        if not callable(callback):
            return default
        return callback(*args, **kwargs)

    def show_announcement(self):
        return self._call('show_announcement')

    def show_tutorial(self):
        return self._call('show_tutorial')

    def show_settings(self):
        return self._call('show_settings')

    def show_about(self):
        return self._call('show_about')

    def show_api_config(self, return_to_model_list=False):
        return self._call('show_api_config', return_to_model_list=return_to_model_list)

    def show_prompt_manager(self, page_id=None, compact=False, scene_id=None):
        return self._call(
            'show_prompt_manager',
            page_id=page_id,
            compact=compact,
            scene_id=scene_id,
        )

    def show_skills_center(self):
        return self._call('show_skills_center')

    def show_discover_skills(self):
        return self._call('show_discover_skills')

    def show_repo_manage(self):
        return self._call('show_repo_manage')

    def show_model_routing(self):
        return self._call('show_model_routing')

    def switch_api_provider_direct(self, api_id):
        return self._call('switch_api_provider_direct', api_id)

    def add_new_provider(self):
        return self._call('add_new_provider')

    def pull_paper_write_context(self):
        return self._call('pull_paper_write_context', default={}) or {}

    def pull_paper_write_selection_snapshot(self):
        return self._call('pull_paper_write_selection_snapshot')

    def apply_result_to_paper_write(
        self,
        result,
        target_mode='smart',
        write_mode='replace',
        section_hint='',
        task_type='',
    ):
        return self._call(
            'apply_result_to_paper_write',
            result,
            target_mode=target_mode,
            write_mode=write_mode,
            section_hint=section_hint,
            task_type=task_type,
            default={'ok': False, 'message': '论文写作页桥接不可用'},
        )

    def send_paper_write_content(self, page_id, payload):
        return self._call(
            'send_paper_write_content',
            page_id,
            payload,
            default={'ok': False, 'message': '论文写作内容发送桥接不可用'},
        )

    def navigate_to_page(self, page_id):
        return self._call(
            'navigate_to_page',
            page_id,
            default={'ok': False, 'message': '页面跳转桥接不可用'},
        )

    def write_app_log(self, message, level='INFO'):
        return self._call('write_app_log', message, level=level)

    def restore_page_workspace(self, page_id, state, save_to_disk=True):
        return self._call(
            'restore_page_workspace',
            page_id,
            state,
            save_to_disk=save_to_disk,
            default={'ok': False, 'message': '工作区快照恢复桥接不可用'},
        )
