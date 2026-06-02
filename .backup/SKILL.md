---
name: my-refactor
description: Use when user says "my-refactor <path|name|description>" or "ms sk refactor <path|name|description>"
---

# my-refactor

代码风格重构 skill，在不破坏现有功能的前提下，优化代码风格并补充规范注释。

## 触发规则

| 用户输入 | 触发动作 |
| ----------------------------------------- | -------------------------------------------------------------------------------- |
| `my-refactor <目标>` | `python3 ~/my-skills/my-refactor/scripts/engine_refactor.py run "<目标>"` |
| `ms sk refactor <目标>` | 同上 |

## 目标支持

- **文件路径**：`./src/utils.py`
- **目录路径**：`./src/`
- **项目名**：在 `~/my-projects/` 下查找同名目录

## 执行流程

1. 扫描目标代码结构（语言、文件列表、函数列表）
2. LLM 分析可优化点（风格问题 + 缺少注释的位置）
3. 生成 markdown 改动清单（含 diff）
4. 人确认后，agent 执行实际修改
5. 汇报完成状态

## 约束规则

- **不改逻辑**，只改风格和注释
- 改动必须提供 diff，人确认后才执行
- 注释使用目标语言一致的注释风格（# // """ 等）
