#!/usr/bin/env python3
"""
engine_refactor.py - 代码风格重构引擎

用法：
  python3 engine_refactor.py analyze "<目标>"    # 分析并生成 diff 清单
  python3 engine_refactor.py apply "<目标>"      # 执行 diff 清单（需先 analyze）
  python3 engine_refactor.py exec "<目标>"       # 分析 + 确认后执行

目标：文件路径 / 目录路径 / 项目名（在 ~/my-projects/ 下查找）

输出：markdown 格式改动清单（含 diff），exec 模式确认后执行。
"""

import argparse
import ast
import difflib
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
LLM_CALL_PY = Path.home() / "my-projects" / "claw-scripts" / "llm" / "llm_call.py"
MY_PROJECTS = Path.home() / "my-projects"

LANG_CONFIG = {
    "Python": {
        "exts": {".py"},
        "comment": "#",
        "docstring": '"""',
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.py", "-not", "-path", "*/__pycache__/*"],
        "parser": "ast",
    },
    "JavaScript": {
        "exts": {".js", ".jsx"},
        "comment": "//",
        "docstring": "/**",
        "index_cmd": ["find", "{path}", "-type", "f", "(", "-name", "*.js", "-o", "-name", "*.jsx", ")", "-not", "-path", "*/node_modules/*"],
        "parser": "regex",
    },
    "TypeScript": {
        "exts": {".ts", ".tsx"},
        "comment": "//",
        "docstring": "/**",
        "index_cmd": ["find", "{path}", "-type", "f", "(", "-name", "*.ts", "-o", "-name", "*.tsx", ")", "-not", "-path", "*/node_modules/*"],
        "parser": "regex",
    },
    "Go": {
        "exts": {".go"},
        "comment": "//",
        "docstring": "//",
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.go"],
        "parser": "regex",
    },
    "Rust": {
        "exts": {".rs"},
        "comment": "//",
        "docstring": "///",
        "index_cmd": ["find", "{path}", "-type", "f", "-name", "*.rs"],
        "parser": "regex",
    },
    "Shell": {
        "exts": {".sh", ".bash", ".zsh"},
        "comment": "#",
        "docstring": "#",
        "index_cmd": ["find", "{path}", "-type", "f", "(", "-name", "*.sh", "-o", "-name", "*.bash", "-o", "-name", "*.zsh", ")"],
        "parser": "regex",
    },
}

EXT_TO_LANG = {ext: lang for lang, cfg in LANG_CONFIG.items() for ext in cfg["exts"]}

BINARY_EXTS = {".so", ".dylib", ".a", ".o", ".obj", ".exe", ".dll", ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".pdf"}


def resolve_target(raw: str) -> Path:
    """将字符串解析为真实文件路径。支持模糊搜索项目目录。"""
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

    fuzzy_dir = search_projects(raw)
    if fuzzy_dir:
        return fuzzy_dir

    raise FileNotFoundError(f"目标不存在或无法定位：{raw}")


def search_projects(keyword: str) -> Optional[Path]:
    """在 ~/my-projects/ 下模糊搜索匹配目录。返回第一个匹配或 None。"""
    if not keyword or not MY_PROJECTS.exists():
        return None
    keyword_lower = keyword.lower()
    try:
        for item in MY_PROJECTS.iterdir():
            if item.is_dir() and keyword_lower in item.name.lower():
                return item.resolve()
    except PermissionError:
        pass
    return None


def is_binary(path: Path) -> bool:
    """检查是否为二进制文件。"""
    if path.suffix in BINARY_EXTS:
        return True
    try:
        with open(path, "rb") as f:
            f.read(1024)
        return False
    except Exception:
        return True


def detect_language(path: Path) -> tuple[str, str]:
    """检测语言，返回 (语言名, 理由)。目录时取最多代码扩展名。"""
    if path.is_file():
        if path.suffix in EXT_TO_LANG:
            return EXT_TO_LANG[path.suffix], f"扩展名 {path.suffix}"
        if path.suffix == ".h":
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                if "namespace" in content or "std::" in content or "cout" in content:
                    return "C++", "C++ 特性 detected"
                if "#include <stdio.h>" in content or "#include <stdlib.h>" in content:
                    return "C", "C 标准库 detected"
            except Exception:
                pass
            return "C/C++", "默认 C/C++"
        if is_binary(path):
            return "Unknown", "二进制文件"
        return "Unknown", f"未知扩展名 {path.suffix}"

    code_exts = set(EXT_TO_LANG.keys())
    try:
        result = subprocess.run(
            ["find", str(path), "-type", "f"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            exts = [
                Path(f).suffix for f in result.stdout.strip().split("\n")
                if f and Path(f).suffix in code_exts
            ]
            if exts:
                most_common = Counter(exts).most_common(1)[0]
                return EXT_TO_LANG[most_common[0]], f"目录下最多 {most_common[1]} 个 {most_common[0]} 文件"
    except subprocess.TimeoutExpired:
        return "Unknown", "扫描超时"
    except Exception:
        pass
    return "Unknown", "未找到代码文件"


def get_lang_config(lang: str) -> dict:
    """根据语言名返回配置字典，包含默认值保护。"""
    defaults = {
        "comment": "//",
        "docstring": "//",
        "exts": set(),
        "index_cmd": ["find", "{path}", "-type", "f"],
        "parser": "regex",
    }
    return LANG_CONFIG.get(lang, defaults)


def scan_files(path: Path, config: dict) -> list[Path]:
    """返回匹配扩展名的文件列表。"""
    if path.is_file():
        return [path] if path.suffix in config["exts"] else []
    cmd = [arg.replace("{path}", str(path)) for arg in config["index_cmd"]]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []
    return [Path(f) for f in result.stdout.strip().split("\n") if f and Path(f).suffix in config["exts"]]


def parse_python_structure(content: str, filepath: str) -> list[dict]:
    """用 ast 解析 Python 代码结构。"""
    items = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        return [{"type": "error", "name": f"ParseError: {e}", "line": 0, "col": 0}]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "col": node.col_offset,
                "end_line": getattr(node, "end_lineno", node.lineno),
            })
        elif isinstance(node, ast.ClassDef):
            items.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno,
                "col": node.col_offset,
                "end_line": getattr(node, "end_lineno", node.lineno),
            })
    return items


_REGEX_PATTERNS = {
    "JavaScript": [
        (r'(?:async\s+)?function\s+(\w+)', 'function'),
        (r'(?:const|let|var)\s+(\w+)\s*=', 'const'),
        (r'class\s+(\w+)', 'class'),
    ],
    "TypeScript": [
        (r'(?:async\s+)?function\s+(\w+)', 'function'),
        (r'(?:const|let|var)\s+(\w+)\s*[=:](?:(?!\breturn\b)[^;])+;', 'const'),
        (r'class\s+(\w+)', 'class'),
        (r'(?:interface|type)\s+(\w+)', 'type'),
    ],
    "Go": [
        (r'func\s+(\w+)', 'function'),
        (r'type\s+(\w+)\s+struct', 'struct'),
        (r'type\s+(\w+)\s+interface', 'interface'),
    ],
    "Rust": [
        (r'fn\s+(\w+)', 'function'),
        (r'struct\s+(\w+)', 'struct'),
        (r'impl\s+(?:<[^>]+>\s+)?(\w+)', 'impl'),
    ],
    "Shell": [
        (r'(?:function\s+)?(\w+)\s*\(\)', 'function'),
        (r'(\w+)\s*\(\)\s*\{', 'function'),
    ],
}

def parse_regex_structure(content: str, lang: str) -> list[dict]:
    """用正则解析 JS/TS/Go/Rust/Shell 代码结构。"""
    items = []
    lang_patterns = _REGEX_PATTERNS.get(lang, [])

    for pattern, kind in lang_patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count('\n') + 1
            items.append({
                "type": kind,
                "name": m.group(1) if m.lastindex else m.group(0),
                "line": line_num,
                "col": m.start() - content.rfind('\n', 0, m.start()) - 1,
            })
    return items


def scan_structure(path: Path, lang: str) -> dict:
    """扫描代码结构：文件列表 + 函数/类列表。"""
    config = get_lang_config(lang)
    code_files = scan_files(path, config)
    parser_type = config.get("parser", "regex")

    structure = {}
    for f in code_files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = content.split("\n")

        if lang == "Python" and parser_type == "ast":
            items = parse_python_structure(content, str(f))
        else:
            items = parse_regex_structure(content, lang)

        items_text = ""
        for item in items[:50]:
            if item["type"] == "error":
                items_text += f"  ⚠️ {item['name']}\n"
            else:
                items_text += f"  [L{item['line']}] {item['type']} {item['name']}\n"

        structure[str(f)] = {
            "lines": len(lines),
            "items": items,
            "items_text": items_text,
            "preview": "\n".join(lines) if lines else "",
        }

    return {"total_files": len(code_files), "files": structure}


PROMPT_FILE = SKILL_DIR / "prompts" / "refactor_system.md"


def build_user_content(path: Path, lang: str, structure: dict) -> str:
    """构建 LLM 分析的 user content。"""
    config = get_lang_config(lang)
    files_items = list(structure["files"].items())[:12]

    files_text = ""
    for fpath, info in files_items:
        try:
            rel = fpath[str(path)].lstrip("/") if str(path) in fpath else fpath
        except Exception:
            rel = fpath
        files_text += f"\n### {rel}（{info['lines']} 行）\n"
        if info["items_text"]:
            files_text += f"符号：\n{info['items_text']}"
        files_text += f"\n```\n{info['preview'][:10000]}\n```\n"

    return f"""## 目标
- 路径：{path}
- 语言：{lang}
- 注释：{config['comment']} / 文档：{config['docstring']}
- 文件数：{structure['total_files']}（展示前 {len(files_items)} 个）

{files_text}
"""


def analyze_and_plan(path: Path, lang: str) -> str:
    """调用 LLM 生成重构计划。"""
    structure = scan_structure(path, lang)
    if structure["total_files"] == 0:
        return f"⚠️ 未找到 {lang} 代码文件，请确认目标路径是否正确。"

    user_content = build_user_content(path, lang, structure)

    try:
        sys.path.insert(0, str(LLM_CALL_PY.parent))
        from llm_call import read_prompt, safe_llm_call
    except Exception as e:
        return f"⚠️ LLM 调用失败：{e}"

    try:
        system_prompt = read_prompt(str(PROMPT_FILE))
    except Exception as e:
        return f"⚠️ 读取 prompt 文件失败：{e}"

    ok, result = safe_llm_call(system_prompt, user_content)
    if ok:
        return result
    return f"⚠️ LLM 分析失败：{result}"


def parse_diff_blocks(markdown: str) -> list[dict]:
    """解析 markdown 中的 diff 块，返回 [{filepath, old_content, new_content}]。"""
    blocks = []
    current_file = None
    current_old = []
    current_new = []
    in_diff = False

    for line in markdown.split("\n"):
        if line.startswith("### File:"):
            if current_file and (current_old or current_new):
                blocks.append({
                    "file": current_file,
                    "old": "\n".join(current_old),
                    "new": "\n".join(current_new),
                })
            current_file = line.replace("### File:", "").strip()
            current_old = []
            current_new = []
            in_diff = False
        elif line.strip() == "```diff":
            in_diff = True
        elif line.strip() == "```" and in_diff:
            in_diff = False
        elif in_diff:
            if line.startswith("-") and not line.startswith("---"):
                current_old.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                current_new.append(line[1:])
            elif not line.startswith("+++") and not line.startswith("---") and not line.startswith("@@"):
                current_old.append(line)
                current_new.append(line)

    if current_file and (current_old or current_new):
        blocks.append({
            "file": current_file,
            "old": "\n".join(current_old),
            "new": "\n".join(current_new),
        })

    return blocks


def apply_diff_to_file(filepath: Path, old_content: str, new_content: str) -> tuple[bool, str]:
    """将 old_content 替换为 new_content，精确到行。返回 (success, message)。"""
    try:
        actual = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"读取文件失败: {e}"

    if old_content not in actual:
        return False, "原文不在文件中（可能已被修改）"

    new_file_content = actual.replace(old_content, new_content, 1)

    try:
        filepath.write_text(new_file_content, encoding="utf-8")
    except Exception as e:
        return False, f"写入文件失败: {e}"

    return True, "已应用改动"


def apply_plan(path: Path, plan: str) -> tuple[int, int, list[str]]:
    """应用 diff 计划。返回 (成功数, 失败数, 错误消息列表)。"""
    blocks = parse_diff_blocks(plan)
    success = 0
    failures = 0
    errors = []

    for block in blocks:
        filepath = path / block["file"] if not Path(block["file"]).is_absolute() else Path(block["file"])
        ok, msg = apply_diff_to_file(filepath, block["old"], block["new"])
        if ok:
            success += 1
        else:
            failures += 1
            errors.append(f"{block['file']}: {msg}")

    return success, failures, errors


def create_branch(base_branch: str = "main") -> tuple[bool, str]:
    """创建新分支用于重构。返回 (success, branch_name or error)。"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = f"refactor/{timestamp}"

    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return True, branch_name

    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, f"创建分支失败: {result.stderr}"
    return True, branch_name


def destruction_analysis(path: Path, lang: str) -> dict:
    """破坏性分析：语法检查 + 测试运行。返回 {passed: bool, details: list[str]}。"""
    details = []
    passed = True

    code_files = []
    config = get_lang_config(lang)
    if lang == "Python":
        for ext in config["exts"]:
            code_files.extend(path.rglob(f"*{ext}"))
    else:
        for ext in config["exts"]:
            code_files.extend(path.rglob(f"*{ext}"))

    code_files = [f for f in code_files if f.is_file() and not is_binary(f)]

    if lang == "Python":
        for f in code_files:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(f)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                passed = False
                details.append(f"语法错误: {f.relative_to(path)} - {result.stderr.strip()}")
            else:
                details.append(f"✅ 语法OK: {f.relative_to(path)}")

        pytest_result = subprocess.run(
            ["python3", "-m", "pytest", str(path / "tests"), "-v", "--tb=short"],
            capture_output=True, text=True, cwd=str(path),
        )
        if pytest_result.returncode == 0:
            details.append(f"✅ 测试通过 ({pytest_result.stdout.strip().splitlines()[-1]})")
        elif pytest_result.returncode == 5:
            details.append("⚠️ 无测试文件（跳过）")
        else:
            passed = False
            details.append(f"❌ 测试失败:\n{pytest_result.stdout[-500:]}")
    else:
        details.append(f"⚠️ {lang} 暂不支持自动破坏性分析，请手动验证")

    return {"passed": passed, "details": details}


def auto_mode(target_path: Path, lang: str) -> dict:
    """自动模式：创建分支 → 分析 → 应用 → 破坏性分析。"""
    branch_ok, branch_name = create_branch()
    if not branch_ok:
        return {"success": False, "error": branch_name}

    plan = analyze_and_plan(target_path, lang)

    blocks = parse_diff_blocks(plan)
    if not blocks:
        subprocess.run(["git", "checkout", "HEAD", "--", "."], cwd=str(target_path))
        subprocess.run(["git", "checkout", "-"], cwd=str(target_path))
        return {"success": True, "branch": branch_name, "changes": 0, "analysis": "无改动"}

    success, failures, errors = apply_plan(target_path, plan)

    analysis = destruction_analysis(target_path, lang)

    return {
        "success": failures == 0 and analysis["passed"],
        "branch": branch_name,
        "changes": {"success": success, "failures": failures, "errors": errors},
        "analysis": analysis,
        "plan": plan,
    }


def main():
    parser = argparse.ArgumentParser(description="代码风格重构引擎")
    parser.add_argument("command", choices=["analyze", "apply", "exec", "auto"])
    parser.add_argument("target", nargs="?", default="", help="目标：文件路径/目录/项目名")
    parser.add_argument("--plan", default="", help="（apply 模式）diff 计划文件路径")
    args = parser.parse_args()

    if not args.target and args.command != "apply":
        print("⚠️ 请提供目标路径或项目名", file=sys.stderr)
        print("用法：ms refactor <path|name>", file=sys.stderr)
        sys.exit(1)

    if args.command == "apply":
        if not args.plan:
            print("⚠️ apply 模式需要 --plan 参数指定 diff 计划文件", file=sys.stderr)
            sys.exit(1)
        try:
            plan_content = Path(args.plan).read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️ 读取 diff 计划失败: {e}", file=sys.stderr)
            sys.exit(1)
        target_path = Path.cwd()
        success, failures, errors = apply_plan(target_path, plan_content)
        print(f"\n✅ 成功: {success}, ❌ 失败: {failures}")
        for err in errors:
            print(f"  - {err}")
        sys.exit(0)

    if args.command == "auto":
        try:
            target_path = resolve_target(args.target)
        except FileNotFoundError as e:
            print(f"⚠️ {e}", file=sys.stderr)
            sys.exit(1)

        lang, reason = detect_language(target_path)
        print(f"📂 目标：{target_path}", file=sys.stderr)
        print(f"🔍 语言：{lang}（{reason}）", file=sys.stderr)

        if lang == "Unknown":
            print("⚠️ 无法识别语言，退出", file=sys.stderr)
            sys.exit(1)

        print(f"⏳ 自动化重构中…", file=sys.stderr)

        result = auto_mode(target_path, lang)

        print("\n" + "=" * 60)
        if result["success"]:
            print(f"✅ 重构完成，分支: {result['branch']}")
        else:
            print(f"⚠️ 重构完成但有问题，分支: {result['branch']}")
        print("=" * 60)

        if "changes" in result:
            print(f"改动：成功 {result['changes']['success']}, 失败 {result['changes']['failures']}")
        if result.get("analysis"):
            print("\n🔍 破坏性分析:")
            for detail in result["analysis"]["details"]:
                print(f"  {detail}")
        if result.get("plan"):
            print("\n📋 改动摘要:")
            print(result["plan"][:1000] + "..." if len(result["plan"]) > 1000 else result["plan"])

        print("\n" + "=" * 60)
        print(f"💡 请去代码里看看，确认无误后手动合并分支:")
        print(f"   git checkout main && git merge {result['branch']}")
        print("=" * 60)
        sys.exit(0)

    try:
        target_path = resolve_target(args.target)
    except FileNotFoundError as e:
        print(f"⚠️ {e}", file=sys.stderr)
        sys.exit(1)

    lang, reason = detect_language(target_path)
    print(f"📂 目标：{target_path}", file=sys.stderr)
    print(f"🔍 语言：{lang}（{reason}）", file=sys.stderr)

    if lang == "Unknown":
        print("⚠️ 无法识别语言，退出", file=sys.stderr)
        sys.exit(1)

    print(f"⏳ 分析中…", file=sys.stderr)

    plan = analyze_and_plan(target_path, lang)

    print("\n" + "=" * 60)
    print("📋 代码重构计划")
    print("=" * 60)
    print(plan)
    print("=" * 60)

    if args.command == "analyze":
        print("\n💡 预览完成。使用 exec 模式将进入确认后执行流程。")
        print("   或保存以上内容，配合 apply --plan <file> 手动执行。")
    elif args.command == "exec":
        print("\n✅ 分析完成。确认后执行全部改动。")
        print("💡 回复「确认」执行全部改动，或指定具体文件只改部分。")


if __name__ == "__main__":
    sys.exit(main())
