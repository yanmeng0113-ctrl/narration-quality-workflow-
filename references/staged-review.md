# 可执行分级判定（离线证据合同）

`scripts/staged_review.py --manifest workdir/review.json --output workdir/review-report.json`

此脚本对最终文件实际执行 ffprobe 和完整 FFmpeg 解码，以实测时长与媒体流约束声明；声明时长误差大于 1ms、漏报视频/内嵌字幕或声称旁白但无音轨均拒绝。decode 不采信自填 passed。报告 automatic_checks 为本次执行结果，external_checks 为外部供证。其余 ASR、字幕、画面、尾音等结果须有下述结构化证据文件；它不运行 ASR、画面模型或真实听审，文件哈希只能证明记录版本，不能证明外部记录诚实。不得将手填 passed 当成实际执行证据。技术脚本 audit_audio.py 的 success 不是本地验收通过。

## 输入

顶层 `items` 数组，每项：
- `id` 稳定 ID，`media` 相对清单路径，`source_sha256` 最终文件哈希，`duration_seconds` 实测时长。
- 显式布尔 `has_narration`、`has_video`、`has_subtitles`；据真实媒体设定，不得通过设 false 跳过适用检查。
- `checks`：始终需要 decode；视频需要 visuals；字幕需要 subtitle_sync；旁白需要 asr_content、pronunciation_risk_scan、boundaries_pauses、tail、loudness_peak。
- 每条外部 check：`source_sha256`、`tool`（工具和版本/配置留证）、`status: passed|failed|uncertain`、`coverage: [[start,end],...]`。覆盖必须从 0 连续到最终时长，所有时码有限、非负、有序且不越界。没有该证据即 missing，不自动通过。decode 覆盖由实际解码生成，不使用清单里的 decode 通过声明。
- 每条外部 check 还必须提供 `evidence_ref: {path,sha256}`；path 相对清单，文件必须存在且 SHA-256 匹配。证据 JSON 需含 `source_sha256, check_name, tool, tool_version, method, details, coverage, status`，source/check/coverage/status 与清单一致。method/details 说明真实执行方法与发现，不可写虚构执行记录。只核文档结构不证明执行；ASR 或人工证据来自实际工具回执/审阅记录。
- asr_content 另外需要 `asr_source: {tool, model, blind:true}`、`text_sha256`（expected_text 的 UTF-8 SHA-256）；项内保留 `expected_text`。blind 表示未用正确稿提示识别。结构化 ASR 工件自身也必须包含相同 text_sha256 和 asr_source（blind 必须是真布尔 true）；只更新清单文本哈希不能复用旧工件。实际转写、差异列表和工具输出另留工作区；不得自行把未决差异标 passed。
- pronunciation_risk_scan 是独立于 ASR 拼写的一次全稿读音风险筛查记录。工件包含锁稿 text_sha256 和 pronunciation_risks 数组；每项为 `{id,kind:"pronunciation",text,interval:[start,end],reason,note?}`，记录实际疑点字词、局部区间和理由。没有实际疑点可为空数组；不得仅因 ASR 同字清除已存在的读法风险。
- `pronunciation_notes` 字符串数组、`content_type: prose|poetry`。诗词标签要求读音筛查，不代表全篇发音有问题，也不会自动创建全长疑点。备注须由 scan 中带相同 note 的实际局部风险定位；尚未定位时列 missing/unlocalized_note，不默认发全篇云端。规划器保留这些字段，pronunciation_scan_required 与具体 pronunciation_review_required 分开。
- `risks`：`[{id,kind,interval:[start,end]}]`，例如 kind pronunciation/naturalness/truncation。包含全部本地未决疑点；自动 pronunciation ID 保留不可重复。
- `resolutions`：`[{risk_id,source_sha256,interval,capability,reviewer,evidence,status:"resolved"}]`。必须覆盖疑点且绑定同一最终版本。另需 evidence_ref 指向 SHA 匹配工件：check_name=risk_resolution，source_sha256/text_sha256、risk_id/capability/interval/reviewer/evidence/status 与当前记录一致，coverage=[interval]，并含 tool/tool_version/method/details。status 必须明确 resolved；仅有 reviewer/evidence 字符串不能解决。修改后旧 hash 解决记录失效。capability 为 local_measurement、transcription、human_listening、audio_understanding、local_phonetic_analysis；前二者不能解决 pronunciation/naturalness。local_phonetic_analysis 仅解决读音，工件还需 audio_analyzed:true、具体 acoustic_observations 和 phoneme_findings；不能解决自然度，也不能用 ASR 同字代替声音证据。audio_understanding 可以是已验证的本地音频感知模型，并非强制云端。

## 状态与交付固定措辞

- `stage: blocked`：缺证据/版本不符/覆盖不足/检查未通过。
- `stage: review_required`：适用本地检查记录齐全，但仍有未解决疑点；只送必要疑点短片段复核，未授权不上传。
- `stage: local_pass`：适用检查覆盖完整且无未决疑点。固定交付措辞：“本地检查通过；不等于完整听审通过。”
- `heard_review` 仍仅 not_performed/passed/failed，绝不可填 local_pass。声明 passed 需 listening_evidence，包含最终 source_sha256、全时段 coverage、真实能力、非空 reviewer/evidence，以及按上述格式的 evidence_ref（check_name 为 listening，status 为 passed）；云端还需下述 adapter 证据。listening_evidence 及其工件 status 都须明确 passed；failed/skipped/unknown/false 一律不能视为听审通过。没有完整听审本身不阻塞。
- overall_pass 始终 false（本工具不签发全面听感认证）。结果逐项继续；全 local_pass 退出 0，任一阻塞或待复核退出 2；清单/输出错误退出 1。所有输出拒绝覆盖。

