# -*- coding: utf-8 -*-
"""
降查重率页面。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

from modules.app_metadata import MODULE_PLAGIARISM
from modules.plagiarism import PlagiarismReducer
from modules.report_importer import ReportImportEngine
from modules.ui_components import COLORS, FONTS, CardFrame, ModernButton, create_scrolled_text, get_window_work_area
from pages.text_transform_base import TextTransformPageBase


class PlagiarismPage(TextTransformPageBase):
    PAGE_STATE_ID = 'plagiarism'
    MODE_CARD_TITLE = '重复率降低·降重模式'
    MODE_CARD_HINT = '当前页聚焦“向外规避重复源”，优先依据查重报告或重复源文本定位高风险片段，再执行降重。'
    MODE_DEFAULT = 'light'
    MODE_OPTIONS = (
        (
            'light',
            '轻度降重',
            '同义词精准替换、语序微调，改写幅度 20%-30%，保留原文完整语义。\n'
            '适用场景：查重率 10%-20%，仅需微调轻度重复片段。',
        ),
        (
            'medium',
            '中度降重',
            '句式重组、表述重构，改写幅度 40%-50%，规避连续重复语句，保留核心数据与观点。\n'
            '适用场景：查重率 20%-40%，存在多处中度重复片段。',
        ),
        (
            'deep',
            '深度降重',
            '段落逻辑重构、同义扩写，改写幅度 60%-80%，彻底规避高重复片段。\n'
            '适用场景：查重率 ≥40%，存在大面积标红内容。',
        ),
    )
    MODE_COLOR_KEY = 'accent'
    MODE_LAYOUT = 'inline_selector'
    MODE_INLINE_ITEM_WIDTH = 220
    MODE_INLINE_ITEM_GAP = 10
    MODE_INLINE_GROUP_GAP = 12
    MODE_INLINE_RIGHT_INSET = 4
    TOP_SECTION_LAYOUT = 'merged_toolbar'
    TOP_SECTION_BREAKPOINT = 1240
    DETECT_SECTION_PLACEMENT = 'preview'
    MERGED_TOP_CARD_TITLE = '重复率降低'
    MERGED_MODE_LABEL_TEXT = '重复率降低：'
    MERGED_DETECT_LABEL_TEXT = '结果核验：'
    SHOW_OUTPUT_HEADER_REPLACE_ACTION = True

    ACTION_BUTTON_TEXT = '开始降重'
    ACTION_BUTTON_STYLE = 'primary_fixed'
    ACTION_TIP_TEXT = '降重完成后，结果将自动同步至“历史记录”页面，支持一键导出；下方核验区可继续完成重复风险模拟与差异比对。'
    ACTION_START_STATUS = '降重中...'
    ACTION_LOADING_TEXT = '正在执行降重...'
    ACTION_SUCCESS_STATUS = '降重完成，已写入历史记录'
    ACTION_FAILURE_STATUS = '降重失败'
    PROCESS_EMPTY_WARNING = '请先粘贴需要降重的论文内容。'

    DETECT_CARD_TITLE = '结果核验'
    DETECT_CARD_HINT = '优先复核当前降重结果；无结果时将自动核验原文。结合查重报告或重复源文本，可更准确判断降重效果。'
    DETECT_RESULT_HINT = '完成核验后，此处将展示模拟重复率、重复片段定位与原文-降重结果差异预览。'
    COMPARE_DETECT_COLLAPSIBLE = False
    COMPARE_DETECT_DEFAULT_COLLAPSED = False
    COMPARE_DETECT_HELP_TEXT = '附属功能区，仅用于复核当前降重结果；不影响上方模式选择与主流程执行。'
    COMPARE_DETECT_COLLAPSED_HINT = '默认收起，按需展开降重效果复核。'
    PRIMARY_ANALYSIS_BUTTON_TEXT = '效果复核'
    PRIMARY_ANALYSIS_BUTTON_STYLE = 'primary_fixed'
    PREVIEW_REFRESH_BUTTON_TEXT = '刷新'
    SECONDARY_ANALYSIS_BUTTON_TEXT = '引用规范检查'
    PRIMARY_ANALYSIS_EMPTY_WARNING = '请先输入待降重原文或生成降重处理结果。'
    ANALYSIS_STATUS_READY_TEXT = '请选择结果核验动作'
    STALE_ANALYSIS_TEXT = '内容已更新，请重新执行降重效果复核或刷新差异视图。'
    STALE_PREVIEW_TEXT = '内容已更新，请点击“刷新差异视图”重新生成原文与降重结果的差异预览。'

    INPUT_CARD_TITLE = '待降重原文'
    INPUT_PLACEHOLDER = '请粘贴需要降重的论文段落/全文，支持单独选中查重标红片段处理。'
    OUTPUT_CARD_TITLE = '降重处理结果'
    OUTPUT_PLACEHOLDER = '降重完成后，结果将显示在此处，支持在线编辑微调。'

    COMPARE_SECTION_TITLE = '结果核验与差异预览区'
    COMPARE_SECTION_DESCRIPTION = ''
    COMPARE_CARD_TITLE = '查重报告/重复源文本'
    COMPARE_CARD_HINT = '系统自动识别报告后，可在此继续补充或修订重复源文本。'
    COMPARE_PLACEHOLDER = '请粘贴查重标红内容、重复源文献全文/片段，提升降重精准度。'
    COMPARE_SOURCE_LABEL = '查重报告 / 重复源文本'
    COMPARE_TEXT_USED_FOR_DIFF_BASELINE = False
    COMPARE_DIALOG_TITLE = '导入报告'
    COMPARE_DIALOG_BUTTON_TEXT = '导入报告'
    COMPARE_DIALOG_DESCRIPTION = '导入查重检测报告后，系统会自动解析并对原文区正文完成初次标注。'
    COMPARE_DIALOG_STATUS_TEXT = '导入后系统会先完成初次自动标注，随后可在原文区直接修正。'

    PREVIEW_CARD_TITLE = ''
    PREVIEW_LEGEND_TEXT = '绿色=新增，红色=删除，灰色=保留。'
    PREVIEW_LEGEND_ITEMS = (
        ('绿色', '= 新增', 'success'),
        ('红色', '= 删除', 'error'),
        ('灰色', '= 保留', 'neutral'),
    )
    SUMMARY_TITLE = '检测结果摘要'
    SUMMARY_PLACEHOLDER_TEXT = '完成降重效果复核后，此处将展示模拟重复率、标红片段数量、降重效果评估与核心问题汇总。'
    PREVIEW_TITLE = '差异预览'
    PREVIEW_EMPTY_TEXT = '点击“刷新差异视图”，即可查看原文与降重结果的逐句差异，以及重复片段的修改情况。'
    PREVIEW_MISSING_TEXT = '请先准备待降重原文与降重处理结果。'

    REPLACE_BUTTON_TEXT = '回填到原文区'
    REPLACE_EMPTY_WARNING = '当前没有可回填的降重处理结果。'
    REPLACE_INFO_TEXT = '已将降重处理结果回填到原文区，可继续优化或重新核验。'

    INPUT_SOURCE_LABEL = '待降重原文'
    RESULT_SOURCE_LABEL = '降重处理结果'

    MODULE_NAME = MODULE_PLAGIARISM
    PROMPT_PAGE_ID = 'plagiarism'
    PROMPT_SCENE_ID = 'plagiarism.transform'

    def __init__(self, parent, config_mgr, api_client, history_mgr, set_status, navigate_page=None, app_bridge=None):
        self._compare_dialog = None
        self._compare_import_status = None
        self.report_importer = None
        super().__init__(
            parent,
            config_mgr,
            api_client,
            history_mgr,
            set_status,
            PlagiarismReducer(api_client),
            navigate_page=navigate_page,
            app_bridge=app_bridge,
            loading_text='正在执行降重...',
        )
        self.report_importer = ReportImportEngine(log_callback=self.task_runner.log_callback)
        self.frame.bind('<Destroy>', self._handle_frame_destroy, add='+')

    def _get_detect_button_specs(self):
        return (
            (self.PRIMARY_ANALYSIS_BUTTON_TEXT, self.PRIMARY_ANALYSIS_BUTTON_STYLE, self._run_primary_analysis),
            (self.PREVIEW_REFRESH_BUTTON_TEXT, 'accent', self._refresh_diff_view),
        )

    def _get_primary_action_button_specs(self):
        return (
            (self.COMPARE_DIALOG_BUTTON_TEXT, 'secondary', self._open_compare_dialog),
        )

    def _get_preview_card_header_button_specs(self):
        return ()

    def _get_analysis_summary_title_button_specs(self):
        return (
            (self.PRIMARY_ANALYSIS_BUTTON_TEXT, self.PRIMARY_ANALYSIS_BUTTON_STYLE, self._run_primary_analysis),
        )

    def _get_preview_title_button_specs(self):
        return (
            (self.PREVIEW_REFRESH_BUTTON_TEXT, 'accent', self._refresh_diff_view),
        )

    def _get_preview_title_tooltip_spec(self):
        return {
            'image_path': 'png/Tip.png',
            'text': self.PREVIEW_LEGEND_TEXT,
            'max_size': (16, 16),
        }

    def _build_pre_mode_section(self, parent):
        del parent
        self._ensure_compare_dialog()

    def _build_compare_card(self, parent):
        self._build_compare_editor(
            parent,
            hint_text=self.COMPARE_CARD_HINT,
            placeholder=self.COMPARE_PLACEHOLDER,
            height=12,
        )

    def _build_compare_preview_cards(self, parent):
        left_card = CardFrame(parent)
        self._build_plagiarism_compare_summary_card(left_card.inner)

        right_card = CardFrame(parent)
        self._build_plagiarism_diff_preview_card(right_card.inner)

        parent.grid_columnconfigure(0, weight=3, minsize=0, uniform='plagiarism_compare_preview')
        parent.grid_columnconfigure(1, weight=7, minsize=0, uniform='plagiarism_compare_preview')
        parent.grid_rowconfigure(0, weight=1)
        left_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        right_card.grid(row=0, column=1, sticky='nsew')

    def _build_plagiarism_compare_summary_card(self, parent):
        self._build_analysis_summary_section(
            parent,
            title=self.SUMMARY_TITLE,
            frame_pady=(8, 0),
            height=16,
            fill=tk.BOTH,
            expand=True,
        )

    def _build_plagiarism_diff_preview_card(self, parent):
        self._build_section_heading(
            parent,
            self.PREVIEW_TITLE,
            button_specs=self._get_preview_title_button_specs(),
            tooltip_spec=self._get_preview_title_tooltip_spec(),
        )
        self._build_analysis_status(parent, pady=(8, 8))
        preview_frame, self.preview_text = create_scrolled_text(parent, height=16)
        preview_frame.pack(fill=tk.BOTH, expand=True)
        self.preview_text.configure(state=tk.DISABLED, cursor='arrow')
        self.preview_text.tag_configure('diff_insert', foreground=COLORS['success'])
        self.preview_text.tag_configure('diff_delete', foreground=COLORS['error'], overstrike=1)
        self.preview_text.tag_configure('diff_equal', foreground=COLORS['text_muted'])

    def _ensure_compare_dialog(self):
        dialog = self._compare_dialog
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    return dialog
            except tk.TclError:
                pass

        root = self.frame.winfo_toplevel()
        dialog = tk.Toplevel(root)
        dialog.withdraw()
        dialog.title(self.COMPARE_DIALOG_TITLE)
        dialog.transient(root)
        dialog.configure(bg=COLORS['bg_main'])
        dialog.minsize(680, 420)
        dialog.protocol('WM_DELETE_WINDOW', self._close_compare_dialog)
        dialog.bind('<Escape>', lambda _event: self._close_compare_dialog(), add='+')

        shell = tk.Frame(dialog, bg=COLORS['bg_main'])
        shell.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        card = CardFrame(shell, title=self.COMPARE_DIALOG_TITLE)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card.inner,
            text=self.COMPARE_DIALOG_DESCRIPTION,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
            wraplength=560,
        ).pack(fill=tk.X)

        placeholder = tk.Frame(
            card.inner,
            bg=COLORS['surface_alt'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        placeholder.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        tk.Label(
            placeholder,
            text='支持导入查重检测报告的 PDF 打印版、Word 颜色标记版。',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['surface_alt'],
            justify='center',
            anchor='center',
        ).pack(fill=tk.X, pady=(28, 10))

        ModernButton(
            placeholder,
            '选择报告文件',
            style='primary',
            command=self._choose_import_report_file,
            padx=16,
            pady=8,
        ).pack()
        self._compare_import_status = tk.Label(
            placeholder,
            text=self.COMPARE_DIALOG_STATUS_TEXT,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['surface_alt'],
            justify='left',
            anchor='center',
            wraplength=520,
        )
        self._compare_import_status.pack(fill=tk.X, padx=20, pady=(14, 28))

        footer = tk.Frame(card.inner, bg=COLORS['card_bg'])
        footer.pack(fill=tk.X, pady=(12, 0))

        ModernButton(
            footer,
            '关闭',
            style='ghost',
            command=self._close_compare_dialog,
            padx=14,
            pady=8,
        ).pack(side=tk.RIGHT)

        self._compare_dialog = dialog
        return dialog

    def _open_compare_dialog(self):
        dialog = self._ensure_compare_dialog()
        self._center_compare_dialog(dialog)
        dialog.deiconify()
        dialog.lift()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    def _close_compare_dialog(self):
        dialog = self._compare_dialog
        if dialog is None:
            return
        self._compare_dialog = None
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        try:
            if dialog.winfo_exists():
                dialog.withdraw()
        except tk.TclError:
            pass

    def _center_compare_dialog(self, dialog):
        root = self.frame.winfo_toplevel()
        root.update_idletasks()
        dialog.update_idletasks()

        width = max(dialog.winfo_reqwidth(), 820)
        height = max(dialog.winfo_reqheight(), 620)
        work_x, work_y, work_width, work_height = get_window_work_area(dialog)
        width = min(width, max(1, int(work_width) - 96))
        height = min(height, max(1, int(work_height) - 80))
        root_x = root.winfo_rootx()
        root_y = root.winfo_rooty()
        root_width = max(root.winfo_width(), root.winfo_reqwidth(), width)
        root_height = max(root.winfo_height(), root.winfo_reqheight(), height)
        x = root_x + max((root_width - width) // 2, 0)
        y = root_y + max((root_height - height) // 2, 0)
        x = max(int(work_x), min(x, int(work_x) + max(0, int(work_width) - width)))
        y = max(int(work_y), min(y, int(work_y) + max(0, int(work_height) - height)))
        dialog.geometry(f'{width}x{height}+{x}+{y}')

    def _handle_frame_destroy(self, event):
        if event.widget is not self.frame:
            return
        dialog = self._compare_dialog
        if dialog is None:
            return
        try:
            if dialog.winfo_exists():
                dialog.destroy()
        except tk.TclError:
            pass
        self._compare_dialog = None
        self._compare_import_status = None

    def _set_compare_import_status(self, text, *, color=None):
        if self._compare_import_status is None:
            return
        self._compare_import_status.configure(text=text, fg=color or COLORS['text_sub'])

    def _choose_import_report_file(self):
        source_text = self._get_input_text()
        if not source_text:
            messagebox.showwarning('提示', '请先在原文区准备论文正文，再导入查重检测报告。', parent=self._compare_dialog or self.frame)
            return

        path = filedialog.askopenfilename(
            filetypes=[('报告文件', '*.pdf *.docx'), ('PDF', '*.pdf'), ('Word 文档', '*.docx')],
            parent=self._compare_dialog or self.frame,
        )
        if not path:
            return

        def on_start():
            self._set_compare_import_status(f'正在解析报告：{path}', color=COLORS['warning'])

        def on_success(session):
            notes = '；'.join(session.parse_notes[:2]) if session.parse_notes else '已完成初次自动标注。'
            self._apply_import_session(
                session,
                info_text=(
                    f'报告导入完成：{session.file_name} | 已初次标注 {session.matched_count}/{session.total_body_paragraphs} 个正文段落'
                ),
            )
            self._set_compare_import_status(notes, color=COLORS['success'])
            self.set_status('查重报告导入完成', COLORS['success'])
            if self.config and hasattr(self.config, 'clear_home_last_import_failure'):
                self.config.clear_home_last_import_failure()
                self.config.save()

        def on_error(exc):
            if self.config and hasattr(self.config, 'set_home_last_import_failure'):
                self.config.set_home_last_import_failure('plagiarism', os.path.basename(path), str(exc))
                self.config.save()
            self._set_compare_import_status(f'导入失败：{exc}', color=COLORS['error'])
            messagebox.showerror('导入失败', str(exc), parent=self._compare_dialog or self.frame)

        self.task_runner.run(
            work=lambda: self.report_importer.parse_in_subprocess(path, self.PAGE_STATE_ID, source_text),
            on_success=on_success,
            on_error=on_error,
            on_start=on_start,
            loading_text='正在解析查重检测报告...',
            status_text='正在解析查重检测报告...',
            status_color=COLORS['warning'],
        )

    def _analyze_text(self, text, source_label):
        source_text = self._get_compare_text()
        baseline_text = self._get_input_text()
        current_result = self._get_result_text()
        summary_text = self._build_plagiarism_summary_text(
            source_label=source_label,
            current_text=text,
            base_label=self.INPUT_SOURCE_LABEL if baseline_text else '',
            base_text=baseline_text,
            result_text=current_result,
            source_text=source_text,
        )

        result = self.processor.simulate_repeat_risk(text, source_text)
        color = COLORS['error'] if result['simulated_rate'] >= 35 else COLORS['warning'] if result['simulated_rate'] >= 18 else COLORS['success']
        status_text = f'降重效果复核完成，当前核验对象为“{source_label}”。'
        return summary_text, status_text, color

    def _analyze_secondary_text(self, text, source_label):
        result = self.processor.check_citation_format(text)
        lines = [
            f'核验对象：{source_label}',
            f'正文编号引用数：{result["citation_count"]}',
            f'参考文献编号数：{result["reference_count"]}',
            f'作者-年份引用数：{result["author_year_count"]}',
            f'是否检测到参考文献区：{"是" if result["has_reference_section"] else "否"}',
        ]

        if result['issues']:
            lines.extend(['', '引用规范问题：'])
            lines.extend(f'  - {item}' for item in result['issues'])
        else:
            lines.extend(['', '引用规范检查通过，正文引用与参考文献对应关系未见明显问题。'])

        color = COLORS['warning'] if result['issues'] else COLORS['success']
        status_text = f'引用规范检查完成，当前核验对象为“{source_label}”。'
        return '\n'.join(lines), status_text, color

    def _transform_text(self, text, mode):
        source_text = self._get_compare_text()
        kc = getattr(self, '_pending_knowledge_context', None)
        return self._reduce_until_rate_improves(
            text,
            mode,
            source_text,
            reduce_runner=lambda selected_mode: self._reduce_text_by_mode(text, source_text, selected_mode, kc),
        )

    def _transform_with_annotations(self, text, mode, annotations):
        source_text = self._get_compare_text()
        kc = getattr(self, '_pending_knowledge_context', None)
        return self._reduce_until_rate_improves(
            text,
            mode,
            source_text,
            reduce_runner=lambda selected_mode: self.processor.reduce_with_annotations(
                text,
                annotations,
                selected_mode,
                source_text=source_text,
                knowledge_context=kc,
            ),
        )

    def _reduce_text_by_mode(self, text, source_text, mode, knowledge_context=None):
        if mode == 'light':
            return self.processor.reduce_light(text, source_text, knowledge_context=knowledge_context)
        if mode == 'medium':
            return self.processor.reduce_medium(text, source_text, knowledge_context=knowledge_context)
        return self.processor.reduce_deep(text, source_text, knowledge_context=knowledge_context)

    @staticmethod
    def _next_stronger_mode(mode):
        if mode == 'light':
            return 'medium'
        if mode == 'medium':
            return 'deep'
        return None

    def _reduce_until_rate_improves(self, source_text, mode, compare_text, reduce_runner):
        baseline = self.processor.simulate_repeat_risk(source_text, compare_text)
        best_result = reduce_runner(mode)
        best_risk = self.processor.simulate_repeat_risk(best_result, compare_text)
        if best_risk['simulated_rate'] < baseline['simulated_rate']:
            return best_result

        tried_modes = {mode}
        current_mode = mode
        for _ in range(2):
            next_mode = self._next_stronger_mode(current_mode)
            if not next_mode or next_mode in tried_modes:
                break
            tried_modes.add(next_mode)
            current_mode = next_mode
            candidate_result = reduce_runner(next_mode)
            candidate_risk = self.processor.simulate_repeat_risk(candidate_result, compare_text)
            if candidate_risk['simulated_rate'] < best_risk['simulated_rate']:
                best_result = candidate_result
                best_risk = candidate_risk
            if best_risk['simulated_rate'] < baseline['simulated_rate']:
                break
        return best_result

    def _history_operation(self, mode):
        return f'{MODULE_PLAGIARISM}({mode})'

    def _build_completion_info(self, source_text, result_text):
        compare_text = self._get_compare_text()
        before = self.processor.simulate_repeat_risk(source_text, compare_text)
        after = self.processor.simulate_repeat_risk(result_text, compare_text)
        source_hint = '已启用重复源对标' if compare_text else '未导入重复源，按通用模式处理'
        return (
            f'降重完成 | 模拟重复率 {before["simulated_rate"]}% -> {after["simulated_rate"]}% | '
            f'原文{len(source_text)}字 -> 结果{len(result_text)}字 | {source_hint}'
        )

    def _build_diff_summary(self, base_label, base_text, result_text, counts):
        return self._build_plagiarism_summary_text(
            source_label=self.RESULT_SOURCE_LABEL,
            current_text=result_text,
            base_label=base_label,
            base_text=base_text,
            result_text=result_text,
            source_text=self._get_compare_text(),
            counts=counts,
        )

    def _count_diff_characters(self, base_text, result_text):
        counts = {'equal': 0, 'insert': 0, 'delete': 0}
        for tag, segment in self.aux.diff_highlight(base_text, result_text):
            if tag not in counts or not segment:
                continue
            counts[tag] += len(segment)
        return counts

    def _build_plagiarism_summary_text(
        self,
        *,
        source_label,
        current_text,
        base_label='',
        base_text='',
        result_text='',
        source_text='',
        counts=None,
    ):
        current_value = str(current_text or '')
        base_value = str(base_text or '')
        result_value = str(result_text or '')
        source_value = str(source_text or '')

        current_risk = self.processor.simulate_repeat_risk(current_value, source_value) if current_value else None
        base_risk = None
        result_risk = None

        if base_value:
            if current_risk is not None and current_value == base_value:
                base_risk = current_risk
            else:
                base_risk = self.processor.simulate_repeat_risk(base_value, source_value)

        if result_value:
            if current_risk is not None and current_value == result_value:
                result_risk = current_risk
            else:
                result_risk = self.processor.simulate_repeat_risk(result_value, source_value)

        delta = None
        if base_risk and result_risk:
            delta = base_risk['simulated_rate'] - result_risk['simulated_rate']

        similarity = None
        if base_value and result_value:
            similarity = self.processor.compare_similarity(base_value, result_value)

        diff_counts = counts
        if diff_counts is None and base_value and result_value:
            diff_counts = self._count_diff_characters(base_value, result_value)

        reference_risk = current_risk or result_risk or base_risk or {
            'simulated_rate': 0.0,
            'risk_level': '未完成核验',
            'matched_fragments': [],
            'repeated_phrases': [],
            'risk_paragraphs': [],
            'source_overlap': 0.0,
            'token_similarity': 0.0,
        }

        repeat_source_text = '已导入查重报告 / 重复源文本' if source_value else '未导入重复源'
        base_rate_text = f'{base_risk["simulated_rate"]:g}%' if base_risk else '未提供基准'
        current_result_rate_text = f'{result_risk["simulated_rate"]:g}%' if result_risk else '未生成结果'

        if delta is not None:
            delta_text = self._format_repeat_delta(delta)
        elif result_risk:
            delta_text = '未提供基准'
        else:
            delta_text = '待生成结果'

        if source_value:
            source_overlap_text = f'{reference_risk["source_overlap"]:g}%'
            source_similarity_text = f'{reference_risk["token_similarity"]:g}%'
        else:
            source_overlap_text = '未导入重复源'
            source_similarity_text = '未导入重复源'

        if similarity is not None:
            original_result_similarity_text = f'{similarity["similarity"]:g}%'
        elif result_risk:
            original_result_similarity_text = '未提供基准'
        else:
            original_result_similarity_text = '待生成结果'

        base_length_text = str(len(base_value)) if base_value else '未提供原文'
        result_length_text = str(len(result_value)) if result_value else '未生成结果'

        if diff_counts is not None:
            diff_text = f'{diff_counts.get("equal", 0)} / {diff_counts.get("insert", 0)} / {diff_counts.get("delete", 0)}'
        elif result_risk:
            diff_text = '未提供基准'
        else:
            diff_text = '待生成结果'

        lines = [
            f'核验对象：{source_label or "未指定"}',
            f'差异基准：{base_label or "未提供基准"}',
            f'重复源对标：{repeat_source_text}',
            f'基准模拟重复率：{base_rate_text}',
            f'当前结果模拟重复率：{current_result_rate_text}',
            f'重复率变化值：{delta_text}',
            f'当前风险等级：{reference_risk["risk_level"]}',
            f'对重复源重合片段占比：{source_overlap_text}',
            f'对重复源词汇相似度：{source_similarity_text}',
            f'原文-结果词汇相似度：{original_result_similarity_text}',
            f'原文字数与结果字数：{base_length_text} / {result_length_text}',
            f'保留 / 新增 / 删除字符数：{diff_text}',
            f'疑似重复片段数量：{len(reference_risk["matched_fragments"])}',
            f'高频重复短语数量：{len(reference_risk["repeated_phrases"])}',
            f'高风险段落数量：{len(reference_risk["risk_paragraphs"])}',
            (
                '简短处理建议：'
                + self._build_plagiarism_summary_recommendation(
                    reference_risk,
                    base_risk=base_risk,
                    result_risk=result_risk,
                )
            ),
        ]
        return '\n'.join(lines)

    @staticmethod
    def _format_repeat_delta(delta):
        if delta is None:
            return '待生成结果'
        if delta > 0:
            return f'下降 {delta:g} 个百分点'
        if delta < 0:
            return f'上升 {abs(delta):g} 个百分点'
        return '无变化'

    def _build_plagiarism_summary_recommendation(self, current_risk, *, base_risk=None, result_risk=None):
        rate = current_risk['simulated_rate']
        if result_risk is None:
            if rate >= 35:
                return '先补充重复源并优先改写高重合片段。'
            if rate >= 18:
                return '建议先生成降重结果，再复核重复率变化。'
            return '当前风险较低，生成结果后再确认差异统计。'

        if rate >= 35:
            return '风险仍高，建议补充重复源并使用更高强度模式。'
        if base_risk is not None and result_risk['simulated_rate'] >= base_risk['simulated_rate']:
            return '重复率未下降，建议重写高重合片段后重新降重。'
        if rate >= 18:
            return '重复率已有下降，建议继续拆分长句并改写重复短语。'
        return '风险已降至可控范围，建议通读校正引用与术语。'
