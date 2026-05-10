# -*- coding: utf-8 -*-
"""
智能纠错页面
"""

import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from modules.ai_reducer import AIReducer
from modules.app_metadata import MODULE_CORRECTION, SOURCE_KIND_LABELS as GLOBAL_SOURCE_KIND_LABELS
from modules.aux_tools import AuxTools
from modules.intelligent_corrector import CATEGORY_LABELS, CATEGORY_ORDER, SEVERITY_LABELS, CorrectionRun, IntelligentCorrector
from modules.report_importer import normalize_block_text
from modules.plagiarism import PlagiarismReducer
from modules.prompt_center import PromptCenter
from modules.task_runner import TaskRunner
from pages.home_support import ensure_model_configured
from modules.ui_components import (
    bind_ellipsis_tooltip,
    apply_mixed_fonts,
    COLORS,
    FONTS,
    CardFrame,
    create_home_shell_button,
    LoadingOverlay,
    ModernButton,
    ResponsiveButtonBar,
    bind_adaptive_wrap,
    bind_responsive_two_pane,
    create_scrolled_text,
    set_ellipsized_label_text,
    THEMES,
)
from modules.workspace_state import WorkspaceStateMixin


class CorrectionPage(WorkspaceStateMixin):
    PAGE_STATE_ID = 'correction'
    SOURCE_KIND_LABELS = dict(GLOBAL_SOURCE_KIND_LABELS)
    CITATION_OPTIONS = ('auto', 'GB/T 7714', 'APA', 'MLA')
    ISSUE_ACTION_BUTTON_MIN_WIDTH = 128
    ISSUE_ACTION_BUTTON_EXTRA_WIDTH = 8
    ISSUE_ACTION_BUTTON_HEIGHT = 52
    ISSUE_STATUS_LABELS = {
        'pending': '待处理',
        'applied': '已应用',
        'ignored': '已忽略',
        'stale': '待复核',
    }
    CATEGORY_COLORS = {
        'basic_text': '#FFF4C1',
        'grammar_sentence': '#DCEBFF',
        'academic_format': '#F7D9DD',
        'citation_reference': '#DDF5E4',
        'data_expression': '#E6E1FF',
        'logic_rigor': '#FFDAB5',
        'compliance_risk': '#F8C9D1',
        'ai_style': '#EEE7D7',
    }

    def __init__(self, parent, config_mgr, api_client, history_mgr, set_status, navigate_page=None, app_bridge=None):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.prompt_center = PromptCenter(config_mgr)
        self.aux = AuxTools(api_client)
        self.ai_reducer = AIReducer(api_client)
        self.plagiarism_reducer = PlagiarismReducer(api_client)
        self.corrector = IntelligentCorrector(api_client)
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text='正在执行智能纠错...')
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)

        self.citation_style_var = tk.StringVar(value='auto')
        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self.current_paper_title = ''
        self.current_docx_path = ''
        self.current_run = None
        self.current_run_mode = ''
        self.current_issue_map = {}
        self.current_tree_map = {}
        self.latest_auto_fixed_count = 0
        self._programmatic_input = False
        self._last_bridge_fingerprint = None
        self._tooltip_window = None
        self._paper_font_styles = {}
        self._init_workspace_state_support()

        self._build()
        self.restore_saved_workspace_state()
        self._bind_workspace_state_watchers()
        self._update_source_banner()
        self._update_capability_label()
        self._refresh_stats()
        self._enable_workspace_state_autosave()

    def _build(self):
        self._build_task_card()

        self.stats_card = CardFrame(self.frame, title='错误分类统计')
        self.stats_card.pack(fill=tk.X, pady=(0, 10))
        self._build_stats_card(self.stats_card.inner)

        main_body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        main_body.pack(fill=tk.BOTH, expand=True)
        self.main_body = main_body

        left_card = CardFrame(main_body, title='原文 / 导入文稿')
        self.source_label = tk.Label(
            left_card.title_frame,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='right',
            anchor='e',
        )
        self.source_label.grid(row=0, column=1, sticky='e', padx=(12, 0))
        bind_ellipsis_tooltip(self.source_label, padding=4, wraplength=360)
        self._build_input_card(left_card.inner)

        right_card = CardFrame(main_body, title='修正预览')
        self.preview_title_frame = right_card.title_frame
        self._build_preview_title_actions()
        self._build_preview_card(right_card.inner)

        bind_responsive_two_pane(main_body, left_card, right_card, breakpoint=1180, gap=8, left_minsize=360)

        review_body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        review_body.pack(fill=tk.BOTH, expand=True)

        issue_card = CardFrame(review_body, title='问题列表')
        self._build_issue_card(issue_card.inner)

        detail_card = CardFrame(review_body, title='问题详情')
        self.detail_title_frame = detail_card.title_frame
        self._build_detail_title_actions()
        self._build_detail_card(detail_card.inner)

        bind_responsive_two_pane(review_body, issue_card, detail_card, breakpoint=1320, gap=8, left_minsize=520)

    def _bind_workspace_state_watchers(self):
        self.input_text.bind('<KeyRelease>', self._schedule_workspace_state_save, add='+')
        self.input_text.bind('<<Paste>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')
        self.input_text.bind('<<Cut>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')
        self.citation_style_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())

    def _selected_issue_id(self):
        issue = self._selected_issue()
        if not issue:
            return ''
        return issue.get('id', '')

    def export_workspace_state(self):
        current_run = None
        if self.current_run:
            current_run = {
                'input_text': self.current_run.input_text,
                'corrected_text': self.current_run.corrected_text,
                'issues': list(self.current_run.issues),
                'counts': dict(self.current_run.counts),
                'source_kind': self.current_run.source_kind,
                'citation_style_detected': self.current_run.citation_style_detected,
                'citation_style_effective': self.current_run.citation_style_effective,
                'report_text': self.current_run.report_text,
            }

        return {
            'citation_style': self.citation_style_var.get(),
            'input_text': self._get_input_text(),
            'current_source_kind': self.current_source_kind,
            'current_source_desc': self.current_source_desc,
            'current_paper_title': self.current_paper_title,
            'current_docx_path': self.current_docx_path,
            'current_run': current_run,
            'current_run_mode': self.current_run_mode,
            'latest_auto_fixed_count': self.latest_auto_fixed_count,
            'selected_issue_id': self._selected_issue_id(),
            'info_text': self.info_label.cget('text'),
            'info_color': self.info_label.cget('fg'),
        }

    def restore_workspace_state(self, state):
        if not isinstance(state, dict):
            return

        self.citation_style_var.set(state.get('citation_style', self.citation_style_var.get()))
        self._set_input_text(
            state.get('input_text', ''),
            state.get('current_source_kind', 'manual'),
            state.get('current_source_desc', ''),
            paper_title=state.get('current_paper_title', ''),
            docx_path=state.get('current_docx_path', ''),
            fingerprint=None,
        )

        run_payload = state.get('current_run')
        self.current_run = None
        self.current_run_mode = ''
        if isinstance(run_payload, dict):
            self.current_run = CorrectionRun(
                input_text=run_payload.get('input_text', ''),
                corrected_text=run_payload.get('corrected_text', ''),
                issues=list(run_payload.get('issues', [])),
                counts=dict(run_payload.get('counts', {})),
                source_kind=run_payload.get('source_kind', 'manual'),
                citation_style_detected=run_payload.get('citation_style_detected', 'GB/T 7714'),
                citation_style_effective=run_payload.get('citation_style_effective', 'GB/T 7714'),
                report_text=run_payload.get('report_text', ''),
            )
            self.current_run_mode = state.get('current_run_mode') or 'correction'

        try:
            self.latest_auto_fixed_count = int(state.get('latest_auto_fixed_count', 0) or 0)
        except Exception:
            self.latest_auto_fixed_count = 0

        self._set_info_text(
            state.get('info_text', self.info_label.cget('text')),
            fg=state.get('info_color', self.info_label.cget('fg')),
        )

        if self.current_run:
            self._update_run_views()
            selected_issue_id = state.get('selected_issue_id', '')
            if selected_issue_id:
                self._focus_issue(selected_issue_id)

    def _build_task_card(self):
        card = CardFrame(self.frame, title='纠错设置')
        card.pack(fill=tk.X, pady=(0, 10))
        self.task_card = card
        inner = card.inner

        top_layout = tk.Frame(inner, bg=COLORS['card_bg'])
        top_layout.pack(fill=tk.X, pady=(10, 0))
        self.task_top_layout = top_layout

        panel_kwargs = {
            'bg': COLORS['card_bg'],
            'bd': 0,
            'highlightbackground': COLORS['card_border'],
            'highlightthickness': 2,
            'padx': 14,
            'pady': 14,
        }
        left_panel = tk.Frame(top_layout, **panel_kwargs)
        right_panel = tk.Frame(top_layout, **panel_kwargs)
        self.task_settings_panel = left_panel
        self.task_review_panel = right_panel
        bind_responsive_two_pane(
            top_layout,
            left_panel,
            right_panel,
            breakpoint=1040,
            gap=12,
            left_minsize=420,
            left_weight=1,
            right_weight=1,
            uniform_group='correction_task_columns',
        )

        control_row = tk.Frame(left_panel, bg=COLORS['card_bg'])
        control_row.pack(fill=tk.X)
        self.task_control_row = control_row

        style_shell = tk.Frame(control_row, bg=COLORS['card_bg'])
        style_shell.pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(style_shell, text='引用规范', font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(anchor='w')
        ttk.Combobox(
            style_shell,
            textvariable=self.citation_style_var,
            values=self.CITATION_OPTIONS,
            state='readonly',
            width=16,
            style='Modern.TCombobox',
        ).pack(pady=(6, 0), ipady=2)

        start_shell, self.start_correction_button = create_home_shell_button(
            control_row,
            '开始智能纠错',
            command=self._run_correction,
            style='primary_fixed',
            border_color=THEMES['light']['card_border'],
            padx=12,
            pady=8,
        )
        start_shell.pack(side=tk.RIGHT, anchor='se')

        action_bar = ResponsiveButtonBar(left_panel, min_item_width=160, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        action_bar.pack(fill=tk.X, pady=(12, 0))
        self.primary_action_bar = action_bar
        action_bar.add(create_home_shell_button(action_bar, '提示词', command=self._open_prompt_manager, style='secondary', padx=12, pady=8)[0])
        action_bar.add(create_home_shell_button(action_bar, '导入文稿', command=self._import_document, style='secondary', padx=12, pady=8)[0])
        action_bar.add(create_home_shell_button(action_bar, '清空工作区', command=self._clear_workspace, style='secondary', padx=12, pady=8)[0])

        quick_review_label = tk.Label(
            right_panel,
            text='专项核验',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        quick_review_label.pack(fill=tk.X)

        quick_review_bar = ResponsiveButtonBar(right_panel, min_item_width=150, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        quick_review_bar.pack(fill=tk.X, pady=(8, 0))
        self.quick_review_bar = quick_review_bar
        quick_review_bar.add(create_home_shell_button(quick_review_bar, 'AI风格扫描', command=self._run_ai_style_scan, style='secondary', padx=12, pady=8)[0])
        quick_review_bar.add(create_home_shell_button(quick_review_bar, '逻辑流畅度检测', command=self._run_logic_flow_check, style='secondary', padx=12, pady=8)[0])
        quick_review_bar.add(create_home_shell_button(quick_review_bar, '引用规范检查', command=self._run_citation_format_check, style='secondary', padx=12, pady=8)[0])
        quick_review_bar.add(create_home_shell_button(quick_review_bar, '敏感表达检查', command=self._run_sensitive_expression_check, style='secondary', padx=12, pady=8)[0])

        self.capability_label = tk.Label(
            inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.capability_label._pack_options = {'fill': tk.X, 'pady': (10, 0)}
        self.capability_label.pack(**self.capability_label._pack_options)
        bind_adaptive_wrap(self.capability_label, inner, padding=12, min_width=220)

        self.info_label = tk.Label(
            inner,
            text='开始智能纠错会统一检查语法、格式、引用与敏感表达等问题；右侧会生成修正预览，并在下方列出问题与建议。',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.info_label._pack_options = {'fill': tk.X, 'pady': (8, 0)}
        self.info_label.pack(**self.info_label._pack_options)
        bind_adaptive_wrap(self.info_label, inner, padding=12, min_width=220)

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

    @staticmethod
    def _sanitize_info_text(text):
        value = str(text or '').strip()
        if value == '工作区已清空。':
            return ''
        return value

    def _set_capability_text(self, text):
        self._set_optional_label_text(self.capability_label, text, fg=COLORS['text_sub'])

    def _set_info_text(self, text, *, fg=None):
        self._set_optional_label_text(self.info_label, self._sanitize_info_text(text), fg=fg)

    def _build_input_card(self, parent):
        input_frame, self.input_text = create_scrolled_text(parent, height=18)
        input_frame.pack(fill=tk.BOTH, expand=True)
        self.input_text.bind('<KeyRelease>', self._mark_input_manual, add='+')

    def _build_preview_card(self, parent):
        preview_note = tk.Label(
            parent,
            text='预览区会高亮待处理问题；悬停可查看原因，点击问题列表可定位对应片段。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        preview_note.pack(fill=tk.X)
        bind_adaptive_wrap(preview_note, parent, padding=12, min_width=220)

        output_frame, self.output_text = create_scrolled_text(parent, height=18)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.output_text.configure(state=tk.DISABLED, cursor='arrow')

    def _build_preview_title_actions(self):
        if not getattr(self, 'preview_title_frame', None):
            return

        action_row = tk.Frame(self.preview_title_frame, bg=COLORS['card_bg'])
        action_row.grid(row=0, column=1, sticky='e')

        export_shell, self.export_corrected_button = create_home_shell_button(
            action_row,
            '导出修正文稿',
            command=self._export_corrected,
            style='secondary',
            font=FONTS['small'],
            padx=12,
            pady=5,
        )
        export_shell.pack(side=tk.LEFT)

        shell, self.apply_to_paper_button = create_home_shell_button(
            action_row,
            '回填到原文',
            command=lambda: self._apply_to_paper('body'),
            style='secondary',
            font=FONTS['small'],
            padx=12,
            pady=5,
        )
        shell.pack(side=tk.LEFT, padx=(8, 0))

    def _build_detail_title_actions(self):
        if not getattr(self, 'detail_title_frame', None):
            return

        shell, self.export_report_button = create_home_shell_button(
            self.detail_title_frame,
            '导出纠错报告',
            command=self._export_report,
            style='secondary',
            font=FONTS['small'],
            padx=12,
            pady=5,
        )
        shell.grid(row=0, column=1, sticky='e', padx=(12, 0))

    def _build_stats_card(self, parent):
        self.stat_cards = {}
        grid = tk.Frame(parent, bg=COLORS['card_bg'])
        grid.pack(fill=tk.X)
        for index, category in enumerate(CATEGORY_ORDER):
            col = index
            grid.grid_columnconfigure(col, weight=1)
            box = tk.Frame(grid, bg=COLORS['surface_alt'], highlightbackground=COLORS['card_border'], highlightthickness=1)
            box.grid(row=0, column=col, sticky='nsew', padx=(0, 8 if col < len(CATEGORY_ORDER) - 1 else 0))
            tk.Label(box, text=CATEGORY_LABELS[category], font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['surface_alt']).pack(anchor='w', padx=10, pady=(10, 4))
            value = tk.Label(box, text='0', font=(FONTS['hero'][0], 20, 'bold'), fg=COLORS['text_main'], bg=COLORS['surface_alt'])
            value.pack(anchor='w', padx=10, pady=(0, 10))
            self.stat_cards[category] = value

    def _build_issue_card(self, parent):
        action_bar = tk.Frame(parent, bg=COLORS['card_bg'])
        action_bar.pack(fill=tk.X, pady=(0, 10))
        self.issue_action_bar = action_bar
        self.issue_action_hosts = []
        self.issue_action_buttons = []
        self.issue_action_gap_columns = (1, 3)
        self.issue_action_button_columns = (0, 2, 4)
        self.issue_action_button_width = self.ISSUE_ACTION_BUTTON_MIN_WIDTH

        for column in self.issue_action_button_columns:
            action_bar.grid_columnconfigure(column, weight=0, minsize=self.issue_action_button_width)
        for column in self.issue_action_gap_columns:
            action_bar.grid_columnconfigure(column, weight=1, minsize=0, uniform='issue_action_gap')

        button_specs = [
            ('应用当前修复', 'primary', self._apply_current_fix),
            ('忽略当前问题', 'ghost', self._ignore_current_issue),
            ('一键修复', 'accent', self._auto_fix),
        ]
        for index, (text, style, command) in enumerate(button_specs):
            host = tk.Frame(
                action_bar,
                bg=COLORS['card_bg'],
                width=self.issue_action_button_width,
                height=self.ISSUE_ACTION_BUTTON_HEIGHT,
            )
            sticky = ('w', '', 'e')[index]
            host.grid(row=0, column=self.issue_action_button_columns[index], sticky=sticky)
            host.pack_propagate(False)

            button = ModernButton(host, text, style=style, command=command, padx=4, pady=6, highlightthickness=0)
            button.pack(fill=tk.BOTH, expand=True)

            self.issue_action_hosts.append(host)
            self.issue_action_buttons.append(button)

        self.frame.after_idle(self._sync_issue_action_button_width)

        table_shell = tk.Frame(parent, bg=COLORS['surface_alt'], highlightbackground=COLORS['card_border'], highlightthickness=1)
        table_shell.pack(fill=tk.BOTH, expand=True)
        columns = ('分类', '级别', '状态', '问题')
        self.issue_tree = ttk.Treeview(table_shell, columns=columns, show='headings', height=14, selectmode='browse')
        for key in columns:
            self.issue_tree.heading(key, text=key)
        self.issue_tree.column('分类', width=110, anchor='center')
        self.issue_tree.column('级别', width=80, anchor='center')
        self.issue_tree.column('状态', width=90, anchor='center')
        self.issue_tree.column('问题', width=420, anchor='w')
        self.issue_tree.grid(row=0, column=0, sticky='nsew')
        vsb = ttk.Scrollbar(table_shell, orient=tk.VERTICAL, command=self.issue_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.issue_tree.configure(yscrollcommand=vsb.set)
        table_shell.grid_columnconfigure(0, weight=1)
        table_shell.grid_rowconfigure(0, weight=1)
        self.issue_tree.bind('<<TreeviewSelect>>', self._on_issue_select)

    def _sync_issue_action_button_width(self):
        if not getattr(self, 'issue_action_hosts', None):
            return
        try:
            required_width = max(button.winfo_reqwidth() for button in self.issue_action_buttons)
        except tk.TclError:
            return
        target_width = max(self.ISSUE_ACTION_BUTTON_MIN_WIDTH, required_width + self.ISSUE_ACTION_BUTTON_EXTRA_WIDTH)
        self.issue_action_button_width = target_width
        for column in self.issue_action_button_columns:
            self.issue_action_bar.grid_columnconfigure(column, minsize=target_width)
        for host in self.issue_action_hosts:
            host.configure(width=target_width)

    def _build_detail_card(self, parent):
        self.detail_title_label = tk.Label(
            parent,
            text='当前未选中问题',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.detail_title_label.pack(fill=tk.X)

        self.detail_meta_label = tk.Label(
            parent,
            text='请选择左侧问题查看详情。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.detail_meta_label.pack(fill=tk.X, pady=(6, 10))
        bind_adaptive_wrap(self.detail_meta_label, parent, padding=12, min_width=220)

        detail_frame, self.detail_text = create_scrolled_text(parent, height=14)
        detail_frame.pack(fill=tk.BOTH, expand=True)
        self.detail_text.configure(state=tk.DISABLED, cursor='arrow')

    def _get_input_text(self):
        return normalize_block_text(self.input_text.get('1.0', tk.END))

    def _set_input_text(self, text, source_kind, source_desc, *, paper_title=None, docx_path='', fingerprint=None):
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
        self.current_docx_path = docx_path
        self._last_bridge_fingerprint = fingerprint
        self._update_source_banner()
        self._update_capability_label()
        self._schedule_workspace_state_save()

    def _update_source_banner(self):
        label = self.SOURCE_KIND_LABELS.get(self.current_source_kind, self.current_source_kind)
        text = self.current_source_desc or label
        if self.current_source_kind == 'manual' and text == '手动输入内容':
            text = ''
        set_ellipsized_label_text(self.source_label, text)

    def _update_capability_label(self):
        if self.current_source_kind == 'docx_import' and self.current_docx_path:
            docx_status = '当前导入 DOCX，将提取正文文本后执行智能纠错。'
        else:
            docx_status = ''
        self._set_capability_text(docx_status)

    def _mark_input_manual(self, _event=None):
        if self._programmatic_input:
            return
        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self.current_docx_path = ''
        self._last_bridge_fingerprint = None
        self._update_source_banner()
        self._update_capability_label()
        self._schedule_workspace_state_save()

    def _clear_workspace(self):
        self._programmatic_input = True
        try:
            self.input_text.delete('1.0', tk.END)
        finally:
            self._programmatic_input = False
        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self.current_paper_title = ''
        self.current_docx_path = ''
        self.current_run = None
        self.current_run_mode = ''
        self.current_issue_map = {}
        self.current_tree_map = {}
        self.latest_auto_fixed_count = 0
        self._last_bridge_fingerprint = None
        self._update_source_banner()
        self._update_capability_label()
        self._set_preview_text('')
        self._refresh_issue_tree()
        self._refresh_stats()
        self._set_detail_issue(None)
        self._set_info_text('', fg=COLORS['text_sub'])
        self.set_status('工作区已清空')

    def _import_document(self):
        path = filedialog.askopenfilename(
            filetypes=[('Word 文档', '*.docx')],
            parent=self.frame,
        )
        if not path:
            return
        def work():
            return {
                'paper_title': os.path.splitext(os.path.basename(path))[0],
                'text': self.aux.import_docx(path),
            }

        def on_success(result):
            paper_title = result['paper_title']
            text = result['text']
            source_kind = 'docx_import'
            source_desc = f'已导入 DOCX：{os.path.basename(path)}'
            docx_path = path
            self._set_input_text(
                text,
                source_kind,
                source_desc,
                paper_title=paper_title,
                docx_path=docx_path,
            )
            self._set_info_text(f'已导入文稿：{path}', fg=COLORS['text_sub'])
            if self.config and hasattr(self.config, 'clear_home_last_import_failure'):
                self.config.clear_home_last_import_failure()
                self.config.save()
            self.set_status('文稿导入完成')

        def on_error(exc):
            if self.config and hasattr(self.config, 'set_home_last_import_failure'):
                self.config.set_home_last_import_failure('correction', os.path.basename(path), str(exc))
                self.config.save()
            messagebox.showerror('导入失败', str(exc), parent=self.frame)

        self.task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            loading_text='正在导入 DOCX...',
            status_text='正在导入 DOCX...',
        )

    def _run_ai_style_scan(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入或导入待核验的正文内容', parent=self.frame)
            return
        result = self.ai_reducer.scan_ai_features(text)
        issues = self._build_ai_style_issues(text, result)
        issue_count = len(issues)
        info_text = (
            f'AI风格扫描完成，发现 {issue_count} 项提示。当前结果为专项核验视图，不会生成修正文稿。'
            if issue_count
            else 'AI风格扫描完成，暂未发现明显的 AI 模板化写作痕迹。当前结果为专项核验视图。'
        )
        color = COLORS['error'] if result.get('score', 0) >= 30 else COLORS['warning'] if issue_count else COLORS['success']
        self._apply_review_run('ai_style', text, issues, info_text, 'AI风格扫描完成', color)

    def _run_logic_flow_check(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入或导入待核验的正文内容', parent=self.frame)
            return
        result = self.ai_reducer.check_logic_flow(text)
        issues = self._build_logic_flow_issues(text, result)
        issue_count = len(issues)
        info_text = (
            f'逻辑流畅度检测完成，发现 {issue_count} 项提示。当前结果为专项核验视图，不会生成修正文稿。'
            if issue_count
            else '逻辑流畅度检测完成，当前段落衔接与句间过渡未发现明显问题。'
        )
        color = COLORS['warning'] if issue_count else COLORS['success']
        self._apply_review_run('logic_flow', text, issues, info_text, '逻辑流畅度检测完成', color)

    def _run_citation_format_check(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入或导入待核验的正文内容', parent=self.frame)
            return
        result = self.plagiarism_reducer.check_citation_format(text)
        issues = self._build_citation_format_issues(text, result)
        issue_count = len(issues)
        info_text = (
            f'引用规范检查完成，发现 {issue_count} 项提示。当前结果为专项核验视图，不会生成修正文稿。'
            if issue_count
            else '引用规范检查完成，正文引用与参考文献格式暂未发现明显异常。'
        )
        color = COLORS['warning'] if issue_count else COLORS['success']
        self._apply_review_run('citation_format', text, issues, info_text, '引用规范检查完成', color)

    def _run_sensitive_expression_check(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入或导入待核验的正文内容', parent=self.frame)
            return
        result = self.aux.detect_sensitive(text)
        issues = self._build_sensitive_expression_issues(text, result)
        issue_count = len(issues)
        info_text = (
            f'敏感表达检查完成，发现 {issue_count} 处需要复核的表达。当前结果为专项核验视图，不会生成修正文稿。'
            if issue_count
            else '敏感表达检查完成，暂未发现命中的敏感表达。'
        )
        color = COLORS['error'] if any(getattr(issue, 'severity', '') == 'error' for issue in issues) else COLORS['warning'] if issue_count else COLORS['success']
        self._apply_review_run('sensitive_expression', text, issues, info_text, '敏感表达检查完成', color)

    def _apply_review_run(self, mode, text, issues, info_text, status_text, color):
        self.current_run = self._build_review_run(text, issues)
        self.current_run_mode = mode
        self.latest_auto_fixed_count = 0
        self._update_run_views()
        self._set_info_text(info_text, fg=color)
        self.set_status(status_text, color)

    def _build_review_run(self, text, issues):
        detected_style = self.corrector._detect_citation_style(text)
        selected_style = self.citation_style_var.get()
        effective_style = selected_style if selected_style != 'auto' else detected_style
        merged_issues = self.corrector._merge_issues(issues)
        run = CorrectionRun(
            input_text=text,
            corrected_text=text,
            issues=[issue.as_dict() for issue in merged_issues],
            counts=self.corrector._summarize_issues(merged_issues),
            source_kind=self.current_source_kind,
            citation_style_detected=detected_style,
            citation_style_effective=effective_style,
        )
        run.report_text = self.corrector.build_report(run)
        return run

    def _make_review_issue(
        self,
        text,
        *,
        category,
        severity,
        source,
        title,
        message,
        suggestion='',
        snippet='',
        used_spans=None,
    ):
        start, end = self._find_text_span(text, snippet, used_spans=used_spans)
        if start >= 0 and used_spans is not None:
            used_spans.add((start, end))
        original = text[start:end] if start >= 0 else self._resolve_snippet_for_search(snippet)
        return self.corrector._make_issue(
            category=category,
            severity=severity,
            source=source,
            title=title,
            message=message,
            start=start,
            end=end,
            original=original,
            suggestion=suggestion,
            auto_fixable=False,
            confidence=0.82 if start >= 0 else 0.68,
        )

    def _find_text_span(self, text, snippet, *, used_spans=None):
        target = self._resolve_snippet_for_search(snippet)
        if not target:
            return -1, -1
        start_pos = 0
        while True:
            start = text.find(target, start_pos)
            if start < 0:
                return -1, -1
            end = start + len(target)
            if used_spans is None or (start, end) not in used_spans:
                return start, end
            start_pos = start + 1

    @staticmethod
    def _resolve_snippet_for_search(snippet):
        value = str(snippet or '').strip()
        if not value:
            return ''
        value = value.replace('\r', ' ').replace('\n', ' ').strip()
        value = re.sub(r'\s+', ' ', value)
        if value.endswith('...'):
            value = value[:-3].rstrip()
        if value.startswith('...'):
            value = value[3:].lstrip()
        return value

    def _build_ai_style_issues(self, text, result):
        issues = []
        used_spans = set()
        score = int(result.get('score', 0) or 0)
        severity = 'error' if score >= 30 else 'warning' if score >= 15 else 'info'

        for sentence in result.get('sentences_flagged', []):
            issues.append(
                self._make_review_issue(
                    text,
                    category='ai_style',
                    severity=severity,
                    source='review.ai_style',
                    title='疑似 AI 模板句',
                    message='该句存在较明显的模板化表达，建议补充具体论证或改写句式。',
                    suggestion='改写套话表达，增加与你当前论题直接相关的事实、分析或例证。',
                    snippet=sentence,
                    used_spans=used_spans,
                )
            )

        for feature in result.get('features', []):
            issues.append(
                self.corrector._make_issue(
                    category='ai_style',
                    severity=severity,
                    source='review.ai_style',
                    title='AI 风格特征提示',
                    message=feature,
                    suggestion='优先调整重复套话、均匀句式和模板化衔接方式，增强人工写作痕迹。',
                    auto_fixable=False,
                    confidence=0.7,
                )
            )

        return issues

    def _build_logic_flow_issues(self, text, result):
        issues = []
        used_spans = set()
        flow_score = int(result.get('flow_score', 0) or 0)
        severity = 'error' if flow_score < 60 else 'warning'
        focus_segments = list(result.get('focus_segments', []))
        for index, issue_text in enumerate(result.get('issues', [])):
            snippet = focus_segments[index] if index < len(focus_segments) else ''
            issues.append(
                self._make_review_issue(
                    text,
                    category='logic_rigor',
                    severity=severity,
                    source='review.logic_flow',
                    title='逻辑流畅度提示',
                    message=issue_text,
                    suggestion='补充过渡句、拆分长句，或明确段落之间的因果与递进关系。',
                    snippet=snippet,
                    used_spans=used_spans,
                )
            )
        return issues

    def _build_citation_format_issues(self, text, result):
        issues = []
        used_spans = set()
        for issue_text in result.get('issues', []):
            snippet = ''
            number_match = re.search(r'(\d+)', issue_text)
            if number_match:
                citation_marker = f'[{number_match.group(1)}]'
                if citation_marker in text:
                    snippet = citation_marker
            if not snippet and ('参考文献' in issue_text or '文献列表' in issue_text or '末尾' in issue_text):
                snippet = '参考文献'

            severity = 'error' if ('缺少' in issue_text or '未发现' in issue_text) else 'warning'
            issues.append(
                self._make_review_issue(
                    text,
                    category='citation_reference',
                    severity=severity,
                    source='review.citation',
                    title='引用规范提示',
                    message=issue_text,
                    suggestion='请核对正文引用标记、参考文献编号及条目格式的一致性。',
                    snippet=snippet,
                    used_spans=used_spans,
                )
            )
        return issues

    def _build_sensitive_expression_issues(self, text, result):
        issues = []
        used_spans = set()
        for item in result or []:
            category = str(item.get('category') or '敏感表达')
            severity = 'error' if category in {'政治敏感内容', '违规内容'} else 'warning'
            for match in item.get('matches', []):
                issues.append(
                    self._make_review_issue(
                        text,
                        category='compliance_risk',
                        severity=severity,
                        source='review.sensitive',
                        title=category,
                        message=f'检测到“{match}”可能涉及{category}，建议结合上下文进行人工复核。',
                        suggestion='若非必要，请替换为更客观、中性的学术表达，避免合规风险。',
                        snippet=match,
                        used_spans=used_spans,
                    )
                )
        return issues

    def _run_correction(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', '请先输入或导入待纠错文本', parent=self.frame)
            return
        if not self._ensure_prompt_ready():
            return

        knowledge_context = self._choose_knowledge_context('correction.ai_review', '智能纠错')
        if knowledge_context is None:
            return

        citation_style = self.citation_style_var.get()

        def on_start():
            self.current_run = None
            self.current_run_mode = ''
            self.current_issue_map = {}
            self.current_tree_map = {}
            self.latest_auto_fixed_count = 0
            self._set_preview_text('正在执行智能纠错，请稍候...')
            self._refresh_issue_tree()
            self._refresh_stats()
            self._set_detail_issue(None)

        def on_success(run):
            self.current_run = run
            self.current_run_mode = 'correction'
            self._update_run_views()
            self._add_history_version(
                '全文智能纠错',
                run.input_text,
                run.corrected_text,
                extra=self._build_history_extra(run, auto_fixed_count=0),
            )
            self._set_info_text(
                f'智能纠错完成，共发现 {run.counts.get("pending", 0)} 项待处理问题，可自动修复 {run.counts.get("auto_fixable", 0)} 项。',
                fg=COLORS['text_sub'],
            )
            self.set_status('智能纠错完成')

        def on_error(exc):
            self._set_preview_text(f'错误：{exc}')
            self.current_run_mode = ''
            self._set_info_text('智能纠错失败，请检查模型配置或文稿内容。', fg=COLORS['error'])
            self.set_status('智能纠错失败', COLORS['error'])

        def work():
            return self.corrector.analyze_text(
                text,
                citation_style=citation_style,
                source_kind=self.current_source_kind,
                knowledge_context=knowledge_context,
            )

        self.task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            on_start=on_start,
            loading_text='正在执行智能纠错...',
            status_text='智能纠错执行中...',
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

    def _add_history_version(self, operation, input_text, output_text, extra=None):
        self.history.add(
            operation,
            input_text,
            output_text,
            MODULE_CORRECTION,
            extra=extra,
            page_state_id=self.PAGE_STATE_ID,
            workspace_state=self.capture_workspace_state_snapshot(save_to_disk=False),
        )

    def _open_prompt_manager(self):
        if not self.app_bridge:
            return
        self.app_bridge.show_prompt_manager(page_id='correction', compact=True, scene_id='correction.ai_review')

    def _ensure_prompt_ready(self):
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return False
        if self.prompt_center.scene_has_active_prompt('correction.ai_review'):
            return True
        messagebox.showwarning(
            '提示',
            '当前页面没有可用的提示词，请先创建或选择一条提示词。注意：该提示词仅影响 AI 补充识别链路。',
            parent=self.frame,
        )
        self._open_prompt_manager()
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

    def _build_history_extra(self, run, auto_fixed_count=0):
        paper_title = self.current_paper_title
        if not paper_title and self.current_docx_path:
            paper_title = os.path.splitext(os.path.basename(self.current_docx_path))[0]
        return {
            'source_kind': self.SOURCE_KIND_LABELS.get(self.current_source_kind, self.current_source_kind),
            'citation_style_detected': run.citation_style_detected,
            'citation_style_effective': run.citation_style_effective,
            'issue_counts': dict(run.counts.get('by_category', {})),
            'auto_fixed_count': auto_fixed_count,
            'paper_title': paper_title,
        }

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
            paper_title=payload.get('paper_title', ''),
            fingerprint=fingerprint,
        )
        self._update_paper_font_styles(payload.get('level_font_styles'))
        return {
            'ok': True,
            'message': '内容已发送到智能纠错页',
            'section': section_name,
            'page_id': self.PAGE_STATE_ID,
        }

    def _update_run_views(self):
        run = self.current_run
        if not run:
            return
        run.counts = self.corrector._summarize_issues(run.issues)
        run.report_text = self.corrector.build_report(run)
        self._set_preview_text(run.corrected_text)
        self._apply_paper_fonts_to_widgets()
        self._refresh_issue_tree()
        self._refresh_stats()
        first_pending = next((issue['id'] for issue in run.issues if issue.get('status') == 'pending'), None)
        if first_pending:
            self._focus_issue(first_pending)
        else:
            self._set_detail_issue(None)

    def _refresh_stats(self):
        by_category = {}
        if self.current_run:
            self.current_run.counts = self.corrector._summarize_issues(self.current_run.issues)
            by_category = self.current_run.counts.get('by_category', {})
        for category, label in self.stat_cards.items():
            label.configure(text=str(by_category.get(category, 0)))

    def _refresh_issue_tree(self):
        if not hasattr(self, 'issue_tree'):
            return
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.current_issue_map = {}
        self.current_tree_map = {}
        if not self.current_run:
            return
        for issue in self.current_run.issues:
            iid = self.issue_tree.insert(
                '',
                tk.END,
                values=(
                    CATEGORY_LABELS.get(issue.get('category'), issue.get('category')),
                    SEVERITY_LABELS.get(issue.get('severity'), issue.get('severity')),
                    self.ISSUE_STATUS_LABELS.get(issue.get('status'), issue.get('status')),
                    issue.get('title', ''),
                ),
            )
            self.current_issue_map[issue['id']] = issue
            self.current_tree_map[issue['id']] = iid

    def _focus_issue(self, issue_id):
        iid = self.current_tree_map.get(issue_id)
        if not iid:
            return
        self.issue_tree.selection_set(iid)
        self.issue_tree.focus(iid)
        self.issue_tree.see(iid)
        self._set_detail_issue(self.current_issue_map.get(issue_id))

    def _on_issue_select(self, _event=None):
        selection = self.issue_tree.selection()
        if not selection:
            self._set_detail_issue(None)
            return
        for issue_id, iid in self.current_tree_map.items():
            if iid == selection[0]:
                self._set_detail_issue(self.current_issue_map.get(issue_id))
                return

    def _set_detail_issue(self, issue):
        if not issue:
            self.detail_title_label.configure(text='当前未选中问题')
            self.detail_meta_label.configure(text='请选择左侧问题查看详情。')
            self._set_readonly_text(self.detail_text, '运行智能纠错后，这里会显示问题原因、修改建议与可自动修复内容。')
            return

        self.detail_title_label.configure(text=issue.get('title', '未命名问题'))
        lines = [
            f'分类：{CATEGORY_LABELS.get(issue.get("category"), issue.get("category"))}',
            f'级别：{SEVERITY_LABELS.get(issue.get("severity"), issue.get("severity"))}',
            f'状态：{self.ISSUE_STATUS_LABELS.get(issue.get("status"), issue.get("status"))}',
            f'来源：{issue.get("source", "rule")}',
        ]
        if issue.get('doc_anchor'):
            lines.append(f'锚点：{issue.get("doc_anchor")}')
        self.detail_meta_label.configure(text=' | '.join(lines))

        detail_lines = [f'问题说明：{issue.get("message", "")}']
        if issue.get('original'):
            detail_lines.append(f'原文片段：{issue.get("original")}')
        if issue.get('suggestion'):
            detail_lines.append(f'修改建议：{issue.get("suggestion")}')
        if issue.get('auto_fixable'):
            detail_lines.append(f'自动修复：{issue.get("replacement", "")}')
        else:
            detail_lines.append('自动修复：该问题默认需要人工确认。')
        self._set_readonly_text(self.detail_text, '\n\n'.join(detail_lines))

    def _set_readonly_text(self, widget, text):
        widget.configure(state=tk.NORMAL)
        widget.delete('1.0', tk.END)
        if text:
            widget.insert('1.0', text)
        widget.configure(state=tk.DISABLED)

    def _set_preview_text(self, text):
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete('1.0', tk.END)
        if text:
            self.output_text.insert('1.0', text)
        for tag in list(self.output_text.tag_names()):
            if tag.startswith('issue::'):
                self.output_text.tag_delete(tag)
        for category, color in self.CATEGORY_COLORS.items():
            tag = f'cat::{category}'
            self.output_text.tag_configure(tag, background=color)
        if self.current_run and text:
            for issue in self.current_run.issues:
                if issue.get('status') != 'pending':
                    continue
                start = int(issue.get('start', -1))
                end = int(issue.get('end', -1))
                if start < 0 or end <= start:
                    continue
                start_index = f'1.0+{start}c'
                end_index = f'1.0+{end}c'
                category_tag = f'cat::{issue.get("category")}'
                issue_tag = f'issue::{issue.get("id")}'
                self.output_text.tag_add(category_tag, start_index, end_index)
                self.output_text.tag_add(issue_tag, start_index, end_index)
                self.output_text.tag_bind(issue_tag, '<Enter>', lambda event, payload=issue: self._show_issue_tooltip(event, payload))
                self.output_text.tag_bind(issue_tag, '<Leave>', lambda _event: self._hide_issue_tooltip())
                self.output_text.tag_bind(issue_tag, '<Button-1>', lambda _event, issue_id=issue.get('id'): self._focus_issue(issue_id))
        self.output_text.configure(state=tk.DISABLED)

    def _show_issue_tooltip(self, event, issue):
        self._hide_issue_tooltip()
        x = event.x_root + 16
        y = event.y_root + 12
        tooltip = tk.Toplevel(self.frame)
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f'+{x}+{y}')
        shell = tk.Frame(tooltip, bg=COLORS['card_border'], highlightbackground=COLORS['card_border'], highlightthickness=1)
        shell.pack()
        text = issue.get('message', '')
        if issue.get('suggestion'):
            text += f'\n建议：{issue.get("suggestion")}'
        tk.Label(
            shell,
            text=text,
            font=FONTS['small'],
            fg=COLORS['card_bg'],
            bg=COLORS['card_border'],
            justify='left',
            anchor='w',
            padx=8,
            pady=6,
        ).pack()
        self._tooltip_window = tooltip

    def _hide_issue_tooltip(self):
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def _selected_issue(self):
        selection = self.issue_tree.selection()
        if not selection:
            return None
        for issue_id, iid in self.current_tree_map.items():
            if iid == selection[0]:
                return self.current_issue_map.get(issue_id)
        return None

    def _collect_applicable_issues(self, ids):
        selected_ids = set(ids or [])
        issues = []
        if not self.current_run:
            return issues
        for issue in self.current_run.issues:
            if issue.get('status') != 'pending' or not issue.get('auto_fixable'):
                continue
            if selected_ids and issue.get('id') not in selected_ids:
                continue
            start = int(issue.get('start', -1))
            end = int(issue.get('end', -1))
            if start < 0 or end <= start:
                continue
            issues.append(issue)
        issues.sort(key=lambda item: (int(item.get('start', -1)), int(item.get('end', -1))))
        filtered = []
        last_end = -1
        for issue in issues:
            start = int(issue.get('start', -1))
            if start < last_end:
                continue
            filtered.append(issue)
            last_end = int(issue.get('end', -1))
        return filtered

    def _apply_current_fix(self):
        issue = self._selected_issue()
        if not issue:
            messagebox.showwarning('提示', '请先选择一个问题', parent=self.frame)
            return
        if not issue.get('auto_fixable'):
            messagebox.showwarning('提示', '该问题当前不支持自动修复，请按建议手动处理。', parent=self.frame)
            return
        self._apply_issue_ids([issue['id']])

    def _auto_fix(self):
        if not self.current_run:
            messagebox.showwarning('提示', '请先执行智能纠错', parent=self.frame)
            return
        ids = [issue['id'] for issue in self.current_run.issues if issue.get('status') == 'pending' and issue.get('auto_fixable')]
        if not ids:
            messagebox.showwarning('提示', '当前没有可自动修复的问题', parent=self.frame)
            return
        self._apply_issue_ids(ids)

    def _apply_issue_ids(self, ids):
        if not self.current_run:
            return
        applicable = self._collect_applicable_issues(ids)
        if not applicable:
            messagebox.showwarning('提示', '未找到可应用的自动修复项', parent=self.frame)
            return
        before_text = self.current_run.corrected_text
        new_text = self.corrector.apply_fixes(before_text, self.current_run.issues, ids=[item['id'] for item in applicable])
        if new_text == before_text:
            messagebox.showwarning('提示', '本次没有应用到新的修复内容', parent=self.frame)
            return

        events = []
        applied_ids = {issue['id'] for issue in applicable}
        for issue in applicable:
            start = int(issue.get('start', -1))
            end = int(issue.get('end', -1))
            replacement = issue.get('replacement', '')
            events.append((start, end, len(replacement) - (end - start)))

        for issue in self.current_run.issues:
            if issue.get('id') in applied_ids:
                issue['status'] = 'applied'
                continue
            if issue.get('status') != 'pending':
                continue
            start = int(issue.get('start', -1))
            end = int(issue.get('end', -1))
            if start < 0 or end <= start:
                continue
            original_start = start
            original_end = end
            stale = False
            delta_sum = 0
            for event_start, event_end, delta in events:
                if original_end <= event_start:
                    continue
                if original_start >= event_end:
                    delta_sum += delta
                else:
                    stale = True
                    break
            if stale:
                issue['status'] = 'stale'
            else:
                issue['start'] = original_start + delta_sum
                issue['end'] = original_end + delta_sum

        self.current_run.corrected_text = new_text
        self.latest_auto_fixed_count += len(applicable)
        self._update_run_views()
        self._set_info_text(
            f'已应用 {len(applicable)} 项自动修复；若仍有待复核问题，建议重新执行一轮智能纠错。',
            fg=COLORS['success'],
        )
        self.set_status('自动修复已应用')

    def _ignore_current_issue(self):
        issue = self._selected_issue()
        if not issue:
            messagebox.showwarning('提示', '请先选择一个问题', parent=self.frame)
            return
        issue['status'] = 'ignored'
        self._update_run_views()
        self._set_info_text('已忽略当前问题。', fg=COLORS['text_sub'])
        self.set_status('已忽略问题')

    def _ensure_correction_mode(self, *, for_report=False):
        if not self.current_run or self.current_run_mode == 'correction':
            return True
        message = '当前结果来自专项核验，不是修正文稿，请先执行“开始智能纠错”。'
        if for_report:
            message = '当前结果来自专项核验，不是智能纠错报告，请先执行“开始智能纠错”。'
        messagebox.showwarning('提示', message, parent=self.frame)
        return False

    def _ensure_corrected_text(self):
        if not self._ensure_correction_mode():
            return ''
        corrected_text = normalize_block_text(self.current_run.corrected_text if self.current_run else '')
        if not self.current_run or not corrected_text.strip():
            messagebox.showwarning('提示', '当前没有可导出或写回的修正文稿', parent=self.frame)
            return ''
        return corrected_text

    def _export_corrected(self):
        text = self._ensure_corrected_text()
        if not text:
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('文本文件', '*.txt'), ('Word 文档', '*.docx')],
            parent=self.frame,
        )
        if not path:
            return
        try:
            if path.lower().endswith('.docx'):
                self.aux.export_docx(text, path, title='智能纠错修正文稿')
            else:
                self.aux.export_txt(text, path)
            self._set_info_text(f'修正文稿已导出到：{path}', fg=COLORS['success'])
            self.set_status('修正文稿已导出')
        except Exception as exc:
            messagebox.showerror('导出失败', str(exc), parent=self.frame)

    def _export_report(self):
        if not self._ensure_correction_mode(for_report=True):
            return
        if not self.current_run or not self.current_run.report_text.strip():
            messagebox.showwarning('提示', '请先执行智能纠错生成报告', parent=self.frame)
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('文本文件', '*.txt'), ('Word 文档', '*.docx')],
            parent=self.frame,
        )
        if not path:
            return
        try:
            if path.lower().endswith('.docx'):
                self.aux.export_docx(self.current_run.report_text, path, title='论文纠错报告')
            else:
                self.aux.export_txt(self.current_run.report_text, path)
            self._set_info_text(f'纠错报告已导出到：{path}', fg=COLORS['success'])
            self.set_status('纠错报告已导出')
        except Exception as exc:
            messagebox.showerror('导出失败', str(exc), parent=self.frame)

    def _apply_to_paper(self, target_mode):
        text = self._ensure_corrected_text()
        if not text:
            return
        if not self.app_bridge:
            messagebox.showwarning('提示', '当前版本未连接论文写作页桥接动作。', parent=self.frame)
            return
        title = '写回论文大纲' if target_mode == 'outline' else '回填到原文'
        target_text = '论文大纲' if target_mode == 'outline' else '当前章节正文'
        if not messagebox.askyesno(title, f'确认将当前修正文稿写回到{target_text}吗？', parent=self.frame):
            return
        outcome = self.app_bridge.apply_result_to_paper_write(
            text,
            target_mode=target_mode,
            write_mode='replace',
            section_hint='',
            task_type='',
        )
        if not outcome or not outcome.get('ok'):
            messagebox.showwarning('写回失败', (outcome or {}).get('message', '无法写回到论文写作页'), parent=self.frame)
            return
        self._set_info_text(outcome.get('message', '写回成功'), fg=COLORS['success'])
        self.set_status(outcome.get('message', '已写回论文写作页'))

    def on_show(self):
        if self._workspace_state_restored and self._get_input_text():
            return

        snapshot = self.app_bridge.pull_paper_write_selection_snapshot() if self.app_bridge else None
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
                    paper_title=snapshot.get('paper_title', ''),
                    fingerprint=fingerprint,
                )
                self._update_paper_font_styles(snapshot.get('level_font_styles'))
                return

        context = self.app_bridge.pull_paper_write_context() if self.app_bridge else {}
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
        if existing_input and self.current_source_kind in {'manual', 'import', 'docx_import'}:
            return

        desc = f'来自论文写作页当前章节{f" / {current_section}" if current_section else ""}'
        self._set_input_text(
            current_content,
            'paper_section',
            desc,
            paper_title=context.get('paper_title', ''),
            fingerprint=fingerprint,
        )
        self._update_paper_font_styles(context.get('level_font_styles'))
