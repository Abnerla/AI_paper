# -*- coding: utf-8 -*-
"""
模型路由配置页面。

提供「统一模型模式」与「按功能模型模式」切换，并支持场景级覆盖。
"""

import tkinter as tk
from tkinter import ttk

from modules.config import resolve_model_display_name
from modules.ui_components import (
    bind_combobox_dropdown_mousewheel,
    COLORS,
    FONTS,
    ModernButton,
    ScrollablePage,
)


ROUTING_FEATURES = (
    ('paper_write', '论文写作'),
    ('polish', '学术润色'),
    ('ai_reduce', '降AI检测'),
    ('plagiarism', '降查重率'),
    ('correction', '智能纠错'),
)

ROUTING_SCENES = (
    ('paper_write.outline', '论文写作 · 生成大纲'),
    ('paper_write.import_outline', '论文写作 · 导入识别'),
    ('paper_write.section', '论文写作 · 撰写章节'),
    ('paper_write.abstract', '论文写作 · 生成摘要'),
    ('polish.run_task', '学术润色 · 统一任务'),
    ('polish.translate', '学术润色 · 翻译润色'),
    ('ai_reduce.transform', '降AI检测 · 文本改写'),
    ('plagiarism.transform', '降查重率 · 文本改写'),
    ('correction.ai_review', '智能纠错 · AI 纠错'),
)

ROUTING_UNBOUND_LABEL = '（沿用默认/兜底）'


