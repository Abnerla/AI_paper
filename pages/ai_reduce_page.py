# -*- coding: utf-8 -*-
"""
降 AI 检测页面。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

from modules.ai_reducer import AIReducer
from modules.app_metadata import MODULE_AI_REDUCE
from modules.report_importer import ReportImportEngine
from modules.ui_components import COLORS, FONTS, CardFrame, ModernButton, create_scrolled_text, get_window_work_area
from pages.text_transform_base import TextTransformPageBase


class AIReducePage(TextTransformPageBase):
    PAGE_STATE_ID = 'ai_reduce'
    MODE_CARD_TITLE = 'AI痕迹消除·改写模式'
    MODE_DEFAULT = 'light'
    MODE_OPTIONS = (
        (
            'light',
            '轻度去痕',
            '微调词汇与语序，保留原文 90% 核心内容，快速弱化 AI 高频特征。\n'
            '适用场景：AI 检测率略超标，不想大改原文。',
        ),
        (
            'deep',
            '深度重构',
            '彻底调整句式结构与段落逻辑，保留核心观点，模拟真人写作的思考路径，改写幅度约 60%。\n'
            '适用场景：AI 检测率严重超标、原文模板化严重。',
        ),
        (
            'academic',
            '学术拟合',
            '对标对应学科高质量论文写作习惯，优化表述严谨性，消除 AI 通用化表达。\n'
            '适用场景：需同步提升论文学术质感并规避 AI 检测。',
        ),
    )
    MODE_COLOR_KEY = 'primary'
    MODE_LAYOUT = 'inline_selector'
    MODE_INLINE_ITEM_WIDTH = 248
    MODE_INLINE_ITEM_GAP = 10
    MODE_INLINE_GROUP_GAP = 12
    MODE_INLINE_RIGHT_INSET = 4
    TOP_SECTION_LAYOUT = 'merged_toolbar'
    TOP_SECTION_BREAKPOINT = 1240
    DETECT_SECTION_PLACEMENT = 'preview'
    MERGED_TOP_CARD_TITLE = 'AI痕迹消除'
    MERGED_MODE_LABEL_TEXT = 'A消除模式：'
    MERGED_DETECT_LABEL_TEXT = '结果核验：'
    SHOW_OUTPUT_HEADER_REPLACE_ACTION = True

    ACTION_BUTTON_TEXT = '开始执行'
    ACTION_BUTTON_STYLE = 'primary_fixed'
    ACTION_START_STATUS = 'AI痕迹消除中...'
    ACTION_LOADING_TEXT = '正在执行 AI 痕迹消除...'
    ACTION_SUCCESS_STATUS = 'AI 痕迹消除完成，已写入历史记录'
    ACTION_FAILURE_STATUS = 'AI 痕迹消除失败'
    PROCESS_EMPTY_WARNING = '请先粘贴需要消除 AI 痕迹的论文内容。'

    DETECT_CARD_TITLE = '结果核验'
    DETECT_CARD_HINT = '优先复核当前去痕处理结果；如果尚未执行处理，则默认复核原文输入。'
    DETECT_RESULT_HINT = '完成复核后，可结合下方差异预览一起判断去痕效果。'
    COMPARE_DETECT_COLLAPSIBLE = False
    COMPARE_DETECT_DEFAULT_COLLAPSED = False
    COMPARE_DETECT_HELP_TEXT = '附属功能区，仅用于复核当前去痕结果；不影响上方模式选择与主流程执行。'
    COMPARE_DETECT_COLLAPSED_HINT = '默认收起，按需展开去痕效果复核。'
    PRIMARY_ANALYSIS_BUTTON_TEXT = '结果复核'
    PRIMARY_ANALYSIS_BUTTON_STYLE = 'primary_fixed'
    PREVIEW_REFRESH_BUTTON_TEXT = '刷新'
    SECONDARY_ANALYSIS_BUTTON_TEXT = '逻辑流畅度检测'
    PRIMARY_ANALYSIS_EMPTY_WARNING = '请先输入待处理原文或生成去痕处理结果。'
    ANALYSIS_STATUS_READY_TEXT = '请选择结果核验动作'
    STALE_ANALYSIS_TEXT = '内容已更新，请重新执行去痕效果复核或刷新差异视图。'
    STALE_PREVIEW_TEXT = '内容已更新，请点击“刷新差异视图”重新生成原文与结果的差异预览。'

    INPUT_CARD_TITLE = '待处理原文'
    INPUT_PLACEHOLDER = '请粘贴需要消除AI痕迹的论文段落/全文，支持单独选中段落分段处理。'
    OUTPUT_CARD_TITLE = '去痕处理结果'
    OUTPUT_PLACEHOLDER = '处理完成后，结果将显示在此处，支持在线编辑微调。'

    COMPARE_SECTION_TITLE = '结果核验与差异预览'
    COMPARE_SECTION_DESCRIPTION = ''
    COMPARE_SECTION_COLLAPSIBLE = True
    COMPARE_SECTION_DEFAULT_COLLAPSED = True
    COMPARE_TEXT_USED_FOR_DIFF_BASELINE = False

    PREVIEW_CARD_TITLE = ''
    PREVIEW_LEGEND_TEXT = '绿色=新增、红色=删除、灰色=保留'
    PREVIEW_LEGEND_ITEMS = (
        ('绿色', '= 新增', 'success'),
        ('红色', '= 删除', 'error'),
        ('灰色', '= 保留', 'neutral'),
    )
    SUMMARY_TITLE = '检测结果摘要'
    SUMMARY_PLACEHOLDER_TEXT = '完成去痕效果复核后，此处将展示 AI 生成概率、去痕效果评估与核心问题汇总。'
    PREVIEW_TITLE = '差异预览'
    PREVIEW_EMPTY_TEXT = '点击“刷新差异视图”，即可查看原文与处理结果的逐句差异对比。'
    PREVIEW_MISSING_TEXT = '请先准备原文与去痕处理结果。'

    REPLACE_BUTTON_TEXT = '回填到原文区'
    REPLACE_EMPTY_WARNING = '当前没有可回填的去痕处理结果。'
    REPLACE_INFO_TEXT = '已将去痕处理结果回填到原文区，可继续微调或重新核验。'
    IMPORT_DIALOG_TITLE = '导入报告'
    IMPORT_DIALOG_BUTTON_TEXT = '导入报告'
    IMPORT_DIALOG_DESCRIPTION = '导入 AIGC 检测报告后，系统会自动解析并对原文区正文完成初次标注。'
    IMPORT_DIALOG_PLACEHOLDER = '导入后可在原文区直接修正标注'

    INPUT_SOURCE_LABEL = '原文输入'
    RESULT_SOURCE_LABEL = '去痕处理结果'

    MODULE_NAME = MODULE_AI_REDUCE
    PROMPT_PAGE_ID = 'ai_reduce'
    PROMPT_SCENE_ID = 'ai_reduce.transform'

    def __init__(self, parent, config_mgr, api_client, history_mgr, set_status, navigate_page=None, app_bridge=None):
        self._import_dialog = None
        self._import_status_label = None
        self.report_importer = None
        super().__init__(
            parent,
            config_mgr,
            api_client,
            history_mgr,
            set_status,
            AIReducer(api_client),
            navigate_page=navigate_page,
            app_bridge=app_bridge,
            loading_text='正在执行 AI 痕迹消除...',
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
            (self.IMPORT_DIALOG_BUTTON_TEXT, 'secondary', self._open_import_dialog),
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
        self._ensure_import_dialog()

    def _build_compare_preview_cards(self, parent):
        left_card = CardFrame(parent)
        self._build_ai_compare_summary_card(left_card.inner)

        right_card = CardFrame(parent)
        self._build_ai_diff_preview_card(right_card.inner)

        parent.grid_columnconfigure(0, weight=3, minsize=0, uniform='ai_reduce_compare_preview')
        parent.grid_columnconfigure(1, weight=7, minsize=0, uniform='ai_reduce_compare_preview')
        parent.grid_rowconfigure(0, weight=1)
        left_card.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        right_card.grid(row=0, column=1, sticky='nsew')

    def _build_ai_compare_summary_card(self, parent):
        self._build_analysis_summary_section(
            parent,
            title=self.SUMMARY_TITLE,
            frame_pady=(8, 0),
            height=16,
            fill=tk.BOTH,
            expand=True,
        )

    def _build_ai_diff_preview_card(self, parent):
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

    def _ensure_import_dialog(self):
        dialog = self._import_dialog
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    return dialog
            except tk.TclError:
                pass

        root = self.frame.winfo_toplevel()
        dialog = tk.Toplevel(root)
        dialog.withdraw()
        dialog.title(self.IMPORT_DIALOG_TITLE)
        dialog.transient(root)
        dialog.configure(bg=COLORS['bg_main'])
        dialog.minsize(680, 420)
        dialog.protocol('WM_DELETE_WINDOW', self._close_import_dialog)
        dialog.bind('<Escape>', lambda _event: self._close_import_dialog(), add='+')

        shell = tk.Frame(dialog, bg=COLORS['bg_main'])
        shell.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        card = CardFrame(shell, title=self.IMPORT_DIALOG_TITLE)
        card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            card.inner,
            text=self.IMPORT_DIALOG_DESCRIPTION,
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
            text='支持导入 AIGC 检测报告的 PDF 打印版、Word 颜色标记版。',
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

        self._import_status_label = tk.Label(
            placeholder,
            text='导入后系统会先完成初次自动标注，随后可在原文区直接修正。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['surface_alt'],
            justify='left',
            anchor='center',
            wraplength=520,
        )
        self._import_status_label.pack(fill=tk.X, padx=20, pady=(14, 28))

        footer = tk.Frame(card.inner, bg=COLORS['card_bg'])
        footer.pack(fill=tk.X, pady=(12, 0))

        ModernButton(
            footer,
            '关闭',
            style='ghost',
            command=self._close_import_dialog,
            padx=14,
            pady=8,
        ).pack(side=tk.RIGHT)

        self._import_dialog = dialog
        return dialog

    def _open_import_dialog(self):
        dialog = self._ensure_import_dialog()
        self._center_import_dialog(dialog)
        dialog.deiconify()
        dialog.lift()
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

    def _close_import_dialog(self):
        dialog = self._import_dialog
        if dialog is None:
            return
        self._import_dialog = None
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        try:
            if dialog.winfo_exists():
                dialog.withdraw()
        except tk.TclError:
            pass

    def _center_import_dialog(self, dialog):
        root = self.frame.winfo_toplevel()
        root.update_idletasks()
        dialog.update_idletasks()

        width = max(dialog.winfo_reqwidth(), 720)
        height = max(dialog.winfo_reqheight(), 460)
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
        dialog = self._import_dialog
        if dialog is None:
            return
        try:
            if dialog.winfo_exists():
                dialog.destroy()
        except tk.TclError:
            pass
        self._import_dialog = None
        self._import_status_label = None

    def _set_import_dialog_status(self, text, *, color=None):
        if self._import_status_label is None:
            return
        self._import_status_label.configure(
            text=text,
            fg=color or COLORS['text_sub'],
        )

    def _choose_import_report_file(self):
        source_text = self._get_input_text()
        if not source_text:
            messagebox.showwarning('提示', '请先在原文区准备论文正文，再导入 AIGC 检测报告。', parent=self._import_dialog or self.frame)
            return

        path = filedialog.askopenfilename(
            filetypes=[('报告文件', '*.pdf *.docx'), ('PDF', '*.pdf'), ('Word 文档', '*.docx')],
            parent=self._import_dialog or self.frame,
        )
        if not path:
            return

        def on_start():
            self._set_import_dialog_status(f'正在解析报告：{path}', color=COLORS['warning'])

        def on_success(session):
            notes = '；'.join(session.parse_notes[:2]) if session.parse_notes else '已完成初次自动标注。'
            self._apply_import_session(
                session,
                info_text=(
                    f'报告导入完成：{session.file_name} | 已初次标注 {session.matched_count}/{session.total_body_paragraphs} 个正文段落'
                ),
            )
            self._set_import_dialog_status(notes, color=COLORS['success'])
            self.set_status('AIGC 报告导入完成', COLORS['success'])
            if self.config and hasattr(self.config, 'clear_home_last_import_failure'):
                self.config.clear_home_last_import_failure()
                self.config.save()

        def on_error(exc):
            if self.config and hasattr(self.config, 'set_home_last_import_failure'):
                self.config.set_home_last_import_failure('ai_reduce', os.path.basename(path), str(exc))
                self.config.save()
            self._set_import_dialog_status(f'导入失败：{exc}', color=COLORS['error'])
            messagebox.showerror('导入失败', str(exc), parent=self._import_dialog or self.frame)

        self.task_runner.run(
            work=lambda: self.report_importer.parse_in_subprocess(path, self.PAGE_STATE_ID, source_text),
            on_success=on_success,
            on_error=on_error,
            on_start=on_start,
            loading_text='正在解析 AIGC 检测报告...',
            status_text='正在解析 AIGC 检测报告...',
            status_color=COLORS['warning'],
        )

    def _analyze_text(self, text, source_label):
        baseline_text = self._get_input_text()
        current_result = self._get_result_text()
        summary_text = self._build_ai_summary_text(
            source_label=source_label,
            current_text=text,
            base_label=self.INPUT_SOURCE_LABEL if baseline_text else '',
            base_text=baseline_text,
            result_text=current_result,
        )

        result = self.processor.scan_ai_features(text)
        color = COLORS['error'] if result['score'] >= 30 else COLORS['warning'] if result['score'] >= 15 else COLORS['success']
        status_text = f'去痕效果复核完成，当前核验对象为“{source_label}”。'
        return summary_text, status_text, color

    def _analyze_secondary_text(self, text, source_label):
        result = self.processor.check_logic_flow(text)
        lines = [
            f'核验对象：{source_label}',
            f'逻辑流畅度评分：{result["flow_score"]}/100',
            f'段落数：{result["paragraph_count"]}',
            f'句子数：{result["sentence_count"]}',
            f'过渡词命中：{result["transition_hits"]} 次（句均 {result["transition_rate"]}）',
            f'超长句数量：{result["long_sentence_count"]}',
        ]

        if result['issues']:
            lines.extend(['', '逻辑问题提示：'])
            lines.extend(f'  - {item}' for item in result['issues'])
        else:
            lines.extend(['', '逻辑流畅度检测通过，未发现明显跳跃或断裂。'])

        if result['focus_segments']:
            lines.extend(['', '建议重点复核片段：'])
            lines.extend(f'  - {item}' for item in result['focus_segments'])

        color = COLORS['warning'] if result['flow_score'] < 75 else COLORS['success']
        status_text = f'逻辑流畅度检测完成，当前核验对象为“{source_label}”。'
        return '\n'.join(lines), status_text, color

    def _transform_text(self, text, mode):
        kc = getattr(self, '_pending_knowledge_context', None)
        return self._rewrite_until_score_improves(
            text,
            mode,
            rewrite_runner=lambda selected_mode: self._rewrite_text_by_mode(text, selected_mode, kc),
        )

    def _transform_with_annotations(self, text, mode, annotations):
        kc = getattr(self, '_pending_knowledge_context', None)
        return self._rewrite_until_score_improves(
            text,
            mode,
            rewrite_runner=lambda selected_mode: self.processor.rewrite_with_annotations(text, annotations, selected_mode, knowledge_context=kc),
        )

    def _rewrite_text_by_mode(self, text, mode, knowledge_context=None):
        if mode == 'light':
            return self.processor.rewrite_light(text, knowledge_context=knowledge_context)
        if mode == 'deep':
            return self.processor.rewrite_deep(text, knowledge_context=knowledge_context)
        return self.processor.rewrite_academic(text, knowledge_context=knowledge_context)

    @staticmethod
    def _next_stronger_mode(mode):
        if mode == 'light':
            return 'academic'
        if mode == 'academic':
            return 'deep'
        return None

    def _rewrite_until_score_improves(self, source_text, mode, rewrite_runner):
        baseline = self.processor.scan_ai_features(source_text)
        best_result = rewrite_runner(mode)
        best_scan = self.processor.scan_ai_features(best_result)
        if best_scan['score'] < baseline['score']:
            return best_result

        tried_modes = {mode}
        current_mode = mode
        for _ in range(2):
            next_mode = self._next_stronger_mode(current_mode)
            if not next_mode or next_mode in tried_modes:
                break
            tried_modes.add(next_mode)
            current_mode = next_mode
            candidate_result = rewrite_runner(next_mode)
            candidate_scan = self.processor.scan_ai_features(candidate_result)
            if candidate_scan['score'] < best_scan['score']:
                best_result = candidate_result
                best_scan = candidate_scan
            if best_scan['score'] < baseline['score']:
                break
        return best_result

    def _history_operation(self, mode):
        return f'{MODULE_AI_REDUCE}({mode})'

    def _build_completion_info(self, source_text, result_text):
        source_scan = self.processor.scan_ai_features(source_text)
        result_scan = self.processor.scan_ai_features(result_text)
        delta = source_scan['score'] - result_scan['score']
        return (
            f'AI 痕迹消除完成 | 风险分 {source_scan["score"]} -> {result_scan["score"]} | '
            f'原文{len(source_text)}字 -> 结果{len(result_text)}字 | 效果评估：{self._describe_ai_improvement(delta)}'
        )

    def _build_diff_summary(self, base_label, base_text, result_text, counts):
        return self._build_ai_summary_text(
            source_label=self.RESULT_SOURCE_LABEL,
            current_text=result_text,
            base_label=base_label,
            base_text=base_text,
            result_text=result_text,
            counts=counts,
        )

    def _count_diff_characters(self, base_text, result_text):
        counts = {'equal': 0, 'insert': 0, 'delete': 0}
        for tag, segment in self.aux.diff_highlight(base_text, result_text):
            if tag not in counts or not segment:
                continue
            counts[tag] += len(segment)
        return counts

    def _build_ai_summary_text(
        self,
        *,
        source_label,
        current_text,
        base_label='',
        base_text='',
        result_text='',
        counts=None,
    ):
        current_value = str(current_text or '')
        base_value = str(base_text or '')
        result_value = str(result_text or '')

        current_scan = self.processor.scan_ai_features(current_value) if current_value else None
        base_scan = None
        result_scan = None

        if base_value:
            if current_scan is not None and current_value == base_value:
                base_scan = current_scan
            else:
                base_scan = self.processor.scan_ai_features(base_value)

        if result_value:
            if current_scan is not None and current_value == result_value:
                result_scan = current_scan
            else:
                result_scan = self.processor.scan_ai_features(result_value)

        delta = None
        if base_scan and result_scan:
            delta = base_scan['score'] - result_scan['score']

        diff_counts = counts
        if diff_counts is None and base_value and result_value:
            diff_counts = self._count_diff_characters(base_value, result_value)

        if result_scan:
            current_result_score_text = f'{result_scan["score"]}/100'
            probability_text = f'{self._estimate_ai_probability(result_scan["score"])}%'
        else:
            current_result_score_text = '未生成结果'
            probability_text = '未生成结果'

        if base_scan:
            base_score_text = f'{base_scan["score"]}/100'
        else:
            base_score_text = '未提供基准'

        if delta is not None:
            delta_text = self._format_ai_delta(delta)
            effect_text = self._describe_ai_improvement(delta)
        elif result_scan:
            delta_text = '未提供基准'
            effect_text = '已生成结果，但缺少基准对比。'
        else:
            delta_text = '待生成结果'
            effect_text = '尚未生成去痕结果，当前为原文复核。'

        if diff_counts is not None:
            diff_text = f'{diff_counts.get("equal", 0)} / {diff_counts.get("insert", 0)} / {diff_counts.get("delete", 0)}'
        elif result_scan:
            diff_text = '未提供基准'
        else:
            diff_text = '待生成结果'

        if base_value:
            base_length_text = str(len(base_value))
        else:
            base_length_text = '未提供原文'
        result_length_text = str(len(result_value)) if result_value else '未生成结果'

        reference_scan = current_scan or result_scan or base_scan or {
            'score': 0,
            'features': [],
            'sentences_flagged': [],
            'risk_level': '未完成核验',
        }

        lines = [
            f'核验对象：{source_label or "未指定"}',
            f'差异基准：{base_label or "未提供基准"}',
            f'基准 AI 风险分：{base_score_text}',
            f'当前结果 AI 风险分：{current_result_score_text}',
            f'风险分变化值：{delta_text}',
            f'当前结果估算 AI 生成概率：{probability_text}',
            f'当前风险等级：{reference_scan["risk_level"]}',
            f'去痕效果评估：{effect_text}',
            f'原文字数与结果字数：{base_length_text} / {result_length_text}',
            f'保留 / 新增 / 删除字符数：{diff_text}',
            f'命中 AI 痕迹数量：{len(reference_scan["features"])}',
            f'重点句段数量：{len(reference_scan["sentences_flagged"])}',
            (
                '简短处理建议：'
                + self._build_ai_summary_recommendation(
                    reference_scan,
                    base_scan=base_scan,
                    result_scan=result_scan,
                )
            ),
        ]
        return '\n'.join(lines)

    @staticmethod
    def _format_ai_delta(delta):
        if delta is None:
            return '待生成结果'
        if delta > 0:
            return f'下降 {delta} 分'
        if delta < 0:
            return f'上升 {abs(delta)} 分'
        return '无变化'

    def _build_ai_summary_recommendation(self, current_scan, *, base_scan=None, result_scan=None):
        score = current_scan['score']
        if result_scan is None:
            if score >= 30:
                return '先执行去痕处理，再优先重写高风险句段。'
            if score >= 15:
                return '建议先生成去痕结果，再复核风险分变化。'
            return '当前风险不高，建议生成结果后再查看差异统计。'

        if score >= 30:
            return '风险仍高，建议改用更高强度模式并重写重点句段。'
        if base_scan is not None and result_scan['score'] >= base_scan['score']:
            return '风险未下降，建议切换更高强度模式后重新处理。'
        if score >= 15:
            return '风险已有下降，建议继续人工打散模板化表达。'
        return '风险已降至可控范围，建议通读校正术语和引用。'

    @staticmethod
    def _estimate_ai_probability(score):
        return max(6, min(98, round(score * 2.6)))

    @staticmethod
    def _describe_ai_improvement(delta):
        if delta >= 12:
            return '去痕效果明显'
        if delta >= 5:
            return '去痕效果较好'
        if delta >= 1:
            return '去痕效果有限'
        if delta == 0:
            return '风险分无变化'
        return '风险分反而上升'
