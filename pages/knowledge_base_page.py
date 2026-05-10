# -*- coding: utf-8 -*-
"""
知识库管理与资料选择窗口。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from modules.knowledge_base import (
    KnowledgeBaseError,
    KnowledgeBaseStore,
    ALL_KB_SCENE_IDS,
)
from modules.prompt_center import SCENE_DEFS, PAGE_META
from modules.ui_components import (
    COLORS,
    FONTS,
    ToggleSwitch,
    create_home_shell_button,
    THEMES,
)


def _scene_label(scene_id):
    scene = SCENE_DEFS.get(scene_id, {})
    page_label = scene.get('page_label', '')
    label = scene.get('label', '')
    if page_label and label:
        return f'{page_label} · {label}'
    return label or page_label or scene_id


class KnowledgeBasePanel:
    """知识库管理面板。"""

    def __init__(self, parent, store: KnowledgeBaseStore, set_status=None, close_panel=None):
        self.parent = parent
        self.store = store
        self.set_status = set_status or (lambda *_args, **_kwargs: None)
        self.close_panel = close_panel
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.projects = []
        self.documents = []
        self.current_project_id = ''
        self.current_document_id = ''
        self.project_active_vars = {}
        self.project_scope_summary_var = tk.StringVar(value='')
        self.title_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self._project_row_widgets = []
        self._document_enabled_vars = {}
        self._document_enabled_switches = {}
        self._build()
        self.refresh_all()

    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 16))
        tk.Label(
            header,
            text='知识库',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            text='独立多项目资料库，启动项目后按本次选择使用资料。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT, padx=(14, 0))

        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left_card = tk.Frame(body, bg=COLORS['card_bg'], highlightthickness=1, highlightbackground=COLORS['card_border'])
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 14))
        project_header = tk.Frame(left_card, bg=COLORS['card_bg'])
        project_header.pack(fill=tk.X, padx=14, pady=(14, 8))
        tk.Label(
            project_header,
            text='项目',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        create_shell, _button = create_home_shell_button(
            project_header,
            '创建',
            command=self._create_project,
            style='primary_fixed',
            padx=12,
            pady=5,
            border_color=THEMES['light']['card_border'],
        )
        delete_shell, _button = create_home_shell_button(
            project_header,
            '删除',
            command=self._delete_project,
            style='secondary',
            padx=12,
            pady=5,
        )
        delete_shell.pack(side=tk.RIGHT)
        create_shell.pack(side=tk.RIGHT, padx=(0, 8))

        project_scope_area = tk.Frame(left_card, bg=COLORS['card_bg'])
        project_scope_area.pack(fill=tk.X, side=tk.BOTTOM, padx=14, pady=(8, 14))

        list_shell = tk.Frame(left_card, bg=COLORS['input_bg'], highlightthickness=1, highlightbackground=COLORS['card_border'])
        list_shell.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        self._project_list_canvas = tk.Canvas(list_shell, bg=COLORS['input_bg'], highlightthickness=0, bd=0, width=240)
        self._project_list_scroll = ttk.Scrollbar(list_shell, orient=tk.VERTICAL, command=self._project_list_canvas.yview)
        self._project_list_inner = tk.Frame(self._project_list_canvas, bg=COLORS['input_bg'])
        self._project_list_inner.bind('<Configure>', lambda _e: self._project_list_canvas.configure(scrollregion=self._project_list_canvas.bbox('all')))
        self._canvas_window_id = self._project_list_canvas.create_window((0, 0), window=self._project_list_inner, anchor='nw')
        self._project_list_canvas.bind('<Configure>', lambda _e: self._project_list_canvas.itemconfigure(self._canvas_window_id, width=_e.width))
        self._project_list_canvas.configure(yscrollcommand=self._project_list_scroll.set)
        self._project_list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._project_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_canvas_mousewheel(event):
            self._project_list_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        self._project_list_canvas.bind('<MouseWheel>', _on_canvas_mousewheel)
        self._project_list_inner.bind('<MouseWheel>', _on_canvas_mousewheel)

        project_scope_header = tk.Frame(project_scope_area, bg=COLORS['card_bg'])
        project_scope_header.pack(fill=tk.X, pady=(0, 2))
        tk.Label(project_scope_header, text='项目使用范围', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
        scope_shell, _button = create_home_shell_button(
            project_scope_header,
            '选择范围',
            command=self._open_project_scope_dialog,
            style='secondary',
            padx=10,
            pady=4,
        )
        scope_shell.pack(side=tk.RIGHT)

        tk.Label(
            project_scope_area,
            textvariable=self.project_scope_summary_var,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify=tk.LEFT,
            wraplength=260,
        ).pack(fill=tk.X)

        right = tk.Frame(body, bg=COLORS['bg_main'])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        docs_card = tk.Frame(right, bg=COLORS['card_bg'], highlightthickness=1, highlightbackground=COLORS['card_border'])
        docs_card.pack(fill=tk.BOTH, expand=True)
        docs_header = tk.Frame(docs_card, bg=COLORS['card_bg'])
        docs_header.pack(fill=tk.X, padx=14, pady=(14, 8))
        tk.Label(
            docs_header,
            text='资料',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        for label, command, style in (
            ('导入资料', self._import_documents, 'primary_fixed'),
            ('删除资料', self._delete_document, 'secondary'),
        ):
            shell, _button = create_home_shell_button(
                docs_header,
                label,
                command=command,
                style=style,
                padx=14,
                pady=7,
                border_color=THEMES['light']['card_border'] if style == 'primary_fixed' else None,
            )
            shell.pack(side=tk.RIGHT, padx=(8, 0))

        doc_editor = tk.Frame(docs_card, bg=COLORS['surface_alt'], highlightthickness=1, highlightbackground=COLORS['card_border'])
        doc_editor.pack(fill=tk.X, padx=14, pady=(0, 12))
        form = tk.Frame(doc_editor, bg=COLORS['surface_alt'])
        form.pack(fill=tk.X, padx=12, pady=12)
        tk.Label(form, text='标题', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['surface_alt']).grid(row=0, column=0, sticky='w')
        title_entry = tk.Entry(form, textvariable=self.title_var, font=FONTS['body'], bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT)
        title_entry.grid(row=0, column=1, sticky='ew', padx=(8, 12), ipady=4)
        tk.Label(form, text='标签', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['surface_alt']).grid(row=0, column=2, sticky='w')
        tags_entry = tk.Entry(form, textvariable=self.tags_var, font=FONTS['body'], bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT)
        tags_entry.grid(row=0, column=3, sticky='ew', padx=(8, 0), ipady=4)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)
        if callable(self.close_panel):
            save_shell, _button = create_home_shell_button(
                form,
                '保存资料',
                command=self._save_document,
                style='primary_fixed',
                padx=14,
                pady=5,
                border_color=THEMES['light']['card_border'],
            )
            save_shell.grid(row=0, column=4, sticky='e', padx=(12, 0))

        columns = ('title', 'type', 'chars', 'enabled')
        self.docs_tree = ttk.Treeview(docs_card, columns=columns, show='headings', height=9)
        for col, title, width, anchor in (
            ('title', '标题', 420, 'w'),
            ('type', '类型', 70, 'w'),
            ('chars', '字符数', 80, 'w'),
            ('enabled', '状态', 90, 'center'),
        ):
            self.docs_tree.heading(col, text=title)
            self.docs_tree.column(col, width=width, anchor=anchor, stretch=False if col == 'enabled' else True)
        self.docs_tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        self.docs_tree.bind('<<TreeviewSelect>>', self._on_document_selected)
        self.docs_tree.bind('<Button-1>', self._on_docs_tree_click, add='+')
        self.docs_tree.bind('<Configure>', lambda _event: self._position_document_switches(), add='+')
        self.docs_tree.bind('<Expose>', lambda _event: self._position_document_switches(), add='+')
        self.docs_tree.bind('<MouseWheel>', self._on_docs_tree_mousewheel, add='+')
        self.docs_tree.bind('<KeyRelease>', lambda _event: self.docs_tree.after_idle(self._position_document_switches), add='+')

    def _format_project_scope_summary(self, project):
        if not project:
            return '当前范围：未选择项目'
        bound = set(project.get('bound_scene_ids', ALL_KB_SCENE_IDS) or [])
        total = len(ALL_KB_SCENE_IDS)
        selected = sum(1 for scene_id in ALL_KB_SCENE_IDS if scene_id in bound)
        if selected == total:
            return '当前范围：全部场景'
        if selected == 0:
            return '当前范围：未选择场景'
        return '当前范围：部分场景'

    def refresh_all(self, preferred_project_id='', preferred_document_id=''):
        self._refresh_projects(preferred_project_id or self.current_project_id)
        if not self.current_project_id and self.projects:
            self.current_project_id = self.projects[0]['id']
        self._refresh_documents(preferred_document_id or self.current_document_id)
        self._load_project_scope()

    def _refresh_projects(self, preferred_project_id=''):
        self.projects = self.store.list_projects()
        for widget in self._project_list_inner.winfo_children():
            widget.destroy()
        self.project_active_vars = {}
        self._project_row_widgets = []
        ids = {project['id'] for project in self.projects}
        if preferred_project_id in ids:
            self.current_project_id = preferred_project_id
        elif self.projects:
            self.current_project_id = self.projects[0]['id']
        else:
            self.current_project_id = ''
        for project in self.projects:
            row = tk.Frame(self._project_list_inner, bg=COLORS['input_bg'], cursor='hand2')
            row.pack(fill=tk.X, pady=(0, 1))
            active_var = tk.BooleanVar(value=project.get('active', False))
            self.project_active_vars[project['id']] = active_var
            is_selected = project['id'] == self.current_project_id
            row_bg = COLORS['primary'] if is_selected else COLORS['input_bg']
            toggle = ToggleSwitch(row, variable=active_var, width=36, height=20, bg=row_bg,
                                  command=lambda pid=project['id']: self._on_project_active_toggled(pid))
            toggle.pack(side=tk.LEFT, padx=(4, 6), pady=4)
            name_label = tk.Label(row, text=project['name'], font=FONTS['body'], fg='#FFFFFF' if is_selected else COLORS['text_main'],
                                  bg=row_bg, anchor='w')
            name_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), pady=4)
            for wid in (row, name_label):
                wid.bind('<Button-1>', lambda _e, pid=project['id']: self._on_project_row_clicked(pid))
                wid.bind('<Double-Button-1>', lambda _e, pid=project['id']: self._rename_project(pid))
            self._project_row_widgets.append((project['id'], row, name_label, toggle))

    def _on_project_active_toggled(self, project_id):
        if self.project_active_vars[project_id].get():
            self.store.set_active_project(project_id)
            for pid, var in self.project_active_vars.items():
                if pid != project_id:
                    var.set(False)
        else:
            self.store.update_project(project_id, active=False)
        self.set_status('项目启动状态已更新', COLORS['success'])

    def _on_project_row_clicked(self, project_id):
        self.current_project_id = project_id
        self.current_document_id = ''
        for pid, row, name_label, toggle in self._project_row_widgets:
            is_selected = pid == project_id
            row_bg = COLORS['primary'] if is_selected else COLORS['input_bg']
            fg = '#FFFFFF' if is_selected else COLORS['text_main']
            row.configure(bg=row_bg)
            name_label.configure(bg=row_bg, fg=fg)
            toggle.configure(bg=row_bg)
            toggle._canvas_bg = row_bg
            toggle.canvas.configure(bg=row_bg)
        self._refresh_documents()
        self._load_project_scope()

    def _load_project_scope(self):
        project = self.store.get_project(self.current_project_id) if self.current_project_id else None
        self.project_scope_summary_var.set(self._format_project_scope_summary(project))

    def _open_project_scope_dialog(self):
        if not self.current_project_id:
            messagebox.showwarning('知识库', '请先选择项目。', parent=self.frame)
            return
        project = self.store.get_project(self.current_project_id)
        if not project:
            messagebox.showwarning('知识库', '请先选择项目。', parent=self.frame)
            return
        scene_ids = ProjectScopeDialog(self.frame, project).show()
        if scene_ids is None:
            return
        try:
            project = self.store.update_project(self.current_project_id, bound_scene_ids=scene_ids)
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('项目使用范围已保存', COLORS['success'])
        self.refresh_all(preferred_project_id=project['id'])

    def _refresh_documents(self, preferred_document_id=''):
        self._clear_document_enabled_switches()
        for item in self.docs_tree.get_children():
            self.docs_tree.delete(item)
        self.documents = self.store.list_documents(self.current_project_id) if self.current_project_id else []
        ids = {document['id'] for document in self.documents}
        self.current_document_id = preferred_document_id if preferred_document_id in ids else ''
        for document in self.documents:
            self.docs_tree.insert(
                '',
                tk.END,
                iid=document['id'],
                values=(
                    document.get('title', ''),
                    document.get('source_type', ''),
                    document.get('char_count', 0),
                    '',
                ),
            )
            enabled_var = tk.BooleanVar(value=bool(document.get('enabled', True)))
            self._document_enabled_vars[document['id']] = enabled_var
            switch = ToggleSwitch(
                self.docs_tree,
                variable=enabled_var,
                width=42,
                height=24,
                bg=COLORS['input_bg'],
                command=lambda doc_id=document['id']: self._save_document_enabled_from_switch(doc_id),
            )
            self._document_enabled_switches[document['id']] = switch
        if self.current_document_id:
            self.docs_tree.selection_set(self.current_document_id)
            self.docs_tree.focus(self.current_document_id)
        elif self.documents:
            self.current_document_id = self.documents[0]['id']
            self.docs_tree.selection_set(self.current_document_id)
            self.docs_tree.focus(self.current_document_id)
        self._load_document_detail()
        self.docs_tree.after_idle(self._position_document_switches)

    def _clear_document_enabled_switches(self):
        for switch in self._document_enabled_switches.values():
            try:
                switch.destroy()
            except tk.TclError:
                pass
        self._document_enabled_vars = {}
        self._document_enabled_switches = {}

    def _position_document_switches(self):
        for document_id, switch in self._document_enabled_switches.items():
            try:
                bbox = self.docs_tree.bbox(document_id, 'enabled')
            except tk.TclError:
                bbox = ''
            if not bbox:
                switch.place_forget()
                continue
            x, y, width, height = bbox
            switch_width = 42
            switch_height = 24
            switch.place(
                x=x + max((width - switch_width) // 2, 0),
                y=y + max((height - switch_height) // 2, 0),
                width=switch_width,
                height=switch_height,
            )

    def _on_docs_tree_mousewheel(self, _event):
        self.docs_tree.after_idle(self._position_document_switches)

    def _on_document_selected(self):
        selection = self.docs_tree.selection()
        self.current_document_id = selection[0] if selection else ''
        self._load_document_detail()
        self.docs_tree.after_idle(self._position_document_switches)

    def _on_docs_tree_click(self, event):
        region = self.docs_tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        column = self.docs_tree.identify_column(event.x)
        if column != '#4':
            return
        document_id = self.docs_tree.identify_row(event.y)
        if not document_id:
            return
        self.current_document_id = document_id
        self.docs_tree.selection_set(document_id)
        self.docs_tree.focus(document_id)
        self._toggle_document_enabled(document_id)
        return 'break'

    def _save_document_enabled_from_switch(self, document_id):
        enabled_var = self._document_enabled_vars.get(document_id)
        if enabled_var is None:
            return
        self._set_document_enabled(document_id, bool(enabled_var.get()))

    def _toggle_document_enabled(self, document_id):
        document = self.store.get_document(document_id)
        if not document:
            messagebox.showwarning('知识库', '请先选择资料。', parent=self.frame)
            return
        self._set_document_enabled(document_id, not bool(document.get('enabled', True)))

    def _set_document_enabled(self, document_id, enabled):
        try:
            document = self.store.update_document(document_id, enabled=enabled)
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库资料状态已更新', COLORS['success'])
        self.refresh_all(preferred_project_id=document['project_id'], preferred_document_id=document['id'])

    def _load_document_detail(self):
        document = self.store.get_document(self.current_document_id) if self.current_document_id else None
        self.title_var.set(document.get('title', '') if document else '')
        self.tags_var.set('，'.join(document.get('tags', [])) if document else '')

    def _create_project(self):
        name = simpledialog.askstring('新建知识库项目', '请输入项目名称：', parent=self.frame)
        if not name:
            return
        try:
            project = self.store.create_project(name)
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库项目已创建', COLORS['success'])
        self.refresh_all(preferred_project_id=project['id'])

    def _rename_project(self, project_id=None):
        project_id = project_id or self.current_project_id
        project = self.store.get_project(project_id)
        if not project:
            messagebox.showwarning('知识库', '请先选择项目。', parent=self.frame)
            return
        name = simpledialog.askstring('重命名知识库项目', '请输入新的项目名称：', initialvalue=project['name'], parent=self.frame)
        if not name:
            return
        try:
            self.store.update_project(project['id'], name=name)
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库项目已重命名', COLORS['success'])
        self.refresh_all(preferred_project_id=project['id'])

    def _delete_project(self):
        project = self.store.get_project(self.current_project_id)
        if not project:
            messagebox.showwarning('知识库', '请先选择项目。', parent=self.frame)
            return
        if not messagebox.askyesno('删除知识库项目', f'确定删除"{project["name"]}"及其全部资料吗？', parent=self.frame):
            return
        try:
            self.store.delete_project(project['id'])
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库项目已删除', COLORS['success'])
        self.refresh_all()

    def _import_documents(self):
        if not self.current_project_id:
            messagebox.showwarning('知识库', '请先创建或选择项目。', parent=self.frame)
            return
        paths = filedialog.askopenfilenames(
            title='导入知识库资料',
            filetypes=[
                ('支持的资料文件', '*.txt *.md *.docx *.pdf'),
                ('文本文件', '*.txt *.md'),
                ('Word 文档', '*.docx'),
                ('PDF 文件', '*.pdf'),
            ],
            parent=self.frame,
        )
        if not paths:
            return
        imported = []
        failed = []
        for path in paths:
            try:
                imported.append(self.store.import_document(self.current_project_id, path))
            except Exception as exc:
                failed.append(f'{os.path.basename(path)}：{exc}')
        if failed:
            messagebox.showwarning('知识库导入', '\n'.join(failed), parent=self.frame)
        if imported:
            self.set_status(f'已导入 {len(imported)} 份知识库资料', COLORS['success'])
            self.refresh_all(preferred_document_id=imported[-1]['id'])

    def _save_document(self):
        if not self.current_document_id:
            messagebox.showwarning('知识库', '请先选择资料。', parent=self.frame)
            return
        try:
            document = self.store.update_document(
                self.current_document_id,
                title=self.title_var.get(),
                tags=self.tags_var.get(),
            )
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库资料设置已保存', COLORS['success'])
        self.refresh_all(preferred_project_id=document['project_id'], preferred_document_id=document['id'])
        if callable(self.close_panel):
            self.close_panel()

    def _delete_document(self):
        document = self.store.get_document(self.current_document_id)
        if not document:
            messagebox.showwarning('知识库', '请先选择资料。', parent=self.frame)
            return
        if not messagebox.askyesno('删除知识库资料', f'确定删除"{document["title"]}"吗？', parent=self.frame):
            return
        try:
            self.store.delete_document(document['id'])
        except Exception as exc:
            messagebox.showerror('知识库', str(exc), parent=self.frame)
            return
        self.set_status('知识库资料已删除', COLORS['success'])
        self.refresh_all(preferred_project_id=document['project_id'])


class ProjectScopeDialog:
    """项目使用范围选择弹窗。"""

    def __init__(self, parent, project):
        self.parent = parent
        self.project = project or {}
        self.result = None
        self.scene_vars = {}
        self.window = None

    def show(self):
        self.window = tk.Toplevel(self.parent)
        self.window.title('选择项目使用范围')
        self.window.configure(bg=COLORS['bg_main'])
        self.window.transient(self.parent)
        self.window.geometry('980x860')
        self.window.minsize(900, 760)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self._cancel)
        self._build()
        self.window.wait_window()
        return self.result

    def _build(self):
        container = tk.Frame(self.window, bg=COLORS['bg_main'])
        container.pack(fill=tk.BOTH, expand=True, padx=22, pady=22)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(1, weight=1)

        header = tk.Frame(container, bg=COLORS['bg_main'])
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text='项目使用范围',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['bg_main'],
        ).grid(row=0, column=0, sticky='w')
        project_name = self.project.get('name', '')
        intro_row = tk.Frame(header, bg=COLORS['bg_main'])
        intro_row.grid(row=1, column=0, sticky='ew', pady=(6, 12))
        intro_row.grid_columnconfigure(0, weight=1)
        tk.Label(
            intro_row,
            text=f'项目：{project_name}',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).grid(row=0, column=0, sticky='w')

        toolbar = tk.Frame(intro_row, bg=COLORS['bg_main'])
        toolbar.grid(row=0, column=1, sticky='e')
        for label, command in (
            ('全选', self._select_all),
            ('清空', self._clear_all),
        ):
            button = tk.Button(
                toolbar,
                text=label,
                command=command,
                font=FONTS['small'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['surface_alt'],
                activeforeground=COLORS['text_main'],
                relief=tk.SOLID,
                bd=1,
                padx=8,
                pady=2,
                cursor='hand2',
            )
            button.pack(side=tk.LEFT, padx=(6, 0))

        list_shell = tk.Frame(
            container,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        list_shell.grid(row=1, column=0, sticky='nsew', pady=(12, 0))
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(list_shell, bg=COLORS['card_bg'], highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(list_shell, orient=tk.VERTICAL, command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS['card_bg'])
        inner.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        window_id = canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        canvas.bind('<MouseWheel>', _on_mousewheel)
        inner.bind('<MouseWheel>', _on_mousewheel)

        bound = set(self.project.get('bound_scene_ids', ALL_KB_SCENE_IDS) or [])
        scene_groups = {}
        for scene_id in ALL_KB_SCENE_IDS:
            page_id = SCENE_DEFS[scene_id]['page_id']
            scene_groups.setdefault(page_id, []).append(scene_id)

        for page_id, scene_ids in scene_groups.items():
            page_label = PAGE_META.get(page_id, {}).get('label', page_id)
            group = tk.Frame(inner, bg=COLORS['card_bg'])
            group.pack(fill=tk.X, padx=14, pady=(14, 0))
            tk.Label(
                group,
                text=page_label,
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            ).pack(anchor='w')
            grid = tk.Frame(group, bg=COLORS['card_bg'])
            grid.pack(fill=tk.X, pady=(8, 0))
            for index, scene_id in enumerate(scene_ids):
                cell = tk.Frame(grid, bg=COLORS['card_bg'], width=360)
                cell.grid(row=index // 2, column=index % 2, sticky='w', padx=(0, 28 if index % 2 == 0 else 0), pady=(0, 8))
                cell.grid_propagate(False)
                scene_label = SCENE_DEFS[scene_id].get('label', scene_id.split('.')[-1])
                tk.Label(
                    cell,
                    text=scene_label,
                    font=FONTS['body'],
                    fg=COLORS['text_main'],
                    bg=COLORS['card_bg'],
                    anchor='w',
                    width=16,
                ).pack(side=tk.LEFT)
                var = tk.BooleanVar(value=scene_id in bound)
                self.scene_vars[scene_id] = var
                ToggleSwitch(cell, variable=var, width=42, height=24, bg=COLORS['card_bg']).pack(side=tk.LEFT, padx=(10, 0))

        footer = tk.Frame(container, bg=COLORS['bg_main'])
        footer.grid(row=2, column=0, sticky='ew', pady=(16, 0))
        for label, command, style in (
            ('取消', self._cancel, 'secondary'),
            ('保存范围', self._save, 'primary_fixed'),
        ):
            shell, _button = create_home_shell_button(
                footer,
                label,
                command=command,
                style=style,
                padx=24,
                pady=10,
                border_color=THEMES['light']['card_border'] if style == 'primary_fixed' else None,
            )
            shell.pack(side=tk.RIGHT, padx=(10, 0))

    def _select_all(self):
        for var in self.scene_vars.values():
            var.set(True)

    def _clear_all(self):
        for var in self.scene_vars.values():
            var.set(False)

    def _save(self):
        self.result = [scene_id for scene_id, var in self.scene_vars.items() if var.get()]
        self.window.destroy()

    def _cancel(self):
        self.result = None
        self.window.destroy()


class KnowledgeContextDialog:
    """论文写作请求前的本次资料选择弹窗。"""

    def __init__(self, parent, store: KnowledgeBaseStore, scene_id, action_label='',
                 total_char_limit=None, per_document_char_limit=None):
        from modules.knowledge_base import DEFAULT_TOTAL_CHAR_LIMIT, DEFAULT_PER_DOCUMENT_CHAR_LIMIT
        self.parent = parent
        self.store = store
        self.scene_id = str(scene_id or '').strip()
        self.action_label = str(action_label or '').strip()
        self.total_char_limit = total_char_limit or DEFAULT_TOTAL_CHAR_LIMIT
        self.per_document_char_limit = per_document_char_limit or DEFAULT_PER_DOCUMENT_CHAR_LIMIT
        self.result = None
        self.active_project = None
        self.documents = []
        self.document_ids_by_index = []
        self.document_selected = []
        self.window = None

    def show(self):
        self.active_project = self.store.get_active_project()
        if not self.active_project:
            return {}
        project_scene_ids = set(self.active_project.get('bound_scene_ids', []))
        if self.scene_id and self.scene_id not in project_scene_ids:
            return {}
        self.documents = self.store.list_documents(
            self.active_project['id'],
            scene_id=self.scene_id,
            enabled_only=True,
        )
        if not self.documents:
            return {}
        self.window = tk.Toplevel(self.parent)
        self.window.title('选择知识库资料')
        self.window.configure(bg=COLORS['bg_main'])
        self.window.transient(self.parent)
        self.window.geometry('1180x820')
        self.window.minsize(980, 680)
        self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self._cancel)
        self._build()
        self._refresh_documents()
        self.window.wait_window()
        return self.result

    def _build(self):
        container = tk.Frame(self.window, bg=COLORS['bg_main'])
        container.pack(fill=tk.BOTH, expand=True, padx=22, pady=22)
        project_name = self.active_project.get('name', '') if self.active_project else ''
        title = '选择知识库资料'
        if self.action_label:
            title = f'{title}：{self.action_label}'
        tk.Label(
            container,
            text=title,
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w')
        info_text = f'项目：{project_name}　当前场景：{_scene_label(self.scene_id)}。取消会中止本次生成，跳过知识库会继续正常生成。'
        tk.Label(
            container,
            text=info_text,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w', pady=(6, 4))
        tk.Label(
            container,
            text=f'当前模型预算：总计 {self.total_char_limit} 字，单份 {self.per_document_char_limit} 字',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w', pady=(0, 12))

        footer = tk.Frame(container, bg=COLORS['bg_main'])
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(16, 0))
        for label, command, style in (
            ('取消', self._cancel, 'secondary'),
            ('跳过知识库', self._skip, 'secondary'),
            ('使用所选资料', self._use_selected, 'primary_fixed'),
        ):
            shell, _button = create_home_shell_button(
                footer,
                label,
                command=command,
                style=style,
                padx=22,
                pady=9,
                border_color=THEMES['light']['card_border'] if style == 'primary_fixed' else None,
            )
            shell.pack(side=tk.RIGHT, padx=(10, 0))

        list_shell = tk.Frame(container, bg=COLORS['card_bg'], highlightbackground=COLORS['card_border'], highlightthickness=1)
        list_shell.pack(fill=tk.BOTH, expand=True)
        columns = ('check', 'title', 'chars', 'tags')
        self.docs_tree = ttk.Treeview(list_shell, columns=columns, show='headings', selectmode='none', height=10)
        for col, title, width, anchor in (
            ('check', '', 50, 'center'),
            ('title', '标题', 420, 'w'),
            ('chars', '字符数', 100, 'w'),
            ('tags', '标签', 200, 'w'),
        ):
            self.docs_tree.heading(col, text=title)
            self.docs_tree.column(col, width=width, anchor=anchor, stretch=True if col == 'title' else False)
        self.docs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=12)
        scroll = ttk.Scrollbar(list_shell, orient=tk.VERTICAL, command=self.docs_tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=12)
        self.docs_tree.configure(yscrollcommand=scroll.set)
        self.docs_tree.bind('<Button-1>', self._on_tree_click)

    def _refresh_documents(self):
        for item in self.docs_tree.get_children():
            self.docs_tree.delete(item)
        self.document_ids_by_index = []
        self.document_selected = []
        for index, document in enumerate(self.documents):
            tags = document.get('tags', [])
            tag_text = '、'.join(tags) if tags else ''
            self.document_ids_by_index.append(document['id'])
            self.document_selected.append(False)
            iid = f'doc_{index}'
            self.docs_tree.insert('', tk.END, iid=iid, values=(
                '☐',
                document.get('title', ''),
                f'{document.get("char_count", 0)} 字',
                tag_text,
            ))

    def _on_tree_click(self, event):
        region = self.docs_tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        column = self.docs_tree.identify_column(event.x)
        if column != '#1':
            return
        iid = self.docs_tree.identify_row(event.y)
        if not iid or not iid.startswith('doc_'):
            return
        index = int(iid.split('_', 1)[1])
        if index < 0 or index >= len(self.document_selected):
            return
        self.document_selected[index] = not self.document_selected[index]
        checked = '☑' if self.document_selected[index] else '☐'
        self.docs_tree.item(iid, values=(checked, *self.docs_tree.item(iid, 'values')[1:]))

    def _use_selected(self):
        selected_ids = [
            self.document_ids_by_index[index]
            for index, selected in enumerate(self.document_selected)
            if selected and 0 <= index < len(self.document_ids_by_index)
        ]
        if not selected_ids:
            messagebox.showwarning('知识库', '请选择至少一份资料，或点击"跳过知识库"。', parent=self.window)
            return
        context = self.store.build_context(
            self.active_project['id'], selected_ids, self.scene_id,
            total_char_limit=self.total_char_limit,
            per_document_char_limit=self.per_document_char_limit,
        )
        if not context.get('context_text'):
            messagebox.showwarning('知识库', '所选资料没有可用文本。', parent=self.window)
            return
        self.result = context
        self.window.destroy()

    def _skip(self):
        self.result = {}
        self.window.destroy()

    def _cancel(self):
        self.result = None
        self.window.destroy()
