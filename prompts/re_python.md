# Python Coding Standards

仅对 Python 文件（*.py）生效。

## 核心原则

代码首先服务于阅读，其次才是编写。

优先选择：

- 可读性
- 可维护性
- 简单实现
- 清晰命名

避免：

- 炫技写法
- 过度抽象
- 复杂链式调用
- 难理解的一行代码

---

## 命名规范

### 变量名

使用完整英文单词表达含义。

Good:

user_name = "Tom"
total_count = 10
skill_directory = Path(...)

Bad:

n = "Tom"
cnt = 10
sd = Path(...)

### 函数名

函数名必须体现动作。

Good:

load_skills()
save_config()
generate_summary()

Bad:

data()
handle()
process()

### 类名

使用名词。

SkillManager
ConfigLoader
GitRepository

---

## 函数设计

单个函数尽量只做一件事。

Good:

def load_config():
...

def validate_config():
...

def save_config():
...

Bad:

def handle_everything():
...

函数长度建议：

- 优秀：20行以内
- 可接受：50行以内
- 超过80行应考虑拆分

---

## 注释规范

注释写给 12 岁小朋友阅读。

要求：

- 简短
- 直接
- 解释目的
- 不解释废话

Good:

# 读取配置文件

config = load_config()

# 找出所有 Skill

skills = find_skills()

Good:

# 如果目录不存在，先创建

if not output_dir.exists():
output_dir.mkdir()

Bad:

# 定义一个变量

name = "Tom"

Bad:

# 调用 load_config 函数加载配置

config = load_config()

---

## 类型标注

新增 Python 代码必须包含类型标注。

def load_skills(path: Path) -> list[str]:
...

def build_summary(items: list[str]) -> str:
...

---

## 日志规范

使用 logging。

避免：

print("error")

优先：

logger.info("Loading skills...")
logger.warning("Skill not found")
logger.error("Failed to load config")

---

## 文件结构

推荐顺序：

"""
模块说明
"""

# 标准库

import json
from pathlib import Path

# 第三方库

import requests

# 本地模块

from utils import load_config

class SkillManager:
...

def main():
...

if __name__ == "__main__":
main()

---

## 代码风格

优先写成：

if not skills:
return

而不是：

if len(skills) == 0:
return

优先写成：

for skill in skills:
...

而不是：

for i in range(len(skills)):
...

---

## AI 输出要求

生成 Python 代码时：

1. 优先考虑可读性。
2. 命名必须自解释。
3. 必须包含必要类型标注。
4. 添加简洁中文注释。
5. 注释以 12 岁小朋友能理解为标准。
6. 优先简单方案，不追求高级技巧。
7. 单个函数尽量只做一件事。
8. 代码应达到“半年后自己回来仍能快速看懂”的标准。

## 最终原则

Python 代码的评判标准不是“短”，而是“半年后还能一眼看懂”。

当「优雅」与「可读性」冲突时，永远选择可读性。