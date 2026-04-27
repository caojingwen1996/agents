# 交易纪律审计与规则沉淀 Agent

这个目录实现的是一个 **LLM 驱动的交易纪律复盘 agent**。

核心判断、意图识别、交易前审计、交易后复盘、候选规则生成、以及 `obsidian_kb` 检索，都应由 LLM 根据 `agent.md` 和 `prompts/` 中的提示词完成。

脚本层只做机械工作：归档 Markdown、生成路径、维护目录结构。

## 文件结构

```text
AGENTS.md   给 Codex 自动读取
README.md                        项目说明和使用方法
templates/before.md              交易前置审计报告模板
templates/after.md               交易后执行复盘报告模板
templates/candidate_rule.md      候选个人规则模板
prompts/system.md                Agent 总系统提示词
prompts/pre_trade.md             交易前审计提示词
prompts/post_trade.md            交易后复盘提示词
prompts/rule_deposit.md          个人规则沉淀提示词
rules/                           当前个人规则、候选规则、废弃规则、规则变更记录
refs/                            llmwiki 查询引用记录
trading_discipline_agent/        归档、命名、路径处理等辅助代码
scripts/archive.py               命令行入口，把生成的 Markdown 写入推荐目录
tests/                           测试归档辅助代码
```

## 能力分工

LLM 负责：

1. 意图识别
2. 交易前追问
3. 交易前审计
4. 交易后复盘
5. 复盘分类
6. 规则冲突解释
7. 候选个人规则提炼
8. 判断何时需要调用 `obsidian_kb` skill
9. 调用 `obsidian_kb` skill 查询 llmwiki 外部参考规则

脚本负责：

1. 保存 LLM 生成的 Markdown
2. 生成归档路径
3. 创建归档目录

脚本不负责：

1. 判断用户意图
2. 审计交易计划
3. 判断交易是否违纪
4. 生成候选个人规则
5. 调用或模拟 `obsidian_kb`

## 如何启动

Codex 会在开始工作前读取 AGENTS.md，并且会从当前工作目录向上发现项目配置和 AGENTS.md。

## 测试

```powershell
python -m unittest discover -s tests
```
