# AgentOS

一个支持 Tool Calling、Memory、Evaluation 和 Observability 的大模型 Agent 平台。

## 项目状态

早期开发阶段：仓库正在搭建工程基座，尚未发布可用版本。每日迭代计划与进度见 [TODO.md](TODO.md)，变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 规划能力

### Agent 核心

- **Agent Runtime**：Agent、Message 与运行循环
- **Planning**：任务分解与执行计划
- **Tool Calling**：工具注册、参数校验、调用与结果回填
- **Memory**：短期会话记忆与长期记忆存储
- **Multi-Agent**：多 Agent 协作与消息路由

### 平台能力

- Agent 管理、Tool 管理
- 权限系统与配额控制
- 统一 API 接口与数据模型

### 工程能力

- Logging 与 Observability
- Evaluation 评测体系
- 性能优化与 Docker 部署

## 快速开始

项目骨架搭建完成后在此补充安装与运行方式。

## 开发约定

- 每次改动保持项目可运行，新增能力附带必要测试
- 提交信息使用 [Conventional Commits](https://www.conventionalcommits.org/)，例如 `feat: add agent memory retrieval module`
- 待办事项记录在 TODO.md，变更记录记录在 CHANGELOG.md

## 许可证

[MIT](LICENSE)