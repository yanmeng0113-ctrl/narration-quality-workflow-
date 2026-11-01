# Eddyy Skill Narration Quality

**v0.2.0（第6版，实验版）**

平台无关的旁白生成、逐句审核和局部修复工作流。适用于 TTS、诗词朗读及字幕对时：锁定原稿和句 ID，按供应商已验证能力生成请求计划，检查音频，再局部替换并重新审核全轨。支持已有音频作为审核输入。

核心流程与平台适配层分离；适配器声明能力不代表已经实测各供应商 API。规划工具不联网、不授予生成或付费权限。自动检查不能证明实际听感或替代真实听审；未做完整听审不等于本地检查失败。不要把凭据写入清单。

## 触发、审核与状态

旁白音频或含旁白视频生成、修改或交付验收时使用；视频制作完成后、交付前执行适用的本地检查。无旁白视频检查画面、字幕和技术完整性，不强制 ASR。先锁定稿件与生成参数，再对最终版本全量本地对稿、检查字幕、断句、尾音和音量；按实际能力检查画面并记录版本哈希与覆盖。仅将本地发现且无法可靠判定的必要短片段，在预算和外传授权内交云端音频理解复核（硅基流动可为适配示例）；确认问题后局部修复并复验最终版本。

本地检查通过、疑点已复核、阻塞及完整听审是不同状态。未真实听审不能声称听审通过；本地无影响交付的实质未决疑点时，未做完整听审本身不阻塞。ASR 同音差异不能直接判错，越界时码和无法证实的模型结果不能作为通过证据。工具不会自动完成全部流程，也不授予额外费用或上传权限。

## 已知限制

冒号和等号形式的常见凭据赋值已拒绝，普通英文可使用；启发式不是秘密扫描器，不要将凭据放入清单。新增分级判定：实际探测与解码最终媒体，其余检查需结构化版本绑定证据；未配置或实测任何云端音频理解提供商。见 [分级复核合同](references/staged-review.md)。

## 安装和使用

技能标识为 `eddyy-skill-narration-quality`，沿用 `eddyy-skill-功能名` 命名方式。原名 `narration-quality-workflow` 仅作为历史名称；仓库地址和既有 `v0.2.0` 标签不变。此次只统一技能名称，不改变脚本接口、清单格式或审核行为。已有安装请在迁移前备份本地改动，并确保技能发现目录中只保留一个有效副本，避免新旧名称重复加载。

将本目录复制到 Codex 的 `skills/eddyy-skill-narration-quality`，阅读 [SKILL.md](SKILL.md) 和 [审核说明](references/audit-contract.md)。需要 Python 3；媒体检查需本机 FFmpeg 和 ffprobe。以下从目录根运行，生成的 WAV 仅为合成样例：

```sh
python examples/generate_fixture.py
python scripts/plan_adapter.py --manifest examples/manifest.json --adapter examples/adapter.json --output workdir/plan.json
python scripts/audit_audio.py --manifest examples/audit.json --output workdir/audit.json
python -m unittest discover -s scripts -p 'test_*.py' -v
```

测试可用 `python -m unittest discover -s scripts -p 'test_*.py' -v`，也可在已安装 pytest 时用 `python3 -m pytest -q scripts`（均为 126 项）。

输出文件已存在时工具拒绝覆盖。结构预检用 `--dry-run`，它不验证媒体。回归测试覆盖输入验证、分级证据、读音疑点及输入验证、凭据误判、批次部分失败、媒体工具失败和防覆盖；不等于供应商兼容性或听感认证。

## English

An experimental, platform-neutral workflow for narration planning, audio review, and localized repair. Local deterministic tools do not call external services. See [SKILL.md](SKILL.md) for the workflow and limitations.

## License

MIT; see [LICENSE](LICENSE). FFmpeg is a separate dependency under its own license.

