# -*- coding: utf-8 -*-
"""
论文写作页面
"""

import os
import re
import json
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

from modules.aux_tools import AuxTools
from modules.app_metadata import MODULE_PAPER_WRITE
from modules.paper_writer import PaperWriter
from modules.table_blocks import (
    TABLE_ALIGN_CENTER,
    TABLE_ALIGN_LEFT,
    TABLE_ALIGN_RIGHT,
    TABLE_STYLE_GRID,
    TABLE_STYLE_THREE_LINE,
    blocks_from_plain_text,
    blocks_to_plain_text,
    clear_table_cells,
    calculate_table_column_widths,
    deep_copy_blocks,
    delete_table_alignment_columns,
    delete_table_alignment_rows,
    delete_table_columns_with_merges,
    delete_table_rows_with_merges,
    expand_selection_range_for_merges,
    insert_table_alignment_columns,
    insert_table_alignment_rows,
    insert_table_columns_with_merges,
    insert_table_rows_with_merges,
    merge_table_cells,
    new_paragraph_block,
    new_table_block,
    normalize_table_alignments,
    normalize_table_alignment,
    normalize_merged_cells,
    normalize_table_style,
    normalize_table_pixel_sizes,
    sanitize_blocks,
    set_table_cell_alignment,
    unmerge_table_cells,
)
from pages.home_support import ensure_model_configured
from modules.prompt_center import PromptCenter
from modules.task_runner import TaskRunner
from modules.ui_components import (
    COLORS,
    FONTS,
    CardFrame,
    apply_mixed_fonts,
    create_home_shell_button,
    LoadingOverlay,
    ModernButton,
    bind_responsive_two_pane,
    create_scrolled_text,
    get_resource_path,
    load_image,
    refresh_home_shell_button,
    show_tooltip,
    THEMES,
)
from modules.workspace_state import WorkspaceStateMixin


