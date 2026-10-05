# GitHub 设置与执行边界

本目录是 RAG loop 的本地模板。当前准备的是合成数据 CI：检查状态流转、验证门禁和演示流程，不证明真实 RAG 质量达标。本说明不表示已经创建 GitHub 仓库、推送代码、跑通云端 CI、配置审批或注册 Runner。

## 仓库可见性

个人 GitHub 仓库可以选择私有；若希望公开分享，只发布经过检查的通用代码、测试、合成样例和说明。真实文档、评估题目及答案、索引、日志、模型登录缓存和业务配置留在本地受控执行环境。未来可再建立独立私有执行仓库，本模板未创建它。

发布前逐项检查将提交的文件和 Git 历史。`.gitignore` 不能移除已经提交的数据。公开仓库的代码、运行日志及任何主动上传的附件都应按公开资料处理。

## 当前 CI 做什么

`.github/workflows/ci.yml` 在主分支 `main` 的推送、PR 和手动触发时运行。若实际默认分支名称不同，需要相应调整 `push.branches`。工作流只使用 GitHub 托管的 Ubuntu 和 Windows 执行机器，以及 Python 3.12：

```text
检出模板 → 准备 Python → 标准库 unittest → 合成 loop 演示
```

本机可先从仓库根目录运行同样的命令，要求 Python 3.11 或以上：

```powershell
python -m unittest discover -s tests -v
python loop_core.py demo --output .ci-output/synthetic
```

CI 没有安装业务依赖，不访问真实 RAG 服务，不调用 Codex、Claude 或模型 API。它使用只读仓库权限，并关闭 checkout 凭据持久化；没有模型密钥、`self-hosted` 执行任务、定时任务、`pull_request_target` 或自动创建 PR/合并的步骤。同一分支或 PR 的新运行会取消旧运行；每个系统上的任务最多运行 10 分钟。

演示文件生成在托管机器的工作目录中，本工作流没有配置附件上传或长期状态保存。日志可在 Actions 页面查看。CI 通过只表示模板检查通过，不能代替真实文档和索引的评估。

## 在个人 GitHub 上启用

以下均为待执行设置，不是已完成状态。

1. 创建个人仓库并选定可见性，只推送检查过的模板文件。
2. 在仓库 Actions 设置中允许本工作流所需的官方 `actions/checkout` 和 `actions/setup-python`。保持工作流 token 的默认权限为只读；当前工作流不需要添加任何 secret。
3. 推送至 `main`，或在工作流进入默认分支后从 Actions 页面手动运行。检查 Ubuntu、Windows 两项检查均通过；实际失败应以运行日志定位。
4. 如需合并前强制检查，在仓库支持的 ruleset／分支保护中选择首次运行实际显示的两项状态检查。写入 YAML 并不会自动启用仓库保护规则。

本次没有创建或更改远程仓库、Actions 设置、仓库规则、环境或凭据。

## 真实 loop 在哪里运行

真实执行先保留在当前 Windows 电脑上的受控工作目录，由明确的本地操作启动。当前合成 CI 不会自动调用这台电脑，也没有建立 GitHub 到本机的执行桥接。

不要把带有个人登录状态、业务文档或内网访问能力的本机 Runner 注册到公开仓库。GitHub 官方说明，自托管 Runner 可能被工作流中的不可信代码持久入侵，公开 PR 会扩大这一风险；环境审批也不能提供进程或机器隔离。[GitHub Runner 安全说明](https://docs.github.com/en/actions/reference/security/secure-use#hardening-for-self-hosted-runners)

后续需要自动真实执行时，先确定独立的可信执行边界：受控本地入口，或另行创建的私有执行仓库与隔离执行账户。私有本身也不能替代代码信任检查；执行前应锁定已审查提交、限制数据目录与网络访问、使用独立凭据，避免公开 PR 内容直接获得本机执行权限。持久状态、任务重试和本机断电后的恢复需要另外接入，当前 CI 没有提供这些能力。

真实流水线接入后，沿用项目离线验证，再执行真实 RAG 评估。Codex 根据失败证据生成候选修改；Claude 按需要审查；缺失报告、错误、未执行项或非有限分数均不能被当作通过。代码、数据、索引、评估配置和报告版本共同决定候选身份；审批绑定该身份，任何变化都要重新验证。

## 模型认证与费用

公开模板不需要模型认证。不要上传或提交 `.codex/auth.json`、Claude 登录缓存、API Key 或包含这些内容的日志。

OpenAI 官方将 API Key 作为 CI/CD 自动化的推荐认证方式，API 用量单独计费。账户认证的高级 CI 指引适用于可信执行环境，明确不应在公开／开源仓库使用该账户认证方案。不能通过上传个人登录缓存，让公开 CI 消耗桌面订阅额度。[OpenAI 认证说明](https://learn.chatgpt.com/docs/auth)；[账户认证 CI/CD 高级指引](https://learn.chatgpt.com/docs/auth/ci-cd-auth)

本机已登录的 Codex／Claude 能否用于后续无人值守执行，需要按实际 CLI 版本、账号权益和额度验证。当前模板不声称已实现订阅认证、自动额度恢复或无限连续运行，也没有为任何 API 配置付费调用。

## 审批节点是后续设置

当前 CI 没有发布任务，因此没有配置 GitHub Environment。将来若在适用的执行仓库加入发布任务，可以考虑 Environment 的 required reviewers，并按账号计划及仓库可见性确认可用性。环境的审核人、分支限制和保护规则需要在 GitHub 设置中实际配置；单独添加 `environment:` 不代表审批保护已经生效。[GitHub Environment 说明](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

公开模板里的 Environment 示例最多演示审批流程，不能作为开放本机凭据或真实数据的依据。后续审批通过后恢复执行，还应重新校验候选版本，并在私有执行域记录结果。

## 官方动作版本

以下固定提交于 2026-10-05 从各自官方 release 页面核对。升级时重新核实 release 对应的完整提交，检查变更后再更新；不要只依赖可移动的 major tag。

| 动作 | 核验版本 | 固定提交 |
| --- | --- | --- |
| [actions/checkout](https://github.com/actions/checkout/releases/tag/v7.0.1) | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| [actions/setup-python](https://github.com/actions/setup-python/releases/tag/v7.0.0) | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |

固定 action 提交不意味着托管操作系统和 Python 补丁版本完全固定；本工作流验证的是 Ubuntu／Windows 与 Python 3.12 系列的兼容性。确定性 RAG 实验还需要另外固定业务依赖和数据版本。
