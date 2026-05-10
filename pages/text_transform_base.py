# -*- coding: utf-8 -*-
"""
Shared UI and task flow for text transformation pages.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from modules.aux_tools import AuxTools
from modules.prompt_center import PromptCenter
from modules.report_importer import (
    ImportSession,
    ParagraphAnnotation,
    normalize_block_text,
    split_document_paragraphs,
)
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
    create_selector_card,
    load_image,
    ModernButton,
    ResponsiveButtonBar,
    style_selector_card,
    bind_adaptive_wrap,
    bind_responsive_two_pane,
    create_scrolled_text,
    set_ellipsized_label_text,
    show_tooltip,
    THEMES,
    ToggleSwitch,
)
from modules.workspace_state import WorkspaceStateMixin


TRANSIENT_RESULT_MARKERS = {'处理中...'}


def has_meaningful_text(text):
    return bool(str(text or '').strip())


def normalize_result_text(text):
    value = normalize_block_text(text)
    trimmed = value.strip()
    if not trimmed:
        return ''
    if trimmed in TRANSIENT_RESULT_MARKERS or trimmed.startswith('错误：'):
        return ''
    return trimmed


def resolve_detection_target(input_text, output_text, *, input_label='原文输入', result_label='当前结果'):
    result_text = normalize_result_text(output_text)
    if result_text:
        return result_text, result_label
    source_text = normalize_block_text(input_text)
    if source_text.strip():
        return source_text, input_label
    return '', ''


def resolve_diff_baseline(input_text, compare_text, *, input_label='原文输入', compare_label='对比文本'):
    baseline = normalize_block_text(compare_text)
    if baseline.strip():
        return baseline, compare_label
    source_text = normalize_block_text(input_text)
    if source_text.strip():
        return source_text, input_label
    return '', ''


class TextTransformPageBase(WorkspaceStateMixin):
    _BROKEN_SOURCE_DESC_PREFIXES = (
        ('鏉ヨ嚜璁烘枃鍐欎綔椤甸€夊尯', '来自论文写作页选区'),
        ('鏉ヨ嚜璁烘枃鍐欎綔椤靛綋鍓嶇珷鑺', '来自论文写作页当前章节'),
    )
    PAGE_STATE_ID = ''
    MODE_CARD_TITLE = ''
    MODE_CARD_HINT = ''
    MODE_DEFAULT = ''
    MODE_OPTIONS = ()
    MODE_COLOR_KEY = 'primary'
    MODE_LAYOUT = 'stacked_cards'
    MODE_INLINE_ITEM_WIDTH = 252
    MODE_INLINE_ITEM_HEIGHT = 76
    MODE_INLINE_ITEM_GAP = 14
    MODE_INLINE_ACTION_WIDTH = 332
    MODE_INLINE_ACTION_HEIGHT = 74
    MODE_INLINE_GROUP_GAP = 18
    MODE_INLINE_RIGHT_INSET = 8
    MODE_TOOLTIP_ICON_PATH = 'png/Tip.png'
    TOP_SECTION_LAYOUT = 'stacked'
    TOP_SECTION_BREAKPOINT = 1260
    TOP_SECTION_GAP = 10
    TOP_SECTION_LEFT_MINSIZE = 620
    TOP_SECTION_RIGHT_MINSIZE = 360
    TOP_SECTION_SPLIT_RATIO = 0.62
    DETECT_SECTION_PLACEMENT = 'top'
    MERGED_TOP_CARD_TITLE = ''
    MERGED_MODE_LABEL_TEXT = '处理模式：'
    MERGED_DETECT_LABEL_TEXT = '结果核验：'
    ACTION_BUTTON_TEXT = ''
    ACTION_BUTTON_STYLE = 'primary'
    ACTION_TIP_TEXT = ''
    ACTION_START_STATUS = ''
    ACTION_LOADING_TEXT = ''
    ACTION_SUCCESS_STATUS = ''
    ACTION_FAILURE_STATUS = ''
    PROCESS_EMPTY_WARNING = '请先输入需要处理的文本。'
    INPUT_CARD_IMPORTED_TITLE = '原文区'
    ANNOTATION_EDITOR_TITLE = '段落标注'
    ANNOTATION_RISK_LABELS = {
        'high': '高风险',
        'medium': '中风险',
        'low': '低风险',
        'safe': '安全',
    }
    ANNOTATION_RISK_COLORS = {
        'high': '#F8C9D1',
        'medium': '#FFDAB5',
        'low': '#E6E1FF',
        'safe': '#E9ECEF',
    }
    ANNOTATION_BADGE_COLORS = {
        'high': ('#D9485F', '#FFFDF8'),
        'medium': ('#E67700', '#FFFDF8'),
        'low': ('#7B61FF', '#FFFDF8'),
        'safe': ('#15161A', '#FFFDF8'),
    }
    ANNOTATION_SOURCE_COLOR_STYLES = {
        'red': {'highlight': '#F8C9D1', 'badge': ('#D9485F', '#FFFDF8')},
        'orange': {'highlight': '#FFDAB5', 'badge': ('#E67700', '#FFFDF8')},
        'purple': {'highlight': '#E6E1FF', 'badge': ('#7B61FF', '#FFFDF8')},
        'black': {'highlight': '#E9ECEF', 'badge': ('#15161A', '#FFFDF8')},
        'gray': {'highlight': '#ECEFF3', 'badge': ('#6B7280', '#FFFFFF')},
    }

    DETECT_CARD_TITLE = '检测核验区'
    DETECT_CARD_HINT = ''
    DETECT_RESULT_HINT = ''
    COMPARE_DETECT_BADGE_TEXT = '附属功能区'
    COMPARE_DETECT_HELP_TEXT = '用于复核当前处理结果，不影响上方主流程执行。'
    COMPARE_DETECT_COLLAPSIBLE = False
    COMPARE_DETECT_DEFAULT_COLLAPSED = False
    COMPARE_DETECT_COLLAPSED_HINT = '默认收起，按需展开复核当前结果。'
    PRIMARY_ANALYSIS_BUTTON_TEXT = '开始检测'
    PRIMARY_ANALYSIS_BUTTON_STYLE = 'primary'
    SECONDARY_ANALYSIS_BUTTON_TEXT = '结构检查'
    PRIMARY_ANALYSIS_EMPTY_WARNING = '请先输入原文或生成处理结果。'
    ANALYSIS_STATUS_READY_TEXT = '请选择上方核验动作。'
    STALE_ANALYSIS_TEXT = '内容已更新，请重新执行核验。'
    STALE_PREVIEW_TEXT = '内容已更新，请点击“刷新差异视图”重新生成差异预览。'

    INPUT_CARD_TITLE = '原文输入'
    INPUT_PLACEHOLDER = '请粘贴需要处理的文本。'
    OUTPUT_CARD_TITLE = '处理结果'
    OUTPUT_PLACEHOLDER = '处理完成后，结果将显示在此处。'

    SHOW_COMPARE_SECTION = True
    COMPARE_SECTION_TITLE = '对比与预览'
    COMPARE_SECTION_DESCRIPTION = ''
    COMPARE_SECTION_COLLAPSIBLE = False
    COMPARE_SECTION_DEFAULT_COLLAPSED = False
    COMPARE_CARD_TITLE = '对比文本'
    COMPARE_CARD_HINT = ''
    COMPARE_PLACEHOLDER = '可粘贴用于对比的文本。'
    COMPARE_TEXT_HEIGHT = 16

    PREVIEW_CARD_TITLE = '核验结果与差异预览'
    PREVIEW_LEGEND_TEXT = '绿色=新增内容，红色=删除内容，灰色=保留内容。'
    PREVIEW_LEGEND_ITEMS = ()
    SUMMARY_TITLE = '检测结果摘要'
    SUMMARY_PLACEHOLDER_TEXT = '完成检测后，此处将展示摘要结果。'
    PREVIEW_TITLE = '差异预览'
    PREVIEW_EMPTY_TEXT = '点击“刷新差异视图”，查看文本差异。'
    PREVIEW_MISSING_TEXT = '请先准备基准文本与处理结果。'

    REPLACE_BUTTON_TEXT = '用结果替换原文'
    REPLACE_EMPTY_WARNING = '当前没有可替换的处理结果。'
    REPLACE_INFO_TEXT = '已用处理结果替换原文，请重新核验或继续调整。'
    SHOW_OUTPUT_HEADER_REPLACE_ACTION = False
    INPUT_RESET_BUTTON_TEXT = '重置'
    INPUT_RESET_INFO_TEXT = '原文区已清空。'
    INPUT_RESET_STALE_TEXT = '原文区已清空，请重新输入内容后再执行核验或刷新差异视图。'

    INPUT_SOURCE_LABEL = '原文输入'
    RESULT_SOURCE_LABEL = '当前结果'
    COMPARE_SOURCE_LABEL = '对比文本'
    COMPARE_TEXT_USED_FOR_DIFF_BASELINE = True

    MODULE_NAME = ''
    PROMPT_PAGE_ID = ''
    PROMPT_SCENE_ID = ''

    def __init__(
        self,
        parent,
        config_mgr,
        api_client,
        history_mgr,
        set_status,
        processor,
        *,
        navigate_page=None,
        app_bridge=None,
        loading_text='',
    ):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.processor = processor
        self.prompt_center = PromptCenter(config_mgr)
        self.aux = AuxTools(api_client)
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text=loading_text)
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._pending_knowledge_context = None

        self.mode_var = tk.StringVar(value=self.MODE_DEFAULT)
        self.mode_cards = []
        self.compare_widgets = []
        self._compare_syncing = False
        self._placeholder_state = {}
        self._compare_section_body = None
        self._compare_section_arrow = None
        self._compare_section_expanded = not self.COMPARE_SECTION_DEFAULT_COLLAPSED
        self._compare_detect_body = None
        self._compare_detect_arrow = None
        self._compare_detect_expanded = not self.COMPARE_DETECT_DEFAULT_COLLAPSED
        self.current_source_kind = 'manual'
        self.current_source_desc = '手动输入内容'
        self.current_paper_title = ''
        self._last_bridge_fingerprint = None
        self._paper_font_styles = {}
        self.import_session = None
        self.annotation_overrides = {}
        self.selected_annotation_id = ''
        self._annotation_badges = {}
        self._annotation_tag_names = set()
        self._annotation_popup = None
        self._annotation_layout_job = None
        self._suppress_import_session_clear = False
        self.manual_annotations = []
        self.manual_annotation_base_text = ''
        self._init_workspace_state_support()

        self.input_text = None
        self.output_text = None
        self.compare_text = None
        self.analysis_text = None
        self.preview_text = None
        self.analysis_status_label = None
        self.info_label = None
        self.input_source_label = None
        self._input_card = None

        self._build()
        self._bind_text_watchers()
        self._reset_analysis_workspace()
        self.restore_saved_workspace_state()
        self._bind_workspace_state_watchers()
        self._enable_workspace_state_autosave()

    def _build(self):
        self._build_top_sections(self.frame)
        self._build_input_output_section(self.frame)
        self._build_compare_preview_section(self.frame)
        self._build_replace_row(self.frame)

    def _build_pre_mode_section(self, parent):
        del parent

    def _build_top_sections(self, parent):
        self._build_pre_mode_section(parent)
        if self.TOP_SECTION_LAYOUT == 'merged_toolbar':
            self._build_merged_top_toolbar(parent)
            return
        if self.TOP_SECTION_LAYOUT == 'split':
            if self.DETECT_SECTION_PLACEMENT != 'top':
                self._build_mode_card(parent)
                return
            top_body = tk.Frame(parent, bg=COLORS['bg_main'])
            top_body.pack(fill=tk.X, pady=(0, 10))
            left_host = tk.Frame(top_body, bg=COLORS['bg_main'])
            right_host = tk.Frame(top_body, bg=COLORS['bg_main'])
            left_host.pack_propagate(False)
            right_host.pack_propagate(False)
            mode_card = self._create_mode_card(left_host)
            mode_card.pack(fill=tk.BOTH, expand=True)
            detect_card = self._create_detect_card(right_host)
            detect_card.pack(fill=tk.BOTH, expand=True)
            self._bind_top_section_split(top_body, left_host, right_host)
            return
        self._build_mode_card(parent)
        if self.DETECT_SECTION_PLACEMENT == 'top':
            self._build_detect_section(parent)

    def _bind_top_section_split(self, container, left_host, right_host):
        state = {'job': None, 'signature': None}

        def relayout(_event=None):
            state['job'] = None
            width = max(container.winfo_width(), container.winfo_reqwidth(), 1)
            gap = self.TOP_SECTION_GAP
            left_card = left_host.winfo_children()[0] if left_host.winfo_children() else None
            right_card = right_host.winfo_children()[0] if right_host.winfo_children() else None
            left_height = max(left_card.winfo_reqheight() if left_card else left_host.winfo_reqheight(), 1)
            right_height = max(right_card.winfo_reqheight() if right_card else right_host.winfo_reqheight(), 1)

            if width < self.TOP_SECTION_BREAKPOINT:
                total_height = left_height + gap + right_height
                signature = ('stacked', width, total_height, left_height, right_height)
                if state['signature'] == signature:
                    return
                state['signature'] = signature
                container.configure(height=total_height)
                left_host.place(x=0, y=0, width=width, height=left_height)
                right_host.place(x=0, y=left_height + gap, width=width, height=right_height)
                return

            usable_width = max(width - gap, 1)
            min_left = min(self.TOP_SECTION_LEFT_MINSIZE, max(usable_width - self.TOP_SECTION_RIGHT_MINSIZE, 1))
            left_width = max(min_left, int(usable_width * self.TOP_SECTION_SPLIT_RATIO))
            max_left = max(usable_width - self.TOP_SECTION_RIGHT_MINSIZE, min_left)
            left_width = min(left_width, max_left)
            right_width = max(self.TOP_SECTION_RIGHT_MINSIZE, usable_width - left_width)
            row_height = max(left_height, right_height)
            signature = ('split', width, left_width, right_width, row_height)
            if state['signature'] == signature:
                return
            state['signature'] = signature

            container.configure(height=row_height)
            left_host.place(x=0, y=0, width=left_width, height=row_height)
            right_host.place(x=left_width + gap, y=0, width=right_width, height=row_height)

        def schedule_relayout(_event=None):
            if state.get('job') is not None:
                return
            try:
                state['job'] = container.after(16, relayout)
            except tk.TclError:
                state['job'] = None

        container.bind('<Configure>', schedule_relayout, add='+')
        container.after_idle(relayout)

    def _build_merged_top_toolbar(self, parent):
        title = self.MERGED_TOP_CARD_TITLE or self.MODE_CARD_TITLE or self.DETECT_CARD_TITLE
        card = CardFrame(parent, title=title)
        card.pack(fill=tk.X, pady=(0, 10))
        inner = card.inner

        row1 = tk.Frame(inner, bg=COLORS['card_bg'])
        row1.pack(fill=tk.X)
        row1.grid_columnconfigure(1, weight=1)

        tk.Label(
            row1,
            text=self.MERGED_MODE_LABEL_TEXT,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).grid(row=0, column=0, sticky='nw', padx=(0, 14), pady=(2, 0))

        row1_body = tk.Frame(row1, bg=COLORS['card_bg'])
        row1_body.grid(row=0, column=1, sticky='ew')

        mode_panel = tk.Frame(row1_body, bg=COLORS['card_bg'])
        action_panel = tk.Frame(row1_body, bg=COLORS['card_bg'])
        self._populate_inline_mode_panel(mode_panel)

        action_buttons = tk.Frame(action_panel, bg=COLORS['card_bg'])
        action_buttons.pack(anchor='e')
        for text, style, command in self._get_primary_action_button_specs():
            self._create_header_button_widget(
                action_buttons,
                text,
                style,
                command,
                width=14,
                font=FONTS['body_bold'],
                padx=16,
                pady=10,
            ).pack(side=tk.LEFT, padx=(0, 8))
        self._create_header_button_widget(
            action_buttons,
            self.ACTION_BUTTON_TEXT,
            self.ACTION_BUTTON_STYLE,
            self._run_transform,
            width=10,
            font=FONTS['body_bold'],
            padx=16,
            pady=10,
        ).pack(side=tk.LEFT)
        if self.PROMPT_SCENE_ID and self.app_bridge:
            prompt_shell, _prompt_button = create_home_shell_button(
                action_buttons,
                '提示词',
                command=self._open_prompt_manager,
                style='secondary',
                width=10,
                padx=16,
                pady=10,
            )
            prompt_shell.pack(side=tk.LEFT, padx=(8, 0))
        bind_responsive_two_pane(
            row1_body,
            mode_panel,
            action_panel,
            breakpoint=max(self.TOP_SECTION_BREAKPOINT, 1320),
            gap=10,
            left_minsize=640,
        )

        if self.DETECT_SECTION_PLACEMENT == 'top':
            divider = tk.Frame(inner, bg=COLORS['card_border'], height=1)
            divider.pack(fill=tk.X, pady=(14, 12))
            divider.pack_propagate(False)

            row2 = tk.Frame(inner, bg=COLORS['card_bg'])
            row2.pack(fill=tk.X)
            row2.grid_rowconfigure(0, weight=1)
            row2.grid_columnconfigure(1, weight=1)

            detect_meta = tk.Frame(row2, bg=COLORS['card_bg'])
            detect_meta.grid(row=0, column=0, sticky='nsw', padx=(0, 14))

            tk.Label(
                detect_meta,
                text=self.MERGED_DETECT_LABEL_TEXT,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w', pady=(2, 0))

            detect_body = tk.Frame(row2, bg=COLORS['card_bg'])
            detect_body.grid(row=0, column=1, sticky='ew')

            detect_bar = ResponsiveButtonBar(detect_body, min_item_width=156, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
            detect_bar.pack(fill=tk.X)
            for text, style, command in self._get_detect_button_specs():
                detect_bar.add(
                    self._create_header_button_widget(
                        detect_bar,
                        text,
                        style,
                        command,
                        font=FONTS['body_bold'],
                        padx=14,
                        pady=9,
                    )
                )

            self.analysis_status_label = tk.Label(
                detect_meta,
                text='',
                font=FONTS['tiny'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
                wraplength=170,
            )
            self.analysis_status_label.pack(side=tk.BOTTOM, anchor='w')

        self.info_label = tk.Label(
            inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.info_label.pack(fill=tk.X, pady=(6, 0))
        bind_adaptive_wrap(self.info_label, inner, padding=12, min_width=220)

        self._refresh_mode_cards()
        self.frame.after_idle(self._refresh_mode_cards)

    def _build_mode_card(self, parent):
        card = self._create_mode_card(parent)
        card.pack(fill=tk.X, pady=(0, 10))
        return card

    def _create_mode_card(self, parent):
        card = CardFrame(parent, title=self.MODE_CARD_TITLE)
        inner = card.inner

        if self.MODE_CARD_HINT:
            hint = tk.Label(
                inner,
                text=self.MODE_CARD_HINT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            hint.pack(fill=tk.X)
            bind_adaptive_wrap(hint, inner, padding=12, min_width=220)

        layout = tk.Frame(inner, bg=COLORS['card_bg'])
        layout.pack(fill=tk.X, pady=(12 if self.MODE_CARD_HINT else 0, 0))

        if self.MODE_LAYOUT == 'inline_selector':
            self._build_inline_mode_selector(layout)
        else:
            self._build_stacked_mode_selector(layout)

        self._refresh_mode_cards()
        self.frame.after_idle(self._refresh_mode_cards)
        return card

    def _build_stacked_mode_selector(self, layout):
        mode_panel = tk.Frame(layout, bg=COLORS['card_bg'])
        action_panel = tk.Frame(layout, bg=COLORS['card_bg'])

        self.mode_var.trace_add('write', lambda *_args: self._refresh_mode_cards())

        mode_color = COLORS.get(self.MODE_COLOR_KEY, COLORS['primary'])
        for value, label, desc in self.MODE_OPTIONS:
            shell = tk.Frame(mode_panel, bg=COLORS['shadow'], bd=0, highlightthickness=0)
            shell.pack(fill=tk.X, pady=(0, 10))

            card_frame = tk.Frame(
                shell,
                bg=COLORS['surface_alt'],
                highlightbackground=COLORS['card_border'],
                highlightthickness=1,
                bd=0,
            )
            card_frame.pack(fill=tk.X, expand=True, padx=(0, 4), pady=(0, 4))

            radio = tk.Radiobutton(
                card_frame,
                text=label,
                variable=self.mode_var,
                value=value,
                font=FONTS['body_bold'],
                fg=mode_color,
                bg=COLORS['surface_alt'],
                selectcolor=COLORS['surface_alt'],
                activebackground=COLORS['surface_alt'],
                anchor='w',
                justify='left',
                padx=12,
                pady=8,
            )
            radio.pack(fill=tk.X)

            desc_label = tk.Label(
                card_frame,
                text=desc,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['surface_alt'],
                justify='left',
                anchor='w',
                padx=12,
            )
            desc_label.pack(fill=tk.X, pady=(0, 10))

            bind_adaptive_wrap(desc_label, card_frame, padding=28, min_width=220)
            self.mode_cards.append(
                {
                    'value': value,
                    'card_frame': card_frame,
                    'content_row': None,
                    'radio': radio,
                    'desc_label': desc_label,
                    'info_badge': None,
                }
            )

        action_shell = tk.Frame(
            action_panel,
            bg=COLORS['surface_alt'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        action_shell.pack(fill=tk.X, anchor='n')

        self._create_header_button_widget(
            action_shell,
            self.ACTION_BUTTON_TEXT,
            self.ACTION_BUTTON_STYLE,
            self._run_transform,
            font=FONTS['body_bold'],
            padx=20,
            pady=12,
        ).pack(fill=tk.X, padx=12, pady=(12, 10))

        if self.PROMPT_SCENE_ID and self.app_bridge:
            prompt_shell, _prompt_button = create_home_shell_button(
                action_shell,
                '提示词',
                command=self._open_prompt_manager,
                style='secondary',
                padx=20,
                pady=10,
            )
            prompt_shell.pack(fill=tk.X, padx=12, pady=(0, 10))

        if self.ACTION_TIP_TEXT:
            tip = tk.Label(
                action_shell,
                text=self.ACTION_TIP_TEXT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['surface_alt'],
                justify='left',
                anchor='w',
                padx=12,
            )
            tip.pack(fill=tk.X, pady=(0, 12))
            bind_adaptive_wrap(tip, action_shell, padding=24, min_width=220)

        bind_responsive_two_pane(layout, mode_panel, action_panel, breakpoint=1040, gap=12, left_minsize=480)

    def _build_inline_mode_selector(self, layout):
        toolbar_shell = tk.Frame(layout, bg=COLORS['card_bg'])
        toolbar_shell.pack(fill=tk.X)

        toolbar = tk.Frame(toolbar_shell, bg=COLORS['card_bg'])
        toolbar.pack(fill=tk.X)

        mode_panel = tk.Frame(toolbar, bg=COLORS['card_bg'])
        mode_panel.pack(side=tk.LEFT)
        action_panel = tk.Frame(toolbar, bg=COLORS['card_bg'])
        action_panel.pack(side=tk.RIGHT, padx=(self.MODE_INLINE_GROUP_GAP, self.MODE_INLINE_RIGHT_INSET))

        self._populate_inline_mode_panel(mode_panel)

        action_shell = tk.Frame(
            action_panel,
            bg=COLORS['shadow'],
            bd=0,
            highlightthickness=0,
            width=self.MODE_INLINE_ACTION_WIDTH,
            height=self.MODE_INLINE_ACTION_HEIGHT,
        )
        action_shell.pack(anchor='e')
        action_shell.pack_propagate(False)

        action_inner = tk.Frame(
            action_shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
            height=68,
        )
        action_inner.pack(fill=tk.BOTH, expand=True, padx=(0, 4), pady=(0, 4))
        action_inner.pack_propagate(False)

        ModernButton(
            action_inner,
            self.ACTION_BUTTON_TEXT,
            style=self.ACTION_BUTTON_STYLE,
            command=self._run_transform,
            padx=18,
            pady=10,
        ).pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        if self.ACTION_TIP_TEXT:
            tip = tk.Label(
                layout,
                text=self.ACTION_TIP_TEXT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            tip.pack(fill=tk.X, pady=(8, 0))
            bind_adaptive_wrap(tip, layout, padding=12, min_width=220)

    def _populate_inline_mode_panel(self, mode_panel):
        self.mode_var.trace_add('write', lambda *_args: self._refresh_mode_cards())

        for index, (value, label, desc) in enumerate(self.MODE_OPTIONS):
            mode_card = create_selector_card(
                mode_panel,
                variable=self.mode_var,
                value=value,
                label=label,
                tooltip_text=self._summarize_mode_tooltip(desc),
                accent_key=self.MODE_COLOR_KEY,
                width=self.MODE_INLINE_ITEM_WIDTH,
                height=self.MODE_INLINE_ITEM_HEIGHT,
            )
            mode_card['shell'].pack(
                side=tk.LEFT,
                padx=(0, self.MODE_INLINE_ITEM_GAP if index < len(self.MODE_OPTIONS) - 1 else 0),
            )
            mode_card['desc_label'] = None
            self.mode_cards.append(mode_card)

    @staticmethod
    def _summarize_mode_tooltip(desc):
        parts = [line.strip() for line in (desc or '').splitlines() if line.strip()]
        return parts[0] if parts else ''

    def _get_detect_button_specs(self):
        return (
            (self.PRIMARY_ANALYSIS_BUTTON_TEXT, self.PRIMARY_ANALYSIS_BUTTON_STYLE, self._run_primary_analysis),
            (self.SECONDARY_ANALYSIS_BUTTON_TEXT, 'ghost', self._run_secondary_analysis),
            ('敏感表达检查', 'warning', self._detect_sensitive),
            ('刷新差异视图', 'accent', self._refresh_diff_view),
        )

    def _get_primary_action_button_specs(self):
        return ()

    def _build_detect_section(self, parent):
        card = self._create_detect_card(parent)
        card.pack(fill=tk.X, pady=(0, 10))
        return card

    def _create_detect_card(self, parent):
        card = CardFrame(parent, title=self.DETECT_CARD_TITLE)
        self._build_detect_card(card.inner)
        return card

    def _create_compare_detect_panel(self, parent):
        panel_bg = self._blend_hex(COLORS['surface_alt'], COLORS['card_bg'], 0.12)
        border_color = self._blend_hex(COLORS['card_border'], panel_bg, 0.72)
        badge_bg = self._blend_hex(COLORS['accent'], panel_bg, 0.2)

        shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        body = tk.Frame(
            shell,
            bg=panel_bg,
            bd=0,
            highlightbackground=border_color,
            highlightthickness=1,
        )
        body.pack(fill=tk.BOTH, expand=True, padx=(0, 4), pady=(0, 4))

        header = tk.Frame(body, bg=panel_bg, cursor='hand2' if self.COMPARE_DETECT_COLLAPSIBLE else '')
        header.pack(fill=tk.X, padx=16, pady=(14, 0))

        tk.Label(
            header,
            text=self.COMPARE_DETECT_BADGE_TEXT,
            font=FONTS['tiny'],
            fg=COLORS['text_main'],
            bg=badge_bg,
            padx=8,
            pady=3,
            cursor='hand2' if self.COMPARE_DETECT_COLLAPSIBLE else '',
        ).pack(side=tk.LEFT)

        title = tk.Label(
            header,
            text=self.DETECT_CARD_TITLE,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=panel_bg,
            padx=10,
            cursor='hand2' if self.COMPARE_DETECT_COLLAPSIBLE else '',
        )
        title.pack(side=tk.LEFT)

        tk.Frame(header, bg=panel_bg).pack(side=tk.LEFT, fill=tk.X, expand=True)

        if self.COMPARE_DETECT_COLLAPSIBLE:
            collapsed_hint = tk.Label(
                header,
                text=self.COMPARE_DETECT_COLLAPSED_HINT,
                font=FONTS['small'],
                fg=COLORS['text_muted'],
                bg=panel_bg,
                cursor='hand2',
            )
            collapsed_hint.pack(side=tk.LEFT, padx=(0, 10))

            arrow = tk.Label(
                header,
                text='▶' if self.COMPARE_DETECT_DEFAULT_COLLAPSED else '▼',
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=panel_bg,
                cursor='hand2',
            )
            arrow.pack(side=tk.RIGHT)
            self._compare_detect_arrow = arrow
        else:
            collapsed_hint = None
            self._compare_detect_arrow = None

        content = tk.Frame(body, bg=panel_bg)
        self._compare_detect_body = content

        inner = tk.Frame(content, bg=panel_bg)
        inner.pack(fill=tk.X, padx=16, pady=(10, 16))

        if self.COMPARE_DETECT_HELP_TEXT:
            help_label = tk.Label(
                inner,
                text=self.COMPARE_DETECT_HELP_TEXT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=panel_bg,
                justify='left',
                anchor='w',
            )
            help_label.pack(fill=tk.X)
            bind_adaptive_wrap(help_label, inner, padding=16, min_width=220)

        self._build_detect_card(inner, bg=panel_bg, min_item_width=156)

        if self.COMPARE_DETECT_COLLAPSIBLE:
            def toggle(_event=None):
                self._set_compare_detect_expanded(not self._compare_detect_expanded)

            header.bind('<Button-1>', toggle, add='+')
            title.bind('<Button-1>', toggle, add='+')
            if collapsed_hint is not None:
                collapsed_hint.bind('<Button-1>', toggle, add='+')
            if self._compare_detect_arrow is not None:
                self._compare_detect_arrow.bind('<Button-1>', toggle, add='+')
            self._set_compare_detect_expanded(self._compare_detect_expanded)
        else:
            content.pack(fill=tk.X)

        return shell

    def _build_detect_card(self, parent, *, bg=None, min_item_width=170):
        bg_color = bg or COLORS['card_bg']
        if self.DETECT_CARD_HINT:
            tip = tk.Label(
                parent,
                text=self.DETECT_CARD_HINT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=bg_color,
                justify='left',
                anchor='w',
            )
            tip.pack(fill=tk.X)
            bind_adaptive_wrap(tip, parent, padding=12, min_width=220)

        btn_row = ResponsiveButtonBar(parent, min_item_width=min_item_width, gap_x=8, gap_y=8, bg=bg_color)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        for text, style, command in self._get_detect_button_specs():
            btn_row.add(
                self._create_header_button_widget(
                    btn_row,
                    text,
                    style,
                    command,
                    font=FONTS['body_bold'],
                    padx=12,
                    pady=8,
                )
            )

        if self.DETECT_RESULT_HINT:
            hint = tk.Label(
                parent,
                text=self.DETECT_RESULT_HINT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=bg_color,
                justify='left',
                anchor='w',
            )
            hint.pack(fill=tk.X, pady=(8, 0))
            bind_adaptive_wrap(hint, parent, padding=12, min_width=220)

        self.analysis_status_label = tk.Label(
            parent,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=bg_color,
            justify='left',
            anchor='w',
        )
        self.analysis_status_label.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(self.analysis_status_label, parent, padding=12, min_width=220)

    def _build_input_output_section(self, parent):
        body = tk.Frame(parent, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left_card = CardFrame(body, title=self.INPUT_CARD_TITLE)
        self._input_card = left_card
        self._build_input_card_title_meta(left_card)
        input_frame, self.input_text = create_scrolled_text(left_card.inner, height=20)
        input_frame.pack(fill=tk.BOTH, expand=True)
        self._register_editable_text(self.input_text, self.INPUT_PLACEHOLDER)
        self._bind_input_context_menu()

        right_card = CardFrame(body, title=None if self.SHOW_OUTPUT_HEADER_REPLACE_ACTION else self.OUTPUT_CARD_TITLE)
        if self.SHOW_OUTPUT_HEADER_REPLACE_ACTION:
            self._build_output_card_header(right_card.inner)
        output_frame, self.output_text = create_scrolled_text(right_card.inner, height=20)
        output_frame.pack(fill=tk.BOTH, expand=True, pady=(8 if self.SHOW_OUTPUT_HEADER_REPLACE_ACTION else 0, 0))
        self._register_editable_text(self.output_text, self.OUTPUT_PLACEHOLDER)

        bind_responsive_two_pane(body, left_card, right_card, breakpoint=1180, gap=8, left_minsize=360)

    def _build_input_card_title_meta(self, card):
        if not getattr(card, 'title_frame', None):
            return
        self.input_source_label = tk.Label(
            card.title_frame,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='right',
            anchor='e',
        )
        self.input_source_label.grid(row=0, column=1, sticky='e', padx=(12, 0))
        bind_ellipsis_tooltip(
            self.input_source_label,
            padding=4,
            wraplength=360,
            tooltip_style=self._get_page_tooltip_style(),
        )
        self._create_header_button_widget(
            card.title_frame,
            self.INPUT_RESET_BUTTON_TEXT,
            'ghost',
            self._reset_input_area,
            font=FONTS['small'],
            padx=12,
            pady=5,
        ).grid(row=0, column=2, sticky='e', padx=(8, 0))
        self._update_input_source_meta()

    def _update_input_source_meta(self):
        if self.input_source_label is None:
            return
        text = (self.current_source_desc or '').strip()
        if self.current_source_kind == 'manual' and text == '手动输入内容':
            text = ''
        set_ellipsized_label_text(self.input_source_label, text)

    def _update_input_card_title(self):
        if not self._input_card or not getattr(self._input_card, 'title_label', None):
            return
        title = self.INPUT_CARD_IMPORTED_TITLE if self.import_session else self.INPUT_CARD_TITLE
        self._input_card.title_label.configure(text=title)

    @staticmethod
    def _is_redundant_source_info_text(text):
        value = (text or '').strip()
        if not value or '已接收' not in value:
            return False
        if '论文写作页' not in value and '论文写作页面' not in value:
            return False
        return '发送内容' in value or '主动发送' in value

    def _sanitize_info_text(self, text):
        value = (text or '').strip()
        if self._is_redundant_source_info_text(value):
            return ''
        return value

    def _build_output_card_header(self, parent):
        header = tk.Frame(parent, bg=COLORS['card_bg'])
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text=self.OUTPUT_CARD_TITLE,
            font=FONTS['heading'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)

        ModernButton(
            header,
            self.REPLACE_BUTTON_TEXT,
            style='ghost',
            command=self._replace,
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)

    def _get_preview_card_header_button_specs(self):
        return ()

    def _get_analysis_summary_title_button_specs(self):
        return ()

    def _get_preview_title_tooltip_spec(self):
        return None

    def _get_preview_title_button_specs(self):
        return ()

    def _get_page_tooltip_style(self):
        return 'theme'

    def _create_header_button_widget(self, parent, text, style, command, *, font, padx, pady, width=None):
        if style in {'primary', 'primary_fixed'}:
            return create_home_shell_button(
                parent,
                text,
                command=command,
                style=style,
                font=font,
                padx=padx,
                pady=pady,
                width=width,
                border_color=THEMES['light']['card_border'] if style == 'primary_fixed' else None,
            )[0]
        return ModernButton(
            parent,
            text,
            style=style,
            command=command,
            font=font,
            padx=padx,
            pady=pady,
            width=width,
        )

    def _build_header_action_row(self, parent, specs, *, bg):
        specs = tuple(specs or ())
        if not specs:
            return None

        action_row = tk.Frame(parent, bg=bg)
        for index, (text, style, command) in enumerate(specs):
            self._create_header_button_widget(
                action_row,
                text,
                style,
                command,
                font=FONTS['small'],
                padx=12,
                pady=5,
            ).pack(side=tk.LEFT, padx=(8 if index else 0, 0))
        return action_row

    def _build_preview_card_title_meta(self, card):
        if not getattr(card, 'title_frame', None):
            return

        action_row = self._build_header_action_row(
            card.title_frame,
            self._get_preview_card_header_button_specs(),
            bg=COLORS['card_bg'],
        )
        if action_row is not None:
            action_row.grid(row=0, column=1, sticky='e')

    def _build_compare_preview_section(self, parent):
        if not self.SHOW_COMPARE_SECTION:
            return

        if self.COMPARE_SECTION_COLLAPSIBLE:
            section_card = CardFrame(parent)
            section_card.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
            inner = section_card.inner

            header = tk.Frame(inner, bg=COLORS['card_bg'], cursor='hand2')
            header.pack(fill=tk.X)

            arrow = tk.Label(
                header,
                text='▶' if self.COMPARE_SECTION_DEFAULT_COLLAPSED else '▼',
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                cursor='hand2',
            )
            arrow.pack(side=tk.LEFT, padx=(0, 8))

            title = tk.Label(
                header,
                text=self.COMPARE_SECTION_TITLE,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                cursor='hand2',
            )
            title.pack(side=tk.LEFT)

            if self.COMPARE_SECTION_DESCRIPTION:
                desc = tk.Label(
                    inner,
                    text=self.COMPARE_SECTION_DESCRIPTION,
                    font=FONTS['small'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    justify='left',
                    anchor='w',
                )
                desc.pack(fill=tk.X, pady=(8, 0))
                bind_adaptive_wrap(desc, inner, padding=12, min_width=220)

            body = tk.Frame(inner, bg=COLORS['card_bg'])
            self._build_compare_preview_content(body)
            self._compare_section_body = body
            self._compare_section_arrow = arrow

            def toggle(_event=None):
                if body.winfo_manager():
                    body.pack_forget()
                    arrow.configure(text='▶')
                else:
                    body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
                    arrow.configure(text='▼')

            header.bind('<Button-1>', toggle, add='+')
            arrow.bind('<Button-1>', toggle, add='+')
            title.bind('<Button-1>', toggle, add='+')

            if not self.COMPARE_SECTION_DEFAULT_COLLAPSED:
                body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
            return

        section_card = CardFrame(parent, title=self.COMPARE_SECTION_TITLE)
        section_card.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        if self.COMPARE_SECTION_DESCRIPTION:
            desc = tk.Label(
                section_card.inner,
                text=self.COMPARE_SECTION_DESCRIPTION,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            desc.pack(fill=tk.X)
            bind_adaptive_wrap(desc, section_card.inner, padding=12, min_width=220)

        content = tk.Frame(section_card.inner, bg=COLORS['card_bg'])
        content.pack(fill=tk.BOTH, expand=True, pady=(8 if self.COMPARE_SECTION_DESCRIPTION else 0, 0))
        self._build_compare_preview_content(content)

    def _set_compare_section_expanded(self, expanded):
        if not self.COMPARE_SECTION_COLLAPSIBLE:
            return

        body = self._compare_section_body
        arrow = self._compare_section_arrow
        expanded = bool(expanded)
        self._compare_section_expanded = expanded
        if body is None or arrow is None:
            return

        if expanded:
            if not body.winfo_manager():
                body.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
            arrow.configure(text='▼')
            return

        if body.winfo_manager():
            body.pack_forget()
        arrow.configure(text='▶')

    def _set_compare_detect_expanded(self, expanded):
        if not self.COMPARE_DETECT_COLLAPSIBLE:
            return

        body = self._compare_detect_body
        arrow = self._compare_detect_arrow
        expanded = bool(expanded)
        self._compare_detect_expanded = expanded
        if body is None or arrow is None:
            return

        if expanded:
            if not body.winfo_manager():
                body.pack(fill=tk.X)
            arrow.configure(text='▼')
            return

        if body.winfo_manager():
            body.pack_forget()
        arrow.configure(text='▶')

    def _build_compare_preview_content(self, parent):
        if self.DETECT_SECTION_PLACEMENT == 'compare':
            detect_card = self._create_compare_detect_panel(parent)
            detect_card.pack(fill=tk.X, pady=(0, 10))

        content = tk.Frame(parent, bg=parent.cget('bg'))
        content.pack(fill=tk.BOTH, expand=True)
        self._build_compare_preview_cards(content)

    def _build_compare_preview_cards(self, parent):
        compare_card = CardFrame(parent, title=self.COMPARE_CARD_TITLE)
        self._build_compare_card(compare_card.inner)

        preview_card = CardFrame(parent, title=self.PREVIEW_CARD_TITLE)
        self._build_preview_card_title_meta(preview_card)
        self._build_preview_card(preview_card.inner)

        bind_responsive_two_pane(parent, compare_card, preview_card, breakpoint=1240, gap=8, left_minsize=420)

    def _build_section_heading(self, parent, text, *, pady=(0, 0), button_specs=(), tooltip_spec=None):
        header = tk.Frame(parent, bg=COLORS['card_bg'])
        header.pack(fill=tk.X, pady=pady)

        title_group = tk.Frame(header, bg=COLORS['card_bg'])
        title_group.pack(side=tk.LEFT)
        label = tk.Label(
            title_group,
            text=text,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        )
        label.pack(side=tk.LEFT)

        tooltip = tooltip_spec or {}
        tooltip_text = (tooltip.get('text') or '').strip()
        tooltip_path = tooltip.get('image_path') or ''
        if tooltip_text:
            icon_widget = None
            if tooltip_path:
                try:
                    icon_image = load_image(tooltip_path, max_size=tooltip.get('max_size', (16, 16)))
                    icon_widget = tk.Label(
                        title_group,
                        image=icon_image,
                        bg=COLORS['card_bg'],
                        cursor='hand2',
                    )
                    icon_widget.image = icon_image
                except Exception:
                    icon_widget = None
            if icon_widget is None:
                icon_widget = tk.Label(
                    title_group,
                    text='?',
                    font=FONTS['small'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['card_bg'],
                    cursor='hand2',
                )
            icon_widget.pack(side=tk.LEFT, padx=(8, 0))
            show_tooltip(
                icon_widget,
                tooltip_text,
                placement='top_center',
                y_offset=8,
                wraplength=260,
                tooltip_style=self._get_page_tooltip_style(),
            )

        action_row = self._build_header_action_row(header, button_specs, bg=COLORS['card_bg'])
        if action_row is not None:
            action_row.pack(side=tk.RIGHT)
        return label

    def _build_compare_card(self, parent):
        self._build_compare_editor(
            parent,
            hint_text=self.COMPARE_CARD_HINT,
            placeholder=self.COMPARE_PLACEHOLDER,
            height=self.COMPARE_TEXT_HEIGHT,
        )

    def _build_compare_editor(self, parent, *, hint_text='', placeholder='', height=16):
        if hint_text:
            hint = tk.Label(
                parent,
                text=hint_text,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            hint.pack(fill=tk.X)
            bind_adaptive_wrap(hint, parent, padding=12, min_width=220)

        compare_frame, widget = create_scrolled_text(parent, height=height)
        compare_frame.pack(fill=tk.BOTH, expand=True, pady=(8 if hint_text else 0, 0))
        self._register_compare_widget(widget, placeholder)
        return widget

    def _build_preview_legend(self, parent):
        legend = tk.Frame(parent, bg=COLORS['surface_alt'], highlightbackground=COLORS['card_border'], highlightthickness=1)
        legend.pack(fill=tk.X, pady=(0, 8))
        legend_items = self._get_preview_legend_items()
        if legend_items:
            legend_bar = tk.Frame(legend, bg=COLORS['surface_alt'])
            legend_bar.pack(fill=tk.X, padx=10, pady=8)
            for index, (sample_text, meaning_text, tone) in enumerate(legend_items):
                item = tk.Frame(legend_bar, bg=COLORS['surface_alt'])
                sample_bg, sample_fg = self._resolve_preview_legend_colors(tone)
                tk.Label(
                    item,
                    text=sample_text,
                    font=FONTS['small'],
                    fg=sample_fg,
                    bg=sample_bg,
                    padx=10,
                    pady=4,
                ).pack(side=tk.LEFT)
                tk.Label(
                    item,
                    text=meaning_text,
                    font=FONTS['small'],
                    fg=COLORS['text_sub'],
                    bg=COLORS['surface_alt'],
                    padx=8,
                ).pack(side=tk.LEFT)
                item.pack(side=tk.LEFT, padx=(0, 18 if index < len(legend_items) - 1 else 0))
        else:
            tk.Label(
                legend,
                text=self.PREVIEW_LEGEND_TEXT,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['surface_alt'],
                justify='left',
                anchor='w',
                padx=10,
                pady=8,
            ).pack(fill=tk.X)

    def _build_analysis_status(self, parent, *, pady=(0, 8)):
        if self.analysis_status_label is None:
            self.analysis_status_label = tk.Label(
                parent,
                text='',
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            bind_adaptive_wrap(self.analysis_status_label, parent, padding=12, min_width=220)
        self.analysis_status_label.pack(fill=tk.X, pady=pady)
        return self.analysis_status_label

    def _build_analysis_summary_section(
        self,
        parent,
        *,
        title=None,
        title_pady=(0, 0),
        frame_pady=(8, 8),
        height=8,
        fill=tk.X,
        expand=False,
    ):
        if title:
            self._build_section_heading(
                parent,
                title,
                pady=title_pady,
                button_specs=self._get_analysis_summary_title_button_specs(),
            )
        summary_frame, self.analysis_text = create_scrolled_text(parent, height=height)
        summary_frame.pack(fill=fill, expand=expand, pady=frame_pady)
        self.analysis_text.configure(state=tk.DISABLED, cursor='arrow')
        return summary_frame

    def _build_diff_preview_section(self, parent):
        self._build_section_heading(
            parent,
            self.PREVIEW_TITLE,
            button_specs=self._get_preview_title_button_specs(),
            tooltip_spec=self._get_preview_title_tooltip_spec(),
        )
        preview_frame, self.preview_text = create_scrolled_text(parent, height=16)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.preview_text.configure(state=tk.DISABLED, cursor='arrow')
        self.preview_text.tag_configure('diff_insert', foreground=COLORS['success'])
        self.preview_text.tag_configure('diff_delete', foreground=COLORS['error'], overstrike=1)
        self.preview_text.tag_configure('diff_equal', foreground=COLORS['text_muted'])
        return preview_frame

    def _build_preview_card(self, parent):
        self._build_preview_legend(parent)
        self._build_analysis_status(parent)
        self._build_analysis_summary_section(parent, title=self.SUMMARY_TITLE)
        self._build_diff_preview_section(parent)

    def _get_preview_legend_items(self):
        return self.PREVIEW_LEGEND_ITEMS

    @staticmethod
    def _blend_hex(color, target='#FFFFFF', ratio=0.0):
        ratio = max(0.0, min(1.0, ratio))
        source = color.lstrip('#')
        target = target.lstrip('#')
        if len(source) != 6 or len(target) != 6:
            return color

        def parts(value):
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

        r1, g1, b1 = parts(source)
        r2, g2, b2 = parts(target)
        mixed = (
            round(r1 + (r2 - r1) * ratio),
            round(g1 + (g2 - g1) * ratio),
            round(b1 + (b2 - b1) * ratio),
        )
        return '#{:02X}{:02X}{:02X}'.format(*mixed)

    def _resolve_preview_legend_colors(self, tone):
        if tone == 'success':
            return self._blend_hex(COLORS['success'], ratio=0.18), '#15161A'
        if tone == 'error':
            return self._blend_hex(COLORS['error'], ratio=0.08), '#15161A'
        return self._blend_hex(COLORS['text_muted'], ratio=0.62), '#15161A'

    def _build_replace_row(self, parent):
        if self.TOP_SECTION_LAYOUT == 'merged_toolbar':
            return

        replace_row = tk.Frame(parent, bg=COLORS['bg_main'])
        replace_row.pack(fill=tk.X, pady=(8, 0))

        ModernButton(replace_row, self.REPLACE_BUTTON_TEXT, style='ghost', command=self._replace).pack(anchor='w')

        self.info_label = tk.Label(
            replace_row,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['bg_main'],
            justify='left',
            anchor='w',
        )
        self.info_label.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(self.info_label, replace_row, padding=12, min_width=220)

    def _refresh_mode_cards(self):
        selected = self.mode_var.get()
        mode_color = COLORS.get(self.MODE_COLOR_KEY, COLORS['primary'])

        for card in self.mode_cards:
            value = card['value']
            if 'shell' in card and 'accent_strip' in card:
                style_selector_card(card, selected=value == selected)
                continue
            card_frame = card['card_frame']
            content_row = card.get('content_row')
            radio = card['radio']
            desc_label = card['desc_label']
            info_badge = card['info_badge']
            is_selected = value == selected
            bg = COLORS['accent_light'] if is_selected else COLORS['surface_alt']
            title_color = mode_color if is_selected else COLORS['text_main']
            desc_color = COLORS['text_main'] if is_selected else COLORS['text_sub']
            border = mode_color if is_selected else COLORS['card_border']

            card_frame.configure(bg=bg, highlightbackground=border)
            if content_row is not None:
                content_row.configure(bg=bg)
            radio.configure(
                bg=bg,
                fg=title_color,
                activebackground=bg,
                selectcolor=bg,
                highlightbackground=bg,
            )
            if desc_label is not None:
                desc_label.configure(bg=bg, fg=desc_color)
            if info_badge is not None:
                info_badge.configure(bg=bg, fg=title_color if is_selected else COLORS['text_sub'])

    def _register_editable_text(self, widget, placeholder=''):
        if not placeholder:
            return

        self._placeholder_state[widget] = {'text': placeholder, 'active': False}
        widget.bind('<FocusIn>', lambda _event, current=widget: self._clear_placeholder(current), add='+')
        widget.bind('<FocusOut>', lambda _event, current=widget: self._restore_placeholder(current), add='+')
        self._restore_placeholder(widget)

    def _register_compare_widget(self, widget, placeholder=''):
        if self.compare_text is None:
            self.compare_text = widget
        self.compare_widgets.append(widget)
        self._register_editable_text(widget, placeholder)

        widget.bind('<KeyRelease>', lambda _event, current=widget: self._sync_compare_widgets(current), add='+')
        widget.bind('<<Paste>>', lambda _event, current=widget: self.frame.after_idle(lambda: self._sync_compare_widgets(current)), add='+')
        widget.bind('<<Cut>>', lambda _event, current=widget: self.frame.after_idle(lambda: self._sync_compare_widgets(current)), add='+')

    def _restore_placeholder(self, widget):
        state = self._placeholder_state.get(widget)
        if not state or state['active']:
            return

        content = widget.get('1.0', tk.END).strip()
        if content:
            widget.configure(fg=COLORS['text_main'])
            return

        widget.delete('1.0', tk.END)
        widget.insert('1.0', state['text'])
        widget.configure(fg=COLORS['text_muted'])
        state['active'] = True

    def _clear_placeholder(self, widget):
        state = self._placeholder_state.get(widget)
        if not state or not state['active']:
            return

        widget.delete('1.0', tk.END)
        widget.configure(fg=COLORS['text_main'])
        state['active'] = False

    def _get_text_value(self, widget):
        state = self._placeholder_state.get(widget)
        if state and state['active']:
            return ''
        return normalize_block_text(widget.get('1.0', tk.END))

    def _set_text_value(self, widget, text):
        normalized = normalize_block_text(text)
        state = self._placeholder_state.get(widget)
        if state:
            state['active'] = False
        widget.configure(fg=COLORS['text_main'])
        widget.delete('1.0', tk.END)
        if normalized:
            widget.insert('1.0', normalized)
        elif state:
            self._restore_placeholder(widget)
        if widget is self.input_text:
            self.frame.after_idle(self._schedule_annotation_layout)
        self._schedule_workspace_state_save()

    def _sync_compare_widgets(self, origin):
        if self._compare_syncing or len(self.compare_widgets) < 2:
            return

        value = self._get_text_value(origin)
        self._compare_syncing = True
        try:
            for widget in self.compare_widgets:
                if widget is origin:
                    continue
                self._set_text_value(widget, value)
        finally:
            self._compare_syncing = False

    def _bind_text_watchers(self):
        for widget in [self.input_text, self.output_text, *self.compare_widgets]:
            if widget is None:
                continue
            widget.bind('<KeyRelease>', self._on_text_change, add='+')
            widget.bind('<<Paste>>', lambda _event: self.frame.after_idle(self._on_text_change), add='+')
            widget.bind('<<Cut>>', lambda _event: self.frame.after_idle(self._on_text_change), add='+')
        if self.input_text is not None:
            for sequence in ('<Configure>', '<MouseWheel>', '<Button-4>', '<Button-5>', '<ButtonRelease-1>'):
                self.input_text.bind(sequence, lambda _event: self._schedule_annotation_layout(delay_ms=24), add='+')

    def _bind_workspace_state_watchers(self):
        self.mode_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        for widget in [self.input_text, self.output_text, *self.compare_widgets]:
            if widget is None:
                continue
            widget.bind('<KeyRelease>', self._schedule_workspace_state_save, add='+')
            widget.bind('<<Paste>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')
            widget.bind('<<Cut>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')

    # -- 右键段落标记 --

    def _bind_input_context_menu(self):
        if self.input_text is None:
            return
        self.input_text.bind('<Button-3>', self._show_input_context_menu)

    def _show_input_context_menu(self, event):
        try:
            sel_start = self.input_text.index(tk.SEL_FIRST)
            sel_end = self.input_text.index(tk.SEL_LAST)
        except tk.TclError:
            return 'break'
        if not sel_start or not sel_end:
            return 'break'

        menu = tk.Menu(self.frame, tearoff=0)
        annotation_menu = tk.Menu(menu, tearoff=0)
        for risk_key, risk_label in self.ANNOTATION_RISK_LABELS.items():
            annotation_menu.add_command(
                label=risk_label,
                command=lambda r=risk_key: self._create_manual_annotation(r),
            )
        menu.add_cascade(label='段落标记', menu=annotation_menu)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    def _create_manual_annotation(self, risk_level):
        try:
            sel_start = self.input_text.index(tk.SEL_FIRST)
            sel_end = self.input_text.index(tk.SEL_LAST)
        except tk.TclError:
            return

        start_offset = self._tk_index_to_char_offset(sel_start)
        end_offset = self._tk_index_to_char_offset(sel_end)
        if end_offset <= start_offset:
            return

        for existing in self._get_all_annotations():
            if self._annotations_overlap(start_offset, end_offset, existing.start, existing.end):
                messagebox.showwarning('提示', '选中区域与已有标注重叠，请调整选择范围。', parent=self.frame)
                return

        paragraph_id = self._next_manual_paragraph_id()
        if not self.manual_annotation_base_text:
            self.manual_annotation_base_text = self._get_input_text()

        selected_text = self.input_text.get(sel_start, sel_end).strip()[:80]
        source_color_map = {
            'high': 'red',
            'medium': 'orange',
            'low': 'purple',
            'safe': 'black',
        }

        annotation = ParagraphAnnotation(
            paragraph_id=paragraph_id,
            section_path='',
            start=start_offset,
            end=end_offset,
            risk_level=risk_level,
            ai_score=None,
            repeat_score=None,
            duplicate_status='none',
            source_color=source_color_map.get(risk_level, 'unknown'),
            include_in_run=(risk_level != 'safe'),
            source_excerpt=selected_text,
            is_auto_generated=False,
            is_user_modified=False,
        )

        self.manual_annotations.append(annotation)
        self.manual_annotations.sort(key=lambda a: (a.start, a.end, a.paragraph_id))
        self._render_import_annotations()
        self._schedule_workspace_state_save()

    def _tk_index_to_char_offset(self, index):
        try:
            resolved = self.input_text.index(index)
        except tk.TclError:
            return -1
        text_before = self.input_text.get('1.0', resolved)
        return len(text_before)

    @staticmethod
    def _annotations_overlap(start1, end1, start2, end2):
        return start1 < end2 and start2 < end1

    def _next_manual_paragraph_id(self):
        max_num = 0
        for a in self.manual_annotations:
            if a.paragraph_id.startswith('manual-'):
                try:
                    num = int(a.paragraph_id.split('-', 1)[1])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        return f'manual-{max_num + 1}'

    def _get_all_annotations(self):
        report = self._get_import_annotations() if self.import_session else []
        manual = list(self.manual_annotations or [])
        return report + manual

    def _find_annotation_by_id(self, paragraph_id):
        for annotation in self._get_all_annotations():
            if annotation.paragraph_id == paragraph_id:
                return annotation
        return None

    @staticmethod
    def _get_widget_text(widget):
        if widget is None:
            return ''
        return widget.get('1.0', tk.END).strip()

    def export_workspace_state(self):
        return {
            'mode': self.mode_var.get(),
            'input_text': self._get_input_text(),
            'output_text': self._get_output_text(),
            'compare_text': self._get_compare_text(),
            'analysis_text': self._get_widget_text(self.analysis_text),
            'preview_text': self._get_widget_text(self.preview_text),
            'analysis_status_text': self.analysis_status_label.cget('text') if self.analysis_status_label else '',
            'analysis_status_color': self.analysis_status_label.cget('fg') if self.analysis_status_label else '',
            'info_text': self._sanitize_info_text(self.info_label.cget('text') if self.info_label else ''),
            'compare_section_expanded': self._compare_section_expanded,
            'compare_detect_expanded': self._compare_detect_expanded,
            'current_source_kind': self.current_source_kind,
            'current_source_desc': self.current_source_desc,
            'current_paper_title': self.current_paper_title,
            'import_session': self.import_session.to_dict() if self.import_session else None,
            'annotations': [item.to_dict() for item in self._get_import_annotations()],
            'annotation_overrides': dict(self.annotation_overrides),
            'selected_annotation_id': self.selected_annotation_id,
            'manual_annotations': [item.to_dict() for item in self.manual_annotations],
            'manual_annotation_base_text': self.manual_annotation_base_text,
        }

    def restore_workspace_state(self, state):
        if not isinstance(state, dict):
            return

        mode = state.get('mode', '')
        valid_modes = {value for value, *_rest in self.MODE_OPTIONS}
        if mode in valid_modes:
            self.mode_var.set(mode)

        self._set_input_text(
            state.get('input_text', ''),
            state.get('current_source_kind', 'manual'),
            self._normalize_source_desc(state.get('current_source_desc', '')),
            paper_title=state.get('current_paper_title', ''),
            fingerprint=None,
        )
        self._set_text_value(self.output_text, state.get('output_text', ''))

        compare_text = state.get('compare_text', '')
        for widget in self.compare_widgets:
            self._set_text_value(widget, compare_text)

        analysis_text = state.get('analysis_text', '')
        preview_text = state.get('preview_text', '')
        status_text = state.get('analysis_status_text', '')
        status_color = state.get('analysis_status_color') or COLORS['text_sub']

        if analysis_text:
            self._set_readonly_text(self.analysis_text, analysis_text)
        if preview_text:
            self._set_readonly_text(self.preview_text, preview_text, tag='diff_equal')
        if status_text:
            self._set_analysis_status(status_text, status_color)

        if self.info_label is not None:
            self.info_label.configure(text=self._sanitize_info_text(state.get('info_text', '')))

        if self.COMPARE_SECTION_COLLAPSIBLE:
            self._set_compare_section_expanded(state.get('compare_section_expanded', self._compare_section_expanded))
        if self.COMPARE_DETECT_COLLAPSIBLE:
            self._set_compare_detect_expanded(state.get('compare_detect_expanded', self._compare_detect_expanded))

        session_payload = state.get('import_session')
        self.import_session = ImportSession.from_dict(session_payload) if session_payload else None
        self.annotation_overrides = dict(state.get('annotation_overrides', {}) or {})
        self.selected_annotation_id = str(state.get('selected_annotation_id', '') or '')
        if self.import_session:
            restored_annotations = []
            for item in state.get('annotations', []):
                annotation = ParagraphAnnotation.from_dict(item)
                if annotation is not None:
                    restored_annotations.append(annotation)
            if restored_annotations:
                self.import_session.annotations = restored_annotations

        self.manual_annotations = []
        self.manual_annotation_base_text = str(state.get('manual_annotation_base_text', '') or '')
        for item in state.get('manual_annotations', []):
            annotation = ParagraphAnnotation.from_dict(item)
            if annotation is not None:
                self.manual_annotations.append(annotation)
        self.manual_annotations.sort(key=lambda a: (a.start, a.end, a.paragraph_id))

        self._update_input_card_title()
        self.frame.after_idle(self._render_import_annotations)
        self._refresh_mode_cards()

    def _on_text_change(self, _event=None):
        self._mark_analysis_stale(self.STALE_ANALYSIS_TEXT)
        session_cleared = False
        if (
            self.import_session
            and not self._suppress_import_session_clear
            and self._get_input_text() != self.import_session.original_text
        ):
            self._clear_import_session('原文区正文已修改，原报告标注已清除，请重新导入报告。')
            session_cleared = True
        if (
            self.manual_annotations
            and self._get_input_text() != self.manual_annotation_base_text
        ):
            self.manual_annotations = []
            self.manual_annotation_base_text = ''
            session_cleared = True
        if session_cleared and self.manual_annotations:
            self._render_import_annotations()
        self._schedule_annotation_layout()

    def _get_input_text(self):
        return self._get_text_value(self.input_text)

    def _set_input_text(self, text, source_kind='manual', source_desc='', *, paper_title=None, fingerprint=None):
        self._set_text_value(self.input_text, text)
        self.current_source_kind = source_kind or 'manual'
        self.current_source_desc = self._normalize_source_desc(source_desc)
        if paper_title is not None:
            self.current_paper_title = str(paper_title or '').strip()
        self._last_bridge_fingerprint = fingerprint
        self._update_input_source_meta()
        self._update_input_card_title()
        if self.info_label is not None:
            self.info_label.configure(text=self._sanitize_info_text(self.info_label.cget('text')))
        self._schedule_workspace_state_save()

    @classmethod
    def _normalize_source_desc(cls, text):
        value = str(text or '').strip()
        if not value:
            return ''
        for broken_prefix, expected_prefix in cls._BROKEN_SOURCE_DESC_PREFIXES:
            if not value.startswith(broken_prefix):
                continue
            suffix = value[len(broken_prefix):]
            if suffix.startswith('?'):
                suffix = suffix[1:]
            return f'{expected_prefix}{suffix}'
        return value

    def _get_import_annotations(self):
        if not self.import_session:
            return []
        return list(self.import_session.annotations or [])

    def _set_import_annotations(self, annotations):
        if not self.import_session:
            return
        self.import_session.annotations = sorted(
            [item for item in annotations if isinstance(item, ParagraphAnnotation)],
            key=lambda item: (item.start, item.end, item.paragraph_id),
        )

    def _apply_import_session(self, session, *, info_text=''):
        self.import_session = session
        self.annotation_overrides = {}
        self.selected_annotation_id = ''
        self.manual_annotations = []
        self.manual_annotation_base_text = ''
        self._update_input_card_title()
        self._render_import_annotations()
        if info_text and self.info_label is not None:
            self.info_label.configure(text=info_text, fg=COLORS['text_muted'])
        self._schedule_workspace_state_save()

    def _rebase_import_session_to(self, new_text):
        """将现有报告标注按段落 ID 对齐到新原文，已改写的段落标记为安全跳过。

        段落数量不一致时返回 False，由调用方决定是否清除会话。"""
        if not self.import_session:
            return False
        try:
            new_paragraphs = split_document_paragraphs(new_text)
            old_paragraphs = split_document_paragraphs(self.import_session.original_text)
        except Exception:
            return False
        if len(new_paragraphs) != len(old_paragraphs):
            return False

        old_index = {item.paragraph_id: item for item in old_paragraphs}
        annotation_index = {item.paragraph_id: item for item in self._get_import_annotations()}
        rebuilt = []
        for paragraph in new_paragraphs:
            annotation = annotation_index.get(paragraph.paragraph_id)
            if annotation is None:
                continue
            old_paragraph = old_index.get(paragraph.paragraph_id)
            text_changed = old_paragraph is None or old_paragraph.text != paragraph.text
            updated = ParagraphAnnotation.from_dict(annotation.to_dict())
            updated.start = paragraph.start
            updated.end = paragraph.end
            updated.section_path = paragraph.section_path
            if text_changed:
                updated.risk_level = 'safe'
                updated.include_in_run = False
                updated.ai_score = None
                updated.repeat_score = None
                updated.duplicate_status = 'safe'
                updated.source_color = 'gray'
                updated.is_user_modified = True
                updated.source_excerpt = paragraph.text.strip()[:80]
                self.annotation_overrides[paragraph.paragraph_id] = {
                    'risk_level': 'safe',
                    'include_in_run': False,
                    'ai_score': None,
                    'repeat_score': None,
                    'duplicate_status': 'safe',
                    'is_user_modified': True,
                }
            rebuilt.append(updated)

        self.import_session.original_text = normalize_block_text(new_text)
        self._set_import_annotations(rebuilt)
        if self.manual_annotations:
            self.manual_annotation_base_text = normalize_block_text(new_text)
        self._render_import_annotations()
        self._schedule_workspace_state_save()
        return True

    def _clear_import_session(self, info_text=''):
        self.import_session = None
        self.annotation_overrides = {}
        self.selected_annotation_id = ''
        self._clear_annotation_visuals()
        self._close_annotation_editor()
        self._update_input_card_title()
        if self.manual_annotations and self._get_input_text() == self.manual_annotation_base_text:
            for annotation in self.manual_annotations:
                if not self._should_render_annotation(annotation):
                    continue
                self._render_single_annotation(annotation)
            self._schedule_annotation_layout()
        if info_text and self.info_label is not None:
            self.info_label.configure(text=info_text, fg=COLORS['warning'])
        self._schedule_workspace_state_save()

    def _clear_annotation_visuals(self):
        if self.input_text is not None:
            for tag_name in list(self._annotation_tag_names):
                try:
                    self.input_text.tag_delete(tag_name)
                except tk.TclError:
                    pass
        self._annotation_tag_names.clear()
        for badge in list(self._annotation_badges.values()):
            try:
                badge.destroy()
            except tk.TclError:
                pass
        self._annotation_badges = {}

    @classmethod
    def _normalize_annotation_source_color(cls, value):
        alias_map = {
            '': 'unknown',
            'unknown': 'unknown',
            'none': 'unknown',
            'red': 'red',
            'orange': 'orange',
            'purple': 'purple',
            'violet': 'purple',
            'pink': 'purple',
            'magenta': 'purple',
            'black': 'black',
            'gray': 'gray',
            'grey': 'gray',
            '红色': 'red',
            '橙色': 'orange',
            '橘色': 'orange',
            '紫色': 'purple',
            '黑色': 'black',
            '灰色': 'gray',
        }
        current = str(value or 'unknown').strip().lower()
        return alias_map.get(current, alias_map.get(str(value or '').strip(), 'unknown'))

    @classmethod
    def _format_source_color_label(cls, source_color):
        label_map = {
            'red': '红色',
            'orange': '橙色',
            'purple': '紫色',
            'black': '黑色',
            'gray': '灰色',
            'unknown': '未识别颜色',
        }
        current = cls._normalize_annotation_source_color(source_color)
        return label_map.get(current, '未识别颜色')

    def _get_annotation_highlight_color(self, annotation):
        source_color = self._normalize_annotation_source_color(getattr(annotation, 'source_color', 'unknown'))
        style = self.ANNOTATION_SOURCE_COLOR_STYLES.get(source_color)
        if style is not None:
            return style['highlight']
        return self.ANNOTATION_RISK_COLORS.get(annotation.risk_level, self.ANNOTATION_RISK_COLORS['safe'])

    def _get_annotation_badge_colors(self, annotation):
        source_color = self._normalize_annotation_source_color(getattr(annotation, 'source_color', 'unknown'))
        style = self.ANNOTATION_SOURCE_COLOR_STYLES.get(source_color)
        if style is not None:
            return style['badge']
        return self.ANNOTATION_BADGE_COLORS.get(annotation.risk_level, self.ANNOTATION_BADGE_COLORS['safe'])

    def _render_import_annotations(self):
        self._clear_annotation_visuals()
        if self.input_text is None:
            return

        current_text = self._get_input_text()

        if self.import_session and current_text == self.import_session.original_text:
            for annotation in self._get_import_annotations():
                if not self._should_render_annotation(annotation):
                    continue
                self._render_single_annotation(annotation)

        if self.manual_annotations and current_text == self.manual_annotation_base_text:
            for annotation in self.manual_annotations:
                if not self._should_render_annotation(annotation):
                    continue
                self._render_single_annotation(annotation)

        self._schedule_annotation_layout()

    def _render_single_annotation(self, annotation):
        tag_name = f'annotation::{annotation.paragraph_id}'
        self._annotation_tag_names.add(tag_name)
        self.input_text.tag_configure(
            tag_name,
            background=self._get_annotation_highlight_color(annotation),
            foreground=COLORS['text_main'],
        )
        self.input_text.tag_add(
            tag_name,
            f'1.0+{annotation.start}c',
            f'1.0+{annotation.end}c',
        )
        self.input_text.tag_bind(
            tag_name,
            '<Button-1>',
            lambda _event, paragraph_id=annotation.paragraph_id: self._open_annotation_editor(paragraph_id),
        )
        badge = self._build_annotation_badge(annotation)
        if badge is not None:
            self._annotation_badges[annotation.paragraph_id] = badge

    def _should_render_annotation(self, annotation):
        if not annotation.is_auto_generated:
            return True
        if self._is_plagiarism_annotation_page():
            if annotation.risk_level == 'safe' and not annotation.is_user_modified:
                return False
            if annotation.end <= annotation.start and not annotation.is_user_modified:
                return False
        return True

    def _build_annotation_badge(self, annotation):
        badge_text = self._format_annotation_badge_text(annotation)
        if not badge_text:
            return None
        badge_bg, badge_fg = self._get_annotation_badge_colors(annotation)
        badge = tk.Label(
            self.input_text,
            text=badge_text,
            font=FONTS['tiny'],
            bg=badge_bg,
            fg=badge_fg,
            padx=6,
            pady=2,
            bd=1,
            relief=tk.SOLID,
            cursor='hand2',
        )
        badge.bind(
            '<Button-1>',
            lambda _event, paragraph_id=annotation.paragraph_id: self._open_annotation_editor(paragraph_id),
            add='+',
        )
        show_tooltip(
            badge,
            self._format_annotation_tooltip(annotation),
            placement='top_center',
            y_offset=8,
            wraplength=240,
            tooltip_style=self._get_page_tooltip_style(),
        )
        return badge

    def _is_ai_annotation_page(self):
        return self.PAGE_STATE_ID == 'ai_reduce'

    def _is_plagiarism_annotation_page(self):
        return self.PAGE_STATE_ID == 'plagiarism'

    @staticmethod
    def _format_duplicate_status_label(status, *, short=False):
        status_map = {
            'red': '标红',
            'suspect': '疑似' if short else '疑似重复',
            'safe': '安全',
            'none': '未标注',
        }
        return status_map.get(status, '未标注')

    def _format_annotation_badge_text(self, annotation):
        prefix = '跳过 | ' if not annotation.include_in_run else ''
        source_color = self._normalize_annotation_source_color(getattr(annotation, 'source_color', 'unknown'))
        if not annotation.is_auto_generated:
            risk_label = self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, '')
            return f'{prefix}{risk_label}' if risk_label else ''
        if self._is_ai_annotation_page():
            if annotation.ai_score is None:
                if source_color != 'unknown' and annotation.risk_level != 'safe':
                    return f'{prefix}{self._format_source_color_label(source_color)}标记'
                return ''
            return f'{prefix}AI {round(annotation.ai_score):.0f}%'
        if self._is_plagiarism_annotation_page():
            if annotation.repeat_score is not None:
                return f'{prefix}查重 {round(annotation.repeat_score):.0f}%'
            if source_color != 'unknown' and annotation.risk_level != 'safe':
                return f'{prefix}{self._format_source_color_label(source_color)}标记'
            return ''
        return ''

    @staticmethod
    def _format_annotation_score(value):
        if value is None:
            return '--'
        return f'{value:.1f}%'

    @staticmethod
    def _format_yes_no_flag(value):
        return '是' if value else '否'

    def _format_annotation_tooltip(self, annotation):
        source_color = self._normalize_annotation_source_color(getattr(annotation, 'source_color', 'unknown'))
        if not annotation.is_auto_generated:
            lines = [
                f'风险级别：{self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, annotation.risk_level)}',
                f'本次是否执行：{self._format_yes_no_flag(annotation.include_in_run)}',
                '来源：手动标记',
            ]
            return '\n'.join(lines)
        if self._is_ai_annotation_page():
            lines = [
                f'AI率：{self._format_annotation_score(annotation.ai_score)}',
                f'风险级别：{self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, annotation.risk_level)}',
                f'本次是否执行：{self._format_yes_no_flag(annotation.include_in_run)}',
                f'是否片段匹配：{self._format_yes_no_flag(bool((annotation.source_excerpt or "").strip()))}',
            ]
            if source_color != 'unknown':
                lines.append(f'报告颜色：{self._format_source_color_label(source_color)}')
            return '\n'.join(lines)
        if self._is_plagiarism_annotation_page():
            lines = [
                f'查重率：{self._format_annotation_score(annotation.repeat_score)}',
                f'风险级别：{self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, annotation.risk_level)}',
                f'本次是否执行：{self._format_yes_no_flag(annotation.include_in_run)}',
                f'是否片段匹配：{self._format_yes_no_flag(bool((annotation.source_excerpt or "").strip()))}',
            ]
            if source_color != 'unknown':
                lines.append(f'报告颜色：{self._format_source_color_label(source_color)}')
            return '\n'.join(lines)
        lines = [
            f'风险级别：{self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, annotation.risk_level)}',
            f'本次是否执行：{self._format_yes_no_flag(annotation.include_in_run)}',
        ]
        if source_color != 'unknown':
            lines.append(f'报告颜色：{self._format_source_color_label(source_color)}')
        return '\n'.join(lines)

    def _schedule_annotation_layout(self, delay_ms=24):
        if self.input_text is None:
            return
        if self._annotation_layout_job is not None:
            try:
                self.frame.after_cancel(self._annotation_layout_job)
            except tk.TclError:
                pass
        self._annotation_layout_job = self.frame.after(delay_ms, self._layout_annotation_badges)

    def _layout_annotation_badges(self):
        self._annotation_layout_job = None
        if self.input_text is None:
            return
        widget_width = max(self.input_text.winfo_width(), 100)
        annotations = {item.paragraph_id: item for item in self._get_all_annotations()}
        for paragraph_id, badge in list(self._annotation_badges.items()):
            annotation = annotations.get(paragraph_id)
            if annotation is None:
                try:
                    badge.place_forget()
                except tk.TclError:
                    pass
                continue
            try:
                info = self.input_text.dlineinfo(f'1.0+{annotation.start}c')
            except tk.TclError:
                info = None
            if not info:
                try:
                    badge.place_forget()
                except tk.TclError:
                    pass
                continue
            badge.configure(text=self._format_annotation_badge_text(annotation))
            badge.update_idletasks()
            badge_width = badge.winfo_reqwidth()
            x = max(widget_width - badge_width - 12, 8)
            y = max(int(info[1]) + 2, 2)
            try:
                badge.place(x=x, y=y)
            except tk.TclError:
                continue

    def _should_show_annotation_excerpt(self):
        return False

    def _build_annotation_editor_shell(self, popup):
        popup.configure(bg=COLORS['bg_main'])
        outer = tk.Frame(popup, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        outer.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        shell = tk.Frame(
            outer,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=2,
            bd=0,
            padx=14,
            pady=14,
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=(0, 4), pady=(0, 4))
        return shell

    def _open_annotation_editor(self, paragraph_id):
        annotation = self._find_annotation_by_id(paragraph_id)
        if annotation is None:
            return

        self.selected_annotation_id = paragraph_id
        self._schedule_workspace_state_save()
        self._close_annotation_editor()

        popup = tk.Toplevel(self.frame)
        popup.title(self.ANNOTATION_EDITOR_TITLE)
        popup.transient(self.frame.winfo_toplevel())
        popup.resizable(False, False)
        popup.protocol('WM_DELETE_WINDOW', self._close_annotation_editor)
        popup.bind('<Escape>', lambda _event: self._close_annotation_editor(), add='+')

        shell = self._build_annotation_editor_shell(popup)

        if self._should_show_annotation_excerpt():
            tk.Label(
                shell,
                text=(annotation.source_excerpt or '')[:120],
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                anchor='w',
                justify='left',
                wraplength=320,
            ).pack(fill=tk.X, pady=(0, 10))

        risk_label_map = {label: key for key, label in self.ANNOTATION_RISK_LABELS.items()}
        risk_var = tk.StringVar(value=self.ANNOTATION_RISK_LABELS.get(annotation.risk_level, '安全'))
        include_var = tk.BooleanVar(value=bool(annotation.include_in_run))

        self._build_editor_field(shell, '风险级别', ttk.Combobox, risk_var, {
            'state': 'readonly',
            'values': list(self.ANNOTATION_RISK_LABELS.values()),
            'width': 18,
        })

        ai_var = None
        repeat_var = None
        duplicate_var = None
        if self._is_ai_annotation_page():
            ai_var = tk.StringVar(value='' if annotation.ai_score is None else f'{annotation.ai_score:.1f}')
            self._build_editor_field(shell, 'AI率(%)', tk.Entry, ai_var, {'width': 22})
        elif self._is_plagiarism_annotation_page():
            repeat_var = tk.StringVar(value='' if annotation.repeat_score is None else f'{annotation.repeat_score:.1f}')
            self._build_editor_field(shell, '查重率(%)', tk.Entry, repeat_var, {'width': 22})
            duplicate_options = ('标红', '疑似重复', '安全', '未标注')
            duplicate_var = tk.StringVar(value=self._format_duplicate_status_label(annotation.duplicate_status))
            self._build_editor_field(shell, '重复状态', ttk.Combobox, duplicate_var, {
                'state': 'readonly',
                'values': duplicate_options,
                'width': 18,
            })

        include_row = tk.Frame(shell, bg=COLORS['card_bg'])
        include_row.pack(fill=tk.X, pady=(12, 0))
        tk.Label(
            include_row,
            text='纳入本次执行',
            font=FONTS['body'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        ToggleSwitch(
            include_row,
            variable=include_var,
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT, padx=(10, 0))

        action_row = tk.Frame(shell, bg=COLORS['card_bg'])
        action_row.pack(fill=tk.X, pady=(14, 0))
        ModernButton(
            action_row,
            '取消',
            style='ghost',
            command=self._close_annotation_editor,
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)
        ModernButton(
            action_row,
            '保存',
            style='primary',
            command=lambda: self._save_annotation_editor(
                paragraph_id,
                risk_label_map,
                risk_var,
                include_var,
                ai_var=ai_var,
                repeat_var=repeat_var,
                duplicate_var=duplicate_var,
            ),
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        self._annotation_popup = popup
        self._position_annotation_editor(popup, paragraph_id)
        popup.lift()
        popup.focus_force()

    def _build_editor_field(self, parent, label_text, widget_cls, variable, options):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(
            row,
            text=label_text,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=10,
            anchor='w',
        ).pack(side=tk.LEFT)
        kwargs = self._prepare_annotation_editor_field_options(widget_cls, options)
        kwargs['textvariable'] = variable
        widget = widget_cls(row, **kwargs)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return widget

    def _prepare_annotation_editor_field_options(self, widget_cls, options):
        kwargs = dict(options or {})
        if widget_cls is ttk.Combobox:
            kwargs.setdefault('style', 'Modern.TCombobox')
        elif widget_cls is tk.Entry:
            kwargs.setdefault('font', FONTS['body'])
            kwargs.setdefault('bg', COLORS['input_bg'])
            kwargs.setdefault('fg', COLORS['text_main'])
            kwargs.setdefault('relief', tk.FLAT)
            kwargs.setdefault('bd', 0)
            kwargs.setdefault('highlightthickness', 1)
            kwargs.setdefault('highlightbackground', COLORS['input_border'])
            kwargs.setdefault('highlightcolor', COLORS['accent'])
            kwargs.setdefault('insertbackground', COLORS['text_main'])
        return kwargs

    def _position_annotation_editor(self, popup, paragraph_id):
        popup.update_idletasks()
        badge = self._annotation_badges.get(paragraph_id)
        root = self.frame.winfo_toplevel()
        if badge is not None and badge.winfo_ismapped():
            x = badge.winfo_rootx() - max((popup.winfo_width() - badge.winfo_width()), 0)
            y = badge.winfo_rooty() + badge.winfo_height() + 8
        else:
            root.update_idletasks()
            x = root.winfo_rootx() + max((root.winfo_width() - popup.winfo_width()) // 2, 0)
            y = root.winfo_rooty() + max((root.winfo_height() - popup.winfo_height()) // 2, 0)
        popup.geometry(f'+{x}+{y}')

    def _save_annotation_editor(self, paragraph_id, risk_label_map, risk_var, include_var, *, ai_var=None, repeat_var=None, duplicate_var=None):
        duplicate_text_map = {
            '标红': 'red',
            '疑似重复': 'suspect',
            '安全': 'safe',
            '未标注': 'none',
        }
        chosen_risk = risk_label_map.get(risk_var.get(), 'safe')
        ai_score_value = None
        repeat_score_value = None
        if ai_var is not None:
            raw_score = str(ai_var.get() or '').strip()
            if raw_score:
                try:
                    ai_score_value = max(0.0, min(100.0, float(raw_score)))
                except ValueError:
                    messagebox.showwarning('提示', 'AI率请输入 0-100 之间的数字。', parent=self._annotation_popup or self.frame)
                    return
        if repeat_var is not None:
            raw_score = str(repeat_var.get() or '').strip()
            if raw_score:
                try:
                    repeat_score_value = max(0.0, min(100.0, float(raw_score)))
                except ValueError:
                    messagebox.showwarning('提示', '查重率请输入 0-100 之间的数字。', parent=self._annotation_popup or self.frame)
                    return

        chosen_duplicate = None
        if duplicate_var is not None:
            chosen_duplicate = duplicate_text_map.get(duplicate_var.get(), 'none')

        is_manual = any(a.paragraph_id == paragraph_id for a in self.manual_annotations)

        if is_manual:
            updated = []
            for annotation in self.manual_annotations:
                if annotation.paragraph_id != paragraph_id:
                    updated.append(annotation)
                    continue
                updated_annotation = ParagraphAnnotation.from_dict(annotation.to_dict())
                updated_annotation.risk_level = chosen_risk
                updated_annotation.include_in_run = bool(include_var.get())
                updated_annotation.is_user_modified = True
                if ai_var is not None:
                    updated_annotation.ai_score = ai_score_value
                if repeat_var is not None:
                    updated_annotation.repeat_score = repeat_score_value
                if duplicate_var is not None:
                    updated_annotation.duplicate_status = chosen_duplicate
                updated.append(updated_annotation)
            self.manual_annotations = sorted(updated, key=lambda a: (a.start, a.end, a.paragraph_id))
        else:
            updated_annotations = []
            for annotation in self._get_import_annotations():
                if annotation.paragraph_id != paragraph_id:
                    updated_annotations.append(annotation)
                    continue
                updated_annotation = ParagraphAnnotation.from_dict(annotation.to_dict())
                updated_annotation.risk_level = chosen_risk
                updated_annotation.include_in_run = bool(include_var.get())
                updated_annotation.is_user_modified = True
                if ai_var is not None:
                    updated_annotation.ai_score = ai_score_value
                if repeat_var is not None:
                    updated_annotation.repeat_score = repeat_score_value
                if duplicate_var is not None:
                    updated_annotation.duplicate_status = chosen_duplicate
                updated_annotations.append(updated_annotation)
                self.annotation_overrides[paragraph_id] = {
                    'risk_level': updated_annotation.risk_level,
                    'include_in_run': updated_annotation.include_in_run,
                    'ai_score': updated_annotation.ai_score,
                    'repeat_score': updated_annotation.repeat_score,
                    'duplicate_status': updated_annotation.duplicate_status,
                    'is_user_modified': True,
                }
            self._set_import_annotations(updated_annotations)

        self._close_annotation_editor()
        self._render_import_annotations()
        self._schedule_workspace_state_save()

    def _close_annotation_editor(self):
        popup = self._annotation_popup
        if popup is None:
            return
        try:
            if popup.winfo_exists():
                popup.destroy()
        except tk.TclError:
            pass
        self._annotation_popup = None

    def _get_output_text(self):
        return self._get_text_value(self.output_text)

    def _get_compare_text(self):
        for widget in self.compare_widgets:
            value = self._get_text_value(widget)
            if value:
                return value
        return ''

    def _get_result_text(self):
        return normalize_result_text(self._get_output_text())

    def _get_detection_target(self):
        return resolve_detection_target(
            self._get_input_text(),
            self._get_output_text(),
            input_label=self.INPUT_SOURCE_LABEL,
            result_label=self.RESULT_SOURCE_LABEL,
        )

    def _get_diff_baseline(self):
        if not self.COMPARE_TEXT_USED_FOR_DIFF_BASELINE:
            input_text = self._get_input_text()
            if input_text:
                return input_text, self.INPUT_SOURCE_LABEL
            return '', ''

        return resolve_diff_baseline(
            self._get_input_text(),
            self._get_compare_text(),
            input_label=self.INPUT_SOURCE_LABEL,
            compare_label=self.COMPARE_SOURCE_LABEL,
        )

    def _set_readonly_text(self, widget, text, tag=None):
        widget.configure(state=tk.NORMAL)
        widget.delete('1.0', tk.END)
        if text:
            if tag:
                widget.insert('1.0', text, tag)
            else:
                widget.insert('1.0', text)
        widget.configure(state=tk.DISABLED)
        self._schedule_workspace_state_save()

    def _set_analysis_status(self, text, color=None):
        if self.analysis_status_label is None:
            return
        self.analysis_status_label.configure(text=text, fg=color or COLORS['text_sub'])
        self._schedule_workspace_state_save()

    def _reset_analysis_workspace(self):
        self._set_analysis_status(self.ANALYSIS_STATUS_READY_TEXT)
        self._set_readonly_text(self.analysis_text, self.SUMMARY_PLACEHOLDER_TEXT)
        self._set_readonly_text(self.preview_text, self.PREVIEW_EMPTY_TEXT, tag='diff_equal')

    def _mark_analysis_stale(self, status_text):
        self._set_analysis_status(status_text, COLORS['warning'])
        self._set_readonly_text(self.analysis_text, status_text)
        self._set_readonly_text(self.preview_text, self.STALE_PREVIEW_TEXT, tag='diff_equal')

    def _run_primary_analysis(self):
        text, source_label = self._get_detection_target()
        if not text:
            messagebox.showwarning('提示', self.PRIMARY_ANALYSIS_EMPTY_WARNING, parent=self.frame)
            return

        summary_text, status_text, status_color = self._analyze_text(text, source_label)
        self._set_readonly_text(self.analysis_text, summary_text)
        self._set_analysis_status(status_text, status_color)

    def _run_secondary_analysis(self):
        text, source_label = self._get_detection_target()
        if not text:
            messagebox.showwarning('提示', self.PRIMARY_ANALYSIS_EMPTY_WARNING, parent=self.frame)
            return

        summary_text, status_text, status_color = self._analyze_secondary_text(text, source_label)
        self._set_readonly_text(self.analysis_text, summary_text)
        self._set_analysis_status(status_text, status_color)

    def _analyze_secondary_text(self, text, source_label):
        result = self.aux.check_format(text)
        lines = [
            f'核验对象：{source_label}',
            f'字数：{result["word_count"]}',
            f'段落数：{result["para_count"]}',
            f'句子数：{result["sentence_count"]}',
        ]

        if result['issues']:
            lines.extend(['', '发现的问题：'])
            lines.extend(f'  - {issue}' for issue in result['issues'])
            status = f'结构检查完成，请根据提示调整“{source_label}”。'
            color = COLORS['warning']
        else:
            lines.extend(['', '结构检查通过，未发现明显问题。'])
            status = f'结构检查完成，当前核验对象为“{source_label}”。'
            color = COLORS['success']

        return '\n'.join(lines), status, color

    def _detect_sensitive(self):
        text, source_label = self._get_detection_target()
        if not text:
            messagebox.showwarning('提示', self.PRIMARY_ANALYSIS_EMPTY_WARNING, parent=self.frame)
            return

        found = self.aux.detect_sensitive(text)
        lines = [f'核验对象：{source_label}']
        if not found:
            lines.extend(['', '未检测到敏感或明显违规表达。'])
            self._set_readonly_text(self.analysis_text, '\n'.join(lines))
            self._set_analysis_status(f'敏感表达检查完成，当前核验对象为“{source_label}”。', COLORS['success'])
            return

        lines.extend(['', '检测到需要谨慎处理的内容：'])
        for item in found:
            matches = '、'.join(item['matches'])
            lines.append(f'  - [{item["category"]}] {matches}')
        self._set_readonly_text(self.analysis_text, '\n'.join(lines))
        self._set_analysis_status(f'敏感表达检查完成，请根据提示调整“{source_label}”。', COLORS['warning'])

    def _render_diff_preview(self, base_text, result_text):
        chunks = self.aux.diff_highlight(base_text, result_text)
        counts = {'equal': 0, 'insert': 0, 'delete': 0}

        self.preview_text.configure(state=tk.NORMAL)
        self.preview_text.delete('1.0', tk.END)
        if not chunks:
            self.preview_text.insert('1.0', '未检测到差异内容。', 'diff_equal')
        else:
            for tag, segment in chunks:
                if not segment:
                    continue
                counts[tag] += len(segment)
                self.preview_text.insert(tk.END, segment, f'diff_{tag}')
        self.preview_text.configure(state=tk.DISABLED)
        self.preview_text.see('1.0')
        return counts

    def _refresh_diff_view(self, auto=False):
        base_text, base_label = self._get_diff_baseline()
        result_text = self._get_result_text()
        if not base_text or not result_text:
            self._set_readonly_text(self.preview_text, self.PREVIEW_MISSING_TEXT, tag='diff_equal')
            self._set_analysis_status('差异视图暂不可用，请先准备基准文本与处理结果。', COLORS['warning'])
            if not auto:
                messagebox.showwarning('提示', self.PREVIEW_MISSING_TEXT, parent=self.frame)
            return

        counts = self._render_diff_preview(base_text, result_text)
        self._set_readonly_text(self.analysis_text, self._build_diff_summary(base_label, base_text, result_text, counts))
        self._set_analysis_status('差异视图已自动刷新。' if auto else '差异视图已刷新。', COLORS['success'])

    def _run_transform(self):
        text = self._get_input_text()
        if not text:
            messagebox.showwarning('提示', self.PROCESS_EMPTY_WARNING, parent=self.frame)
            return
        if not self._ensure_prompt_ready():
            return

        mode = self.mode_var.get()

        knowledge_context = self._choose_knowledge_context(self.PROMPT_SCENE_ID)
        if knowledge_context is None:
            return
        self._pending_knowledge_context = knowledge_context

        def on_start():
            self._set_text_value(self.output_text, '处理中...')
            self._mark_analysis_stale('结果正在更新，完成后将自动刷新差异视图。')

        self.task_runner.run(
            work=lambda: self._transform_text_with_import_annotations(text, mode),
            on_success=lambda result: self._finish_transform(mode, text, result),
            on_error=self._handle_transform_error,
            on_start=on_start,
            loading_text=self.ACTION_LOADING_TEXT,
            status_text=self.ACTION_START_STATUS,
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

    def _finish_transform(self, mode, source_text, result):
        self._set_text_value(self.output_text, result)
        self._apply_paper_fonts_to_widgets()
        self.info_label.configure(text=self._build_completion_info(source_text, result), fg=COLORS['text_muted'])
        self._refresh_diff_view(auto=True)
        workspace_state = self.capture_workspace_state_snapshot(save_to_disk=False)
        self.history.add(
            self._history_operation(mode),
            source_text,
            result,
            self.MODULE_NAME,
            extra=self._build_history_extra(),
            page_state_id=self.PAGE_STATE_ID,
            workspace_state=workspace_state,
        )
        self.set_status(self.ACTION_SUCCESS_STATUS)
        self._pending_knowledge_context = None

    def _handle_transform_error(self, exc):
        self._set_text_value(self.output_text, f'错误：{exc}')
        self.set_status(self.ACTION_FAILURE_STATUS, COLORS['error'])
        self._mark_analysis_stale('处理失败，核验结果与差异预览已失效。')
        self._pending_knowledge_context = None

    def _transform_text_with_import_annotations(self, text, mode):
        all_annotations = self._get_all_annotations()
        if all_annotations:
            return self._transform_with_annotations(text, mode, all_annotations)
        return self._transform_text(text, mode)

    def _transform_with_annotations(self, text, mode, annotations):
        del annotations
        return self._transform_text(text, mode)

    def _build_history_extra(self):
        extra = {}
        if self.import_session:
            extra.update({
                'import_file_name': self.import_session.file_name,
                'import_vendor': self.import_session.vendor,
                'import_file_format': self.import_session.file_format,
                'import_report_kind': self.import_session.report_kind,
                'matched_annotation_count': self.import_session.matched_count,
                'total_annotation_count': len(self._get_import_annotations()),
            })
        if self.manual_annotations:
            extra['manual_annotation_count'] = len(self.manual_annotations)
        if self.current_paper_title:
            extra['paper_title'] = self.current_paper_title
        return extra

    def _open_prompt_manager(self):
        if not self.app_bridge or not self.PROMPT_SCENE_ID:
            return
        self.app_bridge.show_prompt_manager(
            page_id=self.PROMPT_PAGE_ID or '',
            compact=True,
            scene_id=self.PROMPT_SCENE_ID,
        )

    def _ensure_prompt_ready(self):
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return False
        if not self.PROMPT_SCENE_ID:
            return True
        if self.prompt_center.scene_has_active_prompt(self.PROMPT_SCENE_ID):
            return True
        messagebox.showwarning('提示', '当前页面没有可用的提示词，请先创建或选择一条提示词。', parent=self.frame)
        self._open_prompt_manager()
        return False

    def _replace(self):
        result = self._get_result_text()
        if not result:
            messagebox.showwarning('提示', self.REPLACE_EMPTY_WARNING, parent=self.frame)
            return

        rebased = False
        if self.import_session:
            self._suppress_import_session_clear = True
            try:
                self._set_text_value(self.input_text, result)
                rebased = self._rebase_import_session_to(self._get_input_text())
            finally:
                self._suppress_import_session_clear = False
            if not rebased:
                self._clear_import_session('原文区已被处理结果替换，原报告标注已清除。')
        else:
            self._set_text_value(self.input_text, result)

        if rebased:
            self.info_label.configure(
                text='原文区已更新为处理结果，已对齐原报告标注，已处理段落标记为安全。',
                fg=COLORS['text_muted'],
            )
        else:
            self.info_label.configure(text=self.REPLACE_INFO_TEXT, fg=COLORS['text_muted'])
        self._mark_analysis_stale('原文已被结果替换，请重新核验或刷新差异视图。')

    def _reset_input_area(self):
        self._set_input_text('', 'manual', '', paper_title='')
        if self.import_session:
            self._clear_import_session()
        self.manual_annotations = []
        self.manual_annotation_base_text = ''
        if self.info_label is not None:
            self.info_label.configure(text=self.INPUT_RESET_INFO_TEXT, fg=COLORS['text_sub'])
        self._mark_analysis_stale(self.INPUT_RESET_STALE_TEXT)
        if self.input_text is not None:
            self.input_text.delete('1.0', tk.END)
            state = self._placeholder_state.get(self.input_text)
            if state:
                state['active'] = False
            self.input_text.configure(fg=COLORS['text_main'])
            self.input_text.mark_set(tk.INSERT, '1.0')
            self.input_text.focus_set()
            self._schedule_workspace_state_save()

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
        self._mark_analysis_stale(self.STALE_ANALYSIS_TEXT)
        return {
            'ok': True,
            'message': '内容已发送到目标页面',
            'section': section_name,
            'page_id': self.PAGE_STATE_ID,
        }

    def on_show(self):
        if self._workspace_state_restored and self._get_input_text():
            return
        if not self.app_bridge:
            return

        snapshot = self.app_bridge.pull_paper_write_selection_snapshot()
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

        context = self.app_bridge.pull_paper_write_context()
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
        for widget in [self.input_text, self.output_text] + list(self.compare_widgets):
            try:
                apply_mixed_fonts(widget, cn, en, pt)
            except Exception:
                pass

    def _analyze_text(self, text, source_label):
        raise NotImplementedError

    def _transform_text(self, text, mode):
        raise NotImplementedError

    def _history_operation(self, mode):
        raise NotImplementedError

    def _build_completion_info(self, source_text, result_text):
        return f'处理完成 | 原文{len(source_text)}字 -> 结果{len(result_text)}字'

    def _build_diff_summary(self, base_label, base_text, result_text, counts):
        del base_text, result_text
        lines = [
            f'差异基准：{base_label}',
            '对比方向：基准文本 -> 当前结果',
            f'保留字符：{counts["equal"]}',
            f'新增字符：{counts["insert"]}',
            f'删除字符：{counts["delete"]}',
        ]
        return '\n'.join(lines)