class _TableBlockWidget:
    CELL_WIDTH = 18
    CELL_MIN_PIXEL_WIDTH = 96
    CELL_MAX_PIXEL_WIDTH = 360
    CELL_PADDING_X = 18
    CELL_TEXT_PAD_X = 4
    CELL_TEXT_RIGHT_MARGIN = 24
    CELL_COLUMN_SAFETY_PADDING = 24
    CELL_READABLE_MAX_PIXEL_WIDTH = 148
    CELL_GRID_PAD_X = 1
    CELL_GRID_IPAD_X = 1
    SELECTOR_PIXEL_WIDTH = 36
    TABLE_SHELL_PAD_X = 6
    TABLE_EDITOR_RIGHT_GAP = 48
    TABLE_GRID_RIGHT_INSET = 18
    CELL_MIN_HEIGHT = 2
    ROW_MIN_PIXEL_HEIGHT = 28
    RESIZE_HIT_MARGIN = 6
    ROW_SELECTOR_WIDTH = 3
    COL_SELECTOR_HEIGHT = 1

    def __init__(self, parent, block, on_change=None, on_delete=None, on_activate=None, viewport_parent=None):
        self.parent = parent
        self.viewport_parent = viewport_parent or parent
        self.on_change = on_change or (lambda: None)
        self.on_delete = on_delete or (lambda _editor: None)
        self.on_activate = on_activate or (lambda _editor: None)
        self.block_id = str((block or {}).get('table_id', '') or os.urandom(6).hex())
        self.has_header = bool((block or {}).get('has_header', True))
        self.caption_var = tk.StringVar(value=str((block or {}).get('caption', '') or ''))
        self.rows = self._normalize_rows((block or {}).get('rows', []))
        self.merged_cells = normalize_merged_cells(
            (block or {}).get('merged_cells', []),
            len(self.rows),
            len(self.rows[0]) if self.rows else 1,
        )
        self.table_style = normalize_table_style((block or {}).get('table_style', TABLE_STYLE_GRID))
        self.cell_alignments = normalize_table_alignments(
            (block or {}).get('cell_alignments', []),
            len(self.rows),
            len(self.rows[0]) if self.rows else 1,
        )
        self.manual_column_widths = normalize_table_pixel_sizes(
            (block or {}).get('column_widths', []),
            len(self.rows[0]) if self.rows else 1,
            min_value=self.CELL_MIN_PIXEL_WIDTH,
        )
        self.manual_row_heights = normalize_table_pixel_sizes(
            (block or {}).get('row_heights', []),
            len(self.rows),
            min_value=self.ROW_MIN_PIXEL_HEIGHT,
        )
        self.selection_mode = 'cell'
        self.selected_row = 0
        self.selected_col = 0
        self.selected_row_range = (0, 0)
        self.selected_col_range = (0, 0)
        self.hover_mode = ''
        self.hover_index = None
        self._drag_select_mode = ''
        self._drag_anchor_index = None
        self._cell_drag_anchor = None
        self._floating_toolbar = None
        self._floating_toolbar_root_bind = None
        self._covered_cells = {}
        self._merge_by_anchor = {}
        self._column_widths = []
        self._last_layout_width = 0
        self._layout_after_id = None
        self._parent_configure_bind = None
        self._resize_state = None
        self._resize_hover = None
        self._resize_cursor_widget = None
        self._drag_icon_window = None
        self._drag_icon_label = None
        self._drag_icon_image = None
        self.window_frame = None

        self.frame = tk.Frame(
            parent,
            bg=COLORS['surface_alt'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        self.frame._table_block_editor = self

        self._build_shell()
        self._render_grid()
        self.frame.bind('<Configure>', self._on_layout_configure, add='+')
        try:
            self._parent_configure_bind = self.viewport_parent.bind('<Configure>', self._on_layout_configure, add='+')
        except Exception:
            self._parent_configure_bind = None

    @staticmethod
    def _normalize_table_text(value):
        return re.sub(r'\s+', ' ', str(value or '').replace('\r', ' ').replace('\n', ' ')).strip()

    @staticmethod
    def _normalize_rows(rows):
        normalized = []
        max_cols = 0
        if not isinstance(rows, list):
            rows = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                normalized_row = [_TableBlockWidget._normalize_table_text(cell) for cell in row]
            else:
                normalized_row = [_TableBlockWidget._normalize_table_text(row)]
            max_cols = max(max_cols, len(normalized_row))
            normalized.append(normalized_row)
        if not normalized:
            normalized = [['', ''], ['', '']]
            return normalized
        max_cols = max(1, max_cols)
        for row in normalized:
            if len(row) < max_cols:
                row.extend([''] * (max_cols - len(row)))
        return normalized

    def _build_shell(self):
        caption_row = tk.Frame(self.frame, bg=COLORS['surface_alt'])
        caption_row.pack(fill=tk.X, padx=6, pady=(6, 6))
        tk.Label(
            caption_row,
            text='表题',
            font=FONTS['tiny'],
            fg=COLORS['text_sub'],
            bg=COLORS['surface_alt'],
        ).pack(side=tk.LEFT)
        caption_entry = tk.Entry(
            caption_row,
            textvariable=self.caption_var,
            font=FONTS['small'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
        )
        caption_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), ipady=2)
        caption_entry.bind('<KeyRelease>', lambda _event: self._notify_change())
        self.caption_entry = caption_entry

        self.grid_shell = tk.Frame(self.frame, bg=COLORS['surface_alt'])
        self.grid_shell.pack(fill=tk.X, padx=6, pady=(0, 6))
        try:
            self.grid_shell.grid_propagate(False)
        except tk.TclError:
            pass

    def _normalize_cell_text(self, value):
        return self._normalize_table_text(value)

    def _cell_text(self, widget):
        try:
            if isinstance(widget, tk.Text):
                return widget.get('1.0', 'end-1c')
            return widget.get()
        except tk.TclError:
            return ''

    def _sync_rows_from_widgets(self):
        if not hasattr(self, '_cell_widgets'):
            return
        for row_idx, row_widgets in enumerate(self._cell_widgets):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists():
                    continue
                self.rows[row_idx][col_idx] = self._normalize_cell_text(self._cell_text(widget))

    def _row_count(self):
        return len(self.rows)

    def _col_count(self):
        return max(len(row) for row in self.rows) if self.rows else 1

    def _normalize_current_merges(self):
        self.merged_cells = normalize_merged_cells(
            self.merged_cells,
            self._row_count(),
            self._col_count(),
        )

    def _normalize_current_alignments(self):
        self.cell_alignments = normalize_table_alignments(
            self.cell_alignments,
            self._row_count(),
            self._col_count(),
        )

    def _build_merge_maps(self):
        self._normalize_current_merges()
        self._normalize_current_alignments()
        covered = {}
        anchors = {}
        for cell in self.merged_cells:
            row = cell['row']
            col = cell['col']
            anchors[(row, col)] = cell
            for row_idx in range(row, row + cell['rowspan']):
                for col_idx in range(col, col + cell['colspan']):
                    if row_idx == row and col_idx == col:
                        continue
                    covered[(row_idx, col_idx)] = (row, col)
        self._covered_cells = covered
        self._merge_by_anchor = anchors

    def _merge_for_cell(self, row_idx, col_idx):
        anchor = self._covered_cells.get((row_idx, col_idx), (row_idx, col_idx))
        return self._merge_by_anchor.get(anchor)

    def _cell_selection_bounds(self, row_idx, col_idx):
        merged = self._merge_for_cell(row_idx, col_idx)
        if not merged:
            return row_idx, row_idx, col_idx, col_idx
        row = merged['row']
        col = merged['col']
        return row, row + merged['rowspan'] - 1, col, col + merged['colspan'] - 1

    def _expanded_cell_range(self, anchor, target):
        anchor_bounds = self._cell_selection_bounds(anchor[0], anchor[1])
        target_bounds = self._cell_selection_bounds(target[0], target[1])
        row_range = (
            min(anchor_bounds[0], target_bounds[0]),
            max(anchor_bounds[1], target_bounds[1]),
        )
        col_range = (
            min(anchor_bounds[2], target_bounds[2]),
            max(anchor_bounds[3], target_bounds[3]),
        )
        return expand_selection_range_for_merges(
            row_range,
            col_range,
            self.merged_cells,
            self._row_count(),
            self._col_count(),
        )

    def _set_selected_cell_range(self, anchor, target):
        self.on_activate(self)
        if not self.rows:
            return
        anchor = (
            max(0, min(int(anchor[0]), self._row_count() - 1)),
            max(0, min(int(anchor[1]), self._col_count() - 1)),
        )
        target = (
            max(0, min(int(target[0]), self._row_count() - 1)),
            max(0, min(int(target[1]), self._col_count() - 1)),
        )
        row_range, col_range = self._expanded_cell_range(anchor, target)
        self.selection_mode = 'cell'
        self.selected_row = row_range[0]
        self.selected_col = col_range[0]
        self.selected_row_range = row_range
        self.selected_col_range = col_range
        self._refresh_selection_style()

    def _selection_has_merge(self):
        row_range, col_range = self._current_content_range()
        for merged in self.merged_cells:
            row_start = merged['row']
            row_end = row_start + merged['rowspan'] - 1
            col_start = merged['col']
            col_end = col_start + merged['colspan'] - 1
            if row_start <= row_range[1] and row_range[0] <= row_end and col_start <= col_range[1] and col_range[0] <= col_end:
                return True
        return False

    def _current_content_range(self):
        if self.selection_mode == 'table':
            return (0, max(self._row_count() - 1, 0)), (0, max(self._col_count() - 1, 0))
        if self.selection_mode == 'row':
            return self._current_row_range(), (0, max(self._col_count() - 1, 0))
        if self.selection_mode == 'column':
            return (0, max(self._row_count() - 1, 0)), self._current_col_range()
        return self._current_row_range(), self._current_col_range()

    def _data_grid_row(self, row_idx):
        if self.table_style == TABLE_STYLE_THREE_LINE:
            return row_idx * 2 + 2
        return row_idx + 1

    def _data_rowspan(self, rowspan):
        if self.table_style == TABLE_STYLE_THREE_LINE:
            return max(1, int(rowspan) * 2 - 1)
        return max(1, int(rowspan))

    def _normalize_range(self, start, end, limit):
        if limit <= 0:
            return 0, 0
        try:
            start = int(start)
        except Exception:
            start = 0
        try:
            end = int(end)
        except Exception:
            end = start
        if start > end:
            start, end = end, start
        return max(0, min(start, limit - 1)), max(0, min(end, limit - 1))

    def _current_row_range(self):
        if self.selection_mode == 'table':
            return 0, max(self._row_count() - 1, 0)
        if self.selection_mode == 'row':
            return self._normalize_range(self.selected_row_range[0], self.selected_row_range[1], self._row_count())
        return self._normalize_range(self.selected_row_range[0], self.selected_row_range[1], self._row_count())

    def _current_col_range(self):
        if self.selection_mode == 'table':
            return 0, max(self._col_count() - 1, 0)
        if self.selection_mode == 'column':
            return self._normalize_range(self.selected_col_range[0], self.selected_col_range[1], self._col_count())
        return self._normalize_range(self.selected_col_range[0], self.selected_col_range[1], self._col_count())

    def _selected_row_count(self):
        start, end = self._current_row_range()
        return max(1, end - start + 1)

    def _selected_col_count(self):
        start, end = self._current_col_range()
        return max(1, end - start + 1)

    def _set_selected_cell(self, row_idx, col_idx):
        self.on_activate(self)
        if not self.rows:
            self.selected_row = 0
            self.selected_col = 0
            return
        row = max(0, min(int(row_idx), len(self.rows) - 1))
        col = max(0, min(int(col_idx), len(self.rows[0]) - 1))
        self._set_selected_cell_range((row, col), (row, col))
        self._destroy_floating_toolbar()

    def _set_selected_row(self, row_idx, end_idx=None, show_toolbar=True):
        self.on_activate(self)
        self.selection_mode = 'row'
        start, end = self._normalize_range(row_idx, row_idx if end_idx is None else end_idx, self._row_count())
        self.selected_row_range = (start, end)
        self.selected_row = start
        self.selected_col = max(0, min(self.selected_col, self._col_count() - 1))
        self._refresh_selection_style()
        if show_toolbar:
            self._show_floating_toolbar()

    def _set_selected_column(self, col_idx, end_idx=None, show_toolbar=True):
        self.on_activate(self)
        self.selection_mode = 'column'
        start, end = self._normalize_range(col_idx, col_idx if end_idx is None else end_idx, self._col_count())
        self.selected_col_range = (start, end)
        self.selected_col = start
        self.selected_row = max(0, min(self.selected_row, self._row_count() - 1))
        self._refresh_selection_style()
        if show_toolbar:
            self._show_floating_toolbar()

    def _set_selected_table(self, show_toolbar=True):
        self.on_activate(self)
        self.selection_mode = 'table'
        self.selected_row_range = (0, max(self._row_count() - 1, 0))
        self.selected_col_range = (0, max(self._col_count() - 1, 0))
        self.selected_row = 0
        self.selected_col = 0
        self._refresh_selection_style()
        if show_toolbar:
            self._show_floating_toolbar()

    def _set_hover(self, mode, index=None):
        self.hover_mode = mode
        self.hover_index = index
        self._refresh_selection_style()

    def _clear_hover(self, mode=None, index=None):
        if mode is not None and self.hover_mode != mode:
            return
        if index is not None and self.hover_index != index:
            return
        self.hover_mode = ''
        self.hover_index = None
        self._refresh_selection_style()

    def _is_cell_selected(self, row_idx, col_idx):
        row_start, row_end, col_start, col_end = self._cell_selection_bounds(row_idx, col_idx)
        if self.selection_mode == 'table':
            return True
        if self.selection_mode == 'row':
            selected_start, selected_end = self.selected_row_range
            return row_start <= selected_end and selected_start <= row_end
        if self.selection_mode == 'column':
            selected_start, selected_end = self.selected_col_range
            return col_start <= selected_end and selected_start <= col_end
        selected_row_start, selected_row_end = self.selected_row_range
        selected_col_start, selected_col_end = self.selected_col_range
        return (
            row_start <= selected_row_end
            and selected_row_start <= row_end
            and col_start <= selected_col_end
            and selected_col_start <= col_end
        )

    def _cell_alignment(self, row_idx, col_idx):
        try:
            return normalize_table_alignment(self.cell_alignments[row_idx][col_idx])
        except Exception:
            return TABLE_ALIGN_LEFT

    def _cell_justify(self, row_idx, col_idx):
        alignment = self._cell_alignment(row_idx, col_idx)
        if alignment == TABLE_ALIGN_CENTER:
            return tk.CENTER
        if alignment == TABLE_ALIGN_RIGHT:
            return tk.RIGHT
        return tk.LEFT

    def _text_font(self):
        try:
            return tkfont.Font(root=self.frame, font=FONTS['small'])
        except Exception:
            return tkfont.Font(font=FONTS['small'])

    def _font_metrics(self):
        font = self._text_font()
        line_height = max(12, int(font.metrics('linespace') or 16))
        char_width = max(1, int(font.measure('M') or 8))
        return font, line_height, char_width

    def _load_drag_icon_image(self):
        if self._drag_icon_image is not None:
            return self._drag_icon_image
        try:
            self._drag_icon_image = load_image('png/Drag.png', max_size=(24, 24))
        except Exception:
            self._drag_icon_image = None
        return self._drag_icon_image

    def _show_drag_icon(self, event):
        image = self._load_drag_icon_image()
        if image is None:
            return
        if self._drag_icon_window is None or not self._drag_icon_window.winfo_exists():
            try:
                window = tk.Toplevel(self.frame)
                window.overrideredirect(True)
                window.attributes('-topmost', True)
                label = tk.Label(window, image=image, bd=0, bg=COLORS['surface_alt'])
                label.pack()
                self._drag_icon_window = window
                self._drag_icon_label = label
            except Exception:
                self._drag_icon_window = None
                return
        try:
            self._drag_icon_window.geometry(f'+{int(event.x_root) + 10}+{int(event.y_root) + 10}')
            self._drag_icon_window.deiconify()
            self._drag_icon_window.lift()
        except Exception:
            pass

    def _hide_drag_icon(self):
        window = getattr(self, '_drag_icon_window', None)
        if window is not None and window.winfo_exists():
            try:
                window.withdraw()
            except tk.TclError:
                pass

    def _destroy_drag_icon(self):
        window = getattr(self, '_drag_icon_window', None)
        if window is not None and window.winfo_exists():
            try:
                window.destroy()
            except tk.TclError:
                pass
        self._drag_icon_window = None
        self._drag_icon_label = None

    def _set_resize_cursor(self, widget, cursor):
        previous = getattr(self, '_resize_cursor_widget', None)
        if previous is not None and previous is not widget and previous.winfo_exists():
            self._restore_resize_cursor(previous)
        self._resize_cursor_widget = widget
        try:
            if not hasattr(widget, '_table_default_cursor'):
                widget._table_default_cursor = widget.cget('cursor')
            widget.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _restore_resize_cursor(self, widget=None):
        target = widget or getattr(self, '_resize_cursor_widget', None)
        if target is not None and target.winfo_exists():
            try:
                target.configure(cursor=getattr(target, '_table_default_cursor', ''))
            except tk.TclError:
                pass
        if widget is None or widget is self._resize_cursor_widget:
            self._resize_cursor_widget = None

    def _clear_resize_hover(self, widget=None):
        if self._resize_state:
            return
        self._resize_hover = None
        self._restore_resize_cursor(widget)
        self._hide_drag_icon()

    def _available_table_width(self):
        return max(
            self.CELL_MIN_PIXEL_WIDTH,
            self._max_table_frame_width()
            - self.SELECTOR_PIXEL_WIDTH
            - self.TABLE_GRID_RIGHT_INSET
            - self.TABLE_SHELL_PAD_X * 2
            - self._table_border_width(),
        )

    def _text_widget_inset(self):
        inset = 0
        for option in ('padx', 'borderwidth', 'highlightthickness'):
            try:
                inset += int(float(self.viewport_parent.cget(option) or 0))
            except Exception:
                pass
        return inset

    def _table_border_width(self):
        try:
            return int(float(self.frame.cget('highlightthickness') or 0)) * 2
        except Exception:
            return 0

    def _max_table_window_width(self):
        try:
            width = int(self.viewport_parent.winfo_width() or 0)
        except Exception:
            width = 0
        if width <= 1:
            try:
                width = int(self.frame.winfo_width() or self.viewport_parent.winfo_reqwidth() or 0)
            except Exception:
                width = 0
        width = width or 720
        return max(self.CELL_MIN_PIXEL_WIDTH, width - self._text_widget_inset() * 2)

    def _max_table_frame_width(self):
        return max(
            self.CELL_MIN_PIXEL_WIDTH,
            self._max_table_window_width() - self.TABLE_EDITOR_RIGHT_GAP,
        )

    def _table_frame_width_for_columns(self, column_widths):
        content_width = sum(int(width or 0) for width in (column_widths or []))
        return min(
            self._max_table_frame_width(),
            self.SELECTOR_PIXEL_WIDTH
            + content_width
            + self.TABLE_GRID_RIGHT_INSET
            + self.TABLE_SHELL_PAD_X * 2
            + self._table_border_width(),
        )

    def _grid_shell_width_for_columns(self, column_widths):
        content_width = sum(int(width or 0) for width in (column_widths or []))
        return max(1, self.SELECTOR_PIXEL_WIDTH + content_width + self.TABLE_GRID_RIGHT_INSET)

    def _sync_grid_shell_size(self, column_widths):
        grid_width = self._grid_shell_width_for_columns(column_widths or self._column_widths)
        try:
            self.grid_shell.grid_propagate(True)
            self.grid_shell.update_idletasks()
            grid_height = max(1, int(self.grid_shell.winfo_reqheight() or self.grid_shell.winfo_height() or 1))
            self.grid_shell.configure(width=grid_width, height=grid_height)
            self.grid_shell.grid_propagate(False)
        except tk.TclError:
            pass

    def _sync_window_frame_size(self, column_widths=None):
        window_frame = getattr(self, 'window_frame', None)
        if window_frame is None or not window_frame.winfo_exists():
            return
        table_width = self._table_frame_width_for_columns(column_widths or self._column_widths)
        try:
            self._sync_grid_shell_size(column_widths or self._column_widths)
            self.frame.pack_propagate(True)
            self.frame.update_idletasks()
        except Exception:
            pass
        height = max(1, int(self.frame.winfo_reqheight() or self.frame.winfo_height() or 1))
        try:
            self.frame.configure(width=table_width, height=height)
            self.frame.pack_propagate(False)
            window_frame.pack_propagate(False)
            window_frame.configure(
                width=table_width + self.TABLE_EDITOR_RIGHT_GAP,
                height=height,
            )
        except tk.TclError:
            pass

    def _measure_cell_text_widths(self):
        body_font = self._text_font()
        try:
            header_font = tkfont.Font(root=self.frame, font=FONTS['body_bold'])
        except Exception:
            header_font = body_font
        widths = []
        for row_idx, row in enumerate(self.rows):
            font = header_font if self.has_header and row_idx == 0 else body_font
            row_widths = []
            for cell in row:
                parts = re.split(r'[\s，。；：、,.!?;:()\[\]{}<>《》]+', str(cell or ''))
                candidates = [str(cell or '')] + [part for part in parts if part]
                measured = max((font.measure(candidate) for candidate in candidates), default=0)
                row_widths.append(measured)
            widths.append(row_widths)
        return widths

    def _column_readable_min_widths(self, cell_text_widths):
        col_count = self._col_count()
        floors = [self.CELL_MIN_PIXEL_WIDTH for _col in range(col_count)]
        if not isinstance(cell_text_widths, list):
            return floors
        extra_width = (
            self.CELL_PADDING_X * 2
            + self.CELL_TEXT_RIGHT_MARGIN
            + self.CELL_COLUMN_SAFETY_PADDING
        )
        for row in cell_text_widths:
            if not isinstance(row, (list, tuple)):
                continue
            for col_idx, measured in enumerate(row[:col_count]):
                try:
                    target = int(measured or 0) + extra_width
                except Exception:
                    target = extra_width
                floors[col_idx] = max(
                    floors[col_idx],
                    min(self.CELL_READABLE_MAX_PIXEL_WIDTH, target),
                )
        return floors

    def _apply_column_readable_floors(self, widths, readable_floors, available_width):
        if not widths:
            return widths
        available = max(1, int(available_width or 1))
        adjusted = [
            max(int(width or 0), int(readable_floors[idx] if idx < len(readable_floors) else self.CELL_MIN_PIXEL_WIDTH))
            for idx, width in enumerate(widths)
        ]
        overflow = sum(adjusted) - available
        while overflow > 0:
            flexible = [
                idx for idx, width in enumerate(adjusted)
                if width > self.CELL_MIN_PIXEL_WIDTH
            ]
            if not flexible:
                break
            share = max(1, (overflow + len(flexible) - 1) // len(flexible))
            changed = 0
            for idx in flexible:
                reduction = min(share, adjusted[idx] - self.CELL_MIN_PIXEL_WIDTH, overflow - changed)
                if reduction <= 0:
                    continue
                adjusted[idx] -= reduction
                changed += reduction
                if changed >= overflow:
                    break
            if changed <= 0:
                break
            overflow -= changed
        return adjusted

    def _normalize_manual_column_widths(self):
        self.manual_column_widths = normalize_table_pixel_sizes(
            self.manual_column_widths,
            self._col_count(),
            min_value=self.CELL_MIN_PIXEL_WIDTH,
        )
        return self.manual_column_widths

    def _normalize_manual_row_heights(self):
        self.manual_row_heights = normalize_table_pixel_sizes(
            self.manual_row_heights,
            self._row_count(),
            min_value=self.ROW_MIN_PIXEL_HEIGHT,
        )
        return self.manual_row_heights

    def _fit_widths_to_available(self, widths, available_width):
        if not widths:
            return widths
        available = max(1, int(available_width or 1))
        fitted = [max(self.CELL_MIN_PIXEL_WIDTH, int(width or self.CELL_MIN_PIXEL_WIDTH)) for width in widths]
        overflow = sum(fitted) - available
        while overflow > 0:
            flexible = [idx for idx, width in enumerate(fitted) if width > self.CELL_MIN_PIXEL_WIDTH]
            if not flexible:
                break
            share = max(1, (overflow + len(flexible) - 1) // len(flexible))
            changed = 0
            for idx in flexible:
                reduction = min(share, fitted[idx] - self.CELL_MIN_PIXEL_WIDTH, overflow - changed)
                if reduction <= 0:
                    continue
                fitted[idx] -= reduction
                changed += reduction
                if changed >= overflow:
                    break
            if changed <= 0:
                break
            overflow -= changed
        return fitted

    def _expand_widths_to_available(self, widths, available_width):
        fitted = self._fit_widths_to_available(widths, available_width)
        if not fitted:
            return fitted
        available = max(sum(fitted), int(available_width or 0))
        extra = available - sum(fitted)
        if extra <= 0:
            return fitted
        weights = [max(1, width) for width in fitted]
        weight_total = sum(weights)
        additions = [int(extra * weight / weight_total) for weight in weights]
        remainder = extra - sum(additions)
        for idx in range(remainder):
            additions[idx % len(additions)] += 1
        return [width + additions[idx] for idx, width in enumerate(fitted)]

    def _calculate_column_widths(self):
        available_width = self._available_table_width()
        measurements = self._measure_cell_text_widths()
        widths = calculate_table_column_widths(
            self.rows,
            available_width,
            cell_text_widths=measurements,
            merged_cells=self.merged_cells,
            min_width=self.CELL_MIN_PIXEL_WIDTH,
            max_width=self.CELL_MAX_PIXEL_WIDTH,
            cell_padding=self.CELL_PADDING_X * 2 + self.CELL_TEXT_RIGHT_MARGIN,
        )
        widths = self._apply_column_readable_floors(
            widths,
            self._column_readable_min_widths(measurements),
            available_width,
        )
        manual_widths = self._normalize_manual_column_widths()
        if manual_widths:
            widths = self._fit_widths_to_available(manual_widths, available_width)
        self._column_widths = widths
        self._last_layout_width = available_width
        return widths

    def _span_pixel_width(self, col_idx, colspan=1):
        widths = self._column_widths or [self.CELL_MIN_PIXEL_WIDTH] * self._col_count()
        start = max(0, int(col_idx))
        end = min(len(widths), start + max(1, int(colspan or 1)))
        if start >= end:
            return self.CELL_MIN_PIXEL_WIDTH
        return max(1, sum(widths[start:end]))

    def _width_to_text_chars(self, pixel_width):
        _font, _line_height, char_width = self._font_metrics()
        usable_width = max(char_width, self._cell_text_usable_width(pixel_width))
        return max(1, int(usable_width // char_width))

    def _cell_text_usable_width(self, pixel_width):
        reserved = (
            self.CELL_TEXT_PAD_X * 2
            + self.CELL_TEXT_RIGHT_MARGIN
            + self.CELL_GRID_PAD_X * 2
            + self.CELL_GRID_IPAD_X * 2
            + 4
        )
        return max(12, int(pixel_width) - reserved)

    def _wrapped_line_count(self, text, pixel_width):
        font, _line_height, _char_width = self._font_metrics()
        limit = self._cell_text_usable_width(pixel_width)
        total = 0
        for paragraph in str(text or '').splitlines() or ['']:
            if not paragraph:
                total += 1
                continue
            line_width = 0
            line_count = 1
            for token in re.findall(r'\S+\s*|\s+', paragraph):
                token_width = max(1, font.measure(token))
                if line_width > 0 and line_width + token_width > limit:
                    line_count += 1
                    line_width = 0
                if token_width <= limit:
                    line_width += token_width
                    continue
                for char in token:
                    char_width = max(1, font.measure(char))
                    if line_width > 0 and line_width + char_width > limit:
                        line_count += 1
                        line_width = 0
                    line_width += char_width
            total += line_count
        return max(1, total)

    def _estimate_cell_height(self, text, colspan=1, pixel_width=None):
        value = str(text or '')
        if pixel_width is None:
            pixel_width = self.CELL_MIN_PIXEL_WIDTH * max(1, int(colspan or 1))
        lines = self._wrapped_line_count(value, pixel_width)
        return max(self.CELL_MIN_HEIGHT, lines)

    def _cell_pixel_height(self, text, colspan=1, pixel_width=None, row_idx=None, rowspan=1):
        _font, line_height, _char_width = self._font_metrics()
        lines = self._estimate_cell_height(text, colspan=colspan, pixel_width=pixel_width)
        auto_height = max(self.ROW_MIN_PIXEL_HEIGHT, lines * line_height + 12)
        manual_heights = self._normalize_manual_row_heights()
        if row_idx is None or not manual_heights:
            return auto_height
        start = max(0, int(row_idx))
        end = min(len(manual_heights), start + max(1, int(rowspan or 1)))
        if start >= end:
            return auto_height
        return max(auto_height, sum(manual_heights[start:end]))

    def _cell_container_width(self, col_idx, colspan=1, three_line=None):
        pixel_width = self._span_pixel_width(col_idx, colspan)
        if three_line is None:
            three_line = self.table_style == TABLE_STYLE_THREE_LINE
        outer_pad = 0 if three_line else self.CELL_GRID_PAD_X
        return max(1, int(pixel_width) - outer_pad * 2)

    def _configure_cell_dimensions(self, widget, row_idx, col_idx, text, colspan=1):
        pixel_width = self._span_pixel_width(col_idx, colspan)
        widget.configure(
            width=1,
            height=1,
            wrap=tk.CHAR,
        )
        container = getattr(widget, '_cell_container', None)
        if container is not None and container.winfo_exists():
            container.configure(
                width=self._cell_container_width(col_idx, colspan),
                height=self._cell_pixel_height(text, colspan=colspan, pixel_width=pixel_width, row_idx=row_idx),
            )

    def _display_line_count(self, widget, fallback_text='', fallback_width=None):
        try:
            widget.update_idletasks()
            count = widget.count('1.0', 'end-1c', 'displaylines')
            if count:
                return max(self.CELL_MIN_HEIGHT, int(count[0]) + 1)
        except Exception:
            pass
        width = fallback_width
        if width is None:
            try:
                width = max(1, int(widget.winfo_width() or 0))
            except Exception:
                width = self.CELL_MIN_PIXEL_WIDTH
        return self._estimate_cell_height(fallback_text, pixel_width=width)

    def _fit_cell_heights_to_content(self):
        if not self.frame.winfo_exists():
            return
        changed = False
        for row_idx, row_widgets in enumerate(getattr(self, '_cell_widgets', [])):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists() or (row_idx, col_idx) in self._covered_cells:
                    continue
                merged = self._merge_by_anchor.get((row_idx, col_idx))
                colspan = int(merged.get('colspan', 1)) if merged else 1
                text = self._cell_text(widget)
                fallback_width = self._span_pixel_width(col_idx, colspan)
                height = self._display_line_count(widget, text, fallback_width)
                _font, line_height, _char_width = self._font_metrics()
                pixel_height = max(24, height * line_height + 12)
                manual_heights = self._normalize_manual_row_heights()
                if manual_heights and row_idx < len(manual_heights):
                    pixel_height = max(pixel_height, manual_heights[row_idx])
                try:
                    container = getattr(widget, '_cell_container', None)
                    current = int(container.cget('height') or 0) if container is not None else 0
                except Exception:
                    current = 0
                if current != pixel_height:
                    try:
                        if container is not None and container.winfo_exists():
                            container.configure(height=pixel_height)
                    except tk.TclError:
                        pass
                    changed = True
        if changed:
            self._sync_window_frame_size(self._column_widths)

    def _on_layout_configure(self, event=None):
        widget = getattr(event, 'widget', None)
        if widget not in (self.frame, self.parent, self.viewport_parent):
            return
        current_width = self._available_table_width()
        if abs(current_width - self._last_layout_width) < 8:
            return
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self, delay=120):
        if self._layout_after_id is not None:
            try:
                self.frame.after_cancel(self._layout_after_id)
            except Exception:
                pass
        self._layout_after_id = self.frame.after(delay, self._refresh_existing_layout)

    def _refresh_existing_layout(self):
        self._layout_after_id = None
        if not self.frame.winfo_exists() or not getattr(self, '_cell_widgets', None):
            return
        self._sync_rows_from_widgets()
        self._build_merge_maps()
        column_widths = self._calculate_column_widths()
        self.grid_shell.grid_columnconfigure(0, weight=0, minsize=self.SELECTOR_PIXEL_WIDTH)
        for col_idx in range(self._col_count()):
            width = column_widths[col_idx] if col_idx < len(column_widths) else self.CELL_MIN_PIXEL_WIDTH
            self.grid_shell.grid_columnconfigure(col_idx + 1, weight=0, minsize=width)
        self.grid_shell.grid_columnconfigure(self._col_count() + 1, weight=0, minsize=self.TABLE_GRID_RIGHT_INSET)
        for row_idx, row_widgets in enumerate(getattr(self, '_cell_widgets', [])):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists() or (row_idx, col_idx) in self._covered_cells:
                    continue
                merged = self._merge_by_anchor.get((row_idx, col_idx))
                colspan = int(merged.get('colspan', 1)) if merged else 1
                text = self.rows[row_idx][col_idx] if row_idx < len(self.rows) and col_idx < len(self.rows[row_idx]) else ''
                self._configure_cell_dimensions(widget, row_idx, col_idx, text, colspan)
        self._sync_window_frame_size(column_widths)
        self.frame.after_idle(self._fit_cell_heights_to_content)

    def _refresh_selection_style(self):
        for row_idx, row_widgets in enumerate(getattr(self, '_cell_widgets', [])):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists():
                    continue
                selected = self._is_cell_selected(row_idx, col_idx)
                is_header = self.has_header and row_idx == 0
                if selected:
                    bg = COLORS['accent_light']
                elif self.hover_mode == 'row' and self.hover_index == row_idx:
                    bg = COLORS['surface_alt']
                elif self.hover_mode == 'column' and self.hover_index == col_idx:
                    bg = COLORS['surface_alt']
                elif is_header:
                    bg = COLORS['surface_alt']
                else:
                    bg = COLORS['input_bg']
                widget.configure(bg=bg, highlightbackground=COLORS['accent'] if selected else COLORS['input_border'])

        for row_idx, selector in enumerate(getattr(self, '_row_selectors', [])):
            selected = self.selection_mode in {'row', 'table'} and self.selected_row_range[0] <= row_idx <= self.selected_row_range[1]
            hovered = self.hover_mode == 'row' and self.hover_index == row_idx
            selector.configure(
                bg=COLORS['accent_light'] if selected or hovered else COLORS['card_bg'],
                fg=COLORS['accent'] if selected or hovered else COLORS['text_sub'],
            )

        for col_idx, selector in enumerate(getattr(self, '_col_selectors', [])):
            selected = self.selection_mode in {'column', 'table'} and self.selected_col_range[0] <= col_idx <= self.selected_col_range[1]
            hovered = self.hover_mode == 'column' and self.hover_index == col_idx
            selector.configure(
                bg=COLORS['accent_light'] if selected or hovered else COLORS['card_bg'],
                fg=COLORS['accent'] if selected or hovered else COLORS['text_sub'],
            )

        selector = getattr(self, '_table_selector', None)
        if selector is not None and selector.winfo_exists():
            active = self.selection_mode == 'table' or self.hover_mode == 'table'
            selector.configure(
                bg=COLORS['accent_light'] if active else COLORS['card_bg'],
                fg=COLORS['accent'] if active else COLORS['text_sub'],
            )

    def _render_grid(self):
        self._destroy_floating_toolbar()
        for child in self.grid_shell.winfo_children():
            child.destroy()

        self._cell_widgets = []
        self._cell_containers = []
        self._row_selectors = []
        self._col_selectors = []
        self._covered_cells = {}
        self._merge_by_anchor = {}
        row_count = len(self.rows)
        col_count = max(len(row) for row in self.rows) if self.rows else 0

        if row_count <= 0 or col_count <= 0:
            self.rows = [['', ''], ['', '']]
            row_count = len(self.rows)
            col_count = len(self.rows[0])
        self._build_merge_maps()
        column_widths = self._calculate_column_widths()
        three_line = self.table_style == TABLE_STYLE_THREE_LINE

        self._table_selector = tk.Label(
            self.grid_shell,
            text='↘',
            width=self.ROW_SELECTOR_WIDTH,
            height=self.COL_SELECTOR_HEIGHT,
            font=FONTS['small'],
            bg=COLORS['card_bg'],
            fg=COLORS['text_sub'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
            cursor='hand2',
        )
        self._table_selector.grid(row=0, column=0, sticky='nsew', padx=1, pady=1)
        self._table_selector.bind('<Enter>', lambda _event: self._set_hover('table'))
        self._table_selector.bind('<Leave>', lambda _event: self._clear_hover('table'))
        self._table_selector.bind('<Button-1>', self._on_table_selector_press)
        self._table_selector.bind('<Button-3>', self._on_table_context)

        for col_idx in range(col_count):
            selector = tk.Label(
                self.grid_shell,
                text='▼',
                height=self.COL_SELECTOR_HEIGHT,
                font=FONTS['small'],
                bg=COLORS['card_bg'],
                fg=COLORS['text_sub'],
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=COLORS['input_border'],
                cursor='hand2',
            )
            selector.grid(row=0, column=col_idx + 1, sticky='nsew', padx=1, pady=1)
            selector.bind('<Enter>', lambda _event, c=col_idx: self._set_hover('column', c))
            selector.bind('<Leave>', lambda _event, c=col_idx: self._clear_hover('column', c))
            selector.bind('<Motion>', lambda event, c=col_idx: self._on_column_selector_motion(c, event))
            selector.bind('<Leave>', lambda event, c=col_idx: (self._clear_hover('column', c), self._clear_resize_hover(getattr(event, 'widget', None))))
            selector.bind('<Button-1>', lambda event, c=col_idx: self._on_column_selector_press(c, event))
            selector.bind('<B1-Motion>', self._on_column_selector_drag)
            selector.bind('<ButtonRelease-1>', self._on_selector_release)
            selector.bind('<Button-3>', lambda event, c=col_idx: self._on_column_selector_context(c, event))
            self._col_selectors.append(selector)

        if three_line:
            line_rows = {1: 2, self._data_grid_row(row_count - 1) + 1: 2}
            if self.has_header and row_count > 1:
                line_rows[self._data_grid_row(0) + 1] = 1
            for line_row, height in sorted(line_rows.items()):
                line = tk.Frame(self.grid_shell, bg=COLORS['text_main'], height=height)
                line.grid(row=line_row, column=1, columnspan=col_count, sticky='ew', padx=1, pady=0)

        for row_idx, row in enumerate(self.rows):
            selector = tk.Label(
                self.grid_shell,
                text='▶',
                width=self.ROW_SELECTOR_WIDTH,
                font=FONTS['small'],
                bg=COLORS['card_bg'],
                fg=COLORS['text_sub'],
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=COLORS['input_border'],
                cursor='hand2',
            )
            selector.grid(row=self._data_grid_row(row_idx), column=0, sticky='nsew', padx=1, pady=1)
            selector.bind('<Enter>', lambda _event, r=row_idx: self._set_hover('row', r))
            selector.bind('<Leave>', lambda _event, r=row_idx: self._clear_hover('row', r))
            selector.bind('<Motion>', lambda event, r=row_idx: self._on_row_selector_motion(r, event))
            selector.bind('<Leave>', lambda event, r=row_idx: (self._clear_hover('row', r), self._clear_resize_hover(getattr(event, 'widget', None))))
            selector.bind('<Button-1>', lambda event, r=row_idx: self._on_row_selector_press(r, event))
            selector.bind('<B1-Motion>', self._on_row_selector_drag)
            selector.bind('<ButtonRelease-1>', self._on_selector_release)
            selector.bind('<Button-3>', lambda event, r=row_idx: self._on_row_selector_context(r, event))
            self._row_selectors.append(selector)

            row_widgets = [None] * col_count
            row_containers = [None] * col_count
            for col_idx in range(col_count):
                if (row_idx, col_idx) in self._covered_cells:
                    continue
                merged = self._merge_by_anchor.get((row_idx, col_idx))
                rowspan = int(merged.get('rowspan', 1)) if merged else 1
                colspan = int(merged.get('colspan', 1)) if merged else 1
                cell_value = row[col_idx] if col_idx < len(row) else ''
                pixel_width = self._span_pixel_width(col_idx, colspan)
                container = tk.Frame(
                    self.grid_shell,
                    width=self._cell_container_width(col_idx, colspan, three_line=three_line),
                    height=self._cell_pixel_height(
                        cell_value,
                        colspan=colspan,
                        pixel_width=pixel_width,
                        row_idx=row_idx,
                        rowspan=rowspan,
                    ),
                    bg=COLORS['surface_alt'] if self.has_header and row_idx == 0 else COLORS['input_bg'],
                    highlightthickness=0,
                    bd=0,
                )
                container.grid(
                    row=self._data_grid_row(row_idx),
                    column=col_idx + 1,
                    rowspan=self._data_rowspan(rowspan),
                    columnspan=colspan,
                    sticky='nsew',
                    padx=0 if three_line else self.CELL_GRID_PAD_X,
                    pady=0 if three_line else 1,
                )
                container.pack_propagate(False)
                cell = tk.Text(
                    container,
                    font=FONTS['small'],
                    width=1,
                    height=1,
                    wrap=tk.CHAR,
                    bg=COLORS['surface_alt'] if self.has_header and row_idx == 0 else COLORS['input_bg'],
                    fg=COLORS['text_main'],
                    relief=tk.FLAT,
                    highlightthickness=0 if three_line else 1,
                    highlightbackground=COLORS['surface_alt'] if three_line else COLORS['input_border'],
                    insertbackground=COLORS['text_main'],
                    padx=4,
                    pady=3,
                    tabs=(self._font_metrics()[2] * 4,),
                    undo=True,
                )
                cell.tag_configure(
                    'cell_align',
                    justify=self._cell_justify(row_idx, col_idx),
                    rmargin=self.CELL_TEXT_RIGHT_MARGIN,
                )
                cell._cell_container = container
                cell.pack(fill=tk.BOTH, expand=True)
                cell.insert('1.0', cell_value)
                cell.tag_add('cell_align', '1.0', 'end')
                if self.has_header and row_idx == 0:
                    cell.configure(font=FONTS['body_bold'])
                cell.bind('<FocusIn>', lambda _event, r=row_idx, c=col_idx: self._on_cell_focus(r, c))
                cell.bind('<Button-1>', lambda event, r=row_idx, c=col_idx: self._on_cell_press(r, c, event))
                cell.bind('<B1-Motion>', self._on_cell_drag)
                cell.bind('<ButtonRelease-1>', self._on_cell_release)
                cell.bind('<Button-3>', lambda event, r=row_idx, c=col_idx: self._on_cell_context(r, c, event))
                cell.bind('<KeyRelease>', lambda _event: self._on_cell_changed())
                cell.bind('<Return>', self._on_cell_return)
                cell.bind('<Control-Return>', lambda _event: None)
                row_widgets[col_idx] = cell
                row_containers[col_idx] = container
            self._cell_widgets.append(row_widgets)
            self._cell_containers.append(row_containers)

        self.grid_shell.grid_columnconfigure(0, weight=0, minsize=self.SELECTOR_PIXEL_WIDTH)
        for col_idx in range(col_count):
            width = column_widths[col_idx] if col_idx < len(column_widths) else self.CELL_MIN_PIXEL_WIDTH
            self.grid_shell.grid_columnconfigure(col_idx + 1, weight=0, minsize=width)
        self.grid_shell.grid_columnconfigure(col_count + 1, weight=0, minsize=self.TABLE_GRID_RIGHT_INSET)
        self.grid_shell.grid_rowconfigure(0, weight=0, minsize=20)
        for row_idx in range(row_count):
            self.grid_shell.grid_rowconfigure(self._data_grid_row(row_idx), weight=1)

        self._sync_window_frame_size(column_widths)
        self._refresh_selection_style()
        self.frame.after_idle(self._fit_cell_heights_to_content)

    def _column_resize_hit(self, widget, col_idx, event):
        if self._col_count() <= 1:
            return None
        try:
            x = int(event.x_root) - int(widget.winfo_rootx())
            width = max(1, int(widget.winfo_width()))
        except Exception:
            return None
        margin = self.RESIZE_HIT_MARGIN
        if x <= margin and col_idx > 0:
            return ('column', col_idx - 1)
        if x >= width - margin and col_idx < self._col_count() - 1:
            return ('column', col_idx)
        return None

    def _row_resize_hit(self, widget, row_idx, event):
        if self._row_count() <= 1:
            return None
        try:
            y = int(event.y_root) - int(widget.winfo_rooty())
            height = max(1, int(widget.winfo_height()))
        except Exception:
            return None
        margin = self.RESIZE_HIT_MARGIN
        if y <= margin and row_idx > 0:
            return ('row', row_idx - 1)
        if y >= height - margin and row_idx < self._row_count() - 1:
            return ('row', row_idx)
        return None

    def _column_selector_resize_hit(self, col_idx, event):
        widget = getattr(event, 'widget', None)
        return self._column_resize_hit(widget, col_idx, event) if widget is not None else None

    def _row_selector_resize_hit(self, row_idx, event):
        widget = getattr(event, 'widget', None)
        return self._row_resize_hit(widget, row_idx, event) if widget is not None else None

    def _update_resize_hover(self, event, hit):
        widget = getattr(event, 'widget', None)
        if widget is None:
            return
        if hit is None:
            self._clear_resize_hover(widget)
            return
        mode, index = hit
        self._resize_hover = hit
        self._set_resize_cursor(widget, 'sb_h_double_arrow' if mode == 'column' else 'sb_v_double_arrow')
        self._show_drag_icon(event)

    def _on_column_selector_motion(self, col_idx, event=None):
        if event is None:
            return None
        self._update_resize_hover(event, self._column_selector_resize_hit(col_idx, event))
        return None

    def _on_row_selector_motion(self, row_idx, event=None):
        if event is None:
            return None
        self._update_resize_hover(event, self._row_selector_resize_hit(row_idx, event))
        return None

    def _start_resize_from_hit(self, hit, event):
        if hit is None or event is None:
            return False
        mode, index = hit
        self._sync_rows_from_widgets()
        self._resize_state = {
            'mode': mode,
            'index': index,
            'start_x': int(getattr(event, 'x_root', 0) or 0),
            'start_y': int(getattr(event, 'y_root', 0) or 0),
            'column_widths': list(self._column_widths or self._calculate_column_widths()),
            'row_heights': self._current_row_pixel_heights(),
        }
        self._drag_select_mode = 'resize'
        self._set_resize_cursor(getattr(event, 'widget', self.frame), 'sb_h_double_arrow' if mode == 'column' else 'sb_v_double_arrow')
        self._show_drag_icon(event)
        return True

    def _current_row_pixel_heights(self):
        heights = []
        manual = self._normalize_manual_row_heights()
        for row_idx in range(self._row_count()):
            row_height = manual[row_idx] if manual and row_idx < len(manual) else self.ROW_MIN_PIXEL_HEIGHT
            for container in getattr(self, '_cell_containers', [[]])[row_idx] if row_idx < len(getattr(self, '_cell_containers', [])) else []:
                if container is not None and container.winfo_exists():
                    try:
                        row_height = max(row_height, int(container.winfo_height() or 0))
                    except Exception:
                        pass
            heights.append(max(self.ROW_MIN_PIXEL_HEIGHT, row_height))
        return heights

    def _perform_resize_drag(self, event):
        state = self._resize_state
        if not state:
            return None
        mode = state.get('mode')
        index = int(state.get('index', 0))
        if mode == 'column':
            widths = list(state.get('column_widths') or [])
            if index < 0 or index + 1 >= len(widths):
                return 'break'
            delta = int(getattr(event, 'x_root', 0) or 0) - int(state.get('start_x', 0))
            left_original = int(widths[index])
            right_original = int(widths[index + 1])
            min_width = self.CELL_MIN_PIXEL_WIDTH
            delta = max(min_width - left_original, min(delta, right_original - min_width))
            widths[index] = left_original + delta
            widths[index + 1] = right_original - delta
            self.manual_column_widths = widths
            self._refresh_existing_layout()
        elif mode == 'row':
            heights = list(state.get('row_heights') or [])
            if index < 0 or index >= len(heights):
                return 'break'
            delta = int(getattr(event, 'y_root', 0) or 0) - int(state.get('start_y', 0))
            heights[index] = max(self.ROW_MIN_PIXEL_HEIGHT, int(heights[index]) + delta)
            self.manual_row_heights = heights
            self._refresh_existing_layout()
        self._show_drag_icon(event)
        return 'break'

    def _stop_resize_drag(self, event=None):
        if not self._resize_state:
            return None
        self._resize_state = None
        self._drag_select_mode = ''
        self._notify_change()
        if event is not None:
            hit = self._resize_hover
            self._update_resize_hover(event, hit)
        else:
            self._clear_resize_hover()
        return 'break'

    def _index_from_root_position(self, widgets, axis, root_value):
        for index, widget in enumerate(widgets):
            if not widget.winfo_exists():
                continue
            start = widget.winfo_rooty() if axis == 'y' else widget.winfo_rootx()
            size = widget.winfo_height() if axis == 'y' else widget.winfo_width()
            if start <= root_value <= start + max(size, 1):
                return index
        if not widgets:
            return None
        first_start = widgets[0].winfo_rooty() if axis == 'y' else widgets[0].winfo_rootx()
        return 0 if root_value < first_start else len(widgets) - 1

    def _cell_from_root_position(self, x_root, y_root):
        candidate = None
        for row_idx, row_widgets in enumerate(getattr(self, '_cell_widgets', [])):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists():
                    continue
                x_start = widget.winfo_rootx()
                y_start = widget.winfo_rooty()
                x_end = x_start + max(widget.winfo_width(), 1)
                y_end = y_start + max(widget.winfo_height(), 1)
                if x_start <= x_root <= x_end and y_start <= y_root <= y_end:
                    return row_idx, col_idx
                if x_root >= x_start and y_root >= y_start:
                    candidate = (row_idx, col_idx)
        if candidate is not None:
            return candidate
        if self.rows:
            return 0, 0
        return None

    def _on_table_selector_press(self, event=None):
        self._set_selected_table(show_toolbar=True)
        return 'break'

    def _on_row_selector_press(self, row_idx, event=None):
        if self._start_resize_from_hit(self._row_selector_resize_hit(row_idx, event), event):
            return 'break'
        self._drag_select_mode = 'row'
        self._drag_anchor_index = row_idx
        self._set_selected_row(row_idx, show_toolbar=False)
        return 'break'

    def _on_column_selector_press(self, col_idx, event=None):
        if self._start_resize_from_hit(self._column_selector_resize_hit(col_idx, event), event):
            return 'break'
        self._drag_select_mode = 'column'
        self._drag_anchor_index = col_idx
        self._set_selected_column(col_idx, show_toolbar=False)
        return 'break'

    def _on_row_selector_drag(self, event=None):
        if self._resize_state:
            return self._perform_resize_drag(event)
        if self._drag_select_mode != 'row' or self._drag_anchor_index is None:
            return 'break'
        target = self._index_from_root_position(self._row_selectors, 'y', getattr(event, 'y_root', 0))
        if target is not None:
            self._set_selected_row(self._drag_anchor_index, target, show_toolbar=False)
        return 'break'

    def _on_column_selector_drag(self, event=None):
        if self._resize_state:
            return self._perform_resize_drag(event)
        if self._drag_select_mode != 'column' or self._drag_anchor_index is None:
            return 'break'
        target = self._index_from_root_position(self._col_selectors, 'x', getattr(event, 'x_root', 0))
        if target is not None:
            self._set_selected_column(self._drag_anchor_index, target, show_toolbar=False)
        return 'break'

    def _on_selector_release(self, event=None):
        if self._resize_state:
            return self._stop_resize_drag(event)
        self._drag_select_mode = ''
        self._drag_anchor_index = None
        self._cell_drag_anchor = None
        return 'break'

    def _on_cell_press(self, row_idx, col_idx, event=None):
        self._drag_select_mode = 'cell'
        if getattr(event, 'state', 0) & 0x0001:
            anchor = (self.selected_row, self.selected_col)
            self._cell_drag_anchor = anchor
            self._set_selected_cell_range(anchor, (row_idx, col_idx))
        else:
            self._cell_drag_anchor = (row_idx, col_idx)
            self._set_selected_cell(row_idx, col_idx)
        try:
            widget = getattr(event, 'widget', None)
            if widget is not None and widget.winfo_exists():
                widget.focus_set()
        except Exception:
            pass
        return None

    def _on_cell_focus(self, row_idx, col_idx):
        self.on_activate(self)
        if self._drag_select_mode == 'cell':
            return
        self._set_selected_cell(row_idx, col_idx)

    def _on_cell_drag(self, event=None):
        if self._drag_select_mode != 'cell' or self._cell_drag_anchor is None:
            return None
        target = self._cell_from_root_position(
            getattr(event, 'x_root', 0),
            getattr(event, 'y_root', 0),
        )
        if target is not None:
            self._set_selected_cell_range(self._cell_drag_anchor, target)
        return 'break'

    def _on_cell_release(self, event=None):
        if self._drag_select_mode == 'cell':
            self._drag_select_mode = ''
            self._cell_drag_anchor = None
        return None

    def _on_cell_context(self, row_idx, col_idx, event=None):
        row_range, col_range = self._current_content_range()
        if not (row_range[0] <= row_idx <= row_range[1] and col_range[0] <= col_idx <= col_range[1]):
            self._set_selected_cell(row_idx, col_idx)
        return self._show_context_menu(event)

    def _on_row_selector_context(self, row_idx, event=None):
        self._set_selected_row(row_idx, show_toolbar=True)
        return self._show_context_menu(event)

    def _on_column_selector_context(self, col_idx, event=None):
        self._set_selected_column(col_idx, show_toolbar=True)
        return self._show_context_menu(event)

    def _on_table_context(self, event=None):
        self._set_selected_table(show_toolbar=True)
        return self._show_context_menu(event)

    def _show_context_menu(self, event=None):
        menu = tk.Menu(self.frame, tearoff=0)
        menu.add_command(label='上方插入行', command=lambda: self.insert_row(after=False))
        menu.add_command(label='下方插入行', command=lambda: self.insert_row(after=True))
        menu.add_command(label='左侧插入列', command=lambda: self.insert_column(after=False))
        menu.add_command(label='右侧插入列', command=lambda: self.insert_column(after=True))
        menu.add_separator()
        row_range, col_range = self._current_content_range()
        can_merge = (row_range[1] - row_range[0] + 1) * (col_range[1] - col_range[0] + 1) > 1
        menu.add_command(
            label='合并单元格',
            command=self.merge_selection,
            state=tk.NORMAL if can_merge else tk.DISABLED,
        )
        menu.add_command(
            label='取消合并单元格',
            command=self.unmerge_selection,
            state=tk.NORMAL if self._selection_has_merge() else tk.DISABLED,
        )
        style_label = '切换为普通表格' if self.table_style == TABLE_STYLE_THREE_LINE else '切换为三线表'
        menu.add_command(label=style_label, command=self.toggle_three_line_table)
        if self.selection_mode == 'table':
            menu.add_separator()
            menu.add_command(label='根据窗口调整表格', command=self.fit_table_to_window)
            menu.add_command(label='根据内容调整表格', command=self.fit_table_to_content)
        menu.add_separator()
        menu.add_command(label='删除所选行', command=self.delete_row)
        menu.add_command(label='删除所选列', command=self.delete_column)
        menu.add_command(label='清空所选内容', command=self.clear_selection)
        menu.add_separator()
        menu.add_command(label='删除整表', command=self.delete_table)
        try:
            menu.tk_popup(getattr(event, 'x_root', 0), getattr(event, 'y_root', 0))
        finally:
            menu.grab_release()
        return 'break'

    def _destroy_floating_toolbar(self):
        bind_id = getattr(self, '_floating_toolbar_root_bind', None)
        if bind_id:
            try:
                self.frame.winfo_toplevel().unbind('<Button-1>', bind_id)
            except Exception:
                pass
        self._floating_toolbar_root_bind = None
        toolbar = getattr(self, '_floating_toolbar', None)
        if toolbar is not None and toolbar.winfo_exists():
            try:
                toolbar.destroy()
            except tk.TclError:
                pass
        self._floating_toolbar = None

    def _show_floating_toolbar(self):
        self._destroy_floating_toolbar()

    def _apply_rows_update(self, rows, *, merged_cells=None, cell_alignments=None, mode=None, row_range=None, col_range=None, show_toolbar=True):
        self.rows = self._normalize_rows(rows)
        if merged_cells is not None:
            self.merged_cells = normalize_merged_cells(merged_cells, self._row_count(), self._col_count())
        else:
            self._normalize_current_merges()
        if cell_alignments is not None:
            self.cell_alignments = normalize_table_alignments(cell_alignments, self._row_count(), self._col_count())
        else:
            self._normalize_current_alignments()
        self._normalize_manual_column_widths()
        self._normalize_manual_row_heights()
        if mode == 'row' and row_range is not None:
            self.selection_mode = 'row'
            self.selected_row_range = self._normalize_range(row_range[0], row_range[1], self._row_count())
            self.selected_row = self.selected_row_range[0]
        elif mode == 'column' and col_range is not None:
            self.selection_mode = 'column'
            self.selected_col_range = self._normalize_range(col_range[0], col_range[1], self._col_count())
            self.selected_col = self.selected_col_range[0]
        elif mode == 'table':
            self.selection_mode = 'table'
            self.selected_row_range = (0, max(self._row_count() - 1, 0))
            self.selected_col_range = (0, max(self._col_count() - 1, 0))
        else:
            self.selection_mode = 'cell'
            self.selected_row = max(0, min(self.selected_row, self._row_count() - 1))
            self.selected_col = max(0, min(self.selected_col, self._col_count() - 1))
            self.selected_row_range = (self.selected_row, self.selected_row)
            self.selected_col_range = (self.selected_col, self.selected_col)
        self._render_grid()
        self._notify_change()

    def _on_cell_changed(self):
        self._sync_rows_from_widgets()
        self._schedule_layout_refresh(delay=180)
        self._notify_change()

    def _on_cell_return(self, event=None):
        widget = getattr(event, 'widget', None)
        if isinstance(widget, tk.Text):
            widget.insert(tk.INSERT, ' ')
            self._on_cell_changed()
        return 'break'

    def _notify_change(self):
        self.on_change()

    def apply_alignment(self, alignment):
        self._sync_rows_from_widgets()
        row_range, col_range = self._current_content_range()
        self.cell_alignments = set_table_cell_alignment(
            self.cell_alignments,
            alignment,
            mode=self.selection_mode,
            row_range=row_range,
            col_range=col_range,
            row_count=self._row_count(),
            col_count=self._col_count(),
        )
        for row_idx, row_widgets in enumerate(getattr(self, '_cell_widgets', [])):
            for col_idx, widget in enumerate(row_widgets):
                if widget is None or not widget.winfo_exists():
                    continue
                if not self._is_cell_selected(row_idx, col_idx):
                    continue
                widget.tag_configure(
                    'cell_align',
                    justify=self._cell_justify(row_idx, col_idx),
                    rmargin=self.CELL_TEXT_RIGHT_MARGIN,
                )
                widget.tag_add('cell_align', '1.0', 'end')
        self._notify_change()

    def serialize(self):
        self._sync_rows_from_widgets()
        return new_table_block(
            self.rows,
            table_id=self.block_id,
            caption=self.caption_var.get().strip(),
            has_header=self.has_header,
            merged_cells=self.merged_cells,
            table_style=self.table_style,
            cell_alignments=self.cell_alignments,
            column_widths=self._normalize_manual_column_widths(),
            row_heights=self._normalize_manual_row_heights(),
        )

    def set_data(self, block):
        sanitized = sanitize_blocks([block])
        if sanitized and sanitized[0].get('type') == 'table':
            table_block = sanitized[0]
            self.block_id = str(table_block.get('table_id', self.block_id) or self.block_id)
            self.has_header = bool(table_block.get('has_header', True))
            self.caption_var.set(str(table_block.get('caption', '') or ''))
            self.rows = self._normalize_rows(table_block.get('rows', []))
            self.merged_cells = normalize_merged_cells(
                table_block.get('merged_cells', []),
                len(self.rows),
                len(self.rows[0]) if self.rows else 1,
            )
            self.table_style = normalize_table_style(table_block.get('table_style', TABLE_STYLE_GRID))
            self.cell_alignments = normalize_table_alignments(
                table_block.get('cell_alignments', []),
                len(self.rows),
                len(self.rows[0]) if self.rows else 1,
            )
            self.manual_column_widths = normalize_table_pixel_sizes(
                table_block.get('column_widths', []),
                len(self.rows[0]) if self.rows else 1,
                min_value=self.CELL_MIN_PIXEL_WIDTH,
            )
            self.manual_row_heights = normalize_table_pixel_sizes(
                table_block.get('row_heights', []),
                len(self.rows),
                min_value=self.ROW_MIN_PIXEL_HEIGHT,
            )
            self.selection_mode = 'cell'
            self.selected_row = 0
            self.selected_col = 0
            self.selected_row_range = (0, 0)
            self.selected_col_range = (0, 0)
            self._render_grid()

    def _insert_manual_row_heights(self, anchor, count=1, after=True):
        heights = self._normalize_manual_row_heights()
        if not heights:
            return
        index = max(0, min(int(anchor) + (1 if after else 0), len(heights)))
        template = heights[max(0, min(int(anchor), len(heights) - 1))] if heights else self.ROW_MIN_PIXEL_HEIGHT
        self.manual_row_heights = heights[:index] + [template] * max(1, int(count or 1)) + heights[index:]

    def _delete_manual_row_heights(self, start, end):
        heights = self._normalize_manual_row_heights()
        if not heights:
            return
        start, end = self._normalize_range(start, end, len(heights))
        remaining = heights[:start] + heights[end + 1:]
        self.manual_row_heights = remaining if remaining else []

    def _insert_manual_column_widths(self, anchor, count=1, after=True):
        widths = self._normalize_manual_column_widths()
        if not widths:
            return
        index = max(0, min(int(anchor) + (1 if after else 0), len(widths)))
        template = widths[max(0, min(int(anchor), len(widths) - 1))] if widths else self.CELL_MIN_PIXEL_WIDTH
        self.manual_column_widths = widths[:index] + [template] * max(1, int(count or 1)) + widths[index:]

    def _delete_manual_column_widths(self, start, end):
        widths = self._normalize_manual_column_widths()
        if not widths:
            return
        start, end = self._normalize_range(start, end, len(widths))
        remaining = widths[:start] + widths[end + 1:]
        self.manual_column_widths = remaining if remaining else []

    def insert_row(self, after=True):
        self._sync_rows_from_widgets()
        start, end = self._current_row_range()
        count = self._selected_row_count() if self.selection_mode in {'row', 'table'} else 1
        anchor = end if after else start
        old_row_count = self._row_count()
        old_col_count = self._col_count()
        updated, merged = insert_table_rows_with_merges(
            self.rows,
            self.merged_cells,
            anchor,
            count=count,
            after=after,
        )
        alignments = insert_table_alignment_rows(
            self.cell_alignments,
            anchor,
            count=count,
            after=after,
            col_count=old_col_count,
        )
        inserted_start = anchor + (1 if after else 0)
        inserted_end = inserted_start + count - 1
        self._insert_manual_row_heights(anchor, count=count, after=after)
        self._apply_rows_update(updated, merged_cells=merged, cell_alignments=alignments, mode='row', row_range=(inserted_start, inserted_end))

    def delete_row(self):
        self._sync_rows_from_widgets()
        start, end = self._current_row_range()
        old_row_count = self._row_count()
        old_col_count = self._col_count()
        updated, merged = delete_table_rows_with_merges(self.rows, self.merged_cells, start, end)
        alignments = delete_table_alignment_rows(
            self.cell_alignments,
            start,
            end,
            row_count=old_row_count,
            col_count=old_col_count,
        )
        next_row = min(start, len(updated) - 1)
        self._delete_manual_row_heights(start, end)
        self._apply_rows_update(updated, merged_cells=merged, cell_alignments=alignments, mode='row', row_range=(next_row, next_row))

    def insert_column(self, after=True):
        self._sync_rows_from_widgets()
        start, end = self._current_col_range()
        count = self._selected_col_count() if self.selection_mode in {'column', 'table'} else 1
        anchor = end if after else start
        old_row_count = self._row_count()
        old_col_count = self._col_count()
        updated, merged = insert_table_columns_with_merges(
            self.rows,
            self.merged_cells,
            anchor,
            count=count,
            after=after,
        )
        alignments = insert_table_alignment_columns(
            self.cell_alignments,
            anchor,
            count=count,
            after=after,
            row_count=old_row_count,
            col_count=old_col_count,
        )
        inserted_start = anchor + (1 if after else 0)
        inserted_end = inserted_start + count - 1
        self._insert_manual_column_widths(anchor, count=count, after=after)
        self._apply_rows_update(updated, merged_cells=merged, cell_alignments=alignments, mode='column', col_range=(inserted_start, inserted_end))

    def delete_column(self):
        self._sync_rows_from_widgets()
        start, end = self._current_col_range()
        old_row_count = self._row_count()
        old_col_count = self._col_count()
        updated, merged = delete_table_columns_with_merges(self.rows, self.merged_cells, start, end)
        alignments = delete_table_alignment_columns(
            self.cell_alignments,
            start,
            end,
            row_count=old_row_count,
            col_count=old_col_count,
        )
        next_col = min(start, len(updated[0]) - 1)
        self._delete_manual_column_widths(start, end)
        self._apply_rows_update(updated, merged_cells=merged, cell_alignments=alignments, mode='column', col_range=(next_col, next_col))

    def delete_selection(self):
        if self.selection_mode == 'column':
            self.delete_column()
            return
        if self.selection_mode in {'row', 'table'}:
            self.delete_row()
            return
        self.clear_selection()

    def clear_selection(self):
        self._sync_rows_from_widgets()
        row_range = self._current_row_range()
        col_range = self._current_col_range()
        updated = clear_table_cells(
            self.rows,
            mode=self.selection_mode,
            row_range=row_range,
            col_range=col_range,
        )
        self._apply_rows_update(
            updated,
            mode=self.selection_mode if self.selection_mode in {'row', 'column', 'table'} else None,
            row_range=row_range,
            col_range=col_range,
        )

    def merge_selection(self):
        self._sync_rows_from_widgets()
        row_range, col_range = self._current_content_range()
        if (row_range[1] - row_range[0] + 1) * (col_range[1] - col_range[0] + 1) <= 1:
            return
        updated, merged = merge_table_cells(self.rows, self.merged_cells, row_range, col_range)
        self._apply_rows_update(
            updated,
            merged_cells=merged,
            mode=None,
            row_range=row_range,
            col_range=col_range,
        )
        self.selection_mode = 'cell'
        self.selected_row = row_range[0]
        self.selected_col = col_range[0]
        self.selected_row_range = row_range
        self.selected_col_range = col_range
        self._refresh_selection_style()

    def unmerge_selection(self):
        self._sync_rows_from_widgets()
        row_range, col_range = self._current_content_range()
        updated, merged = unmerge_table_cells(self.rows, self.merged_cells, row_range, col_range)
        self._apply_rows_update(
            updated,
            merged_cells=merged,
            mode=None,
            row_range=row_range,
            col_range=col_range,
        )
        self.selection_mode = 'cell'
        self.selected_row = row_range[0]
        self.selected_col = col_range[0]
        self.selected_row_range = row_range
        self.selected_col_range = col_range
        self._refresh_selection_style()

    def toggle_three_line_table(self):
        self._sync_rows_from_widgets()
        self.table_style = (
            TABLE_STYLE_GRID
            if self.table_style == TABLE_STYLE_THREE_LINE
            else TABLE_STYLE_THREE_LINE
        )
        self._render_grid()
        self._notify_change()

    def fit_table_to_window(self):
        self._sync_rows_from_widgets()
        self.manual_column_widths = []
        base_widths = self._calculate_column_widths()
        self.manual_column_widths = self._expand_widths_to_available(base_widths, self._available_table_width())
        self.selection_mode = 'table'
        self.selected_row_range = (0, max(self._row_count() - 1, 0))
        self.selected_col_range = (0, max(self._col_count() - 1, 0))
        self._render_grid()
        self._notify_change()

    def fit_table_to_content(self):
        self._sync_rows_from_widgets()
        self.manual_column_widths = []
        self.selection_mode = 'table'
        self.selected_row_range = (0, max(self._row_count() - 1, 0))
        self.selected_col_range = (0, max(self._col_count() - 1, 0))
        self._render_grid()
        self._notify_change()

    def delete_table(self):
        self._destroy_floating_toolbar()
        self.on_delete(self)

    def destroy(self):
        if self._layout_after_id is not None:
            try:
                self.frame.after_cancel(self._layout_after_id)
            except Exception:
                pass
            self._layout_after_id = None
        if self._parent_configure_bind:
            try:
                self.viewport_parent.unbind('<Configure>', self._parent_configure_bind)
            except Exception:
                pass
            self._parent_configure_bind = None
        self._destroy_floating_toolbar()
        self._destroy_drag_icon()
        window_frame = getattr(self, 'window_frame', None)
        if window_frame is not None and window_frame.winfo_exists():
            window_frame.destroy()
        elif self.frame.winfo_exists():
            self.frame.destroy()


class PaperWritePage(WorkspaceStateMixin):
    PAGE_STATE_ID = 'paper_write'
    PARAGRAPH_INDENT = '　　'
    DEFAULT_BG_SWATCH_COLOR = '#C9CED8'
    TOOLBAR_ICON_SIZE = (20, 20)
    TOOLBAR_SEPARATOR_WIDTH = 2
    TOOLBAR_SEPARATOR_HEIGHT = 22
    STACKABLE_INLINE_FORMAT_TAGS = (
        'fmt_bold',
        'fmt_italic',
        'fmt_underline',
        'fmt_strike',
    )
    PARAGRAPH_ALIGNMENT_TAGS = (
        'fmt_align_left',
        'fmt_align_center',
        'fmt_align_right',
    )
    SCRIPT_FORMAT_TAGS = (
        'fmt_superscript',
        'fmt_subscript',
    )
    LOWER_GREEK_LETTERS = (
        'α', 'β', 'γ', 'δ', 'ε', 'ζ', 'η', 'θ', 'ι', 'κ', 'λ', 'μ',
        'ν', 'ξ', 'ο', 'π', 'ρ', 'σ', 'τ', 'υ', 'φ', 'χ', 'ψ', 'ω',
    )
    NUMBERING_MENU_OPTIONS = (
        ('1,2,3...', 'decimal'),
        ('a,b,c...', 'lower_alpha'),
        ('i,ii,iii...', 'lower_roman'),
        ('A,B,C', 'upper_alpha'),
        ('I,II,III...', 'upper_roman'),
        ('一、二、三…', 'cn_comma'),
        ('（一）（二）（三）…', 'cn_paren'),
        ('①②③…', 'circled_digit'),
        ('α,β,γ,δ', 'lower_greek'),
    )
    BULLET_MENU_OPTIONS = (
        ('○ 大圆圈', '○'),
        ('● 小黑点', '●'),
        ('■ 小方块', '■'),
        ('▼ 下三角', '▼'),
        ('▶ 右三角', '▶'),
    )
    TOOLBAR_ICON_FILES = {
        '撤回': 'png/Withdraw.png',
        '重做': 'png/Redo.png',
        '查替': 'png/Query.png',
        '缩进': 'png/Indentation.png',
        '项目符号': 'png/Bullet_points.png',
        '引用': 'png/Quote.png',
        '编号': 'png/Number.png',
        '加粗': 'png/Bold.png',
        '斜体': 'png/Italic.png',
        '下划线': 'png/Underline.png',
        '删除线': 'png/Strikethrough.png',
        '上标': 'png/Superscript.png',
        '下标': 'png/Subscript.png',
        '格式刷': 'png/Format_Painter.png',
        '字色': 'png/Color.png',
        '字体格式': 'png/Font.png',
    }
    TOOLBAR_TEXT_FALLBACKS = {
        '撤回': '撤',
        '重做': '重',
        '格式刷': '刷',
        '字体格式': '字',
        '字色': '色',
        '底色': '底',
        '表格': '表',
        '加粗': 'B',
        '斜体': 'I',
        '下划线': 'U',
        '删除线': 'S',
        '上标': 'x²',
        '下标': 'x₂',
        '缩进': '缩',
        '项目符号': '•',
        '编号': '1.',
        '居左': '左',
        '居中': '中',
        '居右': '右',
        '引用': '引',
        '查替': '查',
    }
    WORD_CN_FONT_FAMILIES = (
        '宋体', '黑体', '楷体', '仿宋', '微软雅黑',
        '华文中宋', '华文楷体', '华文仿宋', '方正小标宋',
    )
    WORD_EN_FONT_FAMILIES = (
        'Times New Roman', 'Arial', 'Calibri',
        'Cambria', 'Georgia', 'Courier New',
    )
    WORD_FONT_FAMILIES = WORD_CN_FONT_FAMILIES + WORD_EN_FONT_FAMILIES
    WORD_FONT_SIZES = (
        ('初号', 42), ('小初', 36), ('一号', 26), ('小一', 24),
        ('二号', 22), ('小二', 18), ('三号', 16), ('小三', 15),
        ('四号', 14), ('小四', 12), ('五号', 10.5), ('小五', 9),
        ('六号', 7.5), ('小六', 6.5), ('七号', 5.5), ('八号', 5),
    )
    LEVEL_STYLE_DEFAULTS = {
        'h1': {'font': '黑体', 'font_en': 'Times New Roman', 'size_name': '三号', 'size_pt': 16},
        'h2': {'font': '黑体', 'font_en': 'Times New Roman', 'size_name': '四号', 'size_pt': 14},
        'h3': {'font': '黑体', 'font_en': 'Times New Roman', 'size_name': '小四', 'size_pt': 12},
        'body': {'font': '宋体', 'font_en': 'Times New Roman', 'size_name': '小四', 'size_pt': 12},
    }
    FOREGROUND_FORMAT_COLORS = (
        ('黑', 'fmt_fg_black', '#15161A'),
        ('蓝', 'fmt_fg_blue', '#2144B0'),
        ('红', 'fmt_fg_red', '#C92A2A'),
        ('绿', 'fmt_fg_green', '#2B8A3E'),
        ('橙', 'fmt_fg_orange', '#E67700'),
        ('灰', 'fmt_fg_gray', '#5E6372'),
    )
    BACKGROUND_FORMAT_COLORS = (
        ('黄', 'fmt_bg_yellow', '#FFF1A8'),
        ('蓝', 'fmt_bg_blue', '#DCE7FF'),
        ('绿', 'fmt_bg_green', '#D8F5DD'),
        ('粉', 'fmt_bg_pink', '#FFE1EA'),
        ('灰', 'fmt_bg_gray', '#E9ECEF'),
        ('无', '', ''),
    )
    OUTLINE_EMPHASIS_MARKERS = ('***', '___', '**', '__', '*', '_')
    OUTLINE_BULLET_PREFIX_RE = re.compile(r'^\s*[-*•]\s+(.+)$')
    OUTLINE_MARKDOWN_RE = re.compile(r'^(#{1,6})\s+(.+)$')
    OUTLINE_CHAPTER_RE = re.compile(r'^(第[一二三四五六七八九十百千万\d]+(章|节|部分|篇))\s*[:：]?\s*(.+)$')
    OUTLINE_DECIMAL_RE = re.compile(r'^((?:\d+\.)+\d+)\s*[:：]?\s*(.+)$')
    OUTLINE_SINGLE_NUMBER_RE = re.compile(r'^(\d+)(?:([、．.])\s*|\s+)(.+)$')
    OUTLINE_CN_ENUM_RE = re.compile(r'^([一二三四五六七八九十百千万]+[、．.])\s*(.+)$')
    OUTLINE_CN_PAREN_RE = re.compile(r'^(（[一二三四五六七八九十百千万]+）)\s*(.+)$')
    OUTLINE_ARABIC_PAREN_RE = re.compile(r'^((?:（\d+）|\(\d+\)))\s*(.+)$')
    OUTLINE_CN_ABSTRACT_TITLES = frozenset({'摘要', '中文摘要', '摘要与关键词'})
    OUTLINE_CN_KEYWORD_TITLES = frozenset({'关键词', '关键字', '中文关键词', '中文关键字'})
    OUTLINE_EN_ABSTRACT_TITLES = frozenset({'abstract', '英文摘要', 'abstract and keywords'})
    OUTLINE_EN_KEYWORD_TITLES = frozenset({'keywords', '英文关键词', '英文关键字'})
    OUTLINE_INTRO_TITLES = frozenset({'引言', '绪论'})
    OUTLINE_REFERENCE_TITLES = frozenset({'参考文献', 'references', 'bibliography'})
    OUTLINE_APPENDIX_TITLES = frozenset({'附录', 'appendix'})
    OUTLINE_IMPORT_MODE_LOCAL = 'local'
    OUTLINE_IMPORT_MODE_AI = 'ai'
    NUMERIC_REFERENCE_STYLES = frozenset({'GB/T 7714', 'IEEE'})
    BATCH_WRITE_WARNING_SECTION_WORDS = max(1200, PaperWriter.SECTION_MAX_TOKENS * 2 // 3)
    BATCH_WRITE_WARNING_TOTAL_WORDS = PaperWriter.SECTION_MAX_TOKENS * 4
    BATCH_WRITE_WARNING_SECTION_COUNT = 8

    def __init__(self, parent, config_mgr, api_client, history_mgr,
                 set_status, navigate_page=None, app_bridge=None):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.prompt_center = PromptCenter(config_mgr)
        self.writer = PaperWriter(api_client)
        self.aux = AuxTools(api_client)
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr)
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._snapshots = []
        self._sections = {}   # {章节标题: 内容}
        self._section_blocks = {}  # {章节标题: [段落块/表格块]}
        self._section_formats = {}  # {章节标题: [{'tag': 'fmt_*', 'start': '1.0', 'end': '1.4'}]}
        self._section_order = []  # 章节顺序
        self._section_levels = {}  # {章节标题: 层级}
        self._section_parent = {}  # {章节标题: 父标题}
        self._section_children = {}  # {章节标题: [子标题]}
        self._collapsed_sections = set()  # 折叠的分支标题
        self._editor_section_source = ''
        self._outline_editing_title = ''
        self._outline_drag_job = None
        self._outline_drag_data = None
        self._outline_layout_job = None
        self._pending_outline_canvas_width = None
        self._outline_last_width = None
        self._outline_context_title = ''
        self._selection_snapshot = None
        self._editor_selection_range = None
        self._context_revision = 0
        self._find_window = None
        self._find_query_var = None
        self._replace_query_var = None
        self._editor_tool_buttons = {}
        self._editor_tool_images = {}
        self._editor_bg_swatch_images = {}
        self._editor_tool_separators = []
        self._editor_bg_indicator_color = self.DEFAULT_BG_SWATCH_COLOR
        self._fixed_primary_shell_buttons = []
        self._editor_numbering_window = None
        self._editor_bullet_window = None
        self._editor_palette_window = None
        self._editor_popup_root_click_bind = None
        self._editor_format_fonts = {}
        self._editor_font_render_tags = {}
        self._editor_block_widgets = []
        self._active_table_editor = None
        self._outline_level_fonts = {}
        self._stats_layout_job = None
        self._pending_stats_width = None
        self._stats_wraplength = None
        self._format_painter_tags = None
        self._level_font_styles = {k: dict(v) for k, v in self.LEVEL_STYLE_DEFAULTS.items()}
        self._current_cn_font = None
        self._current_en_font = None
        self._current_size_pt = 12
        self._init_workspace_state_support()
        self._build()
        self.restore_saved_workspace_state()
        self._bind_workspace_state_watchers()
        self._enable_workspace_state_autosave()

    # ──────────────────────────────────────────────
    # 构建
    # ──────────────────────────────────────────────

    def _build(self):
        # ── 写作设置卡片 ──────────────────────────────
        self._build_settings_card()

        # ── 主体双栏 ─────────────────────────────────
        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left = self._build_left_panel(body)
        right = self._build_right_panel(body)

        bind_responsive_two_pane(
            body,
            left,
            right,
            breakpoint=1180,
            gap=8,
            left_minsize=260,
            left_weight=25,
            right_weight=75,
            uniform_group='paper_write_body',
        )

    def _bind_workspace_state_watchers(self):
        for widget in (self.topic_entry, self.subject_entry, self.section_entry, self.edit_text):
            widget.bind('<KeyRelease>', self._schedule_workspace_state_save, add='+')
            widget.bind('<<Paste>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')
            widget.bind('<<Cut>>', lambda _event: self.frame.after_idle(self._schedule_workspace_state_save), add='+')

        self.style_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.ref_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.wcount_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())

    def export_workspace_state(self):
        current_section = self.section_entry.get().strip()
        editor_blocks = self._get_current_editor_blocks()
        editor_text = blocks_to_plain_text(editor_blocks)
        sections = dict(self._sections)
        section_blocks = self._copy_section_blocks_map()
        section_formats = self._copy_section_format_map()
        section_order = list(self._section_order)
        section_levels = dict(self._section_levels)
        editor_section_source = self._editor_section_source or current_section
        if editor_section_source:
            sections[editor_section_source] = editor_text
            if editor_blocks:
                section_blocks[editor_section_source] = deep_copy_blocks(editor_blocks)
            else:
                section_blocks.pop(editor_section_source, None)
            section_formats[editor_section_source] = self._serialize_editor_format_spans()
            if editor_section_source not in section_order:
                section_order.append(editor_section_source)
            section_levels[editor_section_source] = section_levels.get(
                editor_section_source,
                self._infer_outline_level(editor_section_source),
            )
        section_blocks = {
            title: deep_copy_blocks(blocks)
            for title, blocks in section_blocks.items()
            if title in sections and blocks
        }

        selected_section = ''
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            selected_section = self._outline_selected.get().strip()

        return {
            'topic': self.topic_entry.get().strip(),
            'style': self.style_var.get(),
            'subject': self.subject_entry.get().strip(),
            'reference_style': self.ref_var.get(),
            'outline_text': self.outline_text.get('1.0', tk.END).strip(),
            'sections': sections,
            'section_blocks': section_blocks,
            'section_formats': section_formats,
            'section_order': section_order,
            'section_levels': section_levels,
            'section_parent': dict(self._section_parent),
            'collapsed_sections': sorted(self._collapsed_sections),
            'selected_section': selected_section,
            'current_section': current_section,
            'editor_section_source': editor_section_source,
            'target_word_count': self.wcount_var.get(),
            'editor_text': editor_text,
            'editor_toolbar_bg_color': self._editor_bg_indicator_color,
            'snapshots': list(self._snapshots),
            'selection_snapshot': dict(self._selection_snapshot or {}),
            'context_revision': self._context_revision,
            'level_font_styles': {k: dict(v) for k, v in self._level_font_styles.items()},
        }

    def restore_workspace_state(self, state):
        if not isinstance(state, dict):
            return

        self.topic_entry.delete(0, tk.END)
        self.topic_entry.insert(0, state.get('topic', ''))
        self.style_var.set(state.get('style', self.style_var.get()))
        self.subject_entry.delete(0, tk.END)
        self.subject_entry.insert(0, state.get('subject', ''))
        self.ref_var.set(state.get('reference_style', self.ref_var.get()))
        self.wcount_var.set(state.get('target_word_count', self.wcount_var.get()))

        self.outline_text.delete('1.0', tk.END)
        outline_text = state.get('outline_text', '')
        if outline_text:
            self.outline_text.insert('1.0', outline_text)

        sections = state.get('sections', {})
        self._sections = dict(sections) if isinstance(sections, dict) else {}
        raw_section_blocks = state.get('section_blocks', {})
        self._section_blocks = self._normalize_section_blocks_map(raw_section_blocks, sections=self._sections)
        fallback_blocks = self._build_section_blocks_from_sections(self._sections)
        for title, blocks in fallback_blocks.items():
            self._section_blocks.setdefault(title, blocks)
        order = state.get('section_order', [])
        self._section_order = [item for item in order if item in self._sections] if isinstance(order, list) else []
        if not self._section_order:
            self._section_order = list(self._sections)
        levels = state.get('section_levels', {})
        if isinstance(levels, dict):
            self._section_levels = {
                key: max(1, int(levels.get(key, self._infer_outline_level(key)) or 1))
                for key in self._section_order
            }
        else:
            self._section_levels = {key: self._infer_outline_level(key) for key in self._section_order}
        parent_map = state.get('section_parent', {})
        if isinstance(parent_map, dict):
            self._section_parent = {
                key: parent_map.get(key, '')
                for key in self._section_order
            }
        else:
            self._section_parent = {}
        self._section_formats = self._sanitize_section_format_map(state.get('section_formats', {}))
        self._restore_level_font_styles(state.get('level_font_styles', {}))
        aliases = self._normalize_outline_structure_state()
        self._rebuild_section_children()
        collapsed = state.get('collapsed_sections', [])
        if isinstance(collapsed, list):
            self._collapsed_sections = {
                resolved_title
                for title in collapsed
                for resolved_title in [self._resolve_normalized_section_title(title, aliases)]
                if resolved_title in self._section_order and self._section_children.get(resolved_title)
            }
        else:
            self._collapsed_sections = set()

        snapshots = state.get('snapshots', [])
        self._snapshots = list(snapshots) if isinstance(snapshots, list) else []
        selection_snapshot = state.get('selection_snapshot', {})
        self._selection_snapshot = dict(selection_snapshot) if isinstance(selection_snapshot, dict) else None

        self._refresh_outline_list()

        selected_section = self._resolve_normalized_section_title(state.get('selected_section', ''), aliases)
        if selected_section in self._sections:
            self._select_section(selected_section, touch_context=False)

        current_section = self._resolve_normalized_section_title(state.get('current_section', ''), aliases)
        self.section_entry.delete(0, tk.END)
        self.section_entry.insert(0, current_section)
        editor_source = state.get('editor_section_source', '') or current_section
        self._editor_section_source = self._resolve_normalized_section_title(editor_source, aliases) or current_section
        toolbar_bg_color = state.get('editor_toolbar_bg_color', self.DEFAULT_BG_SWATCH_COLOR)
        if isinstance(toolbar_bg_color, str) and re.match(r'^#[0-9A-Fa-f]{6}$', toolbar_bg_color):
            self._editor_bg_indicator_color = toolbar_bg_color
        else:
            self._editor_bg_indicator_color = self.DEFAULT_BG_SWATCH_COLOR

        editor_text = self._normalize_section_body(state.get('editor_text', ''))
        editor_formats = self._section_formats.get(self._editor_section_source, [])
        editor_blocks = self._get_section_blocks(self._editor_section_source)
        if not editor_blocks:
            editor_blocks = self._blocks_from_section_text(editor_text)
        self._set_editor_content(editor_text, editor_formats, reset_undo=True, blocks=editor_blocks)
        self._update_background_color_button()

        try:
            self._context_revision = int(state.get('context_revision', 0) or 0)
        except Exception:
            self._context_revision = 0

        self._apply_level_font_to_editor()

        self._update_stats()

    def _build_settings_card(self):
        card = CardFrame(self.frame, title='写作设置')
        card.pack(fill=tk.X, pady=(0, 8))
        inner = card.inner

        # 第一排：论文标题、论文类型、学科/方向、引用格式
        row1 = tk.Frame(inner, bg=COLORS['card_bg'])
        row1.pack(fill=tk.X, pady=(0, 8))

        self.topic_entry = self._labeled_entry(row1, '论文标题', side=tk.LEFT, expand=True)

        self.style_var = tk.StringVar(value='学术论文')
        self._labeled_combo(
            row1, '论文类型', self.style_var,
            ['学术论文', '毕业论文', '综述文章', '研究报告', '实验报告'],
            width=120,
        )

        self.subject_entry = self._labeled_entry(row1, '学科/方向', side=tk.LEFT, width=160)

        self.ref_var = tk.StringVar(value='GB/T 7714')
        self._labeled_combo(
            row1, '引用格式', self.ref_var,
            ['GB/T 7714', 'APA', 'MLA', 'Chicago', 'IEEE'],
            width=110,
        )

        # 第二排：操作按钮
        row2 = tk.Frame(inner, bg=COLORS['card_bg'])
        row2.pack(fill=tk.X)

        self._settings_secondary_action_row = tk.Frame(row2, bg=COLORS['card_bg'])
        self._settings_secondary_action_row.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._settings_primary_action_row = tk.Frame(row2, bg=COLORS['card_bg'])
        self._settings_primary_action_row.pack(side=tk.RIGHT, anchor='e')

        primary_btn_specs = [
            ('生成摘要', self._gen_abstract),
            ('生成大纲', self._gen_outline),
        ]
        secondary_btn_specs = [
            ('新建空白', self._new_doc),
            ('导入文件', self._import_file),
            ('保存快照', self._save_snapshot),
            ('提示词', self._open_prompt_manager),
        ]
        self._settings_action_buttons = {}
        self._settings_action_shells = {}
        button_gap_x = 30
        button_gap_y = 4
        for index, (label, cmd) in enumerate(primary_btn_specs):
            shell, button = create_home_shell_button(
                self._settings_primary_action_row,
                label,
                command=cmd,
                style='primary_fixed',
                border_color=THEMES['light']['card_border'],
            )
            right_gap = button_gap_x if index < len(primary_btn_specs) - 1 else 0
            shell.pack(side=tk.LEFT, padx=(0, right_gap), pady=button_gap_y)
            self._settings_action_buttons[label] = button
            self._settings_action_shells[label] = shell
            self._fixed_primary_shell_buttons.append(shell)

        for index, (label, cmd) in enumerate(secondary_btn_specs):
            shell, button = create_home_shell_button(
                self._settings_secondary_action_row,
                label,
                command=cmd,
                style='secondary',
            )
            right_gap = button_gap_x if index < len(secondary_btn_specs) - 1 else 0
            shell.pack(side=tk.LEFT, padx=(0, right_gap), pady=button_gap_y)
            self._settings_action_buttons[label] = button
            self._settings_action_shells[label] = shell

    def _labeled_entry(self, parent, label, side=tk.LEFT, expand=False, width=None):
        grp = tk.Frame(parent, bg=COLORS['card_bg'])
        grp.pack(side=side, padx=(0, 12), fill=tk.X, expand=expand)
        tk.Label(grp, text=label, font=FONTS['small'], fg=COLORS['text_sub'],
                 bg=COLORS['card_bg']).pack(anchor='w')
        kw = {'font': FONTS['body'], 'bg': COLORS['input_bg'], 'fg': COLORS['text_main'],
              'relief': tk.FLAT, 'highlightthickness': 1,
              'highlightbackground': COLORS['input_border']}
        if width:
            kw['width'] = width // 8
        e = tk.Entry(grp, **kw)
        e.pack(fill=tk.X, pady=(4, 0), ipady=4)
        return e

    def _labeled_combo(self, parent, label, var, values, width=140):
        grp = tk.Frame(parent, bg=COLORS['card_bg'])
        grp.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(grp, text=label, font=FONTS['small'], fg=COLORS['text_sub'],
                 bg=COLORS['card_bg']).pack(anchor='w')
        cb = ttk.Combobox(grp, textvariable=var, values=values,
                          state='readonly', style='Modern.TCombobox', width=width // 8)
        cb.pack(pady=(4, 0))
        return cb

    # ── 左栏 ─────────────────────────────────────

    def _build_left_panel(self, parent):
        left = tk.Frame(parent, bg=COLORS['bg_main'])

        # 论文大纲
        outline_card = CardFrame(left, title='论文大纲')
        outline_card.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        outline_inner = outline_card.inner

        # 大纲列表容器（可滚动）
        list_frame = tk.Frame(outline_inner, bg=COLORS['surface_alt'],
                              highlightbackground=COLORS['card_border'], highlightthickness=1)
        list_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(list_frame, bg=COLORS['surface_alt'], bd=0, highlightthickness=0)
        sb = tk.Scrollbar(list_frame, orient='vertical', command=canvas.yview)
        self._outline_list = tk.Frame(canvas, bg=COLORS['surface_alt'])
        self._outline_list.bind('<Configure>', self._on_outline_inner_configure, add='+')
        self._outline_window_id = canvas.create_window((0, 0), window=self._outline_list, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.bind('<Configure>', self._on_outline_canvas_configure, add='+')
        self._outline_canvas = canvas
        self._outline_empty_label = None
        self._bind_outline_mousewheel(list_frame)
        self._bind_outline_mousewheel(canvas)
        self._bind_outline_mousewheel(self._outline_list)

        # 大纲原文文本（折叠区，用于生成大纲时回显）
        self.outline_text = tk.Text(
            outline_inner, height=0, width=1,
            bg=COLORS['surface_alt'], fg=COLORS['text_main'],
            font=('Consolas', 10), relief=tk.FLAT,
        )
        # 不 pack — 仅作数据存储

        # 实时统计 + 使用建议
        stat_card = CardFrame(left, title='实时统计')
        stat_card.pack(fill=tk.X)
        stat_inner = stat_card.inner

        stats = [
            ('总字符数', 'stat_total'),
            ('中文字符', 'stat_cn'),
            ('英文单词', 'stat_en'),
            ('章节字符数', 'stat_section_total'),
            ('章节中文字符', 'stat_section_cn'),
        ]
        self._stat_labels = {}
        grid = tk.Frame(stat_inner, bg=COLORS['card_bg'])
        grid.pack(fill=tk.X, pady=(0, 8))
        stat_positions = [
            (0, 0, 2),
            (0, 2, 2),
            (0, 4, 2),
            (1, 0, 3),
            (1, 3, 3),
        ]
        for col_index in range(6):
            grid.columnconfigure(col_index, weight=1, uniform='paper_stats')
        for row_index in range(2):
            grid.rowconfigure(row_index, weight=1)
        for (lbl, key), (row_index, col_index, colspan) in zip(stats, stat_positions):
            col = tk.Frame(grid, bg=COLORS['surface_alt'],
                           highlightbackground=COLORS['card_border'], highlightthickness=1)
            col.grid(
                row=row_index,
                column=col_index,
                columnspan=colspan,
                padx=(0, 4),
                pady=(0, 4),
                sticky='nsew',
            )
            tk.Label(col, text=lbl, font=FONTS['tiny'] if hasattr(FONTS, 'tiny') else FONTS['small'],
                     fg=COLORS['text_muted'], bg=COLORS['surface_alt']).pack(pady=(4, 0))
            val_lbl = tk.Label(col, text='0', font=FONTS['body_bold'] if 'body_bold' in FONTS else FONTS['body'],
                               fg=COLORS['primary'], bg=COLORS['surface_alt'])
            val_lbl.pack(pady=(0, 4))
            self._stat_labels[key] = val_lbl

        self.advice_label = tk.Label(
            stat_inner, text='开始写作后将显示使用建议',
            font=FONTS['small'], fg=COLORS['text_muted'],
            bg=COLORS['card_bg'], wraplength=320, justify='left', anchor='w',
        )
        self.advice_label.pack(fill=tk.X)
        stat_inner.bind('<Configure>', self._on_stats_container_configure, add='+')

        return left

    def _on_outline_canvas_configure(self, event=None):
        self._pending_outline_canvas_width = getattr(event, 'width', 0) or self._pending_outline_canvas_width
        self._schedule_outline_layout()

    def _on_outline_inner_configure(self, _event=None):
        self._schedule_outline_layout()

    def _schedule_outline_layout(self, delay_ms=16):
        if self._outline_layout_job is not None:
            return
        try:
            self._outline_layout_job = self.frame.after(delay_ms, self._apply_outline_layout)
        except tk.TclError:
            self._outline_layout_job = None

    def _apply_outline_layout(self):
        self._outline_layout_job = None
        if not hasattr(self, '_outline_canvas') or not hasattr(self, '_outline_window_id'):
            return
        canvas_width = self._pending_outline_canvas_width or self._outline_canvas.winfo_width()
        self._sync_outline_list_width(canvas_width)
        try:
            bbox = self._outline_canvas.bbox('all')
            fallback_width = max(int(canvas_width or 0), 1)
            fallback_height = max(self._outline_list.winfo_reqheight(), 1)
            self._outline_canvas.configure(scrollregion=bbox or (0, 0, fallback_width, fallback_height))
        except tk.TclError:
            return
        self._pending_outline_canvas_width = None

    def _sync_outline_list_width(self, canvas_width=None):
        if not hasattr(self, '_outline_canvas') or not hasattr(self, '_outline_window_id'):
            return

        if canvas_width is None:
            canvas_width = self._outline_canvas.winfo_width()
        if canvas_width <= 1:
            return
        canvas_width = int(canvas_width)
        self._outline_last_width = canvas_width

        self._outline_canvas.itemconfigure(self._outline_window_id, width=canvas_width)

        wraplength = max(canvas_width - 24, 80)
        if self._outline_empty_label is not None and self._outline_empty_label.winfo_exists():
            self._outline_empty_label.configure(wraplength=wraplength)

        for row_info in getattr(self, '_outline_row_widgets', {}).values():
            row_info['title'].configure(wraplength=wraplength)

    def _bind_outline_mousewheel(self, widget):
        if widget is None or getattr(widget, '_outline_mousewheel_bound', False):
            return

        widget.bind('<MouseWheel>', self._on_outline_mousewheel, add='+')
        widget.bind('<Button-4>', self._on_outline_mousewheel, add='+')
        widget.bind('<Button-5>', self._on_outline_mousewheel, add='+')
        widget._outline_mousewheel_bound = True

    def _outline_list_has_scrollable_content(self):
        if not hasattr(self, '_outline_canvas') or not hasattr(self, '_outline_list'):
            return False

        try:
            self._outline_canvas.update_idletasks()
        except Exception:
            return False

        bbox = self._outline_canvas.bbox('all')
        if not bbox:
            return False

        content_height = max(bbox[3] - bbox[1], 0)
        canvas_height = max(self._outline_canvas.winfo_height(), 0)
        return content_height > canvas_height + 1

    def _on_outline_mousewheel(self, event=None):
        if not self._outline_list_has_scrollable_content():
            return

        if getattr(event, 'num', None) == 4:
            delta = -1
        elif getattr(event, 'num', None) == 5:
            delta = 1
        else:
            raw_delta = getattr(event, 'delta', 0)
            if raw_delta == 0:
                return
            delta = int(-raw_delta / 120)
            if delta == 0:
                delta = -1 if raw_delta > 0 else 1

        self._outline_canvas.yview_scroll(delta, 'units')
        return 'break'

    # ── 右栏 ─────────────────────────────────────

    def _build_right_panel(self, parent):
        right = tk.Frame(parent, bg=COLORS['bg_main'])

        edit_card = CardFrame(right, title='内容编辑区')
        edit_card.pack(fill=tk.BOTH, expand=True)
        inner = edit_card.inner
        if edit_card.title_frame is not None:
            spacer = tk.Frame(edit_card.title_frame, bg=COLORS['card_bg'])
            spacer.grid(row=0, column=1, sticky='ew')
            edit_card.title_frame.grid_columnconfigure(2, weight=0)
            self._write_all_sections_button_shell, self._write_all_sections_button = create_home_shell_button(
                edit_card.title_frame,
                '写所有章节',
                command=self._write_all_sections,
                style='secondary',
                padx=12,
                pady=4,
                font=FONTS['small'],
            )
            self._write_all_sections_button_shell.grid(row=0, column=2, sticky='e')

        # 顶部：当前章节 + 目标字数 + 写章节按钮
        top_row = tk.Frame(inner, bg=COLORS['card_bg'])
        top_row.pack(fill=tk.X, pady=(0, 8))

        tk.Label(top_row, text='当前章节', font=FONTS['small'],
                 fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
        self.section_entry = tk.Entry(
            top_row, font=FONTS['body'],
            bg=COLORS['input_bg'], fg=COLORS['text_main'],
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=COLORS['input_border'],
        )
        self.section_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(6, 12))

        tk.Label(top_row, text='目标字数', font=FONTS['small'],
                 fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
        self.wcount_var = tk.StringVar(value='1000')
        ttk.Combobox(
            top_row, textvariable=self.wcount_var,
            values=['500', '800', '1000', '1500', '2000', '3000', '5000'],
            state='readonly', style='Modern.TCombobox', width=6,
        ).pack(side=tk.LEFT, padx=(6, 12))

        self._write_table_button_shell, self._write_table_button = create_home_shell_button(
            top_row,
            '生成表格',
            command=self._generate_table_block,
            style='secondary',
            padx=12,
            pady=6,
            font=FONTS['body'],
            border_color=THEMES['light']['card_border'],
        )
        self._write_table_button_shell.pack(side=tk.LEFT, padx=(0, 8))

        self._write_section_button_shell, self._write_section_button = create_home_shell_button(
            top_row,
            '写当前章节',
            command=self._write_section,
            style='primary_fixed',
            padx=14,
            pady=6,
            font=FONTS['body_bold'],
            border_color=THEMES['light']['card_border'],
        )
        self._write_section_button_shell.pack(side=tk.LEFT)
        self._fixed_primary_shell_buttons.append(self._write_section_button_shell)

        tool_row = tk.Frame(inner, bg=COLORS['card_bg'])
        tool_row.pack(fill=tk.X, pady=(0, 8))
        self._editor_tool_buttons = {}
        self._editor_tool_images = {}
        self._editor_tool_separators = []

        tool_groups = [
            [('撤回', self._editor_undo), ('重做', self._editor_redo)],
            [('格式刷', self._handle_format_painter), ('字体格式', self._open_font_format_dialog), ('字色', lambda: self._open_color_palette('fg')), ('底色', lambda: self._open_color_palette('bg'))],
            [
                ('加粗', self._toggle_bold_selection),
                ('斜体', lambda: self._toggle_inline_format_selection('fmt_italic')),
                ('下划线', lambda: self._toggle_inline_format_selection('fmt_underline')),
                ('删除线', lambda: self._toggle_inline_format_selection('fmt_strike')),
                ('上标', lambda: self._toggle_inline_format_selection('fmt_superscript', exclusive_group=self.SCRIPT_FORMAT_TAGS)),
                ('下标', lambda: self._toggle_inline_format_selection('fmt_subscript', exclusive_group=self.SCRIPT_FORMAT_TAGS)),
            ],
            [('居左', lambda: self._apply_alignment(TABLE_ALIGN_LEFT)), ('居中', lambda: self._apply_alignment(TABLE_ALIGN_CENTER)), ('居右', lambda: self._apply_alignment(TABLE_ALIGN_RIGHT))],
            [('缩进', self._indent_selected_paragraphs), ('项目符号', self._open_bullet_menu), ('编号', self._open_numbering_dialog)],
            [('引用', self._insert_citation_template), ('查替', self._open_find_dialog)],
        ]
        column = 0
        for group_index, group in enumerate(tool_groups):
            for label, command in group:
                btn = ModernButton(
                    tool_row,
                    '',
                    style='ghost',
                    command=command,
                    padx=3,
                    pady=4,
                    font=FONTS['small'],
                    compound='center',
                )
                self._configure_toolbar_icon_button(btn, label)
                self._apply_toolbar_button_content(btn, label)
                btn.grid(row=0, column=column, padx=(0, 3), sticky='ew')
                tool_row.grid_columnconfigure(column, weight=1, uniform='editor_toolbar')
                show_tooltip(btn, label)
                self._editor_tool_buttons[label] = btn
                column += 1
            if group_index < len(tool_groups) - 1:
                separator = tk.Frame(
                    tool_row,
                    bg=self._toolbar_separator_color(),
                    width=self.TOOLBAR_SEPARATOR_WIDTH,
                    height=self.TOOLBAR_SEPARATOR_HEIGHT,
                )
                separator.grid(row=0, column=column, padx=6, pady=2, sticky='ns')
                tool_row.grid_columnconfigure(column, minsize=8)
                self._editor_tool_separators.append(separator)
                column += 1
        self._refresh_editor_toolbar_icons()

        # 编辑区文本框
        edit_frame, self.edit_text = create_scrolled_text(
            inner,
            height=22,
            # 正文需要保留空格输入，不能让空格成为主要换行触发点。
            wrap=tk.CHAR,
            undo=True,
            autoseparators=True,
            maxundo=200,
        )
        edit_frame.pack(fill=tk.BOTH, expand=True)
        self.edit_text.configure(
            bg=COLORS['input_bg'], fg=COLORS['text_main'],
            font=FONTS['body'], relief=tk.FLAT,
            exportselection=False,
        )
        self._refresh_editor_selection_style()
        self.edit_text.tag_configure(
            'outline_focus',
            background=COLORS['accent_light'],
            foreground=COLORS['text_main'],
        )
        self.edit_text.tag_configure(
            'find_match',
            background=COLORS['accent'],
            foreground=COLORS['text_main'],
        )
        self._configure_editor_format_tags()
        self.edit_text.edit_separator()
        self.edit_text.bind('<KeyRelease>', self._on_editor_key_release)
        self.edit_text.bind('<ButtonRelease-1>', self._on_editor_mouse_release)
        self.edit_text.bind('<Return>', self._on_editor_return)
        self.edit_text.bind('<Control-z>', self._editor_undo)
        self.edit_text.bind('<Control-Z>', self._editor_undo)
        self.edit_text.bind('<Control-y>', self._editor_redo)
        self.edit_text.bind('<Control-Y>', self._editor_redo)

        return right

    def _format_tag_names(self):
        tags = list(self.STACKABLE_INLINE_FORMAT_TAGS)
        tags.extend(self.SCRIPT_FORMAT_TAGS)
        tags.extend(self.PARAGRAPH_ALIGNMENT_TAGS)
        tags.extend(tag for _label, tag, _color in self.FOREGROUND_FORMAT_COLORS)
        tags.extend(tag for _label, tag, _color in self.BACKGROUND_FORMAT_COLORS if tag)
        return tags

    def _font_affecting_format_tags(self):
        return list(self.STACKABLE_INLINE_FORMAT_TAGS[:2]) + list(self.SCRIPT_FORMAT_TAGS)

    def _script_format_groups(self):
        return [tuple(self.SCRIPT_FORMAT_TAGS)]

    def _foreground_format_tags(self):
        return [tag for _label, tag, _color in self.FOREGROUND_FORMAT_COLORS]

    def _background_format_tags(self):
        return [tag for _label, tag, _color in self.BACKGROUND_FORMAT_COLORS if tag]

    def _build_editor_font(self, *, bold=False, italic=False, size_delta=0):
        if getattr(self, 'edit_text', None) is not None:
            font = tkfont.Font(root=self.frame, font=self.edit_text.cget('font'))
        else:
            font = tkfont.Font(root=self.frame, font=FONTS['body'])
        font.configure(
            family=self._current_cn_font or font.cget('family'),
            weight='bold' if bold else 'normal',
            slant='italic' if italic else 'roman',
            size=max(8, int(self._current_size_pt or font.cget('size')) + size_delta),
        )
        return font

    def _font_render_tag_name(self, *, bold=False, italic=False, script='normal'):
        parts = ['_fmt_render']
        if bold:
            parts.append('bold')
        if italic:
            parts.append('italic')
        if script != 'normal':
            parts.append(script)
        return '_'.join(parts)

    def _configure_editor_render_fonts(self):
        self._editor_format_fonts = {}
        self._editor_font_render_tags = {}
        script_options = {
            'normal': {'size_delta': 0, 'offset': 0},
            'superscript': {'size_delta': -2, 'offset': 4},
            'subscript': {'size_delta': -2, 'offset': -2},
        }
        for bold in (False, True):
            for italic in (False, True):
                for script, config in script_options.items():
                    if not bold and not italic and script == 'normal':
                        continue
                    tag_name = self._font_render_tag_name(bold=bold, italic=italic, script=script)
                    font = self._build_editor_font(
                        bold=bold,
                        italic=italic,
                        size_delta=config['size_delta'],
                    )
                    self._editor_format_fonts[tag_name] = font
                    self._editor_font_render_tags[(bold, italic, script)] = tag_name
                    self.edit_text.tag_configure(
                        tag_name,
                        font=font,
                        offset=config['offset'],
                    )

    def _font_render_tag_names(self):
        return list(self._editor_font_render_tags.values())

    def _clear_editor_font_render_tags(self):
        for tag in self._font_render_tag_names():
            self.edit_text.tag_remove(tag, '1.0', tk.END)

    def _resolve_font_render_tag(self, start):
        active_tags = set(self.edit_text.tag_names(start))
        bold = 'fmt_bold' in active_tags
        italic = 'fmt_italic' in active_tags
        script = 'normal'
        if 'fmt_superscript' in active_tags:
            script = 'superscript'
        elif 'fmt_subscript' in active_tags:
            script = 'subscript'
        return self._editor_font_render_tags.get((bold, italic, script), '')

    def _refresh_editor_font_render_tags(self):
        self._clear_editor_font_render_tags()
        text_end = self.edit_text.index('end-1c')
        if not self.edit_text.get('1.0', text_end):
            return

        boundaries = {'1.0', text_end}
        for tag in self._font_affecting_format_tags():
            ranges = self.edit_text.tag_ranges(tag)
            for idx in range(0, len(ranges), 2):
                boundaries.add(self.edit_text.index(ranges[idx]))
                boundaries.add(self.edit_text.index(ranges[idx + 1]))

        ordered = sorted(boundaries, key=self._index_sort_key)
        for idx in range(len(ordered) - 1):
            start = ordered[idx]
            end = ordered[idx + 1]
            if self.edit_text.compare(start, '>=', end):
                continue
            render_tag = self._resolve_font_render_tag(start)
            if render_tag:
                self.edit_text.tag_add(render_tag, start, end)
        self._raise_editor_overlay_tags()

    def _configure_editor_format_tags(self):
        self._configure_editor_render_fonts()
        self.edit_text.tag_configure('fmt_underline', underline=1)
        self.edit_text.tag_configure('fmt_strike', overstrike=1)
        self.edit_text.tag_configure('fmt_align_left', justify=tk.LEFT)
        self.edit_text.tag_configure('fmt_align_center', justify=tk.CENTER)
        self.edit_text.tag_configure('fmt_align_right', justify=tk.RIGHT)
        for _label, tag, color in self.FOREGROUND_FORMAT_COLORS:
            self.edit_text.tag_configure(tag, foreground=color)
        for _label, tag, color in self.BACKGROUND_FORMAT_COLORS:
            if not tag:
                continue
            self.edit_text.tag_configure(tag, background=color)
        self._refresh_editor_font_render_tags()
        self._raise_editor_overlay_tags()

    def _refresh_editor_selection_style(self):
        self.edit_text.configure(
            selectbackground=COLORS['accent'],
            selectforeground=COLORS['text_main'],
            inactiveselectbackground=COLORS['accent_light'],
        )
        self._raise_editor_overlay_tags()

    def _raise_editor_overlay_tags(self):
        try:
            self.edit_text.tag_raise('find_match')
            self.edit_text.tag_raise(tk.SEL)
        except tk.TclError:
            pass

    def _is_toolbar_button_active(self, label):
        return label == '格式刷' and self._format_painter_tags is not None

    def _configure_toolbar_icon_button(self, button, label=None):
        background = COLORS['accent_light'] if label and self._is_toolbar_button_active(label) else COLORS['card_bg']
        button.configure(
            bg=background,
            activebackground=background,
            highlightbackground=background,
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT,
            overrelief=tk.FLAT,
            cursor='hand2',
        )

    def _toolbar_text_fallback(self, label):
        return self.TOOLBAR_TEXT_FALLBACKS.get(label, (label or '')[:2])

    def _apply_toolbar_button_content(self, button, label):
        image = self._load_toolbar_icon(label)
        if image:
            button.configure(image=image, text='')
            return
        button.configure(image='', text=self._toolbar_text_fallback(label))

    def _toolbar_icon_foreground(self):
        return COLORS['text_main']

    def _toolbar_separator_color(self):
        return COLORS['text_sub']

    def _load_toolbar_icon(self, label):
        if label == '底色':
            return self._get_background_swatch_image(self._editor_bg_indicator_color)
        cache_key = (label, self._toolbar_icon_foreground())
        if cache_key in self._editor_tool_images:
            return self._editor_tool_images[cache_key]

        filename = self.TOOLBAR_ICON_FILES.get(label, '')
        if not filename:
            return ''
        try:
            image = self._render_tinted_toolbar_icon(filename, self._toolbar_icon_foreground())
        except Exception:
            try:
                image = load_image(filename, max_size=self.TOOLBAR_ICON_SIZE)
            except Exception:
                return ''
        self._editor_tool_images[cache_key] = image
        return image

    def _render_tinted_toolbar_icon(self, filename, color_hex):
        if Image is None or ImageTk is None:
            return load_image(filename, max_size=self.TOOLBAR_ICON_SIZE)

        path = get_resource_path(filename)
        raw = Image.open(path).convert('RGBA')
        raw.thumbnail(self.TOOLBAR_ICON_SIZE, Image.LANCZOS)
        alpha = raw.getchannel('A')
        tinted = Image.new('RGBA', raw.size, color_hex)
        tinted.putalpha(alpha)
        canvas = Image.new('RGBA', self.TOOLBAR_ICON_SIZE, (0, 0, 0, 0))
        offset_x = max((self.TOOLBAR_ICON_SIZE[0] - raw.width) // 2, 0)
        offset_y = max((self.TOOLBAR_ICON_SIZE[1] - raw.height) // 2, 0)
        canvas.alpha_composite(tinted, (offset_x, offset_y))
        return ImageTk.PhotoImage(canvas)

    def _normalize_swatch_color(self, color):
        if isinstance(color, str) and re.match(r'^#[0-9A-Fa-f]{6}$', color):
            return color.upper()
        return self.DEFAULT_BG_SWATCH_COLOR

    def _get_background_swatch_image(self, color):
        normalized = self._normalize_swatch_color(color)
        if normalized in self._editor_bg_swatch_images:
            return self._editor_bg_swatch_images[normalized]

        width, height = self.TOOLBAR_ICON_SIZE
        image = tk.PhotoImage(width=width, height=height)
        image.put(COLORS['card_bg'], to=(0, 0, width, height))
        border = max(2, width // 8)
        right = max(width - border, border + 1)
        bottom = max(height - border, border + 1)
        inner_left = min(border * 2, width - 2)
        inner_top = min(border * 2, height - 2)
        inner_right = max(width - border * 2, inner_left + 1)
        inner_bottom = max(height - border * 2, inner_top + 1)
        image.put(COLORS['text_main'], to=(border, border, right, border + 1))
        image.put(COLORS['text_main'], to=(border, bottom - 1, right, bottom))
        image.put(COLORS['text_main'], to=(border, border, border + 1, bottom))
        image.put(COLORS['text_main'], to=(right - 1, border, right, bottom))
        image.put(normalized, to=(inner_left, inner_top, inner_right, inner_bottom))
        self._editor_bg_swatch_images[normalized] = image
        return image

    def _update_background_color_button(self):
        button = self._editor_tool_buttons.get('底色')
        if button is None:
            return
        button.configure(image=self._get_background_swatch_image(self._editor_bg_indicator_color))

    def _refresh_editor_toolbar_icons(self):
        previous_images = self._editor_tool_images
        previous_swatches = self._editor_bg_swatch_images
        self._editor_tool_images = {}
        self._editor_bg_swatch_images = {}
        for label, button in self._editor_tool_buttons.items():
            self._configure_toolbar_icon_button(button, label)
            self._apply_toolbar_button_content(button, label)
        for separator in self._editor_tool_separators:
            if separator.winfo_exists():
                separator.configure(
                    bg=self._toolbar_separator_color(),
                    width=self.TOOLBAR_SEPARATOR_WIDTH,
                    height=self.TOOLBAR_SEPARATOR_HEIGHT,
                )
        del previous_images
        del previous_swatches

    def _copy_section_format_map(self):
        return {
            title: [dict(span) for span in spans]
            for title, spans in self._section_formats.items()
            if title in self._sections
        }

    @staticmethod
    def _index_sort_key(index):
        try:
            line, column = str(index).split('.', 1)
            return int(line), int(column)
        except Exception:
            return 0, 0

    def _sanitize_section_format_map(self, section_formats):
        if not isinstance(section_formats, dict):
            return {}

        valid_tags = set(self._format_tag_names())
        cleaned = {}
        for title, spans in section_formats.items():
            if title not in self._sections or not isinstance(spans, list):
                continue
            normalized_spans = []
            for span in spans:
                if not isinstance(span, dict):
                    continue
                tag = span.get('tag')
                start = span.get('start')
                end = span.get('end')
                if tag not in valid_tags or not isinstance(start, str) or not isinstance(end, str):
                    continue
                normalized_spans.append({'tag': tag, 'start': start, 'end': end})
            cleaned[title] = sorted(
                normalized_spans,
                key=lambda item: (self._index_sort_key(item['start']), self._index_sort_key(item['end']), item['tag']),
            )
        return cleaned

    def _clear_editor_block_widgets(self):
        for editor in getattr(self, '_editor_block_widgets', []):
            try:
                editor.destroy()
            except Exception:
                pass
        self._editor_block_widgets = []
        self._active_table_editor = None

    def _normalize_section_blocks(self, blocks):
        return sanitize_blocks(blocks)

    def _blocks_from_section_text(self, text):
        blocks = blocks_from_plain_text(text)
        if blocks:
            return deep_copy_blocks(blocks)
        if str(text or '').strip():
            return [new_paragraph_block(text)]
        return []

    def _copy_section_blocks_map(self):
        return {
            title: deep_copy_blocks(blocks)
            for title, blocks in getattr(self, '_section_blocks', {}).items()
            if isinstance(title, str)
        }

    def _normalize_section_blocks_map(self, blocks_map, sections=None, aliases=None):
        if not isinstance(blocks_map, dict):
            return {}

        target_sections = sections if isinstance(sections, dict) else self._sections
        valid_titles = set(target_sections.keys()) if isinstance(target_sections, dict) else set()
        aliases = aliases if isinstance(aliases, dict) else {}
        normalized = {}

        for raw_title, raw_blocks in blocks_map.items():
            title = str(raw_title or '').strip()
            if not title:
                continue
            resolved_title = title
            if resolved_title not in valid_titles:
                resolved_title = aliases.get(title, title)
            if valid_titles and resolved_title not in valid_titles:
                continue
            blocks = self._normalize_section_blocks(raw_blocks)
            if blocks:
                normalized[resolved_title] = deep_copy_blocks(blocks)
        return normalized

    def _build_section_blocks_from_sections(self, sections=None):
        source_sections = sections if isinstance(sections, dict) else self._sections
        blocks_map = {}
        for title, text in source_sections.items():
            blocks = self._blocks_from_section_text(text)
            if blocks:
                blocks_map[title] = blocks
        return blocks_map

    def _get_section_blocks(self, title):
        section = (title or '').strip()
        if not section:
            return []
        blocks = self._section_blocks.get(section)
        if blocks:
            return deep_copy_blocks(blocks)
        text = self._sections.get(section, '')
        return self._blocks_from_section_text(text)

    def _get_current_editor_blocks(self):
        return self._capture_editor_blocks()

    def _get_current_editor_text(self):
        return blocks_to_plain_text(self._get_current_editor_blocks())

    def _capture_editor_blocks(self):
        if not getattr(self, 'edit_text', None):
            return []

        try:
            dump_items = self.edit_text.dump('1.0', 'end-1c', text=True, window=True)
        except Exception:
            dump_items = []

        blocks = []
        text_buffer = []

        def flush_text_buffer():
            if not text_buffer:
                return
            text_value = ''.join(text_buffer)
            text_buffer.clear()
            for block in blocks_from_plain_text(text_value):
                blocks.append(block)

        for item in dump_items:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            kind, value = item[0], item[1]
            if kind == 'text':
                text_buffer.append(value)
                continue
            if kind == 'window':
                flush_text_buffer()
                try:
                    widget = self.edit_text.nametowidget(value)
                except Exception:
                    widget = None
                editor = getattr(widget, '_table_block_editor', None) if widget is not None else None
                if editor is not None:
                    blocks.append(editor.serialize())

        flush_text_buffer()
        return self._normalize_section_blocks(blocks)

    def _render_table_block(self, parent, block):
        window_frame = tk.Frame(parent, bg=COLORS['input_bg'])
        editor = _TableBlockWidget(
            window_frame,
            block,
            on_change=self._on_table_block_changed,
            on_delete=self._remove_table_block_widget,
            on_activate=self._set_active_table_editor,
            viewport_parent=parent,
        )
        editor.window_frame = window_frame
        window_frame._table_block_editor = editor
        window_frame.pack_propagate(False)
        editor.frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, editor.TABLE_EDITOR_RIGHT_GAP))
        editor._sync_window_frame_size()
        self._editor_block_widgets.append(editor)
        return editor

    def _set_active_table_editor(self, editor):
        if editor is not None:
            self._active_table_editor = editor
            self._editor_selection_range = None

    def _render_blocks_to_editor(self, blocks, format_spans=None, reset_undo=False):
        self._clear_editor_block_widgets()
        self.edit_text.delete('1.0', tk.END)

        sanitized_blocks = self._normalize_section_blocks(blocks)
        for block_index, block in enumerate(sanitized_blocks):
            if block_index > 0:
                self.edit_text.insert(tk.END, '\n\n')
            if block['type'] == 'paragraph':
                if block.get('text', ''):
                    self.edit_text.insert(tk.END, block['text'])
                continue
            if block['type'] == 'table':
                editor = self._render_table_block(self.edit_text, block)
                self.edit_text.window_create(tk.END, window=editor.window_frame)

        self._clear_editor_format_tags()
        self._apply_format_spans_to_editor(format_spans or [])
        self._refresh_editor_font_render_tags()
        self.edit_text.tag_remove('find_match', '1.0', tk.END)
        self.edit_text.tag_remove('outline_focus', '1.0', tk.END)
        self._raise_editor_overlay_tags()
        self.edit_text.see('1.0')
        if reset_undo:
            self._reset_editor_undo_stack()

    def _set_section_blocks(self, title, blocks):
        section = (title or '').strip()
        if not section:
            return []
        sanitized = self._normalize_section_blocks(blocks)
        if sanitized:
            self._section_blocks[section] = deep_copy_blocks(sanitized)
        else:
            self._section_blocks.pop(section, None)
        self._sections[section] = blocks_to_plain_text(sanitized)
        return sanitized

    def _remove_table_block_widget(self, editor):
        current_section = self._editor_section_source or self.section_entry.get().strip()
        if not current_section:
            return
        blocks = self._capture_editor_blocks()
        table_id = getattr(editor, 'block_id', '')
        filtered = []
        removed = False
        for block in blocks:
            if block.get('type') == 'table' and str(block.get('table_id', '') or '') == str(table_id or ''):
                removed = True
                continue
            filtered.append(block)
        if not removed:
            return
        self._set_section_blocks(current_section, filtered)
        self._set_editor_content('', self._section_formats.get(current_section, []), reset_undo=True, blocks=filtered)
        self._touch_context_revision()
        self._update_stats()
        self._capture_selection_snapshot()
        self._schedule_workspace_state_save()
        self.set_status('已删除表格')

    def _on_table_block_changed(self):
        current_section = self._editor_section_source or self.section_entry.get().strip()
        if current_section:
            blocks = self._capture_editor_blocks()
            self._set_section_blocks(current_section, blocks)
        self._touch_context_revision()
        self._update_stats()
        self._schedule_workspace_state_save()

    def _clear_editor_format_tags(self):
        for tag in self._format_tag_names():
            self.edit_text.tag_remove(tag, '1.0', tk.END)
        self._clear_editor_font_render_tags()

    def _set_editor_content(self, content, format_spans=None, reset_undo=False, blocks=None):
        if blocks is None:
            self._clear_editor_block_widgets()
            self.edit_text.delete('1.0', tk.END)
            if content:
                self.edit_text.insert('1.0', content)
            self._clear_editor_format_tags()
            self._apply_format_spans_to_editor(format_spans or [])
            self._refresh_editor_font_render_tags()
            self.edit_text.tag_remove('find_match', '1.0', tk.END)
            self.edit_text.tag_remove('outline_focus', '1.0', tk.END)
            self._raise_editor_overlay_tags()
            self.edit_text.see('1.0')
            if reset_undo:
                self._reset_editor_undo_stack()
            return
        self._render_blocks_to_editor(blocks, format_spans=format_spans, reset_undo=reset_undo)

    def _apply_format_spans_to_editor(self, spans):
        if not spans:
            return
        text_end = self.edit_text.index('end-1c')
        for span in spans:
            tag = span.get('tag')
            if tag not in self._format_tag_names():
                continue
            try:
                start = self.edit_text.index(span.get('start', '1.0'))
                end = self.edit_text.index(span.get('end', '1.0'))
            except tk.TclError:
                continue
            if self.edit_text.compare(start, '>=', end):
                continue
            if self.edit_text.compare(start, '>=', text_end):
                continue
            if self.edit_text.compare(end, '>', text_end):
                end = text_end
            self.edit_text.tag_add(tag, start, end)
        self._raise_editor_overlay_tags()

    def _serialize_editor_format_spans(self):
        text_end = self.edit_text.index('end-1c')
        if not self.edit_text.get('1.0', text_end):
            return []

        spans = []
        for tag in self._format_tag_names():
            ranges = self.edit_text.tag_ranges(tag)
            for idx in range(0, len(ranges), 2):
                start = self.edit_text.index(ranges[idx])
                end = self.edit_text.index(ranges[idx + 1])
                if self.edit_text.compare(start, '>=', end):
                    continue
                if self.edit_text.compare(start, '>=', text_end):
                    continue
                if self.edit_text.compare(end, '>', text_end):
                    end = text_end
                spans.append({'tag': tag, 'start': start, 'end': end})

        spans.sort(key=lambda item: (self._index_sort_key(item['start']), self._index_sort_key(item['end']), item['tag']))
        merged = []
        for span in spans:
            if (
                merged
                and merged[-1]['tag'] == span['tag']
                and self.edit_text.compare(span['start'], '<=', merged[-1]['end'])
            ):
                if self.edit_text.compare(span['end'], '>', merged[-1]['end']):
                    merged[-1]['end'] = span['end']
                continue
            merged.append(dict(span))
        return merged

    def _copy_section_formats(self, title):
        return [dict(span) for span in self._section_formats.get(title, [])]

    def _preserve_existing_formats(self, title, previous_text, new_text, source_spans=None):
        if previous_text and new_text.startswith(previous_text):
            spans = source_spans if source_spans is not None else self._copy_section_formats(title)
            return [dict(span) for span in spans]
        return []

    # ──────────────────────────────────────────────
    # 统计
    # ──────────────────────────────────────────────

    def _update_stats(self, event=None):
        full_text, chapter_text = self._collect_stats_texts()

        total = self._count_text_characters(full_text)
        cn = self._count_chinese_characters(full_text)
        en = self._count_english_words(full_text)
        chapter_total = self._count_text_characters(chapter_text)
        chapter_cn = self._count_chinese_characters(chapter_text)

        self._stat_labels['stat_total'].configure(text=str(total))
        self._stat_labels['stat_cn'].configure(text=str(cn))
        self._stat_labels['stat_en'].configure(text=str(en))
        self._stat_labels['stat_section_total'].configure(text=str(chapter_total))
        self._stat_labels['stat_section_cn'].configure(text=str(chapter_cn))

        self._update_advice(total, cn, en, chapter_total, chapter_cn)

    def _on_editor_key_release(self, event=None):
        self._sync_editor_state()

    def _on_editor_mouse_release(self, event=None):
        self._active_table_editor = None
        self.frame.after_idle(self._capture_selection_snapshot)

    def _on_stats_container_configure(self, event=None):
        if not hasattr(self, 'advice_label') or self.advice_label is None:
            return
        self._pending_stats_width = getattr(event, 'width', 0) or self._pending_stats_width
        if self._stats_layout_job is not None:
            return
        try:
            self._stats_layout_job = self.frame.after(16, self._apply_stats_container_layout)
        except tk.TclError:
            self._stats_layout_job = None

    def _apply_stats_container_layout(self):
        self._stats_layout_job = None
        if not hasattr(self, 'advice_label') or self.advice_label is None:
            return
        width = self._pending_stats_width or self.advice_label.winfo_width()
        if width <= 1:
            return
        wraplength = max(int(width) - 18, 180)
        if self._stats_wraplength == wraplength:
            return
        self._stats_wraplength = wraplength
        self.advice_label.configure(wraplength=wraplength)

    def _collect_stats_texts(self):
        current_text = self._get_current_editor_text()
        current_section = self._editor_section_source or self.section_entry.get().strip()

        sections = dict(self._sections)
        if current_section:
            sections[current_section] = current_text
        elif current_text:
            sections['__current__'] = current_text

        full_parts = [
            self._normalize_section_body(content)
            for content in sections.values()
            if self._normalize_section_body(content)
        ]
        return '\n'.join(full_parts), current_text

    @staticmethod
    def _count_text_characters(text):
        normalized = re.sub(r'[\r\n]+', '', text or '')
        return len(normalized)

    @staticmethod
    def _count_chinese_characters(text):
        return len(re.findall(r'[\u4e00-\u9fff]', text or ''))

    @staticmethod
    def _count_english_words(text):
        return len(re.findall(r"\b[a-zA-Z]+(?:[-'][a-zA-Z]+)*\b", text or ''))

    def _sync_editor_state(self, *, touch_context=True, capture_selection=True):
        self._store_current_editor_content()
        self._refresh_editor_font_render_tags()
        self._refresh_mixed_font_tags()
        if touch_context:
            self._touch_context_revision()
        self._update_stats()
        if capture_selection:
            self.frame.after_idle(self._capture_selection_snapshot)
        self._schedule_workspace_state_save()

    def _reset_editor_undo_stack(self):
        try:
            self.edit_text.edit_reset()
        except tk.TclError:
            return
        try:
            self.edit_text.edit_separator()
        except tk.TclError:
            pass

    def _on_editor_return(self, event=None):
        insert_index = self.edit_text.index(tk.INSERT)
        line_start = self.edit_text.index(f'{insert_index} linestart')
        current_line_before_cursor = self.edit_text.get(line_start, insert_index)

        try:
            if self.edit_text.tag_ranges(tk.SEL):
                self.edit_text.delete(tk.SEL_FIRST, tk.SEL_LAST)
                insert_index = self.edit_text.index(tk.INSERT)
                line_start = self.edit_text.index(f'{insert_index} linestart')
                current_line_before_cursor = self.edit_text.get(line_start, insert_index)
        except tk.TclError:
            pass

        suffix = self.PARAGRAPH_INDENT if self._should_auto_indent_line(current_line_before_cursor) else ''
        self.edit_text.insert(tk.INSERT, f'\n{suffix}')
        self.edit_text.edit_separator()
        self._sync_editor_state()
        return 'break'

    def _should_auto_indent_line(self, line_text):
        text = (line_text or '').strip()
        if not text:
            return False
        if self._parse_outline_heading(text):
            return False
        if re.match(r'^\[[0-9]+\]', text):
            return False
        if self._match_attached_bullet_prefix(text) or self._match_attached_numbering_prefix(text):
            return False
        if self._line_has_supported_list_prefix(text):
            return False
        return True

    def _editor_undo(self, event=None):
        try:
            self.edit_text.edit_undo()
        except tk.TclError:
            return 'break'
        self._sync_editor_state()
        return 'break'

    def _editor_redo(self, event=None):
        try:
            self.edit_text.edit_redo()
        except tk.TclError:
            return 'break'
        self._sync_editor_state()
        return 'break'

    def _get_active_selection_range(self):
        try:
            ranges = self.edit_text.tag_ranges(tk.SEL)
        except tk.TclError:
            ranges = ()
        if len(ranges) == 2:
            start = self.edit_text.index(ranges[0])
            end = self.edit_text.index(ranges[1])
            if self.edit_text.compare(start, '<', end):
                return start, end

        stored = self._editor_selection_range or {}
        if (
            stored.get('section') == (self._editor_section_source or self.section_entry.get().strip())
            and stored.get('context_revision') == self._context_revision
            and stored.get('start')
            and stored.get('end')
        ):
            start = self.edit_text.index(stored['start'])
            end = self.edit_text.index(stored['end'])
            if self.edit_text.compare(start, '<', end):
                return start, end
        return '', ''

    def _restore_editor_selection(self, start, end):
        if not start or not end or self.edit_text.compare(start, '>=', end):
            return
        self.edit_text.tag_remove(tk.SEL, '1.0', tk.END)
        self.edit_text.tag_add(tk.SEL, start, end)
        self._raise_editor_overlay_tags()
        self.edit_text.mark_set(tk.INSERT, end)
        self.edit_text.see(start)

    def _selection_required(self):
        start, end = self._get_active_selection_range()
        if not start or not end:
            self.set_status('请先在内容编辑区选中文本后再执行该操作', COLORS['warning'])
            self.edit_text.focus_set()
            return '', ''
        return start, end

    def _selection_fully_has_tag(self, start, end, tag):
        cursor = start
        while self.edit_text.compare(cursor, '<', end):
            tag_range = self.edit_text.tag_nextrange(tag, cursor, end)
            if not tag_range:
                return False
            tag_start = self.edit_text.index(tag_range[0])
            tag_end = self.edit_text.index(tag_range[1])
            if self.edit_text.compare(tag_start, '>', cursor):
                return False
            cursor = tag_end
        return True

    def _remove_tags_from_range(self, tag_names, start, end):
        for tag in tag_names:
            self.edit_text.tag_remove(tag, start, end)

    def _inline_format_groups(self):
        groups = [(tag,) for tag in self.STACKABLE_INLINE_FORMAT_TAGS]
        groups.extend(self._script_format_groups())
        groups.append(tuple(self.PARAGRAPH_ALIGNMENT_TAGS))
        groups.append(tuple(self._foreground_format_tags()))
        groups.append(tuple(self._background_format_tags()))
        return groups

    def _remove_all_inline_format_tags_from_range(self, start, end):
        self._remove_tags_from_range(self._format_tag_names(), start, end)

    def _collect_uniform_format_tags(self, start, end):
        applied = []
        for group in self._inline_format_groups():
            if len(group) == 1:
                tag = group[0]
                if self._selection_fully_has_tag(start, end, tag):
                    applied.append(tag)
                continue
            chosen = next((tag for tag in group if self._selection_fully_has_tag(start, end, tag)), '')
            if chosen:
                applied.append(chosen)
        return applied

    def _collect_inherited_format_tags(self, start, end):
        active_tags = set(self.edit_text.tag_names(start))
        inherited = []
        for tag in self.STACKABLE_INLINE_FORMAT_TAGS:
            if tag in active_tags or self.edit_text.tag_nextrange(tag, start, end):
                inherited.append(tag)

        for group in [tuple(self.SCRIPT_FORMAT_TAGS), tuple(self._foreground_format_tags()), tuple(self._background_format_tags())]:
            chosen = next((tag for tag in group if tag in active_tags), '')
            if not chosen:
                chosen = next((tag for tag in group if self.edit_text.tag_nextrange(tag, start, end)), '')
            if chosen:
                inherited.append(chosen)
        return inherited

    def _replace_range_text_preserving_formats(self, start, end, replacement_text):
        inherited_tags = self._collect_inherited_format_tags(start, end)
        self.edit_text.delete(start, end)
        if replacement_text:
            self.edit_text.insert(start, replacement_text)
            new_end = f'{start}+{len(replacement_text)}c'
            self._remove_all_inline_format_tags_from_range(start, new_end)
            for tag in inherited_tags:
                self.edit_text.tag_add(tag, start, new_end)
            return new_end
        return start

    def _toggle_bold_selection(self):
        self._toggle_inline_format_selection('fmt_bold')

    def _toggle_inline_format_selection(self, tag_name, exclusive_group=None):
        start, end = self._selection_required()
        if not start:
            return
        group = tuple(exclusive_group or (tag_name,))
        should_remove = self._selection_fully_has_tag(start, end, tag_name)
        self.edit_text.edit_separator()
        if should_remove:
            self.edit_text.tag_remove(tag_name, start, end)
        else:
            if group:
                self._remove_tags_from_range(group, start, end)
            self.edit_text.tag_add(tag_name, start, end)
        self.edit_text.edit_separator()
        self._restore_editor_selection(start, end)
        self._sync_editor_state()
        self.edit_text.focus_set()

    def _selection_line_range(self, start, end):
        line_start = self.edit_text.index(f'{start} linestart')
        if self.edit_text.compare(end, '>', f'{end} linestart'):
            line_end = self.edit_text.index(f'{end} lineend')
        else:
            line_end = self.edit_text.index(f'{start} lineend')
        return line_start, line_end

    def _apply_text_alignment(self, alignment):
        start, end = self._selection_required()
        if not start:
            return False
        tag_map = {
            TABLE_ALIGN_LEFT: 'fmt_align_left',
            TABLE_ALIGN_CENTER: 'fmt_align_center',
            TABLE_ALIGN_RIGHT: 'fmt_align_right',
        }
        tag_name = tag_map.get(normalize_table_alignment(alignment), 'fmt_align_left')
        line_start, line_end = self._selection_line_range(start, end)
        self.edit_text.edit_separator()
        self._remove_tags_from_range(self.PARAGRAPH_ALIGNMENT_TAGS, line_start, line_end)
        self.edit_text.tag_add(tag_name, line_start, line_end)
        self.edit_text.edit_separator()
        self._restore_editor_selection(start, end)
        self._sync_editor_state()
        self.edit_text.focus_set()
        return True

    def _apply_alignment(self, alignment):
        editor = getattr(self, '_active_table_editor', None)
        if editor is not None and editor.frame.winfo_exists():
            editor.apply_alignment(alignment)
            self.set_status('已调整表格单元格对齐方式')
            return
        if self._apply_text_alignment(alignment):
            self.set_status('已调整正文对齐方式')

    def _clear_format_painter(self, *, refresh=True):
        self._format_painter_tags = None
        if refresh:
            self._refresh_editor_toolbar_icons()

    def _handle_format_painter(self):
        if self._format_painter_tags is not None:
            start, end = self._get_active_selection_range()
            if not start:
                self._clear_format_painter()
                self.set_status('格式刷已取消')
                self.edit_text.focus_set()
                return
            self.edit_text.edit_separator()
            self._remove_all_inline_format_tags_from_range(start, end)
            for tag in self._format_painter_tags:
                self.edit_text.tag_add(tag, start, end)
            self.edit_text.edit_separator()
            self._restore_editor_selection(start, end)
            self._clear_format_painter()
            self._sync_editor_state()
            self.edit_text.focus_set()
            self.set_status('已将复制的格式应用到当前选区')
            return

        start, end = self._selection_required()
        if not start:
            return
        self._format_painter_tags = self._collect_uniform_format_tags(start, end)
        self._refresh_editor_toolbar_icons()
        self.edit_text.focus_set()
        self.set_status('格式刷已就绪，请选中目标文本后再次点击格式刷')

    def _apply_color_to_selection(self, mode, tag_name):
        start, end = self._selection_required()
        if not start:
            return False

        target_tags = self._foreground_format_tags() if mode == 'fg' else self._background_format_tags()
        self.edit_text.edit_separator()
        self._remove_tags_from_range(target_tags, start, end)
        if tag_name:
            self.edit_text.tag_add(tag_name, start, end)
        self.edit_text.edit_separator()
        self._restore_editor_selection(start, end)
        if mode == 'bg':
            resolved_color = next(
                (color for _label, tag, color in self.BACKGROUND_FORMAT_COLORS if tag == tag_name),
                self.DEFAULT_BG_SWATCH_COLOR,
            )
            self._editor_bg_indicator_color = self._normalize_swatch_color(resolved_color)
            self._update_background_color_button()
        self._sync_editor_state()
        self.edit_text.focus_set()
        return True

    def _apply_palette_choice(self, mode, tag_name, color, popup_attr):
        self._apply_color_to_selection(mode, tag_name)
        self._close_popup_window(popup_attr)

    def _close_popup_window(self, attr_name):
        self._unbind_popup_outside_close()
        window = getattr(self, attr_name, None)
        if window is not None and window.winfo_exists():
            window.destroy()
        setattr(self, attr_name, None)

    def _unbind_popup_outside_close(self):
        if not self._editor_popup_root_click_bind:
            return
        try:
            self.frame.winfo_toplevel().unbind('<Button-1>', self._editor_popup_root_click_bind)
        except Exception:
            pass
        self._editor_popup_root_click_bind = None

    def _bind_popup_outside_close(self, attr_name, anchor):
        self._unbind_popup_outside_close()
        root = self.frame.winfo_toplevel()

        def on_root_click(event=None):
            popup = getattr(self, attr_name, None)
            widget = getattr(event, 'widget', None)
            if popup is None or not popup.winfo_exists():
                self._unbind_popup_outside_close()
                return
            if widget is anchor or (widget and str(widget).startswith(str(anchor))):
                return
            if widget is popup or (widget and str(widget).startswith(str(popup))):
                return
            self._close_popup_window(attr_name)

        self._editor_popup_root_click_bind = root.bind('<Button-1>', on_root_click, add='+')

    def _create_toolbar_popup(self, button_label, attr_name, title, borderless=False, close_on_outside_click=False):
        self._close_popup_window(attr_name)
        anchor = self._editor_tool_buttons.get(button_label)
        if anchor is None:
            return None

        window = tk.Toplevel(self.frame)
        window.title(title)
        window.transient(self.frame.winfo_toplevel())
        window.resizable(False, False)
        window.configure(bg=COLORS['card_bg'])
        if borderless:
            window.wm_overrideredirect(True)
            try:
                window.attributes('-topmost', True)
            except Exception:
                pass
        else:
            window.bind('<FocusOut>', lambda _event, name=attr_name: self.frame.after(80, lambda: self._close_popup_window(name)))

        anchor.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        window.geometry(f'+{x}+{y}')
        setattr(self, attr_name, window)
        window.lift()
        if close_on_outside_click:
            self.frame.after_idle(lambda name=attr_name, target=anchor: self._bind_popup_outside_close(name, target))
        return window

    def _open_numbering_dialog(self):
        window = self._create_toolbar_popup(
            '编号',
            '_editor_numbering_window',
            '插入编号',
            borderless=True,
            close_on_outside_click=True,
        )
        if window is None:
            return

        shell = tk.Frame(
            window,
            bg=COLORS['card_bg'],
            padx=6,
            pady=6,
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        shell.pack(fill=tk.BOTH, expand=True)
        for index, (button_text, style_key) in enumerate(self.NUMBERING_MENU_OPTIONS):
            button = ModernButton(
                shell,
                button_text,
                style='ghost',
                command=lambda numbering_style=style_key: (self._apply_numbering_to_selected_lines(numbering_style), self._close_popup_window('_editor_numbering_window')),
                padx=8,
                pady=4,
                font=FONTS['small'],
            )
            button.pack(fill=tk.X, pady=(0, 4 if index < len(self.NUMBERING_MENU_OPTIONS) - 1 else 0))
        window.update_idletasks()
        window.lift()

    def _open_bullet_menu(self):
        window = self._create_toolbar_popup(
            '项目符号',
            '_editor_bullet_window',
            '插入项目符号',
            borderless=True,
            close_on_outside_click=True,
        )
        if window is None:
            return

        shell = tk.Frame(
            window,
            bg=COLORS['card_bg'],
            padx=6,
            pady=6,
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        shell.pack(fill=tk.BOTH, expand=True)

        for index, (button_text, symbol) in enumerate(self.BULLET_MENU_OPTIONS):
            button = ModernButton(
                shell,
                button_text,
                style='ghost',
                command=lambda bullet_symbol=symbol: (self._apply_bullets_to_selected_lines(bullet_symbol), self._close_popup_window('_editor_bullet_window')),
                padx=8,
                pady=4,
                font=FONTS['small'],
            )
            button.pack(fill=tk.X, pady=(0, 4 if index < len(self.BULLET_MENU_OPTIONS) - 1 else 0))
        window.update_idletasks()
        window.lift()

    # ──────────────────────────────────────────────
    # 字体格式统一设置
    # ──────────────────────────────────────────────

    def _normalize_level_font_style(self, level_key, style):
        # 恢复工作区状态时只接受四组层级配置，其余字段回退到默认值。
        defaults = dict(self.LEVEL_STYLE_DEFAULTS.get(level_key, {}))
        if not isinstance(style, dict):
            return defaults

        normalized = dict(defaults)
        font_name = str(style.get('font', '') or '').strip()
        if font_name:
            normalized['font'] = font_name

        font_en_name = str(style.get('font_en', '') or '').strip()
        if font_en_name:
            normalized['font_en'] = font_en_name

        size_map = {name: pt for name, pt in self.WORD_FONT_SIZES}
        size_name = str(style.get('size_name', '') or '').strip()
        if size_name in size_map:
            normalized['size_name'] = size_name
            normalized['size_pt'] = size_map[size_name]
            return normalized

        raw_size_pt = style.get('size_pt', None)
        try:
            size_pt = float(raw_size_pt)
        except (TypeError, ValueError):
            size_pt = None
        if size_pt is None or size_pt <= 0:
            return normalized

        normalized['size_pt'] = size_pt
        matched_name = next(
            (name for name, pt in self.WORD_FONT_SIZES if float(pt) == size_pt),
            '',
        )
        if matched_name:
            normalized['size_name'] = matched_name
        return normalized

    def _restore_level_font_styles(self, saved_styles):
        saved = saved_styles if isinstance(saved_styles, dict) else {}
        for key in ('h1', 'h2', 'h3', 'body'):
            self._level_font_styles[key] = self._normalize_level_font_style(
                key,
                saved.get(key, {}),
            )
        self._outline_level_fonts = {}

    def _open_font_format_dialog(self):
        root = self.frame.winfo_toplevel()
        dlg = tk.Toplevel(root)
        dlg.title('字体格式统一设置')
        dlg.configure(bg=COLORS['card_bg'])
        dlg.transient(root)
        dlg.withdraw()

        size_names = [name for name, _pt in self.WORD_FONT_SIZES]
        level_labels = [
            ('h1', '一级标题'),
            ('h2', '二级标题'),
            ('h3', '三级标题'),
            ('body', '正文'),
        ]
        combos = {}

        header_frame = tk.Frame(dlg, bg=COLORS['card_bg'])
        header_frame.pack(fill=tk.X, padx=20, pady=(20, 6))
        for col, text in enumerate(['层级', '中文字体', '英文字体', '字号']):
            tk.Label(header_frame, text=text, bg=COLORS['card_bg'], fg=COLORS['text_main'],
                     font=FONTS['small']).grid(row=0, column=col, padx=10, sticky='w')
            header_frame.grid_columnconfigure(col, weight=1 if col > 0 else 0)

        rows_frame = tk.Frame(dlg, bg=COLORS['card_bg'])
        rows_frame.pack(fill=tk.X, padx=20, pady=6)

        for row_idx, (key, label) in enumerate(level_labels):
            current = self._level_font_styles.get(key, self.LEVEL_STYLE_DEFAULTS[key])
            tk.Label(rows_frame, text=label, bg=COLORS['card_bg'], fg=COLORS['text_main'],
                     font=FONTS['body'], width=8, anchor='w').grid(row=row_idx, column=0, padx=10, pady=6, sticky='w')

            font_var = tk.StringVar(value=current.get('font', '宋体'))
            font_cb = ttk.Combobox(rows_frame, textvariable=font_var, values=list(self.WORD_CN_FONT_FAMILIES),
                                   state='readonly', width=12)
            font_cb.grid(row=row_idx, column=1, padx=10, pady=6, sticky='ew')

            font_en_var = tk.StringVar(value=current.get('font_en', 'Times New Roman'))
            font_en_cb = ttk.Combobox(rows_frame, textvariable=font_en_var, values=list(self.WORD_EN_FONT_FAMILIES),
                                      state='readonly', width=16)
            font_en_cb.grid(row=row_idx, column=2, padx=10, pady=6, sticky='ew')

            size_var = tk.StringVar(value=current.get('size_name', '小四'))
            size_cb = ttk.Combobox(rows_frame, textvariable=size_var, values=size_names,
                                   state='readonly', width=8)
            size_cb.grid(row=row_idx, column=3, padx=10, pady=6, sticky='ew')

            combos[key] = (font_var, font_en_var, size_var)
        rows_frame.grid_columnconfigure(1, weight=1)
        rows_frame.grid_columnconfigure(2, weight=1)
        rows_frame.grid_columnconfigure(3, weight=1)

        size_map = {name: pt for name, pt in self.WORD_FONT_SIZES}

        def apply_settings():
            for key, (fv, fev, sv) in combos.items():
                font_name = fv.get()
                font_en_name = fev.get()
                size_name = sv.get()
                size_pt = size_map.get(size_name, 12)
                self._level_font_styles[key] = {'font': font_name, 'font_en': font_en_name, 'size_name': size_name, 'size_pt': size_pt}
            self._outline_level_fonts = {}
            self._apply_level_font_to_editor()
            if getattr(self, '_outline_row_widgets', None):
                self._refresh_outline_list()
            self._schedule_workspace_state_save()
            dlg.destroy()

        def reset_defaults():
            for key, (fv, fev, sv) in combos.items():
                defaults = self.LEVEL_STYLE_DEFAULTS[key]
                fv.set(defaults['font'])
                fev.set(defaults['font_en'])
                sv.set(defaults['size_name'])

        btn_frame = tk.Frame(dlg, bg=COLORS['card_bg'])
        btn_frame.pack(fill=tk.X, padx=20, pady=(10, 20))
        ModernButton(btn_frame, '重置为默认', style='ghost', command=reset_defaults,
                     font=FONTS['small']).pack(side=tk.LEFT, padx=6)
        ModernButton(btn_frame, '应用', style='primary', command=apply_settings,
                     font=FONTS['small']).pack(side=tk.RIGHT, padx=6)

        dlg.update_idletasks()
        dlg_w = max(dlg.winfo_reqwidth(), 560)
        dlg_h = max(dlg.winfo_reqheight(), 300)
        rx = root.winfo_x()
        ry = root.winfo_y()
        rw = root.winfo_width()
        rh = root.winfo_height()
        x = rx + (rw - dlg_w) // 2
        y = ry + (rh - dlg_h) // 2
        dlg.geometry(f'{dlg_w}x{dlg_h}+{x}+{y}')
        dlg.resizable(False, False)
        dlg.deiconify()
        dlg.grab_set()
        dlg.focus_force()

    def _apply_level_font_to_editor(self):
        style = self._level_font_styles.get('body', self.LEVEL_STYLE_DEFAULTS.get('body', {}))
        self._current_cn_font = style.get('font', '宋体')
        self._current_en_font = style.get('font_en', 'Times New Roman')
        self._current_size_pt = int(style.get('size_pt', 12))
        apply_mixed_fonts(self.edit_text, self._current_cn_font, self._current_en_font, self._current_size_pt)
        self._configure_editor_render_fonts()
        self._refresh_editor_font_render_tags()

    def _refresh_mixed_font_tags(self):
        if not getattr(self, '_current_cn_font', None):
            return
        apply_mixed_fonts(self.edit_text, self._current_cn_font, self._current_en_font, self._current_size_pt)

    def _open_color_palette(self, mode):
        label = '字色' if mode == 'fg' else '底色'
        title = '选择字色' if mode == 'fg' else '选择底色'
        attr_name = '_editor_palette_window'
        window = self._create_toolbar_popup(label, attr_name, title, borderless=True, close_on_outside_click=True)
        if window is None:
            return

        palette = self.FOREGROUND_FORMAT_COLORS if mode == 'fg' else self.BACKGROUND_FORMAT_COLORS
        shell = tk.Frame(
            window,
            bg=COLORS['card_bg'],
            padx=6,
            pady=6,
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        shell.pack(fill=tk.BOTH, expand=True)

        for index, (button_text, tag_name, color) in enumerate(palette):
            row = index // 3
            column = index % 3
            color_value = color or COLORS['card_bg']
            button = tk.Button(
                shell,
                text='',
                width=2,
                height=1,
                bg=color_value,
                activebackground=color_value,
                relief=tk.FLAT,
                bd=0,
                highlightthickness=1,
                highlightbackground=COLORS['card_border'],
                highlightcolor=COLORS['primary'],
                cursor='hand2',
                command=lambda tag=tag_name, action_mode=mode, color_choice=color: self._apply_palette_choice(action_mode, tag, color_choice, attr_name),
            )
            if not color:
                none_image = self._get_background_swatch_image(self.DEFAULT_BG_SWATCH_COLOR)
                button.configure(image=none_image, compound='center', bg=COLORS['card_bg'], activebackground=COLORS['card_bg'])
                button.image = none_image
            button.grid(row=row, column=column, padx=3, pady=3, sticky='nsew')
            shell.grid_columnconfigure(column, weight=1, uniform=f'palette_{mode}')
        for row_index in range(max(2, (len(palette) + 2) // 3)):
            shell.grid_rowconfigure(row_index, weight=1, uniform=f'palette_row_{mode}')
        window.update_idletasks()
        window.lift()

    def _get_selected_line_range(self):
        stored = self._editor_selection_range or {}
        if (
            stored.get('section') == self.section_entry.get().strip()
            and stored.get('context_revision') == self._context_revision
            and stored.get('start')
            and stored.get('end')
        ):
            start = stored['start']
            end = stored['end']
        else:
            ranges = self.edit_text.tag_ranges(tk.SEL)
            if len(ranges) == 2:
                start = self.edit_text.index(ranges[0])
                end = self.edit_text.index(ranges[1])
            else:
                line = int(self.edit_text.index(tk.INSERT).split('.')[0])
                return line, line

        start_line = int(start.split('.')[0])
        end_line = int(end.split('.')[0])
        if end.endswith('.0') and end_line > start_line:
            end_line -= 1
        return start_line, max(start_line, end_line)

    def _format_list_debug_value(self, value):
        if isinstance(value, str):
            return ascii(value)
        if isinstance(value, dict):
            items = ', '.join(
                f'{key}:{self._format_list_debug_value(val)}'
                for key, val in value.items()
            )
            return '{' + items + '}'
        if isinstance(value, tuple):
            items = ', '.join(self._format_list_debug_value(item) for item in value)
            if len(value) == 1:
                items += ','
            return '(' + items + ')'
        if isinstance(value, list):
            items = ', '.join(self._format_list_debug_value(item) for item in value)
            return '[' + items + ']'
        if isinstance(value, set):
            items = ', '.join(self._format_list_debug_value(item) for item in sorted(value, key=repr))
            return '{' + items + '}'
        return repr(value)

    def _write_list_debug_log(self, event, **fields):
        if not self.app_bridge or not hasattr(self.app_bridge, 'write_app_log'):
            return
        try:
            parts = [f'[paper_write.list_debug] {event}']
            for key, value in fields.items():
                parts.append(f'{key}={self._format_list_debug_value(value)}')
            self.app_bridge.write_app_log(' '.join(parts), level='DEBUG')
        except Exception:
            pass

    def _get_list_debug_selection_ranges(self):
        try:
            ranges = self.edit_text.tag_ranges(tk.SEL)
        except Exception as exc:
            return [f'<selection-error:{exc}>']
        resolved = []
        for item in ranges:
            try:
                resolved.append(self.edit_text.index(item))
            except Exception as exc:
                resolved.append(f'<index-error:{exc}>')
        return resolved

    def _get_line_text_for_debug(self, line_no):
        try:
            return self.edit_text.get(f'{line_no}.0', f'{line_no}.0 lineend')
        except Exception as exc:
            return f'<line-error:{exc}>'

    def _log_list_debug_selection_context(self, action, **extra_fields):
        try:
            insert_index = self.edit_text.index(tk.INSERT)
        except Exception as exc:
            insert_index = f'<insert-error:{exc}>'
        fields = {
            'action': action,
            'stored_selection': dict(self._editor_selection_range or {}),
            'tk_selection': self._get_list_debug_selection_ranges(),
            'insert_index': insert_index,
        }
        fields.update(extra_fields)
        self._write_list_debug_log('selection_context', **fields)

    def _log_list_debug_line_window(self, action, start_line, end_line, limit=12):
        if start_line > end_line:
            return
        total = end_line - start_line + 1
        sample_end = min(end_line, start_line + max(1, limit) - 1)
        self._write_list_debug_log(
            'selection_window',
            action=action,
            start_line=start_line,
            end_line=end_line,
            sampled_lines=sample_end - start_line + 1,
            total_lines=total,
        )
        for line_no in range(start_line, sample_end + 1):
            line_text = self._get_line_text_for_debug(line_no)
            self._write_list_debug_log(
                'selection_line',
                action=action,
                line_no=line_no,
                meaningful=self._line_has_meaningful_text(line_text),
                text=line_text,
            )
        if sample_end < end_line:
            self._write_list_debug_log(
                'selection_window_truncated',
                action=action,
                omitted_start=sample_end + 1,
                omitted_end=end_line,
            )

    def _remove_existing_bullet_prefix(self, line_no):
        line_start = f'{line_no}.0'
        line_end = f'{line_no}.0 lineend'
        line_text = self.edit_text.get(line_start, line_end)
        match = re.match(r'^(\s*)([○●■▼▶])\s+', line_text)
        if not match:
            return line_start
        bullet_start = f'{line_no}.{len(match.group(1))}'
        bullet_end = f'{line_no}.{len(match.group(0))}'
        self.edit_text.delete(bullet_start, bullet_end)
        self._write_list_debug_log(
            'remove_existing_bullet_prefix',
            line_no=line_no,
            removed_prefix=match.group(0),
            before_text=line_text,
            after_text=self._get_line_text_for_debug(line_no),
        )
        return bullet_start

    def _collect_nonempty_line_numbers(self, start_line, end_line):
        lines = []
        for line_no in range(start_line, end_line + 1):
            line_text = self.edit_text.get(f'{line_no}.0', f'{line_no}.0 lineend')
            if self._line_has_meaningful_text(line_text):
                lines.append(line_no)
        return lines

    @staticmethod
    def _line_has_meaningful_text(line_text):
        normalized = re.sub(r'[\s\u3000\u200b\ufeff\u2060]+', '', line_text or '')
        return bool(normalized)

    @staticmethod
    def _first_meaningful_text_char(line_text):
        normalized = re.sub(r'^[\s\u3000\u200b\ufeff\u2060]+', '', line_text or '')
        return normalized[0] if normalized else ''

    def _list_marker_separator_for_text(self, line_text):
        first_char = self._first_meaningful_text_char(line_text)
        if not first_char:
            return ' '
        if first_char.isascii() and (first_char.isalnum() or first_char in '"\'([{'):
            return ' '
        return ''

    def _list_marker_separator_for_line(self, line_no):
        return self._list_marker_separator_for_text(self._get_line_text_for_debug(line_no))

    def _match_attached_bullet_prefix(self, line_text):
        symbols = ''.join(re.escape(symbol) for _label, symbol in self.BULLET_MENU_OPTIONS if symbol)
        if not symbols:
            return None
        return re.match(rf'^(\s*)([{symbols}])(?=\S)', line_text or '')

    @staticmethod
    def _match_attached_numbering_prefix(line_text):
        return re.match(
            r'^(\s*)((?:'
            r'[0-9]+\.'
            r'|[a-zA-Z]+\.'
            r'|[ivxlcdmIVXLCDM]+\.'
            r'|[\u2460-\u2473]'
            r'))(?=\S)',
            line_text or '',
        )

    def _match_bullet_marker_token(self, line_text):
        symbols = ''.join(re.escape(symbol) for _label, symbol in self.BULLET_MENU_OPTIONS if symbol)
        if not symbols:
            return None
        return re.match(rf'^(\s*)([{symbols}])', line_text or '')

    @staticmethod
    def _match_numbering_marker_token(line_text):
        return re.match(
            r'^(\s*)((?:'
            r'[0-9]+\.'
            r'|[a-zA-Z]+\.'
            r'|[ivxlcdmIVXLCDM]+\.'
            r'|[\u4e00-\u9fa5]+、'
            r'|（[\u4e00-\u9fa5]+）'
            r'|[\u2460-\u2473]'
            r'))',
            line_text or '',
        )

    def _remove_attached_bullet_prefix(self, line_no):
        line_start = f'{line_no}.0'
        line_end = f'{line_no}.0 lineend'
        line_text = self.edit_text.get(line_start, line_end)
        match = self._match_attached_bullet_prefix(line_text)
        if not match:
            return line_start
        bullet_start = f'{line_no}.{len(match.group(1))}'
        bullet_end = f'{line_no}.{len(match.group(0))}'
        self.edit_text.delete(bullet_start, bullet_end)
        self._write_list_debug_log(
            'remove_attached_bullet_prefix',
            line_no=line_no,
            removed_prefix=match.group(0),
            before_text=line_text,
            after_text=self._get_line_text_for_debug(line_no),
        )
        return bullet_start

    def _remove_attached_numbering_prefix(self, line_no):
        line_start = f'{line_no}.0'
        line_end = f'{line_no}.0 lineend'
        line_text = self.edit_text.get(line_start, line_end)
        match = self._match_attached_numbering_prefix(line_text)
        if not match:
            return line_start
        prefix_start = f'{line_no}.{len(match.group(1))}'
        prefix_end = f'{line_no}.{len(match.group(0))}'
        self.edit_text.delete(prefix_start, prefix_end)
        self._write_list_debug_log(
            'remove_attached_numbering_prefix',
            line_no=line_no,
            removed_prefix=match.group(0),
            before_text=line_text,
            after_text=self._get_line_text_for_debug(line_no),
        )
        return prefix_start

    def _resolve_list_target_lines(self, start_line, end_line):
        target_lines = self._collect_nonempty_line_numbers(start_line, end_line)
        self._write_list_debug_log(
            'resolve_targets_initial',
            start_line=start_line,
            end_line=end_line,
            selected_nonempty_lines=target_lines,
        )
        if target_lines:
            return target_lines

        try:
            last_line = int(self.edit_text.index('end-1c').split('.')[0])
        except Exception:
            last_line = end_line

        for line_no in range(min(end_line + 1, last_line), last_line + 1):
            line_text = self.edit_text.get(f'{line_no}.0', f'{line_no}.0 lineend')
            if self._line_has_meaningful_text(line_text):
                self._write_list_debug_log(
                    'resolve_targets_forward_hit',
                    start_line=start_line,
                    end_line=end_line,
                    target_line=line_no,
                    text=line_text,
                )
                return [line_no]

        for line_no in range(max(start_line - 1, 1), 0, -1):
            line_text = self.edit_text.get(f'{line_no}.0', f'{line_no}.0 lineend')
            if self._line_has_meaningful_text(line_text):
                self._write_list_debug_log(
                    'resolve_targets_backward_hit',
                    start_line=start_line,
                    end_line=end_line,
                    target_line=line_no,
                    text=line_text,
                )
                return [line_no]

        self._write_list_debug_log(
            'resolve_targets_fallback',
            start_line=start_line,
            end_line=end_line,
            fallback_line=start_line,
        )
        return [start_line]

    def _collapse_blank_lines_before_target(self, start_line, target_line):
        if target_line <= start_line:
            self._write_list_debug_log(
                'collapse_blank_lines_skip',
                start_line=start_line,
                target_line=target_line,
                reason='target_not_after_start',
            )
            return target_line
        blank_lines = []
        for line_no in range(start_line, target_line):
            line_text = self.edit_text.get(f'{line_no}.0', f'{line_no}.0 lineend')
            if self._line_has_meaningful_text(line_text):
                self._write_list_debug_log(
                    'collapse_blank_lines_abort',
                    start_line=start_line,
                    target_line=target_line,
                    blocking_line=line_no,
                    blocking_text=line_text,
                )
                return target_line
            blank_lines.append({'line_no': line_no, 'text': line_text})
        self._write_list_debug_log(
            'collapse_blank_lines_delete',
            start_line=start_line,
            target_line=target_line,
            blank_lines=blank_lines,
        )
        self.edit_text.delete(f'{start_line}.0', f'{target_line}.0')
        self._write_list_debug_log(
            'collapse_blank_lines_deleted',
            resulting_line=start_line,
            resulting_text=self._get_line_text_for_debug(start_line),
        )
        return start_line

    def _remove_leading_paragraph_indent(self, line_no):
        line_start = f'{line_no}.0'
        line_end = f'{line_no}.0 lineend'
        line_text = self.edit_text.get(line_start, line_end)
        removed = ''
        removed_text = ''
        removed_from = 'none'

        def match_indent(start_col):
            segment = (line_text or '')[start_col:]
            if segment.startswith(self.PARAGRAPH_INDENT):
                return start_col, self.PARAGRAPH_INDENT, 'paragraph_indent'
            if segment.startswith('  '):
                return start_col, '  ', 'double_space'
            if segment.startswith('\t'):
                return start_col, '\t', 'tab'
            return None, '', ''

        start_col, removed_text, removed = match_indent(0)

        if removed_text:
            removed_from = 'line_start'
        else:
            marker_match = self._match_bullet_marker_token(line_text) or self._match_numbering_marker_token(line_text)
            if marker_match:
                marker_end = len(marker_match.group(0))
                for offset in (marker_end, marker_end + 1):
                    if offset > len(line_text):
                        continue
                    if offset == marker_end + 1 and line_text[marker_end:marker_end + 1] != ' ':
                        continue
                    start_col, removed_text, removed = match_indent(offset)
                    if removed_text:
                        removed_from = 'after_list_prefix'
                        break

        if removed_text:
            self.edit_text.delete(
                f'{line_no}.{start_col}',
                f'{line_no}.{start_col + len(removed_text)}',
            )
        self._write_list_debug_log(
            'remove_leading_paragraph_indent',
            line_no=line_no,
            removed=removed or 'none',
            removed_text=removed_text,
            removed_from=removed_from,
            before_text=line_text,
            after_text=self._get_line_text_for_debug(line_no),
        )
        return removed_text

    def _prepare_list_target_line(self, start_line, target_line):
        self._write_list_debug_log(
            'prepare_target_begin',
            start_line=start_line,
            target_line=target_line,
            target_text=self._get_line_text_for_debug(target_line),
        )
        resolved_line = self._collapse_blank_lines_before_target(start_line, target_line)
        indent_text = self._remove_leading_paragraph_indent(resolved_line)
        self._remove_attached_bullet_prefix(resolved_line)
        self._remove_attached_numbering_prefix(resolved_line)
        self._remove_existing_bullet_prefix(resolved_line)
        self._remove_existing_numbering_prefix(resolved_line)
        self._write_list_debug_log(
            'prepare_target_end',
            start_line=start_line,
            target_line=target_line,
            resolved_line=resolved_line,
            preserved_indent=indent_text,
            resolved_text=self._get_line_text_for_debug(resolved_line),
        )
        return resolved_line, f'{resolved_line}.0', indent_text

    def _to_alpha_sequence(self, number, uppercase=False):
        result = []
        value = max(1, int(number))
        while value > 0:
            value -= 1
            result.append(chr((value % 26) + (65 if uppercase else 97)))
            value //= 26
        return ''.join(reversed(result))

    def _to_roman_sequence(self, number, uppercase=False):
        value = max(1, int(number))
        numerals = (
            (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
            (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
            (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'),
        )
        result = []
        for arabic, roman in numerals:
            while value >= arabic:
                result.append(roman)
                value -= arabic
        text = ''.join(result)
        return text if uppercase else text.lower()

    def _to_chinese_numeral(self, number):
        value = max(1, int(number))
        digits = '零一二三四五六七八九'
        if value < 10:
            return digits[value]
        if value == 10:
            return '十'
        if value < 20:
            return f'十{digits[value % 10]}'
        if value < 100:
            tens, ones = divmod(value, 10)
            return f'{digits[tens]}十{digits[ones] if ones else ""}'
        return str(value)

    def _to_circled_digit(self, number):
        value = max(1, int(number))
        if 1 <= value <= 20:
            return chr(9311 + value)
        return str(value)

    def _to_greek_sequence(self, number):
        value = max(1, int(number))
        letters = self.LOWER_GREEK_LETTERS
        if value <= len(letters):
            return letters[value - 1]
        quotient, remainder = divmod(value - 1, len(letters))
        return f'{letters[quotient - 1]}{letters[remainder]}'

    def _format_numbering_prefix(self, style_key, number, separator=' '):
        value = max(1, int(number))
        if style_key == 'decimal':
            return f'{value}.{separator}'
        if style_key == 'lower_alpha':
            return f'{self._to_alpha_sequence(value)}.{separator}'
        if style_key == 'lower_roman':
            return f'{self._to_roman_sequence(value)}.{separator}'
        if style_key == 'upper_alpha':
            return f'{self._to_alpha_sequence(value, uppercase=True)}.{separator}'
        if style_key == 'upper_roman':
            return f'{self._to_roman_sequence(value, uppercase=True)}.{separator}'
        if style_key == 'cn_comma':
            return f'{self._to_chinese_numeral(value)}、'
        if style_key == 'cn_paren':
            return f'（{self._to_chinese_numeral(value)}）'
        if style_key == 'circled_digit':
            return f'{self._to_circled_digit(value)}{separator}'
        if style_key == 'lower_greek':
            return f'{self._to_greek_sequence(value)}.{separator}'
        return f'{value}.{separator}'

    def _line_has_supported_list_prefix(self, text):
        return bool(re.match(
            r'^(?:'
            r'[-*•○●■▼▶]\s+'
            r'|[0-9]+\.\s+'
            r'|[a-zA-Z]+\.\s+'
            r'|[ivxlcdmIVXLCDM]+\.\s+'
            r'|[α-ω]+\.\s+'
            r'|[一二三四五六七八九十百]+、'
            r'|（[一二三四五六七八九十百]+）'
            r'|[①-⑳]\s*'
            r')',
            text or '',
        ))

    def _remove_existing_numbering_prefix(self, line_no):
        line_start = f'{line_no}.0'
        line_end = f'{line_no}.0 lineend'
        line_text = self.edit_text.get(line_start, line_end)
        match = re.match(
            r'^(\s*)((?:'
            r'[0-9]+\.\s+'
            r'|[a-zA-Z]+\.\s+'
            r'|[ivxlcdmIVXLCDM]+\.\s+'
            r'|[α-ω]+\.\s+'
            r'|[一二三四五六七八九十百]+、'
            r'|（[一二三四五六七八九十百]+）'
            r'|[①-⑳]\s*'
            r'))',
            line_text,
        )
        if not match:
            return line_start
        prefix_start = f'{line_no}.{len(match.group(1))}'
        prefix_end = f'{line_no}.{len(match.group(0))}'
        self.edit_text.delete(prefix_start, prefix_end)
        self._write_list_debug_log(
            'remove_existing_numbering_prefix',
            line_no=line_no,
            removed_prefix=match.group(0),
            before_text=line_text,
            after_text=self._get_line_text_for_debug(line_no),
        )
        return prefix_start

    def _apply_bullets_to_selected_lines(self, symbol):
        start_line, end_line = self._get_selected_line_range()
        self._log_list_debug_selection_context(
            'bullet',
            symbol=symbol,
            start_line=start_line,
            end_line=end_line,
        )
        self._log_list_debug_line_window('bullet', start_line, end_line)
        target_lines = self._resolve_list_target_lines(start_line, end_line)
        self._write_list_debug_log(
            'apply_bullets_targets',
            symbol=symbol,
            start_line=start_line,
            end_line=end_line,
            target_lines=target_lines,
        )
        self.edit_text.edit_separator()
        for line_no in target_lines:
            self._write_list_debug_log(
                'apply_bullets_before_prepare',
                symbol=symbol,
                requested_line=line_no,
                requested_text=self._get_line_text_for_debug(line_no),
            )
            _resolved_line, insert_pos, indent_text = self._prepare_list_target_line(start_line, line_no)
            separator = '' if indent_text else self._list_marker_separator_for_line(_resolved_line)
            self._write_list_debug_log(
                'apply_bullets_before_insert',
                symbol=symbol,
                requested_line=line_no,
                resolved_line=_resolved_line,
                indent_text=indent_text,
                separator=separator,
                insert_pos=insert_pos,
                line_text=self._get_line_text_for_debug(_resolved_line),
            )
            self.edit_text.insert(insert_pos, f'{symbol}{separator}{indent_text}')
            self._write_list_debug_log(
                'apply_bullets_after_insert',
                symbol=symbol,
                resolved_line=_resolved_line,
                indent_text=indent_text,
                separator=separator,
                insert_pos=insert_pos,
                line_text=self._get_line_text_for_debug(_resolved_line),
            )
        self.edit_text.edit_separator()
        self._sync_editor_state()
        self.edit_text.focus_set()

    def _apply_numbering_to_selected_lines(self, style_key, capture_selection=True):
        start_line, end_line = self._get_selected_line_range()
        self._log_list_debug_selection_context(
            'numbering',
            style_key=style_key,
            capture_selection=capture_selection,
            start_line=start_line,
            end_line=end_line,
        )
        self._log_list_debug_line_window('numbering', start_line, end_line)
        target_lines = self._resolve_list_target_lines(start_line, end_line)
        self._write_list_debug_log(
            'apply_numbering_targets',
            style_key=style_key,
            capture_selection=capture_selection,
            start_line=start_line,
            end_line=end_line,
            target_lines=target_lines,
        )
        self.edit_text.edit_separator()
        for offset, line_no in enumerate(target_lines, start=1):
            raw_prefix = self._format_numbering_prefix(style_key, offset)
            self._write_list_debug_log(
                'apply_numbering_before_prepare',
                style_key=style_key,
                requested_line=line_no,
                sequence=offset,
                prefix=raw_prefix,
                requested_text=self._get_line_text_for_debug(line_no),
            )
            _resolved_line, insert_pos, indent_text = self._prepare_list_target_line(start_line, line_no)
            separator = '' if indent_text else self._list_marker_separator_for_line(_resolved_line)
            prefix = self._format_numbering_prefix(style_key, offset, separator=separator)
            self._write_list_debug_log(
                'apply_numbering_before_insert',
                style_key=style_key,
                requested_line=line_no,
                resolved_line=_resolved_line,
                sequence=offset,
                prefix=prefix,
                indent_text=indent_text,
                separator=separator,
                insert_pos=insert_pos,
                line_text=self._get_line_text_for_debug(_resolved_line),
            )
            self.edit_text.insert(insert_pos, f'{prefix}{indent_text}')
            self._write_list_debug_log(
                'apply_numbering_after_insert',
                style_key=style_key,
                resolved_line=_resolved_line,
                sequence=offset,
                prefix=prefix,
                indent_text=indent_text,
                separator=separator,
                insert_pos=insert_pos,
                line_text=self._get_line_text_for_debug(_resolved_line),
            )
        self.edit_text.edit_separator()
        self._sync_editor_state(capture_selection=capture_selection)
        self.edit_text.focus_set()

    def _indent_selected_paragraphs(self):
        start_line, end_line = self._get_selected_line_range()
        self.edit_text.edit_separator()
        for line_no in range(start_line, end_line + 1):
            line_start = f'{line_no}.0'
            self.edit_text.insert(line_start, self.PARAGRAPH_INDENT)
        self.edit_text.edit_separator()
        self._sync_editor_state()
        self.edit_text.focus_set()

    def _insert_citation_template(self):
        insert_index = self.edit_text.index(tk.INSERT)
        self.edit_text.insert(tk.INSERT, '[]')
        self.edit_text.mark_set(tk.INSERT, f'{insert_index}+1c')
        self.edit_text.edit_separator()
        self._sync_editor_state(capture_selection=False)
        self.edit_text.focus_set()

    def _open_find_dialog(self):
        if self._find_window is not None and self._find_window.winfo_exists():
            self._find_window.deiconify()
            self._find_window.lift()
            self._find_window.focus_set()
            return

        self._find_query_var = tk.StringVar(value='')
        self._replace_query_var = tk.StringVar(value='')
        window = tk.Toplevel(self.frame)
        window.title('查找与替换')
        window.transient(self.frame.winfo_toplevel())
        window.resizable(False, False)
        window.configure(bg=COLORS['card_bg'])
        self._find_window = window

        shell = tk.Frame(window, bg=COLORS['card_bg'], padx=12, pady=12)
        shell.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            shell,
            text='查找内容',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        entry = tk.Entry(
            shell,
            textvariable=self._find_query_var,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
            width=28,
        )
        entry.pack(fill=tk.X, pady=(6, 10), ipady=4)
        entry.bind('<Return>', lambda _event: self._find_next())

        tk.Label(
            shell,
            text='替换为',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        replace_entry = tk.Entry(
            shell,
            textvariable=self._replace_query_var,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
            width=28,
        )
        replace_entry.pack(fill=tk.X, pady=(6, 10), ipady=4)
        replace_entry.bind('<Return>', lambda _event: self._replace_current())

        button_row = tk.Frame(shell, bg=COLORS['card_bg'])
        button_row.pack(fill=tk.X)
        ModernButton(button_row, '上一个', style='ghost', command=self._find_previous, padx=10, pady=6, font=FONTS['small']).pack(side=tk.LEFT)
        ModernButton(button_row, '下一个', style='ghost', command=self._find_next, padx=10, pady=6, font=FONTS['small']).pack(side=tk.LEFT, padx=(6, 0))
        ModernButton(button_row, '替换', style='ghost', command=self._replace_current, padx=10, pady=6, font=FONTS['small']).pack(side=tk.LEFT, padx=(6, 0))
        ModernButton(button_row, '全部替换', style='ghost', command=self._replace_all, padx=10, pady=6, font=FONTS['small']).pack(side=tk.LEFT, padx=(6, 0))
        ModernButton(button_row, '关闭', style='secondary', command=self._close_find_dialog, padx=10, pady=6, font=FONTS['small']).pack(side=tk.RIGHT)

        window.protocol('WM_DELETE_WINDOW', self._close_find_dialog)
        entry.focus_set()
        entry.select_range(0, tk.END)

    def _close_find_dialog(self):
        if self._find_window is not None and self._find_window.winfo_exists():
            self._find_window.destroy()
        self._find_window = None
        self._find_query_var = None
        self._replace_query_var = None
        self.edit_text.tag_remove('find_match', '1.0', tk.END)

    def _find_next(self):
        self._find_text(backwards=False)

    def _find_previous(self):
        self._find_text(backwards=True)

    def _find_text(self, backwards=False):
        if self._find_query_var is None:
            return
        needle = self._find_query_var.get().strip()
        if not needle:
            self.set_status('请输入要查找的内容', COLORS['warning'])
            return

        self.edit_text.tag_remove('find_match', '1.0', tk.END)
        start = self.edit_text.index(tk.INSERT)
        active_start, active_end = self._get_active_find_match()
        if backwards:
            search_from = self.edit_text.index(f'{active_start} -1c') if active_start else start
            match_index = self.edit_text.search(needle, search_from, stopindex='1.0', backwards=True, nocase=True)
            if not match_index:
                match_index = self.edit_text.search(needle, tk.END, stopindex='1.0', backwards=True, nocase=True)
        else:
            search_from = active_end or start
            match_index = self.edit_text.search(needle, search_from, stopindex=tk.END, nocase=True)
            if not match_index:
                match_index = self.edit_text.search(needle, '1.0', stopindex=tk.END, nocase=True)

        if not match_index:
            self.set_status('未找到匹配内容', COLORS['warning'])
            return

        match_end = f'{match_index}+{len(needle)}c'
        self.edit_text.tag_add('find_match', match_index, match_end)
        self.edit_text.tag_remove(tk.SEL, '1.0', tk.END)
        self.edit_text.tag_add(tk.SEL, match_index, match_end)
        self.edit_text.mark_set(tk.INSERT, match_end)
        self.edit_text.see(match_index)
        self.edit_text.focus_set()

    def _get_active_find_match(self):
        ranges = self.edit_text.tag_ranges('find_match')
        if len(ranges) == 2:
            return self.edit_text.index(ranges[0]), self.edit_text.index(ranges[1])
        return None, None

    def _replace_current(self):
        if self._find_query_var is None or self._replace_query_var is None:
            return
        needle = self._find_query_var.get().strip()
        if not needle:
            self.set_status('请输入要查找的内容', COLORS['warning'])
            return

        start, end = self._get_active_find_match()
        if not start or not end:
            self._find_next()
            start, end = self._get_active_find_match()
            if not start or not end:
                return

        current_text = self.edit_text.get(start, end)
        if current_text.lower() != needle.lower():
            self._find_next()
            start, end = self._get_active_find_match()
            if not start or not end:
                return

        replace_text = self._replace_query_var.get()
        self.edit_text.edit_separator()
        new_end = self._replace_range_text_preserving_formats(start, end, replace_text)
        self.edit_text.tag_remove('find_match', '1.0', tk.END)
        if replace_text:
            self.edit_text.tag_add('find_match', start, new_end)
        self.edit_text.mark_set(tk.INSERT, new_end if replace_text else start)
        self.edit_text.edit_separator()
        self._sync_editor_state(capture_selection=False)
        self.edit_text.focus_set()
        self.set_status('已替换当前匹配内容')

    def _replace_all(self):
        if self._find_query_var is None or self._replace_query_var is None:
            return
        needle = self._find_query_var.get().strip()
        if not needle:
            self.set_status('请输入要查找的内容', COLORS['warning'])
            return

        replace_text = self._replace_query_var.get()
        count = 0
        start = '1.0'
        self.edit_text.tag_remove('find_match', '1.0', tk.END)
        self.edit_text.edit_separator()
        while True:
            match_index = self.edit_text.search(needle, start, stopindex=tk.END, nocase=True)
            if not match_index:
                break
            match_end = f'{match_index}+{len(needle)}c'
            new_end = self._replace_range_text_preserving_formats(match_index, match_end, replace_text)
            start = new_end if replace_text else match_index
            count += 1
        self.edit_text.edit_separator()
        self._sync_editor_state(capture_selection=False)
        self.edit_text.focus_set()
        if count:
            self.set_status(f'已替换 {count} 处内容')
        else:
            self.set_status('未找到可替换的内容', COLORS['warning'])

    def _update_advice(self, total, cn, en, chapter_total, chapter_cn):
        advice = []
        if chapter_total == 0:
            advice.append('当前章节还没有内容，可以开始撰写。')
        elif chapter_total < 100:
            advice.append('当前章节内容较少，建议继续补充。')
        elif chapter_total < 300:
            advice.append('当前章节篇幅偏短，可再补充论述。')
        if chapter_cn > 0 and en > 0 and en / max(cn + en, 1) > 0.3:
            advice.append('英文占比较高，注意中英文表达平衡。')
        if total >= 1200 and chapter_total > 0 and chapter_total / max(total, 1) < 0.08:
            advice.append('当前章节占全文比例偏低，可适当扩展。')
        if chapter_cn >= 800:
            advice.append('当前章节篇幅较长，建议关注层次与分段。')
        if not advice:
            advice.append('当前章节结构良好，可以继续完善细节。')
        self.advice_label.configure(text='\n'.join(advice))

    def _touch_context_revision(self):
        self._context_revision += 1

    def _capture_selection_snapshot(self):
        try:
            ranges = self.edit_text.tag_ranges(tk.SEL)
        except tk.TclError:
            self._editor_selection_range = None
            return

        if len(ranges) != 2:
            self._editor_selection_range = None
            return

        start_index = self.edit_text.index(ranges[0])
        end_index = self.edit_text.index(ranges[1])
        selected_text = self._normalize_editor_block_text(self.edit_text.get(ranges[0], ranges[1]))
        if not selected_text.strip():
            self._editor_selection_range = None
            return

        self._editor_selection_range = {
            'start': start_index,
            'end': end_index,
            'section': self.section_entry.get().strip(),
            'context_revision': self._context_revision,
        }
        self._selection_snapshot = {
            'text': selected_text,
            'section': self.section_entry.get().strip(),
            'context_revision': self._context_revision,
            'source': 'paper_write_selection',
            'paper_title': self.topic_entry.get().strip(),
        }

    def _store_current_editor_content(self):
        title = self._editor_section_source or self.section_entry.get().strip()
        if not title:
            return
        if title not in self._sections:
            return
        blocks = self._capture_editor_blocks()
        self._set_section_blocks(title, blocks)
        self._section_formats[title] = self._serialize_editor_format_spans()

    def export_polish_context(self):
        current_section = self.section_entry.get().strip()
        current_content = self._get_current_editor_text()
        outline_text = self.outline_text.get('1.0', tk.END).strip()
        return {
            'paper_title': self.topic_entry.get().strip(),
            'current_section': current_section,
            'current_content': current_content,
            'outline_text': outline_text,
            'context_revision': self._context_revision,
            'level_font_styles': {k: dict(v) for k, v in self._level_font_styles.items()},
        }

    def export_selection_snapshot(self):
        self._capture_selection_snapshot()
        snapshot = self._selection_snapshot or {}
        if snapshot.get('context_revision') != self._context_revision:
            return None
        result = dict(snapshot)
        result['paper_title'] = self.topic_entry.get().strip()
        result['level_font_styles'] = {k: dict(v) for k, v in self._level_font_styles.items()}
        return result

    def _get_outline_section_body(self, title):
        target_title = (title or '').strip()
        if not target_title:
            return ''
        self._store_current_editor_content()
        if self._editor_section_source == target_title or self.section_entry.get().strip() == target_title:
            return self._get_current_editor_text()
        return self._normalize_section_body(self._sections.get(target_title, ''))

    def _build_outline_send_payload(self, title, page_id):
        section_title = (title or '').strip()
        body_text = self._get_outline_section_body(section_title)
        if not body_text:
            return None
        return {
            'text': body_text,
            'paper_title': self.topic_entry.get().strip(),
            'section': section_title,
            'section_level': self._section_levels.get(section_title, self._infer_outline_level(section_title)),
            'context_revision': self._context_revision,
            'source_kind': 'paper_section',
            'source_desc': f'来自论文写作页面主动发送 / {section_title}',
            'target_page_id': page_id,
            'level_font_styles': {k: dict(v) for k, v in self._level_font_styles.items()},
        }

    def _send_outline_section_to_page(self, title, page_id, page_label):
        payload = self._build_outline_send_payload(title, page_id)
        if not payload:
            messagebox.showwarning('提示', '当前标题下暂无可发送的正文内容。', parent=self.frame)
            return
        if not self.app_bridge:
            messagebox.showwarning('提示', '当前版本未连接章节内容发送桥接。', parent=self.frame)
            return

        outcome = self.app_bridge.send_paper_write_content(page_id, payload)
        if not outcome or not outcome.get('ok'):
            messagebox.showwarning('发送失败', (outcome or {}).get('message', '无法发送到目标页面'), parent=self.frame)
            return

        self.set_status(f'已将“{payload["section"]}”的正文发送到{page_label}')
        if messagebox.askyesno('发送成功', f'已将当前章节正文发送到“{page_label}”。\n\n是否立即跳转到该页面？', parent=self.frame):
            if callable(self.navigate_page):
                self.navigate_page(page_id)
            elif self.app_bridge:
                self.app_bridge.navigate_to_page(page_id)

    def apply_external_result(self, result, target_mode='smart', write_mode='replace', section_hint='', task_type=''):
        result = self._normalize_editor_block_text(result)
        if not result.strip():
            return {'ok': False, 'message': '没有可写回的内容'}

        resolved_target = target_mode
        if resolved_target == 'smart':
            resolved_target = 'outline' if task_type == '论文大纲' else 'body'

        if resolved_target == 'outline':
            existing_outline = self.outline_text.get('1.0', tk.END).strip()
            if write_mode == 'append' and existing_outline:
                merged_outline = existing_outline + '\n\n' + result
            else:
                merged_outline = result
            self._parse_and_show_outline(merged_outline)
            self._touch_context_revision()
            self._schedule_workspace_state_save()
            return {
                'ok': True,
                'target': 'outline',
                'message': '已写回论文大纲',
                'section': '',
            }

        section_name = (section_hint or '').strip() or self.section_entry.get().strip()
        existing_blocks = self._get_current_editor_blocks()
        existing_content = blocks_to_plain_text(existing_blocks)
        existing_formats = []
        current_source = self._editor_section_source or self.section_entry.get().strip()
        if current_source and current_source == section_name:
            existing_formats = self._serialize_editor_format_spans()
        elif section_name:
            existing_formats = self._copy_section_formats(section_name)
        result_blocks = self._blocks_from_section_text(result)
        if write_mode == 'append' and existing_blocks:
            new_blocks = self._normalize_section_blocks(existing_blocks + result_blocks)
        else:
            new_blocks = result_blocks or existing_blocks
        new_content = blocks_to_plain_text(new_blocks)
        new_formats = self._preserve_existing_formats(
            section_name,
            existing_content,
            new_content,
            source_spans=existing_formats,
        ) if section_name and not any(block.get('type') == 'table' for block in new_blocks) else []

        if section_name:
            self.section_entry.delete(0, tk.END)
            self.section_entry.insert(0, section_name)
        self._set_editor_content(new_content, new_formats, blocks=new_blocks)
        self._editor_section_source = section_name or ''
        self._update_stats()
        self._touch_context_revision()
        self.frame.after_idle(self._capture_selection_snapshot)
        self._schedule_workspace_state_save()

        if section_name:
            self._set_section_blocks(section_name, new_blocks)
            self._section_formats[section_name] = new_formats
            if section_name not in self._section_order:
                self._section_order.append(section_name)
                self._section_formats.setdefault(section_name, [])
                self._section_levels[section_name] = self._infer_outline_level(section_name)
                self._section_parent[section_name] = self._find_parent_for_insert(len(self._section_order) - 1, self._section_levels[section_name])
                self._rebuild_section_children()
                self._sync_outline_text_from_sections()
                self._refresh_outline_list()

        return {
            'ok': True,
            'target': 'body',
            'message': f'已写回当前章节：{section_name or "未命名章节"}',
            'section': section_name,
        }

    # ──────────────────────────────────────────────
    # 工具栏功能
    # ──────────────────────────────────────────────

    def _gen_outline(self):
        topic = self.topic_entry.get().strip()
        if not topic:
            messagebox.showwarning('提示', '请输入论文标题', parent=self.frame)
            return
        if not self._ensure_prompt_ready('paper_write.outline'):
            return

        subject = self.subject_entry.get().strip()
        style = self.style_var.get()
        ref = self.ref_var.get()

        def on_start():
            self.outline_text.delete('1.0', tk.END)
            self.outline_text.insert(tk.END, '生成中，请稍候...')

        def on_success(result):
            prepared = self._prepare_outline_generation_result(result)
            display_text = prepared['display_text']
            self.outline_text.delete('1.0', tk.END)
            if not display_text:
                self.outline_text.insert(tk.END, '错误：模型未返回可显示内容')
                self._clear_outline_structure_view()
                self._write_outline_generation_log(
                    'empty_result',
                    level='WARN',
                    topic=topic,
                )
                self.set_status('生成失败：模型未返回可显示内容', COLORS['error'])
                return

            self.outline_text.insert(tk.END, display_text)
            if prepared['has_structure']:
                self._parse_and_show_outline(display_text, parsed=prepared['parsed'])
                self.set_status('大纲生成完成')
                self._write_outline_generation_log(
                    'render_structured',
                    topic=topic,
                    heading_count=len(prepared['parsed'].get('order', [])),
                    result_len=len(display_text),
                )
            else:
                self._show_unstructured_outline_result(display_text)
                self._write_outline_generation_log(
                    'parse_fallback',
                    level='WARN',
                    topic=topic,
                    result_len=len(display_text),
                )
                self.set_status('已生成文本，但格式无法解析，已按原始结果显示', COLORS['warning'])

            self._schedule_workspace_state_save()
            self._add_history_version(
                '生成大纲',
                topic,
                display_text,
                extra={'paper_title': topic},
            )

        def on_error(exc):
            self.outline_text.delete('1.0', tk.END)
            self.outline_text.insert(tk.END, f'错误：{exc}')
            self.set_status('生成失败', COLORS['error'])

        self.task_runner.run(
            work=lambda: self.writer.generate_outline(topic, style, ref, subject=subject),
            on_success=on_success,
            on_error=on_error,
            on_start=on_start,
            loading_text='正在生成论文大纲...',
            status_text='正在生成大纲...',
            status_color=COLORS['warning'],
        )

    @staticmethod
    def _normalize_outline_generation_text(text):
        return str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()

    @classmethod
    def _empty_outline_structure(cls):
        return {
            'sections': {},
            'order': [],
            'levels': {},
            'parents': {},
        }

    @classmethod
    def _prepare_outline_generation_result(cls, text):
        display_text = cls._normalize_outline_generation_text(text)
        parsed = cls._build_outline_structure(display_text) if display_text else cls._empty_outline_structure()
        has_structure = bool(parsed.get('order'))
        return {
            'display_text': display_text,
            'parsed': parsed,
            'has_structure': has_structure,
            'preserve_raw_text': bool(display_text) and not has_structure,
        }

    def _clear_outline_structure_view(self):
        self._sections = {}
        self._section_blocks = {}
        self._section_formats = {}
        self._section_order = []
        self._section_levels = {}
        self._section_parent = {}
        self._section_children = {}
        self._collapsed_sections = set()
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            self._outline_selected.set('')
        self._refresh_outline_list()
        self._clear_editor_block_widgets()
        self.edit_text.delete('1.0', tk.END)
        self.section_entry.delete(0, tk.END)
        self._editor_section_source = ''
        self._touch_context_revision()

    def _show_unstructured_outline_result(self, text, title='未解析大纲'):
        fallback_title = str(title or '').strip() or '未解析大纲'
        raw_text = str(text or '').strip()
        self._sections = {fallback_title: raw_text}
        self._section_blocks = self._build_section_blocks_from_sections(self._sections)
        self._section_formats = {fallback_title: []}
        self._section_order = [fallback_title]
        self._section_levels = {fallback_title: 1}
        self._section_parent = {fallback_title: ''}
        self._collapsed_sections = set()
        self._rebuild_section_children()
        self.outline_text.delete('1.0', tk.END)
        if raw_text:
            self.outline_text.insert('1.0', raw_text)
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            self._outline_selected.set('')
        self._refresh_outline_list()
        self._editor_section_source = ''
        self.section_entry.delete(0, tk.END)
        self._select_section(fallback_title, touch_context=False)
        self._touch_context_revision()

    def _write_outline_generation_log(self, event, level='INFO', **fields):
        if not self.app_bridge or not hasattr(self.app_bridge, 'write_app_log'):
            return
        parts = [f'[paper_write_outline] event={event}']
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f'{key}={value}')
        self.app_bridge.write_app_log(' '.join(parts), level=level)

    def _add_history_version(self, operation, input_text, output_text, extra=None):
        self.history.add(
            operation,
            input_text,
            output_text,
            MODULE_PAPER_WRITE,
            extra=extra,
            page_state_id=self.PAGE_STATE_ID,
            workspace_state=self.capture_workspace_state_snapshot(save_to_disk=False),
        )

    @staticmethod
    def _normalize_import_title_text(text):
        value = re.sub(r'\s+', ' ', str(text or '').strip())
        if not value:
            return '', False

        stripped_by_prefix = False
        prefix_patterns = (
            r'^(?:论文标题|论文题目|论文名称)\s*[:：]?\s*(.+)$',
            r'^(?:标题|题目|主题)\s*[:：]?\s*(.+)$',
            r'^(?:中文标题|中文题目|英文标题|英文题目)\s*[:：]?\s*(.+)$',
            r'^(?:title)\s*[:：]?\s*(.+)$',
        )
        for pattern in prefix_patterns:
            match = re.match(pattern, value, re.IGNORECASE)
            if not match:
                continue
            candidate = re.sub(r'\s+', ' ', match.group(1).strip())
            if candidate:
                value = candidate
                stripped_by_prefix = True
                break

        return value.strip(' \t\r\n-—_:：'), stripped_by_prefix

    def _evaluate_import_title_candidate(self, text, *, source='body'):
        normalized, stripped_by_prefix = self._normalize_import_title_text(text)
        if not normalized:
            return None

        plain = self._heading_plain_text(normalized)
        if not plain:
            return None
        if self._parse_outline_heading(normalized):
            return None

        exact_blacklist = {
            '摘要', '中文摘要', 'abstract', '英文摘要', '摘要与关键词', 'abstract and keywords',
            '关键词', '关键字', '中文关键词', '中文关键字', 'keywords', '英文关键词', '英文关键字',
            '参考文献', 'references', 'bibliography',
            '附录', 'appendix',
            '目录', 'contents', 'table of contents',
            '致谢', 'acknowledgements', 'acknowledgments',
            '本科毕业论文', '毕业论文', '学位论文', '论文',
        }
        if plain in exact_blacklist:
            return None

        if len(normalized) < 4 or len(normalized) > 80:
            return None
        if re.search(r'[\\/]', normalized):
            return None

        score = {
            'body': 42,
            'current': 30,
            'filename': 12,
        }.get(source, 0)

        length = len(normalized)
        if 8 <= length <= 36:
            score += 18
        elif 6 <= length <= 48:
            score += 12
        else:
            score += 4

        if stripped_by_prefix:
            score += 18
        if re.search(r'[\u4e00-\u9fffA-Za-z]', normalized):
            score += 8

        punctuation_count = len(re.findall(r'[，。！？：；,.!?;:_\-—/]', normalized))
        if punctuation_count <= 2:
            score += 6
        else:
            score -= min(punctuation_count * 2, 14)

        digit_count = len(re.findall(r'\d', normalized))
        if digit_count and digit_count / max(length, 1) > 0.35:
            score -= 20
        if re.search(r'\.[A-Za-z0-9]{1,5}$', normalized):
            score -= 24
        if re.search(r'[_/\\]', normalized):
            score -= 16

        meta_prefixes = (
            '学号', '作者', '姓名', '学生', '班级', '专业', '院系',
            '指导教师', '指导老师', '完成时间', '完成日期', '日期',
            '目录', '摘要', '中文摘要', '英文摘要', '关键词', '关键字', '中文关键词', '中文关键字', '英文关键词', '英文关键字',
            'abstract', 'keywords', 'references', 'bibliography',
            'appendix', 'contents', 'acknowledgements', 'acknowledgments',
        )
        if plain.startswith(meta_prefixes):
            score -= 36
        if re.search(r'(?:^|[\s(（【\[])本科毕业论文(?:[)）】\]]|$)', normalized):
            score -= 30
        if re.search(r'(?:^|[\s(（【\[])学位论文(?:[)）】\]]|$)', normalized):
            score -= 24
        if length <= 20 and normalized.endswith(('大学', '学院', '学校')):
            score -= 30
        if normalized.startswith(('本文', '本研究', '本论文', '为了', '通过', '随着', '针对', '根据', '由于', '这是', '该文', '我们')):
            score -= 28

        return {
            'text': normalized,
            'source': source,
            'score': score,
        }

    def _is_import_title_boundary_line(self, text):
        if self._parse_outline_heading(text):
            return True

        plain = self._heading_plain_text(text)
        return plain in {
            '摘要', '中文摘要', 'abstract', '英文摘要', '摘要与关键词', 'abstract and keywords',
            '关键词', '关键字', '中文关键词', '中文关键字', 'keywords', '英文关键词', '英文关键字',
            '目录', 'contents', 'table of contents',
            '参考文献', 'references', 'bibliography',
            '附录', 'appendix',
            '致谢', 'acknowledgements', 'acknowledgments',
        }

    def _extract_body_title_candidate(self, text):
        lines = [line.strip() for line in str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n') if line.strip()]
        if not lines:
            return None

        search_lines = lines[:24]
        for index, line in enumerate(lines[:40]):
            if self._is_import_title_boundary_line(line):
                if index > 0:
                    search_lines = lines[:min(index, 24)]
                else:
                    search_lines = []
                break

        best_candidate = None
        for line in search_lines:
            candidate = self._evaluate_import_title_candidate(line, source='body')
            if not candidate or candidate['score'] < 46:
                continue
            if best_candidate is None or candidate['score'] > best_candidate['score']:
                best_candidate = candidate
        return best_candidate

    def _extract_import_title_candidate(self, text, path):
        candidate = self._extract_body_title_candidate(text)
        if candidate:
            return candidate

        file_stem = os.path.splitext(os.path.basename(path or ''))[0].strip()
        fallback = self._evaluate_import_title_candidate(file_stem, source='filename')
        if fallback and fallback['score'] >= 24:
            return fallback
        return None

    def _should_replace_import_title(self, current_title, candidate):
        if not candidate:
            return False

        current_text = str(current_title or '').strip()
        if not current_text:
            return True
        if current_text == candidate['text']:
            return False

        current_candidate = self._evaluate_import_title_candidate(current_text, source='current')
        if not current_candidate:
            return True
        if candidate['source'] == 'body':
            return candidate['score'] >= current_candidate['score']
        return candidate['score'] > current_candidate['score']

    def _apply_imported_paper_title(self, text, path):
        candidate = self._extract_import_title_candidate(text, path)
        if not candidate:
            return ''

        source_label = '正文' if candidate['source'] == 'body' else '文件名'
        current_title = self.topic_entry.get().strip()
        if not self._should_replace_import_title(current_title, candidate):
            if current_title and current_title != candidate['text']:
                return f'已识别论文标题候选（{source_label}）：{candidate["text"]}，已保留当前论文标题'
            return ''

        self.topic_entry.delete(0, tk.END)
        self.topic_entry.insert(0, candidate['text'])
        return f'已自动识别论文标题（{source_label}）：{candidate["text"]}'

    def _get_import_recognition_mode(self):
        if not self.config or not hasattr(self.config, 'get_setting'):
            return self.OUTLINE_IMPORT_MODE_LOCAL
        value = str(self.config.get_setting('paper_write_import_recognition_mode', self.OUTLINE_IMPORT_MODE_LOCAL) or '').strip().lower()
        return self.OUTLINE_IMPORT_MODE_AI if value == self.OUTLINE_IMPORT_MODE_AI else self.OUTLINE_IMPORT_MODE_LOCAL

    def _import_file(self):
        path = filedialog.askopenfilename(
            filetypes=[('Word文档', '*.docx')],
            parent=self.frame,
        )
        if not path:
            return
        mode = self._get_import_recognition_mode()
        if mode == self.OUTLINE_IMPORT_MODE_AI and not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return

        def work():
            structured = self.aux.import_docx_blocks(path)
            text = structured.get('text', '')
            blocks = structured.get('blocks', [])
            if mode == self.OUTLINE_IMPORT_MODE_AI:
                parsed = self._build_outline_structure_with_ai(blocks)
                mode_label = 'AI识别'
            else:
                parsed = self._build_outline_structure_from_blocks(blocks)
                mode_label = '本地识别'
            return {'text': text, 'parsed': parsed, 'mode_label': mode_label}

        def on_success(result):
            text = result['text']
            parsed = result['parsed']
            title_feedback = self._apply_imported_paper_title(text, path)
            # 先解析大纲，不把全文直接填入编辑区
            self._parse_and_show_outline(text, parsed=parsed)
            # 清空编辑区，等待用户点击章节
            self._clear_editor_block_widgets()
            self.edit_text.delete('1.0', tk.END)
            self.section_entry.delete(0, tk.END)
            self._editor_section_source = ''
            self._touch_context_revision()
            self._update_stats()
            self._schedule_workspace_state_save()
            if self.config and hasattr(self.config, 'clear_home_last_import_failure'):
                self.config.clear_home_last_import_failure()
                self.config.save()
            mode_label = result.get('mode_label') or '本地识别'
            status_text = f'已导入: {path}（{mode_label}），请点击左侧大纲章节查看内容'
            if title_feedback:
                status_text = f'{status_text}；{title_feedback}'
            self.set_status(status_text)

        def on_error(exc):
            if self.config and hasattr(self.config, 'set_home_last_import_failure'):
                self.config.set_home_last_import_failure('paper_write', os.path.basename(path), str(exc))
                self.config.save()
            messagebox.showerror('导入失败', str(exc), parent=self.frame)

        self.task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            loading_text='正在导入 DOCX...',
            status_text='正在导入 DOCX...',
        )

    def _parse_and_show_outline(self, text, parsed=None):
        """从文本中解析章节标题，填充左侧大纲列表"""
        parsed = parsed if isinstance(parsed, dict) else self._build_outline_structure(text)
        self._sections = dict(parsed['sections'])
        raw_section_blocks = parsed.get('section_blocks', {})
        self._section_blocks = self._normalize_section_blocks_map(raw_section_blocks, sections=self._sections)
        for title, section_text in self._sections.items():
            if title not in self._section_blocks:
                blocks = self._blocks_from_section_text(section_text)
                if blocks:
                    self._section_blocks[title] = blocks
        self._section_formats = {title: [] for title in self._sections}
        self._section_order = list(parsed['order'])
        self._section_levels = dict(parsed['levels'])
        self._section_parent = dict(parsed['parents'])
        self._collapsed_sections = set()
        self._normalize_outline_structure_state(preserve_blocks=True)
        self._rebuild_section_children()

        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._editor_section_source = ''
        self.section_entry.delete(0, tk.END)
        if self._section_order:
            self._select_section(self._section_order[0], touch_context=False)
        else:
            self._clear_editor_block_widgets()
            self.edit_text.delete('1.0', tk.END)
            self._editor_section_source = ''
        self._touch_context_revision()

    def _section_has_structured_table_blocks(self, title, blocks_map=None):
        source = blocks_map if isinstance(blocks_map, dict) else self._section_blocks
        blocks = source.get(title, [])
        return any(isinstance(block, dict) and block.get('type') == 'table' for block in blocks)

    def _apply_normalized_outline_state(self, normalized, preserve_blocks=False):
        old_sections = dict(self._sections)
        old_blocks = self._copy_section_blocks_map()
        old_formats = self._copy_section_format_map() if hasattr(self, '_section_formats') else {}
        self._sections = dict(normalized.get('sections', {}))
        self._section_order = list(normalized.get('order', []))
        self._section_levels = dict(normalized.get('levels', {}))
        self._section_parent = dict(normalized.get('parents', {}))
        aliases = dict(normalized.get('aliases', {}) or {})
        self._section_formats = {}
        self._section_blocks = {}
        for title in self._section_order:
            if old_sections.get(title, None) == self._sections.get(title, None):
                self._section_formats[title] = list(old_formats.get(title, []))
            else:
                self._section_formats[title] = []

            source_titles = [title] + [
                old_title
                for old_title, resolved_title in aliases.items()
                if resolved_title == title
            ]
            selected_blocks = []
            for old_title in source_titles:
                if (
                    old_sections.get(old_title, None) == self._sections.get(title, None)
                    or (preserve_blocks and self._section_has_structured_table_blocks(old_title, old_blocks))
                ):
                    selected_blocks = old_blocks.get(old_title, [])
                    if selected_blocks:
                        break
            if selected_blocks:
                self._section_blocks[title] = deep_copy_blocks(selected_blocks)
                continue
            blocks = self._blocks_from_section_text(self._sections.get(title, ''))
            if blocks:
                self._section_blocks[title] = blocks
        return aliases

    def _normalize_outline_structure_state(self, preserve_blocks=False):
        normalized = self._normalize_outline_structure(
            {
                'sections': self._sections,
                'order': self._section_order,
                'levels': self._section_levels,
                'parents': self._section_parent,
            }
        )
        return self._apply_normalized_outline_state(normalized, preserve_blocks=preserve_blocks)

    def _resolve_normalized_section_title(self, title, aliases=None):
        candidate = str(title or '').strip()
        if not candidate:
            return ''
        if candidate in self._sections:
            return candidate
        if aliases:
            mapped = aliases.get(candidate, '')
            if mapped in self._sections:
                return mapped
        kind = self._classify_outline_special_title(candidate)
        if kind:
            return self._find_section_title_by_kind(kind)
        return ''

    def _normalize_section_body(self, text):
        return self._normalize_outline_section_body(text)

    @classmethod
    def _strip_outline_emphasis(cls, text):
        normalized = str(text or '').strip()
        if not normalized:
            return ''
        while True:
            changed = False
            for marker in cls.OUTLINE_EMPHASIS_MARKERS:
                if normalized.startswith(marker) and normalized.endswith(marker) and len(normalized) > len(marker) * 2:
                    inner = normalized[len(marker):-len(marker)].strip()
                    if inner:
                        normalized = inner
                        changed = True
                        break
            if not changed:
                return normalized

    @classmethod
    def _normalize_special_heading_plain_text(cls, text):
        normalized = re.sub(r'\s+', ' ', str(text or '').strip())
        normalized = normalized.strip('：:').strip()
        return normalized.lower()

    @classmethod
    def _classify_plain_special_heading(cls, text):
        plain = cls._normalize_special_heading_plain_text(text)
        if plain in cls.OUTLINE_CN_ABSTRACT_TITLES:
            return 'cn_abstract'
        if plain in cls.OUTLINE_CN_KEYWORD_TITLES:
            return 'cn_keywords'
        if plain in cls.OUTLINE_EN_ABSTRACT_TITLES:
            return 'en_abstract'
        if plain in cls.OUTLINE_EN_KEYWORD_TITLES:
            return 'en_keywords'
        if plain in cls.OUTLINE_INTRO_TITLES:
            return 'intro'
        if plain in cls.OUTLINE_REFERENCE_TITLES:
            return 'reference'
        if plain in cls.OUTLINE_APPENDIX_TITLES:
            return 'appendix'
        return ''

    @classmethod
    def _classify_outline_special_title(cls, title):
        return cls._classify_plain_special_heading(cls._editable_title_text(title))

    @classmethod
    def _canonical_outline_title(cls, kind, intro_name='引言'):
        mapping = {
            'cn_abstract': '# 中文摘要',
            'en_abstract': '# 英文摘要',
            'intro': f'# {intro_name or "引言"}',
            'reference': '# 参考文献',
        }
        return mapping.get(kind, '')

    @classmethod
    def _build_markdown_outline_title(cls, text, level):
        hashes = '#' * max(1, min(int(level or 1), 6))
        return f'{hashes} {str(text or "").strip()}'.strip()

    @classmethod
    def _merge_outline_section_bodies(cls, current, extra):
        current_text = cls._normalize_outline_section_body(current or '')
        extra_text = cls._normalize_outline_section_body(extra or '')
        if not extra_text:
            return current_text
        if not current_text:
            return extra_text
        if extra_text == current_text or extra_text in current_text:
            return current_text
        if current_text in extra_text:
            return extra_text
        return f'{current_text}\n\n{extra_text}'

    @classmethod
    def _normalize_keyword_content(cls, text):
        normalized = cls._normalize_outline_section_body(text or '')
        normalized = re.sub(
            r'^\s*(?:关键词|关键字|中文关键词|中文关键字|英文关键词|英文关键字|keywords)\s*[:：]\s*',
            '',
            normalized,
            flags=re.IGNORECASE,
        )
        return normalized.strip(' \t\r\n；;，,')

    @classmethod
    def _format_keyword_line(cls, keyword_text, language='cn'):
        normalized = cls._normalize_keyword_content(keyword_text)
        if not normalized:
            return ''
        prefix = 'Keywords: ' if str(language or '').lower().startswith('en') else '关键词：'
        return f'{prefix}{normalized}'

    @classmethod
    def _merge_abstract_keyword_body(cls, abstract_text, keyword_text, language='cn'):
        abstract_body = cls._normalize_outline_section_body(abstract_text or '')
        keyword_line = cls._format_keyword_line(keyword_text, language=language)
        if not keyword_line:
            return abstract_body
        parts = [part for part in (abstract_body, keyword_line) if part]
        return '\n\n'.join(parts).strip()

    def _supports_numeric_reference_linking(self):
        style = ''
        if hasattr(self, 'ref_var') and self.ref_var is not None:
            try:
                style = str(self.ref_var.get() or '').strip()
            except Exception:
                style = ''
        return style in self.NUMERIC_REFERENCE_STYLES

    @classmethod
    def _normalize_reference_entry_text(cls, text):
        normalized = cls._normalize_outline_section_body(text or '')
        normalized = re.sub(r'^\s*(?:\[(\d+)\]|(\d+)[\.、])\s*', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    @classmethod
    def _reference_entry_key(cls, text):
        return cls._normalize_reference_entry_text(text)

    @classmethod
    def _parse_reference_entries(cls, text):
        normalized = str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            return []

        lines = normalized.split('\n')
        entries = []
        current = None
        numbered_found = False
        start_re = re.compile(r'^\s*(?:\[(\d+)\]|(\d+)[\.、])\s*(.*)$')

        def flush_current():
            if not current:
                return
            entry_text = cls._normalize_reference_entry_text('\n'.join(current['parts']))
            if not entry_text:
                return
            entries.append(
                {
                    'number': current['number'],
                    'text': entry_text,
                    'key': cls._reference_entry_key(entry_text),
                }
            )

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current and current['parts'] and current['parts'][-1] != '':
                    current['parts'].append('')
                continue

            match = start_re.match(stripped)
            if match:
                numbered_found = True
                flush_current()
                current = {
                    'number': int(match.group(1) or match.group(2)),
                    'parts': [match.group(3).strip()],
                }
                continue

            if current:
                current['parts'].append(stripped)
                continue

            entry_text = cls._normalize_reference_entry_text(stripped)
            if entry_text:
                entries.append({'number': None, 'text': entry_text, 'key': cls._reference_entry_key(entry_text)})

        flush_current()
        if numbered_found:
            return [entry for entry in entries if entry.get('key')]

        fallback_entries = []
        for block in re.split(r'\n\s*\n', normalized):
            entry_text = cls._normalize_reference_entry_text(block)
            if entry_text:
                fallback_entries.append({'number': None, 'text': entry_text, 'key': cls._reference_entry_key(entry_text)})
        return fallback_entries or [entry for entry in entries if entry.get('key')]

    @classmethod
    def _parse_citation_numbers(cls, content):
        numbers = []
        for part in re.split(r'[,，、]', str(content or '').strip()):
            token = part.strip()
            if not token:
                continue
            range_match = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', token)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                if start <= end:
                    numbers.extend(range(start, end + 1))
                else:
                    numbers.extend(range(end, start + 1))
                continue
            if token.isdigit():
                numbers.append(int(token))
        return numbers

    @classmethod
    def _format_citation_numbers(cls, numbers):
        ordered = sorted(dict.fromkeys(int(number) for number in numbers if int(number) > 0))
        if not ordered:
            return ''
        parts = []
        start = ordered[0]
        prev = ordered[0]
        for number in ordered[1:]:
            if number == prev + 1:
                prev = number
                continue
            parts.append(f'{start}-{prev}' if start != prev else str(start))
            start = prev = number
        parts.append(f'{start}-{prev}' if start != prev else str(start))
        return ','.join(parts)

    @classmethod
    def _collect_citation_reference_keys(cls, text, number_to_entry):
        if not text or not number_to_entry:
            return []

        keys = []
        seen = set()
        for match in re.finditer(r'\[([^\[\]]+)\]', text):
            for number in cls._parse_citation_numbers(match.group(1)):
                entry = number_to_entry.get(number)
                key = entry.get('key', '') if entry else ''
                if not key or key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return keys

    @classmethod
    def _rewrite_citations_with_entry_map(cls, text, number_to_entry):
        if not text or not number_to_entry:
            return text

        def replace(match):
            source_numbers = cls._parse_citation_numbers(match.group(1))
            if not source_numbers:
                return match.group(0)
            target_numbers = []
            for number in source_numbers:
                entry = number_to_entry.get(number)
                target_number = entry.get('new_number') if entry else None
                target_numbers.append(target_number if target_number else number)
            formatted = cls._format_citation_numbers(target_numbers)
            return f'[{formatted}]' if formatted else match.group(0)

        return re.sub(r'\[([^\[\]]+)\]', replace, text)

    @classmethod
    def _build_reference_body_from_entries(cls, entries):
        lines = []
        for index, entry in enumerate(entries, start=1):
            entry_text = cls._normalize_reference_entry_text(entry.get('text', ''))
            if not entry_text:
                continue
            lines.append(f'[{index}] {entry_text}')
        return '\n'.join(lines).strip()

    @classmethod
    def _normalize_intro_child_level(cls, original_level, previous_level=0):
        target_level = 2 if int(original_level or 1) <= 2 else 3
        if previous_level <= 0 and target_level > 2:
            return 2
        if previous_level >= 2 and target_level > previous_level + 1:
            return min(previous_level + 1, 3)
        return max(2, min(target_level, 3))

    @classmethod
    def _is_primary_body_chapter_title(cls, title):
        kind = cls._classify_outline_special_title(title)
        if kind:
            return False
        parsed = cls._analyze_outline_heading(title)
        if not parsed or int(parsed.get('level', 0) or 0) != 1:
            return False
        if parsed.get('style') in {'chapter', 'single_number', 'cn_enum'}:
            return True
        if parsed.get('style') == 'markdown':
            return bool(
                re.match(
                    r'^(?:第[一二三四五六七八九十百千万\d]+(?:章|部分|篇)|\d+(?:[、．.]|\s+)|[一二三四五六七八九十百千万]+[、．.])',
                    parsed.get('body', '').strip(),
                )
            )
        return False

    @classmethod
    def _analyze_outline_heading(cls, line):
        text = cls._strip_outline_emphasis(line)
        bullet_match = cls.OUTLINE_BULLET_PREFIX_RE.match(text)
        if bullet_match:
            text = cls._strip_outline_emphasis(bullet_match.group(1).strip())
        if not text or len(text) > 160:
            return None

        markdown = cls.OUTLINE_MARKDOWN_RE.match(text)
        if markdown:
            hashes = markdown.group(1)
            label_text = markdown.group(2).strip()
            if not label_text:
                return None
            return {
                'title': f'{hashes} {label_text}',
                'level': min(len(hashes), 3),
                'prefix': hashes,
                'body': label_text,
                'style': 'markdown',
            }

        chapter = cls.OUTLINE_CHAPTER_RE.match(text)
        if chapter:
            prefix = chapter.group(1).strip()
            label_text = chapter.group(3).strip()
            if not label_text:
                return None
            kind = chapter.group(2)
            level = 2 if kind == '节' else 1
            return {
                'title': f'{prefix} {label_text}',
                'level': level,
                'prefix': prefix,
                'body': label_text,
                'style': 'chapter',
            }

        decimal = cls.OUTLINE_DECIMAL_RE.match(text)
        if decimal:
            prefix = decimal.group(1).strip().rstrip('.．')
            label_text = decimal.group(2).strip()
            if not prefix or not label_text:
                return None
            level = min(len([item for item in prefix.split('.') if item]), 3)
            return {
                'title': f'{prefix} {label_text}',
                'level': max(1, level),
                'prefix': prefix,
                'body': label_text,
                'style': 'decimal',
            }

        single_number = cls.OUTLINE_SINGLE_NUMBER_RE.match(text)
        if single_number:
            prefix = single_number.group(1).strip()
            separator = single_number.group(2) or ''
            label_text = single_number.group(3).strip()
            if not label_text:
                return None
            display_prefix = f'{prefix}{separator}' if separator else prefix
            return {
                'title': f'{display_prefix} {label_text}',
                'level': 1,
                'prefix': display_prefix,
                'body': label_text,
                'style': 'single_number',
            }

        chinese_enum = cls.OUTLINE_CN_ENUM_RE.match(text)
        if chinese_enum:
            prefix = chinese_enum.group(1).strip()
            label_text = chinese_enum.group(2).strip()
            if not label_text:
                return None
            return {
                'title': f'{prefix} {label_text}',
                'level': 1,
                'prefix': prefix,
                'body': label_text,
                'style': 'cn_enum',
            }

        chinese_paren = cls.OUTLINE_CN_PAREN_RE.match(text)
        if chinese_paren:
            prefix = chinese_paren.group(1).strip()
            label_text = chinese_paren.group(2).strip()
            if not label_text:
                return None
            return {
                'title': f'{prefix} {label_text}',
                'level': 2,
                'prefix': prefix,
                'body': label_text,
                'style': 'cn_paren',
            }

        arabic_paren = cls.OUTLINE_ARABIC_PAREN_RE.match(text)
        if arabic_paren:
            prefix = arabic_paren.group(1).strip()
            label_text = arabic_paren.group(2).strip()
            if not label_text:
                return None
            return {
                'title': f'{prefix} {label_text}',
                'level': 3,
                'prefix': prefix,
                'body': label_text,
                'style': 'arabic_paren',
            }

        plain_special_kind = cls._classify_plain_special_heading(text)
        if plain_special_kind:
            level = 2 if plain_special_kind in {'cn_keywords', 'en_keywords'} else 1
            return {
                'title': text,
                'level': level,
                'prefix': '',
                'body': text,
                'style': 'plain_special',
            }

        return None

    @classmethod
    def _normalize_outline_section_body(cls, text):
        lines = []
        for raw_line in (text or '').splitlines():
            if cls._analyze_outline_heading(raw_line):
                continue
            lines.append(raw_line)
        # Preserve first-line indentation while still trimming blank lines
        # introduced by the Tk text widget around the stored section body.
        return '\n'.join(lines).strip('\n')

    @staticmethod
    def _normalize_import_section_body(text):
        return str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')

    @classmethod
    def _build_outline_structure(cls, text):
        lines = str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
        headings = []
        stack = []
        for index, line in enumerate(lines):
            parsed = cls._analyze_outline_heading(line)
            if not parsed:
                continue
            title = parsed['title']
            level = parsed['level']
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            parent_title = stack[-1]['title'] if stack else ''
            heading = {'title': title, 'start': index, 'level': level, 'parent': parent_title}
            headings.append(heading)
            stack.append(heading)

        sections = {}
        order = []
        levels = {}
        parents = {}
        for idx, heading in enumerate(headings):
            next_start = headings[idx + 1]['start'] if idx + 1 < len(headings) else len(lines)
            body_lines = []
            for candidate in lines[heading['start'] + 1:next_start]:
                if cls._analyze_outline_heading(candidate):
                    continue
                body_lines.append(candidate)
            title = heading['title']
            sections[title] = cls._normalize_outline_section_body('\n'.join(body_lines))
            order.append(title)
            levels[title] = heading['level']
            parents[title] = heading['parent']
        return {
            'sections': sections,
            'order': order,
            'levels': levels,
            'parents': parents,
        }

    @staticmethod
    def _block_toc_like(block):
        if not isinstance(block, dict):
            return False
        if bool(block.get('is_toc_like', False)):
            return True
        text = re.sub(r'\s+', ' ', str(block.get('text', '') or '').strip())
        if not text:
            return False
        plain = text.strip('：:').lower()
        if plain in {'目录', 'contents', 'table of contents'}:
            return True
        if re.search(r'(?:\.{2,}|…{2,}|·{2,}|_{2,})\s*\d+\s*$', text):
            return True
        style_text = f'{block.get("style_name", "")} {block.get("style_id", "")}'.lower()
        return 'toc' in style_text or '目录' in style_text

    @staticmethod
    def _coerce_block_outline_level(block):
        try:
            level = int((block or {}).get('outline_level', -1))
        except Exception:
            return -1
        return level if 0 <= level <= 8 else -1

    @classmethod
    def _heading_from_docx_metadata(cls, block):
        if not isinstance(block, dict) or block.get('type') != 'paragraph':
            return None
        text = str(block.get('text', '') or '').strip()
        if not text or cls._block_toc_like(block):
            return None
        if cls._looks_like_descriptive_chapter_sentence(text):
            return None

        style_text = f'{block.get("style_name", "")} {block.get("style_id", "")}'.strip()
        style_lower = style_text.lower()
        outline_level = cls._coerce_block_outline_level(block)
        level = 0
        style_match = re.search(r'(?:heading|标题)\s*([1-9一二三四五六七八九])', style_lower, re.IGNORECASE)
        if style_match:
            raw_level = style_match.group(1)
            cn_level_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
            try:
                level = int(raw_level)
            except Exception:
                level = cn_level_map.get(raw_level, 0)
        elif outline_level >= 0:
            level = outline_level + 1
        if level <= 0 or level > 3:
            return None

        parsed = cls._analyze_outline_heading(text)
        if parsed:
            if (
                parsed.get('style') in {'chapter', 'decimal', 'single_number', 'cn_enum', 'cn_paren', 'arabic_paren'}
                and cls._looks_like_import_body_sentence(parsed.get('body', ''))
            ):
                return None
            result = dict(parsed)
            result['level'] = min(max(level, 1), 3)
            result['style'] = 'docx_style'
            return result

        special_kind = cls._classify_plain_special_heading(text)
        if special_kind:
            return {
                'title': text,
                'level': min(max(level, 1), 3),
                'prefix': '',
                'body': text,
                'style': 'docx_style',
            }

        if cls._looks_like_import_body_sentence(text):
            return None

        return {
            'title': cls._build_markdown_outline_title(text, min(max(level, 1), 3)),
            'level': min(max(level, 1), 3),
            'prefix': '',
            'body': text,
            'style': 'docx_style',
        }

    @staticmethod
    def _metadata_numeric_score(block):
        score = 0
        try:
            font_size = float((block or {}).get('font_size_pt') or 0)
        except Exception:
            font_size = 0
        try:
            bold_ratio = float((block or {}).get('bold_ratio') or 0)
        except Exception:
            bold_ratio = 0
        alignment = str((block or {}).get('alignment', '') or '').lower()
        style_text = f'{(block or {}).get("style_name", "")} {(block or {}).get("style_id", "")}'.lower()
        if font_size >= 13.5:
            score += 2
        elif font_size >= 12.5:
            score += 1
        if bold_ratio >= 0.8:
            score += 2
        elif bold_ratio >= 0.5:
            score += 1
        if 'center' in alignment or alignment == '1':
            score += 1
        if 'normal' not in style_text and ('正文' not in style_text):
            score += 1
        return score

    @staticmethod
    def _block_has_import_metadata(block):
        if not isinstance(block, dict):
            return False
        for key in ('style_name', 'style_id', 'outline_level', 'font_size_pt', 'bold_ratio', 'alignment', 'is_toc_like'):
            value = block.get(key, None)
            if value not in (None, '', -1, False):
                return True
        return False

    @staticmethod
    def _looks_like_descriptive_chapter_sentence(text):
        value = str(text or '').strip()
        if not value:
            return False
        return bool(
            re.match(
                r'^\s*\u7b2c[\u4e00-\u4e5d\u5341\u767e\u5343\u4e07\d]+(?:\u7ae0|\u8282|\u90e8\u5206|\u7bc7)\s*'
                r'(?:\u4e3a|\u662f|\u5c06|\u4f1a|\u4e3b\u8981|\u91cd\u70b9|\u56f4\u7ed5|\u805a\u7126|'
                r'\u5305\u62ec|\u4ecb\u7ecd|\u9610\u8ff0|\u5206\u6790|\u8ba8\u8bba|\u8bf4\u660e|'
                r'\u5c55\u5f00|\u603b\u7ed3|\u660e\u786e|\u63a2\u8ba8)',
                value,
            )
        )

    @staticmethod
    def _looks_like_import_body_sentence(text):
        value = str(text or '').strip()
        if not value:
            return True
        compact = re.sub(r'\s+', '', value)
        if len(compact) > 70:
            return True
        if re.search(r'[\u3002\uff01\uff1f?!\uff1b;]$', value):
            return True
        if len(compact) >= 24 and re.search(r'[\uff0c\u3001\uff1b\uff1a,:]', value):
            return True
        body_leads = (
            '\u7814\u7a76\u5bf9\u8c61', '\u6837\u672c\u6765\u6e90', '\u5b9e\u9a8c\u8fc7\u7a0b', '\u6570\u636e\u6765\u6e90', '\u8c03\u67e5\u5bf9\u8c61',
            '\u672c\u6587', '\u672c\u7814\u7a76', '\u672c\u8bba\u6587', '\u5177\u4f53\u800c\u8a00', '\u9996\u5148', '\u5176\u6b21', '\u6700\u540e',
        )
        if value.startswith(body_leads):
            return True
        sentence_leads = (
            '\u4e3a', '\u662f', '\u5c06', '\u4f1a', '\u4e3b\u8981', '\u91cd\u70b9', '\u56f4\u7ed5',
            '\u805a\u7126', '\u5305\u62ec', '\u4ecb\u7ecd', '\u9610\u8ff0', '\u5206\u6790', '\u8ba8\u8bba',
            '\u8bf4\u660e', '\u5c55\u5f00', '\u603b\u7ed3', '\u660e\u786e', '\u63a2\u8ba8',
        )
        if value.startswith(sentence_leads):
            return len(compact) >= 10 or bool(re.search(r'[\uff0c\u3001\uff1b\uff1a,:]', value))
        return False

    @staticmethod
    def _looks_like_numbered_body_sentence(text):
        return PaperWritePage._looks_like_import_body_sentence(text)
        value = str(text or '').strip()
        if not value:
            return True
        if len(value) > 70:
            return True
        if re.search(r'[。！？?!；;，,]$', value):
            return True
        body_leads = (
            '研究对象', '样本来源', '实验过程', '数据来源', '调查对象',
            '本文', '本研究', '本论文', '具体而言', '首先', '其次', '最后',
        )
        return value.startswith(body_leads)

    @classmethod
    def _heading_from_import_block(cls, block):
        metadata_heading = cls._heading_from_docx_metadata(block)
        if metadata_heading:
            return metadata_heading
        if not isinstance(block, dict) or block.get('type') != 'paragraph' or cls._block_toc_like(block):
            return None

        text = str(block.get('text', '') or '').strip()
        if cls._looks_like_descriptive_chapter_sentence(text):
            return None
        parsed = cls._analyze_outline_heading(text)
        if not parsed:
            return None

        style = parsed.get('style')
        if style in {'chapter', 'decimal', 'single_number', 'cn_enum', 'cn_paren', 'arabic_paren'}:
            body = str(parsed.get('body', '') or '').strip()
            if cls._looks_like_import_body_sentence(body):
                return None
        if style in {'markdown', 'chapter', 'decimal', 'plain_special'}:
            return parsed

        if style in {'single_number', 'cn_enum', 'cn_paren', 'arabic_paren'}:
            body = str(parsed.get('body', '') or '').strip()
            if cls._looks_like_numbered_body_sentence(body):
                return None
            if cls._block_has_import_metadata(block) and cls._metadata_numeric_score(block) < 2:
                return None
            return parsed

        return None

    @classmethod
    def _build_ai_import_blocks_payload(cls, blocks):
        payload = []
        for index, block in enumerate(sanitize_blocks(blocks)):
            block_type = str(block.get('type', '') or '').strip()
            if block_type == 'paragraph':
                text = str(block.get('text', '') or '').strip()
                if not text:
                    continue
                payload.append(
                    {
                        'index': index,
                        'type': 'paragraph',
                        'text': text[:500],
                        'style_name': str(block.get('style_name', '') or '')[:80],
                        'outline_level': block.get('outline_level', -1),
                        'font_size_pt': block.get('font_size_pt', ''),
                        'bold_ratio': block.get('bold_ratio', 0),
                        'alignment': str(block.get('alignment', '') or '')[:40],
                        'is_toc_like': bool(cls._block_toc_like(block)),
                    }
                )
                continue
            if block_type == 'table':
                rows = block.get('rows', []) or []
                caption = str(block.get('caption', '') or '').strip()
                preview_rows = []
                for row in rows[:3]:
                    preview_rows.append([str(cell or '')[:80] for cell in list(row)[:5]])
                payload.append(
                    {
                        'index': index,
                        'type': 'table',
                        'caption': caption[:120],
                        'rows_preview': preview_rows,
                        'row_count': len(rows),
                    }
                )
        return payload

    @staticmethod
    def _extract_json_object(text):
        raw = str(text or '').strip()
        if not raw:
            raise RuntimeError('AI识别未返回内容')
        if raw.startswith('```'):
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.IGNORECASE)
            raw = re.sub(r'\s*```$', '', raw).strip()
        start = raw.find('{')
        end = raw.rfind('}')
        if start < 0 or end < start:
            raise RuntimeError('AI识别结果不是 JSON 对象')
        try:
            payload = json.loads(raw[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'AI识别结果 JSON 解析失败：{exc}') from exc
        if not isinstance(payload, dict):
            raise RuntimeError('AI识别结果不是 JSON 对象')
        return payload

    @classmethod
    def _normalize_ai_import_title(cls, title, level):
        text = str(title or '').strip()
        if not text:
            return ''
        markdown = cls.OUTLINE_MARKDOWN_RE.match(cls._strip_outline_emphasis(text))
        if markdown:
            return cls._build_markdown_outline_title(markdown.group(2).strip(), level)
        return cls._build_markdown_outline_title(text, level)

    @classmethod
    def _build_outline_structure_from_ai_payload(cls, ai_payload, blocks):
        sanitized = sanitize_blocks(blocks)
        sections_payload = ai_payload.get('sections') if isinstance(ai_payload, dict) else None
        if not isinstance(sections_payload, list):
            raise RuntimeError('AI识别结果缺少 sections 数组')
        index_map = {index: block for index, block in enumerate(sanitized)}

        sections = {}
        section_blocks = {}
        order = []
        levels = {}
        parents = {}
        stack = []
        used_block_indexes = set()

        def allocate_title(proposed):
            base = str(proposed or '').strip() or '# 未命名章节'
            candidate = base
            suffix = 2
            while candidate in sections:
                candidate = f'{base} ({suffix})'
                suffix += 1
            return candidate

        for item in sections_payload:
            if not isinstance(item, dict):
                continue
            try:
                level = int(item.get('level', 1) or 1)
            except Exception:
                level = 1
            level = max(1, min(level, 3))
            title = allocate_title(cls._normalize_ai_import_title(item.get('title', ''), level))
            if not title:
                continue
            body_blocks = []
            for raw_index in item.get('blocks', []) or []:
                try:
                    block_index = int(raw_index)
                except Exception:
                    continue
                block = index_map.get(block_index)
                if not block or block_index in used_block_indexes:
                    continue
                if cls._block_toc_like(block):
                    used_block_indexes.add(block_index)
                    continue
                body_blocks.append(block)
                used_block_indexes.add(block_index)

            while stack and stack[-1]['level'] >= level:
                stack.pop()
            parent_title = stack[-1]['title'] if stack else ''
            sections[title] = cls._normalize_import_section_body(blocks_to_plain_text(body_blocks))
            section_blocks[title] = deep_copy_blocks(body_blocks)
            order.append(title)
            levels[title] = level
            parents[title] = parent_title
            stack.append({'title': title, 'level': level})

        if not order:
            raise RuntimeError('AI识别结果没有有效章节')

        return {
            'sections': sections,
            'section_blocks': section_blocks,
            'order': order,
            'levels': levels,
            'parents': parents,
        }

    def _build_outline_structure_with_ai(self, blocks):
        payload = self._build_ai_import_blocks_payload(blocks)
        if not payload:
            return self._empty_outline_structure()
        response = self.writer.import_outline_with_ai(payload)
        parsed_payload = self._extract_json_object(response)
        return self._build_outline_structure_from_ai_payload(parsed_payload, blocks)

    @classmethod
    def _build_outline_structure_from_blocks(cls, blocks):
        sanitized = sanitize_blocks(blocks)
        if not sanitized:
            return cls._empty_outline_structure()

        sections = {}
        section_blocks = {}
        order = []
        levels = {}
        parents = {}
        stack = []
        current_title = ''
        fallback_blocks = []

        def ensure_section(parsed_heading):
            nonlocal current_title
            title = parsed_heading['title']
            level = parsed_heading['level']
            while stack and stack[-1]['level'] >= level:
                stack.pop()
            parent_title = stack[-1]['title'] if stack else ''
            heading = {'title': title, 'level': level, 'parent': parent_title}
            stack.append(heading)
            if title not in sections:
                sections[title] = ''
                section_blocks[title] = []
                order.append(title)
            levels[title] = level
            parents[title] = parent_title
            current_title = title

        for block in sanitized:
            if cls._block_toc_like(block):
                continue
            if block.get('type') == 'paragraph':
                heading = cls._heading_from_import_block(block)
                if heading:
                    ensure_section(heading)
                    continue
            if current_title:
                section_blocks.setdefault(current_title, []).append(block)
            else:
                fallback_blocks.append(block)

        if not order:
            fallback_title = '未解析大纲'
            fallback_text = blocks_to_plain_text(fallback_blocks or sanitized)
            return {
                'sections': {fallback_title: fallback_text},
                'section_blocks': {fallback_title: deep_copy_blocks(fallback_blocks or sanitized)},
                'order': [fallback_title],
                'levels': {fallback_title: 1},
                'parents': {fallback_title: ''},
            }

        if fallback_blocks:
            first_title = order[0]
            section_blocks[first_title] = deep_copy_blocks(fallback_blocks) + section_blocks.get(first_title, [])

        for title in order:
            sections[title] = cls._normalize_import_section_body(
                blocks_to_plain_text(section_blocks.get(title, []))
            )

        return {
            'sections': sections,
            'section_blocks': section_blocks,
            'order': order,
            'levels': levels,
            'parents': parents,
        }

    @classmethod
    def _normalize_outline_structure(cls, parsed):
        sections = dict(parsed.get('sections', {}) or {})
        raw_order = list(parsed.get('order', []) or [])
        raw_levels = dict(parsed.get('levels', {}) or {})
        raw_parents = dict(parsed.get('parents', {}) or {})
        order = [title for title in raw_order if title in sections]
        for title in sections:
            if title not in order:
                order.append(title)
        if not order:
            return {
                'sections': {},
                'order': [],
                'levels': {},
                'parents': {},
                'aliases': {},
            }

        intro_root_titles = {
            title
            for title in order
            if cls._classify_outline_special_title(title) == 'intro'
        }

        def has_intro_ancestor(title):
            parent = raw_parents.get(title, '')
            while parent:
                if parent in intro_root_titles:
                    return True
                parent = raw_parents.get(parent, '')
            return False

        first_body_index = next(
            (index for index, title in enumerate(order) if cls._is_primary_body_chapter_title(title)),
            len(order),
        )
        intro_name = '绪论' if any(
            cls._normalize_special_heading_plain_text(cls._editable_title_text(title)) == '绪论'
            for title in intro_root_titles
        ) else '引言'

        cn_abstract_body = ''
        en_abstract_body = ''
        intro_body = ''
        reference_body = ''
        intro_children = []
        normal_nodes = []
        appendix_nodes = []
        previous_intro_level = 0

        for index, title in enumerate(order):
            body = cls._normalize_outline_section_body(sections.get(title, ''))
            level = max(1, int(raw_levels.get(title, cls._infer_outline_level(title)) or 1))
            kind = cls._classify_outline_special_title(title)

            if kind == 'cn_abstract':
                abstract_text, keyword_text = cls._parse_abstract_result(body)
                merged_body = cls._merge_abstract_keyword_body(abstract_text, keyword_text, language='cn')
                cn_abstract_body = cls._merge_outline_section_bodies(cn_abstract_body, merged_body or body)
                continue

            if kind == 'cn_keywords':
                cn_abstract_body = cls._merge_outline_section_bodies(
                    cn_abstract_body,
                    cls._format_keyword_line(body, language='cn'),
                )
                continue

            if kind == 'en_abstract':
                abstract_text, keyword_text = cls._parse_abstract_result(body)
                merged_body = cls._merge_abstract_keyword_body(abstract_text, keyword_text, language='en')
                en_abstract_body = cls._merge_outline_section_bodies(en_abstract_body, merged_body or body)
                continue

            if kind == 'en_keywords':
                en_abstract_body = cls._merge_outline_section_bodies(
                    en_abstract_body,
                    cls._format_keyword_line(body, language='en'),
                )
                continue

            if kind == 'intro':
                if cls._normalize_special_heading_plain_text(cls._editable_title_text(title)) == '绪论':
                    intro_name = '绪论'
                intro_body = cls._merge_outline_section_bodies(intro_body, body)
                continue

            if kind == 'reference':
                reference_body = cls._merge_outline_section_bodies(reference_body, body)
                continue

            if has_intro_ancestor(title) or (index < first_body_index and level > 1):
                child_level = cls._normalize_intro_child_level(level, previous_intro_level)
                previous_intro_level = child_level
                intro_children.append(
                    {
                        'source': title,
                        'title': cls._build_markdown_outline_title(cls._editable_title_text(title), child_level),
                        'body': body,
                        'level': child_level,
                    }
                )
                continue

            target_nodes = appendix_nodes if kind == 'appendix' else normal_nodes
            target_nodes.append(
                {
                    'source': title,
                    'title': title,
                    'body': body,
                    'level': level,
                }
            )

        final_nodes = []
        used_titles = set()
        aliases = {}

        def allocate_title(proposed_title):
            candidate = str(proposed_title or '').strip()
            if not candidate:
                candidate = '# 未命名章节'
            if candidate not in used_titles:
                used_titles.add(candidate)
                return candidate
            suffix = 2
            while True:
                retry = f'{candidate} ({suffix})'
                if retry not in used_titles:
                    used_titles.add(retry)
                    return retry
                suffix += 1

        def append_node(title, body, level):
            actual_title = allocate_title(title)
            final_nodes.append(
                {
                    'title': actual_title,
                    'body': cls._normalize_outline_section_body(body or ''),
                    'level': max(1, int(level or 1)),
                }
            )
            return actual_title

        cn_abstract_title = append_node(cls._canonical_outline_title('cn_abstract'), cn_abstract_body, 1)
        en_abstract_title = append_node(cls._canonical_outline_title('en_abstract'), en_abstract_body, 1)
        intro_title = append_node(cls._canonical_outline_title('intro', intro_name=intro_name), intro_body, 1)

        for title in order:
            kind = cls._classify_outline_special_title(title)
            if kind == 'cn_abstract':
                aliases[title] = cn_abstract_title
            elif kind == 'cn_keywords':
                aliases[title] = cn_abstract_title
            elif kind == 'en_abstract':
                aliases[title] = en_abstract_title
            elif kind == 'en_keywords':
                aliases[title] = en_abstract_title
            elif kind == 'intro':
                aliases[title] = intro_title

        for node in intro_children:
            actual_title = append_node(node['title'], node['body'], node['level'])
            aliases[node['source']] = actual_title

        for node in normal_nodes:
            actual_title = append_node(node['title'], node['body'], node['level'])
            aliases[node['source']] = actual_title

        reference_title = append_node(cls._canonical_outline_title('reference'), reference_body, 1)
        for title in order:
            if cls._classify_outline_special_title(title) == 'reference':
                aliases[title] = reference_title

        for node in appendix_nodes:
            actual_title = append_node(node['title'], node['body'], node['level'])
            aliases[node['source']] = actual_title

        normalized_sections = {}
        normalized_order = []
        normalized_levels = {}
        normalized_parents = {}
        stack = []
        for node in final_nodes:
            title = node['title']
            level = node['level']
            while stack and stack[-1][1] >= level:
                stack.pop()
            normalized_sections[title] = node['body']
            normalized_order.append(title)
            normalized_levels[title] = level
            normalized_parents[title] = stack[-1][0] if stack else ''
            stack.append((title, level))

        return {
            'sections': normalized_sections,
            'order': normalized_order,
            'levels': normalized_levels,
            'parents': normalized_parents,
            'aliases': aliases,
        }

    @staticmethod
    def _normalize_editor_block_text(text):
        return str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')

    def _compose_outline_text(self):
        return '\n'.join(self._section_order).strip()

    def _sync_outline_text_from_sections(self):
        self.outline_text.delete('1.0', tk.END)
        outline_text = self._compose_outline_text()
        if outline_text:
            self.outline_text.insert('1.0', outline_text)

    def _heading_plain_text(self, title):
        return self._normalize_special_heading_plain_text(self._editable_title_text(title))

    def _find_section_title_by_kind(self, kind):
        for title in self._section_order:
            if self._classify_outline_special_title(title) == kind:
                return title
        return ''

    def _is_abstract_section_title(self, title):
        return self._classify_outline_special_title(title) in {'cn_abstract', 'en_abstract'}

    def _is_keyword_section_title(self, title):
        return self._classify_outline_special_title(title) in {'cn_keywords', 'en_keywords'}

    def _find_chinese_abstract_section_title(self):
        return self._find_section_title_by_kind('cn_abstract')

    def _is_reference_section_title(self, title):
        return self._classify_outline_special_title(title) == 'reference'

    def _is_appendix_section_title(self, title):
        return self._classify_outline_special_title(title) == 'appendix' or self._heading_plain_text(title).startswith('附录')

    def _find_reference_section_title(self):
        for title in self._section_order:
            if self._is_reference_section_title(title):
                return title
        return ''

    @classmethod
    def _build_default_front_matter_structure(cls, intro_name='引言'):
        titles = [
            (cls._canonical_outline_title('cn_abstract'), 1),
            (cls._canonical_outline_title('en_abstract'), 1),
            (cls._canonical_outline_title('intro', intro_name=intro_name), 1),
            (cls._canonical_outline_title('reference'), 1),
        ]
        sections = {title: '' for title, _ in titles}
        order = [title for title, _ in titles]
        levels = {title: level for title, level in titles}
        parents = {}
        stack = []
        for title in order:
            level = levels[title]
            while stack and stack[-1][1] >= level:
                stack.pop()
            parents[title] = stack[-1][0] if stack else ''
            stack.append((title, level))
        return {
            'sections': sections,
            'order': order,
            'levels': levels,
            'parents': parents,
            'aliases': {},
        }

    def _ensure_abstract_section(self):
        self._normalize_outline_structure_state()
        if not self._section_order:
            self._apply_normalized_outline_state(self._build_default_front_matter_structure())
        abstract_title = self._find_chinese_abstract_section_title()
        if not abstract_title:
            self._apply_normalized_outline_state(self._build_default_front_matter_structure())
            abstract_title = self._find_chinese_abstract_section_title()
        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        return abstract_title

    def _collect_full_text_for_abstract(self):
        self._store_current_editor_content()

        parts = []
        topic = self.topic_entry.get().strip()
        if topic:
            parts.append(f'# {topic}')

        for title in self._section_order:
            if (
                self._is_abstract_section_title(title)
                or self._is_keyword_section_title(title)
                or self._is_reference_section_title(title)
            ):
                continue
            body = self._normalize_section_body(self._sections.get(title, ''))
            if not body:
                continue
            parts.append(f'{title}\n{body}')

        if not parts:
            current_text = self._get_current_editor_text()
            if current_text:
                current_title = self._editor_section_source or self.section_entry.get().strip() or '正文'
                parts.append(f'{current_title}\n{current_text}')

        return '\n\n'.join(part for part in parts if part).strip()

    @staticmethod
    def _parse_abstract_result(text):
        raw = (text or '').strip()
        if not raw:
            return '', ''

        normalized = raw.replace('\r\n', '\n').replace('\r', '\n')
        keyword_match = re.search(
            r'(?:^|\n)\s*[【\[]?(?:关键词|关键字|keywords)[】\]]?\s*(?:[:：]\s*)?(.+)$',
            normalized,
            re.IGNORECASE | re.DOTALL,
        )
        keyword_text = ''
        abstract_part = normalized
        if keyword_match:
            abstract_part = normalized[:keyword_match.start()].strip()
            keyword_text = keyword_match.group(1).strip()

        abstract_part = re.sub(
            r'^\s*[【\[]?(?:摘要|abstract)[】\]]?\s*(?:[:：]\s*)?',
            '',
            abstract_part,
            flags=re.IGNORECASE,
        )
        keyword_text = re.sub(r'\s+', ' ', keyword_text).strip('；;,.， ')
        return abstract_part.strip(), keyword_text

    def _format_generated_abstract(self, text):
        abstract_text, keyword_text = self._parse_abstract_result(text)
        if not abstract_text and not keyword_text:
            return self._normalize_section_body(text)

        parts = []
        if abstract_text:
            parts.append(abstract_text)
        if keyword_text:
            parts.append(f'关键词：{keyword_text}')
        return '\n\n'.join(parts).strip()

    def _write_abstract_to_section(self, content):
        self._normalize_outline_structure_state()
        abstract_title = self._ensure_abstract_section()
        abstract_text, keyword_text = self._parse_abstract_result(content)
        if not abstract_text and not keyword_text:
            abstract_text = self._normalize_section_body(content)
        self._sections[abstract_title] = self._merge_abstract_keyword_body(
            abstract_text,
            keyword_text,
            language='cn',
        )
        self._section_blocks[abstract_title] = self._blocks_from_section_text(self._sections[abstract_title])
        self._section_formats[abstract_title] = []
        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._select_section(abstract_title, touch_context=False)
        self._touch_context_revision()
        self._update_stats()
        self.frame.after_idle(self._capture_selection_snapshot)
        self._schedule_workspace_state_save()
        return abstract_title

    @staticmethod
    def _is_markdown_rule_line(line):
        return bool(re.match(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$', str(line or '')))

    @classmethod
    def _split_reference_heading_line(cls, line):
        candidate = str(line or '').strip()
        if not candidate or cls._is_markdown_rule_line(candidate):
            return None

        candidate = re.sub(r'^\s*#{1,6}\s*', '', candidate).strip()
        emphasis_markers = r'(?:\*\*\*|___|\*\*|__|\*|_)'
        match = re.match(
            rf'^(?:{emphasis_markers}\s*)?(?:[【\[]\s*)?'
            rf'(?P<label>参考文献|references|bibliography)'
            rf'(?:\s*[】\]])?(?:\s*{emphasis_markers})?\s*(?P<trailing>.*)$',
            candidate,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        trailing = (match.group('trailing') or '').strip()
        if not trailing:
            return {'inline_rest': ''}

        if trailing[:1] not in ':：（(':
            return None

        remainder = trailing
        if remainder[:1] in ':：':
            remainder = remainder[1:].lstrip()

        while remainder:
            note_match = re.match(r'^[（(][^()（）\n]{0,200}[)）]\s*', remainder)
            if not note_match:
                break
            remainder = remainder[note_match.end():].lstrip()
            if remainder[:1] in ':：':
                remainder = remainder[1:].lstrip()

        return {'inline_rest': remainder}

    @classmethod
    def _find_reference_block_start(cls, lines):
        if not lines:
            return None, None

        for heading_index, line in enumerate(lines):
            if cls._split_reference_heading_line(line) is None:
                continue

            block_start = heading_index
            while block_start > 0 and not str(lines[block_start - 1] or '').strip():
                block_start -= 1
            if block_start > 0 and cls._is_markdown_rule_line(lines[block_start - 1]):
                block_start -= 1
                while block_start > 0 and not str(lines[block_start - 1] or '').strip():
                    block_start -= 1
            return block_start, heading_index

        return None, None

    @classmethod
    def _find_trailing_reference_entries_start(cls, lines):
        if not lines:
            return None

        start_re = re.compile(r'^\s*(?:\[(\d+)\]|(\d+)[\.、])\s+\S')
        candidates = []
        for index, line in enumerate(lines):
            if not start_re.match(str(line or '')):
                continue
            if index > 0:
                previous = str(lines[index - 1] or '')
                if previous.strip() and not cls._is_markdown_rule_line(previous):
                    continue
            candidates.append(index)

        for index in candidates:
            suffix = '\n'.join(lines[index:]).strip()
            if not suffix:
                continue
            entries = cls._parse_reference_entries(suffix)
            if not entries:
                continue
            numbered_starts = [
                line for line in lines[index:]
                if start_re.match(str(line or ''))
            ]
            if numbered_starts:
                return index
        return None

    def _strip_reference_heading(self, text):
        normalized = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            return ''

        lines = normalized.split('\n')
        _block_start, heading_index = self._find_reference_block_start(lines)
        if heading_index is None:
            return normalized

        heading_meta = self._split_reference_heading_line(lines[heading_index]) or {}
        entry_lines = []
        inline_rest = (heading_meta.get('inline_rest') or '').strip()
        if inline_rest:
            entry_lines.append(inline_rest)
        entry_lines.extend(lines[heading_index + 1:])
        while entry_lines and self._is_markdown_rule_line(entry_lines[0]):
            entry_lines.pop(0)
        while entry_lines and not str(entry_lines[0]).strip():
            entry_lines.pop(0)
        while entry_lines and not str(entry_lines[-1]).strip():
            entry_lines.pop()
        if entry_lines:
            return '\n'.join(entry_lines).strip()
        return normalized

    def _extract_references_from_section_result(self, text):
        normalized = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            return '', ''

        lines = normalized.split('\n')
        block_start, heading_index = self._find_reference_block_start(lines)
        if heading_index is None:
            trailing_start = self._find_trailing_reference_entries_start(lines)
            if trailing_start is None:
                return self._normalize_section_body(normalized), ''
            body_part = '\n'.join(lines[:trailing_start]).strip()
            references_text = '\n'.join(lines[trailing_start:]).strip()
            return self._normalize_section_body(body_part), self._normalize_section_body(references_text)

        body_part = '\n'.join(lines[:block_start]).strip()
        references_part = '\n'.join(lines[block_start:]).strip()
        references_text = self._strip_reference_heading(references_part)
        return self._normalize_section_body(body_part), self._normalize_section_body(references_text)

    def _ensure_reference_section(self):
        self._normalize_outline_structure_state()
        if not self._section_order:
            self._apply_normalized_outline_state(self._build_default_front_matter_structure())
        reference_title = self._find_reference_section_title()
        if reference_title:
            return reference_title

        insert_index = len(self._section_order)
        appendix_title = next((title for title in self._section_order if self._is_appendix_section_title(title)), '')
        if appendix_title:
            insert_index = self._section_order.index(appendix_title)

        reference_title = self._canonical_outline_title('reference')
        if reference_title in self._sections:
            reference_title = self._make_unique_title(reference_title)
        self._section_order.insert(insert_index, reference_title)
        self._sections[reference_title] = ''
        self._section_blocks.pop(reference_title, None)
        self._section_formats[reference_title] = []
        self._section_levels[reference_title] = 1
        self._section_parent[reference_title] = ''
        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        return reference_title

    def _write_references_to_section(self, references_text):
        clean_references = self._normalize_section_body(self._strip_reference_heading(references_text))
        if not clean_references:
            return ''

        reference_title = self._ensure_reference_section()
        existing_entries = self._parse_reference_entries(self._sections.get(reference_title, ''))
        new_entries = self._parse_reference_entries(clean_references)
        merged_entries = self._merge_reference_entry_lists(existing_entries, new_entries)
        self._sections[reference_title] = self._build_reference_body_from_entries(merged_entries)
        self._section_blocks[reference_title] = self._blocks_from_section_text(self._sections[reference_title])
        self._section_formats[reference_title] = []
        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._schedule_workspace_state_save()
        return reference_title

    @classmethod
    def _compose_section_text(cls, existing_text, new_text, write_mode='replace'):
        existing = cls._normalize_editor_block_text(existing_text)
        new = cls._normalize_editor_block_text(new_text)
        if write_mode == 'append':
            if existing and new:
                return f'{existing}\n\n{new}'
            return new or existing
        return new or existing

    def _compose_section_blocks(self, section, existing_text, new_text, write_mode='replace'):
        if section and (self._editor_section_source == section or self.section_entry.get().strip() == section):
            existing_blocks = self._get_current_editor_blocks()
        else:
            existing_blocks = self._get_section_blocks(section) if section else self._blocks_from_section_text(existing_text)
        if not existing_blocks:
            existing_blocks = self._blocks_from_section_text(existing_text)
        new_blocks = self._blocks_from_section_text(new_text)
        if write_mode == 'append':
            return self._normalize_section_blocks(existing_blocks + new_blocks)
        return self._normalize_section_blocks(new_blocks or existing_blocks)

    @classmethod
    def _merge_reference_entry_lists(cls, *groups):
        merged = []
        seen = set()
        for group in groups:
            for entry in group or []:
                entry_text = cls._normalize_reference_entry_text(entry.get('text', ''))
                entry_key = cls._reference_entry_key(entry_text)
                if not entry_key or entry_key in seen:
                    continue
                seen.add(entry_key)
                merged.append({'text': entry_text, 'key': entry_key})
        return merged

    @classmethod
    def _build_reference_number_map(cls, entries):
        number_map = {}
        next_auto_number = 1
        for entry in entries or []:
            entry_text = cls._normalize_reference_entry_text(entry.get('text', ''))
            entry_key = cls._reference_entry_key(entry_text)
            if not entry_key:
                continue
            number = entry.get('number')
            if not isinstance(number, int) or number <= 0:
                while next_auto_number in number_map:
                    next_auto_number += 1
                number = next_auto_number
            number_map[number] = {
                'number': number,
                'text': entry_text,
                'key': entry_key,
            }
            next_auto_number = max(next_auto_number, number + 1)
        return number_map

    def _is_reference_linkable_section_title(self, title):
        return bool(title) and not (
            self._is_abstract_section_title(title)
            or self._is_keyword_section_title(title)
            or self._is_reference_section_title(title)
        )

    def _ensure_section_registered(self, section):
        if not section or section in self._section_order:
            return

        insert_index = len(self._section_order)
        reference_title = self._find_reference_section_title()
        appendix_title = next((title for title in self._section_order if self._is_appendix_section_title(title)), '')
        if reference_title:
            insert_index = self._section_order.index(reference_title)
        elif appendix_title:
            insert_index = self._section_order.index(appendix_title)

        level = self._infer_outline_level(section)
        self._section_order.insert(insert_index, section)
        self._sections.setdefault(section, '')
        if self._sections.get(section):
            self._section_blocks.setdefault(section, self._blocks_from_section_text(self._sections.get(section, '')))
        self._section_formats.setdefault(section, [])
        self._section_levels[section] = level
        self._section_parent[section] = self._find_parent_for_insert(insert_index, level)

    def _sync_document_references_after_section_write(
        self,
        section,
        existing_text,
        new_text,
        references_text,
        existing_formats=None,
        write_mode='replace',
    ):
        reference_title = self._ensure_reference_section()
        old_reference_entries = self._parse_reference_entries(self._sections.get(reference_title, ''))
        local_reference_entries = self._parse_reference_entries(references_text)
        old_number_map = self._build_reference_number_map(old_reference_entries)
        local_number_map = self._build_reference_number_map(local_reference_entries)

        entry_by_key = {}
        for entry in list(old_reference_entries) + list(local_reference_entries):
            entry_text = self._normalize_reference_entry_text(entry.get('text', ''))
            entry_key = self._reference_entry_key(entry_text)
            if entry_key and entry_key not in entry_by_key:
                entry_by_key[entry_key] = {'text': entry_text, 'key': entry_key}

        ordered_keys = []
        seen_keys = set()

        def append_keys(keys):
            for key in keys:
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                ordered_keys.append(key)

        for title in self._section_order:
            if title == reference_title or not self._is_reference_linkable_section_title(title):
                continue
            if title == section:
                if write_mode == 'append':
                    append_keys(self._collect_citation_reference_keys(existing_text, old_number_map))
                append_keys(self._collect_citation_reference_keys(new_text, local_number_map))
                continue
            section_body = self._normalize_section_body(self._sections.get(title, ''))
            append_keys(self._collect_citation_reference_keys(section_body, old_number_map))

        trailing_entry_groups = (old_reference_entries, local_reference_entries)
        if write_mode == 'replace':
            trailing_entry_groups = (local_reference_entries,)

        for entries in trailing_entry_groups:
            for entry in entries:
                entry_key = entry.get('key') or self._reference_entry_key(entry.get('text', ''))
                if not entry_key or entry_key in seen_keys:
                    continue
                seen_keys.add(entry_key)
                ordered_keys.append(entry_key)

        final_entries = []
        new_number_by_key = {}
        for entry_key in ordered_keys:
            entry = entry_by_key.get(entry_key)
            if not entry:
                continue
            new_number = len(final_entries) + 1
            new_number_by_key[entry_key] = new_number
            final_entries.append({'text': entry['text'], 'key': entry_key, 'new_number': new_number})

        for number_map in (old_number_map, local_number_map):
            for entry in number_map.values():
                entry['new_number'] = new_number_by_key.get(entry.get('key'))

        for title in self._section_order:
            if title in {section, reference_title} or not self._is_reference_linkable_section_title(title):
                continue
            current_body = self._normalize_section_body(self._sections.get(title, ''))
            rewritten_body = self._rewrite_citations_with_entry_map(current_body, old_number_map)
            if rewritten_body != current_body:
                self._sections[title] = rewritten_body
                blocks = self._blocks_from_section_text(rewritten_body)
                if blocks:
                    self._section_blocks[title] = blocks
                else:
                    self._section_blocks.pop(title, None)
                self._section_formats[title] = []

        rewritten_existing = self._rewrite_citations_with_entry_map(existing_text, old_number_map)
        rewritten_new = self._rewrite_citations_with_entry_map(new_text, local_number_map)
        merged_text = self._compose_section_text(rewritten_existing, rewritten_new, write_mode=write_mode)
        original_merged_text = self._compose_section_text(existing_text, new_text, write_mode=write_mode)
        merged_blocks = self._blocks_from_section_text(merged_text)
        merged_formats = (
            self._preserve_existing_formats(section, existing_text, merged_text, source_spans=existing_formats)
            if merged_text == original_merged_text
            else []
        )
        if any(block.get('type') == 'table' for block in merged_blocks):
            merged_formats = []

        self._sections[section] = merged_text
        if merged_blocks:
            self._section_blocks[section] = merged_blocks
        else:
            self._section_blocks.pop(section, None)
        self._section_formats[section] = merged_formats
        self._sections[reference_title] = self._build_reference_body_from_entries(final_entries)
        self._section_blocks[reference_title] = self._blocks_from_section_text(self._sections[reference_title])
        self._section_formats[reference_title] = []
        return merged_text, merged_formats, reference_title

    @classmethod
    def _parse_outline_heading(cls, line):
        parsed = cls._analyze_outline_heading(line)
        if not parsed:
            return None
        return parsed['title'], parsed['level']

    @classmethod
    def _infer_outline_level(cls, title):
        parsed = cls._parse_outline_heading(title)
        if parsed:
            return parsed[1]
        return 2

    def _default_title_for_level(self, level):
        if level <= 1:
            return '# 新一级标题'
        if level == 2:
            return '## 新二级标题'
        return '### 新三级标题'

    @classmethod
    def _editable_title_text(cls, title):
        parsed = cls._analyze_outline_heading(title)
        if parsed:
            return parsed['body']
        return cls._strip_outline_emphasis(title)

    def _format_title_for_level(self, original_title, new_text, level=None):
        target_level = max(1, int(level or self._section_levels.get(original_title, self._infer_outline_level(original_title)) or 1))
        label_text = (new_text or '').strip()
        if not label_text:
            return original_title

        parsed = self._analyze_outline_heading(original_title)
        if parsed:
            style = parsed['style']
            prefix = parsed['prefix']
            if style == 'markdown':
                hashes = '#' * min(target_level, 6)
                return f'{hashes} {label_text}'
            return f'{prefix} {label_text}'

        default_title = self._default_title_for_level(target_level)
        prefix_match = re.match(r'^(#{1,6})\s+', default_title)
        if prefix_match:
            return f'{prefix_match.group(1)} {label_text}'
        return label_text

    def _make_unique_title(self, proposed_title, exclude_title=''):
        candidate = (proposed_title or '').strip()
        if not candidate:
            return exclude_title or proposed_title

        taken = {title for title in self._section_order if title != exclude_title}
        if candidate not in taken:
            return candidate

        suffix = 2
        while True:
            retry = f'{candidate} ({suffix})'
            if retry not in taken:
                return retry
            suffix += 1

    def _is_descendant_of(self, title, ancestor):
        parent = self._section_parent.get(title, '')
        while parent:
            if parent == ancestor:
                return True
            parent = self._section_parent.get(parent, '')
        return False

    def _get_section_subtree_titles(self, title):
        if title not in self._section_order:
            return []

        start = self._section_order.index(title)
        result = [title]
        for candidate in self._section_order[start + 1:]:
            if not self._is_descendant_of(candidate, title):
                break
            result.append(candidate)
        return result

    def _subtree_end_index(self, title):
        subtree = self._get_section_subtree_titles(title)
        if not subtree:
            return -1
        return self._section_order.index(subtree[-1])

    def _find_parent_for_insert(self, anchor_index, level):
        for index in range(anchor_index - 1, -1, -1):
            candidate = self._section_order[index]
            candidate_level = self._section_levels.get(candidate, self._infer_outline_level(candidate))
            if candidate_level < level:
                return candidate
        return ''

    def _rename_section_title(self, old_title, new_title):
        if old_title not in self._sections or not new_title:
            return False
        unique_title = self._make_unique_title(new_title, exclude_title=old_title)
        if unique_title == old_title:
            return False

        self._sections[unique_title] = self._sections.pop(old_title)
        if old_title in self._section_blocks:
            self._section_blocks[unique_title] = self._section_blocks.pop(old_title)
        self._section_formats[unique_title] = self._section_formats.pop(old_title, [])
        self._section_levels[unique_title] = self._section_levels.pop(old_title, self._infer_outline_level(unique_title))
        self._section_parent[unique_title] = self._section_parent.pop(old_title, '')

        index = self._section_order.index(old_title)
        self._section_order[index] = unique_title

        for title in list(self._section_parent.keys()):
            if self._section_parent.get(title) == old_title:
                self._section_parent[title] = unique_title

        if old_title in self._collapsed_sections:
            self._collapsed_sections.remove(old_title)
            self._collapsed_sections.add(unique_title)

        if hasattr(self, '_outline_selected') and self._outline_selected.get() == old_title:
            self._outline_selected.set(unique_title)
        if self._editor_section_source == old_title:
            self._editor_section_source = unique_title
        if self.section_entry.get().strip() == old_title:
            self.section_entry.delete(0, tk.END)
            self.section_entry.insert(0, unique_title)

        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._select_section(unique_title, touch_context=False)
        self._touch_context_revision()
        self._schedule_workspace_state_save()
        return True

    def _insert_outline_title(self, reference_title, position, level):
        if reference_title not in self._section_order:
            return

        if position == 'below':
            anchor_index = self._subtree_end_index(reference_title) + 1
        else:
            anchor_index = self._section_order.index(reference_title)

        parent = self._find_parent_for_insert(anchor_index, level)
        new_title = self._make_unique_title(self._default_title_for_level(level))

        self._section_order.insert(anchor_index, new_title)
        self._sections[new_title] = ''
        self._section_blocks.pop(new_title, None)
        self._section_formats[new_title] = []
        self._section_levels[new_title] = level
        self._section_parent[new_title] = parent
        if parent in self._collapsed_sections:
            self._collapsed_sections.remove(parent)

        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._select_section(new_title, touch_context=False)
        self._begin_outline_title_edit(new_title)
        self._touch_context_revision()
        self._schedule_workspace_state_save()
        self.set_status('已插入新标题，请直接输入标题名称')
        return new_title

    def _clear_section_display(self):
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            self._outline_selected.set('')
        self._clear_editor_block_widgets()
        self.edit_text.delete('1.0', tk.END)
        self.section_entry.delete(0, tk.END)
        self._editor_section_source = ''
        self._editor_bg_indicator_color = self.DEFAULT_BG_SWATCH_COLOR
        self._refresh_editor_toolbar_icons()
        self._selection_snapshot = None
        self._editor_selection_range = None
        self._reset_editor_undo_stack()
        self._update_stats()

    def _delete_outline_title(self, title):
        if title not in self._section_order:
            return False

        subtree = self._get_section_subtree_titles(title)
        if not subtree:
            return False

        message = f'确定删除“{title}”吗？此操作不可撤销。'
        if len(subtree) > 1:
            message = f'确定删除“{title}”及其下级标题（共 {len(subtree)} 项）吗？此操作不可撤销。'
        if not messagebox.askyesno('删除大纲', message, parent=self.frame):
            return False

        self._store_current_editor_content()

        current_title = self._editor_section_source or self.section_entry.get().strip()
        start_index = self._section_order.index(title)
        end_index = start_index + len(subtree) - 1
        replacement_title = ''
        if current_title and current_title not in subtree:
            replacement_title = current_title
        elif end_index + 1 < len(self._section_order):
            replacement_title = self._section_order[end_index + 1]
        elif start_index > 0:
            replacement_title = self._section_order[start_index - 1]

        removed_titles = set(subtree)
        self._section_order = [candidate for candidate in self._section_order if candidate not in removed_titles]
        for candidate in subtree:
            self._sections.pop(candidate, None)
            self._section_blocks.pop(candidate, None)
            self._section_formats.pop(candidate, None)
            self._section_levels.pop(candidate, None)
            self._section_parent.pop(candidate, None)

        self._collapsed_sections.difference_update(removed_titles)
        if self._outline_context_title in removed_titles:
            self._outline_context_title = ''
        if self._outline_editing_title in removed_titles:
            self._outline_editing_title = ''

        self._infer_section_relationships_from_order()
        self._collapsed_sections = {
            candidate
            for candidate in self._collapsed_sections
            if candidate in self._section_children and self._section_children.get(candidate)
        }
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()

        if replacement_title and replacement_title in self._section_order:
            if current_title and replacement_title == current_title:
                self._outline_selected.set(replacement_title)
                for candidate in list(getattr(self, '_outline_row_widgets', {}).keys()):
                    self._set_outline_row_visual(candidate)
                self.frame.after_idle(lambda target=replacement_title: self._scroll_outline_selection_into_view(target))
                self._update_stats()
            else:
                self._select_section(replacement_title, touch_context=False)
        else:
            self._clear_section_display()

        self._touch_context_revision()
        self._schedule_workspace_state_save()
        self.set_status('已删除所选大纲')
        return True

    def _change_outline_level(self, title, target_level):
        if title not in self._section_order:
            return False

        try:
            target_level = int(target_level)
        except Exception:
            return False
        target_level = max(1, min(target_level, 3))

        current_level = self._section_levels.get(title, self._infer_outline_level(title))
        delta = target_level - current_level
        if delta == 0:
            return False

        subtree = self._get_section_subtree_titles(title)
        if not subtree:
            return False

        updated_levels = {}
        for candidate in subtree:
            candidate_level = self._section_levels.get(candidate, self._infer_outline_level(candidate))
            next_level = candidate_level + delta
            if next_level < 1 or next_level > 3:
                messagebox.showwarning(
                    '提示',
                    '调整后会超出当前支持的三级大纲范围，请先调整下级标题。',
                    parent=self.frame,
                )
                return False
            updated_levels[candidate] = next_level

        for candidate, next_level in updated_levels.items():
            self._section_levels[candidate] = next_level

        self._infer_section_relationships_from_order()
        self._collapsed_sections = {
            candidate
            for candidate in self._collapsed_sections
            if self._section_children.get(candidate)
        }
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()
        self._select_section(title, touch_context=False)
        self._touch_context_revision()
        self._schedule_workspace_state_save()
        self.set_status('已调整大纲级别')
        return True

    def _move_section_to_target(self, moving_title, target_title, place_after=False):
        if moving_title == target_title:
            return False
        if moving_title not in self._section_order or target_title not in self._section_order:
            return False

        moving_level = self._section_levels.get(moving_title, self._infer_outline_level(moving_title))
        target_level = self._section_levels.get(target_title, self._infer_outline_level(target_title))
        moving_parent = self._section_parent.get(moving_title, '')
        target_parent = self._section_parent.get(target_title, '')
        if moving_level != target_level or moving_parent != target_parent:
            return False

        moving_block = self._get_section_subtree_titles(moving_title)
        if target_title in moving_block:
            return False

        target_block = self._get_section_subtree_titles(target_title)
        moving_start = self._section_order.index(moving_title)
        target_start = self._section_order.index(target_title)

        remaining_order = [title for title in self._section_order if title not in moving_block]
        if place_after:
            last_target = target_block[-1]
            insert_index = remaining_order.index(last_target) + 1
        else:
            insert_index = remaining_order.index(target_title)

        self._section_order = remaining_order[:insert_index] + moving_block + remaining_order[insert_index:]
        if moving_start != target_start:
            self._sync_outline_text_from_sections()
            self._refresh_outline_list()
            self._select_section(moving_title, touch_context=False)
            self._touch_context_revision()
            self._schedule_workspace_state_save()
        return True

    def _rebuild_section_children(self):
        self._section_children = {title: [] for title in self._section_order}
        for title in self._section_order:
            parent = self._section_parent.get(title, '')
            if parent in self._section_children:
                self._section_children[parent].append(title)

    def _infer_section_relationships_from_order(self):
        stack = []
        self._section_parent = {}
        for title in self._section_order:
            level = self._section_levels.get(title, self._infer_outline_level(title))
            while stack and stack[-1][1] >= level:
                stack.pop()
            self._section_parent[title] = stack[-1][0] if stack else ''
            stack.append((title, level))
        self._rebuild_section_children()

    def _get_visible_section_titles(self):
        visible = []
        for title in self._section_order:
            if self._is_section_visible(title):
                visible.append(title)
        return visible

    def _is_section_visible(self, title):
        parent = self._section_parent.get(title, '')
        while parent:
            if parent in self._collapsed_sections:
                return False
            parent = self._section_parent.get(parent, '')
        return True

    def _outline_font_for_level(self, level):
        level_key = {1: 'h1', 2: 'h2', 3: 'h3'}.get(max(1, int(level or 1)), 'body')
        style = self._level_font_styles.get(level_key, self.LEVEL_STYLE_DEFAULTS.get(level_key, {}))
        family = style.get('font', self.LEVEL_STYLE_DEFAULTS.get(level_key, {}).get('font', '宋体'))
        size = max(8, int(style.get('size_pt', self.LEVEL_STYLE_DEFAULTS.get(level_key, {}).get('size_pt', 12))))
        weight = 'bold' if level_key in {'h1', 'h2'} else 'normal'
        font_key = (level_key, family, size, weight)
        cached = self._outline_level_fonts.get(font_key)
        if cached is not None:
            return cached
        font = tkfont.Font(root=self.frame, family=family, size=size, weight=weight)
        self._outline_level_fonts[font_key] = font
        return font

    def _set_outline_row_visual(self, title, hovered=False):
        row_info = getattr(self, '_outline_row_widgets', {}).get(title)
        if not row_info:
            return

        selected = bool(getattr(self, '_outline_selected', None) and self._outline_selected.get() == title)
        bg = COLORS['primary'] if selected else COLORS['primary_light'] if hovered else COLORS['surface_alt']
        fg = '#FFFFFF' if selected else COLORS['text_main']
        toggle_fg = '#FFFFFF' if selected else COLORS['text_sub']

        row_info['row'].configure(bg=bg)
        row_info['title'].configure(bg=bg, fg=fg)
        row_info['toggle'].configure(bg=bg, fg=toggle_fg)
        if row_info['show_toggle']:
            row_info['toggle'].configure(text='▸' if title in self._collapsed_sections else '▾')

    def _toggle_outline_branch(self, title):
        if title in self._collapsed_sections:
            self._collapsed_sections.remove(title)
        else:
            self._collapsed_sections.add(title)
        self._refresh_outline_list()
        self._select_record_in_outline_if_visible(title)
        self._schedule_workspace_state_save()

    def _select_record_in_outline_if_visible(self, title):
        if title not in getattr(self, '_outline_row_widgets', {}):
            return
        self._set_outline_row_visual(title)

    def _ensure_section_visible_in_outline(self, title):
        changed = False
        parent = self._section_parent.get(title, '')
        while parent:
            if parent in self._collapsed_sections:
                self._collapsed_sections.remove(parent)
                changed = True
            parent = self._section_parent.get(parent, '')
        if changed:
            self._refresh_outline_list()

    def _scroll_outline_selection_into_view(self, title):
        row_info = getattr(self, '_outline_row_widgets', {}).get(title)
        if not row_info:
            return

        self._outline_canvas.update_idletasks()
        row = row_info['row']
        row_top = row.winfo_y()
        row_bottom = row_top + max(row.winfo_height(), 1)
        canvas_top = self._outline_canvas.canvasy(0)
        canvas_height = max(self._outline_canvas.winfo_height(), 1)
        canvas_bottom = canvas_top + canvas_height
        content_height = max(self._outline_list.winfo_height(), 1)

        if row_top < canvas_top:
            self._outline_canvas.yview_moveto(max(row_top / content_height, 0))
        elif row_bottom > canvas_bottom:
            target_top = max(row_bottom - canvas_height, 0)
            self._outline_canvas.yview_moveto(min(target_top / content_height, 1))

    def _section_has_displayable_content(self, title):
        section = str(title or '').strip()
        if not section:
            return False
        blocks = self._section_blocks.get(section, [])
        if isinstance(blocks, list) and blocks:
            return True
        return bool(self._normalize_section_body(self._sections.get(section, '')))

    def _find_first_displayable_descendant(self, title):
        section = str(title or '').strip()
        if not section:
            return ''
        for child in self._section_children.get(section, []):
            if self._section_has_displayable_content(child):
                return child
            descendant = self._find_first_displayable_descendant(child)
            if descendant:
                return descendant
        return ''

    def _resolve_editor_display_source(self, title):
        section = str(title or '').strip()
        if not section or section not in self._sections:
            return section
        if self._section_has_displayable_content(section):
            return section
        return self._find_first_displayable_descendant(section) or section

    def _load_section_into_editor(self, source_title):
        content = self._normalize_section_body(self._sections.get(source_title, ''))
        self._editor_section_source = source_title
        self._set_editor_content(
            content,
            self._section_formats.get(source_title, []),
            reset_undo=True,
            blocks=self._get_section_blocks(source_title),
        )
        self._apply_level_font_to_editor()

    def _cancel_outline_drag_job(self):
        if not self._outline_drag_job:
            return
        try:
            self.frame.after_cancel(self._outline_drag_job)
        except Exception:
            pass
        self._outline_drag_job = None

    def _on_outline_press(self, title, event=None):
        if self._outline_editing_title:
            return 'break'
        self._cancel_outline_drag_job()
        self._outline_drag_data = {
            'title': title,
            'start_y_root': getattr(event, 'y_root', 0),
            'armed': False,
            'dragging': False,
            'target': title,
            'place_after': False,
        }
        self._outline_drag_job = self.frame.after(260, lambda t=title: self._arm_outline_drag(t))
        return 'break'

    def _arm_outline_drag(self, title):
        self._outline_drag_job = None
        if not self._outline_drag_data or self._outline_drag_data.get('title') != title:
            return
        self._outline_drag_data['armed'] = True

    def _find_outline_drop_target(self, moving_title, y_root):
        moving_level = self._section_levels.get(moving_title, self._infer_outline_level(moving_title))
        moving_parent = self._section_parent.get(moving_title, '')
        candidates = []
        for title, row_info in getattr(self, '_outline_row_widgets', {}).items():
            if title == moving_title:
                continue
            if self._section_levels.get(title, self._infer_outline_level(title)) != moving_level:
                continue
            if self._section_parent.get(title, '') != moving_parent:
                continue
            row = row_info['row']
            top = row.winfo_rooty()
            height = max(row.winfo_height(), 1)
            mid = top + height / 2
            bottom = top + height
            candidates.append((title, top, mid, bottom))

        if not candidates:
            return '', False

        for title, top, mid, bottom in candidates:
            if top <= y_root <= bottom:
                return title, y_root >= mid

        target, _top, mid, _bottom = min(candidates, key=lambda item: abs(item[2] - y_root))
        return target, y_root >= mid

    def _on_outline_motion(self, title, event=None):
        if not self._outline_drag_data or self._outline_drag_data.get('title') != title:
            return 'break'
        if not self._outline_drag_data.get('armed'):
            return 'break'

        delta = abs(getattr(event, 'y_root', 0) - self._outline_drag_data.get('start_y_root', 0))
        if delta < 4 and not self._outline_drag_data.get('dragging'):
            return 'break'

        self._outline_drag_data['dragging'] = True
        target, place_after = self._find_outline_drop_target(title, getattr(event, 'y_root', 0))
        if target:
            self._outline_drag_data['target'] = target
            self._outline_drag_data['place_after'] = place_after
        return 'break'

    def _finish_outline_drag(self):
        self._cancel_outline_drag_job()
        data = self._outline_drag_data or {}
        self._outline_drag_data = None
        return data

    def _on_outline_release(self, title, event=None):
        if self._outline_editing_title == title:
            return 'break'
        data = self._finish_outline_drag()
        if not data or data.get('title') != title:
            return 'break'

        if data.get('dragging') and data.get('target'):
            if self._move_section_to_target(title, data['target'], place_after=data.get('place_after', False)):
                self.set_status('已调整标题顺序')
                return 'break'

        self._select_section(title)
        return 'break'

    def _show_outline_context_menu(self, title, event=None):
        self._outline_context_title = title
        menu = tk.Menu(self.frame, tearoff=0)

        for label, position in (('在上方插入标题', 'above'), ('在下方插入标题', 'below')):
            sub_menu = tk.Menu(menu, tearoff=0)
            sub_menu.add_command(label='一级标题', command=lambda t=title, p=position: self._insert_outline_title(t, p, 1))
            sub_menu.add_command(label='二级标题', command=lambda t=title, p=position: self._insert_outline_title(t, p, 2))
            sub_menu.add_command(label='三级标题', command=lambda t=title, p=position: self._insert_outline_title(t, p, 3))
            menu.add_cascade(label=label, menu=sub_menu)

        menu.add_separator()
        level_menu = tk.Menu(menu, tearoff=0)
        level_menu.add_command(label='一级标题', command=lambda t=title: self._change_outline_level(t, 1))
        level_menu.add_command(label='二级标题', command=lambda t=title: self._change_outline_level(t, 2))
        level_menu.add_command(label='三级标题', command=lambda t=title: self._change_outline_level(t, 3))
        menu.add_cascade(label='调整大纲级别', menu=level_menu)

        menu.add_separator()
        send_menu = tk.Menu(menu, tearoff=0)
        send_menu.add_command(label='降AI检测', command=lambda t=title: self._send_outline_section_to_page(t, 'ai_reduce', '降AI检测'))
        send_menu.add_command(label='降查重率', command=lambda t=title: self._send_outline_section_to_page(t, 'plagiarism', '降查重率'))
        send_menu.add_command(label='学术润色', command=lambda t=title: self._send_outline_section_to_page(t, 'polish', '学术润色'))
        send_menu.add_command(label='智能纠错', command=lambda t=title: self._send_outline_section_to_page(t, 'correction', '智能纠错'))
        menu.add_cascade(label='发送', menu=send_menu)
        menu.add_separator()
        menu.add_command(label='重命名标题', command=lambda t=title: self._begin_outline_title_edit(t))
        menu.add_command(label='删除', command=lambda t=title: self._delete_outline_title(t))

        try:
            menu.tk_popup(getattr(event, 'x_root', 0), getattr(event, 'y_root', 0))
        finally:
            menu.grab_release()
        return 'break'

    def _begin_outline_title_edit(self, title):
        row_info = getattr(self, '_outline_row_widgets', {}).get(title)
        if not row_info:
            return
        if self._outline_editing_title and self._outline_editing_title != title:
            self._cancel_outline_title_edit(self._outline_editing_title)
            row_info = getattr(self, '_outline_row_widgets', {}).get(title)
            if not row_info:
                return

        existing = row_info.get('editor')
        if existing and existing.winfo_exists():
            existing.focus_set()
            existing.select_range(0, tk.END)
            return

        title_label = row_info['title']
        title_label.pack_forget()
        entry = tk.Entry(
            row_info['row'],
            font=self._outline_font_for_level(row_info['level']),
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['primary'],
        )
        entry.insert(0, self._editable_title_text(title))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6), pady=4, ipady=3)
        entry.focus_set()
        entry.select_range(0, tk.END)
        entry.bind('<Return>', lambda _event, t=title: self._commit_outline_title_edit(t))
        entry.bind('<Escape>', lambda _event, t=title: self._cancel_outline_title_edit(t))
        entry.bind('<FocusOut>', lambda _event, t=title: self._commit_outline_title_edit(t))
        row_info['editor'] = entry
        self._outline_editing_title = title

    def _cancel_outline_title_edit(self, title):
        row_info = getattr(self, '_outline_row_widgets', {}).get(title)
        if not row_info:
            self._outline_editing_title = ''
            return

        entry = row_info.pop('editor', None)
        if entry and entry.winfo_exists():
            entry.destroy()
        row_info['title'].pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=6)
        self._outline_editing_title = ''

    def _commit_outline_title_edit(self, title):
        row_info = getattr(self, '_outline_row_widgets', {}).get(title)
        if not row_info:
            self._outline_editing_title = ''
            return

        entry = row_info.get('editor')
        if not entry or not entry.winfo_exists():
            self._outline_editing_title = ''
            return

        new_text = entry.get().strip()
        self._cancel_outline_title_edit(title)
        if not new_text:
            return
        self._rename_section_title(title, self._format_title_for_level(title, new_text))

    def _refresh_outline_list(self):
        """重建左侧大纲按钮列表"""
        previous_selected = ''
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            previous_selected = self._outline_selected.get().strip()
        for w in self._outline_list.winfo_children():
            w.destroy()
        self._outline_empty_label = None
        self._outline_row_widgets = {}

        if not self._section_order:
            self._outline_empty_label = tk.Label(
                self._outline_list,
                text='暂无大纲，请导入文件或生成大纲',
                font=FONTS['small'],
                fg=COLORS['text_muted'],
                bg=COLORS['surface_alt'],
                wraplength=220,
                justify='left',
                anchor='w',
            )
            self._outline_empty_label.pack(fill=tk.X, pady=20, padx=10)
            self.frame.after_idle(self._sync_outline_list_width)
            return

        self._outline_selected = tk.StringVar(value=previous_selected if previous_selected in self._section_order else '')
        for title in self._get_visible_section_titles():
            level = max(1, int(self._section_levels.get(title, self._infer_outline_level(title)) or 1))
            row = tk.Frame(self._outline_list, bg=COLORS['surface_alt'], cursor='hand2')
            row.pack(fill=tk.X)

            indent = 8 + max(level - 1, 0) * 18
            branch = self._section_children.get(title, [])
            show_toggle = bool(branch)
            toggle_text = '▸' if title in self._collapsed_sections else '▾'
            toggle = tk.Label(
                row,
                text=toggle_text if show_toggle else ' ',
                font=FONTS['body_bold'],
                fg=COLORS['text_sub'],
                bg=COLORS['surface_alt'],
                width=2,
                anchor='center',
                cursor='hand2' if show_toggle else 'arrow',
            )
            toggle.pack(side=tk.LEFT, padx=(indent, 0))

            title_label = tk.Label(
                row,
                text=title,
                font=self._outline_font_for_level(level),
                fg=COLORS['text_main'],
                bg=COLORS['surface_alt'],
                anchor='w',
                cursor='hand2',
                wraplength=220,
                justify='left',
                padx=6,
                pady=6,
            )
            title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._bind_outline_mousewheel(row)
            self._bind_outline_mousewheel(toggle)
            self._bind_outline_mousewheel(title_label)

            if show_toggle:
                toggle.bind('<Button-1>', lambda e, t=title: self._toggle_outline_branch(t))
            for widget in (row, title_label):
                widget.bind('<Enter>', lambda e, t=title: self._set_outline_row_visual(t, hovered=True))
                widget.bind('<Leave>', lambda e, t=title: self._set_outline_row_visual(t, hovered=False))
                widget.bind('<ButtonPress-1>', lambda e, t=title: self._on_outline_press(t, e))
                widget.bind('<B1-Motion>', lambda e, t=title: self._on_outline_motion(t, e))
                widget.bind('<ButtonRelease-1>', lambda e, t=title: self._on_outline_release(t, e))
                widget.bind('<Double-Button-1>', lambda e, t=title: self._begin_outline_title_edit(t))
                widget.bind('<Button-3>', lambda e, t=title: self._show_outline_context_menu(t, e))

            self._outline_row_widgets[title] = {
                'row': row,
                'toggle': toggle,
                'title': title_label,
                'level': level,
                'show_toggle': show_toggle,
                'editor': None,
            }
            self._set_outline_row_visual(title)

        self._outline_canvas.yview_moveto(0)
        self.frame.after_idle(self._sync_outline_list_width)

    def _display_section(self, title, touch_context=True):
        self._ensure_section_visible_in_outline(title)
        self._outline_selected.set(title)
        for candidate in list(getattr(self, '_outline_row_widgets', {}).keys()):
            self._set_outline_row_visual(candidate)
        display_source = self._resolve_editor_display_source(title)
        self.section_entry.delete(0, tk.END)
        self.section_entry.insert(0, display_source or title)
        self._load_section_into_editor(display_source)
        self.frame.after_idle(lambda target=title: self._scroll_outline_selection_into_view(target))
        if touch_context:
            self._touch_context_revision()
        self._update_stats()
        self.frame.after_idle(self._capture_selection_snapshot)

    def _select_section(self, title, touch_context=True):
        """点击标题时，仅显示该标题对应的正文内容。"""
        self._store_current_editor_content()
        self._display_section(title, touch_context=touch_context)

    def _new_doc(self):
        if not messagebox.askyesno(
            '新建空白',
            '此操作会清空当前论文写作页面的全部内容，包括写作设置、论文大纲、所有章节正文与当前编辑区内容。\n\n确定继续吗？',
            parent=self.frame,
        ):
            return

        self.topic_entry.delete(0, tk.END)
        self.style_var.set('学术论文')
        self.subject_entry.delete(0, tk.END)
        self.ref_var.set('GB/T 7714')
        self.wcount_var.set('1000')

        self.outline_text.delete('1.0', tk.END)
        self._sections = {}
        self._section_blocks = {}
        self._section_formats = {}
        self._section_order = []
        self._section_levels = {}
        self._section_parent = {}
        self._section_children = {}
        self._collapsed_sections = set()
        if hasattr(self, '_outline_selected') and self._outline_selected is not None:
            self._outline_selected.set('')
        self._refresh_outline_list()

        self._clear_editor_block_widgets()
        self.edit_text.delete('1.0', tk.END)
        self.section_entry.delete(0, tk.END)
        self._editor_section_source = ''
        self._editor_bg_indicator_color = self.DEFAULT_BG_SWATCH_COLOR
        self._refresh_editor_toolbar_icons()
        self._snapshots = []
        self._selection_snapshot = None
        self._reset_editor_undo_stack()
        self._touch_context_revision()
        self._schedule_workspace_state_save()
        self.set_status('已新建空白文档，整页内容已清空')
        self._update_stats()

    def on_show(self):
        for shell in self._fixed_primary_shell_buttons:
            refresh_home_shell_button(shell)
        self._refresh_editor_selection_style()
        self._refresh_editor_toolbar_icons()

    def _snapshot_has_meaningful_content(self, state):
        if not isinstance(state, dict):
            return False

        text_fields = [
            state.get('topic', ''),
            state.get('subject', ''),
            state.get('outline_text', ''),
            state.get('current_section', ''),
            state.get('editor_text', ''),
        ]
        if any(str(value or '').strip() for value in text_fields):
            return True

        sections = state.get('sections', {})
        if isinstance(sections, dict):
            for title, content in sections.items():
                if str(title or '').strip() or str(content or '').strip():
                    return True

        return False

    def _build_snapshot_record(self, state, ts):
        snapshot_state = dict(state or {})
        snapshot_state['snapshots'] = []

        sections = snapshot_state.get('sections', {})
        section_count = len(sections) if isinstance(sections, dict) else 0
        topic = str(snapshot_state.get('topic', '') or '').strip()
        current_section = str(snapshot_state.get('current_section', '') or '').strip()

        summary_parts = ['已保存完整工作区快照']
        if topic:
            summary_parts.append(f'标题：{topic}')
        if current_section:
            summary_parts.append(f'当前章节：{current_section}')
        if section_count:
            summary_parts.append(f'章节数：{section_count}')

        return {
            'time': ts,
            'topic': topic,
            'current_section': current_section,
            'section_count': section_count,
            'summary': ' | '.join(summary_parts),
            'workspace_state': snapshot_state,
        }

    @staticmethod
    def _build_full_document_text(state):
        if not isinstance(state, dict):
            return ''
        section_order = state.get('section_order', [])
        sections = state.get('sections', {})
        section_blocks = state.get('section_blocks', {})
        if not isinstance(sections, dict) or not sections:
            return ''
        parts = []
        for title in (section_order or list(sections.keys())):
            body = ''
            if isinstance(section_blocks, dict):
                body = blocks_to_plain_text(section_blocks.get(title, []))
            if not body:
                body = str(sections.get(title, '') or '').strip()
            if title.strip():
                parts.append(title.strip())
            if body:
                parts.append(body)
            parts.append('')
        return '\n'.join(parts).strip()

    def _save_snapshot(self):
        state = self.capture_workspace_state_snapshot(save_to_disk=False)
        if not self._snapshot_has_meaningful_content(state):
            messagebox.showwarning('提示', '当前页面还没有可保存的内容', parent=self.frame)
            return
        import datetime
        now = datetime.datetime.now()
        ts = now.strftime('%H:%M:%S')
        full_ts = now.strftime('%Y-%m-%d %H:%M:%S')
        snapshot = self._build_snapshot_record(state, ts)
        self._snapshots.append(snapshot)
        self.save_workspace_state_now(save_to_disk=True)

        if self.history:
            snapshot_state = snapshot.get('workspace_state', {})
            topic = snapshot.get('topic') or self.topic_entry.get().strip()
            full_text = self._build_full_document_text(snapshot_state)
            outline_text = str(snapshot_state.get('outline_text', '') or '').strip()
            section_count = snapshot.get('section_count', 0)

            self.history.add(
                '保存快照',
                topic or '论文写作快照',
                full_text or snapshot.get('summary', '已保存完整工作区快照'),
                MODULE_PAPER_WRITE,
                extra={
                    'paper_title': topic,
                    'topic': snapshot.get('current_section', ''),
                    'snapshot_time': full_ts,
                    'snapshot_type': 'workspace',
                    'section_count': section_count,
                    'outline_summary': outline_text[:200] if outline_text else '',
                    'style': str(snapshot_state.get('style', '') or '').strip(),
                    'subject': str(snapshot_state.get('subject', '') or '').strip(),
                    'reference_style': str(snapshot_state.get('reference_style', '') or '').strip(),
                },
                page_state_id=self.PAGE_STATE_ID,
                workspace_state=snapshot_state,
            )

        self.set_status(f'完整快照已保存 [{ts}]，共 {len(self._snapshots)} 个')
        messagebox.showinfo(
            '快照已保存',
            f'已保存完整工作区快照 [{ts}]\n'
            f'包含写作设置、大纲、所有章节内容与格式样式\n'
            f'当前共 {len(self._snapshots)} 个快照',
            parent=self.frame,
        )

    def _open_prompt_manager(self):
        if not self.app_bridge:
            return
        self.app_bridge.show_prompt_manager(page_id='paper_write', compact=True)

    def _ensure_prompt_ready(self, scene_id):
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return False
        if self.prompt_center.scene_has_active_prompt(scene_id):
            return True
        messagebox.showwarning('提示', '当前页面没有可用的提示词，请先创建或选择一条提示词。', parent=self.frame)
        if self.app_bridge:
            self.app_bridge.show_prompt_manager(page_id='paper_write', compact=True, scene_id=scene_id)
        return False

    def _resolve_section_existing_content(self, section):
        section = (section or '').strip()
        if not section:
            return ''
        if self._editor_section_source == section or self.section_entry.get().strip() == section:
            return self._get_current_editor_text()
        return self._normalize_section_body(self._sections.get(section, ''))

    def _resolve_section_existing_formats(self, section):
        section = (section or '').strip()
        if not section:
            return []
        if self._editor_section_source == section:
            return self._serialize_editor_format_spans()
        return self._copy_section_formats(section)

    def _apply_written_section_result(
        self,
        section,
        result,
        *,
        existing_text='',
        existing_formats=None,
        set_display=True,
        write_mode='replace',
    ):
        section = (section or '').strip()
        if not section:
            raise ValueError('章节名称不能为空')

        existing = self._normalize_section_body(existing_text)
        if existing_formats is None:
            existing_formats = self._resolve_section_existing_formats(section)
        existing_formats = [dict(span) for span in (existing_formats or [])]

        reference_section_title = ''
        clean_result = ''
        display_section = section
        self._ensure_section_registered(section)

        if self._is_reference_section_title(section):
            references_text = self._normalize_section_body(self._strip_reference_heading(result))
            clean_result = references_text
            merged = self._normalize_section_body(self._sections.get(section, ''))
            merged_formats = self._copy_section_formats(section)
            if references_text:
                reference_section_title = self._write_references_to_section(references_text)
                merged = self._normalize_section_body(self._sections.get(reference_section_title, ''))
                merged_formats = self._copy_section_formats(reference_section_title)
                display_section = reference_section_title
            self._sections[display_section] = merged
            blocks = self._blocks_from_section_text(merged)
            if blocks:
                self._section_blocks[display_section] = blocks
            else:
                self._section_blocks.pop(display_section, None)
            self._section_formats[display_section] = merged_formats
        else:
            clean_result, references_text = self._extract_references_from_section_result(result)
            should_sync_numeric_references = (
                self._supports_numeric_reference_linking()
                and (
                    bool(references_text)
                    or bool(self._find_reference_section_title())
                    or bool(re.search(r'\[[^\[\]]+\]', existing))
                    or bool(re.search(r'\[[^\[\]]+\]', clean_result))
                )
            )
            if should_sync_numeric_references:
                merged, merged_formats, reference_section_title = self._sync_document_references_after_section_write(
                    section,
                    existing,
                    clean_result,
                    references_text,
                    existing_formats=existing_formats,
                    write_mode=write_mode,
                )
            else:
                merged_blocks = self._compose_section_blocks(section, existing, clean_result, write_mode=write_mode)
                merged = blocks_to_plain_text(merged_blocks)
                merged_formats = self._preserve_existing_formats(
                    section,
                    existing,
                    merged,
                    source_spans=existing_formats,
                ) if not any(block.get('type') == 'table' for block in merged_blocks) else []
                self._set_section_blocks(section, merged_blocks)
                self._section_formats[section] = merged_formats
                if references_text:
                    reference_section_title = self._write_references_to_section(references_text)

        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()

        if set_display:
            current_display = self._editor_section_source or self.section_entry.get().strip()
            if current_display and current_display != display_section:
                self._store_current_editor_content()
            self._display_section(display_section, touch_context=False)
        else:
            self._update_stats()
            self.frame.after_idle(self._capture_selection_snapshot)

        self._touch_context_revision()
        self._add_history_version(
            '写作章节',
            section,
            clean_result,
            extra={
                'paper_title': self.topic_entry.get().strip() or section,
                'references_section': reference_section_title,
            },
        )
        self._schedule_workspace_state_save()
        return {
            'section': section,
            'display_section': display_section,
            'clean_result': clean_result,
            'reference_section_title': reference_section_title,
        }

    def _get_batch_write_scope_mode(self):
        choice = messagebox.askyesnocancel(
            '写所有章节',
            '请选择本次批量生成范围：\n\n'
            '是：只写空白章节\n'
            '否：写全部章节\n'
            '取消：不执行',
            parent=self.frame,
        )
        if choice is None:
            return ''
        return 'empty_only' if choice else 'all'

    def _collect_batch_write_targets(self, scope_mode):
        self._normalize_outline_structure_state()
        self._rebuild_section_children()

        targets = []
        for title in self._section_order:
            if self._is_reference_section_title(title):
                continue
            if self._section_children.get(title):
                continue

            existing_text = self._resolve_section_existing_content(title)
            if scope_mode == 'empty_only' and existing_text:
                continue

            targets.append(
                {
                    'section': title,
                    'existing_text': existing_text,
                    'existing_formats': self._copy_section_formats(title),
                }
            )
        return targets

    def _confirm_batch_write_warning(self, targets, word_count):
        target_count = len(targets)
        total_words = max(0, int(word_count or 0)) * target_count
        warnings = []

        if int(word_count or 0) > self.BATCH_WRITE_WARNING_SECTION_WORDS:
            warnings.append(
                f'当前目标字数为 {word_count} 字，单章节篇幅偏长。'
            )
        if target_count > self.BATCH_WRITE_WARNING_SECTION_COUNT:
            warnings.append(
                f'本次计划生成 {target_count} 个章节，批量范围较大。'
            )
        if total_words > self.BATCH_WRITE_WARNING_TOTAL_WORDS:
            warnings.append(
                f'按当前设置估算，总目标字数约为 {total_words} 字。'
            )

        if not warnings:
            return True

        message = (
            f'本次计划生成 {target_count} 个章节，按每章约 {word_count} 字估算，总目标约 {total_words} 字。\n\n'
            + '\n'.join(warnings)
            + '\n\n可能遇到额度不足或单次生成过长，建议分批生成。\n\n是否仍继续本次批量生成？'
        )
        return bool(messagebox.askyesno('建议分批生成', message, parent=self.frame))

    @staticmethod
    def _classify_batch_write_error(error_text):
        lowered = str(error_text or '').lower()
        length_keywords = (
            'context_length_exceeded',
            'context length',
            'too many tokens',
            'max_tokens',
            'maximum context',
            '上下文长度',
            '长度超限',
            '输入过长',
            '超长',
        )
        quota_keywords = (
            'insufficient_quota',
            'quota',
            'rate limit',
            'too many requests',
            '429',
            '额度',
            '余额',
            '频率限制',
            '请求过于频繁',
            'credit',
        )
        if any(keyword in lowered for keyword in length_keywords):
            return 'length'
        if any(keyword in lowered for keyword in quota_keywords):
            return 'quota'
        return 'generic'

    def _show_batch_write_failure(self, result):
        failed_section = str(result.get('failed_section', '') or '').strip()
        completed_sections = list(result.get('completed_sections', []) or [])
        remaining_sections = list(result.get('remaining_sections', []) or [])
        error_text = str(result.get('error_message', '') or '').strip()
        error_type = str(result.get('error_type', 'generic') or 'generic').strip()

        if error_type == 'quota':
            reason_text = '检测到额度不足或频率限制，建议缩小范围后分批生成。'
            dialog = messagebox.showwarning
        elif error_type == 'length':
            reason_text = '检测到单次生成过长或上下文超长，建议降低目标字数后分批生成。'
            dialog = messagebox.showwarning
        else:
            reason_text = '批量写作过程中发生错误，后续章节未继续执行。'
            dialog = messagebox.showerror

        remaining_preview = ''
        if remaining_sections:
            preview_items = remaining_sections[:8]
            remaining_preview = '\n'.join(preview_items)
            if len(remaining_sections) > len(preview_items):
                remaining_preview += f'\n……还有 {len(remaining_sections) - len(preview_items)} 个章节'

        message = (
            f'失败章节：{failed_section or "未确定"}\n'
            f'已完成章节数：{len(completed_sections)}\n'
            f'剩余章节数：{len(remaining_sections)}\n\n'
            f'{reason_text}'
        )
        if remaining_preview:
            message += f'\n\n剩余章节：\n{remaining_preview}'
        if error_text:
            message += f'\n\n错误信息：\n{error_text[:500]}'

        self.set_status(f'批量写作已中止：{failed_section or "执行失败"}', COLORS['error'])
        dialog('批量写作已中止', message, parent=self.frame)

    def _run_on_ui_thread_sync(self, callback):
        event = threading.Event()
        payload = {}

        def runner():
            try:
                payload['result'] = callback()
            except Exception as exc:
                payload['error'] = exc
            finally:
                event.set()

        self.frame.after(0, runner)
        event.wait()
        if payload.get('error') is not None:
            raise payload['error']
        return payload.get('result')

    def _prepare_batch_section_write_inputs(self, section, index, total):
        self.set_status(
            f'正在写第 {index}/{total} 节：{section}',
            COLORS['warning'],
        )
        self._select_section(section, touch_context=False)
        return {
            'outline': self.outline_text.get('1.0', tk.END).strip(),
            'existing_text': self._resolve_section_existing_content(section),
            'existing_formats': self._resolve_section_existing_formats(section),
            'word_count': int(self.wcount_var.get() or '1000'),
            'reference_style': self.ref_var.get(),
        }

    def _run_batch_write_task(self, targets, outline, word_count, reference_style):
        total = len(targets)
        completed_sections = []

        for index, item in enumerate(targets, start=1):
            section = item.get('section', '')
            try:
                write_inputs = self._run_on_ui_thread_sync(
                    lambda title=section, current=index, overall=total: self._prepare_batch_section_write_inputs(
                        title,
                        current,
                        overall,
                    )
                )
            except Exception as exc:
                error_message = str(exc)
                return {
                    'ok': False,
                    'failed_section': section,
                    'completed_sections': completed_sections,
                    'remaining_sections': [entry.get('section', '') for entry in targets[index - 1:]],
                    'error_type': 'generic',
                    'error_message': error_message,
                }

            try:
                result = self.writer.write_section(
                    write_inputs.get('outline', outline or ''),
                    section,
                    write_inputs.get('existing_text', ''),
                    write_inputs.get('word_count', word_count),
                    write_inputs.get('reference_style', reference_style),
                )
            except Exception as exc:
                error_message = str(exc)
                return {
                    'ok': False,
                    'failed_section': section,
                    'completed_sections': completed_sections,
                    'remaining_sections': [entry.get('section', '') for entry in targets[index - 1:]],
                    'error_type': self._classify_batch_write_error(error_message),
                    'error_message': error_message,
                }

            try:
                self._run_on_ui_thread_sync(
                    lambda title=section, response=result, current=index, overall=total, payload=write_inputs: (
                        self._apply_written_section_result(
                            title,
                            response,
                            existing_text=payload.get('existing_text', ''),
                            existing_formats=payload.get('existing_formats', []),
                            set_display=True,
                            write_mode='replace',
                        ),
                        self.set_status(
                            f'已完成第 {current}/{overall} 节：{title}',
                            COLORS['warning'] if current < overall else COLORS['info'],
                        ),
                    )
                )
            except Exception as exc:
                error_message = str(exc)
                return {
                    'ok': False,
                    'failed_section': section,
                    'completed_sections': completed_sections,
                    'remaining_sections': [entry.get('section', '') for entry in targets[index - 1:]],
                    'error_type': 'generic',
                    'error_message': error_message,
                }

            completed_sections.append(section)

        return {
            'ok': True,
            'completed_sections': completed_sections,
            'completed_count': len(completed_sections),
        }

    def _write_all_sections(self):
        self._store_current_editor_content()
        self._normalize_outline_structure_state()
        self._rebuild_section_children()
        self._sync_outline_text_from_sections()
        self._refresh_outline_list()

        outline = self.outline_text.get('1.0', tk.END).strip()
        if not outline or not self._section_order:
            messagebox.showwarning('提示', '请先生成或导入论文大纲', parent=self.frame)
            return
        if not self._ensure_prompt_ready('paper_write.section'):
            return

        scope_mode = self._get_batch_write_scope_mode()
        if not scope_mode:
            return

        targets = self._collect_batch_write_targets(scope_mode)
        if not targets:
            if scope_mode == 'empty_only':
                message = '当前叶子章节都已有正文，没有可批量生成的空白章节。'
            else:
                message = '当前大纲没有可批量写作的叶子章节。'
            messagebox.showwarning('提示', message, parent=self.frame)
            return

        word_count = int(self.wcount_var.get() or '1000')
        if not self._confirm_batch_write_warning(targets, word_count):
            return

        reference_style = self.ref_var.get()

        def on_success(result):
            if not result.get('ok'):
                self._show_batch_write_failure(result)
                return
            completed_count = int(result.get('completed_count', 0) or 0)
            self.set_status(f'已完成批量写作，共生成 {completed_count} 个章节')

        def on_error(exc):
            self.set_status(f'批量写作失败：{exc}', COLORS['error'])
            messagebox.showerror('批量写作失败', str(exc), parent=self.frame)

        self.task_runner.run(
            work=lambda: self._run_batch_write_task(
                targets,
                outline,
                word_count,
                reference_style,
            ),
            on_success=on_success,
            on_error=on_error,
            loading_text='正在批量写作章节...',
            status_text=f'准备批量写作，共 {len(targets)} 节...',
            status_color=COLORS['warning'],
        )

    def _write_section(self):
        section = self.section_entry.get().strip()
        outline = self.outline_text.get('1.0', tk.END).strip()
        if not section:
            messagebox.showwarning('提示', '请输入当前章节名称', parent=self.frame)
            return
        if not self._ensure_prompt_ready('paper_write.section'):
            return
        existing = self._get_current_editor_text()
        existing_formats = self._resolve_section_existing_formats(section)

        def on_success(result):
            outcome = self._apply_written_section_result(
                section,
                result,
                existing_text=existing,
                existing_formats=existing_formats,
                write_mode='replace',
            )
            if outcome.get('reference_section_title'):
                self.set_status(f'章节写作完成，参考文献已写入 {outcome["reference_section_title"]}')
            else:
                self.set_status('章节写作完成')
            return

        def on_error(exc):
            self.set_status(f'写作失败: {exc}', COLORS['error'])

        self.task_runner.run(
            work=lambda: self.writer.write_section(
                outline,
                section,
                existing,
                int(self.wcount_var.get() or '1000'),
                self.ref_var.get(),
            ),
            on_success=on_success,
            on_error=on_error,
            loading_text='正在撰写章节...',
            status_text='正在撰写章节...',
            status_color=COLORS['warning'],
        )

    def _generate_table_block(self):
        section = self.section_entry.get().strip()
        outline = self.outline_text.get('1.0', tk.END).strip()
        if not section:
            messagebox.showwarning('提示', '请输入当前章节名称', parent=self.frame)
            return
        if not self._ensure_prompt_ready('paper_write.section'):
            return

        existing = self._get_current_editor_text()
        existing_formats = self._resolve_section_existing_formats(section)

        def on_success(result):
            outcome = self._apply_written_section_result(
                section,
                result,
                existing_text=existing,
                existing_formats=existing_formats,
                write_mode='append',
            )
            if outcome.get('reference_section_title'):
                self.set_status(f'表格已生成，参考文献已写入 {outcome["reference_section_title"]}')
            else:
                self.set_status('表格已生成并插入当前章节')

        def on_error(exc):
            self.set_status(f'表格生成失败: {exc}', COLORS['error'])

        self.task_runner.run(
            work=lambda: self.writer.generate_table(
                outline,
                section,
                existing,
                int(self.wcount_var.get() or '1000'),
                self.ref_var.get(),
            ),
            on_success=on_success,
            on_error=on_error,
            loading_text='正在生成表格...',
            status_text='正在生成表格...',
            status_color=COLORS['warning'],
        )

    def _gen_abstract(self):
        full_text = self._collect_full_text_for_abstract()
        if not full_text:
            messagebox.showwarning('提示', '请先完善论文正文内容，再生成全文摘要', parent=self.frame)
            return
        if not self._ensure_prompt_ready('paper_write.abstract'):
            return

        def on_success(result):
            formatted_result = self._format_generated_abstract(result)
            abstract_title = self._write_abstract_to_section(formatted_result)
            self._add_history_version(
                '生成摘要',
                full_text[:200],
                formatted_result,
                extra={
                    'paper_title': self.topic_entry.get().strip(),
                    'topic': abstract_title,
                },
            )
            self.set_status('摘要已生成并写入摘要区')

        def on_error(exc):
            self.set_status(f'失败: {exc}', COLORS['error'])

        self.task_runner.run(
            work=lambda: self.writer.write_abstract(full_text),
            on_success=on_success,
            on_error=on_error,
            loading_text='正在生成摘要...',
            status_text='正在生成摘要...',
            status_color=COLORS['warning'],
        )
