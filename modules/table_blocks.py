# -*- coding: utf-8 -*-
"""
表格块解析与序列化工具。
"""

from __future__ import annotations

import copy
import re
import uuid


TABLE_SEPARATOR_RE = re.compile(
    r'^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$'
)

TABLE_STYLE_GRID = 'grid'
TABLE_STYLE_THREE_LINE = 'three_line'
TABLE_STYLES = {TABLE_STYLE_GRID, TABLE_STYLE_THREE_LINE}

TABLE_ALIGN_LEFT = 'left'
TABLE_ALIGN_CENTER = 'center'
TABLE_ALIGN_RIGHT = 'right'
TABLE_ALIGNMENTS = {TABLE_ALIGN_LEFT, TABLE_ALIGN_CENTER, TABLE_ALIGN_RIGHT}


def _normalize_text(value):
    return str(value or '').replace('\r\n', '\n').replace('\r', '\n')


def normalize_paragraph_text(value):
    return _normalize_text(value).strip()


def normalize_table_cell(value):
    text = _normalize_text(value)
    text = text.replace('\n', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def normalize_table_rows(rows):
    normalized = []
    if not isinstance(rows, list):
        rows = []

    max_cols = 0
    for row in rows:
        if isinstance(row, (list, tuple)):
            normalized_row = [normalize_table_cell(cell) for cell in row]
        else:
            normalized_row = [normalize_table_cell(row)]
        max_cols = max(max_cols, len(normalized_row))
        normalized.append(normalized_row)

    if not normalized:
        return [['']]

    max_cols = max(1, max_cols)
    padded = []
    for row in normalized:
        current = list(row[:max_cols])
        if len(current) < max_cols:
            current.extend([''] * (max_cols - len(current)))
        padded.append(current)
    return padded


def normalize_table_style(value):
    style = str(value or '').strip().lower()
    return style if style in TABLE_STYLES else TABLE_STYLE_GRID


def normalize_table_alignment(value):
    alignment = str(value or '').strip().lower()
    aliases = {
        'left': TABLE_ALIGN_LEFT,
        'l': TABLE_ALIGN_LEFT,
        'start': TABLE_ALIGN_LEFT,
        '居左': TABLE_ALIGN_LEFT,
        '左': TABLE_ALIGN_LEFT,
        'center': TABLE_ALIGN_CENTER,
        'centre': TABLE_ALIGN_CENTER,
        'middle': TABLE_ALIGN_CENTER,
        'c': TABLE_ALIGN_CENTER,
        '1': TABLE_ALIGN_CENTER,
        '居中': TABLE_ALIGN_CENTER,
        '中': TABLE_ALIGN_CENTER,
        'right': TABLE_ALIGN_RIGHT,
        'r': TABLE_ALIGN_RIGHT,
        'end': TABLE_ALIGN_RIGHT,
        '2': TABLE_ALIGN_RIGHT,
        '居右': TABLE_ALIGN_RIGHT,
        '右': TABLE_ALIGN_RIGHT,
    }
    return aliases.get(alignment, TABLE_ALIGN_LEFT)


def normalize_table_alignments(cell_alignments, row_count, col_count, default=TABLE_ALIGN_LEFT):
    row_count = max(1, _int_value(row_count, 1))
    col_count = max(1, _int_value(col_count, 1))
    default_alignment = normalize_table_alignment(default)
    normalized = [[default_alignment for _col in range(col_count)] for _row in range(row_count)]
    if not isinstance(cell_alignments, list):
        return normalized

    for row_idx, raw_row in enumerate(cell_alignments[:row_count]):
        if not isinstance(raw_row, (list, tuple)):
            continue
        for col_idx, value in enumerate(raw_row[:col_count]):
            normalized[row_idx][col_idx] = normalize_table_alignment(value)
    return normalized


def normalize_table_pixel_sizes(values, count, *, min_value=1, max_value=4000):
    count = max(0, _int_value(count, 0))
    if count <= 0 or not isinstance(values, list):
        return []

    normalized = []
    has_size = False
    min_value = max(1, _int_value(min_value, 1))
    max_value = max(min_value, _int_value(max_value, 4000))
    for index in range(count):
        raw_value = values[index] if index < len(values) else 0
        size = _int_value(raw_value, 0)
        if size > 0:
            has_size = True
            normalized.append(max(min_value, min(size, max_value)))
        else:
            normalized.append(min_value)
    return normalized if has_size else []


def _table_shape(rows):
    normalized = normalize_table_rows(rows)
    row_count = len(normalized)
    col_count = max(1, len(normalized[0]) if normalized else 1)
    return normalized, row_count, col_count


def _int_value(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _merge_intersects(cell, used_cells):
    row = cell['row']
    col = cell['col']
    rowspan = cell['rowspan']
    colspan = cell['colspan']
    for row_idx in range(row, row + rowspan):
        for col_idx in range(col, col + colspan):
            if (row_idx, col_idx) in used_cells:
                return True
    return False


def _mark_merge_cells(cell, used_cells):
    row = cell['row']
    col = cell['col']
    rowspan = cell['rowspan']
    colspan = cell['colspan']
    for row_idx in range(row, row + rowspan):
        for col_idx in range(col, col + colspan):
            used_cells.add((row_idx, col_idx))


def normalize_merged_cells(merged_cells, row_count, col_count):
    row_count = max(1, _int_value(row_count, 1))
    col_count = max(1, _int_value(col_count, 1))
    if not isinstance(merged_cells, list):
        return []

    normalized = []
    used_cells = set()
    for raw_cell in merged_cells:
        if not isinstance(raw_cell, dict):
            continue
        row = _int_value(raw_cell.get('row'), -1)
        col = _int_value(raw_cell.get('col'), -1)
        rowspan = max(1, _int_value(raw_cell.get('rowspan'), 1))
        colspan = max(1, _int_value(raw_cell.get('colspan'), 1))
        if row < 0 or col < 0 or row >= row_count or col >= col_count:
            continue
        rowspan = min(rowspan, row_count - row)
        colspan = min(colspan, col_count - col)
        if rowspan <= 1 and colspan <= 1:
            continue
        cell = {
            'row': row,
            'col': col,
            'rowspan': rowspan,
            'colspan': colspan,
        }
        if _merge_intersects(cell, used_cells):
            continue
        _mark_merge_cells(cell, used_cells)
        normalized.append(cell)
    return normalized


def _pixel_value(value, default=0):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(0, number)


def _normalize_cell_widths(cell_text_widths, row_count, col_count):
    normalized = [[0 for _col in range(col_count)] for _row in range(row_count)]
    if not isinstance(cell_text_widths, list):
        return normalized
    for row_idx, raw_row in enumerate(cell_text_widths[:row_count]):
        if not isinstance(raw_row, (list, tuple)):
            continue
        for col_idx, value in enumerate(raw_row[:col_count]):
            normalized[row_idx][col_idx] = _pixel_value(value, 0)
    return normalized


def _covered_merge_cells(merged_cells):
    covered = set()
    anchors = {}
    for cell in merged_cells:
        row = cell['row']
        col = cell['col']
        anchors[(row, col)] = cell
        for row_idx in range(row, row + cell['rowspan']):
            for col_idx in range(col, col + cell['colspan']):
                if row_idx == row and col_idx == col:
                    continue
                covered.add((row_idx, col_idx))
    return covered, anchors


def _distribute_span_width(widths, start, span, target_width, per_column_max):
    end = min(len(widths), start + max(1, span))
    if start < 0 or start >= end:
        return
    current = sum(widths[start:end])
    deficit = max(0, int(target_width) - current)
    while deficit > 0:
        flexible = [
            index
            for index in range(start, end)
            if widths[index] < per_column_max
        ]
        if not flexible:
            break
        share = max(1, (deficit + len(flexible) - 1) // len(flexible))
        changed = 0
        for index in flexible:
            addition = min(share, per_column_max - widths[index], deficit - changed)
            if addition <= 0:
                continue
            widths[index] += addition
            changed += addition
            if changed >= deficit:
                break
        if changed <= 0:
            break
        deficit -= changed


def _round_widths_to_limit(widths, limit):
    rounded = [max(1, int(round(width))) for width in widths]
    if not rounded:
        return []
    limit = max(1, int(limit))
    overflow = sum(rounded) - limit
    index = len(rounded) - 1
    while overflow > 0 and any(width > 1 for width in rounded):
        if rounded[index] > 1:
            rounded[index] -= 1
            overflow -= 1
        index = (index - 1) % len(rounded)
    return rounded


def _fit_widths_to_available(min_widths, ideal_widths, available_width):
    available = max(1, _pixel_value(available_width, 1))
    if sum(ideal_widths) <= available:
        return [int(round(width)) for width in ideal_widths]

    min_total = sum(min_widths)
    if min_total >= available:
        if min_total <= 0:
            return [max(1, available // max(1, len(min_widths)))] * len(min_widths)
        scaled = [max(1, width * available / min_total) for width in min_widths]
        return _round_widths_to_limit(scaled, available)

    extra = available - min_total
    flex = [max(0, ideal - minimum) for minimum, ideal in zip(min_widths, ideal_widths)]
    flex_total = sum(flex)
    if flex_total <= 0:
        return _round_widths_to_limit(min_widths, available)

    fitted = [
        minimum + extra * flexible / flex_total
        for minimum, flexible in zip(min_widths, flex)
    ]
    return _round_widths_to_limit(fitted, available)


def calculate_table_column_widths(
    rows,
    available_width,
    *,
    cell_text_widths=None,
    merged_cells=None,
    min_width=56,
    max_width=360,
    cell_padding=24,
):
    """根据内容测量结果计算表格列宽，返回像素宽度列表。"""
    normalized, row_count, col_count = _table_shape(rows)
    min_width = max(1, _pixel_value(min_width, 56))
    max_width = max(min_width, _pixel_value(max_width, 360))
    cell_padding = _pixel_value(cell_padding, 24)
    available = max(1, _pixel_value(available_width, min_width * col_count))
    measurements = _normalize_cell_widths(cell_text_widths, row_count, col_count)
    normalized_merges = normalize_merged_cells(merged_cells or [], row_count, col_count)
    covered, anchors = _covered_merge_cells(normalized_merges)

    min_widths = [min_width for _col in range(col_count)]
    ideal_widths = [min_width for _col in range(col_count)]
    for row_idx, row in enumerate(normalized):
        for col_idx, _cell in enumerate(row[:col_count]):
            if (row_idx, col_idx) in covered:
                continue
            merged = anchors.get((row_idx, col_idx))
            colspan = int(merged.get('colspan', 1)) if merged else 1
            measured = measurements[row_idx][col_idx] + cell_padding
            if colspan <= 1:
                ideal_widths[col_idx] = max(
                    ideal_widths[col_idx],
                    min(max_width, max(min_width, measured)),
                )
                continue
            span_max = max_width * max(1, colspan)
            span_target = min(span_max, max(min_width * colspan, measured))
            _distribute_span_width(ideal_widths, col_idx, colspan, span_target, max_width)

    return _fit_widths_to_available(min_widths, ideal_widths, available)


PARAGRAPH_METADATA_KEYS = {
    'style_name',
    'style_id',
    'outline_level',
    'font_size_pt',
    'bold_ratio',
    'alignment',
    'is_toc_like',
}


def _normalize_paragraph_metadata(metadata):
    normalized = {}
    if not isinstance(metadata, dict):
        return normalized
    for key in PARAGRAPH_METADATA_KEYS:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if value in (None, ''):
            continue
        if key == 'outline_level':
            level = _int_value(value, -1)
            if level >= 0:
                normalized[key] = level
            continue
        if key == 'font_size_pt':
            try:
                size = float(value)
            except (TypeError, ValueError):
                continue
            if size > 0:
                normalized[key] = round(size, 2)
            continue
        if key == 'bold_ratio':
            try:
                ratio = float(value)
            except (TypeError, ValueError):
                continue
            normalized[key] = max(0.0, min(1.0, round(ratio, 3)))
            continue
        if key == 'is_toc_like':
            normalized[key] = bool(value)
            continue
        normalized[key] = str(value).strip()
    return normalized


def new_paragraph_block(text, **metadata):
    block = {
        'type': 'paragraph',
        'text': normalize_paragraph_text(text),
    }
    block.update(_normalize_paragraph_metadata(metadata))
    return block


def new_table_block(
    rows,
    *,
    table_id=None,
    caption='',
    has_header=True,
    merged_cells=None,
    table_style=TABLE_STYLE_GRID,
    cell_alignments=None,
    column_widths=None,
    row_heights=None,
):
    normalized_rows = normalize_table_rows(rows)
    row_count = len(normalized_rows)
    col_count = max(1, len(normalized_rows[0]) if normalized_rows else 1)
    block = {
        'type': 'table',
        'table_id': str(table_id or uuid.uuid4().hex),
        'caption': normalize_paragraph_text(caption),
        'has_header': bool(has_header),
        'rows': normalized_rows,
        'merged_cells': normalize_merged_cells(merged_cells or [], row_count, col_count),
        'table_style': normalize_table_style(table_style),
        'cell_alignments': normalize_table_alignments(cell_alignments or [], row_count, col_count),
    }
    normalized_widths = normalize_table_pixel_sizes(column_widths or [], col_count, min_value=1)
    normalized_heights = normalize_table_pixel_sizes(row_heights or [], row_count, min_value=1)
    if normalized_widths:
        block['column_widths'] = normalized_widths
    if normalized_heights:
        block['row_heights'] = normalized_heights
    return block


def sanitize_block(block):
    if not isinstance(block, dict):
        return None

    block_type = str(block.get('type', '') or '').strip().lower()
    if block_type == 'paragraph':
        text = normalize_paragraph_text(block.get('text', ''))
        if not text:
            return None
        return new_paragraph_block(text, **_normalize_paragraph_metadata(block))

    if block_type == 'table':
        rows = normalize_table_rows(block.get('rows', []))
        table_block = new_table_block(
            rows,
            table_id=block.get('table_id', ''),
            caption=block.get('caption', ''),
            has_header=block.get('has_header', True),
            merged_cells=block.get('merged_cells', []),
            table_style=block.get('table_style', TABLE_STYLE_GRID),
            cell_alignments=block.get('cell_alignments', []),
            column_widths=block.get('column_widths', []),
            row_heights=block.get('row_heights', []),
        )
        return table_block

    text = normalize_paragraph_text(block.get('text', ''))
    if text:
        return new_paragraph_block(text)
    return None


def sanitize_blocks(blocks):
    sanitized = []
    if not isinstance(blocks, list):
        return sanitized
    for block in blocks:
        sanitized_block = sanitize_block(block)
        if sanitized_block is not None:
            sanitized.append(sanitized_block)
    return sanitized


def _split_table_row(line):
    text = _normalize_text(line).strip()
    if text.startswith('|'):
        text = text[1:]
    if text.endswith('|'):
        text = text[:-1]
    return [normalize_table_cell(cell) for cell in text.split('|')]


def _looks_like_table_start(lines, index):
    if index < 0 or index + 1 >= len(lines):
        return False
    line = str(lines[index] or '')
    next_line = str(lines[index + 1] or '')
    if '|' not in line:
        return False
    if not TABLE_SEPARATOR_RE.match(next_line):
        return False
    return True


def parse_markdown_blocks(text):
    lines = _normalize_text(text).split('\n')
    blocks = []
    paragraph_lines = []
    index = 0

    def flush_paragraph():
        if not paragraph_lines:
            return
        paragraph_text = '\n'.join(line.rstrip() for line in paragraph_lines).strip()
        paragraph_lines.clear()
        if paragraph_text:
            blocks.append(new_paragraph_block(paragraph_text))

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            flush_paragraph()
            index += 1
            continue

        if _looks_like_table_start(lines, index):
            flush_paragraph()
            header = _split_table_row(lines[index])
            body = []
            index += 2
            while index < len(lines):
                candidate = lines[index]
                if not candidate.strip():
                    break
                if '|' not in candidate:
                    break
                body.append(_split_table_row(candidate))
                index += 1
            blocks.append(new_table_block([header] + body))
            continue

        paragraph_lines.append(line)
        index += 1

    flush_paragraph()
    return blocks


def table_block_to_markdown(block):
    sanitized = sanitize_block(block)
    if not sanitized or sanitized.get('type') != 'table':
        return ''

    rows = sanitize_table_rows_for_output(sanitized.get('rows', []))
    if not rows:
        return ''

    width = max(len(row) for row in rows)
    normalized = [row + [''] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]
    separator = ['---'] * width
    lines = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(separator) + ' |',
    ]
    for row in body:
        lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines)


def sanitize_table_rows_for_output(rows):
    sanitized = normalize_table_rows(rows)
    return [[normalize_table_cell(cell) for cell in row] for row in sanitized]


def _positive_count(count):
    try:
        value = int(count)
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def _clamp_range(length, start, end=None):
    if length <= 0:
        return 0, 0
    try:
        start_index = int(start)
    except (TypeError, ValueError):
        start_index = 0
    try:
        end_index = int(start if end is None else end)
    except (TypeError, ValueError):
        end_index = start_index
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    start_index = max(0, min(start_index, length - 1))
    end_index = max(0, min(end_index, length - 1))
    return start_index, end_index


def _range_overlaps(start_a, end_a, start_b, end_b):
    return start_a <= end_b and start_b <= end_a


def _merge_bounds(cell):
    row = cell['row']
    col = cell['col']
    return row, row + cell['rowspan'] - 1, col, col + cell['colspan'] - 1


def _merge_intersects_range(cell, row_range, col_range):
    row_start, row_end, col_start, col_end = _merge_bounds(cell)
    return (
        _range_overlaps(row_start, row_end, row_range[0], row_range[1])
        and _range_overlaps(col_start, col_end, col_range[0], col_range[1])
    )


def expand_selection_range_for_merges(row_range, col_range, merged_cells, row_count, col_count):
    row_start, row_end = _clamp_range(row_count, *(row_range or (0, 0)))
    col_start, col_end = _clamp_range(col_count, *(col_range or (0, 0)))
    normalized_merges = normalize_merged_cells(merged_cells, row_count, col_count)

    changed = True
    while changed:
        changed = False
        for cell in normalized_merges:
            if not _merge_intersects_range(cell, (row_start, row_end), (col_start, col_end)):
                continue
            cell_row_start, cell_row_end, cell_col_start, cell_col_end = _merge_bounds(cell)
            next_row_start = min(row_start, cell_row_start)
            next_row_end = max(row_end, cell_row_end)
            next_col_start = min(col_start, cell_col_start)
            next_col_end = max(col_end, cell_col_end)
            if (
                next_row_start != row_start
                or next_row_end != row_end
                or next_col_start != col_start
                or next_col_end != col_end
            ):
                row_start, row_end = next_row_start, next_row_end
                col_start, col_end = next_col_start, next_col_end
                changed = True
    return (row_start, row_end), (col_start, col_end)


def _merge_after_row_insert(cell, insert_at, count):
    row_start, row_end, _col_start, _col_end = _merge_bounds(cell)
    updated = dict(cell)
    if insert_at <= row_start:
        updated['row'] += count
    elif row_start < insert_at <= row_end:
        updated['rowspan'] += count
    return updated


def _merge_after_col_insert(cell, insert_at, count):
    _row_start, _row_end, col_start, col_end = _merge_bounds(cell)
    updated = dict(cell)
    if insert_at <= col_start:
        updated['col'] += count
    elif col_start < insert_at <= col_end:
        updated['colspan'] += count
    return updated


def _map_deleted_index(index, delete_start, delete_end):
    if delete_start <= index <= delete_end:
        return None
    if index > delete_end:
        return index - (delete_end - delete_start + 1)
    return index


def _merge_after_row_delete(cell, delete_start, delete_end):
    row_start, row_end, col_start, _col_end = _merge_bounds(cell)
    remaining = [
        row_idx
        for row_idx in range(row_start, row_end + 1)
        if row_idx < delete_start or row_idx > delete_end
    ]
    if not remaining:
        return None
    mapped = [_map_deleted_index(row_idx, delete_start, delete_end) for row_idx in remaining]
    mapped = [row_idx for row_idx in mapped if row_idx is not None]
    if not mapped:
        return None
    return {
        'row': min(mapped),
        'col': col_start,
        'rowspan': max(mapped) - min(mapped) + 1,
        'colspan': cell['colspan'],
    }


def _merge_after_col_delete(cell, delete_start, delete_end):
    row_start, _row_end, col_start, col_end = _merge_bounds(cell)
    remaining = [
        col_idx
        for col_idx in range(col_start, col_end + 1)
        if col_idx < delete_start or col_idx > delete_end
    ]
    if not remaining:
        return None
    mapped = [_map_deleted_index(col_idx, delete_start, delete_end) for col_idx in remaining]
    mapped = [col_idx for col_idx in mapped if col_idx is not None]
    if not mapped:
        return None
    return {
        'row': row_start,
        'col': min(mapped),
        'rowspan': cell['rowspan'],
        'colspan': max(mapped) - min(mapped) + 1,
    }


def insert_table_rows(rows, row_index=0, *, count=1, after=True):
    normalized = normalize_table_rows(rows)
    width = max(1, len(normalized[0]) if normalized else 1)
    start, _end = _clamp_range(len(normalized), row_index)
    insert_at = start + (1 if after else 0)
    insert_at = max(0, min(insert_at, len(normalized)))
    additions = [[''] * width for _ in range(_positive_count(count))]
    return normalize_table_rows(normalized[:insert_at] + additions + normalized[insert_at:])


def insert_table_rows_with_merges(rows, merged_cells, row_index=0, *, count=1, after=True):
    normalized, row_count, col_count = _table_shape(rows)
    start, _end = _clamp_range(row_count, row_index)
    insert_at = start + (1 if after else 0)
    count = _positive_count(count)
    updated_rows = insert_table_rows(normalized, row_index, count=count, after=after)
    updated_merges = [
        _merge_after_row_insert(cell, insert_at, count)
        for cell in normalize_merged_cells(merged_cells, row_count, col_count)
    ]
    return updated_rows, normalize_merged_cells(updated_merges, len(updated_rows), len(updated_rows[0]))


def insert_table_alignment_rows(cell_alignments, row_index=0, *, count=1, after=True, col_count=None):
    width = max(1, _int_value(col_count, 0))
    existing = cell_alignments if isinstance(cell_alignments, list) else []
    row_count = max(1, len(existing))
    if width <= 1:
        width = 1
        for row in existing:
            if isinstance(row, (list, tuple)):
                width = max(width, len(row))
    normalized = normalize_table_alignments(existing, row_count, width)
    start, _end = _clamp_range(len(normalized), row_index)
    insert_at = start + (1 if after else 0)
    insert_at = max(0, min(insert_at, len(normalized)))
    additions = [[TABLE_ALIGN_LEFT] * width for _ in range(_positive_count(count))]
    return normalize_table_alignments(normalized[:insert_at] + additions + normalized[insert_at:], len(normalized) + len(additions), width)


def delete_table_rows(rows, start, end=None):
    normalized = normalize_table_rows(rows)
    width = max(1, len(normalized[0]) if normalized else 1)
    start_index, end_index = _clamp_range(len(normalized), start, end)
    remaining = [
        row
        for index, row in enumerate(normalized)
        if index < start_index or index > end_index
    ]
    if not remaining:
        remaining = [[''] * width]
    return normalize_table_rows(remaining)


def delete_table_rows_with_merges(rows, merged_cells, start, end=None):
    normalized, row_count, col_count = _table_shape(rows)
    start_index, end_index = _clamp_range(row_count, start, end)
    updated_rows = delete_table_rows(normalized, start_index, end_index)
    updated_merges = []
    for cell in normalize_merged_cells(merged_cells, row_count, col_count):
        adjusted = _merge_after_row_delete(cell, start_index, end_index)
        if adjusted is not None:
            updated_merges.append(adjusted)
    return updated_rows, normalize_merged_cells(updated_merges, len(updated_rows), len(updated_rows[0]))


def delete_table_alignment_rows(cell_alignments, start, end=None, *, row_count=None, col_count=None):
    rows_len = max(1, _int_value(row_count, 0))
    width = max(1, _int_value(col_count, 0))
    existing = cell_alignments if isinstance(cell_alignments, list) else []
    if rows_len <= 1:
        rows_len = max(1, len(existing))
    if width <= 1:
        width = 1
        for row in existing:
            if isinstance(row, (list, tuple)):
                width = max(width, len(row))
    normalized = normalize_table_alignments(existing, rows_len, width)
    start_index, end_index = _clamp_range(len(normalized), start, end)
    remaining = [
        row
        for index, row in enumerate(normalized)
        if index < start_index or index > end_index
    ]
    if not remaining:
        remaining = [[TABLE_ALIGN_LEFT] * width]
    return normalize_table_alignments(remaining, len(remaining), width)


def insert_table_columns(rows, col_index=0, *, count=1, after=True):
    normalized = normalize_table_rows(rows)
    width = max(1, len(normalized[0]) if normalized else 1)
    start, _end = _clamp_range(width, col_index)
    insert_at = start + (1 if after else 0)
    insert_at = max(0, min(insert_at, width))
    additions = [''] * _positive_count(count)
    updated = []
    for row in normalized:
        padded = list(row[:width])
        updated.append(padded[:insert_at] + list(additions) + padded[insert_at:])
    return normalize_table_rows(updated)


def insert_table_columns_with_merges(rows, merged_cells, col_index=0, *, count=1, after=True):
    normalized, row_count, col_count = _table_shape(rows)
    start, _end = _clamp_range(col_count, col_index)
    insert_at = start + (1 if after else 0)
    count = _positive_count(count)
    updated_rows = insert_table_columns(normalized, col_index, count=count, after=after)
    updated_merges = [
        _merge_after_col_insert(cell, insert_at, count)
        for cell in normalize_merged_cells(merged_cells, row_count, col_count)
    ]
    return updated_rows, normalize_merged_cells(updated_merges, len(updated_rows), len(updated_rows[0]))


def insert_table_alignment_columns(cell_alignments, col_index=0, *, count=1, after=True, row_count=None, col_count=None):
    rows_len = max(1, _int_value(row_count, 0))
    width = max(1, _int_value(col_count, 0))
    existing = cell_alignments if isinstance(cell_alignments, list) else []
    if rows_len <= 1:
        rows_len = max(1, len(existing))
    if width <= 1:
        width = 1
        for row in existing:
            if isinstance(row, (list, tuple)):
                width = max(width, len(row))
    normalized = normalize_table_alignments(existing, rows_len, width)
    start, _end = _clamp_range(width, col_index)
    insert_at = start + (1 if after else 0)
    insert_at = max(0, min(insert_at, width))
    additions = [TABLE_ALIGN_LEFT] * _positive_count(count)
    updated = []
    for row in normalized:
        updated.append(row[:insert_at] + list(additions) + row[insert_at:])
    return normalize_table_alignments(updated, rows_len, width + len(additions))


def delete_table_columns(rows, start, end=None):
    normalized = normalize_table_rows(rows)
    width = max(1, len(normalized[0]) if normalized else 1)
    start_index, end_index = _clamp_range(width, start, end)
    updated = []
    for row in normalized:
        remaining = [
            cell
            for index, cell in enumerate(row[:width])
            if index < start_index or index > end_index
        ]
        if not remaining:
            remaining = ['']
        updated.append(remaining)
    return normalize_table_rows(updated)


def delete_table_columns_with_merges(rows, merged_cells, start, end=None):
    normalized, row_count, col_count = _table_shape(rows)
    start_index, end_index = _clamp_range(col_count, start, end)
    updated_rows = delete_table_columns(normalized, start_index, end_index)
    updated_merges = []
    for cell in normalize_merged_cells(merged_cells, row_count, col_count):
        adjusted = _merge_after_col_delete(cell, start_index, end_index)
        if adjusted is not None:
            updated_merges.append(adjusted)
    return updated_rows, normalize_merged_cells(updated_merges, len(updated_rows), len(updated_rows[0]))


def delete_table_alignment_columns(cell_alignments, start, end=None, *, row_count=None, col_count=None):
    rows_len = max(1, _int_value(row_count, 0))
    width = max(1, _int_value(col_count, 0))
    existing = cell_alignments if isinstance(cell_alignments, list) else []
    if rows_len <= 1:
        rows_len = max(1, len(existing))
    if width <= 1:
        width = 1
        for row in existing:
            if isinstance(row, (list, tuple)):
                width = max(width, len(row))
    normalized = normalize_table_alignments(existing, rows_len, width)
    start_index, end_index = _clamp_range(width, start, end)
    updated = []
    for row in normalized:
        remaining = [
            alignment
            for index, alignment in enumerate(row[:width])
            if index < start_index or index > end_index
        ]
        if not remaining:
            remaining = [TABLE_ALIGN_LEFT]
        updated.append(remaining)
    return normalize_table_alignments(updated, rows_len, len(updated[0]) if updated else 1)


def clear_table_cells(rows, *, mode='cell', row_range=None, col_range=None):
    normalized = normalize_table_rows(rows)
    row_count = len(normalized)
    col_count = max(1, len(normalized[0]) if normalized else 1)
    updated = [list(row[:col_count]) for row in normalized]

    if mode == 'table':
        row_start, row_end = 0, row_count - 1
        col_start, col_end = 0, col_count - 1
    else:
        row_start, row_end = _clamp_range(row_count, *(row_range or (0, 0)))
        col_start, col_end = _clamp_range(col_count, *(col_range or (0, 0)))
        if mode == 'row':
            col_start, col_end = 0, col_count - 1
        elif mode == 'column':
            row_start, row_end = 0, row_count - 1

    for row_index in range(row_start, row_end + 1):
        for col_index in range(col_start, col_end + 1):
            updated[row_index][col_index] = ''
    return normalize_table_rows(updated)


def set_table_cell_alignment(cell_alignments, alignment, *, mode='cell', row_range=None, col_range=None, row_count=1, col_count=1):
    row_count = max(1, _int_value(row_count, 1))
    col_count = max(1, _int_value(col_count, 1))
    updated = normalize_table_alignments(cell_alignments, row_count, col_count)
    normalized_alignment = normalize_table_alignment(alignment)

    if mode == 'table':
        row_start, row_end = 0, row_count - 1
        col_start, col_end = 0, col_count - 1
    else:
        row_start, row_end = _clamp_range(row_count, *(row_range or (0, 0)))
        col_start, col_end = _clamp_range(col_count, *(col_range or (0, 0)))
        if mode == 'row':
            col_start, col_end = 0, col_count - 1
        elif mode == 'column':
            row_start, row_end = 0, row_count - 1

    for row_idx in range(row_start, row_end + 1):
        for col_idx in range(col_start, col_end + 1):
            updated[row_idx][col_idx] = normalized_alignment
    return updated


def merge_table_cells(rows, merged_cells, row_range, col_range):
    normalized, row_count, col_count = _table_shape(rows)
    row_start, row_end = _clamp_range(row_count, *(row_range or (0, 0)))
    col_start, col_end = _clamp_range(col_count, *(col_range or (0, 0)))
    if row_start == row_end and col_start == col_end:
        return normalized, normalize_merged_cells(merged_cells, row_count, col_count)

    merge_range = (row_start, row_end), (col_start, col_end)
    updated_rows = [list(row[:col_count]) for row in normalized]
    anchor_text = updated_rows[row_start][col_start]
    for row_idx in range(row_start, row_end + 1):
        for col_idx in range(col_start, col_end + 1):
            if row_idx == row_start and col_idx == col_start:
                continue
            updated_rows[row_idx][col_idx] = ''
    updated_rows[row_start][col_start] = anchor_text

    kept_merges = [
        cell
        for cell in normalize_merged_cells(merged_cells, row_count, col_count)
        if not _merge_intersects_range(cell, merge_range[0], merge_range[1])
    ]
    kept_merges.append({
        'row': row_start,
        'col': col_start,
        'rowspan': row_end - row_start + 1,
        'colspan': col_end - col_start + 1,
    })
    return normalize_table_rows(updated_rows), normalize_merged_cells(kept_merges, row_count, col_count)


def unmerge_table_cells(rows, merged_cells, row_range=None, col_range=None):
    normalized, row_count, col_count = _table_shape(rows)
    if row_range is None:
        row_range = (0, row_count - 1)
    if col_range is None:
        col_range = (0, col_count - 1)
    row_start, row_end = _clamp_range(row_count, *row_range)
    col_start, col_end = _clamp_range(col_count, *col_range)
    kept_merges = [
        cell
        for cell in normalize_merged_cells(merged_cells, row_count, col_count)
        if not _merge_intersects_range(cell, (row_start, row_end), (col_start, col_end))
    ]
    return normalized, normalize_merged_cells(kept_merges, row_count, col_count)


def blocks_to_plain_text(blocks):
    sanitized = sanitize_blocks(blocks)
    if not sanitized:
        return ''

    parts = []
    for block in sanitized:
        if block['type'] == 'paragraph':
            text = normalize_paragraph_text(block.get('text', ''))
            if text:
                parts.append(text)
            continue

        if block['type'] == 'table':
            markdown = table_block_to_markdown(block)
            if markdown:
                parts.append(markdown)

    return '\n\n'.join(parts).strip()


def blocks_from_plain_text(text):
    return parse_markdown_blocks(text)


def deep_copy_blocks(blocks):
    return copy.deepcopy(sanitize_blocks(blocks))
