# 模型配置说明

## 自动禁用 Think 输出

工具会根据 `config.yaml` 中配置的 `model` 名称，**自动**向 API 传入禁用 think/thinking 的参数。无需手动配置。

### 适配模型列表

| 模型厂商 | 匹配关键字 | 传入参数 | 说明 |
|---------|-----------|---------|------|
| DeepSeek | `deepseek` | `enable_thinking: false` | deepseek-chat, deepseek-coder, deepseek-reasoner 等 |
| MiniMax | `minimax`, `abab` | `thinking: false` | minimax-abab6 等 |
| Moonshot / Kimi | `moonshot`, `kimi` | `thinking: false` | moonshot-v1, kimi-latest 等 |
| 通义千问 (Qwen) | `qwen`, `qwq` | `thinking: false` | qwen-turbo, qwq-32b 等 |
| 智谱 (GLM) | `glm`, `chatglm` | `thinking: false` | glm-4, chatglm3 等 |
| 腾讯混元 | `hunyuan` | `thinking: false` | hunyuan-lite 等 |
| 字节豆包 | `doubao` | `thinking: false` | doubao-pro 等 |
| 零一万物 (Yi) | `yi-` 开头 | `thinking: false` | yi-large 等 |
| GPT / Claude | 不匹配以上 | 不传额外参数 | 海外模型默认不输出 think |

### 代码位置

自动禁用逻辑在 `ai_engine.py` 的 `_get_disable_thinking_params()` 方法中：

```python
def _get_disable_thinking_params(self, model: str) -> dict:
    m = model.lower()
    if 'deepseek' in m:
        return {"extra_body": {"enable_thinking": False}}
    if 'minimax' in m or 'abab' in m:
        return {"extra_body": {"thinking": False}}
    # ... 更多模型见源码
    return {}  # 不匹配的不传参
```

在两个 API 调用点生效：
- `_call_api()` — 审核主流程
- `_call_api_json_fix()` — JSON 修复流程

### 添加新模型

如需适配新模型，修改 `ai_engine.py` 中的 `_get_disable_thinking_params` 方法，增加匹配规则和对应参数即可。
