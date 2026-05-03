# -*- coding: utf-8 -*-
"""
模型配置页面
"""

import json
import tkinter as tk
from tkinter import messagebox, ttk

from modules.task_runner import TaskRunner
from modules.config import resolve_model_display_name
from modules.ui_components import (
    bind_combobox_dropdown_mousewheel,
    COLORS,
    FONTS,
    LoadingOverlay,
    ModernButton,
    ModernEntry,
    ScrollablePage,
    ToggleSwitch,
)
from modules.provider_registry import (
    AUTH_OPTION_CUSTOM,
    AUTH_VALUE_MODE_BEARER,
    AUTH_VALUE_MODE_RAW,
    MODEL_LIST_MANUAL,
    PRESET_OPTIONS,
    get_api_format_label,
    get_preset_definition,
    get_protocol_auth_option_label,
    get_protocol_auth_options,
    list_visible_protocol_options,
    normalize_api_format,
    normalize_provider_type,
    resolve_auth_option_definition,
    resolve_auth_option_id,
    resolve_model_list_strategy,
)
from pages.api_config_support import (
    FORM_KEY,
    PRESET_MAP,
    build_base_form_template,
    merge_with_preset_defaults,
)

BILLING_MODE_DISPLAY = {
    'request_model': '按请求模型匹配',
    'response_model': '按返回模型匹配',
}
BILLING_MODE_REVERSE = {label: key for key, label in BILLING_MODE_DISPLAY.items()}

API_FORMAT_DISPLAY = {protocol_id: label for protocol_id, label in list_visible_protocol_options()}
API_FORMAT_REVERSE = {label: protocol_id for protocol_id, label in API_FORMAT_DISPLAY.items()}
AUTH_VALUE_MODE_DISPLAY = {
    AUTH_VALUE_MODE_BEARER: 'Bearer 前缀',
    AUTH_VALUE_MODE_RAW: '原样',
}
AUTH_VALUE_MODE_REVERSE = {label: value for value, label in AUTH_VALUE_MODE_DISPLAY.items()}


