from __future__ import annotations

import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from applyflow.analyze import read_job
from applyflow.config import load_profile, update_profile
from applyflow.hunt import discover_jobs, prepare_and_apply
from applyflow.resume import parse_resume, save_resume
from applyflow.store import get_job, init_db, list_applications, list_jobs

BG = "#F3F5F8"
INK = "#0F172A"
MUTED = "#5B6B7C"
HEADER = "#0B1220"
ACCENT = "#0F766E"
CARD = "#FFFFFF"


def _enable_windows_dpi() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                import ctypes

                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _configure_scaling(root: tk.Misc) -> float:
    try:
        dpi = float(root.winfo_fpixels("1i"))
    except Exception:
        dpi = 96.0
    if dpi < 72:
        dpi = 96.0
    root.tk.call("tk", "scaling", dpi / 72.0)
    return max(dpi / 96.0, 1.0)


class ApplyflowGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        init_db()
        self._scale = _configure_scaling(self)
        self.title("Applyflow")
        self.configure(bg=BG)
        self.jobs: list = []
        self._busy = False
        self._layout_job: str | None = None
        self._fit_to_screen()
        self._build_style()
        self._build()
        self._load_profile_fields()
        self._refresh_resume()
        self._load_saved_jobs()
        self._load_history()
        self._refresh_fill_status()
        self.after(80, self._bring_to_front)

    def _fit_to_screen(self) -> None:
        self.update_idletasks()
        sw = max(self.winfo_screenwidth(), 1280)
        sh = max(self.winfo_screenheight(), 800)
        width = int(sw * 0.96)
        height = int(sh * 0.94)
        x = max((sw - width) // 2, 0)
        y = max((sh - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(self._px(1100), sw - 40), min(self._px(740), sh - 40))
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

    def _bring_to_front(self) -> None:
        self.deiconify()
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(700, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        self.focus_force()
        try:
            import ctypes

            hwnd = int(self.winfo_id())
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _px(self, value: int) -> int:
        return max(1, int(value * self._scale))

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("TNotebook", background=BG)
        style.configure("TNotebook.Tab", padding=[self._px(14), self._px(6)], font=("Segoe UI", 10))
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=INK, font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), background=HEADER, foreground="#F8FAFC")
        style.configure("Sub.TLabel", font=("Segoe UI", 10), background=HEADER, foreground="#CBD5E1")
        style.configure("Hint.TLabel", foreground=MUTED, background=BG, font=("Segoe UI", 9))
        style.configure("Status.TLabel", foreground=INK, background=BG, font=("Segoe UI", 9))
        style.configure("Treeview", rowheight=self._px(32), font=("Segoe UI", 10), background=CARD)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Hunt.TButton", font=("Segoe UI", 10, "bold"), padding=6)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.status_var = tk.StringVar(value="Ready")

        header = tk.Frame(self, bg=HEADER)
        header.grid(row=0, column=0, sticky="ew")
        inner = tk.Frame(header, bg=HEADER)
        inner.pack(fill="x", padx=self._px(18), pady=self._px(14))
        tk.Label(
            inner,
            text="Applyflow",
            bg=HEADER,
            fg="#F8FAFC",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        self.header_var = tk.StringVar(value="Upload a resume, then hunt roles that fit your graduation timeline.")
        tk.Label(
            inner,
            textvariable=self.header_var,
            bg=HEADER,
            fg="#CBD5E1",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=10, pady=(8, 0))
        hunt_tab = ttk.Frame(self.tabs)
        hist_tab = ttk.Frame(self.tabs)
        hunt_tab.columnconfigure(0, weight=1)
        hunt_tab.rowconfigure(0, weight=1)
        hist_tab.columnconfigure(0, weight=1)
        hist_tab.rowconfigure(0, weight=1)
        self.tabs.add(hunt_tab, text="  Hunt  ")
        self.tabs.add(hist_tab, text="  History  ")
        self._build_hunt(hunt_tab)
        self._build_history(hist_tab)

        ttk.Label(self, textvariable=self.status_var, style="Status.TLabel").grid(
            row=2, column=0, sticky="w", padx=16, pady=8
        )

    def _build_hunt(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        shell = ttk.Panedwindow(parent, orient="vertical")
        shell.grid(row=0, column=0, sticky="nsew")
        self._vpanes = shell

        top = ttk.Frame(shell)
        top.columnconfigure(0, weight=1)
        profile = ttk.LabelFrame(top, text="Your details")
        profile.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        for i in range(8):
            profile.columnconfigure(i, weight=1)
        self.first_var = tk.StringVar()
        self.last_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.school_var = tk.StringVar()
        self.grad_var = tk.StringVar()
        self.linkedin_var = tk.StringVar()
        self.github_var = tk.StringVar()
        fields = [
            (0, 0, "First", self.first_var),
            (0, 2, "Last", self.last_var),
            (0, 4, "Email", self.email_var),
            (0, 6, "Phone", self.phone_var),
            (1, 0, "School", self.school_var),
            (1, 2, "Grad year", self.grad_var),
            (1, 4, "LinkedIn", self.linkedin_var),
            (1, 6, "GitHub", self.github_var),
        ]
        for row, col, label, var in fields:
            ttk.Label(profile, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            ttk.Entry(profile, textvariable=var).grid(
                row=row, column=col + 1, sticky="ew", padx=4, pady=2
            )

        hunt = ttk.LabelFrame(top, text="Search")
        hunt.grid(row=1, column=0, sticky="ew", padx=8, pady=2)
        hunt.columnconfigure(2, weight=1)
        self.query_var = tk.StringVar(value="")
        self.location_var = tk.StringVar(value="")
        self.target_var = tk.StringVar(value="Eligible: reading resume…")
        self.fill_var = tk.StringVar(value="")
        self.limit_var = tk.StringVar(value="12")
        self.resume_var = tk.StringVar(value="No resume uploaded")
        self.timeline_var = tk.StringVar(value="Upload a resume to estimate graduation and experience.")
        self.upload_btn = ttk.Button(hunt, text="Upload resume...", command=self._upload_resume)
        self.upload_btn.grid(row=0, column=0, padx=8, pady=6)
        ttk.Label(hunt, text="Keywords").grid(row=0, column=1, padx=(8, 4), sticky="w")
        ttk.Entry(hunt, textvariable=self.query_var).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Label(hunt, text="Location").grid(row=0, column=3, padx=8, sticky="w")
        ttk.Entry(hunt, textvariable=self.location_var, width=18).grid(row=0, column=4, padx=4)
        ttk.Label(hunt, text="Limit").grid(row=0, column=5, padx=8, sticky="w")
        ttk.Entry(hunt, textvariable=self.limit_var, width=5).grid(row=0, column=6, padx=4)
        self.hunt_btn = ttk.Button(hunt, text="Hunt jobs", style="Hunt.TButton", command=self._start_hunt)
        self.hunt_btn.grid(row=0, column=7, padx=10, pady=6)
        ttk.Label(hunt, textvariable=self.resume_var, style="Hint.TLabel").grid(
            row=1, column=0, columnspan=8, sticky="w", padx=8
        )
        ttk.Label(hunt, textvariable=self.timeline_var, style="Hint.TLabel").grid(
            row=2, column=0, columnspan=8, sticky="w", padx=8
        )
        ttk.Label(hunt, textvariable=self.target_var, style="Hint.TLabel").grid(
            row=3, column=0, columnspan=8, sticky="w", padx=8
        )
        ttk.Label(hunt, textvariable=self.fill_var, style="Hint.TLabel").grid(
            row=4, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 6)
        )

        mid = ttk.Frame(shell)
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)
        body = ttk.Panedwindow(mid, orient="horizontal")
        body.grid(row=0, column=0, sticky="nsew", padx=8, pady=4)

        left = ttk.Frame(body)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        cols = ("score", "level", "title", "company", "location", "source")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse", height=22)
        headings = {
            "score": "Score",
            "level": "Level",
            "title": "Role",
            "company": "Company",
            "location": "Location",
            "source": "Source",
        }
        widths = {
            "score": self._px(70),
            "level": self._px(90),
            "title": self._px(360),
            "company": self._px(160),
            "location": self._px(160),
            "source": self._px(110),
        }
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], stretch=col == "title")
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("intern", background="#E0F2FE")
        self.tree.tag_configure("early", background="#ECFDF5")
        self.tree.tag_configure("mid", background="#FFFBEB")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())

        btns = ttk.Frame(left)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)
        self.dry_btn = ttk.Button(btns, text="Prepare application", command=lambda: self._apply_selected(False))
        self.live_btn = ttk.Button(btns, text="Fill form (live)", command=lambda: self._apply_selected(True))
        self.open_btn = ttk.Button(btns, text="Open posting", command=self._open_selected)
        self.dry_btn.pack(side="left", padx=4)
        self.live_btn.pack(side="left", padx=4)
        self.open_btn.pack(side="left", padx=4)

        right = ttk.LabelFrame(body, text="Match & description")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.detail = tk.Text(
            right,
            wrap="word",
            font=("Segoe UI", 11),
            relief="flat",
            bg=CARD,
            fg=INK,
            padx=12,
            pady=12,
            height=28,
            width=56,
        )
        self.detail.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.detail.tag_configure("h1", font=("Segoe UI", 15, "bold"), spacing3=6)
        self.detail.tag_configure("meta", foreground=MUTED, spacing3=8)
        self.detail.tag_configure("label", font=("Segoe UI", 9, "bold"), foreground=ACCENT, spacing1=10)
        self.detail.tag_configure("body", font=("Segoe UI", 11))
        self.detail.configure(state="disabled")

        body.add(left, weight=3)
        body.add(right, weight=2)
        self._body = body

        bottom = ttk.LabelFrame(shell, text="Activity")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=1)
        self.log = tk.Text(
            bottom,
            wrap="word",
            font=("Consolas", 10),
            bg="#0B1220",
            fg="#E2E8F0",
            relief="flat",
            height=6,
        )
        log_scroll = ttk.Scrollbar(bottom, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        log_scroll.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 6))

        shell.add(top, weight=0)
        shell.add(mid, weight=6)
        shell.add(bottom, weight=1)
        shell.bind("<Configure>", self._schedule_layout)
        self.after(120, self._size_workspace)
        self._log("Ready. Upload a resume, confirm school and grad year, then Hunt jobs.")

    def _build_history(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        cols = ("when", "status", "role", "company", "method")
        self.hist = ttk.Treeview(parent, columns=cols, show="headings", selectmode="browse", height=24)
        for col, label, width in [
            ("when", "When", self._px(170)),
            ("status", "Status", self._px(110)),
            ("role", "Role", self._px(420)),
            ("company", "Company", self._px(180)),
            ("method", "Method", self._px(120)),
        ]:
            self.hist.heading(col, text=label)
            self.hist.column(col, width=width, stretch=col == "role")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.hist.yview)
        self.hist.configure(yscrollcommand=scroll.set)
        self.hist.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        scroll.grid(row=0, column=1, sticky="ns", pady=8)
        ttk.Label(
            parent,
            text="Dry-runs and live applies are stored here. Nothing is submitted unless you choose Fill form (live).",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))

    def _schedule_layout(self, _event=None) -> None:
        if self._layout_job is not None:
            try:
                self.after_cancel(self._layout_job)
            except tk.TclError:
                pass
        self._layout_job = self.after(80, self._size_workspace)

    def _move_sash(self, pane: ttk.Panedwindow, index: int, pos: int) -> None:
        try:
            current = int(pane.sashpos(index))
            if abs(current - pos) < 12:
                return
        except tk.TclError:
            pass
        pane.sashpos(index, pos)

    def _size_workspace(self) -> None:
        self._layout_job = None
        try:
            height = self._vpanes.winfo_height()
            width = self._body.winfo_width()
            if height < 120 or width < 200:
                return
            top_h = min(self._px(200), max(self._px(130), int(height * 0.20)))
            activity_h = min(self._px(110), max(self._px(72), int(height * 0.12)))
            if height < self._px(720):
                top_h = min(top_h, int(height * 0.26))
                activity_h = min(activity_h, int(height * 0.14))
            mid_end = height - activity_h
            if mid_end <= top_h + self._px(160):
                top_h = max(self._px(110), int(height * 0.22))
                activity_h = max(self._px(64), int(height * 0.12))
                mid_end = height - activity_h
            if mid_end > top_h + 40:
                self._move_sash(self._vpanes, 0, top_h)
                self._move_sash(self._vpanes, 1, mid_end)
            self._move_sash(self._body, 0, int(width * 0.58))
        except Exception:
            pass

    def _popup(self, title: str, message: str, *, error: bool = False) -> None:
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        long_msg = error or len(message) > 140 or message.count("\n") > 2
        if long_msg:
            w = min(max(self._px(640), int(sw * 0.48)), int(sw * 0.78))
            h = min(max(self._px(360), int(sh * 0.42)), int(sh * 0.72))
        else:
            w = min(max(self._px(440), int(sw * 0.28)), int(sw * 0.5))
            h = min(max(self._px(200), int(sh * 0.18)), int(sh * 0.32))
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        win.minsize(self._px(400), self._px(180))
        txt = tk.Text(win, wrap="word", font=("Segoe UI", 11), bg=CARD, fg=INK, padx=14, pady=14)
        txt.insert("1.0", message)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        ttk.Button(win, text="OK", command=win.destroy).pack(pady=(0, 12))
        win.lift()
        win.grab_set()
        win.focus_force()

    def _ask(self, title: str, message: str) -> bool:
        result = {"ok": False}
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(max(self._px(520), int(sw * 0.38)), int(sw * 0.6))
        h = min(max(self._px(240), int(sh * 0.28)), int(sh * 0.5))
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        win.minsize(self._px(440), self._px(200))
        ttk.Label(win, text=message, wraplength=w - 40, font=("Segoe UI", 11)).pack(
            fill="both", expand=True, padx=18, pady=16
        )

        def yes() -> None:
            result["ok"] = True
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(pady=(0, 14))
        ttk.Button(btns, text="Continue", command=yes).pack(side="left", padx=8)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=8)
        win.grab_set()
        self.wait_window(win)
        return result["ok"]

    def _log(self, message: str) -> None:
        if hasattr(self, "log"):
            self.log.insert("end", message + "\n")
            self.log.see("end")
        if hasattr(self, "status_var"):
            self.status_var.set(message[:120])
        self.update_idletasks()

    def _action_buttons(self) -> list:
        return [self.hunt_btn, self.dry_btn, self.live_btn, self.open_btn, self.upload_btn]

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in self._action_buttons():
            btn.configure(state=state)
        if label:
            self.status_var.set(label)

    def _save_details(self) -> None:
        update_profile(
            first_name=self.first_var.get().strip(),
            last_name=self.last_var.get().strip(),
            email=self.email_var.get().strip(),
            phone=self.phone_var.get().strip(),
            school=self.school_var.get().strip(),
            graduation_year=self.grad_var.get().strip(),
            linkedin=self.linkedin_var.get().strip(),
            github=self.github_var.get().strip(),
            career_level="auto",
        )

    def _load_profile_fields(self) -> None:
        profile = load_profile()
        self.first_var.set(profile.first_name)
        self.last_var.set(profile.last_name)
        self.email_var.set(profile.email)
        self.phone_var.set(profile.phone)
        self.school_var.set(profile.school)
        self.grad_var.set(profile.graduation_year)
        self.linkedin_var.set(profile.linkedin)
        self.github_var.set(profile.github)

    def _refresh_resume(self) -> None:
        try:
            parsed = parse_resume()
            skills = ", ".join(parsed.skills[:8]) or "no skills detected"
            self.resume_var.set(f"{Path(parsed.path).name}   ·   {skills}")
            self.timeline_var.set(parsed.timeline or "Could not estimate graduation/experience from this resume.")
            self.header_var.set(parsed.timeline or self.header_var.get())
            from applyflow.candidate import infer_candidate

            cand = infer_candidate(parsed, load_profile())
            self.target_var.set(f"Eligible from resume: {cand.target_label}")
            if parsed.graduation_year and not self.grad_var.get().strip():
                self.grad_var.set(parsed.graduation_year)
            if parsed.school and not self.school_var.get().strip():
                self.school_var.set(parsed.school)
            if parsed.linkedin and not self.linkedin_var.get().strip():
                self.linkedin_var.set(parsed.linkedin)
            if parsed.github and not self.github_var.get().strip():
                self.github_var.set(parsed.github)
        except FileNotFoundError:
            self.resume_var.set("No resume uploaded")
            self.timeline_var.set("Upload a resume to estimate graduation and experience.")
            self.target_var.set("Eligible from resume: upload a resume first")
        except Exception as exc:
            self.resume_var.set(f"Could not read resume: {exc}")
            self.timeline_var.set("")

    def _upload_resume(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Choose resume",
            filetypes=[
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Text", "*.txt"),
                ("Markdown", "*.md"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            dest = save_resume(Path(path))
            parsed = parse_resume(dest)
            self._refresh_resume()
            self._save_details()
            self._log(f"Saved resume: {dest}")
            self._log("Skills: " + (", ".join(parsed.skills) or "(none)"))
            if parsed.timeline:
                self._log(parsed.timeline)
        except Exception as exc:
            self._popup("Resume", str(exc), error=True)

    def _load_saved_jobs(self) -> None:
        try:
            self.jobs = list_jobs(limit=40, min_score=0)
            self._fill_table(self.jobs)
        except Exception as exc:
            self._log(f"Could not load saved jobs: {exc}")

    def _load_history(self) -> None:
        try:
            for row in self.hist.get_children():
                self.hist.delete(row)
            for item in list_applications(limit=80):
                when = (item.created_at or "").replace("T", " ")[:19]
                self.hist.insert(
                    "",
                    "end",
                    values=(when, item.status, (item.title or "")[:70], item.company, item.method),
                )
        except Exception as exc:
            self._log(f"Could not load history: {exc}")

    def _fill_table(self, jobs) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for job in jobs:
            level = job.career_level or "-"
            tag = level if level in {"intern", "early", "mid"} else ""
            source = (job.source or "").split(":")[0]
            self.tree.insert(
                "",
                "end",
                iid=str(job.id),
                tags=(tag,) if tag else (),
                values=(
                    job.score,
                    level,
                    (job.title or "")[:70],
                    (job.company or "")[:28],
                    (job.location or "")[:24],
                    source,
                ),
            )

    def _selected_job_id(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except ValueError:
            return None

    def _on_select(self, _event=None) -> None:
        job_id = self._selected_job_id()
        if job_id is None:
            return
        job = get_job(job_id)
        if not job:
            return
        try:
            resume = parse_resume()
            reading = read_job(job, resume, fetch=False)
        except Exception:
            reading = None
        blocks = [
            (job.title or "Untitled", "h1"),
            (f"{job.company}  ·  {job.location or 'Location n/a'}  ·  {job.career_level or '-'}  ·  score {job.score}", "meta"),
            (job.apply_target() or "", "meta"),
        ]
        if reading:
            if reading.matching:
                blocks.append(("On your resume", "label"))
                blocks.append((", ".join(reading.matching[:12]), "body"))
            if reading.missing:
                blocks.append(("Not on resume (will not be invented)", "label"))
                blocks.append((", ".join(reading.missing[:8]), "body"))
            if reading.summary:
                blocks.append(("Why this role", "label"))
                blocks.append((reading.summary, "body"))
        blocks.append(("Description", "label"))
        blocks.append(((job.description or "No description loaded yet.")[:5000], "body"))
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for text, tag in blocks:
            if not text:
                continue
            self.detail.insert("end", text + "\n", tag)
        self.detail.configure(state="disabled")

    def _start_hunt(self) -> None:
        if self._busy:
            return
        self._save_details()
        try:
            parse_resume()
        except FileNotFoundError:
            self._popup("Resume", "Upload a resume first.")
            return
        self._set_busy(True, "Hunting jobs...")
        self._log("Hunting roles that fit your timeline...")
        threading.Thread(target=self._hunt_worker, daemon=True).start()

    def _hunt_worker(self) -> None:
        try:
            profile = load_profile()
            resume = parse_resume()
            limit = max(int(self.limit_var.get() or 12), 1)

            def progress(msg: str) -> None:
                self.after(0, lambda m=msg: self._log(m))

            jobs = discover_jobs(
                resume,
                profile,
                query=self.query_var.get().strip(),
                location=self.location_var.get().strip(),
                career_level="auto",
                limit=limit,
                on_progress=progress,
            )
            self.after(0, lambda j=jobs: self._hunt_done(j, None))
        except Exception as exc:
            self.after(0, lambda e=exc: self._hunt_done([], e))

    def _hunt_done(self, jobs, error) -> None:
        self._set_busy(False)
        if error:
            self._log(f"Hunt failed: {error}")
            self._popup("Hunt", str(error), error=True)
            return
        self.jobs = jobs
        self._fill_table(jobs)
        if not jobs:
            self._log("No eligible roles found. Try Auto, a broader keyword, or an empty location.")
            return
        self._log(f"Found {len(jobs)} roles. Select one to see why it fits, then Prepare application.")
        self.tree.selection_set(str(jobs[0].id))
        self._on_select()

    def _refresh_fill_status(self) -> None:
        from applyflow.apply import playwright_available

        if playwright_available():
            self.fill_var.set("Fill form: Chromium is ready. Live apply types into public forms; you submit.")
        else:
            self.fill_var.set(
                "Fill form: Playwright is missing, so Live apply cannot type into fields yet."
            )

    def _apply_selected(self, live: bool) -> None:
        job_id = self._selected_job_id()
        if job_id is None:
            self._popup("Apply", "Select a job in the list first.")
            return
        self._save_details()
        if live:
            from applyflow.apply import playwright_available

            if not playwright_available():
                from applyflow.browser import MISSING_PLAYWRIGHT

                self._popup("Cannot fill form", MISSING_PLAYWRIGHT, error=True)
                return
        if live and not self._ask(
            "Live apply",
            "A Chromium window will open, Applyflow will type your details and attach your resume, "
            "then you review and submit. Continue?",
        ):
            return
        if self._busy:
            return
        self._set_busy(True, f"Applying to job #{job_id}...")
        self._log(f"Applying to job #{job_id} ({'live' if live else 'dry-run'})...")
        threading.Thread(target=self._apply_worker, args=(job_id, live), daemon=True).start()

    def _apply_worker(self, job_id: int, live: bool) -> None:
        try:
            job = get_job(job_id)
            if job is None:
                raise FileNotFoundError(f"No job {job_id}")
            resume = parse_resume()
            profile = load_profile()
            result, reading = prepare_and_apply(
                job,
                resume,
                profile,
                live=live,
                fill=True,
                tweak=True,
                hold_for_review=not live,
            )
            self.after(0, lambda r=result, rd=reading: self._apply_done(r, rd, None))
        except Exception as exc:
            self.after(0, lambda e=exc: self._apply_done(None, None, e))

    def _apply_done(self, result, reading, error) -> None:
        self._set_busy(False, "Ready")
        if error:
            self._log(f"Apply failed: {error}")
            self._popup("Apply", str(error), error=True)
            return
        self._log(f"{result.status}  {result.method}: {result.notes}")
        if reading:
            self._log(reading.summary)
        if result.status == "failed":
            self._popup("Apply", result.notes, error=True)
        self._load_history()

    def _open_selected(self) -> None:
        job_id = self._selected_job_id()
        if job_id is None:
            self._popup("Open", "Select a job in the list first.")
            return
        job = get_job(job_id)
        if job and job.apply_target().startswith("http"):
            webbrowser.open(job.apply_target())
        else:
            self._popup("Open", "This posting has no web URL.")


def launch() -> None:
    _enable_windows_dpi()
    try:
        app = ApplyflowGui()
        app.mainloop()
    except Exception:
        err = traceback.format_exc()
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Applyflow failed to start", err)
        except Exception:
            print(err)
            raise
