# -*- coding: utf-8 -*-
"""
学术润色页面
"""

import tkinter as tk
from tkinter import messagebox, ttk

from modules.app_metadata import MODULE_POLISH, SOURCE_KIND_LABELS as GLOBAL_SOURCE_KIND_LABELS
from modules.polisher import AcademicPolisher
from modules.report_importer import normalize_block_text
from modules.prompt_center import PromptCenter
from modules.task_runner import TaskRunner
from pages.home_support import ensure_model_configured
from modules.ui_components import (
    apply_adaptive_window_geometry,
    bind_ellipsis_tooltip,
    apply_mixed_fonts,
    COLORS,
    FONTS,
    CardFrame,
    create_home_shell_button,
    LoadingOverlay,
    create_selector_card,
    ModernButton,
    style_selector_card,
    bind_adaptive_wrap,
    bind_responsive_two_pane,
    create_scrolled_text,
    set_ellipsized_label_text,
    THEMES,
)
from modules.workspace_state import WorkspaceStateMixin


class PolishPage(WorkspaceStateMixin):
    PAGE_STATE_ID = 'polish'
    TASK_TYPES = ('论文大纲', '摘要', '引言', '章节正文', '结论', '自定义段落')
    EXECUTION_MODES = ('标准模式', '学术强化', '结构重组', '精炼压缩')
    POLISH_OPTION_CARD_WIDTH = 200
    POLISH_OPTION_CARD_HEIGHT = 76
    POLISH_ACTION_BUTTON_WIDTH = 170
    POLISH_ACTION_BUTTON_HEIGHT = 92
    POLISH_TOOLBAR_ITEM_GAP = 12
    POLISH_OPTIONS = (
        ('vocab', '词汇优化', '提升学术表达和术语精度'),
        ('logic', '逻辑优化', '加强过渡、衔接和论证顺序'),
        ('full', '全面润色', '综合提升整体学术质量'),
    )
    SOURCE_KIND_LABELS = dict(GLOBAL_SOURCE_KIND_LABELS)
    POLISH_LABELS = {key: label for key, label, _ in POLISH_OPTIONS}
    LEGACY_TASK_HINTS = {
        '论文大纲': '请保留原有研究主题，重构为层级清晰、逻辑递进的大纲结构。',
        '摘要': '请控制摘要语气客观凝练，突出研究目的、方法、结果和结论。',
        '引言': '请强化研究背景、问题提出与研究价值，避免空泛表述。',
        '章节正文': '请保留论证主线与数据表述，使内容更符合正式论文章节写法。',
        '结论': '请突出核心发现、理论或实践意义，并保持收束感。',
        '自定义段落': '请严格按本段说明生成，不要偏离指定用途。',
    }
    LEGACY_MODE_HINTS = {
        '标准模式': '整体改动保持适中，不要过度重写。',
        '学术强化': '适度提升术语密度和书面正式度，但不要变得生硬。',
        '结构重组': '重点优化段落顺序、过渡句与论证衔接。',
        '精炼压缩': '删除冗余和重复表达，压缩篇幅但保留核心信息。',
    }
    LEGACY_POLISH_HINTS = {
        'vocab': '重点优化词汇、术语和学术表达精度。',
        'logic': '重点加强因果、转承和段落逻辑。',
        'full': '综合执行语法、表达、逻辑和学术风格提升。',
    }
    LEGACY_FACT_HINT = '请保留原文事实、数据、引用含义和术语准确性，不要杜撰文献或新增结论。'

    def __init__(self, parent, config_mgr, api_client, history_mgr, set_status, navigate_page=None, app_bridge=None):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.prompt_center = PromptCenter(config_mgr)
        self.polisher = AcademicPolisher(api_client, prompt_center=self.prompt_center)
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text='正在执行学术润色...')
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)

        self.task_type_var = tk.StringVar(value='章节正文')
        self.execution_mode_var = tk.StringVar(value='标准模式')
        self.polish_var = tk.StringVar(value='full')
        self.topic_var = tk.StringVar(value='')

        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self.current_paper_title = ''
        self.latest_result_text = ''
        self.latest_result_summary = '暂无生成结果'
        self.latest_target_summary = ''
        self.last_task_config = {}
        self._programmatic_input = False
        self._last_bridge_fingerprint = None
        self._legacy_note_cleanup_pending = False
        self._paper_font_styles = {}
        self._init_workspace_state_support()

        self._build()
        self.restore_saved_workspace_state()
        self._bind_task_state()
        self._bind_workspace_state_watchers()
        self._refresh_task_summary()
        self._update_source_banner()
        self._update_preview_banner()
        self._enable_workspace_state_autosave()
        self._flush_legacy_note_cleanup()

    def _build(self):
        self._build_task_card()

        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left_card = CardFrame(body, title='原文输入')
        self.input_title_frame = left_card.title_frame
        self.input_title_frame.grid_columnconfigure(2, weight=0)
        self.source_label = tk.Label(
            self.input_title_frame,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='right',
            anchor='e',
        )
        self.source_label.grid(row=0, column=1, sticky='e', padx=(12, 8))
        bind_ellipsis_tooltip(self.source_label, padding=4, wraplength=360)
        self._build_input_title_actions()
        self._build_input_card(left_card.inner)

        right_card = CardFrame(body, title='结果预览')
        self.result_title_frame = right_card.title_frame
        self._build_result_title_actions()
        self._build_result_card(right_card.inner)

        bind_responsive_two_pane(body, left_card, right_card, breakpoint=1180, gap=8, left_minsize=360)

    def _bind_workspace_state_watchers(self):
        for widget in (self.input_text, self.note_text):
            widget.bind('<KeyRelease>', self._schedule_workspace_state_save, add='+')
            widget.bind('<<Paste>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')
            widget.bind('<<Cut>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')

        self.task_type_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.execution_mode_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.polish_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.topic_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())

    @staticmethod
    def _get_widget_text(widget):
        if widget is None:
            return ''
        return widget.get('1.0', tk.END).strip()

    @staticmethod
    def _sanitize_info_text(text):
        value = str(text or '').strip()
        normalized = value.replace(' ', '')
        if normalized == 'AI任务执行完成；如需导出，请前往“历史记录”页面。':
            return ''
        return value

    def export_workspace_state(self):
        normalized_note = self._get_normalized_note_text()
        return {
            'task_type': self.task_type_var.get(),
            'execution_mode': self.execution_mode_var.get(),
            'polish_type': self.polish_var.get(),
            'topic': self.topic_var.get().strip(),
            'input_text': self._get_input_text(),
            'note_text': normalized_note,
            'current_source_kind': self.current_source_kind,
            'current_source_desc': self.current_source_desc,
            'current_paper_title': self.current_paper_title,
            'latest_result_text': self.latest_result_text,
            'latest_result_summary': self.latest_result_summary,
            'latest_target_summary': self.latest_target_summary,
            'preview_text': self._get_widget_text(self.output_text),
            'preview_detail': self.preview_detail_label.cget('text'),
            'last_task_config': dict(self.last_task_config),
            'info_text': self._sanitize_info_text(self.info_label.cget('text')),
            'info_color': self.info_label.cget('fg'),
        }

    def restore_workspace_state(self, state):
        if not isinstance(state, dict):
            return

        self.task_type_var.set(state.get('task_type', self.task_type_var.get()))
        self.execution_mode_var.set(state.get('execution_mode', self.execution_mode_var.get()))
        polish_type = str(state.get('polish_type', self.polish_var.get()) or '').strip()
        if polish_type not in self.POLISH_LABELS:
            polish_type = 'full'
        self.polish_var.set(polish_type)
        self.topic_var.set(state.get('topic', self.topic_var.get()))
        original_note = state.get('note_text', '')
        normalized_note = self._normalize_legacy_note_text(original_note)
        if normalized_note != str(original_note or '').strip():
            self._legacy_note_cleanup_pending = True
        self._set_note_text(normalized_note)
        self._set_input_text(
            state.get('input_text', ''),
            state.get('current_source_kind', 'manual'),
            state.get('current_source_desc', ''),
            paper_title=state.get('current_paper_title', ''),
            fingerprint=None,
        )

        self.latest_result_text = state.get('latest_result_text', '')
        self.latest_result_summary = state.get('latest_result_summary', self.latest_result_summary)
        self.latest_target_summary = state.get('latest_target_summary', '')
        preview_text = state.get('preview_text', '')
        self._write_text(self.output_text, preview_text, readonly=True)
        self.output_text.configure(fg=COLORS['text_main'])

        last_task_config = state.get('last_task_config', {})
        self.last_task_config = dict(last_task_config) if isinstance(last_task_config, dict) else {}

        self._set_info_text(
            self._sanitize_info_text(state.get('info_text', self.info_label.cget('text'))),
            fg=state.get('info_color', self.info_label.cget('fg')),
        )

        self._refresh_task_summary()
        self._update_source_banner()
        self._update_preview_banner(detail_override=state.get('preview_detail', self.latest_target_summary))

    def _build_task_card(self):
        task_card = CardFrame(self.frame, title='任务设置')
        task_card.pack(fill=tk.X, pady=(0, 10))
        inner = task_card.inner

        task_tip = tk.Label(
            inner,
            text='有选中文本时，润色任务会优先处理论文写作页最近一次选中的内容；其余情况回退到当前章节正文。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        task_tip.pack(fill=tk.X)
        bind_adaptive_wrap(task_tip, inner, padding=12, min_width=220)

        row1 = tk.Frame(inner, bg=COLORS['card_bg'])
        row1.pack(fill=tk.X, pady=(12, 0))
        self._create_labeled_combo(row1, '任务类型', self.task_type_var, self.TASK_TYPES, width=18).pack(side=tk.LEFT, padx=(0, 12))
        self._create_labeled_combo(row1, '执行模式', self.execution_mode_var, self.EXECUTION_MODES, width=18).pack(side=tk.LEFT, padx=(0, 12))
        self._create_labeled_entry(row1, '主题 / 章节', self.topic_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(inner, text='润色方式', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', pady=(12, 0))

        polish_toolbar = tk.Frame(inner, bg=COLORS['card_bg'])
        polish_toolbar.pack(fill=tk.X, pady=(8, 0))
        polish_toolbar.grid_columnconfigure(0, weight=0)
        polish_toolbar.grid_columnconfigure(1, weight=1)
        polish_toolbar.grid_columnconfigure(2, weight=0)
        self.polish_toolbar = polish_toolbar
        self.polish_option_group = tk.Frame(polish_toolbar, bg=COLORS['card_bg'])
        self.polish_option_group.grid(row=0, column=0, sticky='w')
        self.polish_action_group = tk.Frame(polish_toolbar, bg=COLORS['card_bg'])
        self.polish_action_group.grid(row=0, column=2, sticky='e')
        self.polish_toolbar_items = []
        self.primary_action_hosts = []
        self.polish_option_cards = []
        self.polish_option_badges = []
        self.primary_action_buttons = []

        def add_toolbar_item(parent, widget, gap_after=None):
            if gap_after is None:
                gap_after = self.POLISH_TOOLBAR_ITEM_GAP
            widget.pack(in_=parent, side=tk.LEFT, anchor='n', padx=(0, gap_after))
            self.polish_toolbar_items.append(widget)

        for index, (value, label, desc) in enumerate(self.POLISH_OPTIONS):
            option_card = create_selector_card(
                self.polish_option_group,
                variable=self.polish_var,
                value=value,
                label=label,
                tooltip_text=desc,
                accent_key='primary',
                width=self.POLISH_OPTION_CARD_WIDTH,
                height=self.POLISH_OPTION_CARD_HEIGHT,
            )
            self.polish_option_cards.append(option_card)
            self.polish_option_badges.append(option_card['info_badge'])
            gap_after = 0 if index == len(self.POLISH_OPTIONS) - 1 else self.POLISH_TOOLBAR_ITEM_GAP
            add_toolbar_item(self.polish_option_group, option_card['shell'], gap_after=gap_after)

        tk.Label(inner, text='补充说明 / 指令 / 备注内容', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w', pady=(12, 0))
        note_frame, self.note_text = create_scrolled_text(inner, height=6)
        note_frame.pack(fill=tk.X, pady=(8, 0))

        def add_primary_button(
            text,
            style,
            command,
            *,
            width=None,
            gap_after=None,
            home_shell=False,
            shell_style=None,
            border_color=None,
        ):
            host = tk.Frame(
                self.polish_action_group,
                bg=COLORS['card_bg'],
                width=width or self.POLISH_ACTION_BUTTON_WIDTH,
                height=self.POLISH_ACTION_BUTTON_HEIGHT,
            )
            host.pack_propagate(False)
            if home_shell:
                shell, button = create_home_shell_button(
                    host,
                    text,
                    command=command,
                    style=shell_style or style,
                    border_color=border_color,
                    padx=10,
                    pady=8,
                )
                shell.pack(fill=tk.BOTH, expand=True)
            else:
                button = ModernButton(host, text, style=style, command=command, padx=10, pady=8)
                button.pack(fill=tk.BOTH, expand=True)
            add_toolbar_item(self.polish_action_group, host, gap_after=gap_after)
            self.primary_action_hosts.append(host)
            self.primary_action_buttons.append(button)
            return button

        add_primary_button(
            '执行AI任务',
            style='primary_fixed',
            command=self._run_task,
            gap_after=self.POLISH_TOOLBAR_ITEM_GAP,
            home_shell=True,
            shell_style='primary_fixed',
            border_color=THEMES['light']['card_border'],
        )
        add_primary_button(
            '提示词',
            style='secondary',
            command=self._open_prompt_manager,
            gap_after=0,
            home_shell=True,
            shell_style='secondary',
        )

        self.task_summary_label = tk.Label(inner, text='', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], justify='left', anchor='w')
        self.task_summary_label.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(self.task_summary_label, inner, padding=12, min_width=220)

        self.writeback_hint_label = tk.Label(
            inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.writeback_hint_label._pack_options = {'fill': tk.X, 'pady': (6, 0)}
        self.writeback_hint_label.pack(**self.writeback_hint_label._pack_options)
        bind_adaptive_wrap(self.writeback_hint_label, inner, padding=12, min_width=220)

        self.info_label = tk.Label(
            inner,
            text='语法、格式、引用与敏感表达检查请前往“智能纠错”；结果可在历史记录页面导出。',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.info_label._pack_options = {'fill': tk.X, 'pady': (8, 0)}
        self.info_label.pack(**self.info_label._pack_options)
        bind_adaptive_wrap(self.info_label, inner, padding=12, min_width=220)
        self._set_writeback_hint('')
        self._set_info_text(self.info_label.cget('text'), fg=self.info_label.cget('fg'))
        self._refresh_polish_option_cards()
        self.frame.after_idle(self._refresh_polish_option_cards)

    def _build_input_title_actions(self):
        if not getattr(self, 'input_title_frame', None):
            return

        shell, self.translate_button = create_home_shell_button(
            self.input_title_frame,
            '翻译润色',
            command=self._translate,
            style='secondary',
            font=FONTS['small'],
            padx=12,
            pady=5,
        )
        shell.grid(row=0, column=2, sticky='e')

    def _build_result_title_actions(self):
        if not getattr(self, 'result_title_frame', None):
            return

        shell, self.apply_to_paper_button = create_home_shell_button(
            self.result_title_frame,
            '回填到原文',
            command=self._apply_to_paper_write,
            style='secondary',
            font=FONTS['small'],
            padx=12,
            pady=5,
        )
        shell.grid(row=0, column=1, sticky='e', padx=(12, 0))

    def _build_input_card(self, parent):
        input_frame, self.input_text = create_scrolled_text(parent, height=18)
        input_frame.pack(fill=tk.BOTH, expand=True)
        self.input_text.bind('<KeyRelease>', self._mark_input_manual)

    def _build_result_card(self, parent):
        preview_banner = tk.Frame(parent, bg=COLORS['accent_light'], highlightbackground=COLORS['card_border'], highlightthickness=1)
        preview_banner.pack(fill=tk.X, pady=(0, 8))
        self.preview_status_label = tk.Label(preview_banner, text='', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['accent_light'], justify='left', anchor='w', padx=10, pady=6)
        self.preview_status_label.pack(fill=tk.X)
        self.preview_detail_label = tk.Label(preview_banner, text='', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['accent_light'], justify='left', anchor='w', padx=10, pady=8)
        self.preview_detail_label.pack(fill=tk.X)
        bind_adaptive_wrap(self.preview_detail_label, preview_banner, padding=18, min_width=220)

        output_frame, self.output_text = create_scrolled_text(parent, height=18)
        output_frame.pack(fill=tk.BOTH, expand=True)
        self.output_text.configure(state=tk.DISABLED)

    def _bind_task_state(self):
        self.task_type_var.trace_add('write', lambda *args: self._refresh_task_summary())
        self.execution_mode_var.trace_add('write', lambda *args: self._refresh_task_summary())
        self.polish_var.trace_add('write', lambda *args: self._refresh_task_summary())
        self.polish_var.trace_add('write', lambda *_args: self._refresh_polish_option_cards())
        self.topic_var.trace_add('write', lambda *args: self._refresh_task_summary())

    def _refresh_polish_option_cards(self):
        selected = self.polish_var.get()
        for card in self.polish_option_cards:
            style_selector_card(card, selected=card['value'] == selected)

    def _create_labeled_combo(self, parent, label, variable, values, width=16):
        shell = tk.Frame(parent, bg=COLORS['card_bg'])
        tk.Label(shell, text=label, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w')
        ttk.Combobox(
            shell,
            textvariable=variable,
            values=values,
            state='readonly',
            style='Modern.TCombobox',
            width=width,
        ).pack(fill=tk.X, pady=(6, 0), ipady=2)
        return shell

    def _create_labeled_entry(self, parent, label, variable):
        shell = tk.Frame(parent, bg=COLORS['card_bg'])
        tk.Label(shell, text=label, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w')
        entry = tk.Entry(
            shell,
            textvariable=variable,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
        )
        entry.pack(fill=tk.X, pady=(6, 0), ipady=4)
        return shell

    @staticmethod
    def _set_optional_label_text(label, text, *, fg=None):
        if label is None:
            return
        value = str(text or '').strip()
        if fg is not None:
            label.configure(fg=fg)
        label.configure(text=value)
        pack_options = getattr(label, '_pack_options', {'fill': tk.X})
        if value:
            if not label.winfo_manager():
                label.pack(**pack_options)
        elif label.winfo_manager():
            label.pack_forget()

    def _set_writeback_hint(self, text):
        self._set_optional_label_text(self.writeback_hint_label, text, fg=COLORS['text_sub'])

    def _set_info_text(self, text, *, fg=None):
        self._set_optional_label_text(self.info_label, text, fg=fg)

    def _refresh_task_summary(self):
        polish_label = self.POLISH_LABELS.get(self.polish_var.get(), '全面润色')
        topic = self.topic_var.get().strip() or '未指定主题/章节'
        target_text = '论文大纲（仅生成，不提供写回）' if self.task_type_var.get() == '论文大纲' else '论文写作页当前章节'
        summary = f'当前任务：{self.task_type_var.get()} | {self.execution_mode_var.get()} | {polish_label} | {topic} | 目标：{target_text}'
        if hasattr(self, 'task_summary_label'):
            self.task_summary_label.configure(text=summary)

        if not hasattr(self, 'apply_to_paper_button'):
            return
        writeback_task_type = self._get_writeback_task_type()
        if writeback_task_type == '论文大纲':
            self.apply_to_paper_button.configure(state=tk.DISABLED)
            self._set_writeback_hint('当前预览结果不提供大纲写回；请在“论文写作”页面内自行修改大纲。')
        else:
            self.apply_to_paper_button.configure(state=tk.NORMAL)
            self._set_writeback_hint('')

    def _mark_input_manual(self, event=None):
        if self._programmatic_input:
            return
        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self._last_bridge_fingerprint = None
        self._update_source_banner()
        self._schedule_workspace_state_save()

    def _update_source_banner(self):
        source_name = self.SOURCE_KIND_LABELS.get(self.current_source_kind, '未知来源')
        text = self.current_source_desc or source_name
        if self.current_source_kind == 'manual' and text == '手动输入内容':
            text = ''
        set_ellipsized_label_text(self.source_label, text)

    def _update_preview_banner(self, detail_override=None):
        self.preview_status_label.configure(text=self.latest_result_summary or '暂无生成结果')
        detail = detail_override if detail_override is not None else (
            self.latest_target_summary or '执行任务后会在这里显示结果摘要；如需导出，请前往“历史记录”页面。'
        )
        self.preview_detail_label.configure(text=detail)

    def _write_text(self, widget, text, readonly=False):
        widget.configure(state=tk.NORMAL)
        widget.delete('1.0', tk.END)
        widget.insert('1.0', text)
        if readonly:
            widget.configure(state=tk.DISABLED)

    def _set_input_text(self, text, source_kind, source_desc, topic_hint='', paper_title=None, fingerprint=None):
        normalized_text = normalize_block_text(text)
        self._programmatic_input = True
        try:
            self.input_text.delete('1.0', tk.END)
            if normalized_text:
                self.input_text.insert('1.0', normalized_text)
        finally:
            self._programmatic_input = False

        self.current_source_kind = source_kind
        self.current_source_desc = source_desc
        if paper_title is not None:
            self.current_paper_title = str(paper_title or '').strip()
        self._last_bridge_fingerprint = fingerprint
        self._update_source_banner()
        topic_hint = (topic_hint or '').strip()
        if topic_hint:
            self.topic_var.set(topic_hint)
        self._schedule_workspace_state_save()

    def _get_input_text(self):
        return normalize_block_text(self.input_text.get('1.0', tk.END))

    def _get_note_text(self):
        return self.note_text.get('1.0', tk.END).strip()

    def _get_normalized_note_text(self):
        return self._normalize_legacy_note_text(self._get_note_text())

    def _set_note_text(self, text):
        self.note_text.delete('1.0', tk.END)
        self.note_text.insert('1.0', text)
        self._schedule_workspace_state_save()

    def _collect_task_config(self):
        polish_type = self.polish_var.get()
        return {
            'task_type': self.task_type_var.get(),
            'execution_mode': self.execution_mode_var.get(),
            'polish_type': polish_type,
            'polish_label': self.POLISH_LABELS.get(polish_type, '全面润色'),
            'topic': self.topic_var.get().strip(),
            'notes': self._get_normalized_note_text(),
            'source_kind': self.SOURCE_KIND_LABELS.get(self.current_source_kind, self.current_source_kind),
        }

    def _get_writeback_task_type(self):
        if self.latest_result_text.strip() and isinstance(self.last_task_config, dict):
            task_type = str(self.last_task_config.get('task_type', '') or '').strip()
            if task_type:
                return task_type
        return self.task_type_var.get()

    @classmethod
    def _normalize_legacy_note_text(cls, text):
        normalized = str(text or '').strip()
        if cls._is_legacy_local_template(normalized):
            return ''
        return normalized

    @classmethod
    def _is_legacy_local_template(cls, text):
        if not text:
            return False
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        if len(lines) not in (4, 5):
            return False
        if lines[0] not in cls.LEGACY_TASK_HINTS.values():
            return False
        if lines[1] not in cls.LEGACY_MODE_HINTS.values():
            return False
        if lines[2] not in cls.LEGACY_POLISH_HINTS.values():
            return False
        if lines[3] != cls.LEGACY_FACT_HINT:
            return False
        if len(lines) == 5 and not cls._is_legacy_topic_hint(lines[4]):
            return False
        return True

    @staticmethod
    def _is_legacy_topic_hint(line):
        line = str(line or '').strip()
        return line.startswith('请确保结果与“') and line.endswith('”主题保持一致。')

    def _flush_legacy_note_cleanup(self, save_to_disk=True):
        if not self._legacy_note_cleanup_pending:
            return True
        self._legacy_note_cleanup_pending = False
        return self.save_workspace_state_now(save_to_disk=save_to_disk)

    def _make_result_summary(self, config, source_text, result_text):
        return f'{config["task_type"]} | {config["execution_mode"]} | {config["polish_label"]} | {len(source_text)}字 → {len(result_text)}字'

    def _set_result(self, text, summary, detail, error=False, store_result=True):
        self.latest_result_text = text if (store_result and not error) else ''
        self.latest_result_summary = summary
        self._write_text(self.output_text, text, readonly=True)
        self._apply_paper_fonts_to_widgets()
        self._update_preview_banner(detail_override=detail)
        preview_fg = COLORS['error'] if error else COLORS['text_main']
        self.output_text.configure(fg=preview_fg)
        self._refresh_task_summary()
        self._schedule_workspace_state_save()

    def _add_history_version(self, operation, input_text, output_text, extra=None):
        payload = dict(extra or {})
        if not str(payload.get('paper_title', '') or '').strip() and self.current_paper_title:
            payload['paper_title'] = self.current_paper_title
        self.history.add(
            operation,
            input_text,
            output_text,
            MODULE_POLISH,
            extra=payload,
            page_state_id=self.PAGE_STATE_ID,
            workspace_state=self.capture_workspace_state_snapshot(save_to_disk=False),
        )

    def _run_task(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入待处理文本', parent=self.frame)
            return
        if not self._ensure_prompt_ready('polish.run_task'):
            return

        knowledge_context = self._choose_knowledge_context('polish.run_task', '学术润色')
        if knowledge_context is None:
            return

        config = self._collect_task_config()
        self.last_task_config = dict(config)
        self.latest_target_summary = ''
        self._set_result('处理中，请稍候...', '正在执行 AI 任务', '任务执行中，请稍候查看结果。', store_result=False)

        def on_success(result):
            summary = self._make_result_summary(config, text, result)
            if config['task_type'] == '论文大纲':
                detail = '结果已生成。当前为论文大纲任务，本页不提供写回大纲；如需导出，请前往“历史记录”页面。'
            else:
                detail = '结果已生成，可回填到原文；如需导出，请前往“历史记录”页面。'
            self._set_result(result, summary, detail)
            self._set_info_text('', fg=COLORS['text_sub'])
            self._add_history_version(
                f'{config["task_type"]}·{config["polish_label"]}',
                text,
                result,
                extra={
                    'task_type': config['task_type'],
                    'polish_type': config['polish_label'],
                    'execution_mode': config['execution_mode'],
                    'topic': config['topic'],
                    'source_kind': config['source_kind'],
                },
            )
            self.set_status('学术润色完成')

        def on_error(exc):
            self._set_result(f'错误：{exc}', '任务执行失败', '请检查模型配置、网络连接或提示词后重试。', error=True)
            self._set_info_text('任务执行失败，请查看结果区错误信息。', fg=COLORS['error'])
            self.set_status('学术润色失败', COLORS['error'])

        self.task_runner.run(
            work=lambda: self.polisher.run_task(
                text,
                task_type=config['task_type'],
                polish_type=config['polish_type'],
                execution_mode=config['execution_mode'],
                topic=config['topic'],
                notes=config['notes'],
                knowledge_context=knowledge_context,
            ),
            on_success=on_success,
            on_error=on_error,
            loading_text='正在执行学术润色...',
            status_text='学术润色执行中...',
            status_color=COLORS['warning'],
        )

    def _choose_knowledge_context(self, scene_id, action_label=''):
        if not self.app_bridge or not hasattr(self.app_bridge, 'choose_knowledge_context'):
            return {}
        try:
            return self.app_bridge.choose_knowledge_context(
                scene_id, page_id=self.PAGE_STATE_ID, action_label=action_label,
            )
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return None

    def _open_prompt_manager(self):
        if not self.app_bridge:
            return
        self.app_bridge.show_prompt_manager(page_id='polish', compact=True, scene_id='polish.run_task')

    def _ensure_prompt_ready(self, scene_id='polish.run_task'):
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return False
        if self.prompt_center.scene_has_active_prompt(scene_id):
            return True
        messagebox.showwarning('提示', '当前页面没有可用的提示词，请先创建或选择一条提示词。', parent=self.frame)
        self.app_bridge.show_prompt_manager(page_id='polish', compact=True, scene_id=scene_id)
        return False

    def _update_paper_font_styles(self, styles):
        if isinstance(styles, dict) and styles:
            self._paper_font_styles = styles
            self._apply_paper_fonts_to_widgets()

    def _apply_paper_fonts_to_widgets(self):
        body = self._paper_font_styles.get('body', {})
        if not body:
            return
        cn = body.get('font', '宋体')
        en = body.get('font_en', 'Times New Roman')
        pt = int(body.get('size_pt', 12))
        for widget in [self.input_text, self.output_text]:
            try:
                apply_mixed_fonts(widget, cn, en, pt)
            except Exception:
                pass

    def _pull_paper_write_context(self):
        if not self.app_bridge:
            return {}
        return self.app_bridge.pull_paper_write_context()

    def _pull_paper_write_selection_snapshot(self):
        if not self.app_bridge:
            return None
        return self.app_bridge.pull_paper_write_selection_snapshot()

    def receive_paper_write_content(self, payload):
        if not isinstance(payload, dict):
            return {'ok': False, 'message': '发送内容格式不正确'}

        text = normalize_block_text(payload.get('text', ''))
        if not text.strip():
            return {'ok': False, 'message': '当前章节没有可发送的正文内容'}

        section_name = (payload.get('section') or '').strip()
        section_label = f' / {section_name}' if section_name else ''
        fingerprint = (
            'paper_write_send',
            payload.get('context_revision'),
            payload.get('section', ''),
            payload.get('paper_title', ''),
            text,
            payload.get('target_page_id', ''),
        )
        self._set_input_text(
            text,
            payload.get('source_kind', 'paper_section'),
            payload.get('source_desc', f'来自论文写作页面主动发送{section_label}'),
            topic_hint=section_name,
            paper_title=payload.get('paper_title', ''),
            fingerprint=fingerprint,
        )
        if section_name:
            self.task_type_var.set('章节正文')
        self._update_paper_font_styles(payload.get('level_font_styles'))
        return {
            'ok': True,
            'message': '内容已发送到学术润色页',
            'section': section_name,
            'page_id': self.PAGE_STATE_ID,
        }

    def _resolve_target_summary(self, context, section_hint):
        section_name = section_hint or context.get('current_section', '').strip()
        if section_name:
            return f'论文写作页 / 当前章节（{section_name}）'
        return '论文写作页 / 当前正文区'

    def _ensure_result_for_apply(self):
        result = normalize_block_text(self.latest_result_text)
        if not result.strip():
            messagebox.showwarning('提示', '请先执行任务，生成可回填的结果', parent=self.frame)
            return ''
        return result

    def _apply_to_paper_write(self):
        result = self._ensure_result_for_apply()
        if not result:
            return

        config = self.last_task_config or self._collect_task_config()
        if config.get('task_type') == '论文大纲':
            messagebox.showwarning('提示', '当前预览结果为论文大纲，本页不提供大纲写回，请在“论文写作”页面内自行修改。', parent=self.frame)
            return

        context = self._pull_paper_write_context()
        section_hint = config['topic'].strip() or context.get('current_section', '').strip()
        target_summary = self._resolve_target_summary(context, section_hint)

        if not section_hint and not context.get('current_content', '').strip():
            messagebox.showwarning('提示', '论文写作页当前没有可用章节上下文，无法安全写回。', parent=self.frame)
            return

        confirm_text = (
            '将使用当前润色结果覆盖以下正文：\n\n'
            f'{target_summary}\n\n'
            '确定继续吗？'
        )
        if not messagebox.askyesno('回填到原文', confirm_text, parent=self.frame):
            return

        if not self.app_bridge:
            messagebox.showwarning('提示', '当前版本未连接论文写作页桥接动作。', parent=self.frame)
            return

        outcome = self.app_bridge.apply_result_to_paper_write(
            result,
            target_mode='body',
            write_mode='replace',
            section_hint=section_hint,
            task_type=config['task_type'],
        )
        if not outcome or not outcome.get('ok'):
            messagebox.showwarning('写回失败', (outcome or {}).get('message', '无法写回到论文写作页'), parent=self.frame)
            return

        self.latest_target_summary = self._resolve_target_summary(context, outcome.get('section', section_hint))
        self._update_preview_banner()
        self._set_info_text(f'已回填到原文：{self.latest_target_summary}', fg=COLORS['success'])
        self.set_status(outcome.get('message', '已写回论文写作页'))

    def _translate(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入文本', parent=self.frame)
            return
        if not self._ensure_prompt_ready('polish.translate'):
            return

        win = tk.Toplevel(self.frame)
        win.title('翻译润色')
        win.configure(bg=COLORS['bg_main'])
        win.resizable(False, False)
        apply_adaptive_window_geometry(win, '1600x1200')

        tk.Label(win, text='目标语言：', font=FONTS['body'], bg=COLORS['bg_main']).pack(pady=(20, 5))
        lang_var = tk.StringVar(value='英文')
        ttk.Combobox(win, textvariable=lang_var, values=['英文', '中文', '日文', '法文', '德文'], state='readonly', width=15, style='Modern.TCombobox').pack()

        def do_translate():
            target_lang = lang_var.get()
            win.destroy()

            knowledge_context = self._choose_knowledge_context('polish.translate', '翻译润色')
            if knowledge_context is None:
                return

            def on_success(result):
                self.last_task_config = dict(self._collect_task_config())
                summary = f'翻译润色完成 | 目标语言：{target_lang}'
                if self._get_writeback_task_type() == '论文大纲':
                    detail = '翻译结果已进入预览区。当前为论文大纲任务，本页不提供写回大纲；如需导出，请前往”历史记录”页面。'
                else:
                    detail = '翻译结果已进入预览区，可回填到原文；如需导出，请前往”历史记录”页面。'
                self._set_result(result, summary, detail)
                self._set_info_text('翻译润色完成；如需导出，请前往”历史记录”页面。', fg=COLORS['text_sub'])
                self._add_history_version(
                    f'翻译润色({target_lang})',
                    text,
                    result,
                    extra={
                        'tool_name': '翻译润色',
                        'target_lang': target_lang,
                        'source_kind': self.SOURCE_KIND_LABELS.get(self.current_source_kind, self.current_source_kind),
                    },
                )
                self.set_status('翻译完成')

            def on_error(exc):
                self._set_result(f'错误：{exc}', '翻译润色失败', '请检查模型配置或稍后重试。', error=True)
                self._set_info_text('翻译润色失败。', fg=COLORS['error'])
                self.set_status(f'翻译失败: {exc}', COLORS['error'])

            self.task_runner.run(
                work=lambda: self.polisher.translate_polish(text, target_lang, knowledge_context=knowledge_context),
                on_success=on_success,
                on_error=on_error,
                loading_text='正在执行翻译润色...',
                status_text='翻译中...',
                status_color=COLORS['warning'],
            )

        ModernButton(win, '确定翻译', style='primary', command=do_translate).pack(pady=10)

    def apply_workspace_state_snapshot(self, state, save_to_disk=True):
        ok = super().apply_workspace_state_snapshot(state, save_to_disk=False)
        if not ok:
            return False
        if self._legacy_note_cleanup_pending:
            return self._flush_legacy_note_cleanup(save_to_disk=save_to_disk)
        if save_to_disk and getattr(self, 'config', None):
            return bool(self.config.save())
        return True

    def on_show(self):
        if self._workspace_state_restored and self._get_input_text():
            return

        snapshot = self._pull_paper_write_selection_snapshot()
        snapshot_text = normalize_block_text((snapshot or {}).get('text', ''))
        if snapshot and snapshot_text.strip():
            fingerprint = (
                'selection',
                snapshot.get('context_revision'),
                snapshot.get('section', ''),
                snapshot.get('paper_title', ''),
                snapshot_text,
            )
            if fingerprint != self._last_bridge_fingerprint:
                section_name = snapshot.get('section', '').strip()
                desc = f'来自论文写作页选区{f" / {section_name}" if section_name else ""}'
                self._set_input_text(
                    snapshot_text,
                    'paper_selection',
                    desc,
                    topic_hint=section_name,
                    paper_title=snapshot.get('paper_title', ''),
                    fingerprint=fingerprint,
                )
                self._update_paper_font_styles(snapshot.get('level_font_styles'))
                return

        context = self._pull_paper_write_context()
        current_content = normalize_block_text(context.get('current_content', ''))
        current_section = context.get('current_section', '').strip()
        if not current_content.strip():
            return

        fingerprint = (
            'section',
            context.get('context_revision'),
            current_section,
            context.get('paper_title', ''),
            current_content,
        )
        if fingerprint == self._last_bridge_fingerprint:
            return

        existing_input = self._get_input_text()
        if existing_input and self.current_source_kind in {'manual', 'import'}:
            return

        desc = f'来自论文写作页当前章节{f" / {current_section}" if current_section else ""}'
        self._set_input_text(
            current_content,
            'paper_section',
            desc,
            topic_hint=current_section,
            paper_title=context.get('paper_title', ''),
            fingerprint=fingerprint,
        )
        self._update_paper_font_styles(context.get('level_font_styles'))
