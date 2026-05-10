# -*- coding: utf-8 -*-
"""
智能纠错服务。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from modules.prompt_center import PromptCenter


CATEGORY_LABELS = {
    'basic_text': '文字基础',
    'grammar_sentence': '语法与语句',
    'academic_format': '学术格式',
    'citation_reference': '引用与参考文献',
    'data_expression': '数据与表达',
    'logic_rigor': '逻辑与严谨性',
    'compliance_risk': '规范与合规',
    'ai_style': 'AI 化表达',
}

CATEGORY_ORDER = tuple(CATEGORY_LABELS)

SEVERITY_LABELS = {
    'info': '提示',
    'warning': '警告',
    'error': '严重',
}

SEVERITY_ORDER = {
    'info': 0,
    'warning': 1,
    'error': 2,
}

CITATION_STYLE_OPTIONS = ('auto', 'GB/T 7714', 'APA', 'MLA')

INVISIBLE_CHAR_RE = re.compile(r'[\u200b\u200c\u200d\ufeff\xa0]')
MULTI_SPACE_RE = re.compile(r'[ \t]{2,}')
MULTI_BLANK_LINE_RE = re.compile(r'\n{3,}')
MOJIBAKE_RE = re.compile(r'�')
PERCENT_RE = re.compile(r'(?P<num>\d+(?:\.\d+)?)\s*[％%]')
TEMP_RE = re.compile(r'(?P<num>\d+(?:\.\d+)?)\s*(?:°C|C°|℃)')
UNIT_NO_SPACE_RE = re.compile(
    r'(?P<num>\d+(?:\.\d+)?)(?P<unit>kg|g|mg|m|cm|mm|km|s|min|h|Hz|kHz|MHz|GHz|N|Pa|kPa|MPa|V|A|W|mL|L)\b',
    re.IGNORECASE,
)

SENSITIVE_PATTERNS = (
    (re.compile(r'代写|枪手|包过|抄袭|洗稿'), '学术诚信风险', '检测到疑似学术不端或代写相关表述。'),
    (re.compile(r'政治敏感|颠覆|反动'), '敏感表述', '检测到敏感或不规范表述。'),
)

AI_TEMPLATE_PATTERNS = (
    re.compile(r'随着.+?的发展'),
    re.compile(r'值得注意的是'),
    re.compile(r'需要指出的是'),
    re.compile(r'综上所述'),
    re.compile(r'在一定程度上'),
    re.compile(r'具有重要的理论意义和实践价值'),
)

OVERCLAIM_PATTERNS = (
    re.compile(r'显然'),
    re.compile(r'毫无疑问'),
    re.compile(r'毋庸置疑'),
    re.compile(r'完美'),
    re.compile(r'最优'),
    re.compile(r'绝对'),
    re.compile(r'彻底证明'),
)

CLAIM_WITHOUT_CITATION_PATTERNS = (
    re.compile(r'普遍认为'),
    re.compile(r'已有研究表明'),
    re.compile(r'已被证明'),
)

NETWORK_TERMS = (
    'YYDS',
    '绝绝子',
    '躺平',
    '炸裂',
    '超神',
)


@dataclass
class CorrectionIssue:
    id: str
    category: str
    severity: str
    source: str
    title: str
    message: str
    start: int = -1
    end: int = -1
    original: str = ''
    suggestion: str = ''
    replacement: str = ''
    auto_fixable: bool = False
    confidence: float = 0.0
    doc_anchor: str = ''
    status: str = 'pending'

    def as_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'category': self.category,
            'severity': self.severity,
            'source': self.source,
            'title': self.title,
            'message': self.message,
            'start': self.start,
            'end': self.end,
            'original': self.original,
            'suggestion': self.suggestion,
            'replacement': self.replacement,
            'auto_fixable': self.auto_fixable,
            'confidence': self.confidence,
            'doc_anchor': self.doc_anchor,
            'status': self.status,
        }


@dataclass
class CorrectionRun:
    input_text: str
    corrected_text: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    source_kind: str = 'manual'
    citation_style_detected: str = 'GB/T 7714'
    citation_style_effective: str = 'GB/T 7714'
    report_text: str = ''


class IntelligentCorrector:
    """论文智能纠错服务。"""

    def __init__(self, api_client, prompt_center=None):
        self.api = api_client
        self.prompt_center = prompt_center or PromptCenter(getattr(api_client, 'config', None))
        self._issue_index = 0

    def analyze_text(self, text, citation_style='auto', source_kind='manual', knowledge_context=None) -> CorrectionRun:
        content = str(text or '')
        if not content.strip():
            raise ValueError('待纠错文本不能为空')

        detected_style = self._detect_citation_style(content)
        effective_style = (
            citation_style
            if citation_style in CITATION_STYLE_OPTIONS and citation_style != 'auto'
            else detected_style
        )

        issues = []
        issues.extend(self._check_basic_text(content))
        issues.extend(self._check_grammar_and_sentence(content))
        issues.extend(self._check_academic_format_text(content))
        issues.extend(self._check_citations(content, effective_style))
        issues.extend(self._check_data_expression(content))
        issues.extend(self._check_logic_rigor(content, effective_style))
        issues.extend(self._check_compliance_risk(content))
        issues.extend(self._check_ai_style(content))

        merged = self._merge_issues(issues)
        ai_issues = self._collect_ai_issues(content, effective_style, knowledge_context)
        all_issues = self._merge_issues([*merged, *ai_issues])

        run = CorrectionRun(
            input_text=content,
            corrected_text=content,
            issues=[issue.as_dict() for issue in all_issues],
            counts=self._summarize_issues(all_issues),
            source_kind=source_kind,
            citation_style_detected=detected_style,
            citation_style_effective=effective_style,
        )
        run.report_text = self.build_report(run)
        return run


    def apply_fixes(self, text, issues, ids=None) -> str:
        content = str(text or '')
        selected_ids = set(ids or [])
        selected = []
        for issue in self._issue_objects(issues):
            if issue.status != 'pending' or not issue.auto_fixable:
                continue
            if issue.start < 0 or issue.end < issue.start:
                continue
            if selected_ids and issue.id not in selected_ids:
                continue
            selected.append(issue)

        selected.sort(key=lambda item: (item.start, item.end))
        filtered = []
        last_end = -1
        for issue in selected:
            if issue.start < last_end:
                continue
            filtered.append(issue)
            last_end = issue.end

        result = content
        for issue in sorted(filtered, key=lambda item: item.start, reverse=True):
            result = result[:issue.start] + issue.replacement + result[issue.end:]
        return result

    def build_report(self, run: CorrectionRun) -> str:
        counts = dict(run.counts or {})
        by_category = counts.get('by_category', {})
        pending_issues = [
            issue for issue in self._issue_objects(run.issues)
            if issue.status == 'pending'
        ]
        non_auto = [issue for issue in pending_issues if not issue.auto_fixable]
        severe = sorted(
            pending_issues,
            key=lambda item: (-SEVERITY_ORDER.get(item.severity, 0), item.start if item.start >= 0 else 10**9),
        )

        lines = [
            '《论文纠错报告》',
            '',
            '一、摘要',
            f'- 内容来源：{run.source_kind}',
            f'- 引用规范识别：{run.citation_style_detected}',
            f'- 实际检查规范：{run.citation_style_effective}',
            f'- 问题总数：{counts.get("total", 0)}',
            f'- 待处理问题：{counts.get("pending", 0)}',
            f'- 可自动修复：{counts.get("auto_fixable", 0)}',
            '',
            '二、分类统计',
        ]
        for category in CATEGORY_ORDER:
            lines.append(f'- {CATEGORY_LABELS[category]}：{by_category.get(category, 0)}')

        lines.extend(['', '三、主要问题'])
        if severe:
            for issue in severe[:20]:
                anchor = f' | 位置：{issue.doc_anchor}' if issue.doc_anchor else ''
                original = f' | 原文：{issue.original}' if issue.original else ''
                lines.append(
                    f'- [{CATEGORY_LABELS.get(issue.category, issue.category)} / {SEVERITY_LABELS.get(issue.severity, issue.severity)}] '
                    f'{issue.title}{anchor} | {issue.message}{original}'
                )
        else:
            lines.append('- 未发现待处理问题。')

        lines.extend(['', '四、不可自动修复项'])
        if non_auto:
            for issue in non_auto[:20]:
                lines.append(f'- {issue.title}：{issue.suggestion or issue.message}')
        else:
            lines.append('- 当前问题均可通过自动修复或简单人工确认处理。')

        lines.extend(['', '五、能力说明'])
        lines.append('- 逻辑严谨性、文献支撑不足、夸大断言、AI 化表达等问题默认需要人工确认。')
        return '\n'.join(lines)


    def _next_issue_id(self) -> str:
        self._issue_index += 1
        return f'corr-{self._issue_index:05d}'

    def _make_issue(
        self,
        *,
        category,
        severity,
        source,
        title,
        message,
        start=-1,
        end=-1,
        original='',
        suggestion='',
        replacement='',
        auto_fixable=False,
        confidence=0.75,
        doc_anchor='',
        status='pending',
    ) -> CorrectionIssue:
        return CorrectionIssue(
            id=self._next_issue_id(),
            category=category if category in CATEGORY_LABELS else 'grammar_sentence',
            severity=severity if severity in SEVERITY_ORDER else 'warning',
            source=source,
            title=title,
            message=message,
            start=int(start),
            end=int(end),
            original=original,
            suggestion=suggestion,
            replacement='' if replacement is None else replacement,
            auto_fixable=bool(auto_fixable),
            confidence=max(0.0, min(float(confidence), 1.0)),
            doc_anchor=doc_anchor,
            status=status,
        )

    def _issue_objects(self, issues: Iterable[dict[str, Any] | CorrectionIssue]) -> list[CorrectionIssue]:
        result = []
        for item in issues or []:
            if isinstance(item, CorrectionIssue):
                result.append(item)
                continue
            if not isinstance(item, dict):
                continue
            result.append(
                CorrectionIssue(
                    id=str(item.get('id') or self._next_issue_id()),
                    category=str(item.get('category') or 'grammar_sentence'),
                    severity=str(item.get('severity') or 'warning'),
                    source=str(item.get('source') or 'rule'),
                    title=str(item.get('title') or '未命名问题'),
                    message=str(item.get('message') or ''),
                    start=-1 if item.get('start', -1) is None else int(item.get('start', -1)),
                    end=-1 if item.get('end', -1) is None else int(item.get('end', -1)),
                    original=str(item.get('original') or ''),
                    suggestion=str(item.get('suggestion') or ''),
                    replacement='' if item.get('replacement') is None else str(item.get('replacement')),
                    auto_fixable=bool(item.get('auto_fixable', False)),
                    confidence=max(0.0, min(float(item.get('confidence', 0.0) or 0.0), 1.0)),
                    doc_anchor=str(item.get('doc_anchor') or ''),
                    status=str(item.get('status') or 'pending'),
                )
            )
        return result

    def _merge_issues(self, issues: Iterable[CorrectionIssue | dict[str, Any]]) -> list[CorrectionIssue]:
        merged = {}
        for issue in self._issue_objects(issues):
            key = self._issue_key(issue)
            current = merged.get(key)
            if current is None or self._prefer_issue(issue, current):
                merged[key] = issue
        return sorted(
            merged.values(),
            key=lambda item: (
                -SEVERITY_ORDER.get(item.severity, 0),
                CATEGORY_ORDER.index(item.category) if item.category in CATEGORY_ORDER else len(CATEGORY_ORDER),
                item.start if item.start >= 0 else 10**9,
                item.title,
            ),
        )

    def _issue_key(self, issue: CorrectionIssue):
        if issue.start >= 0 and issue.end >= issue.start:
            return ('span', issue.category, issue.start, issue.end, issue.original.strip())
        if issue.doc_anchor:
            return ('anchor', issue.category, issue.doc_anchor, issue.title, issue.original.strip())
        return ('title', issue.category, issue.title, issue.original.strip(), issue.message[:60])

    def _prefer_issue(self, candidate: CorrectionIssue, current: CorrectionIssue) -> bool:
        return (
            SEVERITY_ORDER.get(candidate.severity, 0),
            candidate.confidence,
            len(candidate.message),
        ) > (
            SEVERITY_ORDER.get(current.severity, 0),
            current.confidence,
            len(current.message),
        )

    def _summarize_issues(self, issues: Iterable[CorrectionIssue | dict[str, Any]]) -> dict[str, Any]:
        objects = self._issue_objects(issues)
        by_category = {category: 0 for category in CATEGORY_ORDER}
        by_status = Counter()
        auto_fixable = 0
        pending = 0
        for item in objects:
            by_status[item.status] += 1
            if item.status == 'pending':
                pending += 1
                by_category[item.category] = by_category.get(item.category, 0) + 1
                if item.auto_fixable:
                    auto_fixable += 1
        return {
            'total': len(objects),
            'pending': pending,
            'auto_fixable': auto_fixable,
            'by_category': by_category,
            'by_status': dict(by_status),
        }

    def _detect_citation_style(self, text):
        scores = {
            'GB/T 7714': len(re.findall(r'\[\d+(?:\s*[,，、-]\s*\d+)*\]', text)),
            'APA': len(re.findall(r'\([A-Z][A-Za-z\-]+[^)]*(?:19|20)\d{2}[a-z]?[^)]*\)', text)),
            'MLA': len(re.findall(r'\([A-Z][A-Za-z\-]+[^,)]*\s+\d{1,4}[^)]*\)', text)),
        }
        best_style, best_score = max(scores.items(), key=lambda item: item[1])
        return best_style if best_score > 0 else 'GB/T 7714'

    def _split_reference_section(self, text):
        match = re.search(r'(?im)^\s*(参考文献|references|works cited)\s*$', text)
        if not match:
            return text, '', len(text)
        return text[:match.start()], text[match.end():], match.end()

    def _sentence_has_citation(self, sentence, citation_style):
        if citation_style == 'GB/T 7714':
            return bool(re.search(r'\[\d+(?:\s*[,，、-]\s*\d+)*\]', sentence))
        return bool(re.search(r'\([A-Z][A-Za-z\-]+[^)]*\)', sentence))

    def _find_span(self, text, snippet, used_spans):
        if not snippet:
            return -1, -1
        start = 0
        while True:
            start = text.find(snippet, start)
            if start < 0:
                return -1, -1
            end = start + len(snippet)
            if (start, end) not in used_spans:
                return start, end
            start = end

    def _iter_sentences(self, text):
        for match in re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', text):
            segment = match.group()
            if segment.strip():
                yield segment, match.start(), match.end()

    def _iter_lines(self, text, base_offset=0):
        cursor = base_offset
        for line_no, raw_line in enumerate(text.splitlines(True), start=1):
            clean_line = raw_line.rstrip('\r\n')
            yield clean_line, cursor, cursor + len(clean_line), line_no
            cursor += len(raw_line)

    def _is_cjk(self, char):
        return bool(char and '\u4e00' <= char <= '\u9fff')

    def _is_ascii_context(self, char):
        return bool(char and char.isascii() and (char.isalpha() or char.isdigit()))

    def _length_value(self, value):
        if value is None:
            return None
        if hasattr(value, 'pt'):
            return round(value.pt, 2)
        try:
            return round(float(value), 2)
        except Exception:
            return str(value)

    def _line_spacing_value(self, value):
        if value is None:
            return None
        if hasattr(value, 'pt'):
            return round(value.pt, 2)
        try:
            return round(float(value), 2)
        except Exception:
            return str(value)

    def _check_basic_text(self, text):
        issues = []
        for match in INVISIBLE_CHAR_RE.finditer(text):
            replacement = ' ' if match.group() == '\xa0' else ''
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='warning',
                    source='rule',
                    title='检测到不可见字符',
                    message='文中包含零宽字符或不间断空格，可能影响排版或查重。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='删除不可见字符或改为普通空格。',
                    replacement=replacement,
                    auto_fixable=True,
                    confidence=0.98,
                )
            )

        for match in MOJIBAKE_RE.finditer(text):
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='warning',
                    source='rule',
                    title='检测到乱码字符',
                    message='文中存在乱码替换符，建议核对原始内容。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='检查导入文件或手动恢复该字符。',
                    confidence=0.9,
                )
            )

        for match in MULTI_SPACE_RE.finditer(text):
            if '\n' in match.group():
                continue
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='info',
                    source='rule',
                    title='存在多余空格',
                    message='连续空格会影响排版统一性。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='压缩为单个空格。',
                    replacement=' ',
                    auto_fixable=True,
                    confidence=0.96,
                )
            )

        for match in MULTI_BLANK_LINE_RE.finditer(text):
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='info',
                    source='rule',
                    title='连续换行过多',
                    message='连续空行会导致段落间距不统一。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='压缩为一个空行。',
                    replacement='\n\n',
                    auto_fixable=True,
                    confidence=0.96,
                )
            )

        ascii_to_cn = {
            ',': '，',
            '.': '。',
            ';': '；',
            ':': '：',
            '?': '？',
            '!': '！',
            '(': '（',
            ')': '）',
        }
        cn_to_ascii = {value: key for key, value in ascii_to_cn.items()}
        for index, char in enumerate(text):
            prev_char = text[index - 1] if index > 0 else ''
            next_char = text[index + 1] if index + 1 < len(text) else ''
            if char in ascii_to_cn and (self._is_cjk(prev_char) or self._is_cjk(next_char)):
                issues.append(
                    self._make_issue(
                        category='basic_text',
                        severity='info',
                        source='rule',
                        title='中文语境下标点不统一',
                        message='中文语境中使用了英文标点。',
                        start=index,
                        end=index + 1,
                        original=char,
                        suggestion=f'建议改为中文标点“{ascii_to_cn[char]}”。',
                        replacement=ascii_to_cn[char],
                        auto_fixable=True,
                        confidence=0.88,
                    )
                )
            elif char in cn_to_ascii and (self._is_ascii_context(prev_char) or self._is_ascii_context(next_char)):
                issues.append(
                    self._make_issue(
                        category='basic_text',
                        severity='info',
                        source='rule',
                        title='英文语境下标点不统一',
                        message='英文语境中使用了中文标点。',
                        start=index,
                        end=index + 1,
                        original=char,
                        suggestion=f'建议改为英文标点“{cn_to_ascii[char]}”。',
                        replacement=cn_to_ascii[char],
                        auto_fixable=True,
                        confidence=0.88,
                    )
                )

        for match in PERCENT_RE.finditer(text):
            normalized = f'{match.group("num")}%'
            if match.group() == normalized:
                continue
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='info',
                    source='rule',
                    title='百分比写法不规范',
                    message='百分比建议统一为数字后直接跟 “%” 的形式。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='统一百分比格式。',
                    replacement=normalized,
                    auto_fixable=True,
                    confidence=0.95,
                )
            )

        for match in TEMP_RE.finditer(text):
            normalized = f'{match.group("num")}℃'
            if match.group() == normalized:
                continue
            issues.append(
                self._make_issue(
                    category='basic_text',
                    severity='info',
                    source='rule',
                    title='温度单位写法不统一',
                    message='温度单位建议统一为 “℃” 表示。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='统一温度单位写法。',
                    replacement=normalized,
                    auto_fixable=True,
                    confidence=0.94,
                )
            )
        return issues

    def _check_grammar_and_sentence(self, text):
        issues = []
        for match in re.finditer(r'\b([A-Za-z]+)(\s+\1\b)+', text, flags=re.IGNORECASE):
            issues.append(
                self._make_issue(
                    category='grammar_sentence',
                    severity='warning',
                    source='rule',
                    title='英文单词重复',
                    message='连续重复单词通常属于编辑残留。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='保留一次重复单词即可。',
                    replacement=match.group(1),
                    auto_fixable=True,
                    confidence=0.98,
                )
            )

        for match in re.finditer(r'([\u4e00-\u9fff]{2,8})(?:\1)+', text):
            issues.append(
                self._make_issue(
                    category='grammar_sentence',
                    severity='warning',
                    source='rule',
                    title='短语重复',
                    message='连续重复短语会影响语句简洁性。',
                    start=match.start(),
                    end=match.end(),
                    original=match.group(),
                    suggestion='建议删除重复表达。',
                    replacement=match.group(1),
                    auto_fixable=True,
                    confidence=0.9,
                )
            )

        for sentence, start, end in self._iter_sentences(text):
            if len(sentence.strip()) > 120:
                issues.append(
                    self._make_issue(
                        category='grammar_sentence',
                        severity='info',
                        source='rule',
                        title='句子长度偏长',
                        message='长句可能导致句式杂糅或逻辑不清，建议拆分。',
                        start=start,
                        end=end,
                        original=sentence.strip(),
                        suggestion='拆分长句并补足逻辑连接。',
                        confidence=0.7,
                    )
                )
            for term in NETWORK_TERMS:
                local_start = sentence.find(term)
                if local_start >= 0:
                    issues.append(
                        self._make_issue(
                            category='grammar_sentence',
                            severity='warning',
                            source='rule',
                            title='存在口语化或网络化表达',
                            message='学术论文中建议避免网络化表达。',
                            start=start + local_start,
                            end=start + local_start + len(term),
                            original=term,
                            suggestion='改为正式、客观的学术表达。',
                            confidence=0.82,
                        )
                    )
        return issues

    def _check_academic_format_text(self, text):
        issues = []
        headings = []
        families = set()
        caption_styles = defaultdict(set)
        for line_text, start, end, line_no in self._iter_lines(text):
            stripped = line_text.strip()
            if not stripped:
                continue
            match = re.match(r'^(?P<num>\d+(?:\.\d+)*)\s+', stripped)
            if match:
                parts = [int(item) for item in match.group('num').split('.')]
                headings.append((parts, start, end, stripped, line_no, 'decimal'))
                families.add('decimal')
            elif re.match(r'^[一二三四五六七八九十]+、', stripped):
                headings.append(([1], start, end, stripped, line_no, 'cn_chapter'))
                families.add('cn_chapter')
            elif re.match(r'^（\d+）', stripped):
                headings.append(([1, 1], start, end, stripped, line_no, 'paren'))
                families.add('paren')

            fig_match = re.match(r'^(图)\s*(\d+)', stripped)
            if fig_match:
                caption_styles['图'].add(fig_match.group(0))
            table_match = re.match(r'^(表)\s*(\d+)', stripped)
            if table_match:
                caption_styles['表'].add(table_match.group(0))

        if len(families) > 1:
            issues.append(
                self._make_issue(
                    category='academic_format',
                    severity='warning',
                    source='rule',
                    title='标题层级样式混用',
                    message='同一篇文稿中混用了多种标题编号方式，建议统一标题层级规则。',
                    suggestion='统一使用一种标题编号体系，例如 “1 / 1.1 / 1.1.1”。',
                    confidence=0.92,
                )
            )

        previous_decimal = None
        for parts, start, end, stripped, line_no, family in headings:
            if family != 'decimal':
                continue
            if len(parts) > 1 and previous_decimal and len(parts) > len(previous_decimal) + 1:
                issues.append(
                    self._make_issue(
                        category='academic_format',
                        severity='warning',
                        source='rule',
                        title='标题层级跳级',
                        message=f'第 {line_no} 行标题层级出现跳级。',
                        start=start,
                        end=end,
                        original=stripped,
                        suggestion='检查是否遗漏上一级标题。',
                        doc_anchor=f'第 {line_no} 行',
                        confidence=0.86,
                    )
                )
            if previous_decimal and len(parts) == len(previous_decimal):
                if parts[:-1] == previous_decimal[:-1] and parts[-1] > previous_decimal[-1] + 1:
                    issues.append(
                        self._make_issue(
                            category='academic_format',
                            severity='warning',
                            source='rule',
                            title='标题编号不连续',
                            message=f'第 {line_no} 行标题编号存在跳号。',
                            start=start,
                            end=end,
                            original=stripped,
                            suggestion='核对同级标题编号是否连续。',
                            doc_anchor=f'第 {line_no} 行',
                            confidence=0.86,
                        )
                    )
            previous_decimal = parts

        issues.extend(self._check_caption_sequence(text, '图'))
        issues.extend(self._check_caption_sequence(text, '表'))
        issues.extend(self._check_equation_sequence(text))

        for prefix, styles in caption_styles.items():
            compact = any(re.match(rf'^{prefix}\d+', item) for item in styles)
            spaced = any(re.match(rf'^{prefix}\s+\d+', item) for item in styles)
            if compact and spaced:
                issues.append(
                    self._make_issue(
                        category='academic_format',
                        severity='info',
                        source='rule',
                        title=f'{prefix}表标题格式不统一',
                        message=f'{prefix}标题存在 “{prefix}1” 与 “{prefix} 1” 混用情况。',
                        suggestion=f'统一 {prefix} 标题编号书写格式。',
                        confidence=0.8,
                    )
                )
        return issues

    def _check_caption_sequence(self, text, prefix):
        issues = []
        matches = list(re.finditer(rf'^{prefix}\s*(\d+)', text, flags=re.MULTILINE))
        numbers = [int(match.group(1)) for match in matches]
        for index in range(1, len(numbers)):
            if numbers[index] != numbers[index - 1] + 1:
                match = matches[index]
                line_no = text[:match.start()].count('\n') + 1
                issues.append(
                    self._make_issue(
                        category='academic_format',
                        severity='warning',
                        source='rule',
                        title=f'{prefix}表编号不连续',
                        message=f'{prefix}表编号在第 {line_no} 行附近出现跳号。',
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='检查图表编号是否连续且与正文引用一致。',
                        doc_anchor=f'第 {line_no} 行',
                        confidence=0.9,
                    )
                )
        return issues

    def _check_equation_sequence(self, text):
        issues = []
        matches = list(re.finditer(r'[\(（](\d+)[\)）]\s*$', text, flags=re.MULTILINE))
        numbers = [int(match.group(1)) for match in matches]
        for index in range(1, len(numbers)):
            if numbers[index] != numbers[index - 1] + 1:
                match = matches[index]
                line_no = text[:match.start()].count('\n') + 1
                issues.append(
                    self._make_issue(
                        category='academic_format',
                        severity='warning',
                        source='rule',
                        title='公式编号不连续',
                        message=f'公式编号在第 {line_no} 行附近出现跳号或错位。',
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='核对公式编号与正文引用的一致性。',
                        doc_anchor=f'第 {line_no} 行',
                        confidence=0.85,
                    )
                )
        return issues

    def _check_citations(self, text, citation_style):
        issues = []
        has_numeric = bool(re.search(r'\[\d+(?:\s*[,，、-]\s*\d+)*\]', text))
        has_author_year = bool(re.search(r'\([A-Z][A-Za-z\-]+[^)]*(?:19|20)\d{2}[^)]*\)', text))
        if has_numeric and has_author_year:
            issues.append(
                self._make_issue(
                    category='citation_reference',
                    severity='warning',
                    source='rule',
                    title='正文引用格式混用',
                    message='正文中同时出现数字编码制与作者-年份制引用，建议统一。',
                    suggestion='统一正文引用规范后再提交排版。',
                    confidence=0.95,
                )
            )

        if citation_style == 'GB/T 7714':
            issues.extend(self._check_citations_gbt(text))
        else:
            issues.extend(self._check_citations_author_year(text, citation_style))
        return issues

    def _check_citations_gbt(self, text):
        issues = []
        body_text, refs_text, _ = self._split_reference_section(text)
        body_numbers = [int(num) for num in re.findall(r'\[(\d+)\]', body_text)]
        ref_matches = list(re.finditer(r'^\s*\[(\d+)\]\s*(.+)$', refs_text, flags=re.MULTILINE))
        ref_numbers = [int(match.group(1)) for match in ref_matches]

        for match in re.finditer(r'(?:\[\d+\]){2,}', body_text):
            numbers = [int(item) for item in re.findall(r'\d+', match.group())]
            normalized = ''.join(f'[{item}]' for item in sorted(dict.fromkeys(numbers)))
            if match.group() != normalized:
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='warning',
                        source='rule',
                        title='引用序号顺序混乱',
                        message='连续引用建议按编号递增排列。',
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='统一正文中的连续编号顺序。',
                        replacement=normalized,
                        auto_fixable=True,
                        confidence=0.93,
                    )
                )

        for match in re.finditer(r'\[(\d+(?:\s*[,，、]\s*\d+)+)\]', body_text):
            numbers = [int(item) for item in re.findall(r'\d+', match.group(1))]
            normalized_numbers = sorted(dict.fromkeys(numbers))
            normalized = '[' + ', '.join(str(item) for item in normalized_numbers) + ']'
            if numbers != normalized_numbers:
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='warning',
                        source='rule',
                        title='单组引用序号未排序',
                        message='同一组引用建议按从小到大排序。',
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='统一单组引用的编号顺序。',
                        replacement=normalized,
                        auto_fixable=True,
                        confidence=0.92,
                    )
                )

        if body_numbers and not ref_matches:
            issues.append(
                self._make_issue(
                    category='citation_reference',
                    severity='error',
                    source='rule',
                    title='缺少参考文献列表',
                    message='正文存在数字引用，但未检测到规范的参考文献列表。',
                    suggestion='补充“参考文献”章节并列出对应条目。',
                    confidence=0.98,
                )
            )
            return issues

        if body_numbers and ref_numbers:
            missing_refs = sorted(set(body_numbers) - set(ref_numbers))
            if missing_refs:
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='error',
                        source='rule',
                        title='交叉引用缺失',
                        message=f'正文引用 {missing_refs} 在参考文献列表中未找到对应条目。',
                        suggestion='补齐缺失文献或修正正文中的引用编号。',
                        confidence=0.99,
                    )
                )
            expected = list(range(min(ref_numbers), max(ref_numbers) + 1))
            if ref_numbers != expected:
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='warning',
                        source='rule',
                        title='参考文献编号不连续',
                        message='参考文献列表中的编号存在跳号或乱序。',
                        suggestion='检查文末参考文献编号顺序。',
                        confidence=0.9,
                    )
                )

        for match in ref_matches:
            line = match.group(0).strip()
            if not re.search(r'(19|20)\d{2}', line):
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='warning',
                        source='rule',
                        title='参考文献信息可能缺失年份',
                        message='该条文献未检测到明显年份信息。',
                        original=line,
                        doc_anchor=f'参考文献 [{match.group(1)}]',
                        suggestion='补充年份、卷期或出版信息。',
                        confidence=0.78,
                    )
                )
        return issues

    def _check_citations_author_year(self, text, citation_style):
        issues = []
        body_text, refs_text, refs_offset = self._split_reference_section(text)
        if citation_style == 'APA':
            citation_pattern = re.compile(r'\(([A-Z][A-Za-z\-]+)[^)]*(19|20)\d{2}[a-z]?[^)]*\)')
        else:
            citation_pattern = re.compile(r'\(([A-Z][A-Za-z\-]+)[^,)]*\s+\d{1,4}[^)]*\)')

        citations = [(match.group(1), match.group(0)) for match in citation_pattern.finditer(body_text)]
        if citations and not refs_text.strip():
            issues.append(
                self._make_issue(
                    category='citation_reference',
                    severity='error',
                    source='rule',
                    title='缺少参考文献列表',
                    message='正文存在作者-年份/作者-页码引用，但未检测到参考文献列表。',
                    suggestion='补充 References / Works Cited 章节。',
                    confidence=0.97,
                )
            )
            return issues

        ref_authors = set()
        for line_text, start, end, line_no in self._iter_lines(refs_text, base_offset=refs_offset):
            stripped = line_text.strip()
            if not stripped:
                continue
            author_match = re.match(r'([A-Z][A-Za-z\-]+)', stripped)
            if author_match:
                ref_authors.add(author_match.group(1))
            if citation_style == 'APA' and not re.search(r'(19|20)\d{2}', stripped):
                issues.append(
                    self._make_issue(
                        category='citation_reference',
                        severity='warning',
                        source='rule',
                        title='参考文献可能缺少年份',
                        message=f'第 {line_no} 行参考文献未检测到明显年份信息。',
                        original=stripped,
                        doc_anchor=f'第 {line_no} 行',
                        suggestion='补充年份并统一 APA 格式。',
                        confidence=0.78,
                    )
                )

        missing = sorted({author for author, _ in citations if author not in ref_authors})
        if missing:
            issues.append(
                self._make_issue(
                    category='citation_reference',
                    severity='warning',
                    source='rule',
                    title='正文引用与文末参考文献不匹配',
                    message=f'正文中引用了 {", ".join(missing)}，但参考文献列表未找到对应作者。',
                    suggestion='补齐对应参考文献，或统一作者写法。',
                    confidence=0.86,
                )
            )
        return issues

    def _check_data_expression(self, text):
        issues = []
        for match in UNIT_NO_SPACE_RE.finditer(text):
            original = match.group()
            replacement = f'{match.group("num")} {match.group("unit")}'
            if original == replacement:
                continue
            issues.append(
                self._make_issue(
                    category='data_expression',
                    severity='info',
                    source='rule',
                    title='数值与单位间缺少空格',
                    message='除百分比、摄氏度等特殊单位外，数值与英文单位建议以空格分隔。',
                    start=match.start(),
                    end=match.end(),
                    original=original,
                    suggestion='统一数值与单位的书写格式。',
                    replacement=replacement,
                    auto_fixable=True,
                    confidence=0.9,
                )
            )

        word_forms = defaultdict(set)
        for match in re.finditer(r'\b[A-Za-z][A-Za-z\-]{2,}\b', text):
            word_forms[match.group().lower()].add(match.group())
        for forms in word_forms.values():
            if len(forms) > 1:
                issues.append(
                    self._make_issue(
                        category='data_expression',
                        severity='info',
                        source='rule',
                        title='英文术语大小写不统一',
                        message=f'检测到同一英文术语存在多种写法：{", ".join(sorted(forms)[:4])}',
                        suggestion='统一同一术语的大小写格式。',
                        confidence=0.72,
                    )
                )

        keyword_values = defaultdict(set)
        keyword_positions = {}
        for sentence, start, end in self._iter_sentences(text):
            for keyword in ('准确率', '召回率', '精度', '增长', '下降', '提升', '减少', '损失', '温度'):
                if keyword not in sentence:
                    continue
                num_match = re.search(r'(\d+(?:\.\d+)?)\s*(%|℃|kg|g|mL|L|倍|次|元|万元)?', sentence)
                if not num_match:
                    continue
                normalized = f'{num_match.group(1)}{num_match.group(2) or ""}'
                keyword_values[keyword].add(normalized)
                keyword_positions.setdefault(keyword, (start, end, sentence.strip()))
        for keyword, values in keyword_values.items():
            if len(values) > 1:
                start, end, snippet = keyword_positions[keyword]
                issues.append(
                    self._make_issue(
                        category='data_expression',
                        severity='warning',
                        source='rule',
                        title='相同指标存在不同数值表述',
                        message=f'“{keyword}” 在文中出现多个数值：{", ".join(sorted(values))}',
                        start=start,
                        end=end,
                        original=snippet,
                        suggestion='核对同一指标在全文中的数值与单位是否一致。',
                        confidence=0.74,
                    )
                )
        return issues

    def _check_logic_rigor(self, text, citation_style):
        issues = []
        for sentence, start, end in self._iter_sentences(text):
            for pattern in OVERCLAIM_PATTERNS:
                match = pattern.search(sentence)
                if match:
                    issues.append(
                        self._make_issue(
                            category='logic_rigor',
                            severity='warning',
                            source='rule',
                            title='存在夸大或绝对化表述',
                            message='该句包含较强主观判断，建议改为可验证、可证据支持的表述。',
                            start=start + match.start(),
                            end=start + match.end(),
                            original=match.group(),
                            suggestion='改为客观、审慎的学术表述。',
                            confidence=0.84,
                        )
                    )
            for pattern in CLAIM_WITHOUT_CITATION_PATTERNS:
                match = pattern.search(sentence)
                if match and not self._sentence_has_citation(sentence, citation_style):
                    issues.append(
                        self._make_issue(
                            category='logic_rigor',
                            severity='warning',
                            source='rule',
                            title='论断缺少引用支撑',
                            message='该句含有结论性判断，但未检测到相邻引用。',
                            start=start + match.start(),
                            end=start + match.end(),
                            original=sentence.strip(),
                            suggestion='补充文献支撑，或降低断言强度。',
                            confidence=0.8,
                        )
                    )
        return issues

    def _check_compliance_risk(self, text):
        issues = []
        for pattern, title, message in SENSITIVE_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    self._make_issue(
                        category='compliance_risk',
                        severity='error',
                        source='rule',
                        title=title,
                        message=message,
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='请删除或改写为合规表述。',
                        confidence=0.96,
                    )
                )

        sentence_counter = Counter()
        sentence_positions = {}
        for sentence, start, end in self._iter_sentences(text):
            normalized = re.sub(r'\s+', '', sentence)
            if len(normalized) < 20:
                continue
            sentence_counter[normalized] += 1
            sentence_positions.setdefault(normalized, (start, end, sentence.strip()))
        for normalized, count in sentence_counter.items():
            if count >= 2:
                start, end, snippet = sentence_positions[normalized]
                issues.append(
                    self._make_issue(
                        category='compliance_risk',
                        severity='warning',
                        source='rule',
                        title='存在高重复片段',
                        message=f'检测到重复句段出现 {count} 次，建议检查抄袭或模板化风险。',
                        start=start,
                        end=end,
                        original=snippet,
                        suggestion='改写重复片段并核对引用来源。',
                        confidence=0.82,
                    )
                )
        return issues

    def _check_ai_style(self, text):
        issues = []
        matches = []
        for pattern in AI_TEMPLATE_PATTERNS:
            matches.extend(pattern.finditer(text))
        if len(matches) >= 2:
            for match in matches[:6]:
                issues.append(
                    self._make_issue(
                        category='ai_style',
                        severity='info',
                        source='rule',
                        title='存在模板化表达',
                        message='该表达较为模板化，可能带来 AI 化写作痕迹。',
                        start=match.start(),
                        end=match.end(),
                        original=match.group(),
                        suggestion='改写为更贴合论文上下文的自然表达。',
                        confidence=0.68,
                    )
                )
        return issues

    def _collect_ai_issues(self, text, citation_style, knowledge_context=None):
        if not self.api or not hasattr(self.api, 'call_json_sync'):
            return []
        rendered = self.prompt_center.render_scene(
            'correction.ai_review',
            {
                'text': text,
                'citation_style': citation_style,
            },
        )
        from modules.knowledge_base import append_knowledge_context
        prompt = append_knowledge_context(rendered['prompt'], knowledge_context)
        try:
            payload = self.api.call_json_sync(
                prompt,
                system=rendered['system'],
                temperature=0.2,
                schema_name='correction_issues',
                usage_context={
                    'page_id': 'correction',
                    'scene_id': 'correction.ai_review',
                    'action': 'ai_review',
                },
            )
        except Exception:
            return []

        items = payload if isinstance(payload, list) else payload.get('issues', [])
        issues = []
        used_spans = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            original = str(item.get('original') or '')
            start, end = self._find_span(text, original, used_spans)
            if start >= 0:
                used_spans.add((start, end))
            issues.append(
                self._make_issue(
                    category=str(item.get('category') or 'grammar_sentence'),
                    severity=str(item.get('severity') or 'warning'),
                    source='ai',
                    title=str(item.get('title') or 'AI 识别问题'),
                    message=str(item.get('message') or ''),
                    start=start,
                    end=end,
                    original=original,
                    suggestion=str(item.get('suggestion') or ''),
                    replacement=item.get('replacement'),
                    auto_fixable=bool(item.get('auto_fixable', False)),
                    confidence=float(item.get('confidence', 0.6) or 0.6),
                )
            )
        return issues

