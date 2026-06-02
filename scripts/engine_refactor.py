"""
ms-refactor 重构引擎

分析 Python 代码并生成风格重构建议。
自动流程：选择文件 -> 新建分支 -> 分析应用 -> 重试 -> 报告
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


def create_refactor_branch() -> tuple[bool, str]:
    """创建 refactor/<timestamp> 分支。返回 (success, branch_name)。"""
    from datetime import datetime
    branch_name = f"refactor/{datetime.now().strftime('%Y%m%d%H%M%S')}"

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
    try:
        with open(path, "rb") as f:
            f.read(1024)
        return False
    except Exception:
        return True


def extract_python_symbols(content: str, filepath: str) -> list[dict]:
    """用 ast 解析 Python 代码结构，返回函数和类列表。"""
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


def apply_code_change(filepath: Path, old_content: str, new_content: str) -> tuple[bool, str]:
    """将 old_content 替换为 new_content，使用行匹配。返回 (success, message)。"""
    try:
        actual = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"读取文件失败: {e}"

    actual_lines = actual.splitlines(keepends=True)
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    if len(old_lines) == 0 or len(actual_lines) == 0:
        return False, "空内容无法替换"

    if len(old_lines) == 1:
        first_line = old_lines[0]
        for i, line in enumerate(actual_lines):
            if line == first_line:
                result_lines = actual_lines[:i] + new_lines + actual_lines[i+1:]
                new_file_content = "".join(result_lines)
                try:
                    filepath.write_text(new_file_content, encoding="utf-8")
                except Exception as e:
                    return False, f"写入文件失败: {e}"
                return True, f"已应用改动"
        return False, "未找到匹配行"

    anchor = old_lines[0]
    for start_pos in range(len(actual_lines)):
        if actual_lines[start_pos].rstrip() == anchor.rstrip():
            end_pos = start_pos + len(old_lines)
            if end_pos <= len(actual_lines):
                chunk = actual_lines[start_pos:end_pos]
                from difflib import SequenceMatcher
                s = SequenceMatcher(None, old_lines, chunk)
                ratio = s.ratio()
                if ratio >= 0.5:
                    result_lines = actual_lines[:start_pos] + new_lines + actual_lines[end_pos:]
                    new_file_content = "".join(result_lines)
                    try:
                        filepath.write_text(new_file_content, encoding="utf-8")
                    except Exception as e:
                        return False, f"写入文件失败: {e}"
                    return True, f"已应用改动（相似度: {ratio:.2%}）"

    return False, "未找到匹配内容"


def execute_plan(target: Path, plan: str) -> tuple[int, int, list[str]]:
    """应用 diff 计划。返回 (成功数, 失败数, 错误消息列表)。"""
    blocks = parse_diff_blocks(plan)
    success = 0
    failures = 0
    errors = []

    for block in blocks:
        filepath = target / block["file"] if not Path(block["file"]).is_absolute() else Path(block["file"])
        ok, msg = apply_code_change(filepath, block["old"], block["new"])
        if ok:
            success += 1
        else:
            failures += 1
            errors.append(f"{block['file']}: {msg}")

    return success, failures, errors


def auto_refactor(target: Path, selected_files: list[Path]) -> dict:
    """自动分析并应用所有选定文件的重构。"""
    results = {
        "files_processed": 0,
        "changes_applied": 0,
        "plans": {},
        "errors": [],
    }

    for file_path in selected_files:
        plan = analyze_and_plan(target, file_path)
        if plan.startswith("LLM") or plan.startswith("读取"):
            results["errors"].append(f"{file_path}: {plan}")
            continue

        results["plans"][str(file_path)] = plan
        success, failures, errors = execute_plan(target, plan)
        results["files_processed"] += 1
        results["changes_applied"] += success
        results["errors"].extend(errors)

    return results


def llm_fix_and_regenerate(target: Path, selected_files: list[Path], error_summary: str) -> dict:
    """根据错误信息让 LLM 修复并重新生成 diff。"""
    plans = {}

    for file_path in selected_files:
        rel_path = file_path.relative_to(target) if target.is_dir() else file_path.name

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            continue

        prompt = f"""文件: {rel_path}
内容:
```
{content[:8000]}
```

上次重构有错误：
{error_summary}

请根据错误信息修复这个文件，生成新的重构 diff。
输出格式：
### File: <相对路径>

