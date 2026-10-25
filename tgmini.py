"""
TgMini 2 — лёгкий клиент Telegram для слабых ПК.
Установка:  pip install telethon PySocks
Запуск:     python tgmini.py   (рядом должны лежать sandbox.py и папка plugins/)
api_id / api_hash: https://my.telegram.org
Крестик = полный выход, в фоне ничего не остаётся.
"""
import asyncio, gc, hashlib, json, os, queue, shutil, subprocess, sys, tempfile, threading
from types import SimpleNamespace
import tkinter as tk
import tkinter.font as tkfont
from tkinter import simpledialog, messagebox
from urllib.parse import urlparse, parse_qs

from telethon import TelegramClient, events, utils
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

import sandbox

FROZEN = getattr(sys, "frozen", False)  # запущено как .exe
DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
# портативный режим: рядом с TgMini.exe лежит файл portable.flag, данные хранятся в папке data\\ рядом
PORTABLE = FROZEN and os.path.exists(os.path.join(DIR, "portable.flag"))
if PORTABLE:
    DATA = os.path.join(DIR, "data")
elif FROZEN:  # обычная установка: данные в %APPDATA%\\TgMini
    DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "TgMini")
else:
    DATA = DIR
os.makedirs(DATA, exist_ok=True)
CFG_PATH = os.path.join(DATA, "config.json")
SESSION = os.path.join(DATA, "session")
PLUG_DIR = os.path.join(DATA, "plugins")
TMP_DIR = os.path.join(DATA, "tmp")  # всё временное внутри папки приложения, не в системном Temp
MAX_DIALOGS = 60

THEMES = {
    "Тёмная": dict(bg="#17212b", panel="#0e1621", fg="#e6edf3", dim="#7f8c99", accent="#5eb5f7", sel="#2b5278", entry="#242f3d"),
    "Светлая": dict(bg="#ffffff", panel="#eef1f4", fg="#1b1f23", dim="#6a737d", accent="#1a73e8", sel="#cfe3ff", entry="#f6f8fa"),
    "Полночь": dict(bg="#000000", panel="#0b0b0b", fg="#d6d6d6", dim="#777777", accent="#bb86fc", sel="#2a1a4a", entry="#141414"),
}
DEFAULT_UI = dict(theme="Тёмная", font=10, limit=30, time=True, notify=True)
_LOCK = threading.Lock()


# ---------------- конфиг и прокси ----------------
def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    ui = dict(DEFAULT_UI)
    ui.update(cfg.get("ui", {}))
    cfg["ui"] = ui
    for k in ("chat", "plugins", "plugin_data"):
        cfg.setdefault(k, {})
    return cfg


def save_cfg(cfg):
    with _LOCK:
        try:
            tmp = CFG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
            os.replace(tmp, CFG_PATH)
        except Exception:
            pass


def parse_proxy(link):
    """tg://proxy?server=..&port=..&secret=..  или  tg://socks?server=..&port=..&user=..&pass=.."""
    link = link.strip()
    if not link:
        return None
    u = urlparse(link)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    kind = (u.netloc or u.path.strip("/")).lower()
    if "server" not in q or "port" not in q:
        raise ValueError("Не нашёл server/port в ссылке")
    if kind == "proxy" and q.get("secret"):
        return {"type": "mtproto", "server": q["server"], "port": int(q["port"]), "secret": q["secret"]}
    if kind == "socks":
        return {"type": "socks5", "server": q["server"], "port": int(q["port"]),
                "user": q.get("user"), "pass": q.get("pass")}
    raise ValueError("Нужна ссылка tg://proxy?... или tg://socks?...")


def make_client(cfg, proxy):
    kw = dict(connection_retries=1, retry_delay=1, request_retries=1, device_model="TgMini")
    api_id, api_hash = int(cfg["api_id"]), cfg["api_hash"]
    if proxy and proxy["type"] == "mtproto":
        return TelegramClient(SESSION, api_id, api_hash,
                              connection=ConnectionTcpMTProxyRandomizedIntermediate,
                              proxy=(proxy["server"], proxy["port"], proxy["secret"]), **kw)
    if proxy and proxy["type"] == "socks5":
        p = {"proxy_type": "socks5", "addr": proxy["server"], "port": proxy["port"], "rdns": True}
        if proxy.get("user"):
            p["username"], p["password"] = proxy["user"], proxy.get("pass")
        return TelegramClient(SESSION, api_id, api_hash, proxy=p, **kw)
    return TelegramClient(SESSION, api_id, api_hash, **kw)


