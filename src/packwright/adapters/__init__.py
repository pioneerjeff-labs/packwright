from .claude_code import compile_to_claude_code, compile_to_claude_code_pack
from .codex import compile_to_codex_pack
from .cursor import compile_to_cursor_pack


ADAPTER_COMPILERS = {
    "codex": compile_to_codex_pack,
    "claude-code": compile_to_claude_code_pack,
    "cursor": compile_to_cursor_pack,
}


def compile_adapter_pack(adapter, mechanism, references=None):
    try:
        compiler = ADAPTER_COMPILERS[adapter]
    except KeyError as exc:
        raise ValueError(f"unsupported adapter: {adapter}") from exc
    return compiler(mechanism, references=references)

__all__ = [
    "compile_to_claude_code",
    "compile_to_claude_code_pack",
    "compile_to_codex_pack",
    "compile_to_cursor_pack",
    "compile_adapter_pack",
]
