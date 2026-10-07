#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор "бумажной" Markdown-документации из единого манифеста Showcase (SSOT).
Источник правды: examples/showcase/content/showcase_docs.json
Генерирует:
- docs_ru/showcase_guide.md (Русская версия)
- docs/showcase_guide.md (Английская версия)
"""

import os
import sys
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT_DIR / "examples" / "showcase" / "content" / "showcase_docs.json"
DOCS_RU_DIR = ROOT_DIR / "docs_ru"
DOCS_EN_DIR = ROOT_DIR / "docs"


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Манифест не найден: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_markdown(manifest: dict, lang: str) -> str:
    sections = manifest.get("sections", [])
    is_ru = lang == "ru"

    title = "Архитектурное руководство и витрина возможностей rsgi-wsrpc" if is_ru else "rsgi-wsrpc Architecture Guide & Capabilities Showcase"
    intro = (
        "> **Примечание:** Данный документ автоматически сгенерирован из единого источника правды интерактивной витрины "
        "(`examples/showcase/content/showcase_docs.json`). Все приведенные примеры и RPC-контракты полностью рабочие."
        if is_ru else
        "> **Note:** This document is automatically generated from the Single Source of Truth of the interactive showcase "
        "(`examples/showcase/content/showcase_docs.json`). All examples and RPC contracts are verified and functional."
    )

    toc_title = "## Оглавление" if is_ru else "## Table of Contents"
    lines = [
        f"# {title}",
        "",
        intro,
        "",
        "---",
        "",
        toc_title,
        ""
    ]

    for s in sections:
        s_title = s["title"].get(lang, s["title"].get("en", ""))
        lines.append(f"- [{s['number']}. {s_title}](#{s['id']})")

    lines.append("")
    lines.append("---")
    lines.append("")

    for s in sections:
        s_title = s["title"].get(lang, s["title"].get("en", ""))
        s_summary = s["summary"].get(lang, s["summary"].get("en", ""))
        s_callout = s["callout"].get(lang, s["callout"].get("en", ""))
        code = s.get("code", {})

        lines.append(f"<a id=\"{s['id']}\"></a>")
        lines.append(f"## {s['icon']} {s['number']}. {s_title}")
        lines.append("")
        lines.append(f"> **Спецификация:** `{s['tag']}`" if is_ru else f"> **Specification:** `{s['tag']}`")
        lines.append("")
        lines.append(s_summary)
        lines.append("")
        lines.append(f"**{'Архитектурная суть' if is_ru else 'Architectural Concept'}:**")
        lines.append(s_callout)
        lines.append("")

        if code.get("python"):
            lines.append(f"### {'Бэкенд (Python)' if is_ru else 'Backend (Python)'}")
            lines.append("```python")
            lines.append(code["python"])
            lines.append("```")
            lines.append("")

        if code.get("typescript"):
            lines.append(f"### {'Клиент (TypeScript / JavaScript)' if is_ru else 'Client (TypeScript / JavaScript)'}")
            lines.append("```typescript")
            lines.append(code["typescript"])
            lines.append("```")
            lines.append("")

        if code.get("wire"):
            lines.append(f"### {'Сетевой протокол (JSON-RPC 2.0 Wire Frame)' if is_ru else 'Protocol Frame (JSON-RPC 2.0 Wire Format)'}")
            lines.append("```json")
            lines.append(code["wire"])
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    manifest = load_manifest()

    DOCS_RU_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_EN_DIR.mkdir(parents=True, exist_ok=True)

    # Генерация RU
    ru_md = generate_markdown(manifest, "ru")
    ru_file = DOCS_RU_DIR / "showcase_guide.md"
    with open(ru_file, "w", encoding="utf-8") as f:
        f.write(ru_md)
    print(f"✔ Создан: {ru_file}")

    # Генерация EN
    en_md = generate_markdown(manifest, "en")
    en_file = DOCS_EN_DIR / "showcase_guide.md"
    with open(en_file, "w", encoding="utf-8") as f:
        f.write(en_md)
    print(f"✔ Создан: {en_file}")

    print("\n🎉 'Бумажная' документация успешно синхронизирована с витриной!")


if __name__ == "__main__":
    main()
