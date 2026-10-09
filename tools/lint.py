"""静态体检：查 `compileall` 查不出的那类问题（尤其是「漏导入」）。

背景：Python 只在**运行到那一行**时才解析函数体内的名字，所以
`python -m compileall`（甚至 `import` 整个包）都发现不了函数里写了一个
没导入的类名 —— 直到用户真的点到那个按钮。NovaNote 就因此让整条
"快速记录"链路一用就崩（`dialogs.py` 少导入 `QPlainTextEdit`）。

用法：
    python tools/lint.py            # 只报错误级问题（未定义名字等）
    python tools/lint.py --all      # 连"未使用的导入"一起报

优先使用 pyflakes（判定最可靠）；未安装时降级为内置 AST 检查。
安装 pyflakes（一次性，建议装在隔离环境）：
    pip install pyflakes -i https://pypi.tuna.tsinghua.edu.cn/simple
"""
from __future__ import annotations

import ast
import builtins
import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = ["novanote", "main.py", "tools", "build_exe.py"]

# 这些类别不算"错误"，属整洁性问题
_NOT_ERROR = ("imported but unused", "never used")

# 作用域内可用的名字里，这些特殊名字总是合法
_SPECIAL = {"self", "cls", "__class__", "__name__", "__file__", "__doc__"}


def _iter_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for t in TARGETS:
        p = ROOT / t
        if p.is_dir():
            out += sorted(p.rglob("*.py"))
        elif p.suffix == ".py":
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# 首选：pyflakes
# --------------------------------------------------------------------------- #
def run_pyflakes(all_mode: bool) -> int | None:
    """返回 None 表示 pyflakes 不可用（交由调用方降级）。"""
    # 注意：不能用 except OSError 判断 —— `python -m pyflakes` 在未安装时
    # 只是返回非零并往 stderr 写 "No module named pyflakes"，不抛异常。
    if importlib.util.find_spec("pyflakes") is None:
        return None

    r = subprocess.run(
        [sys.executable, "-m", "pyflakes", *[str(p) for p in _iter_files()]],
        capture_output=True, text=True,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    errors = [ln for ln in lines if not any(k in ln for k in _NOT_ERROR)]
    shown = lines if all_mode else errors

    for ln in shown:
        print(f"  {ln}")
    if not shown:
        print("  ✓ 未发现未定义名字等问题")
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
# 降级：内置 AST 检查（无外部依赖）
# --------------------------------------------------------------------------- #
def _scope_bindings(stmts: list[ast.stmt], args: ast.arguments | None = None) -> set[str]:
    """收集**某一个作用域**内绑定的名字。

    关键点：遇到嵌套的函数 / 类只取其**名字**，**不深入其函数体** ——
    否则嵌套函数里的局部变量会被误当成外层可用，掩盖真正的漏导入。
    """
    names: set[str] = set()
    if args is not None:
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        every += [a for a in (args.vararg, args.kwarg) if a is not None]
        names |= {a.arg for a in every}

    stack: list[ast.AST] = list(stmts)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
            continue                      # 不深入
        if isinstance(n, ast.Lambda):
            continue                      # 不深入
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, ast.ExceptHandler) and isinstance(n.name, str):
            names.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names |= set(n.names)
        stack.extend(ast.iter_child_nodes(n))
    return names


def _check_node(node: ast.AST, visible: set[str], scope_name: str,
                rel: str, out: list[str]) -> None:
    """递归检查。`visible` 含**所有外层作用域**的名字 —— 这样闭包变量
    （嵌套函数引用外层局部变量）不会被误报。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inner = visible | _scope_bindings(child.body, child.args)
            _check_node(child, inner, child.name, rel, out)
        elif isinstance(child, ast.ClassDef):
            # 类体是一个独立作用域：形如 `_apply_bg = _sync_style` 这样的
            # 类体内别名赋值，右侧引用的正是同类中定义的方法名，必须可见。
            inner = visible | _scope_bindings(child.body) | {child.name}
            _check_node(child, inner, child.name, rel, out)
        elif isinstance(child, ast.Lambda):
            inner = visible | _scope_bindings([child.body], child.args)
            _check_node(child, inner, "<lambda>", rel, out)
        else:
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in visible and child.id not in _SPECIAL:
                    out.append(f"{rel}:{child.lineno}: 在 {scope_name}() 中"
                               f"使用了未定义的名字 {child.id!r}")
            _check_node(child, visible, scope_name, rel, out)


def fallback_ast_check() -> int:
    print("  （未安装 pyflakes，使用内置 AST 检查 —— 建议 pip install pyflakes）")
    problems: list[str] = []
    for path in _iter_files():
        rel = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            problems.append(f"{rel}:{e.lineno}: 语法错误 {e.msg}")
            continue
        visible = set(dir(builtins)) | _SPECIAL | _scope_bindings(tree.body)
        _check_node(tree, visible, "<module>", rel, problems)

    for msg in problems:
        print(f"  {msg}")
    if not problems:
        print("  ✓ 未发现未定义名字")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    print("NovaNote 静态体检")
    rc = run_pyflakes("--all" in argv)
    if rc is None:
        rc = fallback_ast_check()
    print("完成" if rc == 0 else "发现问题（见上）")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