class APIConfigPage:
    def __init__(
        self,
        parent,
        config_mgr,
        api_client,
        history_mgr,
        set_status,
        navigate_page=None,
        app_bridge=None,
        force_new=False,
    ):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self._default_force_new = bool(force_new)

        self._on_save_callback = None
        self._on_state_change_callback = None
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text='正在测试模型连接...')

        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._entries = {}
        self._content = None
        self._provider_grid_frame = None
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}
        self._save_as_new = self._default_force_new

        self._initialize_current_form()
        self._build()

    def _initialize_current_form(self):
        if self._default_force_new:
            self._load_preset_draft('openai', reload=False)
            return

        active_api = self.config.active_api
        if active_api and self.config.get_api_config(active_api):
            self._load_saved_record(active_api, reload=False)
            return

        saved_apis = self.config.list_saved_apis()
        if saved_apis:
            self._load_saved_record(saved_apis[0][0], reload=False)
            return

        self._load_preset_draft('openai', reload=False)

    def _load_preset_draft(self, provider_type, reload=True):
        provider_type = normalize_provider_type(provider_type)
        provider_type = provider_type if provider_type in PRESET_MAP else 'custom'
        self._save_as_new = True
        self._current_api_id = None
        self._current_provider_type = provider_type
        self._current_config = merge_with_preset_defaults({}, provider_type)
        if reload:
            self._reload_panel()
        self._notify_state_change()

    def _load_saved_record(self, api_id, reload=True):
        cfg = self.config.get_api_config(api_id)
        if not cfg:
            self._load_preset_draft('openai', reload=reload)
            return

        provider_type = normalize_provider_type(cfg.get('provider_type') or api_id)

        self._save_as_new = False
        self._current_api_id = api_id
        self._current_provider_type = provider_type
        self._current_config = merge_with_preset_defaults(cfg, provider_type)
        if reload:
            self._reload_panel()
        self._notify_state_change()

    def _notify_state_change(self):
        if self._on_state_change_callback:
            self._on_state_change_callback()

    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 12))
        hdr_left = tk.Frame(header, bg=COLORS['bg_main'])
        hdr_left.pack(fill=tk.X, expand=True)
        tk.Label(
            hdr_left,
            text='\u2699  模型配置中心',
            font=FONTS['subtitle'],
            fg=COLORS['primary'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w')
        tk.Label(
            hdr_left,
            text='预设按钮只负责填充模板，填写服务商名称和密钥后再保存为一条记录。',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w', pady=(4, 0))

        self._scroll_page = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        self._scroll_page.pack(fill=tk.BOTH, expand=True)
        self._content = self._scroll_page.inner
        self._build_api_panel(self._content)

    def _reload_panel(self):
        if not self._content:
            return

        new_frame = tk.Frame(self._content, bg=COLORS['bg_main'])
        self._entries = {}
        if hasattr(self, 'tip_label'):
            del self.tip_label

        self._build_api_panel(new_frame)
        for widget in self._content.winfo_children():
            if widget is not new_frame:
                widget.destroy()
        new_frame.pack(fill=tk.BOTH, expand=True)
        self._scroll_page.scroll_to_top()

    def _get_form_entries(self):
        return self._entries.setdefault(FORM_KEY, {})

    def _get_form_config(self):
        return dict(self._current_config or build_base_form_template(self._current_provider_type))

    def _get_current_api_format(self):
        cfg = self._get_form_config()
        preset_format = get_preset_definition(self._current_provider_type).get('api_format', '')
        return normalize_api_format(cfg.get('api_format', preset_format))

    @staticmethod
    def _format_selected_model_label(model_id, display_name=''):
        model_id = str(model_id or '').strip()
        display_name = str(display_name or '').strip()
        if display_name:
            return f'已选择：{display_name}'
        if model_id:
            return f'已选择：{model_id}'
        return '已选择：（未选择）'

    def _refresh_protocol_dependent_form(self, form_key, api_format):
        cfg = self._collect_api_config(form_key)
        cfg['api_format'] = normalize_api_format(api_format)
        if self._current_provider_type == 'custom':
            auth_option = resolve_auth_option_definition(cfg['api_format'], resolve_auth_option_id(cfg['api_format']))
            if auth_option:
                cfg['auth_field'] = auth_option.get('auth_field', cfg.get('auth_field', ''))
                cfg['auth_value_mode'] = auth_option.get('auth_value_mode', cfg.get('auth_value_mode', ''))
        self._current_config = merge_with_preset_defaults(cfg, self._current_provider_type)
        self._reload_panel()

    def _select_api(self, target_id):
        """按 api_id 加载记录（仅用于「查看详情」跳转，进入编辑模式）"""
        if target_id in self.config.get_saved_apis():
            self._load_saved_record(target_id, reload=True)
            return
        self._load_preset_draft(target_id, reload=True)

    def _select_preset(self, preset_id):
        """点击预设模板按钮，始终创建新草稿（不进入编辑模式）"""
        self._load_preset_draft(preset_id, reload=True)

    def _build_api_panel(self, parent):
        self._entries[FORM_KEY] = {}

        grid_card = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        grid_card.pack(fill=tk.X, pady=(0, 10))

        grid_title_row = tk.Frame(grid_card, bg=COLORS['card_bg'])
        grid_title_row.pack(fill=tk.X, padx=16, pady=(10, 6))
        tk.Label(
            grid_title_row,
            text='选择预设模板',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        tk.Label(
            grid_title_row,
            text='预设按钮只负责填充模板，填写服务商名称和密钥后再保存为一条记录。',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.RIGHT)

        self._provider_grid_frame = tk.Frame(grid_card, bg=COLORS['card_bg'])
        self._provider_grid_frame.pack(fill=tk.X, padx=16, pady=(0, 10))
        self._build_provider_grid(self._provider_grid_frame)

        self._build_basic_section(parent, FORM_KEY)
        self._build_collapsible_section(parent, '高级选项', lambda p: self._build_advanced_options(p, FORM_KEY))
        self._build_json_section(parent, FORM_KEY)

        entries = self._entries.setdefault(FORM_KEY, {})
        use_separate_test = entries.get('use_separate_test')
        if use_separate_test is None:
            use_separate_test = tk.BooleanVar(value=bool(self._get_form_config().get('use_separate_test', False)))
            entries['use_separate_test'] = use_separate_test

        def make_test_toggle(title_row):
            self._make_section_switch(title_row, use_separate_test)

        self._build_collapsible_section(
            parent,
            '模型测试配置',
            lambda p: self._build_test_section(p, FORM_KEY, use_separate_test),
            collapsed=True,
            right_widget_factory=make_test_toggle,
            open_var=use_separate_test,
        )

        use_separate_params = entries.get('use_separate_params')
        if use_separate_params is None:
            use_separate_params = tk.BooleanVar(value=bool(self._get_form_config().get('use_separate_params', False)))
            entries['use_separate_params'] = use_separate_params

        def make_params_toggle(title_row):
            self._make_section_switch(title_row, use_separate_params)

        self._build_collapsible_section(
            parent,
            '参数需求',
            lambda p: self._build_params_section(p, FORM_KEY, use_separate_params),
            collapsed=True,
            right_widget_factory=make_params_toggle,
            open_var=use_separate_params,
        )
        self._build_billing_section(parent, FORM_KEY)

    def _build_provider_grid(self, parent):
        for widget in parent.winfo_children():
            widget.destroy()

        cols = 5
        for i, (preset_id, label, _defaults) in enumerate(PRESET_OPTIONS):
            is_selected = (preset_id == self._current_provider_type)
            btn_bg = COLORS['primary'] if is_selected else COLORS['surface_alt']
            btn_fg = '#ffffff' if is_selected else COLORS['text_main']
            btn = tk.Label(
                parent,
                text=label,
                font=FONTS['small'],
                bg=btn_bg,
                fg=btn_fg,
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=5,
                cursor='hand2',
                highlightbackground=COLORS['primary'] if is_selected else COLORS['card_border'],
                highlightthickness=1,
            )
            btn.grid(row=i // cols, column=i % cols, padx=4, pady=3, sticky='ew')
            btn.bind('<Button-1>', lambda _event, aid=preset_id: self._select_preset(aid))

        for col in range(cols):
            parent.columnconfigure(col, weight=1)

    def _make_card(self, parent, title, right_widget_factory=None):
        shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 10))

        card = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        title_row = tk.Frame(card, bg=COLORS['card_bg'])
        title_row.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(
            title_row,
            text=title,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)

        if right_widget_factory:
            right_widget_factory(title_row)

        inner = tk.Frame(card, bg=COLORS['card_bg'])
        inner.pack(fill=tk.X, padx=16, pady=(10, 14))
        return card, inner

    def _make_section_switch(self, title_row, variable):
        switch = tk.Checkbutton(
            title_row,
            text='使用单独配置',
            variable=variable,
            indicatoron=False,
            relief=tk.FLAT,
            bd=0,
            cursor='hand2',
            font=FONTS['small'],
            padx=14,
            pady=6,
            highlightthickness=0,
        )

        def refresh_switch():
            active = bool(variable.get())
            switch.configure(
                bg=COLORS['accent'] if active else COLORS['surface_alt'],
                fg=COLORS['text_main'] if active else COLORS['text_sub'],
                activebackground=COLORS['accent'] if active else COLORS['surface_alt'],
                activeforeground=COLORS['text_main'] if active else COLORS['text_sub'],
                selectcolor=COLORS['accent'] if active else COLORS['surface_alt'],
                text='使用单独配置' if active else '使用单独配置',
            )

        def toggle_switch(_event):
            variable.set(not bool(variable.get()))
            switch.focus_set()
            return 'break'

        switch.configure(command=refresh_switch)
        switch.bind('<Button-1>', toggle_switch)
        variable.trace_add('write', lambda *_: refresh_switch())
        refresh_switch()
        switch.pack(side=tk.RIGHT)

    def _build_collapsible_section(self, parent, title, build_fn, collapsed=True, right_widget_factory=None, open_var=None):
        shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 10))

        card = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        is_open = tk.BooleanVar(value=not collapsed)

        header_row = tk.Frame(card, bg=COLORS['card_bg'], cursor='hand2')
        header_row.pack(fill=tk.X, padx=16, pady=(10, 10))

        arrow_lbl = tk.Label(
            header_row,
            text='\u25b6' if collapsed else '\u25bc',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            cursor='hand2',
        )
        arrow_lbl.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(
            header_row,
            text=title,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            cursor='hand2',
        ).pack(side=tk.LEFT)

        if right_widget_factory:
            right_widget_factory(header_row)

        body = tk.Frame(card, bg=COLORS['card_bg'])
        built = [False]

        def set_body_visible(visible):
            if visible:
                if not built[0]:
                    build_fn(body)
                    built[0] = True
                body.pack(fill=tk.X, padx=16, pady=(0, 12))
                arrow_lbl.configure(text='\u25bc')
            else:
                body.pack_forget()
                arrow_lbl.configure(text='\u25b6')

        def toggle(event=None):
            set_body_visible(not bool(body.winfo_manager()))

        if open_var is not None:
            build_fn(body)
            built[0] = True
            open_var.trace_add('write', lambda *_: set_body_visible(bool(open_var.get())))
            set_body_visible(bool(open_var.get()))
            header_row.bind('<Button-1>', toggle)
            arrow_lbl.bind('<Button-1>', toggle)
        else:
            header_row.bind('<Button-1>', toggle)
            arrow_lbl.bind('<Button-1>', toggle)
            if not collapsed:
                build_fn(body)
                built[0] = True
                set_body_visible(True)

        return card

    def _entry_row(self, parent, label, key, form_key, placeholder='', show='', width=40, prefill=None, toggle_mask=False):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text=label,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        cfg = self._get_form_config()
        if toggle_mask:
            entry_wrap = tk.Frame(row, bg=COLORS['card_bg'])
            entry_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)

            entry = ModernEntry(entry_wrap, placeholder=placeholder, show=show, width=width)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

            toggle_btn = ModernButton(entry_wrap, '显示', style='secondary', padx=12, pady=6)
            toggle_btn.configure(command=lambda e=entry, b=toggle_btn: self._toggle_entry_mask(e, b))
            toggle_btn.pack(side=tk.LEFT, padx=(8, 0))
        else:
            entry = ModernEntry(row, placeholder=placeholder, show=show, width=width)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

        saved = cfg.get(key, '')
        value = saved if saved else (prefill or '')
        if value:
            entry.delete(0, tk.END)
            entry.insert(0, value)
            entry.configure(fg=COLORS['text_main'])
            entry._placeholder_active = False
            entry.refresh_mask_state()

        self._entries[form_key][key] = entry
        return entry

    def _toggle_entry_mask(self, entry, toggle_btn):
        entry.toggle_mask()
        toggle_btn.configure(text='隐藏' if entry.is_mask_visible() else '显示')

    def _combo_row(self, parent, label, key, form_key, values, width=35):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text=label,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        cfg = self._get_form_config()
        var = tk.StringVar(value=cfg.get(key, values[0] if values else ''))
        combo = ttk.Combobox(
            row,
            textvariable=var,
            values=values,
            style='Modern.TCombobox',
            width=width,
            state='readonly',
        )
        combo.pack(side=tk.LEFT)
        bind_combobox_dropdown_mousewheel(combo)
        self._entries[form_key][key] = var
        return combo, var

    def _billing_mode_row(self, parent, form_key, width=28):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text='计费模式',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        cfg = self._get_form_config()
        current_value = str(cfg.get('billing_mode', '') or '').strip()
        current_label = BILLING_MODE_DISPLAY.get(current_value, '')
        var = tk.StringVar(value=current_label)
        combo = ttk.Combobox(
            row,
            textvariable=var,
            values=[''] + list(BILLING_MODE_DISPLAY.values()),
            style='Modern.TCombobox',
            width=width,
            state='readonly',
        )
        combo.pack(side=tk.LEFT)
        bind_combobox_dropdown_mousewheel(combo)
        self._entries[form_key]['billing_mode'] = var
        return combo, var

    def _build_basic_section(self, parent, form_key):
        def make_reset_button(title_row):
            ModernButton(
                title_row,
                '重置当前表单',
                style='secondary',
                command=self._reset,
                padx=16,
                pady=8,
            ).pack(side=tk.RIGHT)

        _, inner = self._make_card(parent, '基础配置', right_widget_factory=make_reset_button)
        cfg = self._get_form_config()
        preset = PRESET_MAP.get(self._current_provider_type, PRESET_MAP['custom'])
        preset_defaults = preset.get('defaults', {})
        current_api_format = self._get_current_api_format()
        model_list_strategy = resolve_model_list_strategy(self._current_provider_type, current_api_format)
        model_requires_manual_input = model_list_strategy == MODEL_LIST_MANUAL

        info_row = tk.Frame(inner, bg=COLORS['card_bg'])
        info_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            info_row,
            text='预设模板',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(
            info_row,
            text=preset['label'],
            font=FONTS['body_bold'],
            fg=COLORS['primary'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)

        self._entry_row(inner, '服务商名称', 'name', form_key, placeholder='请输入服务商名称', width=40)
        self._entry_row(inner, '备注', 'remark', form_key, placeholder='可选备注信息', width=40)
        self._entry_row(inner, '官网链接', 'website', form_key, placeholder=preset_defaults.get('website', 'https://...'), width=40)
        self._entry_row(inner, 'API Key', 'key', form_key, placeholder='请输入 API Key', show='*', width=40, toggle_mask=True)
        self._entry_row(
            inner,
            '请求地址',
            'base_url',
            form_key,
            placeholder=preset_defaults.get('base_url', 'https://your-api-endpoint/v1'),
            width=40,
        )

        mv_row = tk.Frame(inner, bg=COLORS['card_bg'])
        mv_row.pack(fill=tk.X, pady=4)
        tk.Label(
            mv_row,
            text='模型 ID',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        model_init = cfg.get('model', '')
        model_sel_lbl = tk.Label(
            mv_row,
            text=(
                self._format_selected_model_label(model_init, resolve_model_display_name(cfg))
                if model_init
                else '请手动填写模型 ID' if model_requires_manual_input else '已选择：（未选择）'
            ),
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        if model_requires_manual_input:
            model_entry = ModernEntry(mv_row, placeholder='请手动填写模型 ID', width=32)
            model_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
            if model_init:
                model_entry.delete(0, tk.END)
                model_entry.insert(0, model_init)
                model_entry.configure(fg=COLORS['text_main'])
                model_entry._placeholder_active = False
            self._entries[form_key]['model'] = model_entry

            def refresh_manual_model_label(_event=None):
                model_value = model_entry.get_value().strip()
                model_sel_lbl.configure(
                    text=(
                        self._format_selected_model_label(model_value)
                        if model_value
                        else '请手动填写模型 ID'
                    )
                )

            model_entry.bind('<KeyRelease>', refresh_manual_model_label)
            model_entry.bind('<FocusIn>', refresh_manual_model_label, add='+')
            model_entry.bind('<FocusOut>', refresh_manual_model_label, add='+')
        else:
            model_var = tk.StringVar(value=model_init)
            self._entries[form_key]['model'] = model_var
            model_combo = ttk.Combobox(
                mv_row,
                textvariable=model_var,
                values=[model_init] if model_init else [],
                style='Modern.TCombobox',
                width=32,
            )
            model_combo.pack(side=tk.LEFT)
            bind_combobox_dropdown_mousewheel(model_combo)
            ModernButton(
                mv_row,
                '刷新',
                style='secondary',
                command=lambda: self._fetch_models(form_key, model_combo, model_sel_lbl),
                padx=8,
                pady=4,
            ).pack(side=tk.LEFT, padx=(6, 0))
        model_sel_lbl.pack(side=tk.LEFT, padx=(10, 0))
        if not model_requires_manual_input:
            model_var.trace_add(
                'write',
                lambda *_args: model_sel_lbl.configure(
                    text=(
                        self._format_selected_model_label(model_var.get())
                        if model_var.get()
                        else '已选择：（未选择）'
                    )
                ),
            )

        if not hasattr(self, 'tip_label'):
            self.tip_label = tk.Label(
                inner,
                text='',
                font=FONTS['small'],
                fg=COLORS['success'],
                bg=COLORS['card_bg'],
                anchor='w',
            )
            self.tip_label.pack(anchor='w', pady=(4, 0))

    def _build_advanced_options(self, parent, form_key):
        cfg = self._get_form_config()
        current_api_format = self._get_current_api_format()
        protocol_display_map = dict(API_FORMAT_DISPLAY)
        if current_api_format not in protocol_display_map:
            protocol_display_map[current_api_format] = get_api_format_label(current_api_format)

        if self._current_provider_type == 'custom':
            row = tk.Frame(parent, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=4)
            tk.Label(
                row,
                text='API 格式',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=16,
                anchor='e',
            ).pack(side=tk.LEFT, padx=(0, 10))
            api_format_var = tk.StringVar(value=protocol_display_map[current_api_format])
            combo = ttk.Combobox(
                row,
                textvariable=api_format_var,
                values=list(protocol_display_map.values()),
                style='Modern.TCombobox',
                width=35,
                state='readonly',
            )
            combo.pack(side=tk.LEFT)
            bind_combobox_dropdown_mousewheel(combo)
            self._entries[form_key]['api_format'] = api_format_var
            original_api_format = current_api_format

            def on_protocol_change(*_args):
                next_api_format = API_FORMAT_REVERSE.get(api_format_var.get(), original_api_format)
                if normalize_api_format(next_api_format) == normalize_api_format(original_api_format):
                    return
                self._refresh_protocol_dependent_form(form_key, next_api_format)

            api_format_var.trace_add('write', on_protocol_change)
        else:
            row = tk.Frame(parent, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=4)
            tk.Label(
                row,
                text='API 格式',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=16,
                anchor='e',
            ).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(
                row,
                text=get_api_format_label(current_api_format),
                font=FONTS['body_bold'],
                fg=COLORS['primary'],
                bg=COLORS['card_bg'],
            ).pack(side=tk.LEFT)
            self._entries[form_key]['api_format'] = tk.StringVar(value=current_api_format)

        auth_options = get_protocol_auth_options(current_api_format)
        auth_option_ids = [str(option.get('id', '') or '').strip() for option in auth_options]
        auth_option_labels = {
            option_id: get_protocol_auth_option_label(current_api_format, option_id)
            for option_id in auth_option_ids
            if option_id
        }
        current_auth_option_id = resolve_auth_option_id(
            current_api_format,
            cfg.get('auth_field', ''),
            cfg.get('auth_value_mode', ''),
        )
        current_auth_label = auth_option_labels.get(current_auth_option_id, '')

        if self._current_provider_type == 'custom' and len(auth_option_labels) > 1:
            row = tk.Frame(parent, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=4)
            tk.Label(
                row,
                text='认证方式',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=16,
                anchor='e',
            ).pack(side=tk.LEFT, padx=(0, 10))
            auth_scheme_var = tk.StringVar(value=current_auth_label)
            combo = ttk.Combobox(
                row,
                textvariable=auth_scheme_var,
                values=list(auth_option_labels.values()),
                style='Modern.TCombobox',
                width=35,
                state='readonly',
            )
            combo.pack(side=tk.LEFT)
            bind_combobox_dropdown_mousewheel(combo)
            self._entries[form_key]['auth_scheme'] = auth_scheme_var

            custom_auth_container = tk.Frame(parent, bg=COLORS['card_bg'])
            custom_auth_container.pack(fill=tk.X, pady=(0, 4))

            def refresh_custom_auth_fields(*_args):
                current_custom_field = str(cfg.get('auth_field', '') or '').strip()
                current_custom_mode = str(cfg.get('auth_value_mode', AUTH_VALUE_MODE_BEARER) or '').strip().lower()
                existing_field_entry = self._entries[form_key].get('auth_custom_field')
                if isinstance(existing_field_entry, ModernEntry):
                    current_custom_field = existing_field_entry.get_value().strip() or current_custom_field
                existing_value_mode = self._entries[form_key].get('auth_custom_value_mode')
                if existing_value_mode is not None:
                    current_custom_mode = AUTH_VALUE_MODE_REVERSE.get(
                        str(existing_value_mode.get() or '').strip(),
                        current_custom_mode,
                    )
                for child in custom_auth_container.winfo_children():
                    child.destroy()
                selected_option_id = next(
                    (
                        option_id
                        for option_id, label in auth_option_labels.items()
                        if label == auth_scheme_var.get()
                    ),
                    '',
                )
                if selected_option_id != AUTH_OPTION_CUSTOM:
                    return
                self._entry_row(
                    custom_auth_container,
                    '自定义字段名',
                    'auth_custom_field',
                    form_key,
                    placeholder='Authorization',
                    width=36,
                    prefill=current_custom_field,
                )
                value_mode_row = tk.Frame(custom_auth_container, bg=COLORS['card_bg'])
                value_mode_row.pack(fill=tk.X, pady=4)
                tk.Label(
                    value_mode_row,
                    text='值格式',
                    font=FONTS['body'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    width=16,
                    anchor='e',
                ).pack(side=tk.LEFT, padx=(0, 10))
                auth_value_mode_var = tk.StringVar(
                    value=AUTH_VALUE_MODE_DISPLAY.get(
                        current_custom_mode,
                        AUTH_VALUE_MODE_DISPLAY[AUTH_VALUE_MODE_BEARER],
                    )
                )
                combo = ttk.Combobox(
                    value_mode_row,
                    textvariable=auth_value_mode_var,
                    values=list(AUTH_VALUE_MODE_DISPLAY.values()),
                    style='Modern.TCombobox',
                    width=18,
                    state='readonly',
                )
                combo.pack(side=tk.LEFT)
                bind_combobox_dropdown_mousewheel(combo)
                self._entries[form_key]['auth_custom_value_mode'] = auth_value_mode_var

            auth_scheme_var.trace_add('write', refresh_custom_auth_fields)
            refresh_custom_auth_fields()
        else:
            row = tk.Frame(parent, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=4)
            tk.Label(
                row,
                text='认证方式',
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=16,
                anchor='e',
            ).pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(
                row,
                text=current_auth_label,
                font=FONTS['body_bold'],
                fg=COLORS['primary'],
                bg=COLORS['card_bg'],
            ).pack(side=tk.LEFT)

        self._entry_row(parent, '显示名称', 'model_display_name', form_key, placeholder='可选，仅用于界面展示', width=36)

        user_agent_row = tk.Frame(parent, bg=COLORS['card_bg'])
        user_agent_row.pack(fill=tk.X, pady=4)
        tk.Label(
            user_agent_row,
            text='User-Agent 伪装',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))
        enable_user_agent_spoof = tk.BooleanVar(value=bool(cfg.get('enable_user_agent_spoof', False)))
        self._entries[form_key]['enable_user_agent_spoof'] = enable_user_agent_spoof
        tk.Label(
            user_agent_row,
            text='开启浏览器风格请求头',
            font=FONTS['body'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        ToggleSwitch(
            user_agent_row,
            variable=enable_user_agent_spoof,
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT, padx=(10, 0))

    def _build_json_section(self, parent, form_key):
        def make_json_format_button(title_row):
            ModernButton(
                title_row,
                '格式化',
                style='secondary',
                command=lambda: self._format_json_field(form_key, 'extra_json', '额外请求体 JSON'),
                padx=10,
                pady=4,
            ).pack(side=tk.RIGHT)

        _, inner = self._make_card(parent, '额外请求体 JSON', right_widget_factory=make_json_format_button)
        cfg = self._get_form_config()
        checks_frame = tk.Frame(inner, bg=COLORS['card_bg'])
        checks_frame.pack(fill=tk.X, pady=(0, 8))

        check_defs = [
            ('hide_ai_signature', '隐藏 AI 署名'),
            ('teammates_mode', 'teammates 模式'),
            ('enable_tool_search', '启用 tool search'),
            ('high_intensity_thinking', '高强度思考'),
        ]
        for key, label in check_defs:
            var = tk.BooleanVar(value=bool(cfg.get(key, False)))
            self._entries[form_key][key] = var
            row = tk.Frame(checks_frame, bg=COLORS['card_bg'])
            row.pack(side=tk.LEFT, padx=(0, 18))
            tk.Label(
                row,
                text=label,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(side=tk.LEFT)
            ToggleSwitch(
                row,
                variable=var,
                bg=COLORS['card_bg'],
            ).pack(side=tk.LEFT, padx=(10, 0))

        txt_frame = tk.Frame(inner, bg=COLORS['card_bg'])
        txt_frame.pack(fill=tk.X, pady=(6, 0))
        txt = tk.Text(
            txt_frame,
            height=6,
            font=('Consolas', 10),
            bg=COLORS['surface_alt'],
            fg=COLORS['text_main'],
            insertbackground=COLORS['text_main'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS['card_border'],
            wrap=tk.NONE,
        )
        txt.pack(fill=tk.X)
        saved_json = cfg.get('extra_json', '')
        if saved_json:
            txt.insert('1.0', saved_json)
        self._entries[form_key]['extra_json'] = txt

        def make_header_format_button(title_row):
            ModernButton(
                title_row,
                '格式化',
                style='secondary',
                command=lambda: self._format_json_field(form_key, 'extra_headers', '额外请求头 JSON'),
                padx=10,
                pady=4,
            ).pack(side=tk.RIGHT)

        _, header_inner = self._make_card(parent, '额外请求头 JSON', right_widget_factory=make_header_format_button)
        header_txt_frame = tk.Frame(header_inner, bg=COLORS['card_bg'])
        header_txt_frame.pack(fill=tk.X, pady=(6, 0))
        header_txt = tk.Text(
            header_txt_frame,
            height=5,
            font=('Consolas', 10),
            bg=COLORS['surface_alt'],
            fg=COLORS['text_main'],
            insertbackground=COLORS['text_main'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS['card_border'],
            wrap=tk.NONE,
        )
        header_txt.pack(fill=tk.X)
        saved_headers = cfg.get('extra_headers', '')
        if saved_headers:
            header_txt.insert('1.0', saved_headers)
        self._entries[form_key]['extra_headers'] = header_txt

    def _build_test_section(self, parent, form_key, use_separate):
        self._entries[form_key]['use_separate_test'] = use_separate

        self._entry_row(parent, '测试模型 ID', 'test_model', form_key, placeholder='留空沿用当前模型 ID', width=40)
        self._entry_row(
            parent,
            '提示词',
            'test_prompt',
            form_key,
            placeholder='留空沿用全局模型测试提示',
            width=40,
            prefill=self.config.get_setting('global_test_prompt', 'Who are you?') or '',
        )
        self._entry_row(
            parent,
            '超时（秒）',
            'test_timeout',
            form_key,
            placeholder='留空沿用全局测试超时',
            width=20,
            prefill=str(self.config.get_setting('global_test_timeout_sec', 45) or 45),
        )
        self._entry_row(
            parent,
            '降级阈值（毫秒）',
            'test_degrade_ms',
            form_key,
            placeholder='留空沿用全局测试降级阈值',
            width=20,
            prefill=str(self.config.get_setting('global_test_degrade_ms', 6000) or 6000),
        )
        self._entry_row(
            parent,
            '最大重试次数',
            'test_max_retries',
            form_key,
            placeholder='留空沿用全局测试重试次数',
            width=20,
            prefill=str(self.config.get_setting('global_test_max_retries', 2) or 2),
        )

        def refresh_state(*_args):
            state = 'normal' if use_separate.get() else 'disabled'
            for child in parent.winfo_children():
                try:
                    child.configure(state=state)
                except Exception:
                    pass

        use_separate.trace_add('write', refresh_state)
        refresh_state()

    def _build_params_section(self, parent, form_key, use_separate):
        entries = self._entries.setdefault(form_key, {})
        entries['use_separate_params'] = use_separate

        self._entry_row(parent, '温度', 'temperature', form_key, placeholder='留空沿用全局', width=20)
        self._entry_row(parent, '最大生成长度', 'max_tokens', form_key, placeholder='留空沿用全局', width=20)
        self._entry_row(parent, '请求超时（秒）', 'timeout', form_key, placeholder='留空沿用全局', width=20)
        self._entry_row(parent, '核采样', 'top_p', form_key, placeholder='留空沿用全局', width=20)
        self._entry_row(parent, '存在惩罚', 'presence_penalty', form_key, placeholder='留空沿用全局', width=20)
        self._entry_row(parent, '频率惩罚', 'frequency_penalty', form_key, placeholder='留空沿用全局', width=20)

        def refresh_state(*_args):
            state = 'normal' if use_separate.get() else 'disabled'
            for child in parent.winfo_children():
                try:
                    child.configure(state=state)
                except Exception:
                    pass

        use_separate.trace_add('write', refresh_state)
        refresh_state()

    def _build_billing_section(self, parent, form_key):
        cfg = self._get_form_config()
        use_separate = tk.BooleanVar(value=bool(cfg.get('use_separate_billing', False)))
        self._entries[form_key]['use_separate_billing'] = use_separate

        def make_toggle(title_row):
            self._make_section_switch(title_row, use_separate)

        def build_body(inner):
            self._entry_row(inner, '成本倍率', 'billing_multiplier', form_key, placeholder='1.0（空=沿用全局）', width=30)
            self._billing_mode_row(inner, form_key, width=28)

            def refresh_state(*_args):
                state = 'normal' if use_separate.get() else 'disabled'
                for child in inner.winfo_children():
                    try:
                        child.configure(state=state)
                    except Exception:
                        pass

            use_separate.trace_add('write', refresh_state)
            refresh_state()

        self._build_collapsible_section(parent, '计费配置', build_body, collapsed=True, right_widget_factory=make_toggle, open_var=use_separate)

    def _format_json_field(self, form_key, field_key, field_label):
        txt = self._entries.get(form_key, {}).get(field_key)
        if not txt:
            return
        raw = txt.get('1.0', tk.END).strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            txt.delete('1.0', tk.END)
            txt.insert('1.0', pretty)
        except json.JSONDecodeError as exc:
            messagebox.showerror(f'{field_label}格式错误', str(exc), parent=self.frame)

    def _collect_api_config(self, form_key):
        entries = self._entries.get(form_key, {})
        cfg = merge_with_preset_defaults(self._get_form_config(), self._current_provider_type)

        text_keys = [
            'name', 'remark', 'website', 'key', 'base_url',
            'model_display_name',
            'test_model', 'test_prompt', 'test_timeout', 'test_degrade_ms', 'test_max_retries',
            'temperature', 'max_tokens', 'timeout', 'top_p', 'presence_penalty', 'frequency_penalty',
            'billing_multiplier',
        ]
        for key in text_keys:
            widget = entries.get(key)
            if widget is None:
                continue
            if isinstance(widget, ModernEntry):
                value = widget.get_value()
            else:
                value = widget.get()
            cfg[key] = value

        bool_keys = [
            'hide_ai_signature',
            'teammates_mode',
            'enable_tool_search',
            'high_intensity_thinking',
            'enable_user_agent_spoof',
            'use_separate_params',
            'use_separate_test',
            'use_separate_billing',
        ]
        for key in bool_keys:
            var = entries.get(key)
            if var is not None:
                cfg[key] = bool(var.get())

        str_var_keys = ['api_format', 'billing_mode']
        for key in str_var_keys:
            var = entries.get(key)
            if var is not None:
                cfg[key] = var.get()
        model_widget = entries.get('model')
        if model_widget is not None:
            if isinstance(model_widget, ModernEntry):
                cfg['model'] = model_widget.get_value()
            else:
                cfg['model'] = model_widget.get()
        cfg['api_format'] = normalize_api_format(API_FORMAT_REVERSE.get(str(cfg.get('api_format', '') or '').strip(), cfg.get('api_format', '')))
        cfg['billing_mode'] = BILLING_MODE_REVERSE.get(str(cfg.get('billing_mode', '') or '').strip(), cfg.get('billing_mode', ''))

        txt_widget = entries.get('extra_json')
        if txt_widget is not None:
            cfg['extra_json'] = txt_widget.get('1.0', tk.END).strip()
        header_widget = entries.get('extra_headers')
        if header_widget is not None:
            cfg['extra_headers'] = header_widget.get('1.0', tk.END).strip()

        cfg['name'] = (cfg.get('name', '') or '').strip()
        cfg['model_display_name'] = str(cfg.get('model_display_name', '') or '').strip()
        cfg['provider_type'] = self._current_provider_type
        if self._current_provider_type != 'custom':
            preset = get_preset_definition(self._current_provider_type)
            cfg['api_format'] = preset.get('api_format', cfg.get('api_format', ''))
            cfg['auth_field'] = preset.get('auth_field', cfg.get('auth_field', 'Authorization'))
            cfg['auth_value_mode'] = preset.get('auth_value_mode', cfg.get('auth_value_mode', AUTH_VALUE_MODE_BEARER))
        else:
            auth_scheme_var = entries.get('auth_scheme')
            auth_scheme_label = ''
            if auth_scheme_var is not None:
                auth_scheme_label = str(auth_scheme_var.get() or '').strip()
            auth_scheme_id = next(
                (
                    option_id
                    for option_id in (
                        str(option.get('id', '') or '').strip()
                        for option in get_protocol_auth_options(cfg['api_format'])
                    )
                    if option_id and get_protocol_auth_option_label(cfg['api_format'], option_id) == auth_scheme_label
                ),
                '',
            )
            auth_option = resolve_auth_option_definition(cfg['api_format'], auth_scheme_id)
            if auth_scheme_id == AUTH_OPTION_CUSTOM:
                custom_field_entry = entries.get('auth_custom_field')
                if isinstance(custom_field_entry, ModernEntry):
                    cfg['auth_field'] = custom_field_entry.get_value().strip()
                elif custom_field_entry is not None:
                    cfg['auth_field'] = str(custom_field_entry.get() or '').strip()
                value_mode_var = entries.get('auth_custom_value_mode')
                if value_mode_var is not None:
                    cfg['auth_value_mode'] = AUTH_VALUE_MODE_REVERSE.get(
                        str(value_mode_var.get() or '').strip(),
                        cfg.get('auth_value_mode', AUTH_VALUE_MODE_BEARER),
                    )
            elif auth_option:
                cfg['auth_field'] = auth_option.get('auth_field', cfg.get('auth_field', 'Authorization'))
                cfg['auth_value_mode'] = auth_option.get(
                    'auth_value_mode',
                    cfg.get('auth_value_mode', AUTH_VALUE_MODE_BEARER),
                )
        return cfg

    def _validate(self):
        entries = self._entries.get(FORM_KEY, {})
        required = [
            ('name', '服务商名称'),
            ('key', 'API Key'),
            ('base_url', '请求地址'),
        ]
        missing = []
        for field, label in required:
            widget = entries.get(field)
            if widget is None:
                continue
            value = widget.get_value() if isinstance(widget, ModernEntry) else widget.get()
            if not value.strip():
                missing.append((label, widget))
        return (len(missing) == 0), missing

    def _highlight_error(self, widget, error=True):
        color = COLORS.get('error', '#e53935') if error else COLORS.get('card_border', '#e0e0e0')
        try:
            widget.configure(highlightbackground=color, highlightthickness=1 if error else 0)
        except Exception:
            pass

    def _show_tip(self, text, color, duration_ms=0):
        if hasattr(self, 'tip_label') and self.tip_label.winfo_exists():
            self.tip_label.configure(text=text, fg=color)
            if duration_ms:
                self.frame.after(
                    duration_ms,
                    lambda: self.tip_label.configure(text='') if self.tip_label.winfo_exists() else None,
                )

    def _save_all(self):
        ok, missing = self._validate()
        if not ok:
            labels = '、'.join(label for label, _widget in missing)
            for _label, widget in missing:
                self._highlight_error(widget, True)
                widget.after(3000, lambda w=widget: self._highlight_error(w, False))
            self._show_tip(f'\u26a0 以下必填项未填写：{labels}', COLORS.get('error', '#e53935'), duration_ms=5000)
            return False

        cfg = self._collect_api_config(FORM_KEY)
        save_as_new = self._save_as_new
        if save_as_new:
            exclude_id = None
        else:
            exclude_id = self._current_api_id
        duplicate_id = self.config.find_api_id_by_name(cfg.get('name', ''), exclude_api_id=exclude_id)
        if duplicate_id:
            name_entry = self._entries.get(FORM_KEY, {}).get('name')
            if name_entry is not None:
                self._highlight_error(name_entry, True)
                name_entry.after(3000, lambda w=name_entry: self._highlight_error(w, False))
            messagebox.showerror('保存失败', '服务商名称已存在，请更换名称后再保存。', parent=self.frame)
            self._show_tip('服务商名称已存在，请更换后再保存。', COLORS['error'], duration_ms=5000)
            return False

        if save_as_new:
            target_api_id = self.config.generate_api_id()
        else:
            target_api_id = self._current_api_id or self.config.generate_api_id()
        self.config.set_api_config(target_api_id, cfg)
        self.config.active_api = target_api_id
        if not self.config.save():
            messagebox.showerror('保存失败', '配置保存失败，请稍后重试。', parent=self.frame)
            self._show_tip('配置保存失败，请稍后重试。', COLORS['error'], duration_ms=5000)
            return False

        self._current_api_id = target_api_id
        self._current_provider_type = cfg.get('provider_type', 'custom')
        self._current_config = self.config.get_api_config(target_api_id)
        self._save_as_new = False
        self._show_tip('\u2713 配置已保存', COLORS['success'], duration_ms=3000)
        if self._on_save_callback:
            self._on_save_callback()
        if self._default_force_new and save_as_new:
            self._load_preset_draft(cfg.get('provider_type', 'openai'), reload=True)
        else:
            self._reload_panel()
        return True

    def _fetch_models(self, form_key, combo, label):
        label.configure(text='正在获取模型列表...')
        cfg = self._collect_api_config(form_key)
        api_hint = self._current_api_id or self._current_provider_type

        def _done(models):
            combo['values'] = models
            current = combo.get()
            if not current and models:
                combo.set(models[0])
            label.configure(text=self._format_selected_model_label(combo.get()))

        def _fail(exc):
            label.configure(text=f'获取失败：{exc}')

        self.task_runner.run(
            work=lambda: self.api.fetch_models(api_hint, cfg=cfg),
            on_success=_done,
            on_error=_fail,
        )

    def _delete_current(self):
        if not self._current_api_id:
            return
        cfg = self.config.get_api_config(self._current_api_id)
        name = (cfg.get('name', '') if cfg else '') or self._current_api_id
        if not messagebox.askyesno('删除记录', f'确定要删除「{name}」吗？此操作不可撤销。', parent=self.frame):
            return
        self.config.delete_api_config(self._current_api_id)
        self.config.save()
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}
        self._initialize_current_form()
        self._reload_panel()
        self._show_tip('\u2713 记录已删除', COLORS['success'], duration_ms=3000)
        if self._on_save_callback:
            self._on_save_callback()

    def _reset(self):
        if not messagebox.askyesno('重置配置', '确定要清空所有已保存模型记录并重置当前表单吗？此操作不可撤销。', parent=self.frame):
            return

        self.config.reset()
        for widget in self.frame.winfo_children():
            widget.destroy()

        self.loading = LoadingOverlay(self.frame, self.config, text='正在测试模型连接...')
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._entries = {}
        self._content = None
        self._provider_grid_frame = None
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}
        self._save_as_new = self._default_force_new

        self._initialize_current_form()
        self._build()
        self._show_tip('已清空已保存记录，当前显示新的模板草稿。', COLORS['success'], duration_ms=4000)
