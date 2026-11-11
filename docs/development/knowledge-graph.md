# 知识图谱开发说明

本页说明 QB 全学科知识图谱升级的数据模型、导入流程与 AI 接入方式。当前第一批外部数据来自 cn-math-taxonomy 的数学部分。

## 数据模型

### 知识点

`knowledge_points` 在原树形结构上新增通用字段：

| 字段 | 说明 |
|------|------|
| `description` | 知识点说明 |
| `node_type` | `domain` / `chapter` / `conceptual` / `procedural` / `application` / `modeling` / `reasoning` |
| `grade` | 年级或学习阶段，字符串 |
| `chapter` | 教材章节 |
| `learning_requirement` | 学习要求 |
| `attributes` | 学科扩展属性 JSON |
| `source` | 数据来源 |

`domain`、`chapter` 是**分类节点**，与真实知识点共用一张表，通过 `parent_id` 组成：

```
学科 Subject
  └── domain
        └── chapter
              └── 知识点
```

分类节点不参与题目关联、向量索引和 AI 打标。

### 关系

- `knowledge_relation_types`：可配置的关系类型。内置 `prerequisite`、`related`、`derived_from`、`applied_to`、`uses`、`contrasts`、`causes`、`precedes`。
- `knowledge_relations`：`source` 是关系起点，`target` 是终点。对 `prerequisite` 来说，`source` 是先修，`target` 是后继。
  - `status`：`verified` / `external` / `ai_inferred`
  - `attributes.strength`：外部先修边的 `hard` / `soft`
  - 唯一约束保证重复导入幂等；先修边写入时做环检测。

### 外部来源

`knowledge_external_refs` 记录 `(source, entity_type, external_id)` 与 QB 实体的映射，用于重复导入和追溯。

## 外部导入

### 数据放置

cn-math-taxonomy 数据采用 CC BY-NC 4.0，**不提交到 QB 仓库**。本地放在 gitignored 的 `data/imports/`，或导入时上传 zip。

### 支持的 zip

zip 内需要包含：

- `topics.json`
- `dependencies.json`

可选包含 `id-aliases.json`、`cn-curriculum-standards.json`（当前版本不导入别名与课标表）。

### 第一批数学范围

从 `topics.json` 中筛选 `subject` 缺省或为 `math` 的节点，并生成：

- 数学知识点：870
- domain 分类：4
- chapter 分类：308
- 先修边：1459

不导入 `questions.json`；`diagnostic_question` 只保存在 `attributes` 中，不创建题目。

### 流程

1. `POST /api/v1/knowledge-points/import-external/preview`：上传 zip + `subject_id`，返回动作统计、逐条动作、冲突与文件 SHA-256。
2. `POST /api/v1/knowledge-points/import-external`：重新上传同一 zip，并携带预览返回的 `checksum`；服务端校验后执行导入。
3. 第二次导入相同文件不会产生重复节点或关系。

### 匹配规则

- 优先按 `(source, entity_type, external_id)` 匹配；
- 分类节点按 `(subject_id, parent_id, name, node_type)` 匹配；
- 同一父级下存在多个同名节点时标记冲突，不自动覆盖；
- 默认只新增或关联，不覆盖已有非空字段；勾选 `update_existing` 后才更新描述等字段。

## AI 接入

- `search_knowledge_points` 返回知识点 ID、层级、描述和一跳关系。
- `get_knowledge_point_relations` 查询先修 / 后继 / 关联关系。
- 智能导入的知识点匹配会把候选节点的描述与关系作为上下文传给 rerank；提示词明确要求只能从候选知识点中选择。
- 默认只把 `hard` 先修边视为强依赖，`soft` 仅作参考；`external` 状态表示外部数据可能未经审核。
- 向量或图谱查询失败时，回退原有向量召回 + rerank 流程。

## 迁移

新增迁移 `c1d2e3f4a5b6_knowledge_graph.py`：

- 只增加列、表和索引；
- 不修改或删除已有知识点、题目数据；
- 种子写入内置关系类型；
- SQLite / MySQL 双兼容。

```bash
cd backend
uv run alembic upgrade head
```

## 测试

```bash
cd backend && uv run pytest
cd frontend && pnpm test
```

重点覆盖：

- 模型、迁移、关系级联与环检测；
- 关系权限；
- cn 数学导入的过滤、预览、幂等与冲突；
- AI 图谱上下文与降级。
