# Coding Style and Control Flow

## Style and Readability

- Do not use emojis in code or comments.
- Keep log output concise and professional.
- Modules/files: `snake_case` (for example `browser_agent.py`).
- Classes: `PascalCase`; keep acronyms explicit (for example `CDPClient`, `LLMProvider`).
- Functions/variables: `snake_case`; avoid ambiguous abbreviations.
- Constants: `UPPER_SNAKE_CASE`.
- Prefer explicit names when short names are unclear.

## Typing and Documentation

- Use `from __future__ import annotations`.
- Use Python type hints for function arguments and return values.
- Use `typing` types for complex annotations (for example `List`, `Dict`, `Optional`, `Any`).
- Keep docs concise and non-redundant.
- Write key API documentation in English.

## Simplicity and Control Flow

- Prefer the smallest correct change with clear control flow.
- Prefer guard clauses and early returns over deep nesting.
- Do not add `else` after branches that already `return`, `raise`, or `continue`.
- Keep branch depth shallow.
- Maximum nesting depth: `2`.
- Maximum branches in one `if/elif/else` block: `3`.
- Refactor to helpers or strategy mapping when more branches are needed.
- Keep functions focused.
- Target length: `<= 40` lines (excluding docstrings/comments).
- Split oversized functions by responsibility.
- Centralize SDK compatibility/fallback complexity in one private helper.
- New branches must be necessity-driven; do not add speculative compatibility branches.
- During PR updates, prefer removing complexity over adding patch branches.
- Fail fast by default.
- Do not wrap the normal path in broad defensive `try` blocks.
- Catch exceptions only when there is a clear recovery action.
- Let unrecoverable errors raise.
