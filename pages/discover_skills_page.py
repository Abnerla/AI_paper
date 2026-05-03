# -*- coding: utf-8 -*-
"""
发现技能弹窗面板 — 支持仓库/skill.sh 切换、搜索筛选、网格化卡片、安装/详情、仓库管理。
"""

from __future__ import annotations

import threading
import time as _time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from modules.skills_runtime import SkillExecutionError, SkillValidationError
from modules.ui_components import (
    bind_adaptive_wrap,
    bind_combobox_dropdown_mousewheel,
    CardFrame,
    COLORS,
    create_home_shell_button,
    FONTS,
    ModernButton,
    ScrollablePage,
    SkillCardGrid,
    ToggleSwitch,
)


class DiscoverSkillsPanel:
    def __init__(self, parent, config_mgr, skill_manager, remote_content_manager,
                 marketplace_client, *, set_status, close_panel=None, on_skill_installed=None,
                 on_open_repo_manage=None):
        self.config = config_mgr
        self.skill_manager = skill_manager
        self.remote_content = remote_content_manager
        self.marketplace = marketplace_client
        self.set_status = set_status
        self.close_panel = close_panel
        self.on_skill_installed = on_skill_installed
        self.on_open_repo_manage = on_open_repo_manage
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self._current_source = 'registry'  # 'registry' | 'marketplace'
        self._registry_payload = self.skill_manager.load_registry_cache()
        self._marketplace_payload = None
        self._marketplace_error = None
        self._all_skills = []
        self._filtered_skills = []
        self._search_var = tk.StringVar(value='')
        self._source_filter_var = tk.StringVar(value='全部来源')
        self._status_filter_var = tk.StringVar(value='全部')
        self._search_debounce_job = None
        self._source_buttons = {}
        self._source_filter_combo = None
        self._toolbar_row2 = None
        self._grid_area = None
        self._card_grid = None
        self._count_label = None
        self._search_entry = None

        self._build()
        self._load_source_data('registry')

    # ------------------------------------------------------------------ UI 构建
    def _build(self):
        # 顶部栏
        toolbar = tk.Frame(self.frame, bg=COLORS['bg_main'])
        toolbar.pack(fill=tk.X, pady=(0, 10))
        self._build_toolbar(toolbar)

        # 内容区
        self._grid_area = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        self._grid_area.pack(fill=tk.BOTH, expand=True)

        self._card_grid = SkillCardGrid(
            self._grid_area.inner,
            card_width=280,
            gap_x=14,
            gap_y=14,
            bg=COLORS['bg_main'],
        )
        self._card_grid.pack(fill=tk.BOTH, expand=True)

    def _build_toolbar(self, parent):
        # 第一行：数据源切换 | 搜索框 | 刷新
        row1 = tk.Frame(parent, bg=COLORS['bg_main'])
        row1.pack(fill=tk.X, pady=(0, 8))

        # 数据源切换按钮组
        source_frame = tk.Frame(row1, bg=COLORS['bg_main'])
        source_frame.pack(side=tk.LEFT)

        for source_key, source_label in [('registry', '仓库'), ('marketplace', 'skill.sh')]:
            btn = ModernButton(
                source_frame,
                source_label,
                style='primary' if source_key == self._current_source else 'ghost',
                command=lambda k=source_key: self._switch_source(k),
                padx=16,
                pady=4,
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._source_buttons[source_key] = btn

        # 搜索框
        search_frame = tk.Frame(row1, bg=COLORS['bg_main'])
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 12))

        self._search_entry = tk.Entry(
            search_frame,
            textvariable=self._search_var,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_muted'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
            insertbackground=COLORS['text_main'],
        )
        self._search_entry.pack(fill=tk.X, ipady=5)
        self._search_entry.insert(0, self._SEARCH_PLACEHOLDER)
        self._search_entry.bind('<FocusIn>', self._on_search_focus_in)
        self._search_entry.bind('<FocusOut>', self._on_search_focus_out)
        self._search_entry.bind('<KeyRelease>', self._on_search_changed)

        # 刷新按钮
        refresh_shell, _ = create_home_shell_button(
            row1,
            '刷新',
            command=self._refresh,
            style='ghost',
            padx=10,
            pady=4,
        )
        refresh_shell.pack(side=tk.RIGHT)

        # 第二行：来源筛选 | 安装状态筛选 | 仓库管理 | 计数
        self._toolbar_row2 = tk.Frame(parent, bg=COLORS['bg_main'])
        self._toolbar_row2.pack(fill=tk.X, pady=(0, 4))

        # 来源筛选（仅仓库模式下有意义）
        filter_source_frame = tk.Frame(self._toolbar_row2, bg=COLORS['bg_main'])
        filter_source_frame.pack(side=tk.LEFT)
        tk.Label(
            filter_source_frame,
            text='来源:',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT, padx=(0, 4))
        self._source_filter_combo = ttk.Combobox(
            filter_source_frame,
            textvariable=self._source_filter_var,
            values=['全部来源'],
            state='readonly',
            style='Modern.TCombobox',
            width=14,
        )
        self._source_filter_combo.pack(side=tk.LEFT, ipady=3)
        bind_combobox_dropdown_mousewheel(self._source_filter_combo)
        self._source_filter_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # 安装状态筛选
        filter_status_frame = tk.Frame(self._toolbar_row2, bg=COLORS['bg_main'])
        filter_status_frame.pack(side=tk.LEFT, padx=(16, 0))
        tk.Label(
            filter_status_frame,
            text='状态:',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT, padx=(0, 4))
        status_combo = ttk.Combobox(
            filter_status_frame,
            textvariable=self._status_filter_var,
            values=['全部', '已安装', '未安装'],
            state='readonly',
            style='Modern.TCombobox',
            width=10,
        )
        status_combo.pack(side=tk.LEFT, ipady=3)
        bind_combobox_dropdown_mousewheel(status_combo)
        status_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # 仓库管理按钮
        repo_manage_shell, _ = create_home_shell_button(
            self._toolbar_row2,
            '仓库管理',
            command=self._open_repo_manage,
            style='secondary',
            padx=10,
            pady=4,
        )
        repo_manage_shell.pack(side=tk.LEFT, padx=(20, 0))

        # 计数标签
        self._count_label = tk.Label(
            self._toolbar_row2,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
            anchor='e',
        )
        self._count_label.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ 仓库管理（关闭当前弹窗，打开仓库管理弹窗）
    def _open_repo_manage(self):
        if callable(self.on_open_repo_manage):
            self.on_open_repo_manage()

    # ------------------------------------------------------------------ 搜索占位符
    _SEARCH_PLACEHOLDER = '搜索技能名称/描述...'

    def _is_placeholder_active(self):
        try:
            return self._search_entry and self._search_entry.cget('fg') == COLORS['text_muted']
        except tk.TclError:
            return False

    def _on_search_focus_in(self, _event=None):
        entry = _event.widget
        if entry.get() == self._SEARCH_PLACEHOLDER:
            entry.delete(0, tk.END)
            entry.configure(fg=COLORS['text_main'])

    def _on_search_focus_out(self, _event=None):
        entry = _event.widget
        if not entry.get().strip():
            entry.delete(0, tk.END)
            entry.insert(0, self._SEARCH_PLACEHOLDER)
            entry.configure(fg=COLORS['text_muted'])

    def _on_search_changed(self, _event=None):
        if self._search_debounce_job:
            try:
                self.frame.after_cancel(self._search_debounce_job)
            except Exception:
                pass
        self._search_debounce_job = self.frame.after(300, self._apply_filters)

    # ------------------------------------------------------------------ 数据源切换
    def _switch_source(self, source_key):
        if source_key == self._current_source:
            return
        self._current_source = source_key
        for key, btn in self._source_buttons.items():
            btn.set_style('primary' if key == source_key else 'ghost')
        # 来源筛选仅在仓库模式下启用
        if source_key == 'marketplace':
            self._source_filter_combo.configure(state='disabled')
            self._source_filter_var.set('全部来源')
        else:
            self._source_filter_combo.configure(state='readonly')
        # 重置搜索（正确清空，避免占位符冲突）
        self._search_entry.delete(0, tk.END)
        self._search_entry.insert(0, self._SEARCH_PLACEHOLDER)
        self._search_entry.configure(fg=COLORS['text_muted'])
        self._status_filter_var.set('全部')
        self._load_source_data(source_key)

    # ------------------------------------------------------------------ 数据加载
    def _load_source_data(self, source_type):
        self.set_status('正在加载技能列表...', COLORS['warning'])

        if source_type == 'registry':
            self._load_registry_data()
        else:
            self._load_marketplace_data()

    def _load_registry_data(self):
        repos = self.config.get_skills_repositories()
        enabled_repos = [r for r in repos if r.get('enabled', True)]

        # 更新来源筛选选项
        repo_names = ['全部来源'] + [r.get('name', r.get('id', '')) for r in enabled_repos]
        self._source_filter_combo.configure(values=repo_names)

        if not enabled_repos:
            self._all_skills = []
            self._apply_filters()
            self.set_status('没有已启用的仓库', COLORS['warning'])
            return

        # 先加载本地缓存（用于远程拉取失败时的回退）
        self._registry_payload = self.skill_manager.load_registry_cache()

        # 直接远程拉取，避免缓存渲染后再刷新导致的闪烁
        self._fetch_all_repos(enabled_repos)

    def _merge_registry_to_skills(self):
        installed = self.skill_manager.list_installed_skills(self._registry_payload)
        installed_map = {s.get('id'): s for s in installed}
        registry = self.skill_manager.list_registry_skills(self._registry_payload)
        all_skills = []
        for item in registry:
            skill_id = item.get('id', '')
            if skill_id in installed_map:
                all_skills.append(installed_map[skill_id])
            else:
                all_skills.append(item)
        # 已安装但不在注册表中的本地技能也加入
        for item in installed:
            if item.get('id') not in {s.get('id') for s in all_skills}:
                all_skills.append(item)
        self._all_skills = all_skills

    def _fetch_all_repos(self, repos):
        remaining = len(repos)
        merged_skills = []

        def on_repo_loaded(data):
            nonlocal remaining
            remaining -= 1
            try:
                sanitized = self.skill_manager.sanitize_registry_payload(data)
                merged_skills.extend(sanitized.get('skills', []))
            except Exception:
                pass
            if remaining <= 0:
                self._on_all_repos_fetched(merged_skills)

        def on_repo_error(exc):
            nonlocal remaining
            remaining -= 1
            if remaining <= 0:
                self._on_all_repos_fetched(merged_skills)

        for repo in repos:
            url = str(repo.get('url', '') or '').strip()
            if not url:
                remaining -= 1
                continue
            if repo.get('id') == 'official':
                self.remote_content.fetch('skills_index', on_success=on_repo_loaded, on_error=on_repo_error, force=True)
            else:
                self.remote_content.fetch_custom(url, on_success=on_repo_loaded, on_error=on_repo_error, force=True)

        if remaining <= 0:
            self._on_all_repos_fetched(merged_skills)

    def _on_all_repos_fetched(self, raw_skills):
        installed = self.skill_manager.list_installed_skills(self._registry_payload)
        installed_map = {s.get('id'): s for s in installed}

        all_skills = []
        seen_ids = set()

        # 如果远程拉取有数据，使用远程数据
        if raw_skills:
            for item in self.skill_manager.list_registry_skills(self._registry_payload):
                skill_id = item.get('id', '')
                if skill_id in installed_map:
                    merged = installed_map[skill_id]
                else:
                    merged = item
                if skill_id not in seen_ids:
                    seen_ids.add(skill_id)
                    all_skills.append(merged)
            for raw in raw_skills:
                skill_id = str(raw.get('id', '') or '').strip()
                if skill_id and skill_id not in seen_ids:
                    seen_ids.add(skill_id)
                    view = self.skill_manager.build_skill_view(
                        installed_map.get(skill_id, {}),
                        registry_entry=raw,
                    )
                    all_skills.append(view)
        else:
            # 远程拉取全部失败，回退到本地缓存
            for item in self.skill_manager.list_registry_skills(self._registry_payload):
                skill_id = item.get('id', '')
                if skill_id in installed_map:
                    all_skills.append(installed_map[skill_id])
                else:
                    all_skills.append(item)
                seen_ids.add(skill_id)

        for item in installed:
            if item.get('id') not in seen_ids:
                all_skills.append(item)

        self._all_skills = all_skills
        self._apply_filters()
        if raw_skills:
            self.set_status(f'技能索引已刷新，共 {len(self._all_skills)} 个技能', COLORS['success'])
        else:
            self.set_status(f'使用缓存索引，共 {len(self._all_skills)} 个技能', COLORS['text_sub'])

    def _load_marketplace_data(self):
        self.set_status('正在加载 skill.sh 技能市场...', COLORS['warning'])

        def on_loaded(data):
            self._marketplace_payload = data
            self._merge_marketplace_to_skills(data)
            self._apply_filters()
            skill_count = len(self._all_skills)
            if skill_count > 0:
                self.set_status(f'skill.sh 已加载，共 {skill_count} 个技能', COLORS['success'])
            else:
                self.set_status('skill.sh 已加载，但没有可用技能', COLORS['warning'])

        def on_error(exc):
            self._all_skills = []
            self._marketplace_error = str(exc)
            self._apply_filters()
            self.set_status(f'skill.sh 加载失败: {exc}', COLORS['warning'])

        self._marketplace_error = None
        self.marketplace.fetch_index(on_success=on_loaded, on_error=on_error, force=True)

    def _merge_marketplace_to_skills(self, payload):
        installed = self.skill_manager.list_installed_skills(self._registry_payload)
        installed_map = {s.get('id'): s for s in installed}

        all_skills = []
        seen_ids = set()
        for item in (payload or {}).get('skills', []):
            skill_id = item.get('id', '')
            if not skill_id:
                continue
            seen_ids.add(skill_id)
            if skill_id in installed_map:
                view = dict(installed_map[skill_id])
                view['source_label'] = 'skill.sh'
                if view.get('registry_entry'):
                    view['registry_entry'] = dict(view['registry_entry'], source='marketplace')
                all_skills.append(view)
            else:
                all_skills.append({
                    'id': skill_id,
                    'name': item.get('name', skill_id),
                    'version': item.get('version', ''),
                    'latest_version': item.get('version', ''),
                    'description': item.get('description', ''),
                    'min_app_version': item.get('min_app_version', ''),
                    'download_url': item.get('download_url', ''),
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
                    'source_type': 'marketplace',
                    'source_label': 'skill.sh',
                    'actions_count': 0,
                })

        self._all_skills = all_skills

    # ------------------------------------------------------------------ 筛选
    def _apply_filters(self):
        query = ''
        if not self._is_placeholder_active():
            query = str(self._search_var.get() or '').strip().lower()
        source_filter = str(self._source_filter_var.get() or '')
        status_filter = str(self._status_filter_var.get() or '')

        filtered = []
        for view in self._all_skills:
            # 搜索条件
            if query:
                searchable = ' '.join([
                    str(view.get('name', '') or ''),
                    str(view.get('description', '') or ''),
                    str(view.get('id', '') or ''),
                    str(view.get('publisher', '') or ''),
                ]).lower()
                if query not in searchable:
                    continue
            # 安装状态筛选
            if status_filter == '已安装' and not view.get('is_installed'):
                continue
            if status_filter == '未安装' and view.get('is_installed'):
                continue
            # 来源筛选（仅仓库模式）
            if self._current_source == 'registry' and source_filter and source_filter != '全部来源':
                source_label = str(view.get('source_type', 'registry') or 'registry')
                if source_filter != source_label and source_filter != view.get('source_label', ''):
                    continue
            filtered.append(view)

        self._filtered_skills = filtered
        self._render_skill_grid()
        self._update_count_label()

    def _update_count_label(self):
        total = len(self._all_skills)
        shown = len(self._filtered_skills)
        if shown == total:
            self._count_label.configure(text=f'共 {total} 个技能')
        else:
            self._count_label.configure(text=f'显示 {shown} / {total} 个技能')

    # ------------------------------------------------------------------ 网格渲染
    def _render_skill_grid(self):
        if not self._card_grid:
            return
        self._card_grid.clear_cards()

        if not self._filtered_skills:
            # 区分不同空状态
            if self._current_source == 'marketplace' and getattr(self, '_marketplace_error', None):
                empty_text = f'skill.sh 暂时不可用\n{self._marketplace_error}'
            elif not self._all_skills and self._current_source == 'registry':
                empty_text = '仓库中没有技能，请添加仓库或检查网络连接。'
            elif self._all_skills and not self._filtered_skills:
                empty_text = '没有找到匹配的技能。'
            else:
                empty_text = '暂无技能。'
            tk.Label(
                self._card_grid,
                text=empty_text,
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['bg_main'],
                anchor='center',
                justify='center',
            ).grid(row=0, column=0, sticky='ew')
            self._card_grid.grid_columnconfigure(0, weight=1)
            return

        for view in self._filtered_skills:
            card = self._render_skill_card(view)
            self._card_grid.add_card(card)

        self._refresh_grid_layout()

    def _refresh_grid_layout(self):
        if not self._grid_area:
            return

        def apply_layout():
            try:
                self._grid_area.inner.update_idletasks()
                self._grid_area._apply_layout_refresh()
            except tk.TclError:
                pass

        apply_layout()
        try:
            self.frame.after_idle(apply_layout)
        except tk.TclError:
            pass

    def _render_skill_card(self, view):
        skill_id = view.get('id', '')
        is_installed = bool(view.get('is_installed', False))
        has_update = bool(view.get('has_update', False))
        card = CardFrame(self._card_grid, padding=14)

        # 头部行：名称 + 状态标签
        header = tk.Frame(card.inner, bg=COLORS['card_bg'])
        header.pack(fill=tk.X)
        name_label = tk.Label(
            header,
            text=view.get('name', skill_id),
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        name_label.pack(side=tk.LEFT)

        tag_text = ''
        tag_fg = COLORS['primary']
        if is_installed and has_update:
            tag_text = '可更新'
            tag_fg = COLORS['warning']
        elif is_installed:
            tag_text = '已安装'
            tag_fg = COLORS['success']
        if tag_text:
            tk.Label(
                header,
                text=tag_text,
                font=FONTS['small'],
                fg=tag_fg,
                bg=COLORS['card_bg'],
                anchor='e',
            ).pack(side=tk.RIGHT)

        # 元信息行
        version_val = view.get('version', '') or view.get('latest_version', '')
        version_str = str(version_val).strip()
        if not version_str or version_str == 'v0.0.0':
            version_text = '未知'
        elif not version_str.startswith('v'):
            version_text = 'v' + version_str
        else:
            version_text = version_str
        source_label = view.get('source_label', '') or view.get('source_type', '') or 'registry'
        meta_text = f'版本: {version_text}  来源: {source_label}'
        if view.get('publisher'):
            meta_text += f'  作者: {view.get("publisher")}'
        tk.Label(
            card.inner,
            text=meta_text,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
        ).pack(fill=tk.X, pady=(4, 0))

        # 描述行
        desc = view.get('description', '') or '暂无描述'
        desc_label = tk.Label(
            card.inner,
            text=desc,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify='left',
        )
        desc_label.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(desc_label, card.inner, padding=12, min_width=200)

        # 操作行
        action_row = tk.Frame(card.inner, bg=COLORS['card_bg'])
        action_row.pack(fill=tk.X, pady=(10, 0))

        if is_installed and not has_update:
            installed_btn = ModernButton(
                action_row,
                '已安装',
                style='ghost',
                padx=10,
                pady=3,
                state='disabled',
            )
            installed_btn.pack(side=tk.LEFT)
        else:
            install_label = '更新' if has_update else '安装'
            install_style = 'primary'
            install_btn = ModernButton(
                action_row,
                install_label,
                style=install_style,
                padx=10,
                pady=3,
                command=lambda v=view: self._install_skill(v),
            )
            install_btn.pack(side=tk.LEFT)

        detail_btn = ModernButton(
            action_row,
            '详情',
            style='ghost',
            padx=10,
            pady=3,
            command=lambda v=view: self._show_skill_detail(v),
        )
        detail_btn.pack(side=tk.RIGHT)

        return card

    # ------------------------------------------------------------------ 安装技能
    def _install_skill(self, view):
        skill_id = view.get('id', '')
        skill_name = view.get('name', skill_id)
        is_installed = bool(view.get('is_installed', False))
        is_update = is_installed and view.get('has_update', False)
        registry_entry = view.get('registry_entry') or {}

        download_url = str(registry_entry.get('download_url', '') or '').strip()
        if not download_url:
            messagebox.showinfo('发现技能', f'技能「{skill_name}」没有可用的下载地址。', parent=self.frame.winfo_toplevel())
            return

        action_label = '下载并更新' if is_update else '安装'
        if is_installed:
            if not messagebox.askyesno(
                '覆盖确认',
                f'技能「{skill_name}」已安装。\n当前版本：{view.get("version", "未知")}\n'
                f'导入版本：{registry_entry.get("version", "未知")}\n\n'
                f'继续{action_label}吗？',
                parent=self.frame.winfo_toplevel(),
            ):
                return
        else:
            if not messagebox.askyesno(
                '安装确认',
                f'确定安装技能「{skill_name}」吗？',
                parent=self.frame.winfo_toplevel(),
            ):
                return

        self._run_background(
            lambda: self.skill_manager.download_registry_skill_zip(registry_entry),
            success_message='技能安装完成' if not is_update else '技能更新完成',
            on_success=lambda result: self._on_skill_installed(result, view),
            on_error=self._handle_skill_error,
        )

    def _on_skill_installed(self, result, original_view):
        skill_id = (result or {}).get('id', '') or original_view.get('id', '')
        for item in self._all_skills:
            if item.get('id') == skill_id:
                item['is_installed'] = True
                item['has_update'] = False
                if result:
                    item.update({k: v for k, v in result.items() if k in item})
                break
        self._apply_filters()
        if callable(self.on_skill_installed):
            try:
                self.on_skill_installed()
            except Exception:
                pass

    # ------------------------------------------------------------------ 技能详情
    def _show_skill_detail(self, view):
        detail_window = tk.Toplevel(self.frame.winfo_toplevel())
        skill_name = view.get('name', view.get('id', ''))
        detail_window.title(f'技能详情 - {skill_name}')
        detail_window.configure(bg=COLORS['bg_main'])
        detail_window.transient(self.frame.winfo_toplevel())
        detail_window.resizable(True, True)

        # 居中显示
        w, h = 640, 520
        parent_x = self.frame.winfo_toplevel().winfo_x()
        parent_y = self.frame.winfo_toplevel().winfo_y()
        parent_w = self.frame.winfo_toplevel().winfo_width()
        parent_h = self.frame.winfo_toplevel().winfo_height()
        x = parent_x + (parent_w - w) // 2
        y = parent_y + (parent_h - h) // 2
        detail_window.geometry(f'{w}x{h}+{max(0, x)}+{max(0, y)}')
        detail_window.minsize(480, 360)

        # 内容
        card = tk.Frame(detail_window, bg=COLORS['shadow'])
        card.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        body = tk.Frame(card, bg=COLORS['card_bg'], highlightbackground=COLORS['card_border'], highlightthickness=2, bd=0)
        body.pack(fill=tk.BOTH, expand=True, padx=(0, 6), pady=(0, 6))

        scroll = ScrollablePage(body, bg=COLORS['card_bg'])
        scroll.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        inner = scroll.inner

        # 标题
        tk.Label(inner, text=skill_name, font=FONTS['subtitle'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg'], anchor='w').pack(fill=tk.X)

        # 基本信息
        is_installed = bool(view.get('is_installed', False))
        status_parts = []
        if is_installed:
            status_parts.append('已安装')
        if view.get('has_update'):
            status_parts.append('可更新')
        if view.get('is_local_only'):
            status_parts.append('仅本地')
        if not is_installed:
            status_parts.append('未安装')
        status_text = ' / '.join(status_parts) if status_parts else '未知'

        meta_lines = [
            f'ID: {view.get("id", "")}',
            f'版本: {view.get("version", "未知")}  最新: {view.get("latest_version", view.get("version", "未知"))}',
            f'来源: {view.get("source_type", "registry") or "registry"}',
            f'发布者: {view.get("publisher", "未知")}',
            f'状态: {status_text}',
        ]
        if is_installed:
            from pages.skills_center_page import _format_timestamp
            meta_lines.append(f'安装时间: {_format_timestamp(view.get("installed_at", 0))}')
            meta_lines.append(f'启用: {"是" if view.get("enabled") else "否"}')
            meta_lines.append(f'全局生效: {"是" if view.get("global_enabled") else "否"}')

        tk.Label(inner, text='\n'.join(meta_lines), font=FONTS['small'], fg=COLORS['text_sub'],
                 bg=COLORS['card_bg'], anchor='w', justify='left').pack(fill=tk.X, pady=(10, 0))

        # 描述
        desc = view.get('description', '') or '暂无描述'
        tk.Label(inner, text='描述:', font=FONTS['body_bold'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg'], anchor='w').pack(fill=tk.X, pady=(14, 4))
        desc_label = tk.Label(inner, text=desc, font=FONTS['body'], fg=COLORS['text_sub'],
                              bg=COLORS['card_bg'], anchor='w', justify='left')
        desc_label.pack(fill=tk.X)
        bind_adaptive_wrap(desc_label, inner, padding=12, min_width=400)

        # 场景绑定
        scene_bindings = view.get('scene_bindings', [])
        if scene_bindings:
            tk.Label(inner, text='适用场景:', font=FONTS['body_bold'], fg=COLORS['text_main'],
                     bg=COLORS['card_bg'], anchor='w').pack(fill=tk.X, pady=(14, 4))
            tk.Label(inner, text=', '.join(scene_bindings), font=FONTS['body'], fg=COLORS['text_sub'],
                     bg=COLORS['card_bg'], anchor='w', justify='left').pack(fill=tk.X)

        # 操作按钮
        btn_row = tk.Frame(inner, bg=COLORS['card_bg'])
        btn_row.pack(fill=tk.X, pady=(20, 0))

        if not is_installed or view.get('has_update'):
            label = '更新' if is_installed else '安装'
            install_btn = ModernButton(
                btn_row,
                label,
                style='primary',
                padx=14,
                pady=5,
                command=lambda v=view: (detail_window.destroy(), self._install_skill(v)),
            )
            install_btn.pack(side=tk.LEFT, padx=(0, 8))

        homepage = ''
        if view.get('manifest'):
            homepage = str(view.get('manifest', {}).get('homepage', '') or '').strip()
        if not homepage and view.get('registry_entry'):
            homepage = str(view.get('registry_entry', {}).get('homepage', '') or '').strip()
        if homepage:
            ModernButton(
                btn_row,
                '打开主页',
                style='secondary',
                padx=14,
                pady=5,
                command=lambda: webbrowser.open(homepage),
            ).pack(side=tk.LEFT, padx=(0, 8))

        ModernButton(
            btn_row,
            '关闭',
            style='ghost',
            padx=14,
            pady=5,
            command=detail_window.destroy,
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ 刷新
    def _refresh(self):
        self._load_source_data(self._current_source)

    # ------------------------------------------------------------------ 后台任务
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
                        messagebox.showerror('发现技能', str(error), parent=self.frame.winfo_toplevel())
                    return
                if success_message:
                    self.set_status(success_message, COLORS['success'])
                if callable(on_success):
                    on_success(result)

            self.frame.after(0, finalize)

        threading.Thread(target=runner, name='DiscoverSkillsAction', daemon=True).start()

    def _handle_skill_error(self, error):
        messagebox.showerror('发现技能', str(error), parent=self.frame.winfo_toplevel())
        if isinstance(error, (SkillValidationError, SkillExecutionError)):
            self.set_status(str(error), COLORS['error'])
        else:
            self.set_status('技能操作失败', COLORS['error'])


# ======================================================================
# 仓库管理弹窗面板（独立于发现技能弹窗，关闭后自动重新打开发现技能弹窗）
# ======================================================================

class RepoManagePanel:
    def __init__(self, parent, config_mgr, skill_manager, remote_content_manager, *, set_status, close_panel=None):
        self.config = config_mgr
        self.skill_manager = skill_manager
        self.remote_content = remote_content_manager
        self.set_status = set_status
        self.close_panel = close_panel
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self._build()

    def _build(self):
        scroll = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        scroll.pack(fill=tk.BOTH, expand=True)
        inner = scroll.inner
        self._scroll = scroll

        # 添加仓库卡片
        add_card = CardFrame(inner, title='添加仓库', padding=16)
        add_card.pack(fill=tk.X, pady=(0, 14))

        name_frame = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        name_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(name_frame, text='仓库名称:', font=FONTS['body'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg']).pack(side=tk.LEFT)
        name_var = tk.StringVar()
        name_entry = tk.Entry(name_frame, textvariable=name_var, font=FONTS['body'],
                              bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT,
                              highlightthickness=1, highlightbackground=COLORS['input_border'],
                              insertbackground=COLORS['text_main'])
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=4)

        url_frame = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        url_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(url_frame, text='索引 URL:', font=FONTS['body'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg']).pack(side=tk.LEFT)
        url_var = tk.StringVar()
        url_entry = tk.Entry(url_frame, textvariable=url_var, font=FONTS['body'],
                             bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT,
                             highlightthickness=1, highlightbackground=COLORS['input_border'],
                             insertbackground=COLORS['text_main'])
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=4)

        add_btn_row = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        add_btn_row.pack(fill=tk.X, pady=(4, 0))

        def do_add():
            name = str(name_var.get() or '').strip()
            url = str(url_var.get() or '').strip()
            if not url:
                messagebox.showwarning('添加仓库', '请输入索引 URL。', parent=self.frame.winfo_toplevel())
                return
            if not name:
                name = url.split('/')[-1] or '自定义仓库'
            self.set_status('正在验证仓库...', COLORS['warning'])

            def on_validated(data):
                try:
                    self.skill_manager.sanitize_registry_payload(data)
                    self.config.add_skills_repository({
                        'id': '',
                        'name': name,
                        'url': url,
                        'type': 'generic_json',
                        'added_at': int(_time.time()),
                        'enabled': True,
                    })
                    self.set_status('仓库添加成功', COLORS['success'])
                    self._refresh_repo_list()
                except Exception as exc:
                    messagebox.showerror('添加仓库', f'索引格式不兼容: {exc}', parent=self.frame.winfo_toplevel())

            def on_validate_error(exc):
                messagebox.showerror('添加仓库', f'无法访问该 URL: {exc}', parent=self.frame.winfo_toplevel())

            self.remote_content.fetch_custom(url, on_success=on_validated, on_error=on_validate_error, force=True)

        ModernButton(add_btn_row, '添加仓库', style='primary', padx=14, pady=5, command=do_add).pack(side=tk.LEFT)

        # 已添加仓库列表卡片
        self._list_card_placeholder = tk.Frame(inner, bg=COLORS['bg_main'])
        self._list_card_placeholder.pack(fill=tk.BOTH, expand=True)
        self._refresh_repo_list()

        # 确保首次布局刷新（延迟稍长，等窗口完成渲染）
        def _force_refresh():
            try:
                self.frame.update_idletasks()
                self._scroll._apply_layout_refresh()
            except tk.TclError:
                pass
        try:
            self.frame.after(50, _force_refresh)
        except tk.TclError:
            pass

    def _refresh_repo_list(self):
        for child in self._list_card_placeholder.winfo_children():
            child.destroy()

        repos = self.config.get_skills_repositories()
        list_card = CardFrame(self._list_card_placeholder, title=f'已添加仓库 ({len(repos)})', padding=16)
        list_card.pack(fill=tk.BOTH, expand=True)

        if not repos:
            tk.Label(list_card.inner, text='暂无已添加的仓库。', font=FONTS['body'], fg=COLORS['text_sub'],
                     bg=COLORS['card_bg'], anchor='w').pack(fill=tk.X)
        else:
            for repo in repos:
                self._render_repo_item(list_card.inner, repo)

        # 刷新滚动区域布局
        def _force_refresh():
            try:
                self.frame.update_idletasks()
                self._scroll._apply_layout_refresh()
            except tk.TclError:
                pass
        try:
            self.frame.after(50, _force_refresh)
        except tk.TclError:
            pass

    def _render_repo_item(self, parent, repo):
        repo_id = repo.get('id', '')
        is_official = repo_id == 'official'
        enabled = repo.get('enabled', True)

        item_frame = tk.Frame(parent, bg=COLORS['surface_alt'], highlightbackground=COLORS['divider'],
                              highlightthickness=1, bd=0)
        item_frame.pack(fill=tk.X, pady=(0, 8))

        header = tk.Frame(item_frame, bg=COLORS['surface_alt'])
        header.pack(fill=tk.X, padx=14, pady=(10, 0))

        name_text = repo.get('name', repo_id)
        if is_official:
            name_text += '  (官方)'
        tk.Label(header, text=name_text, font=FONTS['body_bold'], fg=COLORS['text_main'],
                 bg=COLORS['surface_alt'], anchor='w').pack(side=tk.LEFT)

        enabled_var = tk.BooleanVar(value=enabled)

        def on_toggle(rid=repo_id, var=enabled_var):
            self.config.update_skills_repository(rid, {'enabled': var.get()})

        enable_label = tk.Label(
            header,
            text='启用',
            font=FONTS['small'],
            fg=COLORS['text_main'],
            bg=COLORS['surface_alt'],
        )
        enable_label.pack(side=tk.RIGHT, padx=(0, 4))
        ToggleSwitch(
            header,
            variable=enabled_var,
            command=on_toggle,
            bg=COLORS['surface_alt'],
        ).pack(side=tk.RIGHT)

        url_text = repo.get('url', '')
        tk.Label(item_frame, text=url_text, font=FONTS['small'], fg=COLORS['text_sub'],
                 bg=COLORS['surface_alt'], anchor='w').pack(fill=tk.X, padx=14, pady=(4, 6))

        if not is_official:
            del_row = tk.Frame(item_frame, bg=COLORS['surface_alt'])
            del_row.pack(fill=tk.X, padx=14, pady=(0, 10))

            def do_delete(rid=repo_id, rname=repo.get('name', repo_id)):
                if not messagebox.askyesno('删除仓库', f'确定删除仓库「{rname}」吗？',
                                           parent=self.frame.winfo_toplevel()):
                    return
                self.config.remove_skills_repository(rid)
                self._refresh_repo_list()

            ModernButton(del_row, '删除', style='danger', padx=10, pady=3, command=do_delete).pack(side=tk.RIGHT)
