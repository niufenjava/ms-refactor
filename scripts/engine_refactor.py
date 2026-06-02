"""
ms-refactor 重构引擎

分析 Python 代码并生成风格重构建议。
流程：选择文件 -> 分析 -> 保存建议 -> 用户决定
"""

import argparse
import ast
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".backup", ".git", ".idea", ".vscode"}

LLM_CALL_PY = Path.home() / "my-projects" / "claw-scripts" / "llm" / "llm_call.py"
MY_PROJECTS = Path.home() / "my-projects"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "re_python.md"
REFACTOR_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "refactor_prompt.md"


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

    fuzzy_dir = search_projects(raw)
    if fuzzy_dir:
        return fuzzy_dir

    raise FileNotFoundError(f"目标不存在或无法定位：{raw}")


def search_projects(keyword: str) -> Optional[Path]:
    """在 ~/my-projects/ 下模糊搜索匹配目录。"""
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
    try:
        with open(path, "rb") as f:
            f.read(1024)
        return False
    except Exception:
        return True


def extract_python_symbols(content: str, filepath: str) -> list[dict]:
    """用 ast 解析 Python 代码结构。"""
    items = []
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError as e:
        return [{"type": "error", "name": f"ParseError: {e}", "line": 0}]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            items.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno,
            })
    return items


def find_python_files(target: Path) -> list[Path]:
    """找出目标目录下所有的 .py 文件。"""
    if target.is_file():
        return [target] if target.suffix == ".py" else []

    files = []
    for item in target.rglob("*.py"):
        if any(skip in item.parts for skip in SKIP_DIRS):
            continue
        if is_binary(item):
            continue
        files.append(item)

    return sorted(files)


def list_and_select_files(target: Path) -> list[Path]:
    """列出 .py 文件，返回用户选择的多选列表。"""
    files = find_python_files(target)
    if not files:
        logger.warning("未找到 Python 文件")
        return []

    logger.info("📋 找到 %d 个 Python 文件（支持多选，如 1,3,5 或 1-3 或 all）：\n", len(files))
    for idx, f in enumerate(files, 1):
        try:
            lines = len(f.read_text(errors="ignore").splitlines())
        except Exception:
            lines = 0
        rel_path = f.relative_to(target) if target.is_dir() else f.name
        logger.info("  [%d] %s (%d 行)", idx, rel_path, lines)

    while True:
        choice = input("\n选择文件: ").strip()
        indices = parse_selection(choice, len(files))
        if choice.lower() == "q":
            return []
        if indices:
            return [files[i] for i in indices]
        logger.warning("无效输入，请输入如 1,3,5 或 1-3 或 all 或 q")


def parse_selection(selection: str, file_count: int) -> list[int]:
    """解析用户输入的选择，返回文件索引列表（0-based）。"""
    selection = selection.strip().lower()
    if selection == "q":
        return []
    if selection == "all":
        return list(range(file_count))

    indices = []
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            try:
                start_idx = int(start.strip()) - 1
                end_idx = int(end.strip())
                indices.extend(range(start_idx, end_idx))
            except ValueError:
                pass
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < file_count:
                    indices.append(idx)
            except ValueError:
                pass

    return sorted(set(indices))


def compose_llm_prompt(target: Path, file_path: Path) -> str:
    """构建发送给 LLM 的分析 prompt。"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"读取文件失败: {e}"

    symbols = extract_python_symbols(content, str(file_path))

    symbols_text = ""
    for s in symbols[:50]:
        if s["type"] == "error":
            symbols_text += f"  ⚠️ {s['name']}\n"
        else:
            symbols_text += f"  [L{s['line']}] {s['type']} {s['name']}\n"

    rel_path = file_path.relative_to(target) if target.is_dir() else file_path.name

    return f"""## 目标文件
{rel_path}

## 代码结构
{symbols_text if symbols_text else "（无）"}

## 代码内容
```
{content[:10000]}
```
"""


def analyze_and_plan(target: Path, file_path: Path) -> str:
    """调用 LLM 生成单个文件的重构建议（完整新代码）。"""
    user_content = compose_llm_prompt(target, file_path)

    try:
        sys.path.insert(0, str(LLM_CALL_PY.parent))
        from llm_call import read_prompt, safe_llm_call
    except Exception as e:
        return f"LLM 调用失败: {e}"

    try:
        system_prompt = read_prompt(str(REFACTOR_PROMPT_FILE))
    except Exception as e:
        return f"读取 prompt 文件失败: {e}"

    ok, result = safe_llm_call(system_prompt, user_content)
    if ok and result:
        return extract_code_from_markdown(result)
    return f"LLM 分析失败: {result}"


def extract_code_from_markdown(content: str) -> str:
    """从 markdown 中提取 Python 代码块。"""
    import re
    match = re.search(r"```python\s*(.*?)\s*```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content


def save_refactored_code(original_path: Path, new_content: str) -> Path:
    """保存重构后的代码到 .refactored.py 文件。"""
    refactored_path = original_path.parent / f"{original_path.stem}.refactored.py"
    refactored_path.write_text(new_content, encoding="utf-8")
    return refactored_path


def main():
    parser = argparse.ArgumentParser(description="Python 代码重构引擎")
    parser.add_argument("target", nargs="?", default="", help="目标：文件路径/目录/项目名")
    args = parser.parse_args()

    if not args.target:
        logger.error("请提供目标路径或项目名")
        logger.info("用法: python3 engine_refactor.py <目标>")
        sys.exit(1)

    try:
        target_path = resolve_target(args.target)
    except FileNotFoundError as e:
        logger.error(e)
        sys.exit(1)

    logger.info("📂 目标: %s", target_path)

    selected_files = list_and_select_files(target_path)
    if not selected_files:
        logger.info("已退出")
        sys.exit(0)

    results = []
    for file_path in selected_files:
        rel_path = file_path.relative_to(target_path) if target_path.is_dir() else file_path.name
        logger.info("\n📄 分析: %s", rel_path)

        new_content = analyze_and_plan(target_path, file_path)

        if new_content.startswith("LLM") or new_content.startswith("读取") or new_content.startswith("语法"):
            logger.error("分析失败: %s", new_content)
            continue

        if len(new_content) < 50:
            logger.error("返回内容过短，可能是错误")
            continue

        refactored_path = save_refactored_code(file_path, new_content)
        logger.info("✅ 已保存到: %s", refactored_path)

        results.append({
            "original": file_path,
            "refactored": refactored_path,
            "rel_path": rel_path,
        })

    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 重构完成")
    logger.info("=" * 60)

    if results:
        logger.info("改动文件:")
        for r in results:
            logger.info("  %s -> %s", r["rel_path"], r["refactored"].name)

    logger.info("")
    logger.info("💡 手动合并命令:")
    for r in results:
        logger.info("  cp %s %s", r["refactored"].name, r["rel_path"])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
