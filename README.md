# Narration Quality Workflow

**v0.1.0 · 实验版**

平台无关的旁白生成、逐句审核和局部修复工作流。适用于 TTS、诗词朗读及字幕对时：锁定原稿和句 ID，按供应商已验证能力生成请求计划，检查音频，再局部替换并重新审核全轨。支持已有音频作为审核输入。

核心流程与平台适配层分离；适配器声明能力不代表已经实测各供应商 API。规划工具不联网、不授予生成或付费权限。自动检查不能代替实际听感验收。不要把凭据写入清单。

## 安装和使用

将本目录复制到 Codex 的 `skills/narration-quality-workflow`，阅读 [SKILL.md](SKILL.md) 和 [审核说明](references/audit-contract.md)。需要 Python 3；媒体检查需本机 FFmpeg 和 ffprobe。以下从目录根运行，生成的 WAV 仅为合成样例：

```sh
python examples/generate_fixture.py
python scripts/plan_adapter.py --manifest examples/manifest.json --adapter examples/adapter.json --output plan.json
python scripts/audit_audio.py --manifest examples/audit.json --output audit.json
python -m unittest discover -s scripts -p 'test_*.py' -v
```

输出文件已存在时工具拒绝覆盖。结构预检用 `--dry-run`，它不验证媒体。测试覆盖 41 项，包括输入验证、凭据误判、批次部分失败、媒体工具失败和防覆盖；不等于供应商兼容性或听感认证。

## English

An experimental, platform-neutral workflow for narration planning, audio review, and localized repair. Local deterministic tools do not call external services. See [SKILL.md](SKILL.md) for the workflow and limitations.

## License

MIT; see [LICENSE](LICENSE). FFmpeg is a separate dependency under its own license.
