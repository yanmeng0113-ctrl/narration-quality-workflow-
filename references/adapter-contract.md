# 平台无关适配合同

公共 manifest 的 `segments` 每项包含唯一 `id`、非空 `text`、可选 `text_sha256`、抽象 `intent` 和平台请求 `request`。脚本重算 UTF-8 SHA-256，给定哈希不符则拒绝；保留原文、ID、哈希及意图。适配器需声明 `verified: true`、名称和 `fields`，每个字段配置 `type`（string/number）及可选 `min`、`max`、`enum`；范围和格式由各平台能力决定。可表达 gain、response_format、sample_rate 等字段。

`prompt.mode` 为 none、field 或 embedded；后两种需 `sample_verified: true`，field 指向已声明字段，embedded 提供经平台验证的 separator。显式 prompt 与 intent 共存时拒绝，避免覆盖。`allowed_tags` 和 `allowed_text_tags` 分别为已核验的精确尖括号标签列表；未知标签拒绝，普通方括号文字不当标签。无提示能力时保留意图和丢弃原因；不支持的标量字段保留值与原因。明显凭据键、Bearer、常见令牌和凭据赋值会被拒绝，但此启发式不能保证发现所有密钥：不得把密钥放入 manifest、prompt 或适配器。

参考 ../examples/manifest.json 与 adapter.json，都是虚构适配器，不是实际兼容声明。`python3 scripts/plan_adapter.py --manifest examples/manifest.json --adapter examples/adapter.json --output plan.json`；加 `--dry-run` 不写文件，不覆盖原文件。计划器不联网、不调用服务、不授予费用权限；verified 与 sample_verified 是调用者基于证据填写，并非程序替代验证。实际使用须另记供应商版本、官方文档/日期、调用及费用状态；用户提供的录音无需生成适配器。