## 云端适配器能力边界

`examples/reviewer_adapter.json` 是**未配置、未验证、无网络实现**的合同，不是可运行硅基流动听审适配器。当前仅新增默认禁用的可选 HTTP transport 代码；没有声称已验证任何供应商的真正音频理解质量，也没有发起真实提供商测试。转写 API 即使返回文字/词时码，也只能标 transcription，不可判自然度或多音字读音，不可编造时码。

未来接入 audio_understanding 前：核当前官方文档支持音频输入和相关判断，记录官方 URL/日期/模型/返回结构，授权短样实测；不得仅把 verified 改 true。解决记录携带 `adapter: {capability:"audio_understanding",verified:true,sample_verified:true,official_docs_url:"..."}`。此离线工具只能检查声明结构，真实性由原始调用回执支持。模型返回时码必须在已发送片段内；适配器在映射到源媒体前验证片段范围，映射后本脚本再次拒绝最终媒体越界，不裁剪或伪造。下述 helper 已实现片段和最终源区间边界校验，不能宣称真实云端链路已通过。

### 文档支持的离线请求/响应 helper

`scripts/reviewer_adapter.py` 提供 `build_request` / `validate_response`，仅 Python 函数、不联网、不载入密钥；默认 request_planning_enabled 缺省为禁用。配置必须明确模型、官方文档 URL 和 max_clip_seconds（≤60 秒上限，仅防止误传全片，可按疑点缩短）。clip 必须是已经提取的 WAV，时长匹配 source_interval；它不会裁剪原文件。构造 chat/completions 的 audio_url 内容，但不保证具体账号模型可用。

来源核验日期 2026-11-01：[硅基流动多模态文档](https://docs.siliconflow.cn/docs/userguide/capabilities/multimodal-vision) 和 [Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct)。Qwen3-Omni 支持音频输入；供应商页面模型表与 SDK 示例存在名称差异，所以不预填生产模型，不据此宣称单价/账号可用性已核实。网页直连曾返回 502，父级官方搜索抓取可读；官方模型卡本地复核可读。

返回值必须是显式 structured findings，文本转写不接受。helper 在源时轴映射前拒绝片段内越界时间；保持 clear/issue/uncertain 作为候选证据，不自动生成 resolved 或 heard_review passed。这是 docs-supported/offline-tested/not-live-validated：真实供应商调用、音频感知质量和中文多音字准确度均未验证。费用/外传授权及实时价格需在实际发送前单独核实；可选 HTTP 执行器的默认禁用、授权与预算门禁见后续章节；离线 helper 本身不联网。

## 可选真实 HTTP transport（默认禁用，仅 mock 测试）

`scripts/reviewer_transport.py` 已实现可执行传输代码，而非只有 request-builder；**尚未向真实供应商发送过本修复版本请求**。启用前必须确认实际授权，不可把 JSON 布尔值当作用户授权。

入口：`python scripts/reviewer_transport.py --config workdir/reviewer.json --context workdir/clip-context.json --clip workdir/clip.wav --source workdir/final.mp4 --output workdir/cloud-candidate.json --execute`。输出须不存在；不提供 --execute 或 execution_enabled 非 true 时拒绝，不上传。仅固定官方 HTTPS `https://api.siliconflow.cn/v1/chat/completions`，拒绝重定向，无自动重试。

配置需要：provider=siliconflow、明确 model、capability=audio_understanding、request_planning_enabled/execution_enabled、model_verified/audio_input_verified/pricing_verified/upload_authorized/payment_authorized 均为真正核实后的 true；official_docs_url、verification_date、pricing_checked_at、approval_reference；max_clip_seconds≤60、output_limit≤4096；pricing.currency、input_per_million、output_per_million、audio_units_per_second 及 remaining_budget。模型不预填，价格不预填；未知费用 fail closed。零价费率须另有 free_tariff_verified:true；audio_units_per_second 必须大于零。该预算计算为保守估算，不是供应商账单证明或服务端硬预算上限。

上传授权绑定 approved_source_sha256 与 approved_clip_sha256；context 同时含这两个源/片段哈希（名为 source_sha256/clip_sha256）、risk_id、source_interval、source_duration_seconds、question。执行前实际探测/解码源媒体，校验源/片段文件 SHA 和时长；片段必须是来源可追溯的本地短 WAV。调用方保存提取命令/回执，不把其他音频冒充源片段。

全部预检后才读取已有环境变量 SILICONFLOW_API_KEY；不读账号配置文件，不索要或记录密钥，不回显音频 base64、Authorization 或原始错误响应。没配凭据即停止。HTTP 错误记录 http_error；HTTP open/read 阶段的超时、连接、IncompleteRead、BadStatusLine 等传输异常均使用固定安全文字记录 outcome_unknown；不回显异常原文，也不吞掉预检异常或 KeyboardInterrupt。响应限制 1MiB、嵌套深度 64；JSON 解析/递归失败记录 invalid_response，仍保留 attempts=1。应先核对供应商执行/账单，禁止自动重试；不因网络不确定自行重新付费。

成功结果仅 candidate_received/review_required；音频理解模型也可能听错，需结合本地证据确认后才登记解决。没有 `heard_review: passed` 自动签发。离线 mock 覆盖成功、HTTP失败、结果不明、越界响应和门禁；真实供应商可用性、价格、延迟和中文发音可靠性仍未验证。