```diff
- 原代码
+ 改动后代码
```
"""

        try:
            sys.path.insert(0, str(LLM_CALL_PY.parent))
            from llm_call import read_prompt, safe_llm_call
        except Exception:
            continue

        try:
            system_prompt = read_prompt(str(PROMPT_FILE))
        except Exception:
            continue

        ok, result = safe_llm_call(system_prompt, prompt)
        if ok:
            plans[str(file_path)] = result

    return plans


MAX_RETRIES = 5

def auto_refactor_with_retry(target: Path, selected_files: list[Path]) -> dict:
    """自动重构 + 5 轮重试。返回最终结果。"""
    all_plans = {}

    for round_num in range(1, MAX_RETRIES + 1):
        logger.info(f"⏳ 第 {round_num} 轮: 分析中...")

        if round_num == 1:
            results = auto_refactor(target, selected_files)
            all_plans.update(results["plans"])
        else:
            check = run_destruction_check(target)
            if check["passed"]:
                logger.info(f"✅ 第 {round_num} 轮: 全部通过")
                break

            error_summary = "\n".join(check["details"])
            logger.warning(f"❌ 第 {round_num} 轮: 失败，LLM 修复中...")

            new_plans = llm_fix_and_regenerate(target, selected_files, error_summary)

            for file_path, plan in new_plans.items():
                fp = Path(file_path)
                success, failures, errors = execute_plan(target, plan)
                all_plans[file_path] = plan

        check = run_destruction_check(target)
        if check["passed"]:
            logger.info(f"✅ 第 {round_num} 轮: 全部通过")
            return {
                "success": True,
                "rounds": round_num,
                "plans": all_plans,
                "results": results,
            }

    logger.error(f"⚠️ {MAX_RETRIES} 轮重试后仍失败，分支已创建，请手动检查")
    return {
        "success": False,
        "rounds": MAX_RETRIES,
        "plans": all_plans,
        "results": results,
    }


def print_summary(results: dict, branch_name: str):
    """输出变更摘要。"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 变更摘要")
    logger.info("=" * 60)
    logger.info(f"🌿 分支: {branch_name}")
    logger.info(f"处理文件: {results.get('files_processed', 0)}")
    logger.info(f"应用改动: {results.get('changes_applied', 0)}")
    if results.get('errors'):
        logger.info(f"错误数: {len(results['errors'])}")
    logger.info("=" * 60)

    if results.get('plans'):
        logger.info("📋 改动文件:")
        for file_path, plan in results["plans"].items():
            fp = Path(file_path)
            rel = fp.name
            blocks = parse_diff_blocks(plan)
            logger.info(f"  {rel} | {len(blocks)} 处改动")

    logger.info("")
    logger.info("💡 合并命令:")
    logger.info(f"  git checkout main && git merge {branch_name}")
    logger.info("=" * 60)


def find_python_files(target: Path) -> list[Path]:
    """找出目标目录下所有的 .py 文件，排除缓存目录。"""
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
    """解析用户输入的选择，返回文件索引列表（0-based）。

    支持格式：
    - "1,3,5" -> [0, 2, 4]
    - "1-3" -> [0, 1, 2]
    - "all" -> [0, 1, ..., file_count-1]
    - "q" -> []
    """
    selection = selection.strip().lower()
    if selection == "q":
        return []
    if selection == "all":
        return list(range(file_count))

    indices = []
    # 逗号分隔
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        # 范围 (如 1-3)
        if "-" in part:
            start, end = part.split("-", 1)
            try:
                start_idx = int(start.strip()) - 1
                end_idx = int(end.strip())
                indices.extend(range(start_idx, end_idx))
            except ValueError:
                pass
        else:
            # 单个数字
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
    """调用 LLM 生成单个文件的重构计划。"""
    user_content = compose_llm_prompt(target, file_path)

    try:
        sys.path.insert(0, str(LLM_CALL_PY.parent))
        from llm_call import read_prompt, safe_llm_call
    except Exception as e:
        return f"LLM 调用失败: {e}"

    try:
        system_prompt = read_prompt(str(PROMPT_FILE))
    except Exception as e:
        return f"读取 prompt 文件失败: {e}"

    ok, result = safe_llm_call(system_prompt, user_content)
    if ok:
        return result
    return f"LLM 分析失败: {result}"


def ask_llm_generate_tests(target: Path) -> bool:
    """询问 LLM 是否需要生成测试。返回 True 表示需要生成。"""
    try:
        sys.path.insert(0, str(LLM_CALL_PY.parent))
        from llm_call import read_prompt, safe_llm_call
    except Exception:
        return False

    files = find_python_files(target)
    files_info = "\n".join([f"- {f.relative_to(target)}" for f in files[:10]])

    prompt = f"""代码目录: {target}
Python 文件:
{files_info}

请判断是否需要为这些代码生成单元测试。
标准：
- 核心业务逻辑（类、复杂函数）需要测试
- 简单工具脚本可跳过
- 函数签名变更必须验证

回答格式：只回答 "yes" 或 "no"，不要解释。"""

    try:
        system_prompt = read_prompt(str(PROMPT_FILE))
    except Exception:
        return False

    ok, result = safe_llm_call(system_prompt, prompt)
    return "yes" in result.lower() if ok else False


def run_destruction_check(target: Path) -> dict:
    """语法检查 + 测试运行。返回 {passed: bool, details: list[str]}。"""
    details = []
    passed = True

    files = find_python_files(target)
    for f in files:
        result = subprocess.run(
            ["python3", "-m", "py_compile", str(f)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            passed = False
            details.append(f"语法错误: {f.relative_to(target)} - {result.stderr.strip()}")
        else:
            details.append(f"✅ 语法OK: {f.relative_to(target)}")

    test_dir = target / "tests"
    if test_dir.exists():
        pytest_result = subprocess.run(
            ["python3", "-m", "pytest", str(test_dir), "-v", "--tb=short"],
            capture_output=True, text=True, cwd=str(target),
        )
        if pytest_result.returncode == 0:
            details.append(f"✅ 测试通过")
        elif pytest_result.returncode == 5:
            details.append("⚠️ 无测试文件")
        else:
            passed = False
            details.append(f"❌ 测试失败")

    return {"passed": passed, "details": details}


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

    branch_ok, branch_name = create_refactor_branch()
    if not branch_ok:
        logger.error("创建分支失败: %s", branch_name)
        sys.exit(1)

    logger.info("🌿 分支: %s", branch_name)

    result = auto_refactor_with_retry(target_path, selected_files)

    print_summary(result, branch_name)

    if result["success"]:
        logger.info("✅ 全部通过")
    else:
        logger.warning("⚠️ 有失败，请检查后合并")


if __name__ == "__main__":
    main()
