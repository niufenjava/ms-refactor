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

ms refactor 是 Python 代码重构工具。

**交互流程：**
1. 列出目标下所有 .py 文件（带序号和行数）
2. 你选择要分析的文件
3. LLM 分析代码，输出重构建议（diff 格式）
4. 你确认：y=应用，n=跳过，s=跳过该文件
5. 继续选下一个文件（输入 q 退出）

**支持语言：** Python only（.py 文件）

## 示例

```
ms refactor ~/my-projects/ms-gh
```
