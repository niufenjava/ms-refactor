---
name: my-refactor
description: Use when user says "ms refactor" | "ms refactor <path>"
---

# ms refactor

## 触发规则

| 用户输入 | 触发动作 |
| -------------------- | ------------------------------------------------ |
| `ms refactor <目标>` | `python3 ~/my-skills/my-refactor/scripts/engine_refactor.py "<目标>"` |

---

## 技能说明

ms refactor 是 Python 代码自动重构工具。

**自动流程：**
1. 列出 .py 文件，支持多选（1,3,5 或 1-3 或 all）
2. 新建分支 refactor/<timestamp>
3. 自动分析并应用选定文件的重构
4. 破坏性分析（语法 + 测试，最多 5 轮重试）
5. 输出变更摘要，用户自行合并

**支持语言：** Python only（.py 文件）

## 示例

```
ms refactor ~/my-projects/ms-gh
```