class ModelRoutingPanel:
    """嵌入对话框或页面使用的模型路由面板。"""

    def __init__(self, parent, config_mgr, set_status=None, close_panel=None, embed_action_bar=True):
        self.config = config_mgr
        self.set_status = set_status
        self.close_panel = close_panel
        self._embed_action_bar = embed_action_bar

        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self._mode_var = tk.BooleanVar()
        self._feature_vars = {}
        self._scene_vars = {}
        self._fallback_var = tk.StringVar()
        self._tip_label = None
        self._feature_frame = None
        self._fallback_row = None
        self._scene_body_frame = None
        self._scroll_page = None

        self._build()
        self._reload_from_config()

    # -------------------- 对外 API（供外部悬浮按钮栏调用） --------------------
    def save(self):
        self._save()

    def reset_to_global(self):
        self._reset_to_global()

    def attach_tip_label(self, label):
        """外部提供提示标签时，_flash_tip 会通过它反馈保存/重置结果。"""
        self._tip_label = label
        if label is None:
            return
        try:
            saved_apis = self.config.list_saved_apis()
            if not saved_apis:
                hint_text = '当前未保存任何 API，请先在「模型配置」中添加模型后再设置路由。'
            else:
                hint_text = f'已保存 {len(saved_apis)} 个 API；切换到按功能模式可分别绑定。'
            label.configure(text=hint_text, fg=COLORS['text_muted'])
        except Exception:
            pass

    # -------------------- UI --------------------
    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 12))
        tk.Label(
            header,
            text='\U0001F9ED  模型路由',
            font=FONTS['subtitle'],
            fg=COLORS['primary'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w')

        self._scroll_page = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        self._scroll_page.pack(fill=tk.BOTH, expand=True)
        content = self._scroll_page.inner

        self._build_mode_card(content)
        self._build_feature_card(content)
        self._build_fallback_card(content)
        self._build_scene_card(content)
        if self._embed_action_bar:
            self._build_action_bar()

    def _make_card(self, parent, title, description=''):
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

        tk.Label(
            card,
            text=title,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', padx=16, pady=(12, 4))
        if description:
            desc_label = tk.Label(
                card,
                text=description,
                font=FONTS['small'],
                fg=COLORS['text_muted'],
                bg=COLORS['card_bg'],
                wraplength=720,
                justify=tk.LEFT,
                anchor='w',
            )
            desc_label.pack(fill=tk.X, padx=16, pady=(0, 6))
            self._bind_dynamic_wraplength(card, desc_label, padding=32)

        inner = tk.Frame(card, bg=COLORS['card_bg'])
        inner.pack(fill=tk.X, padx=16, pady=(2, 14))
        return inner

    @staticmethod
    def _bind_dynamic_wraplength(container, label, padding=8, minimum=200):
        """让 Label 的 wraplength 跟随父容器宽度变化，避免固定值在窄窗口下提前换行。"""
        state = {'width': 0}

        def _sync(event=None):
            try:
                width = container.winfo_width()
            except tk.TclError:
                return
            target = max(minimum, width - padding)
            if abs(target - state['width']) < 2:
                return
            state['width'] = target
            try:
                label.configure(wraplength=target)
            except tk.TclError:
                pass

        container.bind('<Configure>', _sync, add='+')
        container.after(0, _sync)

    def _build_mode_card(self, parent):
        inner = self._make_card(
            parent,
            '路由模式',
        )
        row = tk.Frame(inner, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=(2, 0))

        tk.Label(
            row,
            text='当前模式（切换→）',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=14,
            anchor='w',
        ).pack(side=tk.LEFT, padx=(0, 10))

        self._mode_switch = tk.Checkbutton(
            row,
            variable=self._mode_var,
            indicatoron=False,
            relief=tk.FLAT,
            bd=0,
            cursor='hand2',
            font=FONTS['small'],
            padx=16,
            pady=6,
            highlightthickness=0,
        )
        self._mode_switch.pack(side=tk.LEFT)

        def refresh_switch(*_args):
            active = bool(self._mode_var.get())
            self._mode_switch.configure(
                text='按功能模型' if active else '统一模型',
                bg=COLORS['accent'] if active else COLORS['surface_alt'],
                fg=COLORS['text_main'] if active else COLORS['text_sub'],
                activebackground=COLORS['accent'] if active else COLORS['surface_alt'],
                activeforeground=COLORS['text_main'] if active else COLORS['text_sub'],
                selectcolor=COLORS['accent'] if active else COLORS['surface_alt'],
            )
            self._refresh_enabled_state()

        def toggle_switch(_event=None):
            self._mode_var.set(not bool(self._mode_var.get()))
            self._mode_switch.focus_set()
            return 'break'

        self._mode_switch.configure(command=refresh_switch)
        self._mode_switch.bind('<Button-1>', toggle_switch)
        self._mode_var.trace_add('write', refresh_switch)
        refresh_switch()

        self._mode_hint = tk.Label(
            row,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
        )
        self._mode_hint.pack(side=tk.LEFT, padx=(14, 0))

    def _build_feature_card(self, parent):
        inner = self._make_card(
            parent,
            '功能级映射',
            '按页面/功能绑定 API。未选择时沿用「兜底 API」或当前激活 API。',
        )
        self._feature_frame = inner
        for feature_id, label in ROUTING_FEATURES:
            row = tk.Frame(inner, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=3)
            tk.Label(
                row,
                text=label,
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=14,
                anchor='w',
            ).pack(side=tk.LEFT, padx=(0, 10))
            var = tk.StringVar()
            self._feature_vars[feature_id] = var
            combo = ttk.Combobox(row, textvariable=var, state='readonly', width=42)
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
            bind_combobox_dropdown_mousewheel(combo)

    def _build_fallback_card(self, parent):
        inner = self._make_card(
            parent,
            '兜底 API',
            '在按功能模式下，未配置的功能/场景会自动使用兜底 API；留空则回退到当前激活 API。',
        )
        row = tk.Frame(inner, bg=COLORS['card_bg'])
        row.pack(fill=tk.X)
        self._fallback_row = row
        tk.Label(
            row,
            text='兜底 API',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=14,
            anchor='w',
        ).pack(side=tk.LEFT, padx=(0, 10))
        combo = ttk.Combobox(row, textvariable=self._fallback_var, state='readonly', width=42)
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        bind_combobox_dropdown_mousewheel(combo)

    def _build_scene_card(self, parent):
        inner = self._make_card(
            parent,
            '场景级覆盖（可选）',
            '优先级高于功能级。例如把「论文写作 · 撰写章节」单独绑定到更强的模型。',
        )
        self._scene_body_frame = inner
        for scene_id, label in ROUTING_SCENES:
            row = tk.Frame(inner, bg=COLORS['card_bg'])
            row.pack(fill=tk.X, pady=3)
            tk.Label(
                row,
                text=label,
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                width=22,
                anchor='w',
            ).pack(side=tk.LEFT, padx=(0, 10))
            var = tk.StringVar()
            self._scene_vars[scene_id] = var
            combo = ttk.Combobox(row, textvariable=var, state='readonly', width=38)
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
            bind_combobox_dropdown_mousewheel(combo)

    def _build_action_bar(self):
        bar = tk.Frame(self.frame, bg=COLORS['bg_main'])
        bar.pack(fill=tk.X, pady=(8, 0))

        self._tip_label = tk.Label(
            bar,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['bg_main'],
            anchor='w',
        )
        self._tip_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 12))

        action_row = tk.Frame(bar, bg=COLORS['bg_main'])
        action_row.pack(side=tk.RIGHT)

        ModernButton(
            action_row,
            '保存',
            style='primary',
            padx=22,
            pady=8,
            command=self._save,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ModernButton(
            action_row,
            '重置',
            style='secondary',
            padx=18,
            pady=8,
            command=self._reset_to_global,
        ).pack(side=tk.RIGHT)

    # -------------------- State --------------------
    def _build_option_labels(self):
        options = [('', ROUTING_UNBOUND_LABEL)]
        for api_id, cfg in self.config.list_saved_apis():
            display = (cfg.get('name', '') or '').strip() or api_id
            model_hint = resolve_model_display_name(cfg)
            if model_hint:
                display = f'{display}（{model_hint}）'
            options.append((api_id, display))
        return options

    @staticmethod
    def _api_id_to_label(api_id, options):
        api_id = str(api_id or '').strip()
        for candidate_id, label in options:
            if candidate_id == api_id:
                return label
        return options[0][1] if options else ''

    @staticmethod
    def _label_to_api_id(label, options):
        for api_id, candidate_label in options:
            if candidate_label == label:
                return api_id
        return ''

    def _reload_from_config(self):
        routing = self.config.get_model_routing_config()
        options = self._build_option_labels()
        labels = [label for _api_id, label in options]

        self._mode_var.set(routing.get('mode', 'global') == 'per_feature')

        for widget in self._feature_frame.winfo_children() if self._feature_frame else []:
            for child in widget.winfo_children():
                if isinstance(child, ttk.Combobox):
                    child['values'] = labels
        feature_map = routing.get('feature_map', {}) or {}
        for feature_id, var in self._feature_vars.items():
            var.set(self._api_id_to_label(feature_map.get(feature_id, ''), options))

        if self._fallback_row:
            for child in self._fallback_row.winfo_children():
                if isinstance(child, ttk.Combobox):
                    child['values'] = labels
        self._fallback_var.set(
            self._api_id_to_label(routing.get('fallback_api', ''), options)
        )

        if self._scene_body_frame:
            for widget in self._scene_body_frame.winfo_children():
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Combobox):
                        child['values'] = labels
        scene_map = routing.get('scene_map', {}) or {}
        for scene_id, var in self._scene_vars.items():
            var.set(self._api_id_to_label(scene_map.get(scene_id, ''), options))

        saved_apis = self.config.list_saved_apis()
        if not saved_apis:
            hint_text = '当前未保存任何 API，请先在「模型配置」中添加模型后再设置路由。'
        else:
            hint_text = f'已保存 {len(saved_apis)} 个 API；切换到按功能模式可分别绑定。'
        if self._tip_label:
            self._tip_label.configure(text=hint_text)

        self._refresh_enabled_state()

    def _refresh_enabled_state(self):
        enabled = bool(self._mode_var.get())
        state = 'readonly' if enabled else 'disabled'
        for host in (self._feature_frame, self._fallback_row, self._scene_body_frame):
            if host is None:
                continue
            self._apply_combobox_state(host, state)
        if hasattr(self, '_mode_hint') and self._mode_hint:
            self._mode_hint.configure(
                text='按功能模式启用后映射生效' if enabled else '统一模式下所有功能共用激活 API'
            )

    def _apply_combobox_state(self, widget, state):
        try:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._apply_combobox_state(child, state)

    # -------------------- Actions --------------------
    def _reset_to_global(self):
        self._mode_var.set(False)
        options = self._build_option_labels()
        unbound = self._api_id_to_label('', options)
        for var in self._feature_vars.values():
            var.set(unbound)
        for var in self._scene_vars.values():
            var.set(unbound)
        self._fallback_var.set(unbound)
        self._flash_tip('已切回统一模式，点击「保存」以生效。', COLORS['text_muted'])

    def _save(self):
        options = self._build_option_labels()
        mode = 'per_feature' if bool(self._mode_var.get()) else 'global'

        feature_map = {}
        for feature_id, var in self._feature_vars.items():
            api_id = self._label_to_api_id(var.get(), options)
            if api_id:
                feature_map[feature_id] = api_id

        scene_map = {}
        for scene_id, var in self._scene_vars.items():
            api_id = self._label_to_api_id(var.get(), options)
            if api_id:
                scene_map[scene_id] = api_id

        fallback_api = self._label_to_api_id(self._fallback_var.get(), options)

        self.config.set_model_routing_config(
            mode,
            feature_map=feature_map,
            scene_map=scene_map,
            fallback_api=fallback_api,
        )
        if not self.config.save():
            self._flash_tip('\u26a0 保存失败，请稍后重试。', COLORS.get('error', '#e53935'))
            if callable(self.set_status):
                self.set_status('模型路由保存失败', COLORS.get('error', '#e53935'))
            return
        self._flash_tip('\u2713 路由配置已保存', COLORS['success'])
        if callable(self.set_status):
            self.set_status('模型路由已保存', COLORS['success'])

    def _flash_tip(self, text, color):
        if not self._tip_label:
            return
        try:
            self._tip_label.configure(text=text, fg=color)
            self._tip_label.after(
                4000,
                lambda: self._tip_label.configure(
                    text='', fg=COLORS['text_muted']
                )
                if self._tip_label and self._tip_label.winfo_exists()
                else None,
            )
        except Exception:
            pass


class ModelRoutingPage:
    """独立的模型路由页面（作为完整 page 注入页面栈）。"""

    def __init__(
        self,
        parent,
        config_mgr,
        api_client,
        history_mgr,
        set_status,
        navigate_page=None,
        app_bridge=None,
    ):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge

        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.panel = ModelRoutingPanel(self.frame, config_mgr, set_status=set_status)
        self.panel.frame.pack(fill=tk.BOTH, expand=True)
