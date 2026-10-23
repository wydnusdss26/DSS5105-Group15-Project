# SweaterCo — Track 1 经理助手

本地 Streamlit 应用：风险订单、产量异常、可行性估算、晨报、带确认的备注/草稿/提醒，以及独立后台监控。

**当前问答与晨报概述已适配 OpenAI GPT-6.1 Sol，并已获明确授权开启联网。** 密钥认证与模型可见性检查通过；真实生成检查返回 `credit_balance_exhausted`，需要补充 OpenAI API 余额后才能完成问答验证。此前的 DeepSeek 冒烟测试及 33 题离线报告属于原有验证记录，不能当作新模型的问答准确率。

## 启动

需要 Python 3.11+ 与 uv。在项目根目录运行：

```powershell
uv sync
uv run streamlit run app.py --server.port 8503
```

打开 http://localhost:8503 。8502 保留给原来的应用。在另一个终端运行后台检查器：

```powershell
uv run python worker.py
```

应用和 worker 使用同一个 `runtime/factory.sqlite3`。关闭浏览器不会停止 worker；`Ctrl+C` 停止对应终端里的进程。电脑休眠、关机、worker 停止时不会检查；重新启动后执行到期检查。不自动注册操作系统开机任务。UI 显示后台心跳。

## 使用

- **风险概览**：逾期或有风险订单，保留原来的过滤和 7 天/3 工作日规则。
- **经理助手**：离线时可按订单 ID 查看最新源记录。启用联网后，使用 GPT-6.1 Sol 多轮工具问答；每轮重新读取 CSV，简短结论后展开依据。
- **产量与异常**：可选择前 28 天工作日、上一完整周或过去四周同一星期几；支持比较假设的单日产量。工具展示样本、缺失日期、均值、±20% 正常区间、各口径结论和原始行。阈值与最低样本数是公开的启发式规则；不足时不下结论。近期最大/最小值也由 Python 计算。
- **接单估算**：输入件数、品类和明确交期，比较内部积压与外协资格、队列、产能、运输和风险。不分配订单、不预订产能、不保证交期。
- **晨报**：生成预览不保存。每日计划先预览再确认；worker 每个模拟日期保存一次晨报。离线时使用明确标注的确定性摘要。
- **操作与监控**：先预览，再点 Confirm；Reject 不执行。备注和催单消息仅保存在本机。订单监控到期比较工序及最后活动日期，工序监控检查最近完整工作日。每项监控最多提醒一次，提醒在应用内收件箱展示，无外部推送。

首次运行时模拟日期从 **2026-04-01** 开始；随后每过一个真实日历日推进一天。计划时间为 Asia/Shanghai。侧栏显示两个时钟。CSV 不会自动增加数据：缺失的新日产量标记为未知，而不是零。评测固定在 2026-04-01。

## OpenAI 接入（已授权开启，API 余额待补充）

模型固定为 `gpt-6.1-sol`，接口固定为 `https://api.openai.com/v1/responses`。该模型通过 Responses API 调用工具，使用 `reasoning.effort=low`。请求设置 `store=false`，工具交互期间保留返回的加密推理项目，以便继续同一轮工具执行。八个工具的参数、Python 计算与人工确认要求保持不变。模型配置与通信位于 `openai_client.py`。

密钥从环境变量 `OPENAI_API_KEY` 或被 Git 忽略的 `.streamlit/secrets.toml` 读取，空模板位于 `.streamlit/secrets.example.toml`。联网开关为 `OPENAI_NETWORK_ENABLED`，只有明确设为 `true` 才能调用 OpenAI，环境变量优先。DeepSeek 的旧密钥和旧联网开关不会启用 OpenAI，也不会用于 OpenAI 请求。部署到 Streamlit Cloud 时，需要在该部署的 Secrets 中单独设置 OpenAI 密钥与联网开关。应用和 worker 都需要重新启动才能完整加载模型迁移。

请求有超时和最多六轮工具调用限制。API 错误只显示安全摘要。模型没有任意 SQL、代码执行、CSV 写入或执行操作的工具；只能提出待确认操作。

## 验证

```powershell
uv run python -m unittest discover -s tests -v
uv run python evaluate.py
```

`evaluation/cases.json` 包含 33 道有核验答案的开发题：7 道边界/歧义/不可回答题，8 道可行性或操作题。27 项可离线执行的工具断言通过；其余 6 题需要真实自然语言模型判定，未评测。**100% 是离线工具断言通过率，不是问答准确率。**

金标准由 `evaluation/build_cases.py` 用标准库直接读取 CSV、独立计算；不导入应用工具。原始文件哈希保存在题集里。重新生成金标准只用于审阅后的数据/规范变更，不能掩盖失败。

`uv run python evaluate.py --live` 可记录真实模型行为与工具事实匹配，但仍需人工语义审查、留出集和真实失败案例分析；完整真实评测尚未运行。

## 文档

- `docs/TOOL_SPEC.md`：工具输入、输出、目的、非目标、故障处理和影响范围。
- `docs/ARCHITECTURE.md`：数据流、功能对照、假设和剩余交付项。
- `docs/EVALUATION.md`：测量口径、结果、故障分析和未完成验证。

本地单经理原型，不含生产环境身份认证、多租户、外部消息发送或手机推送。源 CSV 保持不变；运行状态、凭证与临时文件不纳入版本控制。
