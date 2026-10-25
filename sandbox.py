"""Песочница плагинов TgMini: статическая проверка кода + урезанное окружение.

Это защита от случайных и грубых злоупотреблений, а не гарантия против
целенаправленного взлома. Ставьте только плагины, которым доверяете.
"""
import ast, builtins, json, math, random, re, time
from types import SimpleNamespace

PERMS = {
    "read_messages": "читать сообщения (входящие и исходящие)",
    "send_messages": "отправлять сообщения от вашего имени",
    "notify": "показывать уведомления",
    "storage": "хранить свои данные в настройках",
}
BAD_NAMES = {"eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "vars", "globals",
             "locals", "dir", "input", "breakpoint", "memoryview", "type", "super", "object"}
BAD_ATTRS = {"format", "format_map", "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code",
             "cr_await", "ag_frame", "ag_code", "f_globals", "f_locals", "f_back", "f_builtins",
             "f_code", "tb_frame", "tb_next", "mro"}
SAFE = ("abs all any bool dict enumerate filter float int isinstance len list map max min range "
        "reversed round set sorted str sum tuple zip repr divmod chr ord bin hex Exception "
        "ValueError KeyError TypeError IndexError ArithmeticError __build_class__").split()


class PluginError(Exception):
    pass


def check(src):
    """Разбирает код и запрещает опасные конструкции. Ничего не выполняет."""
    if len(src) > 200_000:
        raise PluginError("файл слишком большой")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise PluginError(f"синтаксическая ошибка: {e}")
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            raise PluginError("import запрещён (re, json, time, math, random уже доступны)")
        if isinstance(n, ast.Attribute) and (n.attr.startswith("_") or n.attr in BAD_ATTRS):
            raise PluginError(f"запрещённый атрибут .{n.attr}")
        if isinstance(n, ast.Name) and (n.id in BAD_NAMES or n.id.startswith("__")):
            raise PluginError(f"запрещённое имя {n.id}")
    return tree


def read_meta(tree):
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "META" for t in n.targets):
            try:
                m = ast.literal_eval(n.value)
            except Exception:
                raise PluginError("META должна быть словарём-литералом")
            if not isinstance(m, dict) or not isinstance(m.get("name"), str):
                raise PluginError("в META нужно поле name")
            perms = m.get("permissions", [])
            if not isinstance(perms, list):
                raise PluginError("permissions должен быть списком")
            bad = [p for p in perms if p not in PERMS]
            if bad:
                raise PluginError(f"неизвестное разрешение: {bad[0]}")
            return {"name": m["name"][:40], "version": str(m.get("version", "?"))[:20],
                    "author": str(m.get("author", ""))[:40], "permissions": list(dict.fromkeys(perms))}
    raise PluginError("нет META")


def _modules():
    return {
        "re": SimpleNamespace(search=re.search, match=re.match, fullmatch=re.fullmatch, findall=re.findall,
                              sub=re.sub, split=re.split, compile=re.compile, I=re.I, M=re.M),
        "json": SimpleNamespace(loads=json.loads, dumps=json.dumps),
        "time": SimpleNamespace(time=time.time, strftime=time.strftime),
        "math": SimpleNamespace(**{k: getattr(math, k) for k in
                                   ("floor", "ceil", "sqrt", "pi", "log", "sin", "cos", "fabs")}),
        "random": SimpleNamespace(random=random.random, randint=random.randint, choice=random.choice),
    }


def run(tree, name, api):
    g = {"__builtins__": {k: getattr(builtins, k) for k in SAFE}, "__name__": "plugin_" + name, **_modules()}
    exec(compile(tree, f"<plugin {name}>", "exec"), g)
    setup = g.get("setup")
    if not callable(setup):
        raise PluginError("нет функции setup(api)")
    setup(api)
