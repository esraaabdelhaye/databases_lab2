import io
import json
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageTk

from er_mapping.transformer import ERTransformer
from er_mapping.visualizer import RelationalSchemaVisualizer
from query_engine.executor import Executor
from query_engine.lexer import QueryError
from query_engine.parser import parse, Select, Project, Aggregate, Join, SetOp, TableRef
from relational_algebra.relational_algebra import Table

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
LIGHT = dict(
    bg="#EEF2F6", surface="#FFFFFF", surface_alt="#F4F7FA", border="#D3DBE5", ink="#17202B", muted="#66758A",
    header="#14263B", header_ink="#FFFFFF", header_sub="#9FB3C8", accent="#1F6FB2", accent_hover="#18598F",
    accent_soft="#DCEBF8", heading="#E4EBF3", row_alt="#F5F8FB", scroll="#C2CCD9", scroll_active="#9FB0C4",
    ok="#1E7B4F", error="#B3261E")
DARK = dict(
    bg="#0E1621", surface="#152130", surface_alt="#1A2A3C", border="#263A50", ink="#E4ECF5", muted="#8CA0B6",
    header="#0A111A", header_ink="#FFFFFF", header_sub="#7F93A9", accent="#2F7FCB", accent_hover="#4592DB",
    accent_soft="#1F3A57", heading="#1D2E42", row_alt="#192739", scroll="#2E435A", scroll_active="#4A6784",
    ok="#4CC38A", error="#F07A72")
COLORS = dict(LIGHT)

FONTS = ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Inter", "Helvetica Neue", "Noto Sans", "DejaVu Sans"]
MONOS = ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono"]

# Pruned snippet toolbar: ONLY supported operations
SNIPPETS = [
    ("σ Select", "SELECT[]()", 3), ("π Project", "PROJECT[]()", 3),
    ("γ Aggregate", "AGGREGATE[]()", 3), ("⋈ Join", " JOIN[] ", 2), ("⟕ Left", " LEFT JOIN[] ", 2),
    ("⟖ Right", " RIGHT JOIN[] ", 2), ("∪ Union", " UNION ", 0), ("∩ Intersect", " INTERSECT ", 0),
    ("− Minus", " MINUS ", 0), ("AND", " AND ", 0), ("OR", " OR ", 0), ("NOT", "NOT ", 0),
]


def _esc_tx(text):
    esc = str.maketrans({c: "\\" + c for c in "_&%#$"} | {"{": r"\{", "}": r"\}", " ": r"\ "})
    return r"\mathrm{" + (str(text).translate(esc) or r"\ ") + "}"


def ast_to_latex(node):
    """Converts a parsed AST node into LaTeX relational algebra notation."""
    if isinstance(node, TableRef):
        return _esc_tx(node.name)
    if isinstance(node, Select):
        cond_lat = _cond_to_latex(node.cond)
        child_lat = ast_to_latex(node.child)
        return r"\sigma_{" + cond_lat + r"}\left(" + child_lat + r"\right)"
    if isinstance(node, Project):
        cols_lat = r",\,".join(_esc_tx(col) for col, _ in node.attrs)
        child_lat = ast_to_latex(node.child)
        return r"\pi_{" + cols_lat + r"}\left(" + child_lat + r"\right)"
    if isinstance(node, Aggregate):
        groups_lat = (r",\,".join(_esc_tx(g) for g, _ in node.groups) + r";\,") if node.groups else ""
        specs_lat = r",\,".join(_esc_tx(fn) + "(" + _esc_tx(col) + ")" for fn, col, alias, _ in node.specs)
        child_lat = ast_to_latex(node.child)
        return r"\gamma_{" + groups_lat + specs_lat + r"}\left(" + child_lat + r"\right)"
    if isinstance(node, Join):
        left_lat = ast_to_latex(node.left)
        right_lat = ast_to_latex(node.right)
        sym_map = {"inner": r"\bowtie", "left": "⟕", "right": "⟖"}
        sym = sym_map.get(node.kind, r"\bowtie")
        cond_lat = f"_{{{_cond_to_latex(node.cond)}}}" if node.cond else ""
        return r"\left(" + left_lat + r"\," + sym + cond_lat + r"\," + right_lat + r"\right)"
    if isinstance(node, SetOp):
        left_lat, right_lat = ast_to_latex(node.left), ast_to_latex(node.right)
        sym = {"UNION": r"\cup", "INTERSECT": r"\cap", "MINUS": "-", "DIFFERENCE": "-"}.get(node.op, r"\cup")
        return r"\left(" + left_lat + r"\," + sym + r"\," + right_lat + r"\right)"
    return str(node)


