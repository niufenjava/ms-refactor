#!/usr/bin/env python3
"""
engine_refactor.py - 代码风格重构引擎

用法：python3 engine_refactor.py run "<目标>"
目标：文件路径 / 目录路径 / 项目名（在 ~/my-projects/ 下查找）

输出：markdown 格式改动清单（含 diff），供人工确认后执行。
"""

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
LLM_CALL_PY = Path.home() / "my-projects" / "claw-scripts" / "llm" / "llm_call.py"
MY_PROJECTS = Path.home() / "my-projects"

# 扩展名 -> 语言
EXT_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript (JSX)",
    ".tsx": "TypeScript (TSX)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Bash",
    ".zsh": "Zsh",
    ".lua": "Lua",
    ".r": "R",
    ".sql": "SQL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md": "Markdown",
    ".txt": "Text",
}

# 语言 -> 注释风格 + 文件扩展名 + 索引命令
LANG_CONFIG = {
    "Python": {
        "comment": "#",
        "docstring": '"""',
        "exts": {".py"},
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.py", "-not", "-path", "*/__pycache__/*"],
    },
    "JavaScript": {
        "comment": "//",
        "docstring": "/**",
        "exts": {".js", ".jsx"},
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.js", "-not", "-path", "*/node_modules/*"],
    },
    "TypeScript": {
        "comment": "//",
        "docstring": "/**",
        "exts": {".ts", ".tsx"},
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.ts", "-not", "-path", "*/node_modules/*"],
    },
    "Go": {
        "comment": "//",
        "docstring": "//",
        "exts": {".go"},
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.go"],
    },
    "Rust": {
        "comment": "//",
        "docstring": "///",
        "exts": {".rs"},
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.rs"],
    },
    "Shell": {
        "comment": "#",
        "docstring": "#",
        "exts": {".sh", ".bash", ".zsh"},
        "index_cmd": ["find", "{path}", "-type", "f", "(", "-name", "*.sh", "-o", "-name", "*.bash", "-o", "-name", "*.zsh", ")"],
    },
}


def resolve_target(raw: str) -> Path:
    """将字符串解析为真实文件路径。"""
    raw = raw.strip().strip('"').strip("'")
    p = Path(raw)
    if p.exists():
        return p.resolve()
    if raw.startswith("./") or raw.startswith("../"):
        p = Path(raw).resolve()
        if p.exists():
            return p
    project_dir = MY_PROJECTS / raw
    if project_dir.exists():
        return project_dir.resolve()
    raise FileNotFoundError(f"目标不存在或无法定位：{raw}")


def detect_language(path: Path) -> str:
    """根据扩展名判断语言；目录时只统计代码文件扩展名，取最多语言。"""
    if path.is_file():
        return EXT_MAP.get(path.suffix, "Unknown")
    # 目录：只统计已知代码扩展名，取最多
    code_exts = set(EXT_MAP.keys()) - {".txt", ".md", ".json", ".yaml", ".yml", ".toml"}
    try:
        result = subprocess.run(
            ["find", str(path), "-type", "f"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            exts = [Path(f).suffix for f in result.stdout.strip().split("\n") if f and Path(f).suffix in code_exts]
            if exts:
                most_common = Counter(exts).most_common(1)
                return EXT_MAP.get(most_common[0][0], "Unknown")
    except Exception:
        pass
    return "Unknown"


def get_lang_config(lang: str) -> dict:
    return LANG_CONFIG.get(lang, {
        "comment": "//",
        "docstring": "//",
        "exts": set(),
        "index_cmd": ["find", "{path}", "-type", "f"],
    })


def scan_files(path: Path, config: dict) -> list[Path]:
    """返回匹配扩展名的文件列表。"""
    if path.is_file():
        return [path] if path.suffix in config["exts"] else []
    cmd = [arg.replace("{path}", str(path)) for arg in config["index_cmd"]]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [Path(f) for f in result.stdout.strip().split("\n") if f]


def scan_structure(path: Path, lang: str) -> dict:
    """扫描代码结构：文件列表 + 函数/类列表。"""
    config = get_lang_config(lang)
    code_files = scan_files(path, config)

    structure = {}
    for f in code_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = content.split("\n")

        items = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if lang == "Python":
                if stripped.startswith("def ") or stripped.startswith("class "):
                    items.append(f"[L{i+1}] {stripped}")
            else:
                if any(stripped.startswith(k) for k in ("func ", "function ", "class ", "struct ")):
                    items.append(f"[L{i+1}] {stripped}")

        structure[str(f)] = {
            "lines": len(lines),
            "items": items,
            "preview": "\n".join(lines[:30]) if lines else "",
        }

    return {"total_files": len(code_files), "files": structure}


def build_prompt(path: Path, lang: str, structure: dict) -> str:
    """构建 LLM 重构分析 prompt。"""
    config = get_lang_config(lang)
    files_items = list(structure["files"].items())[:12]  # 最多 12 个文件

    files_text = ""
    for fpath, info in files_items:
        try:
            rel = fpath[str(path)].lstrip("/") if str(path) in fpath else fpath
        except Exception:
            rel = fpath
        files_text += f"\n### {rel}（{info['lines']} 行）\n"
        if info["items"]:
            files_text += "符号：\n" + "\n".join(info["items"]) + "\n"
        files_text += f"\n```\n{info['preview'][:600]}\n```\n"

    return f"""你是代码重构专家，在不改变程序行为的前提下，优化代码风格和补充注释。

## 目标
- 路径：{path}
- 语言：{lang}
- 注释：{config['comment']} / 文档：{config['docstring']}
- 文件数：{structure['total_files']}（展示前 {len(files_items)} 个）

{files_text}

## 原则
1. **不改逻辑** — 只改风格和注释，不改动代码行为
2. **风格一致** — 遵循项目已有风格，不引入外来风格
3. **注释有价值** — 解释「为什么」，不解释「是什么」
4. **最小改动** — 精确到具体行，不大段重写

## 检查维度
- 命名：变量/函数/类名是否清晰可读
- 函数长度：>50 行建议拆分
- 嵌套深度：if/else 过深建议简化
- 注释缺失：关键逻辑缺少说明
- 重复代码：可提取的重复片段
- 参数校验：是否校验输入边界

## 输出格式（严格按此格式）

---
### File: <相对路径>
**问题**：
- <每条问题一行>

**改动**：
```diff
- 原代码（精确到相关行）
+ 改动后代码
```
---

- 只输出有问题的文件，无需改动则标记「无需改动」
- diff 用 unified diff 格式
- 代码截取不超过 10 行
- 全程中文输出
"""


def analyze_and_plan(path: Path, lang: str) -> str:
    """调用 LLM 生成重构计划。"""
    structure = scan_structure(path, lang)
    if structure["total_files"] == 0:
        return f"⚠️ 未找到 {lang} 代码文件，请确认目标路径是否正确。"

    prompt = build_prompt(path, lang, structure)

    try:
        sys.path.insert(0, str(LLM_CALL_PY.parent))
        from llm_call import safe_llm_call
    except Exception as e:
        return f"⚠️ LLM 调用失败：{e}"

    ok, result = safe_llm_call(prompt, "")
    if ok:
        return result
    return "⚠️ LLM 分析失败，请重试。"


def main():
    parser = argparse.ArgumentParser(description="代码风格重构引擎")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("target", nargs="?", default="", help="目标：文件路径/目录/项目名")
    args = parser.parse_args()

    if args.command != "run":
        return

    if not args.target:
        print("⚠️ 请提供目标路径或项目名", file=sys.stderr)
        print("用法：ms sk refactor <path|name>", file=sys.stderr)
        sys.exit(1)

    try:
        target_path = resolve_target(args.target)
    except FileNotFoundError as e:
        print(f"⚠️ {e}", file=sys.stderr)
        sys.exit(1)

    lang = detect_language(target_path)
    print(f"📂 目标：{target_path}", file=sys.stderr)
    print(f"🔍 语言：{lang}", file=sys.stderr)
    print(f"⏳ 分析中…", file=sys.stderr)

    plan = analyze_and_plan(target_path, lang)

    print("\n" + "=" * 60)
    print("📋 代码重构计划")
    print("=" * 60)
    print(plan)
    print("=" * 60)
    print("\n✅ 分析完成。确认无误后，OpenCode 将执行以上改动。")
    print("💡 回复「确认」执行全部改动，或指定具体文件只改部分。")


if __name__ == "__main__":
    sys.exit(main())
