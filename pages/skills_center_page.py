# -*- coding: utf-8 -*-
"""
Skills 管理中心面板。
"""

from __future__ import annotations

import json
import os
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from modules.prompt_center import SCENE_DEFS
from modules.skills_runtime import SkillExecutionError, SkillValidationError
from modules.ui_components import (
    bind_adaptive_wrap,
    bind_combobox_dropdown_mousewheel,
    bind_responsive_two_pane,
    CardFrame,
    COLORS,
    create_home_shell_button,
    create_scrolled_text,
    FONTS,
    ResponsiveButtonBar,
    ScrollablePage,
)


def _format_timestamp(ts):
    try:
        number = int(ts or 0)
    except Exception:
        number = 0
    if number <= 0:
        return '未记录'
    import datetime as _datetime

    return _datetime.datetime.fromtimestamp(number).strftime('%Y-%m-%d %H:%M:%S')


class SkillsCenterPanel:
    def __init__(self, parent, config_mgr, skill_manager, remote_content_manager, *, set_status, close_panel=None, app_bridge=None):
        self.config = config_mgr
        self.skill_manager = skill_manager
        self.remote_content = remote_content_manager
        self.set_status = set_status
        self.close_panel = close_panel
        self.app_bridge = app_bridge
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self.registry_payload = self.skill_manager.load_registry_cache()
        self.installed_skills = []
        self.registry_skills = []
        self.selected_skill_id = ''
        self.selected_is_installed = False
        self.selected_action_id = ''

        self.toolbar_bar = None
        self.summary_label = None
        self.list_view = None
        self.list_inner = None
        self.detail_view = None
        self.detail_inner = None
        self.title_label = None
        self.meta_label = None
        self.desc_label = None
        self.status_label = None
        self.global_var = tk.BooleanVar(value=False)
        self.enabled_var = tk.BooleanVar(value=False)
        self.scene_vars = {}
        self.scene_checks_frame = None
        self.action_tabs_bar = None
        self.action_form_frame = None
        self.action_result_text = None
        self.action_result_frame = None
        self._action_widgets = {}

        self._build()
        self.refresh_all(force_registry=False)

    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 14))

        title_row = tk.Frame(header, bg=COLORS['bg_main'])
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row,
            text='Skills 管理',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT)

        if callable(self.close_panel):
            close_shell, _close_button = create_home_shell_button(
                title_row,
                '关闭',
                command=self.close_panel,
                style='secondary',
                padx=14,
                pady=6,
            )
            close_shell.pack(side=tk.RIGHT)

        self.summary_label = tk.Label(
            header,
            text='',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
            anchor='w',
            justify='left',
        )
        self.summary_label.pack(fill=tk.X, pady=(8, 0))

        toolbar_host = tk.Frame(self.frame, bg=COLORS['bg_main'])
        toolbar_host.pack(fill=tk.X, pady=(0, 14))
        self.toolbar_bar = ResponsiveButtonBar(toolbar_host, min_item_width=156, gap_x=8, gap_y=8, bg=COLORS['bg_main'])
        self.toolbar_bar.pack(fill=tk.X)
        self.toolbar_bar.add(
            create_home_shell_button(
                self.toolbar_bar,
                '从 ZIP 安装',
                command=self._install_from_zip,
                style='primary',
                padx=14,
                pady=7,
            )[0]
        )
        self.toolbar_bar.add(
            create_home_shell_button(
                self.toolbar_bar,
                '导入已有',
                command=self._import_existing_directory,
                style='secondary',
                padx=14,
                pady=7,
            )[0]
        )
        self.toolbar_bar.add(
            create_home_shell_button(
                self.toolbar_bar,
                '发现技能',
                command=self._discover_skills,
                style='secondary',
                padx=14,
                pady=7,
            )[0]
        )
        self.toolbar_bar.add(
            create_home_shell_button(
                self.toolbar_bar,
                '检查更新',
                command=self._check_updates,
                style='secondary',
                padx=14,
                pady=7,
            )[0]
        )

        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left_card = CardFrame(body, title='技能列表')
        right_card = CardFrame(body, title='技能详情')
        self._build_left_panel(left_card.inner)
        self._build_right_panel(right_card.inner)
        bind_responsive_two_pane(body, left_card, right_card, breakpoint=1320, gap=12, left_minsize=360)

    def _build_left_panel(self, parent):
        self.list_view = ScrollablePage(parent, bg=COLORS['card_bg'])
        self.list_view.pack(fill=tk.BOTH, expand=True)
        self.list_inner = self.list_view.inner

    def _build_right_panel(self, parent):
        self.detail_view = ScrollablePage(parent, bg=COLORS['card_bg'])
        self.detail_view.pack(fill=tk.BOTH, expand=True)
        self.detail_inner = self.detail_view.inner

        self.title_label = tk.Label(
            self.detail_inner,
            text='请选择左侧技能',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        self.title_label.pack(fill=tk.X)

        self.meta_label = tk.Label(
            self.detail_inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify='left',
        )
        self.meta_label.pack(fill=tk.X, pady=(6, 0))
        bind_adaptive_wrap(self.meta_label, self.detail_inner, padding=12, min_width=320)

        self.desc_label = tk.Label(
            self.detail_inner,
            text='',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify='left',
        )
        self.desc_label.pack(fill=tk.X, pady=(10, 0))
        bind_adaptive_wrap(self.desc_label, self.detail_inner, padding=12, min_width=320)

        self.status_label = tk.Label(
            self.detail_inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['warning'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify='left',
        )
        self.status_label.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(self.status_label, self.detail_inner, padding=12, min_width=320)

        toggle_card = CardFrame(self.detail_inner, title='启用状态', padding=16)
        toggle_card.pack(fill=tk.X, pady=(14, 0))
        tk.Checkbutton(
            toggle_card.inner,
            text='启用技能',
            variable=self.enabled_var,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            activebackground=COLORS['card_bg'],
            activeforeground=COLORS['text_main'],
            selectcolor=COLORS['card_bg'],
            anchor='w',
        ).pack(anchor='w')
        tk.Checkbutton(
            toggle_card.inner,
            text='全局生效',
            variable=self.global_var,
            font=FONTS['body'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            activebackground=COLORS['card_bg'],
            activeforeground=COLORS['text_main'],
            selectcolor=COLORS['card_bg'],
            anchor='w',
        ).pack(anchor='w', pady=(8, 0))

        self.scene_checks_frame = tk.Frame(toggle_card.inner, bg=COLORS['card_bg'])
        self.scene_checks_frame.pack(fill=tk.X, pady=(10, 0))

        actions_bar = ResponsiveButtonBar(toggle_card.inner, min_item_width=150, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        actions_bar.pack(fill=tk.X, pady=(12, 0))
        actions_bar.add(
            create_home_shell_button(
                actions_bar,
                '保存技能设置',
                command=self._save_current_skill_state,
                style='primary',
                padx=14,
                pady=6,
            )[0]
        )
        actions_bar.add(
            create_home_shell_button(
                actions_bar,
                '删除技能',
                command=self._delete_selected_skill,
                style='danger',
                padx=14,
                pady=6,
            )[0]
        )
        actions_bar.add(
            create_home_shell_button(
                actions_bar,
                '打开主页',
                command=self._open_skill_homepage,
                style='secondary',
                padx=14,
                pady=6,
            )[0]
        )
        actions_bar.add(
            create_home_shell_button(
                actions_bar,
                '下载并更新',
                command=self._update_selected_skill_from_registry,
                style='secondary',
                padx=14,
                pady=6,
            )[0]
        )

        action_card = CardFrame(self.detail_inner, title='独立动作', padding=16)
        action_card.pack(fill=tk.BOTH, expand=True, pady=(14, 0))
        self.action_tabs_bar = ResponsiveButtonBar(action_card.inner, min_item_width=130, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        self.action_tabs_bar.pack(fill=tk.X)
        self.action_form_frame = tk.Frame(action_card.inner, bg=COLORS['card_bg'])
        self.action_form_frame.pack(fill=tk.X, pady=(14, 0))

        action_run_bar = ResponsiveButtonBar(action_card.inner, min_item_width=150, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        action_run_bar.pack(fill=tk.X, pady=(12, 0))
        action_run_bar.add(
            create_home_shell_button(
                action_run_bar,
                '执行动作',
                command=self._run_selected_action,
                style='primary',
                padx=14,
                pady=6,
            )[0]
        )

        self.action_result_frame, self.action_result_text = create_scrolled_text(action_card.inner, height=14, show_scrollbar=True)
        self.action_result_frame.pack(fill=tk.BOTH, expand=True, pady=(14, 0))

    def _run_background(self, work, *, success_message='', on_success=None, on_error=None):
        self.set_status('处理中，请稍候...', COLORS['warning'])

        def runner():
            error = None
            result = None
            try:
                result = work()
            except Exception as exc:
                error = exc

            def finalize():
                if error is not None:
                    self.set_status('操作失败', COLORS['error'])
                    if callable(on_error):
                        on_error(error)
                    else:
                        messagebox.showerror('Skills 管理', str(error), parent=self.frame.winfo_toplevel())
                    return
                if success_message:
                    self.set_status(success_message, COLORS['success'])
                if callable(on_success):
                    on_success(result)

            self.frame.after(0, finalize)

        threading.Thread(target=runner, name='SkillsCenterAction', daemon=True).start()

    def _confirm_replace_install(self, manifest, *, action_label='覆盖安装'):
        skill_id = str((manifest or {}).get('id', '') or '').strip()
        if not skill_id:
            return True
        current = self.skill_manager.get_installed_skill_record(skill_id)
        if not current:
            return True
        skill_name = str((manifest or {}).get('name', '') or current.get('name', '') or skill_id).strip()
        current_version = str(current.get('version', '') or '未知')
        incoming_version = str((manifest or {}).get('version', '') or '未知')
        return messagebox.askyesno(
            '覆盖确认',
            (
                f'技能「{skill_name}」已安装。\n'
                f'当前版本：{current_version}\n'
                f'导入版本：{incoming_version}\n\n'
                f'继续{action_label}吗？'
            ),
            parent=self.frame.winfo_toplevel(),
        )

    def _install_from_zip(self):
        path = filedialog.askopenfilename(
            parent=self.frame.winfo_toplevel(),
            title='选择技能 ZIP 包',
            filetypes=[('ZIP 文件', '*.zip')],
        )
        if not path:
            return
        try:
            manifest = self.skill_manager.inspect_skill_zip(path)
        except Exception as exc:
            self._handle_skill_error(exc)
            return
        if not self._confirm_replace_install(manifest, action_label='覆盖安装'):
            return
        self._run_background(
            lambda: self.skill_manager.install_skill_from_zip(path),
            success_message='技能安装完成',
            on_success=lambda result: self.refresh_all(force_registry=False, preferred_skill_id=(result or {}).get('id', '')),
            on_error=self._handle_skill_error,
        )

    def _import_existing_directory(self):
        path = filedialog.askdirectory(
            parent=self.frame.winfo_toplevel(),
            title='选择已有技能目录',
            mustexist=True,
        )
        if not path:
            return
        try:
            _source_root, manifest = self.skill_manager.validate_skill_directory(path)
        except Exception as exc:
            self._handle_skill_error(exc)
            return
        if not self._confirm_replace_install(manifest, action_label='覆盖安装'):
            return
        self._run_background(
            lambda: self.skill_manager.install_skill_from_directory(path, source_type='directory', source_label=os.path.abspath(path)),
            success_message='技能导入完成',
            on_success=lambda result: self.refresh_all(force_registry=False, preferred_skill_id=(result or {}).get('id', '')),
            on_error=self._handle_skill_error,
        )

    def _discover_skills(self):
        if self.app_bridge and hasattr(self.app_bridge, 'show_discover_skills'):
            self.app_bridge.show_discover_skills()
            return
        # 回退：保留原有行为
        self.set_status('正在拉取官方技能索引...', COLORS['warning'])

        def on_loaded(data):
            self.registry_payload = self.skill_manager.save_registry_cache(data)
            self.refresh_all(force_registry=False)
            self.set_status('技能索引已刷新', COLORS['success'])

        def on_error(exc):
            cached = self.skill_manager.load_registry_cache()
            self.registry_payload = cached
            self.refresh_all(force_registry=False)
            self.set_status('使用本地缓存的技能索引', COLORS['warning'])
            if not cached.get('skills'):
                messagebox.showerror('Skills 管理', str(exc), parent=self.frame.winfo_toplevel())

        self.remote_content.fetch('skills_index', on_success=on_loaded, on_error=on_error, force=True)

    def _check_updates(self):
        self.set_status('正在检查技能更新...', COLORS['warning'])

        def on_loaded(data):
            self.registry_payload = self.skill_manager.save_registry_cache(data)
            self.skill_manager.mark_all_checked()
            self.refresh_all(force_registry=False)
            update_count = self.skill_manager.count_updates(self.registry_payload)
            message = f'发现 {update_count} 个可更新技能。' if update_count else '未发现可更新技能。'
            self.set_status(message, COLORS['success'])

        def on_error(exc):
            self.registry_payload = self.skill_manager.load_registry_cache()
            self.refresh_all(force_registry=False)
            messagebox.showerror('Skills 管理', f'检查更新失败：\n{exc}', parent=self.frame.winfo_toplevel())

        self.remote_content.fetch('skills_index', on_success=on_loaded, on_error=on_error, force=True)

    def refresh_all(self, *, force_registry=False, preferred_skill_id=None):
        if force_registry:
            self.registry_payload = self.skill_manager.load_registry_cache()
        self.installed_skills = self.skill_manager.list_installed_skills(self.registry_payload)
        self.registry_skills = self.skill_manager.list_registry_skills(self.registry_payload)
        self._ensure_selection(preferred_skill_id=preferred_skill_id)
        self._render_summary()
        self._render_skill_list()
        self._render_skill_detail()

    def _render_summary(self):
        installed_count = len(self.installed_skills)
        enabled_count = sum(1 for item in self.installed_skills if item.get('enabled'))
        registry_count = len(self.registry_payload.get('skills', []))
        update_count = self.skill_manager.count_updates(self.registry_payload)
        self.summary_label.configure(
            text=(
                f'已安装 {installed_count} 个技能，其中启用 {enabled_count} 个；'
                f'官方索引收录 {registry_count} 个技能；可更新 {update_count} 个。'
            )
        )

    def _render_skill_list(self):
        for child in self.list_inner.winfo_children():
            child.destroy()

        sections = [
            ('已安装', self.installed_skills),
        ]
        if not any(items for _title, items in sections):
            tk.Label(
                self.list_inner,
                text='当前没有可显示的技能。',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
            ).pack(fill=tk.X, pady=(0, 8))
            return

        rendered_count = 0
        for title, items in sections:
            if not items:
                continue
            tk.Label(
                self.list_inner,
                text=title,
                font=FONTS['heading'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                anchor='w',
            ).pack(fill=tk.X, pady=(0, 8))
            for item in items:
                self._render_skill_list_item(item)
                rendered_count += 1
        self._refresh_skill_list_layout()

    def _refresh_skill_list_layout(self):
        if not self.list_view:
            return

        def apply_layout():
            try:
                self.list_inner.update_idletasks()
                self.list_view._apply_layout_refresh()
            except tk.TclError:
                pass

        apply_layout()
        try:
            self.frame.after_idle(apply_layout)
        except tk.TclError:
            pass

    def _render_skill_list_item(self, item):
        skill_id = item.get('id', '')
        is_selected = self.selected_skill_id == skill_id and bool(item.get('is_installed', False)) == self.selected_is_installed
        shell = tk.Frame(self.list_inner, bg=COLORS['shadow'])
        shell.pack(fill=tk.X, pady=(0, 10))
        body = tk.Frame(
            shell,
            bg=COLORS['accent_soft'] if is_selected else COLORS['card_bg'],
            highlightbackground=COLORS['primary'] if is_selected else COLORS['card_border'],
            highlightthickness=3,
            bd=0,
            cursor='hand2',
        )
        body.pack(fill=tk.X, padx=(0, 6), pady=(0, 6))

        title_row = tk.Frame(body, bg=body.cget('bg'))
        title_row.pack(fill=tk.X, padx=16, pady=(14, 0))
        tk.Label(
            title_row,
            text=item.get('name', skill_id),
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=body.cget('bg'),
            anchor='w',
        ).pack(side=tk.LEFT)
        tag_texts = []
        if item.get('is_installed'):
            tag_texts.append('已安装')
        if item.get('enabled'):
            tag_texts.append('已启用')
        if item.get('is_local_only'):
            tag_texts.append('仅本地')
        if item.get('has_update'):
            tag_texts.append('可更新')
        if tag_texts:
            tk.Label(
                title_row,
                text=' / '.join(tag_texts),
                font=FONTS['small'],
                fg=COLORS['primary'],
                bg=body.cget('bg'),
                anchor='e',
            ).pack(side=tk.RIGHT)

        meta_text = f'版本：{item.get("version", "未知")}  来源：{item.get("source_type", "registry") or "registry"}'
        tk.Label(
            body,
            text=meta_text,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=body.cget('bg'),
            anchor='w',
        ).pack(fill=tk.X, padx=16, pady=(6, 0))

        desc_label = tk.Label(
            body,
            text=item.get('description', '') or '暂无描述',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=body.cget('bg'),
            anchor='w',
            justify='left',
        )
        desc_label.pack(fill=tk.X, padx=16, pady=(8, 14))
        bind_adaptive_wrap(desc_label, body, padding=24, min_width=220)

        def _select(_event=None, current=item):
            self.selected_skill_id = current.get('id', '')
            self.selected_is_installed = bool(current.get('is_installed', False))
            self._render_skill_list()
            self._render_skill_detail()

        for widget in (shell, body, title_row, desc_label):
            widget.bind('<Button-1>', _select, add='+')

    def _ensure_selection(self, *, preferred_skill_id=None):
        target_id = preferred_skill_id or self.selected_skill_id
        if target_id:
            for item in self.installed_skills + self.registry_skills:
                if item.get('id') == target_id:
                    self.selected_skill_id = target_id
                    self.selected_is_installed = bool(item.get('is_installed', False))
                    return
        if self.installed_skills:
            self.selected_skill_id = self.installed_skills[0].get('id', '')
            self.selected_is_installed = True
            return
        if self.registry_skills:
            self.selected_skill_id = self.registry_skills[0].get('id', '')
            self.selected_is_installed = bool(self.registry_skills[0].get('is_installed', False))
            return
        self.selected_skill_id = ''
        self.selected_is_installed = False

    def _get_selected_skill(self):
        for item in self.installed_skills + self.registry_skills:
            if item.get('id') == self.selected_skill_id and bool(item.get('is_installed', False)) == self.selected_is_installed:
                return item
        return None

    def _render_skill_detail(self):
        item = self._get_selected_skill()
        if not item:
            self.title_label.configure(text='请选择左侧技能')
            self.meta_label.configure(text='')
            self.desc_label.configure(text='')
            self.status_label.configure(text='')
            self.enabled_var.set(False)
            self.global_var.set(False)
            self._render_scene_checks([])
            self._render_action_tabs([])
            self._clear_action_form()
            self._set_action_result('')
            return

        self.title_label.configure(text=item.get('name', item.get('id', '')))
        self.meta_label.configure(
            text=(
                f'ID：{item.get("id", "")}\n'
                f'版本：{item.get("version", "未知")}  最新：{item.get("latest_version", item.get("version", "未知"))}\n'
                f'来源：{item.get("source_type", "registry") or "registry"}  安装时间：{_format_timestamp(item.get("installed_at", 0))}\n'
                f'上次检查：{_format_timestamp(item.get("last_checked_at", 0))}'
            )
        )
        self.desc_label.configure(text=item.get('description', '') or '暂无描述。')

        status_messages = []
        if item.get('is_missing_package'):
            status_messages.append('技能包目录缺失，当前无法执行。')
        if item.get('has_update'):
            status_messages.append(f'存在更新版本：{item.get("latest_version", "")}')
        if not item.get('is_installed'):
            status_messages.append('该技能尚未安装。')
        if item.get('is_local_only'):
            status_messages.append('该技能为本地导入版本，不参与在线更新。')
        self.status_label.configure(text='  '.join(status_messages))

        self.enabled_var.set(bool(item.get('enabled', False)))
        self.global_var.set(bool(item.get('global_enabled', False)))
        self._render_scene_checks(item.get('scene_bindings', []), selected=item.get('bound_scene_ids', []))
        manifest = item.get('manifest')
        actions = list((manifest or {}).get('actions', []) or [])
        self._render_action_tabs(actions)
        self._render_action_form(actions)

    def _render_scene_checks(self, scene_bindings, selected=None):
        for child in self.scene_checks_frame.winfo_children():
            child.destroy()
        self.scene_vars = {}
        selected_set = set(selected or [])
        # 默认勾选：scene_bindings 中声明的场景（推荐绑定）
        default_set = set(scene_bindings or [])
        if not selected:
            selected_set = default_set
        # 展示所有可用场景（来自 SCENE_DEFS）
        all_scene_ids = list(SCENE_DEFS.keys())
        if not all_scene_ids:
            tk.Label(
                self.scene_checks_frame,
                text='当前没有可绑定的场景。',
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
            ).pack(fill=tk.X)
            return
        for scene_id in all_scene_ids:
            scene_def = SCENE_DEFS.get(scene_id, {})
            page_label = scene_def.get('page_label', '')
            scene_label = scene_def.get('label', '')
            if page_label and scene_label:
                display_name = f'{page_label} · {scene_label}'
            elif scene_label:
                display_name = scene_label
            elif page_label:
                display_name = page_label
            else:
                display_name = scene_id
            var = tk.BooleanVar(value=scene_id in selected_set)
            self.scene_vars[scene_id] = var
            cb = tk.Checkbutton(
                self.scene_checks_frame,
                text=display_name,
                variable=var,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                activeforeground=COLORS['text_main'],
                selectcolor=COLORS['card_bg'],
                anchor='w',
            )
            cb.pack(anchor='w')
            # 标记推荐绑定（manifest 声明的场景）
            if scene_id in default_set and scene_id not in selected_set:
                cb.select()

    def _render_action_tabs(self, actions):
        for child in self.action_tabs_bar.winfo_children():
            child.destroy()
        self.action_tabs_bar.widgets = []
        if not actions:
            self.selected_action_id = ''
            return
        if self.selected_action_id not in {item.get('id') for item in actions}:
            self.selected_action_id = actions[0].get('id', '')
        for action in actions:
            action_id = action.get('id', '')
            shell, _button = create_home_shell_button(
                self.action_tabs_bar,
                action.get('label', action_id),
                command=lambda current_id=action_id: self._select_action(current_id),
                style='primary' if action_id == self.selected_action_id else 'secondary',
                padx=12,
                pady=6,
            )
            self.action_tabs_bar.add(shell)

    def _select_action(self, action_id):
        self.selected_action_id = str(action_id or '').strip()
        item = self._get_selected_skill()
        actions = list(((item or {}).get('manifest') or {}).get('actions', []) or [])
        self._render_action_tabs(actions)
        self._render_action_form(actions)

    def _clear_action_form(self):
        for child in self.action_form_frame.winfo_children():
            child.destroy()
        self._action_widgets = {}

    def _render_action_form(self, actions):
        self._clear_action_form()
        action = next((item for item in actions if item.get('id') == self.selected_action_id), None)
        if not action:
            tk.Label(
                self.action_form_frame,
                text='当前技能没有可执行的独立动作。',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
            ).pack(fill=tk.X)
            return
        if action.get('description'):
            desc = tk.Label(
                self.action_form_frame,
                text=action.get('description', ''),
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
                justify='left',
            )
            desc.pack(fill=tk.X, pady=(0, 10))
            bind_adaptive_wrap(desc, self.action_form_frame, padding=12, min_width=260)

        for field in action.get('input_schema', {}).get('fields', []):
            self._render_action_field(field)

    def _render_action_field(self, field):
        field_type = field.get('type', 'text')
        field_id = field.get('id', '')
        wrapper = tk.Frame(self.action_form_frame, bg=COLORS['card_bg'])
        wrapper.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            wrapper,
            text=field.get('label', field_id),
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            anchor='w',
        ).pack(anchor='w')

        if field_type == 'textarea':
            frame, text = create_scrolled_text(wrapper, height=6, show_scrollbar=True)
            frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
            default_text = field.get('default', '')
            if default_text not in (None, ''):
                text.insert('1.0', str(default_text))
            self._action_widgets[field_id] = {'type': field_type, 'widget': text}
        elif field_type == 'select':
            var = tk.StringVar(value=str(field.get('default', '') or ''))
            values = [item.get('value', '') for item in field.get('options', [])]
            combo = ttk.Combobox(
                wrapper,
                textvariable=var,
                values=values,
                state='readonly',
                style='Modern.TCombobox',
            )
            combo.pack(fill=tk.X, pady=(6, 0), ipady=4)
            bind_combobox_dropdown_mousewheel(combo)
            self._action_widgets[field_id] = {'type': field_type, 'variable': var}
        elif field_type == 'checkbox':
            var = tk.BooleanVar(value=bool(field.get('default', False)))
            tk.Checkbutton(
                wrapper,
                text=field.get('help', '') or '启用',
                variable=var,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                activeforeground=COLORS['text_main'],
                selectcolor=COLORS['card_bg'],
                anchor='w',
            ).pack(anchor='w', pady=(6, 0))
            self._action_widgets[field_id] = {'type': field_type, 'variable': var}
        else:
            var = tk.StringVar(value='' if field.get('default', None) is None else str(field.get('default')))
            entry = tk.Entry(
                wrapper,
                textvariable=var,
                font=FONTS['body'],
                bg=COLORS['input_bg'],
                fg=COLORS['text_main'],
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=COLORS['input_border'],
                insertbackground=COLORS['text_main'],
            )
            entry.pack(fill=tk.X, pady=(6, 0), ipady=4)
            self._action_widgets[field_id] = {'type': field_type, 'variable': var}

        help_text = str(field.get('help', '') or '').strip()
        if help_text and field_type != 'checkbox':
            tk.Label(
                wrapper,
                text=help_text,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
                justify='left',
            ).pack(fill=tk.X, pady=(4, 0))

    def _collect_action_inputs(self):
        payload = {}
        for field_id, spec in self._action_widgets.items():
            field_type = spec.get('type', 'text')
            if field_type == 'textarea':
                payload[field_id] = spec['widget'].get('1.0', tk.END).strip()
            else:
                payload[field_id] = spec['variable'].get()
        return payload

    def _run_selected_action(self):
        item = self._get_selected_skill()
        if not item or not item.get('is_installed'):
            messagebox.showwarning('Skills 管理', '请先选择一个已安装技能。', parent=self.frame.winfo_toplevel())
            return
        if not self.selected_action_id:
            messagebox.showwarning('Skills 管理', '当前技能没有可执行动作。', parent=self.frame.winfo_toplevel())
            return
        inputs = self._collect_action_inputs()

        def work():
            return self.skill_manager.run_action(item.get('id', ''), self.selected_action_id, inputs)

        self._run_background(
            work,
            success_message='技能动作执行完成',
            on_success=lambda result: self._set_action_result(result),
            on_error=self._handle_skill_error,
        )

    def _set_action_result(self, result):
        if isinstance(result, (dict, list)):
            text = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            text = '' if result is None else str(result)
        self.action_result_text.delete('1.0', tk.END)
        self.action_result_text.insert('1.0', text)

    def _save_current_skill_state(self):
        item = self._get_selected_skill()
        if not item or not item.get('is_installed'):
            messagebox.showwarning('Skills 管理', '当前选择的技能尚未安装。', parent=self.frame.winfo_toplevel())
            return
        bound_scene_ids = [scene_id for scene_id, var in self.scene_vars.items() if var.get()]
        try:
            self.skill_manager.update_skill_state(
                item.get('id', ''),
                enabled=self.enabled_var.get(),
                global_enabled=self.global_var.get(),
                bound_scene_ids=bound_scene_ids,
            )
        except Exception as exc:
            self._handle_skill_error(exc)
            return
        self.set_status('技能设置已保存', COLORS['success'])
        self.refresh_all(force_registry=False, preferred_skill_id=item.get('id', ''))

    def _delete_selected_skill(self):
        item = self._get_selected_skill()
        if not item or not item.get('is_installed'):
            messagebox.showwarning('Skills 管理', '当前选择的技能尚未安装。', parent=self.frame.winfo_toplevel())
            return
        if not messagebox.askyesno(
            '删除技能',
            f'确定要删除技能「{item.get("name", item.get("id", ""))}」吗？此操作不可恢复。',
            parent=self.frame.winfo_toplevel(),
        ):
            return

        self._run_background(
            lambda: self.skill_manager.delete_skill(item.get('id', '')),
            success_message='技能已删除',
            on_success=lambda _result: self.refresh_all(force_registry=False, preferred_skill_id=''),
            on_error=self._handle_skill_error,
        )

    def _open_skill_homepage(self):
        item = self._get_selected_skill()
        if not item:
            return
        url = ''
        if item.get('manifest'):
            url = str(item['manifest'].get('homepage', '') or '').strip()
        if not url and item.get('registry_entry'):
            url = str(item['registry_entry'].get('homepage', '') or '').strip()
        if not url:
            messagebox.showinfo('Skills 管理', '当前技能没有可打开的主页。', parent=self.frame.winfo_toplevel())
            return
        webbrowser.open(url)

    def _update_selected_skill_from_registry(self):
        item = self._get_selected_skill()
        if not item:
            return
        registry_entry = item.get('registry_entry') or {}
        download_url = str(registry_entry.get('download_url', '') or '').strip()
        if not download_url:
            messagebox.showinfo('Skills 管理', '当前技能没有可用的下载更新地址。', parent=self.frame.winfo_toplevel())
            return

        if not self._confirm_replace_install(
            {
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'version': registry_entry.get('version', ''),
            },
            action_label='下载并更新',
        ):
            return

        self._run_background(
            lambda: self.skill_manager.download_registry_skill_zip(registry_entry),
            success_message='技能更新完成',
            on_success=lambda result: self.refresh_all(force_registry=False, preferred_skill_id=(result or {}).get('id', item.get('id', ''))),
            on_error=self._handle_skill_error,
        )

    def _handle_skill_error(self, error):
        messagebox.showerror('Skills 管理', str(error), parent=self.frame.winfo_toplevel())
        if isinstance(error, (SkillValidationError, SkillExecutionError)):
            self.set_status(str(error), COLORS['error'])
        else:
            self.set_status('技能操作失败', COLORS['error'])
