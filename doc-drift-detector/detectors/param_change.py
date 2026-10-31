"""
detectors/param_change.py
=========================
STEP 2C: FUNCTION PARAMETER CHANGED DETECTOR

Detects when function signatures or parameter default values have changed:
- Added parameters: `def foo(a, b)` -> `def foo(a, b, c)`
- Removed parameters: `def foo(a, b, c)` -> `def foo(a, b)`
- Changed parameter defaults: `def foo(a, b=10)` -> `def foo(a, b=20)`

Supports Python via AST parser (with fallback to regex), as well as
JavaScript/TypeScript, Go, Rust, and Java via regex.

Output:
  CodeChange(type="PARAM_CHANGED", name=func_name, file=..., line=...,
             details={"function": func_name, "old_params": [...], "new_params": [...]})
"""

import ast
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from utils.diff_parser import FileDiff, DiffLine
from . import CodeChange


# Generic regex for function declarations across multiple languages
FUNC_DEF_REGEX = re.compile(
    r"""
    ^\s*(?:async\s+)?(?:def|function|func|fn)\s+  # def / function / func / fn keyword
    ([a-zA-Z_][a-zA-Z0-9_]*)\s*                    # function name
    \((.*?)\)                                      # raw parameter list
    """,
    re.VERBOSE
)

# Arrow functions / const declarations: const foo = (a, b) =>
ARROW_FUNC_REGEX = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>"
)


def parse_python_params_via_ast(sig_text: str) -> Optional[List[str]]:
    """
    Parses a python function definition line using Python's `ast` module.
    Returns a clean list of parameter representations, e.g. ['a', 'b=10', '*args', '**kwargs'].
    """
    code = f"{sig_text.strip()}:\n    pass"
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params: List[str] = []
                args = node.args

                # Positional / standard args with defaults
                num_defaults = len(args.defaults)
                num_args = len(args.args)
                pos_default_start = num_args - num_defaults

                for i, arg in enumerate(args.args):
                    arg_name = arg.arg
                    if i >= pos_default_start:
                        default_node = args.defaults[i - pos_default_start]
                        val_str = ast.unparse(default_node) if hasattr(ast, "unparse") else "..."
                        params.append(f"{arg_name}={val_str}")
                    else:
                        params.append(arg_name)

                # *vararg
                if args.vararg:
                    params.append(f"*{args.vararg.arg}")

                # kwonly args
                for i, kwarg in enumerate(args.kwonlyargs):
                    kw_default = args.kw_defaults[i]
                    if kw_default:
                        val_str = ast.unparse(kw_default) if hasattr(ast, "unparse") else "..."
                        params.append(f"{kwarg.arg}={val_str}")
                    else:
                        params.append(kwarg.arg)

                # **kwarg
                if args.kwarg:
                    params.append(f"**{args.kwarg.arg}")

                return params
    except Exception:
        pass
    return None


def parse_params_regex(raw_params: str) -> List[str]:
    """
    Fallback parameter list parser: splits parameter strings handling nested commas.
    """
    if not raw_params.strip():
        return []

    params: List[str] = []
    current: List[str] = []
    depth = 0

    for ch in raw_params:
        if ch in "([{'\"":
            depth += 1
            current.append(ch)
        elif ch in ")]}'\"":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            params.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        token = "".join(current).strip()
        if token:
            params.append(token)

    # Filter out self/cls if first parameter in Python methods
    if params and params[0] in ("self", "cls"):
        params = params[1:]

    return params


def extract_function_signature(line_text: str) -> Optional[Tuple[str, List[str]]]:
    """
    Extracts (function_name, parameter_list) from a line of code.
    Tries AST parsing first for Python, then regex.
    """
    stripped = line_text.strip()

    # Try Python AST if it starts with def
    if stripped.startswith("def ") or stripped.startswith("async def "):
        # Ensure it has colon or closing paren
        clean_sig = stripped.split(":", 1)[0]
        params = parse_python_params_via_ast(clean_sig)
        if params is not None:
            name_match = re.search(r"(?:def|async def)\s+([a-zA-Z_][a-zA-Z0-9_]*)", clean_sig)
            if name_match:
                # Filter out self/cls
                filtered_params = [p for p in params if p not in ("self", "cls")]
                return name_match.group(1), filtered_params

    # Regex search for standard functions
    match = FUNC_DEF_REGEX.search(stripped)
    if match:
        func_name = match.group(1)
        raw_params = match.group(2)
        return func_name, parse_params_regex(raw_params)

    # Regex search for arrow functions
    arrow_match = ARROW_FUNC_REGEX.search(stripped)
    if arrow_match:
        func_name = arrow_match.group(1)
        raw_params = arrow_match.group(2)
        return func_name, parse_params_regex(raw_params)

    return None


def detect_param_changes(file_diff: FileDiff) -> List[CodeChange]:
    """
    STEP 2C: Detect changed function parameters in a FileDiff.
    Finds function signatures modified between removed lines and added lines.
    """
    changes: List[CodeChange] = []

    # Map removed function signatures: func_name -> (params, line_number)
    removed_funcs: Dict[str, Tuple[List[str], int]] = {}

    for line in file_diff.removed_lines:
        res = extract_function_signature(line.content)
        if res:
            func_name, params = res
            removed_funcs[func_name] = (params, line.line_number)

    # Compare with added function signatures
    for line in file_diff.added_lines:
        res = extract_function_signature(line.content)
        if res:
            func_name, new_params = res
            if func_name in removed_funcs:
                old_params, old_line = removed_funcs[func_name]
                if old_params != new_params:
                    # Identify specific parameter differences
                    old_param_names = [p.split("=")[0].strip() for p in old_params]
                    new_param_names = [p.split("=")[0].strip() for p in new_params]

                    removed_p = [p for p in old_param_names if p not in new_param_names]
                    added_p = [p for p in new_param_names if p not in old_param_names]

                    # Detect modified defaults
                    old_defaults = {
                        p.split("=")[0].strip(): p.split("=")[1].strip()
                        for p in old_params if "=" in p
                    }
                    new_defaults = {
                        p.split("=")[0].strip(): p.split("=")[1].strip()
                        for p in new_params if "=" in p
                    }
                    modified_defaults = {
                        k: (old_defaults[k], new_defaults[k])
                        for k in old_defaults
                        if k in new_defaults and old_defaults[k] != new_defaults[k]
                    }

                    changes.append(
                        CodeChange(
                            change_type="PARAM_CHANGED",
                            name=func_name,
                            file=file_diff.file_path,
                            line=line.line_number,
                            old_value=", ".join(old_params),
                            new_value=", ".join(new_params),
                            details={
                                "function": func_name,
                                "old_params": old_params,
                                "new_params": new_params,
                                "removed_params": removed_p,
                                "added_params": added_p,
                                "modified_defaults": modified_defaults,
                                "old_line": old_line,
                                "raw_diff": f"- def {func_name}({', '.join(old_params)}) / + def {func_name}({', '.join(new_params)})"
                            }
                        )
                    )

    return changes

