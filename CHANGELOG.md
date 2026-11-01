# Changelog

## 未发布（`v0.2.0` 之后的 main）

- 技能标识统一为 `eddyy-skill-narration-quality`（提交 `1ae928f`）；旧名 `narration-quality-workflow` 仅为历史名称，仓库地址与 `v0.2.0` 标签不变，脚本接口、清单格式和审核行为不变。
- 新增 `install.sh`：复制到 `<skills 目录>/eddyy-skill-narration-quality`，已有安装改名备份到 `.backups/`，不删除；支持 `--target` 与 `--dry-run`。
- 清理测试中未使用的 `copy` 导入。
- 仍为实验版：未实测任何供应商 API，也未做听感 QA。

## v0.2.0（第6版，实验版）

固定的实验性版本，基于提交 `e534d07`；本次仅补充版本与文档标记，不改变行为、测试或评分逻辑。

- 包含 126 项回归测试（`python -m unittest discover -s scripts -p 'test_*.py' -v` 或 `python3 -m pytest -q scripts`）；回归测试不等于供应商兼容性或听感认证。
- 旁白生成、逐句审核与局部修复工作流，以及分级复核合同（见 `references/staged-review.md`）。
- README 已如实说明：未实测任何供应商 API，适配器声明的能力不代表已验证；未配置或实测任何云端音频理解（listen）提供商；自动检查不能替代真实听审。
- 规划工具不联网，不启用供应商 HTTP 调用。
- 文档：新增本 CHANGELOG；SKILL.md 标题后加入版本行；README 补充 unittest 与 pytest 均可运行的说明。
