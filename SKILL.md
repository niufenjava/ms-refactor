---
name: my-refactor
description: Use when user says "ms refactor" | "ms refactor <path>"
---

# ms refactor

## 触发规则

| 用户输入 | 触发动作 |
| -------------------- | ------------------------------------------------ |
| `ms refactor` | 返回技能列表 |
| `ms refactor <目标>` | `python3 ~/my-skills/my-refactor/scripts/engine_refactor.py analyze "<目标>"` |
| `ms refactor <目标> exec` | `python3 ~/my-skills/my-refactor/scripts/engine_refactor.py exec "<目标>"` |
| `ms refactor <目标> auto` | 新建分支 → 自动重构 → 破坏性分析 → 问你怎么样 |

---

## 技能列表
ms refactor 技能列表:
  ms refactor <目标>          | 分析代码，生成 diff 清单（不执行）
  ms refactor <目标> exec    | 分析 + 确认后执行改动
  ms refactor <目标> auto    | 自动重构 + 破坏性分析，询问你确认后合并

## 支持语言
Python、JavaScript/JSX、TypeScript/TSX、Go、Rust、Shell

## auto 模式流程
1. 新建分支 `refactor/YYYYMMDD-HHMMSS`
2. 扫描代码结构
3. LLM 生成改动计划
4. **自动应用所有改动**（不逐个确认）
5. 破坏性分析（语法检查 + 运行测试）
6. 展示结果，请你去代码里看看
7. 你确认没问题后，手动合并到原分支
