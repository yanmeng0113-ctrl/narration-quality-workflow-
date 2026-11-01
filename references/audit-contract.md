# 审核合同

生产清单逐句记录 stable ID、原文与朗读文本、文本哈希、模型/voice/speed、实际提示、读音疑点、目标总间隔、调用状态/次数/估算费用、源音频哈希与替换版本；不保存凭据。结果不明先核查，不盲重试。

可选 audit_audio.py 使用顶层 items 数组，每项为唯一 id、audio 路径和可选 heard_review（not_performed、passed、failed）；thresholds 可设置 true_peak_limit_dbtp 与 tail_rms_threshold_dbfs。参见 ../examples/audit.json。实际音频路径相对 manifest 解析。脚本需要 FFmpeg/ffprobe，也可用具有等效能力的其他工具；支持 --ffmpeg 和 --ffprobe 指定路径。--dry-run 不写文件，输出必须为不存在的新文件。真峰超限与尾部声能只是技术指标，尾部活动为截断风险候选而不是结论；整体验收不自动 PASS。错误会指出工具和原因。尾部阈值随报告保存。

ASR 为独立步骤：不使用正确稿提示，交叉识别、分段复核并与原文比对同音、漏字、重复及补全，差异均先列不确定。识别置信度不是发音正确概率；词时间近似，低音量辅音不等于停顿。比对源段首尾、拼接全轨和总间隔，保护完整音素及呼吸；时轴调整后重排字幕、完整解码、逐处复核与最终编码真峰检查。无法实际听音时不得声称听审通过或自动整体合格。

通用边界：原稿、低能量区和词位可能不一致；目标句与上一句无可靠静音时不能按模型字位硬切。复核源段和独立缓存；无法可靠分离则报告不确定，授权下局部重生后仍检查尾音与独立识别。成片可能残留删除区朗读或字幕漂移；应全轨识别、重点片段复核、画面采样与时轴映射分别留证。压缩静音需同步移动音画和后续字幕。这些是流程指导，不是脚本自动完成的功能。


`--dry-run` 仅做结构预检并报告各项媒体是否存在，不做媒体检查。实际运行逐项报告 success/error：部分失败仍写出所有结果并退出码2；全部成功退出0但不代表整体验收通过；结构错误或输出冲突退出1且不写报告。

## 最小示例

在 Skill 目录内，需 Python 和 PATH 中的 FFmpeg/ffprobe。生成的是本地合成正弦音，不含用户录音；输出文件必须不存在：

```bash
python examples/generate_fixture.py
python scripts/plan_adapter.py --manifest examples/manifest.json --adapter examples/adapter.json --output plan.json
python scripts/audit_audio.py --manifest examples/audit.json --output audit.json
```

fixture 生成器拒绝覆盖已有文件；生产时在独立工作目录设置实际路径。

## 分级复核与记录

先按实际能力和授权范围对最终版本执行全量本地检查，记录版本哈希、覆盖及缺项；只对本地发现且无法可靠判定的疑点，在已授权预算与外传范围内发送必要短片段给适用云端适配器。识别差异不能单独判错，越界时码和无法证实的结果不能作为通过证据。确认问题后局部修复并复验最终版；分别记录本地通过、疑点已复核和阻塞。未真实完整听审不得声称听审通过，但本地无实质未决疑点时，不把未做完整听审本身作为交付阻塞。
