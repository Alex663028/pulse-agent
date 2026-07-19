'''Sandboxed Python execution using process isolation and static analysis.'''

from __future__ import annotations

import ast
import io
import multiprocessing
import sys
from typing import Any


# Allowed modules (read-only operations only)
_ALLOWED_MODULES = {
    'math', 'statistics', 'random', 'datetime', 'collections',
    'itertools', 'functools', 'decimal', 'fractions', 'typing',
    'copy', 'json', 're', 'string', 'hashlib', 'operator',
    'dataclasses', 'enum', 'numbers', 'array', 'bisect', 'heapq',
    'pprint', 'textwrap', 'calendar', 'base64', 'binascii',
}

# Blocked attributes that could escape sandbox
_BLOCKED_ATTRS = {
    '__class__', '__bases__', '__mro__', '__subclasses__',
    '__globals__', '__code__', '__builtins__', '__dict__',
    '__init__', '__new__', '__del__', '__getattribute__',
    '__setattr__', '__delattr__', '__get__', '__set__', '__delete__',
}


class SandboxError(Exception):
    '''Raised when sandbox security is violated.'''


def _check_node(node: ast.AST) -> str | None:
    '''Check an AST node for dangerous patterns. Returns error or None.'''
    # Block attribute access to dunder attributes
    if isinstance(node, ast.Attribute):
        if node.attr in _BLOCKED_ATTRS:
            return f"access to '{node.attr}' is not allowed in sandbox"
    
    # Block compile/exec/eval/__import__ calls
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ('compile', 'eval', 'exec', 'execfile'):
            return f"function '{func.id}' is not allowed in sandbox"
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('compile', 'eval', 'exec'):
            return f"function '{node.func.attr}' is not allowed in sandbox"
    
    # Block __import__ calls (we control imports separately)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == '__import__':
            return 'use import statements instead of __import__()'
    
    return None


def check_code_safety(code: str) -> str | None:
    '''Static analysis: reject dangerous patterns. Returns error message or None.'''
    try:
        tree = ast.parse(code, mode='exec')
    except SyntaxError as e:
        return f'syntax error: {e}'

    for node in ast.walk(tree):
        result = _check_node(node)
        if result:
            return result
    
    return None


def _restricted_import(name: str, *args: Any, **kwargs: Any) -> Any:
    '''Import function that only allows whitelisted modules.'''
    top_level = name.split('.', 1)[0]
    if top_level not in _ALLOWED_MODULES:
        raise ImportError(
            f"module '{name}' is not allowed in sandbox. "
            f"Allowed modules: {sorted(_ALLOWED_MODULES)}"
        )
    return __import__(name, *args, **kwargs)


def _get_restricted_globals() -> dict[str, Any]:
    '''Build a restricted globals dict with only safe builtins.'''
    import builtins as _builtins
    safe_names = {
        'abs', 'all', 'any', 'bin', 'bool', 'bytes', 'chr', 'complex',
        'dict', 'dir', 'divmod', 'enumerate', 'filter', 'float', 'format',
        'frozenset', 'hasattr', 'hash', 'hex', 'id', 'int', 'isinstance',
        'issubclass', 'iter', 'len', 'list', 'map', 'max', 'min', 'next',
        'object', 'oct', 'ord', 'pow', 'print', 'range', 'repr', 'reversed',
        'round', 'set', 'slice', 'sorted', 'str', 'sum', 'tuple', 'type',
        'vars', 'zip', 'True', 'False', 'None', 'Ellipsis', 'NotImplemented',
        'ArithmeticError', 'AssertionError', 'AttributeError', 'BaseException',
        'Exception', 'EOFError', 'GeneratorExit', 'ImportError', 'IndexError',
        'KeyError', 'LookupError', 'MemoryError', 'NameError', 'NotImplementedError',
        'OSError', 'OverflowError', 'RuntimeError', 'StopIteration', 'SyntaxError',
        'SystemExit', 'TabError', 'TypeError', 'ValueError', 'ZeroDivisionError',
    }
    safe_builtins = {name: getattr(_builtins, name) for name in safe_names if hasattr(_builtins, name)}
    safe_builtins['__import__'] = _restricted_import
    safe_builtins['__build_class__'] = getattr(_builtins, '__build_class__', None)
    return {'__builtins__': safe_builtins}


def _exec_target(code_str: str, result_queue: multiprocessing.Queue) -> None:
    '''Target function for sandboxed execution in a separate process.'''
    try:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            restricted_globals = _get_restricted_globals()
            compiled = compile(code_str, '<sandbox>', 'exec')
            exec(compiled, restricted_globals)
            output = sys.stdout.getvalue()
            result_queue.put(('ok', output))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    except Exception as e:
        result_queue.put(('error', str(e)))


def run_sandboxed(code: str, timeout: int = 5) -> str:
    '''Execute Python code in a sandboxed environment. Returns output string.'''
    # Static analysis first
    safety_error = check_code_safety(code)
    if safety_error:
        return f'SandboxError: {safety_error}'
    
    # Use multiprocessing for true isolation
    result_queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=_exec_target, args=(code, result_queue))
    proc.start()
    proc.join(timeout=timeout + 2)
    
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
        return f'SandboxError: execution timed out after {timeout}s'
    
    if result_queue.empty():
        return 'SandboxError: process exited without result'
    
    status, output = result_queue.get()
    if status == 'error':
        return f'SandboxError: {output}'
    return output if output else '(no output)'
