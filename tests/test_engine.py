#!/usr/bin/env python3
"""engine_refactor 测试用例"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from engine_refactor import (
    detect_language,
    parse_diff_blocks,
    apply_diff_to_file,
    parse_python_structure,
    parse_regex_structure,
    LANG_CONFIG,
)


class TestSearchProjects(unittest.TestCase):
    def test_fuzzy_search_finds_match(self):
        from engine_refactor import search_projects
        result = search_projects("trino")
        # 如果 ~/my-projects/ 下有含 "trino" 的目录则返回，否则 None
        if result:
            self.assertIn("trino", result.name.lower())

    def test_fuzzy_search_no_match(self):
        from engine_refactor import search_projects
        result = search_projects("nonexistent_xyz_12345")
        self.assertIsNone(result)


class TestDetectLanguage(unittest.TestCase):
    def test_python_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"def foo(): pass")
            f.flush()
            lang, reason = detect_language(Path(f.name))
        self.assertEqual(lang, "Python")
        Path(f.name).unlink()

    def test_js_file(self):
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            f.write(b"function foo() {}")
            f.flush()
            lang, reason = detect_language(Path(f.name))
        self.assertEqual(lang, "JavaScript")
        Path(f.name).unlink()

    def test_go_file(self):
        with tempfile.NamedTemporaryFile(suffix=".go", delete=False) as f:
            f.write(b"package main\nfunc main() {}")
            f.flush()
            lang, reason = detect_language(Path(f.name))
        self.assertEqual(lang, "Go")
        Path(f.name).unlink()

    def test_binary_file(self):
        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"\x7fELF")
            f.flush()
            lang, reason = detect_language(Path(f.name))
        self.assertEqual(lang, "Unknown")
        Path(f.name).unlink()


class TestParsePythonStructure(unittest.TestCase):
    def test_function_and_class(self):
        code = '''
class Foo:
    def bar(self): pass

def baz(): pass
'''
        items = parse_python_structure(code, "test.py")
        names = {item["name"] for item in items}
        self.assertIn("Foo", names)
        self.assertIn("bar", names)
        self.assertIn("baz", names)


class TestParseRegexStructure(unittest.TestCase):
    def test_js_function(self):
        code = '''
function foo() {}
const bar = 1;
class Baz {}
'''
        items = parse_regex_structure(code, "JavaScript")
        names = {item["name"] for item in items}
        self.assertIn("foo", names)
        self.assertIn("bar", names)
        self.assertIn("Baz", names)

    def test_go_function(self):
        code = '''
func main() {}
type Foo struct {}
'''
        items = parse_regex_structure(code, "Go")
        names = {item["name"] for item in items}
        self.assertIn("main", names)
        self.assertIn("Foo", names)


class TestParseDiffBlocks(unittest.TestCase):
    def test_basic_diff(self):
        markdown = '''
### File: foo.py
**问题**：
- 缺少注释

**改动**：
```diff
- def foo():
+ # Foo 函数入口
+ def foo():
```
'''
        blocks = parse_diff_blocks(markdown)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["file"], "foo.py")
        self.assertIn("def foo():", blocks[0]["old"])
        self.assertIn("# Foo 函数入口", blocks[0]["new"])

    def test_multiple_files(self):
        markdown = '''
### File: a.py
```diff
- a
+ b
```

### File: b.py
```diff
- c
+ d
```
'''
        blocks = parse_diff_blocks(markdown)
        self.assertEqual(len(blocks), 2)


class TestApplyDiff(unittest.TestCase):
    def test_simple_replace(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def foo():\n    pass\n")
            f.flush()
            filepath = Path(f.name)

        ok, msg = apply_diff_to_file(filepath, "def foo():", "# Foo\ndef foo():")
        self.assertTrue(ok)

        content = filepath.read_text()
        self.assertIn("# Foo", content)
        self.assertIn("def foo():", content)

        filepath.unlink()

    def test_old_content_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def foo():\n    pass\n")
            f.flush()
            filepath = Path(f.name)

        ok, msg = apply_diff_to_file(filepath, "not exist", "# Foo")
        self.assertFalse(ok)
        self.assertIn("原文不在文件中", msg)

        filepath.unlink()


class TestLangConfig(unittest.TestCase):
    def test_all_langs_have_required_fields(self):
        required = {"exts", "comment", "docstring", "index_cmd", "parser"}
        for lang, cfg in LANG_CONFIG.items():
            self.assertTrue(required.issubset(cfg.keys()), f"{lang} 缺少字段")


if __name__ == "__main__":
    unittest.main()
