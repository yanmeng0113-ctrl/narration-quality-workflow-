# 提示控制与来源

核验日期：2026-10-31。官方 [SiliconFlow TTS 文档](https://docs.siliconflow.cn/en/userguide/capabilities/text-to-speech) 将 input 定义为待转语音文本，并列 model、voice、speed、gain、response_format 和 sample_rate；其 CosyVoice2 示例给出自然语言指令与 `<|endofprompt|>` 分隔方式。文档所述能力不等于本次模型/音色对任何标签均有效，也不保证指令不会被念出；用短样、授权预算和独立核对验证，失败回退为纯朗读文本和语义分句。`<strong>` 等未经该具体接口文档证明的标签不可视为支持。

不同供应商版本、端点和模型差异很大；在实际调用时重新查官方文档、计价和返回状态，记录当前日期，不把某平台参数推广到其他平台。表达目标、语义断句与停顿可写入制作计划，不应作为不支持的文本标签混入朗读正文。