# ---------------- приложение ----------------
class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.client = None
        self.dialogs, self.visible, self.by_id = [], [], {}
        self.cur = None
        self.unread, self.media = {}, {}
        self.hooks, self.plugins, self.perrors, self.plog = [], [], [], []
        self.flt = "all"
        self.online_text = ""
        self._toast = None
        self.menu_open = False
        self.q = queue.Queue()

        shutil.rmtree(TMP_DIR, ignore_errors=True)  # хвосты после аварийного закрытия
        self.root = tk.Tk()
        self.root.title("TgMini")
        self.root.geometry("900x560")
        self.font = tkfont.nametofont("TkDefaultFont").copy()
        self.fontb = self.font.copy()
        self.fontb.configure(weight="bold")
        self.build_ui()
        self.apply_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.root.after(150, self.poll)

        if not self.cfg.get("api_id"):
            self.cfg["api_id"] = simpledialog.askstring("API", "api_id (my.telegram.org):")
            self.cfg["api_hash"] = simpledialog.askstring("API", "api_hash:")
            if not self.cfg["api_id"] or not self.cfg["api_hash"]:
                os._exit(0)
            save_cfg(self.cfg)
        self.load_plugins()
        self.call(self.start())

    # ---------- UI ----------
    def build_ui(self):
        r = self.root
        bar = tk.Frame(r)
        bar.pack(fill="x")
        tk.Button(bar, text="☰", width=3, command=self.toggle_menu).pack(side="left")
        self.title_lbl = tk.Label(bar, text="TgMini", anchor="w")
        self.title_lbl.pack(side="left", padx=8)
        self.status = tk.Label(bar, text="", anchor="e")
        self.status.pack(side="right", padx=8)

        pills = tk.Frame(r)
        pills.pack(fill="x", pady=2)
        self.pills = {}
        for key, label in (("all", "Все"), ("user", "Личные"), ("group", "Группы"), ("channel", "Каналы")):
            b = tk.Button(pills, text=label, command=lambda k=key: self.set_filter(k))
            b.pack(side="left", padx=3, ipadx=6)
            self.pills[key] = b

        body = tk.Frame(r)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        self.lb = tk.Listbox(left, width=30, exportselection=False, activestyle="none")
        self.lb.pack(fill="y", expand=True)
        self.lb.bind("<<ListboxSelect>>", self.on_select)
        right = tk.Frame(body)
        right.pack(side="right", fill="both", expand=True)
        self.txt = tk.Text(right, state="disabled", wrap="word")
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_bind("link", "<Enter>", lambda e: self.txt.config(cursor="hand2"))
        self.txt.tag_bind("link", "<Leave>", lambda e: self.txt.config(cursor="xterm"))
        self.entry = tk.Entry(right)
        self.entry.pack(fill="x", ipady=4)
        self.entry.bind("<Return>", self.on_send)

        self.menu = tk.Frame(r, bd=1)
        tk.Label(self.menu, text="TgMini", anchor="w", font=self.fontb).pack(fill="x", padx=14, pady=10)
        items = (("⚙  Настройки", self.open_settings), ("💬  Настройки чата", self.open_chat_settings),
                 ("🧩  Плагины", self.open_plugins), ("🌐  Прокси (без VPN)", self.set_proxy),
                 ("🎨  Сменить тему", self.cycle_theme), ("🚪  Выйти из аккаунта", self.logout),
                 ("✖  Выход", self.quit))
        for label, fn in items:
            tk.Button(self.menu, text=label, anchor="w", padx=14,
                      command=lambda f=fn: (self.toggle_menu(False), f())).pack(fill="x", ipady=6)

    def theme(self):
        return THEMES.get(self.cfg["ui"]["theme"], THEMES["Тёмная"])

    def paint(self, w):
        t = self.theme()
        c = w.winfo_class()
        try:
            if c in ("Frame", "Toplevel", "Tk"):
                w.configure(bg=t["bg"])
            elif c == "Label":
                w.configure(bg=t["bg"], fg=t["fg"])
            elif c == "Button":
                w.configure(bg=t["panel"], fg=t["fg"], activebackground=t["sel"], activeforeground=t["fg"],
                            relief="flat", bd=0, highlightthickness=0)
            elif c == "Listbox":
                w.configure(bg=t["panel"], fg=t["fg"], selectbackground=t["sel"], selectforeground=t["fg"],
                            highlightthickness=0, bd=0)
            elif c == "Text":
                w.configure(bg=t["bg"], fg=t["fg"], insertbackground=t["fg"], highlightthickness=0, bd=0)
            elif c in ("Entry", "Spinbox"):
                w.configure(bg=t["entry"], fg=t["fg"], insertbackground=t["fg"], relief="flat", highlightthickness=0)
            elif c == "Checkbutton":
                w.configure(bg=t["bg"], fg=t["fg"], selectcolor=t["panel"], activebackground=t["bg"],
                            activeforeground=t["fg"], highlightthickness=0)
            elif c == "Menubutton":
                w.configure(bg=t["panel"], fg=t["fg"], activebackground=t["sel"], activeforeground=t["fg"],
                            relief="flat", highlightthickness=0)
        except tk.TclError:
            pass
        for ch in w.winfo_children():
            self.paint(ch)

    def apply_ui(self):
        ui, t = self.cfg["ui"], self.theme()
        self.font.configure(size=ui["font"])
        self.fontb.configure(size=ui["font"])
        for w in (self.txt, self.entry, self.lb):
            w.configure(font=self.font)
        self.paint(self.root)
        for w in [self.menu] + list(self.menu.winfo_children()):
            w.configure(bg=t["panel"])
        tg = self.txt.tag_configure
        tg("time", foreground=t["dim"])
        tg("who", foreground=t["accent"], font=self.fontb)
        tg("link", foreground=t["accent"], underline=True)
        self.mark_pills()

    def mark_pills(self):
        t = self.theme()
        for k, b in self.pills.items():
            on = k == self.flt
            b.configure(bg=t["accent"] if on else t["panel"], fg="#ffffff" if on else t["fg"])

    def toggle_menu(self, show=None):
        self.menu_open = (not self.menu_open) if show is None else show
        if self.menu_open:
            self.menu.place(x=0, y=0, relheight=1, width=240)
            self.menu.lift()
        else:
            self.menu.place_forget()

    def cycle_theme(self):
        names = list(THEMES)
        self.cfg["ui"]["theme"] = names[(names.index(self.cfg["ui"]["theme"]) + 1) % len(names)]
        save_cfg(self.cfg)
        self.apply_ui()

    def set_filter(self, k):
        self.flt = k
        self.mark_pills()
        self.refresh_list()

    def refresh_list(self):
        self.visible = [d for d in self.dialogs if self.flt == "all" or d["kind"] == self.flt]
        self.lb.delete(0, "end")
        for d in self.visible:
            n = self.unread.get(d["id"], 0)
            mute = "🔕 " if self.cfg["chat"].get(str(d["id"]), {}).get("mute") else ""
            self.lb.insert("end", f"{mute}{d['name']}" + (f"  ({n})" if n else ""))
        idx = next((i for i, d in enumerate(self.visible) if d is self.cur), None)
        if idx is not None:
            self.lb.selection_set(idx)
        total = sum(self.unread.values())
        self.root.title("TgMini" + (f" ({total})" if total else ""))

    def toast(self, title, text):
        t = self.theme()
        if self._toast is not None:
            try:
                self._toast.destroy()
            except tk.TclError:
                pass
        w = tk.Toplevel(self.root)
        self._toast = w
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=t["accent"])
        f = tk.Frame(w, bg=t["panel"])
        f.pack(padx=2, pady=2)
        tk.Label(f, text=title[:40], bg=t["panel"], fg=t["accent"], font=self.fontb, anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(f, text=text[:140], bg=t["panel"], fg=t["fg"], wraplength=280, justify="left", anchor="w").pack(fill="x", padx=10, pady=(0, 8))
        w.update_idletasks()
        w.geometry(f"+{w.winfo_screenwidth() - w.winfo_width() - 16}+{w.winfo_screenheight() - w.winfo_height() - 56}")
        w.bind("<Button-1>", lambda e: (self.root.deiconify(), self.root.lift(), w.destroy()))
        w.after(4500, lambda: w.winfo_exists() and w.destroy())

    # ---------- потоки ----------
    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def ui(self, fn):
        self.q.put(fn)

    def poll(self):
        try:
            while True:
                try:
                    self.q.get_nowait()()
                except queue.Empty:
                    raise
                except Exception as e:
                    print("ui error:", e, file=sys.stderr)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def set_status(self, s):
        self.ui(lambda: self.status.config(text=s))

    async def ask(self, prompt, secret=False):
        def blocking():
            box = queue.Queue()
            self.ui(lambda: box.put(simpledialog.askstring("TgMini", prompt, show="*" if secret else None)))
            return box.get()
        return await self.loop.run_in_executor(None, blocking)

    async def confirm(self, text):
        def blocking():
            box = queue.Queue()
            self.ui(lambda: box.put(messagebox.askyesno("TgMini", text)))
            return box.get()
        return await self.loop.run_in_executor(None, blocking)

    # ---------- подключение ----------
    async def try_connect(self, proxy):
        c = make_client(self.cfg, proxy)
        try:
            await asyncio.wait_for(c.connect(), 10)
            self.client = c
            return True
        except Exception:
            try:
                await c.disconnect()
            except Exception:
                pass
            return False

    async def start(self):
        self.set_status("Подключение…")
        proxy = self.cfg.get("proxy")
        via = "напрямую"
        if proxy and self.cfg.get("mode") == "proxy":
            ok, via = await self.try_connect(proxy), "через прокси"
        else:
            ok = await self.try_connect(None)
            if not ok and proxy:
                ok, via = await self.try_connect(proxy), "через прокси"
        if not ok:
            self.set_status("Нет связи. Меню ☰ → Прокси")
            return
        c = self.client
        if not await c.is_user_authorized():
            phone = await self.ask("Телефон (+7...)")
            await c.send_code_request(phone)
            code = await self.ask("Код из Telegram")
            try:
                await c.sign_in(phone, code)
            except SessionPasswordNeededError:
                await c.sign_in(password=await self.ask("Пароль 2FA", True))
        c.add_event_handler(self.on_new, events.NewMessage)
        self.online_text = "Онлайн (" + via + ")"
        self.set_status(self.online_text)
        await self.load_dialogs()

    async def load_dialogs(self):
        ds = await self.client.get_dialogs(limit=MAX_DIALOGS)
        self.dialogs = [dict(id=d.id, ent=d.entity, name=d.name or "?",
                             kind="group" if d.is_group else "channel" if d.is_channel else "user") for d in ds]
        self.by_id = {d["id"]: d for d in self.dialogs}
        self.unread = {d.id: d.unread_count for d in ds if d.unread_count}
        self.ui(self.refresh_list)

    # ---------- чат ----------
    def chat_limit(self, cid):
        return int(self.cfg["chat"].get(str(cid), {}).get("limit") or self.cfg["ui"]["limit"])

    def on_select(self, _):
        sel = self.lb.curselection()
        if not sel:
            return
        self.cur = self.visible[sel[0]]
        self.unread.pop(self.cur["id"], None)
        self.title_lbl.config(text=self.cur["name"])
        self.refresh_list()
        self.call(self.load_chat())

    @staticmethod
    def media_label(m):
        if not m.media:
            return None
        if m.photo:
            return "фото"
        if m.voice:
            return "голосовое"
        if m.video_note:
            return "кружок"
        if m.video:
            return "видео"
        if m.sticker:
            return "стикер"
        if m.document:
            return "файл" + (": " + m.file.name if m.file and m.file.name else "")
        return None if m.web_preview else "медиа"

    async def parts(self, m):
        if m.out:
            who = "Я"
        else:
            s = await m.get_sender()
            who = getattr(s, "first_name", None) or getattr(s, "title", None) or "?"
        return (m.date.astimezone().strftime("%H:%M"), who, m.text or "", self.media_label(m), m.id)

    async def load_chat(self):
        d = self.cur
        if not d:
            return
        msgs = await self.client.get_messages(d["ent"], limit=self.chat_limit(d["id"]))
        ps, media = [], {}
        for m in reversed(msgs):
            ps.append(await self.parts(m))
            if self.media_label(m):
                media[m.id] = m
        try:
            await self.client.send_read_acknowledge(d["ent"])
        except Exception:
            pass

        def show():
            if d is not self.cur:
                return
            self.media = media
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.config(state="disabled")
            for p in ps:
                self.put(p)
            gc.collect()
        self.ui(show)

    def put(self, p):
        tm, who, body, label, mid = p
        T = self.txt
        T.config(state="normal")
        if self.cfg["ui"]["time"]:
            T.insert("end", tm + " ", "time")
        T.insert("end", who + ": ", "who")
        T.insert("end", body)
        if label:
            tag = f"m{mid}"
            T.insert("end", (" " if body else "") + "📎 " + label, ("link", tag))
            T.tag_bind(tag, "<Button-1>", lambda e, i=mid: self.click_media(i))
        T.insert("end", "\n")
        T.config(state="disabled")
        T.see("end")

    def trim(self):
        lim = self.chat_limit(self.cur["id"]) * 2
        lines = int(self.txt.index("end-1c").split(".")[0])
        if lines > lim:
            self.txt.config(state="normal")
            self.txt.delete("1.0", f"{lines - lim // 2}.0")
            self.txt.config(state="disabled")
        while len(self.media) > 200:
            self.media.pop(next(iter(self.media)))

    async def on_new(self, ev):
        m, cid = ev.message, ev.chat_id
        d = self.by_id.get(cid)
        if d:
            name = d["name"]
        else:
            try:
                name = utils.get_display_name(await ev.get_chat())
            except Exception:
                name = "Чат"
            self.call(self.load_dialogs())
        info = {"id": m.id, "chat_id": cid, "chat": name, "text": m.text or "", "out": bool(m.out)}
        for pname, cb in list(self.hooks):
            try:
                cb(dict(info))
            except Exception as e:
                self.plugin_log(pname, f"ошибка: {e}")
        p = await self.parts(m)

        def apply():
            is_cur = bool(self.cur) and self.cur["id"] == cid
            if is_cur:
                if p[3]:
                    self.media[m.id] = m
                self.put(p)
                self.trim()
            if m.out:
                return
            if not is_cur:
                self.unread[cid] = self.unread.get(cid, 0) + 1
                self.refresh_list()
            muted = self.cfg["chat"].get(str(cid), {}).get("mute")
            if self.cfg["ui"]["notify"] and not muted and (not is_cur or self.root.state() == "iconic"):
                self.toast(name, p[2] or "📎 " + (p[3] or "медиа"))
        self.ui(apply)

    def on_send(self, _):
        text = self.entry.get().strip()
        if text and self.cur:
            self.entry.delete(0, "end")
            self.call(self.client.send_message(self.cur["ent"], text))

    # ---------- медиа по клику ----------
    def tmpdir(self):
        os.makedirs(TMP_DIR, exist_ok=True)
        return TMP_DIR

    def click_media(self, mid):
        m = self.media.get(mid)
        if m:
            self.call(self.open_media(m))

    async def open_media(self, m):
        size = getattr(m.file, "size", 0) or 0
        if size > 50 * 1024 * 1024 and not await self.confirm(f"Файл {size // 2**20} МБ. Скачать?"):
            return
        self.set_status("Загрузка файла…")
        try:
            path = await m.download_media(file=self.tmpdir())
        except Exception as e:
            self.set_status(f"Ошибка загрузки: {e}")
            return
        self.set_status(self.online_text)
        if path:
            self.ui(lambda: self.open_path(path))

    @staticmethod
    def open_path(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Не удалось открыть", str(e))

    # ---------- диалоги настроек ----------
    def dlg(self, title):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.transient(self.root)
        top.resizable(False, False)
        return top

    def open_settings(self):
        ui = self.cfg["ui"]
        top = self.dlg("Настройки")
        vt, vf, vl = tk.StringVar(value=ui["theme"]), tk.StringVar(value=str(ui["font"])), tk.StringVar(value=str(ui["limit"]))
        vtime, vn = tk.BooleanVar(value=ui["time"]), tk.BooleanVar(value=ui["notify"])
        tk.Label(top, text="Тема", anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=4)
        tk.OptionMenu(top, vt, *THEMES).grid(row=0, column=1, sticky="ew", padx=10)
        tk.Label(top, text="Размер шрифта", anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        tk.Spinbox(top, from_=8, to=20, textvariable=vf, width=6).grid(row=1, column=1, sticky="w", padx=10)
        tk.Label(top, text="Сообщений в чате", anchor="w").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        tk.Spinbox(top, from_=10, to=100, textvariable=vl, width=6).grid(row=2, column=1, sticky="w", padx=10)
        tk.Checkbutton(top, text="Показывать время", variable=vtime).grid(row=3, column=0, columnspan=2, sticky="w", padx=10)
        tk.Checkbutton(top, text="Уведомления", variable=vn).grid(row=4, column=0, columnspan=2, sticky="w", padx=10)

        def ok():
            try:
                ui["font"] = max(8, min(20, int(vf.get())))
                ui["limit"] = max(10, min(100, int(vl.get())))
            except ValueError:
                pass
            ui["theme"], ui["time"], ui["notify"] = vt.get(), vtime.get(), vn.get()
            save_cfg(self.cfg)
            self.apply_ui()
            top.destroy()
            if self.cur:
                self.call(self.load_chat())
        tk.Button(top, text="Сохранить", command=ok).grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=10, ipady=4)
        self.paint(top)

    def open_chat_settings(self):
        if not self.cur:
            messagebox.showinfo("Настройки чата", "Сначала выберите чат")
            return
        cid = str(self.cur["id"])
        c = self.cfg["chat"].setdefault(cid, {})
        top = self.dlg("Чат: " + self.cur["name"][:30])
        vm, vl = tk.BooleanVar(value=bool(c.get("mute"))), tk.StringVar(value=str(c.get("limit") or 0))
        tk.Checkbutton(top, text="Без уведомлений (🔕)", variable=vm).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=6)
        tk.Label(top, text="Сообщений (0 = общее)", anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        tk.Spinbox(top, from_=0, to=100, textvariable=vl, width=6).grid(row=1, column=1, padx=10)

        def ok():
            try:
                c["limit"] = max(0, min(100, int(vl.get())))
            except ValueError:
                pass
            c["mute"] = vm.get()
            save_cfg(self.cfg)
            top.destroy()
            self.refresh_list()
            self.call(self.load_chat())
        tk.Button(top, text="Сохранить", command=ok).grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=10, ipady=4)
        self.paint(top)

    # ---------- плагины ----------
    def plugin_log(self, name, text):
        self.plog.append(f"[{name}] {text}")
        del self.plog[:-200]

    def ask_install(self, info, changed):
        lst = "\n".join("  • " + sandbox.PERMS[p] for p in info["perms"]) or "  • ничего (без разрешений)"
        head = "Плагин изменился с прошлого раза!\n\n" if changed else ""
        by = f", автор: {info['author']}" if info["author"] else ""
        return messagebox.askyesno(
            "Установка плагина",
            f"{head}«{info['name']}» v{info['version']}{by}\n\nЗапрашивает разрешения:\n{lst}\n\nУстановить и включить?",
            icon="warning")

    def load_plugins(self):
        if FROZEN and not os.path.isdir(PLUG_DIR):  # первый запуск: кладём примеры плагинов
            try:
                shutil.copytree(os.path.join(sys._MEIPASS, "plugins"), PLUG_DIR)
            except Exception:
                pass
        os.makedirs(PLUG_DIR, exist_ok=True)
        for fn in sorted(os.listdir(PLUG_DIR)):
            if not fn.endswith(".py"):
                continue
            try:
                with open(os.path.join(PLUG_DIR, fn), encoding="utf-8") as f:
                    src = f.read()
                tree = sandbox.check(src)
                meta = sandbox.read_meta(tree)
            except Exception as e:
                self.perrors.append(f"{fn}: {e}")
                continue
            h = hashlib.sha256(src.encode()).hexdigest()
            info = dict(file=fn, name=meta["name"], version=meta["version"], author=meta["author"],
                        perms=meta["permissions"], hash=h, tree=tree)
            rec = self.cfg["plugins"].get(fn)
            if rec is None or (rec.get("enabled") and (rec.get("hash") != h or set(info["perms"]) - set(rec.get("approved", [])))):
                ok = self.ask_install(info, changed=rec is not None)
                rec = {"approved": info["perms"] if ok else [], "enabled": ok, "hash": h}
                self.cfg["plugins"][fn] = rec
                save_cfg(self.cfg)
            info["enabled"] = bool(rec.get("enabled"))
            self.plugins.append(info)
            if info["enabled"]:
                try:
                    sandbox.run(tree, info["name"], self.make_api(info["name"], set(rec["approved"])))
                    self.plugin_log(info["name"], "запущен")
                except Exception as e:
                    self.plugin_log(info["name"], f"не запустился: {e}")

    def make_api(self, name, perms):
        def need(p):
            if p not in perms:
                raise sandbox.PluginError(f"нет разрешения «{p}»")

        def on_message(cb):
            need("read_messages")
            self.hooks.append((name, cb))

        def send(chat_id, text):
            need("send_messages")
            self.call(self.client.send_message(int(chat_id), str(text)[:4000]))

        def notify(title, text):
            need("notify")
            t, x = str(title)[:60], str(text)[:200]
            self.ui(lambda: self.toast(t, x))

        def get(key, default=None):
            need("storage")
            return self.cfg["plugin_data"].get(name, {}).get(str(key), default)

        def set_(key, value):
            need("storage")
            value = json.loads(json.dumps(value))
            d = self.cfg["plugin_data"].setdefault(name, {})
            d[str(key)] = value
            if len(json.dumps(d)) > 100_000:
                d.pop(str(key), None)
                raise sandbox.PluginError("хранилище плагина переполнено (100 КБ)")
            self.ui(lambda: save_cfg(self.cfg))

        def log(*a):
            self.plugin_log(name, " ".join(map(str, a)))
        return SimpleNamespace(on_message=on_message, send=send, notify=notify, get=get, set=set_, log=log)

    def open_plugins(self):
        top = self.dlg("Плагины")
        vars_ = {}
        if not self.plugins:
            tk.Label(top, text="Положите .py-плагины в папку plugins/ и перезапустите").pack(padx=10, pady=10)
        for p in self.plugins:
            v = tk.BooleanVar(value=p["enabled"])
            vars_[p["file"]] = v
            perms = ", ".join(sandbox.PERMS[x].split(" (")[0] for x in p["perms"]) or "без разрешений"
            tk.Checkbutton(top, text=f"{p['name']} v{p['version']}\n   {perms}", variable=v,
                           justify="left", anchor="w").pack(fill="x", padx=10, pady=2)
        for e in self.perrors:
            tk.Label(top, text="⚠ " + e, anchor="w", wraplength=420, justify="left").pack(fill="x", padx=10)
        log = tk.Text(top, height=7, width=58)
        log.insert("end", "\n".join(self.plog[-15:]) or "журнал пуст")
        log.config(state="disabled")
        log.pack(padx=10, pady=8)

        def save():
            for p in self.plugins:
                want, rec = vars_[p["file"]].get(), self.cfg["plugins"][p["file"]]
                if want and not p["enabled"] and self.ask_install(p, False):
                    rec.update(approved=p["perms"], enabled=True, hash=p["hash"])
                elif not want and p["enabled"]:
                    rec["enabled"] = False
            save_cfg(self.cfg)
            messagebox.showinfo("Плагины", "Изменения применятся после перезапуска")
            top.destroy()
        tk.Button(top, text="Открыть папку плагинов", command=lambda: self.open_path(PLUG_DIR)).pack(fill="x", padx=10, pady=(0, 4), ipady=4)
        tk.Button(top, text="Сохранить", command=save).pack(fill="x", padx=10, pady=(0, 10), ipady=4)
        self.paint(top)

    # ---------- прокси ----------
    def set_proxy(self):
        link = simpledialog.askstring(
            "Прокси", "Вставьте ссылку tg://proxy?... или tg://socks?...\n(пусто = убрать прокси)")
        if link is None:
            return
        try:
            self.cfg["proxy"] = parse_proxy(link)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.cfg["mode"] = "auto"
        save_cfg(self.cfg)
        self.call(self.reconnect())

    async def reconnect(self):
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        await self.start()

    # ---------- выход ----------
    def logout(self):
        if messagebox.askyesno("Выход из аккаунта",
                               "Завершить сессию в Telegram и удалить все локальные данные приложения?"):
            self.call(self.do_logout())

    async def do_logout(self):
        try:
            await self.client.log_out()  # убирает устройство из «Активных сеансов»
        except Exception:
            pass
        self.ui(self.wipe_and_quit)

    def wipe_and_quit(self):
        if FROZEN:
            shutil.rmtree(DATA, ignore_errors=True)
        else:
            for f in os.listdir(DATA):
                if f.startswith("session") or f in ("config.json", "tmp"):
                    p = os.path.join(DATA, f)
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.path.exists(p) and os.remove(p)
        os._exit(0)

    def quit(self):
        try:
            if self.client:
                asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop).result(3)
        except Exception:
            pass
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        os._exit(0)  # процесс убит полностью, в фоне ничего не остаётся

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
