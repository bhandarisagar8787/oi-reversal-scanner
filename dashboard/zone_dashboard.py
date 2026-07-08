"""
zone_dashboard.py
=================
Professional desktop GUI — card-style layout, dark theme, live auto-refresh.
Reads directly from market_data.sqlite3 (read-only).
Run alongside oi_reversal_scanner.py; this window picks up new zones automatically.

    python zone_dashboard.py
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, font as tkfont
from datetime import datetime, timezone, timedelta

import pandas as pd
from app import market_db as mdb

def _confirm_close_ist(ts_utc_epoch: int) -> str:
    """Display confirm time as bar CLOSE (open + 30 min) — matches Pine behaviour."""
    bar_open  = datetime.fromtimestamp(int(ts_utc_epoch), tz=IST)
    bar_close = bar_open + timedelta(minutes=30)
    return bar_close.strftime("%Y-%m-%d %H:%M:%S IST")


REFRESH_MS   = 2_000   # auto-refresh every 2 s
IST          = timezone(timedelta(hours=5, minutes=30))

# ── Colour palette ────────────────────────────────────────────────────────────
BG          = "#0b0e14"
SURFACE     = "#131722"
SURFACE2    = "#1c2336"
BORDER      = "#2a2e3d"
TEXT        = "#d1d5db"
TEXT_DIM    = "#6b7280"
BULL_FG     = "#00e676"
BEAR_FG     = "#ff5252"
PASS_BADGE  = "#1a4731"
PASS_TXT    = "#00e676"
FAIL_BADGE  = "#3b1a1a"
FAIL_TXT    = "#ff5252"
ACCENT      = "#3b82f6"
HEADER_BG   = "#161b27"

COLUMNS = [
    # (internal_key,   header,          width, anchor)
    ("symbol",        "Symbol",         100,   "w"),
    ("zone_type",     "Type",            60,   "center"),
    ("extreme_ist",   "Extreme (IST)",  170,   "w"),
    ("confirm_ist",   "Confirm close(IST)", 185, "w"),
    ("zone_top",      "Top",             90,   "e"),
    ("zone_bottom",   "Bottom",          90,   "e"),
    ("range_pts",     "Range",           70,   "e"),
    ("oi_change_pct", "OI Δ%",           80,   "e"),
    ("status",        "Status",         110,   "center"),
]

SORT_UNDERLYING = {
    "extreme_ist": "extreme_ts_utc",
    "confirm_ist": "confirm_ts_utc",
}


class ZoneDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OI Reversal Zone Scanner")
        self.geometry("1280x720")
        self.minsize(900, 500)
        self.configure(bg=BG)

        self.sort_col     = "confirm_ts_utc"
        self.sort_reverse = True
        self._last_count  = -1

        self._setup_fonts()
        self._build_header()
        self._build_filter_bar()
        self._build_table()
        self._build_summary_cards()
        self._build_statusbar()

        self.refresh()
        self.after(REFRESH_MS, self._auto_refresh)

    # ─────────────────────────────────────── setup
    def _setup_fonts(self):
        self.font_title  = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        self.font_label  = tkfont.Font(family="Segoe UI", size=10)
        self.font_mono   = tkfont.Font(family="Consolas", size=10)
        self.font_card_n = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        self.font_card_l = tkfont.Font(family="Segoe UI", size=9)
        self.font_badge  = tkfont.Font(family="Segoe UI", size=9, weight="bold")

    # ─────────────────────────────────────── header
    def _build_header(self):
        hdr = tk.Frame(self, bg=HEADER_BG, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="⬡", bg=HEADER_BG, fg=ACCENT,
                 font=tkfont.Font(size=22)).pack(side="left", padx=(18, 6), pady=8)
        tk.Label(hdr, text="OI Reversal Zone Scanner", bg=HEADER_BG, fg=TEXT,
                 font=self.font_title).pack(side="left", pady=8)

        self.clock_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self.clock_var, bg=HEADER_BG, fg=TEXT_DIM,
                 font=self.font_label).pack(side="right", padx=18)
        self._tick_clock()

    def _tick_clock(self):
        ist_now = datetime.now(IST).strftime("%Y-%m-%d  %H:%M:%S IST")
        self.clock_var.set(ist_now)
        self.after(1000, self._tick_clock)

    # ─────────────────────────────────────── filter bar
    def _build_filter_bar(self):
        bar = tk.Frame(self, bg=SURFACE, pady=10)
        bar.pack(fill="x", padx=0)

        inner = tk.Frame(bar, bg=SURFACE)
        inner.pack(padx=18, fill="x")

        # Symbol filter
        tk.Label(inner, text="Symbol", bg=SURFACE, fg=TEXT_DIM,
                 font=self.font_label).grid(row=0, column=0, padx=(0, 6))
        self.symbol_var = tk.StringVar(value="All")
        self.symbol_combo = ttk.Combobox(inner, textvariable=self.symbol_var,
                                          state="readonly", width=16,
                                          font=self.font_label)
        self.symbol_combo.grid(row=0, column=1, padx=(0, 24))
        self.symbol_combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())

        # Zone type filter
        tk.Label(inner, text="Zone type", bg=SURFACE, fg=TEXT_DIM,
                 font=self.font_label).grid(row=0, column=2, padx=(0, 6))
        self.type_var = tk.StringVar(value="All")
        ttk.Combobox(inner, textvariable=self.type_var, state="readonly",
                     values=["All", "bull", "bear"], width=8,
                     font=self.font_label).grid(row=0, column=3, padx=(0, 24))
        self.type_var.trace_add("write", lambda *_: self.refresh())

        # OI-passed toggle
        self.only_passed_var = tk.BooleanVar(value=True)
        cb = tk.Checkbutton(inner, text="OI-filter passed only",
                             variable=self.only_passed_var, command=self.refresh,
                             bg=SURFACE, fg=TEXT, selectcolor=SURFACE2,
                             activebackground=SURFACE, activeforeground=TEXT,
                             font=self.font_label)
        cb.grid(row=0, column=4, padx=(0, 24))

        # Refresh button
        tk.Button(inner, text="↺  Refresh", command=self.refresh,
                  bg=ACCENT, fg="white", relief="flat", padx=14, pady=4,
                  font=self.font_label, cursor="hand2",
                  activebackground="#2563eb").grid(row=0, column=5, padx=(0, 0))

        # Style comboboxes
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=SURFACE2, background=SURFACE2,
                         foreground=TEXT, selectbackground=SURFACE2,
                         selectforeground=TEXT, bordercolor=BORDER, arrowcolor=TEXT_DIM)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE2)],
                  selectbackground=[("readonly", SURFACE2)],
                  selectforeground=[("readonly", TEXT)])

    # ─────────────────────────────────────── table
    def _build_table(self):
        style = ttk.Style(self)
        style.configure("Zone.Treeview",
                         background=SURFACE, fieldbackground=SURFACE,
                         foreground=TEXT, rowheight=30,
                         font=("Consolas", 10))
        style.configure("Zone.Treeview.Heading",
                         background=SURFACE2, foreground=TEXT_DIM,
                         font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Zone.Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])

        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        col_ids = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(frame, columns=col_ids, show="headings",
                                  selectmode="browse", style="Zone.Treeview")

        for col_id, label, width, anchor in COLUMNS:
            self.tree.heading(col_id, text=label,
                               command=lambda c=col_id: self._sort_by(c))
            self.tree.column(col_id, width=width, anchor=anchor, minwidth=50)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # Row tags
        self.tree.tag_configure("bull",    foreground=BULL_FG)
        self.tree.tag_configure("bear",    foreground=BEAR_FG)
        self.tree.tag_configure("fail",    foreground=TEXT_DIM)
        self.tree.tag_configure("row_odd", background="#141824")

    # ─────────────────────────────────────── summary cards
    def _build_summary_cards(self):
        self.cards_frame = tk.Frame(self, bg=BG)
        self.cards_frame.pack(fill="x", padx=14, pady=(10, 4))

        self._bull_n   = tk.StringVar(value="0")
        self._bear_n   = tk.StringVar(value="0")
        self._total_n  = tk.StringVar(value="0")
        self._sym_n    = tk.StringVar(value="0")

        cards = [
            ("Bull Zones",   self._bull_n,  BULL_FG,  SURFACE),
            ("Bear Zones",   self._bear_n,  BEAR_FG,  SURFACE),
            ("Total Zones",  self._total_n, ACCENT,   SURFACE),
            ("Symbols w/ zones", self._sym_n, TEXT_DIM, SURFACE),
        ]
        for label, var, col, bg in cards:
            self._make_card(self.cards_frame, label, var, col, bg)

    def _make_card(self, parent, label, var, fg, bg):
        card = tk.Frame(parent, bg=bg, padx=20, pady=12,
                         highlightbackground=BORDER, highlightthickness=1)
        card.pack(side="left", padx=(0, 10), fill="y")
        tk.Label(card, text=label, bg=bg, fg=TEXT_DIM,
                 font=self.font_card_l).pack(anchor="w")
        tk.Label(card, textvariable=var, bg=bg, fg=fg,
                 font=self.font_card_n).pack(anchor="w")

    # ─────────────────────────────────────── status bar
    def _build_statusbar(self):
        bar = tk.Frame(self, bg=SURFACE2, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_var = tk.StringVar(value="Loading …")
        tk.Label(bar, textvariable=self.status_var, bg=SURFACE2, fg=TEXT_DIM,
                 anchor="w", font=self.font_label, padx=14).pack(fill="x", pady=5)

    # ─────────────────────────────────────── refresh
    def _auto_refresh(self):
        self.refresh()
        self.after(REFRESH_MS, self._auto_refresh)

    def refresh(self):
        symbols = mdb.get_all_symbols()
        cur_sym = self.symbol_var.get()
        self.symbol_combo["values"] = ["All"] + symbols
        if cur_sym not in (["All"] + symbols):
            self.symbol_var.set("All")

        chosen      = self.symbol_var.get()
        chosen_type = self.type_var.get()
        only_passed = self.only_passed_var.get()

        targets = symbols if chosen == "All" else [chosen]
        frames  = []
        for sym in targets:
            z = mdb.get_zones(symbol=sym, only_passed=only_passed)
            if not z.empty:
                frames.append(z)

        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        # Type filter
        if not df.empty and chosen_type != "All":
            df = df[df["zone_type"] == chosen_type]

        self._update_cards(df)
        self._render(df)

        total_bars = sum(len(mdb.get_bars(s)) for s in symbols)
        self.status_var.set(
            f"Symbols tracked: {len(symbols)}   │   "
            f"Total bars in DB: {total_bars}   │   "
            f"Zones displayed: {len(df)}   │   "
            f"Auto-refresh: every {REFRESH_MS//1000}s   │   "
            f"Scanner writes every 30 min"
        )

    def _update_cards(self, df: pd.DataFrame):
        if df.empty:
            self._bull_n.set("0")
            self._bear_n.set("0")
            self._total_n.set("0")
            self._sym_n.set("0")
            return
        bull  = (df["zone_type"] == "bull").sum()
        bear  = (df["zone_type"] == "bear").sum()
        self._bull_n.set(str(bull))
        self._bear_n.set(str(bear))
        self._total_n.set(str(len(df)))
        self._sym_n.set(str(df["symbol"].nunique()))

    def _render(self, df: pd.DataFrame):
        for row in self.tree.get_children():
            self.tree.delete(row)
        if df.empty:
            return

        df = df.copy()
        df["extreme_ist"] = df["extreme_ts_utc"].apply(mdb.utc_epoch_to_ist_str)
        df["confirm_ist"] = df["confirm_ts_utc"].apply(_confirm_close_ist)
        df["range_pts"]   = (df["zone_top"] - df["zone_bottom"]).round(2)
        df["status"]      = df["passed_oi_filter"].map({1: "✓ PASS", 0: "✗ FAIL"})

        sort_col = SORT_UNDERLYING.get(self.sort_col, self.sort_col)
        if sort_col in df.columns:
            df = df.sort_values(sort_col, ascending=not self.sort_reverse)
        else:
            df = df.sort_values("confirm_ts_utc", ascending=False)

        for idx, (_, r) in enumerate(df.iterrows()):
            passed = bool(r.get("passed_oi_filter", 1))
            if not passed:
                tag = "fail"
            elif r["zone_type"] == "bull":
                tag = "bull"
            else:
                tag = "bear"

            pct_str = (f"{r['oi_change_pct']:.2f}%"
                       if pd.notna(r.get("oi_change_pct")) else "n/a")
            values = [
                r["symbol"],
                r["zone_type"].upper(),
                r["extreme_ist"],
                r["confirm_ist"],
                f"{r['zone_top']:.2f}",
                f"{r['zone_bottom']:.2f}",
                f"{r['range_pts']:.2f}",
                pct_str,
                r["status"],
            ]
            tags = (tag, "row_odd") if idx % 2 else (tag,)
            self.tree.insert("", "end", values=values, tags=tags)

    def _sort_by(self, col_id: str):
        underlying = SORT_UNDERLYING.get(col_id, col_id)
        if self.sort_col == underlying:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col    = underlying
            self.sort_reverse = True
        self.refresh()


if __name__ == "__main__":
    mdb.init_db()
    app = ZoneDashboard()
    app.mainloop()
