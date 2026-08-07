# AI 知识库 · 编码规范 v0.2

## 要做什么
- Python 用 black 格式化，以 PEP 8 为准
- TypeScript strict mode（项目计划引入TypeScript）
- 所有公开函数必须有 Google 风格 docstring

## 不做什么
- 不用任何魔法字符串（所有字符串字面量都必须定义为常量）
- 不允许 TODO 提交到 main（TODO 必须在提交前完成）

## 边界 & 验收
- 单测覆盖率 ≥ 80%（行覆盖率）

## 怎么验证
- CI 上跑 lint + 单测
- Python: flake8 + mypy + pytest
- TypeScript: ESLint + Prettier + Jest

## 配置文件
- Python: pyproject.toml
- TypeScript: tsconfig.json
- ESLint: .eslintrc.js
- Prettier: .prettierrc
- Jest: jest.config.js

## 版本要求
- Python 3.12+
- Node.js 18+