def _cond_to_latex(cond):
    if not cond:
        return ""
    kind = cond[0]
    if kind == "cmp":
        op_map = {"=": "=", "!=": r"\neq", ">": ">", "<": "<", ">=": r"\geq", "<=": r"\leq"}
        op = op_map.get(cond[1], cond[1])
        l_val = _esc_tx(cond[2][1]) if cond[2][0] == "col" else str(cond[2][1])
        r_val = _esc_tx(cond[3][1]) if cond[3][0] == "col" else str(cond[3][1])
        return f"{l_val} {op} {r_val}"
    if kind == "not":
        return r"\neg\left(" + _cond_to_latex(cond[1]) + r"\right)"
    sym = r"\land " if kind == "and" else r"\lor "
    return sym.join(_cond_to_latex(c) for c in cond[1])


def render_latex(latex, color, fontsize=16, max_w=None):
    try:
        clean_latex = str(latex).strip().strip("$").replace("\n", " ")
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0, 0, f"${clean_latex}$", fontsize=fontsize, color=color)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", pad_inches=0.05, transparent=True)
        plt.close(fig)
        buf.seek(0)
        img = Image.open(buf).convert("RGBA")
        if max_w and img.width > max_w:
            img = img.resize((max_w, max(1, img.height * max_w // img.width)), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        plt.close("all")
        return None


def _sort_key(v):
    return (0, v, "") if isinstance(v, (int, float)) and not isinstance(v, bool) else (1, 0, str(v).lower())


class UnifiedDatabaseLabGUI:

    def __init__(self, root):
        self.root = root
        root.title("Database Lab: ER Visualizer & Relational Algebra")
        root.geometry("1280x850")
        root.minsize(1020, 660)

        # Part 1 state
        self.original_p1_img = self.p1_img = None
        self.zoom_factor = 1.0

        # Part 2 state
        self.tables = {}
        self.sel_table = self.last_result = self.latex_img = self._expr = None
        self._view_columns, self._view_rows, self._sort = [], [], (None, False)
        self._after_val = None

        self.sidebar_expanded, self.dark = True, False
        self._registry = []

        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._pick_fonts()
        self._define_layouts()
        self._setup_style()
        self._build_header()
        self._build_status_bar()

        self.page_frames = {}
        for key in ("part1", "part2"):
            self.page_frames[key] = ttk.Frame(root)

        self._build_part1_tab()
        self._build_part2_tab()
        self.select_page("part1")
        self.apply_theme()

    # ------------------------------------------------------------------ theme
    def _themed(self, widget, **options):
        self._registry = [(w, o) for w, o in self._registry if w is not widget]
        self._registry.append((widget, options))
        widget.configure(**{k: COLORS[v] for k, v in options.items()})
        return widget

    def _pick_fonts(self):
        families = set(tkfont.families())
        self.font_family = next((f for f in FONTS if f in families), "TkDefaultFont")
        mono = next((f for f in MONOS if f in families), "TkFixedFont")
        ff = self.font_family
        self.f_body, self.f_bold = (ff, 10), (ff, 10, "bold")
        self.f_title, self.f_section = (ff, 16, "bold"), (ff, 11, "bold")
        self.f_small, self.f_mono = (ff, 9), (mono, 11)

    def _define_layouts(self):
        for orient, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
            self.style.layout(f"Thin.{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
                (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])

    def _setup_style(self):
        c, s = COLORS, self.style
        self.root.configure(bg=c["bg"])
        s.configure(".", font=self.f_body, background=c["bg"], foreground=c["ink"])
        s.configure("TFrame", background=c["bg"])
        s.configure("Card.TFrame", background=c["surface"])
        s.configure("TLabel", background=c["bg"], foreground=c["ink"])
        s.configure("Card.TLabel", background=c["surface"], foreground=c["ink"])
        s.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"], font=self.f_small)
        s.configure("CardMuted.TLabel", background=c["surface"], foreground=c["muted"], font=self.f_small)
        s.configure("Section.TLabel", background=c["surface"], foreground=c["ink"], font=self.f_section)

        def fill(bg):
            return dict(background=bg, bordercolor=bg, lightcolor=bg, darkcolor=bg)

        s.configure("TButton", padding=(14, 7), foreground=c["ink"], focusthickness=0, focuscolor=c["surface"],
                    borderwidth=1, **{**fill(c["surface"]), "bordercolor": c["border"]})
        s.map("TButton", background=[("active", c["accent_soft"]), ("pressed", c["accent_soft"])],
              bordercolor=[("active", c["accent"])], foreground=[("disabled", c["muted"])])
        s.configure("Accent.TButton", padding=(18, 8), foreground="#FFFFFF", font=self.f_bold, **fill(c["accent"]))
        s.map("Accent.TButton", background=[("active", c["accent_hover"]), ("pressed", c["accent_hover"])],
              bordercolor=[("active", c["accent_hover"])], lightcolor=[("active", c["accent_hover"])])
        s.configure("Tool.TButton", padding=(8, 4), font=self.f_small)

        s.configure("Treeview", foreground=c["ink"], rowheight=30, borderwidth=0, font=self.f_body,
                    fieldbackground=c["surface"], **fill(c["surface"]))
        s.map("Treeview", background=[("selected", c["accent_soft"])], foreground=[("selected", c["ink"])])
        s.configure("Treeview.Heading", background=c["heading"], foreground=c["ink"], font=self.f_bold,
                    padding=(10, 8), relief="flat", borderwidth=0)
        s.map("Treeview.Heading", background=[("active", c["accent_soft"])])
        s.configure("TPanedwindow", background=c["bg"])

        for orient in ("Vertical", "Horizontal"):
            name = f"Thin.{orient}.TScrollbar"
            s.configure(name, background=c["scroll"], troughcolor=c["surface"], bordercolor=c["surface"],
                        lightcolor=c["scroll"], darkcolor=c["scroll"], relief="flat", arrowsize=10)
            s.map(name, background=[("active", c["scroll_active"])])

    def toggle_theme(self, _event=None):
        self.dark = not self.dark
        COLORS.clear()
        COLORS.update(DARK if self.dark else LIGHT)
        self.apply_theme()

    def apply_theme(self):
        self._setup_style()
        alive = []
        for widget, options in self._registry:
            try:
                widget.configure(**{k: COLORS[v] for k, v in options.items()})
                alive.append((widget, options))
            except tk.TclError:
                pass
        self._registry = alive

        if hasattr(self, "query_text"):
            c = COLORS
            self.query_text.configure(
                bg=c["surface_alt"],
                fg=c["ink"],
                insertbackground=c["ink"],
                selectbackground=c["accent_soft"],
                selectforeground=c["ink"],
                highlightbackground=c["border"],
                highlightcolor=c["accent"],
                relief="flat",
                bd=1
            )
            self.query_text.tag_configure("err", background="#8B2626" if self.dark else "#F4B6B0", foreground="#FFFFFF" if self.dark else "#000000", underline=True)

        self._refresh_nav()
        self._configure_tree_tags()
        self._refresh_table_list()
        self.btn_theme.config(text="Light mode" if self.dark else "Dark mode")
        self._draw_p1_empty_state()
        if self._expr:
            self._show_expr(*self._expr)

    def _configure_tree_tags(self):
        self.tree.tag_configure("odd", background=COLORS["row_alt"])
        self.tree.tag_configure("even", background=COLORS["surface"])

    def _card(self, parent):
        return self._themed(tk.Frame(parent, highlightthickness=1), bg="surface", highlightbackground="border",
                            highlightcolor="border")

    # ------------------------------------------------------- header / status
    def _build_header(self):
        header = self._themed(tk.Frame(self.root), bg="header")
        header.pack(fill=tk.X)
        top = self._themed(tk.Frame(header), bg="header")
        top.pack(fill=tk.X, padx=24, pady=(14, 0))
        self._themed(tk.Label(top, text="Database Lab", font=self.f_title), bg="header", fg="header_ink").pack(side=tk.LEFT)
        self._themed(tk.Label(top, text="ER mapping and relational algebra", font=self.f_small), bg="header", fg="header_sub").pack(side=tk.LEFT, padx=(14, 0), pady=(5, 0))

        self.btn_theme = self._themed(tk.Label(top, text="Dark mode", font=self.f_small, cursor="hand2"), bg="header", fg="header_sub")
        self.btn_theme.pack(side=tk.RIGHT, pady=(5, 0))
        self.btn_theme.bind("<Button-1>", self.toggle_theme)

        nav = self._themed(tk.Frame(header), bg="header")
        nav.pack(fill=tk.X, padx=24, pady=(10, 0))
        self.nav_items = {}
        for key, text in (("part1", "ER to relational"), ("part2", "Relational algebra")):
            item = tk.Frame(nav)
            item.pack(side=tk.LEFT, padx=(0, 26))
            label = tk.Label(item, text=text, font=self.f_bold, cursor="hand2")
            label.pack(pady=(0, 6))
            bar = tk.Frame(item, height=3)
            bar.pack(fill=tk.X)
            label.bind("<Button-1>", lambda e, k=key: self.select_page(k))
            self.nav_items[key] = (item, label, bar)

    def _refresh_nav(self):
        c = COLORS
        for key, (item, label, bar) in self.nav_items.items():
            active = key == getattr(self, "current_page", None)
            item.config(bg=c["header"])
            label.config(bg=c["header"], fg=c["header_ink"] if active else c["header_sub"])
            bar.config(bg="#5DADEC" if active else c["header"])

    def select_page(self, key):
        for frame in self.page_frames.values():
            frame.pack_forget()
        self.page_frames[key].pack(fill=tk.BOTH, expand=True)
        self.current_page = key
        self._refresh_nav()

    def _build_status_bar(self):
        bar = self._themed(tk.Frame(self.root, highlightthickness=1), bg="surface", highlightbackground="border")
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_dot = self._themed(tk.Label(bar, text="\u25CF", font=self.f_small), bg="surface", fg="muted")
        self.status_dot.pack(side=tk.LEFT, padx=(14, 4), pady=6)
        self.status_text = self._themed(tk.Label(bar, text="Ready", font=self.f_small, anchor=tk.W), bg="surface", fg="ink")
        self.status_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def set_status(self, message, kind="info"):
        self._themed(self.status_dot, bg="surface", fg={"info": "muted", "ok": "ok", "error": "error"}[kind])
        self.status_text.config(text=message)

    # ---------------------------------------------------------------- PART 1
    def _build_part1_tab(self):
        page = self.page_frames["part1"]
        top_bar = ttk.Frame(page)
        top_bar.pack(fill=tk.X, padx=20, pady=(16, 8))
        ttk.Button(top_bar, text="Open ERD JSON", style="Accent.TButton", command=self.process_part1).pack(side=tk.LEFT)
        self.lbl_p1_status = ttk.Label(top_bar, text="No ERD loaded.", style="Muted.TLabel")
        self.lbl_p1_status.pack(side=tk.LEFT, padx=14)

        zoom_box = ttk.Frame(top_bar)
        zoom_box.pack(side=tk.RIGHT)
        ttk.Button(zoom_box, text="\u2212", width=3, style="Tool.TButton", command=lambda: self._set_zoom(self.zoom_factor / 1.15)).pack(side=tk.LEFT, padx=2)
        self.lbl_zoom = ttk.Label(zoom_box, text="100%", style="Muted.TLabel", width=6, anchor=tk.CENTER)
        self.lbl_zoom.pack(side=tk.LEFT)
        ttk.Button(zoom_box, text="+", width=3, style="Tool.TButton", command=lambda: self._set_zoom(self.zoom_factor * 1.15)).pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_box, text="Fit", style="Tool.TButton", command=self._fit_to_window).pack(side=tk.LEFT, padx=(8, 2))

        card = self._card(page)
        card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(4, 16))
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)
        self.canvas = self._themed(tk.Canvas(card, highlightthickness=0, cursor="fleur"), bg="surface")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(ev, self.zoom_image)
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))

    def _draw_p1_empty_state(self):
        if self.original_p1_img is not None:
            return
        self.canvas.delete("empty")
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.create_text(w / 2, h / 2 - 12, text="No schema to show yet", font=(self.font_family, 14, "bold"), fill=COLORS["ink"], tags="empty")

    def process_part1(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                erd_json = json.load(f)
            tables, foreign_keys = ERTransformer(erd_json).transform()
            out_dir = "outputs"
            os.makedirs(out_dir, exist_ok=True)
            out_base = os.path.join(out_dir, "schema_diagram")
            RelationalSchemaVisualizer(tables, foreign_keys).render(output_path=out_base)
            with Image.open(f"{out_base}.png") as img:
                self.original_p1_img = img.copy()
            self.canvas.delete("empty")
            self.zoom_factor = 1.0
            self._fit_to_window()
            self.lbl_p1_status.config(text=os.path.basename(file_path))
            self.set_status("Generated relational schema successfully.", "ok")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def zoom_image(self, event):
        if self.original_p1_img is None:
            return
        up = event.num == 4 or event.delta > 0
        self._set_zoom(self.zoom_factor * (1.15 if up else 1 / 1.15))

    def _set_zoom(self, value):
        self.zoom_factor = max(0.1, min(value, 5.0))
        self._update_p1_image_display()

    def _fit_to_window(self):
        if self.original_p1_img is None:
            return
        cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        iw, ih = self.original_p1_img.size
        self._set_zoom(min(cw / iw, ch / ih) * 0.96)

    def _update_p1_image_display(self):
        w = max(1, int(self.original_p1_img.width * self.zoom_factor))
        h = max(1, int(self.original_p1_img.height * self.zoom_factor))
        self.p1_img = ImageTk.PhotoImage(self.original_p1_img.resize((w, h), Image.Resampling.LANCZOS))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.p1_img, anchor=tk.NW)
        self.lbl_zoom.config(text=f"{int(self.zoom_factor * 100)}%")

    # ---------------------------------------------------------------- PART 2
    def _build_part2_tab(self):
        page = self.page_frames["part2"]
        top_bar = ttk.Frame(page)
        top_bar.pack(fill=tk.X, padx=20, pady=(16, 8))
        ttk.Button(top_bar, text="Open dataset JSON", style="Accent.TButton", command=self.load_p2_dataset).pack(side=tk.LEFT)
        self.lbl_p2_status = ttk.Label(top_bar, text="No dataset loaded.", style="Muted.TLabel")
        self.lbl_p2_status.pack(side=tk.LEFT, padx=14)

        self.paned = ttk.PanedWindow(page, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=20, pady=(4, 16))
        self._build_sidebar(self.paned)

        main = ttk.Frame(self.paned)
        self.paned.add(main, weight=3)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)
        self._build_query_card(main)
        self._build_expression_card(main)
        self._build_result_card(main)

    def _build_sidebar(self, parent):
        self.side = self._card(parent)
        parent.add(self.side, weight=1)

        head = ttk.Frame(self.side, style="Card.TFrame")
        head.pack(fill=tk.X, padx=12, pady=(12, 6))
        self.lbl_side_title = ttk.Label(head, text="Tables", style="Section.TLabel")
        self.lbl_side_title.pack(side=tk.LEFT)
        self.btn_toggle_sidebar = ttk.Button(head, text="◀", width=3, style="Tool.TButton", command=self.toggle_sidebar)
        self.btn_toggle_sidebar.pack(side=tk.RIGHT)

        self.side_content = ttk.Frame(self.side, style="Card.TFrame")
        self.side_content.pack(fill=tk.BOTH, expand=True)

        list_box = ttk.Frame(self.side_content, style="Card.TFrame")
        list_box.pack(fill=tk.BOTH, expand=True, padx=1)
        list_box.grid_rowconfigure(0, weight=1)
        list_box.grid_columnconfigure(0, weight=1)
        self.tables_canvas = self._themed(tk.Canvas(list_box, highlightthickness=0, height=260, yscrollincrement=20), bg="surface")
        vsb = ttk.Scrollbar(list_box, orient=tk.VERTICAL, style="Thin.Vertical.TScrollbar", command=self.tables_canvas.yview)
        self.tables_canvas.configure(yscrollcommand=vsb.set)
        self.tables_canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.tables_inner = self._themed(tk.Frame(self.tables_canvas), bg="surface")
        self._tables_win = self.tables_canvas.create_window((0, 0), window=self.tables_inner, anchor="nw")

        def _on_canvas_configure(e):
            self.tables_canvas.itemconfig(self._tables_win, width=e.width)

        self.tables_canvas.bind("<Configure>", _on_canvas_configure)
        self.tables_inner.bind("<Configure>", lambda e: self.tables_canvas.configure(scrollregion=self.tables_canvas.bbox("all")))

        self.lbl_side_empty = self._themed(
            tk.Label(self.tables_canvas, text="Tables from your\ndataset appear here.", font=self.f_small, justify=tk.CENTER), bg="surface", fg="muted")
        self.lbl_side_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        self._themed(tk.Frame(self.side_content, height=1), bg="border").pack(fill=tk.X, pady=(0, 10))
        ttk.Label(self.side_content, text="Columns", style="Section.TLabel").pack(anchor=tk.W, padx=16, pady=(0, 4))
        self.lbl_schema = ttk.Label(self.side_content, text="Select a table.", style="CardMuted.TLabel", wraplength=280, justify=tk.LEFT)
        self.lbl_schema.pack(anchor=tk.W, padx=16, pady=(0, 16), fill=tk.X)

    def toggle_sidebar(self):
        self.sidebar_expanded = not self.sidebar_expanded
        if self.sidebar_expanded:
            self.lbl_side_title.pack(side=tk.LEFT)
            self.side_content.pack(fill=tk.BOTH, expand=True)
        else:
            self.side_content.pack_forget()
            self.lbl_side_title.pack_forget()
        self.btn_toggle_sidebar.config(text="◀" if self.sidebar_expanded else "▶")

    def _refresh_table_list(self, select=None):
        for w in self.tables_inner.winfo_children():
            w.destroy()
        active = select if select in self.tables else self.sel_table
        for name, table in self.tables.items():
            self._add_table_row(name, table, name == active)
        if self.tables:
            self.lbl_side_empty.place_forget()
        else:
            self.lbl_side_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _add_table_row(self, name, table, selected):
        c = COLORS
        bg = c["accent_soft"] if selected else c["surface"]
        row = tk.Frame(self.tables_inner, bg=bg, cursor="hand2", highlightthickness=1,
                       highlightbackground=c["accent"] if selected else c["border"])
        row.pack(fill=tk.X, padx=8, pady=(0, 10))

        top = tk.Frame(row, bg=bg)
        top.pack(fill=tk.X, padx=14, pady=(12, 4))
        tk.Label(top, text=name, font=self.f_bold, bg=bg, fg=c["ink"]).pack(side=tk.LEFT)
        tk.Label(top, text=f"{len(table.data)} rows", font=self.f_small, bg=bg, fg=c["muted"]).pack(side=tk.RIGHT)

        lbl = tk.Label(row, text="base table", font=self.f_small, bg=bg, fg=c["muted"], anchor=tk.W)
        lbl.pack(fill=tk.X, padx=14, pady=(0, 12))

        widgets = [row, top, lbl, *top.winfo_children()]
        for w in widgets:
            w.bind("<Button-1>", lambda e, n=name: self._select_table(n))
            w.bind("<Double-Button-1>", lambda e, n=name: self._insert_snippet(n))

    def _select_table(self, name):
        self.sel_table = name
        table = self.tables[name]
        self.lbl_schema.config(text=", ".join(table.columns) if table.columns else "(no columns)")
        self._refresh_table_list()

    def _build_query_card(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=16, pady=12)

        op_bar = ttk.Frame(inner, style="Card.TFrame")
        op_bar.pack(fill=tk.X, pady=(0, 8))
        for i, (label, text, back) in enumerate(SNIPPETS):
            ttk.Button(op_bar, text=label, style="Tool.TButton",
                       command=lambda t=text, b=back: self._insert_snippet(t, b)).grid(row=i // 6, column=i % 6, padx=2, pady=2)

        self.query_text = tk.Text(inner, height=4, font=self.f_mono, undo=True, wrap=tk.WORD)
        self.query_text.pack(fill=tk.X, pady=(4, 8))
        self.query_text.bind("<KeyRelease>", self._schedule_validation)

        run_bar = ttk.Frame(inner, style="Card.TFrame")
        run_bar.pack(fill=tk.X)
        ttk.Button(run_bar, text="Run Query", style="Accent.TButton", command=self.run_console_query).pack(side=tk.LEFT)
        ttk.Button(run_bar, text="Clear", command=lambda: self.query_text.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=8)
        self.lbl_query_err = ttk.Label(run_bar, text="", style="CardMuted.TLabel")
        self.lbl_query_err.pack(side=tk.LEFT, padx=12)

    def _insert_snippet(self, text, back=0):
        self.query_text.insert(tk.INSERT, text)
        if back:
            self.query_text.mark_set(tk.INSERT, f"insert-{back}c")
        self.query_text.focus_set()
        self._schedule_validation()

    def _schedule_validation(self, _=None):
        if self._after_val:
            self.root.after_cancel(self._after_val)
        self._after_val = self.root.after(300, self._validate_query)

    def _validate_query(self):
        self.query_text.tag_remove("err", "1.0", tk.END)
        q = self.query_text.get("1.0", "end-1c").strip()
        if not q:
            self.lbl_query_err.config(text="")
            return
        try:
            parse(q)
            self.lbl_query_err.config(text="Syntax OK", foreground=COLORS["ok"])
        except QueryError as e:
            self.lbl_query_err.config(text=f"Error: {e.message}", foreground=COLORS["error"])

    def run_console_query(self):
        query = self.query_text.get("1.0", "end-1c").strip()
        if not query:
            return
        try:
            parsed_ast = parse(query)
            latex_expr = ast_to_latex(parsed_ast)
            executor = Executor(self.tables)
            result = executor.run(query)
            self.last_result = result
            self.render_tree_data(result.columns, result.data)
            self._show_expr(latex_expr, query)
            self.set_status(f"Executed successfully. Returned {len(result.data)} row(s).", "ok")
        except QueryError as e:
            self.lbl_query_err.config(text=e.message, foreground=COLORS["error"])
            self.set_status("Query execution failed.", "error")
        except Exception as e:
            messagebox.showerror("Execution Error", str(e))

    def _build_expression_card(self, parent):
        card = self._card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill=tk.X, padx=16, pady=8)

        ttk.Label(inner, text="Expression Pipeline", style="CardMuted.TLabel").pack(side=tk.LEFT, padx=(0, 14))

        expr_box = ttk.Frame(inner, style="Card.TFrame")
        expr_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        expr_box.grid_rowconfigure(0, weight=1)
        expr_box.grid_columnconfigure(0, weight=1)

        self.expr_canvas = self._themed(tk.Canvas(expr_box, height=45, highlightthickness=0), bg="surface")
        hsb = ttk.Scrollbar(expr_box, orient=tk.HORIZONTAL, style="Thin.Horizontal.TScrollbar", command=self.expr_canvas.xview)
        self.expr_canvas.configure(xscrollcommand=hsb.set)

        self.expr_canvas.grid(row=0, column=0, sticky="nsew")
        hsb.grid(row=1, column=0, sticky="ew")

        self.lbl_expr = self._themed(
            tk.Label(self.expr_canvas, text="Enter a query to construct your relational query.", font=self.f_mono,
                     anchor=tk.W, justify=tk.LEFT), bg="surface", fg="muted")
        self._expr_win = self.expr_canvas.create_window((0, 0), window=self.lbl_expr, anchor="w")
        self.lbl_expr.bind("<Configure>", lambda e: self.expr_canvas.configure(scrollregion=self.expr_canvas.bbox("all")))

    def _show_expr(self, latex, plain):
        clean_plain = str(plain).strip().strip("$")
        clean_latex = str(latex).strip().strip("$")
        self._expr = (clean_latex, clean_plain)

        img = render_latex(clean_latex, COLORS["ink"], fontsize=10, max_w=None)
        if img:
            self.latex_img = img
            self.lbl_expr.config(image=img, text="")
            self.expr_canvas.config(height=max(45, img.height() + 10))
        else:
            self.lbl_expr.config(image="", text=clean_plain)

    def _build_result_card(self, parent):
        card = self._card(parent)
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        head = ttk.Frame(card, style="Card.TFrame")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 8))
        ttk.Label(head, text="Result", style="Section.TLabel").pack(side=tk.LEFT)
        self.lbl_row_count = ttk.Label(head, text="", style="CardMuted.TLabel")
        self.lbl_row_count.pack(side=tk.RIGHT)

        wrap = ttk.Frame(card, style="Card.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, style="Thin.Vertical.TScrollbar", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, style="Thin.Horizontal.TScrollbar", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.lbl_tree_empty = self._themed(
            tk.Label(self.tree, text="Results will appear here after you run a query.", font=self.f_body),
            bg="surface", fg="muted")
        self.lbl_tree_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self._configure_tree_tags()

    def load_p2_dataset(self):
        file_path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tables = {t_name: Table(t_name, list(dict.fromkeys(k for r in rows for k in r)), rows) for t_name, rows in data.items()}

            self.tables, self.last_result, self.sel_table = tables, None, None
            self._clear_result()
            self._refresh_table_list()
            name = os.path.basename(file_path)
            self.lbl_p2_status.config(text=f"{name}  \u2022  {len(tables)} table(s)")
            self.set_status(f"Loaded {len(tables)} table(s) from {name}.", "ok")

            if tables:
                first = next(iter(tables))
                self._select_table(first)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _clear_result(self):
        self._expr = None
        self.render_tree_data([], [])
        self.lbl_tree_empty.config(text="Results will appear here after you run a query.", font=self.f_body)
        self.lbl_tree_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.lbl_row_count.config(text="")
        self.lbl_expr.config(image="", text="Run a query to see its relational algebra expression.")

    def render_tree_data(self, columns, rows):
        self._view_columns, self._view_rows, self._sort = list(columns), list(rows), (None, False)
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = columns
        body_font, head_font = tkfont.Font(font=self.f_body), tkfont.Font(font=self.f_bold)

        for i, col in enumerate(columns):
            values = [r.get(col) for r in rows]
            sample = ["NULL" if v is None else str(v) for v in values[:200]]
            widest = max([head_font.measure(str(col)) + 24] + [body_font.measure(s) for s in sample])
            self.tree.heading(col, text=col, anchor=tk.W, command=lambda c=col: self._sort_by(c))
            self.tree.column(col, anchor=tk.W, width=max(120, min(widest + 48, 360)), minwidth=80,
                             stretch=(i == len(columns) - 1))

        self._fill_tree(self._view_rows)
        if rows:
            self.lbl_tree_empty.place_forget()
        else:
            self.lbl_tree_empty.config(text="This query returned no rows.")
            self.lbl_tree_empty.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        plural = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
        self.lbl_row_count.config(text=f"{plural(len(rows), 'row')}  \u2022  {plural(len(columns), 'column')}")

    def _fill_tree(self, rows):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            vals = ["NULL" if r.get(c) is None else r.get(c) for c in self._view_columns]
            self.tree.insert("", tk.END, values=vals, tags=("odd" if i % 2 else "even",))

    def _sort_by(self, col):
        prev_col, desc = self._sort
        desc = (not desc) if prev_col == col else False
        self._sort = (col, desc)
        present = sorted((r for r in self._view_rows if r.get(col) is not None),
                         key=lambda r: _sort_key(r.get(col)), reverse=desc)
        missing = [r for r in self._view_rows if r.get(col) is None]
        self._fill_tree(present + missing)
        for c in self._view_columns:
            self.tree.heading(c, text=c + (("  \u25BC" if desc else "  \u25B2") if c == col else ""))


def main():
    root = tk.Tk()
    UnifiedDatabaseLabGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()