"""
Model configuration and constraint resolution.

Single source of truth for LLM model limits. Litellm's model registry is
often wrong for OpenRouter-hosted models (e.g., reporting 262K max_output
for kimi-k2.5 which only supports 8K). This module provides an override
table for known models and falls back to litellm / conservative defaults.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """Constraints for a specific LLM model."""

    context_window: int        # max input tokens the model accepts
    max_output_tokens: int     # actual provider limit for completions
    supports_tool_calling: bool

    def __str__(self) -> str:
        return (
            f"ctx={self.context_window:,} "
            f"out={self.max_output_tokens:,} "
            f"tools={'yes' if self.supports_tool_calling else 'no'}"
        )


# ──────────────────────────────────────────────────────────────────────
# Override table for models where litellm reports incorrect values.
# Keys are the model identifier WITHOUT the provider prefix
# (e.g., "moonshotai/kimi-k2.5" not "openrouter/moonshotai/kimi-k2.5").
# ──────────────────────────────────────────────────────────────────────

MODEL_OVERRIDES: dict[str, ModelConfig] = {
    # Kimi K2.5: litellm says 262K output, OpenRouter actually supports 8K
    "moonshotai/kimi-k2.5": ModelConfig(
        context_window=131_072,
        max_output_tokens=8_192,
        supports_tool_calling=True,
    ),
    # Kimi K2 Thinking: extended output
    "moonshotai/kimi-k2-thinking": ModelConfig(
        context_window=131_072,
        max_output_tokens=64_000,
        supports_tool_calling=True,
    ),
    # Devstral
    "mistralai/devstral-2512": ModelConfig(
        context_window=131_072,
        max_output_tokens=8_192,
        supports_tool_calling=True,
    ),
    # MiniMax M2.1
    "minimax/minimax-m2.1": ModelConfig(
        context_window=1_048_576,
        max_output_tokens=16_384,
        supports_tool_calling=True,
    ),
    # Qwen3 Coder (Ollama, common local model)
    "qwen3-coder:30b": ModelConfig(
        context_window=32_768,
        max_output_tokens=8_192,
        supports_tool_calling=True,
    ),
}

# Conservative fallback when model is completely unknown
_DEFAULT_CONFIG = ModelConfig(
    context_window=32_768,
    max_output_tokens=4_096,
    supports_tool_calling=True,
)


def _strip_provider_prefix(model: str) -> str:
    """Strip provider routing prefixes like 'openrouter/' or 'ollama/'.

    Examples:
        'openrouter/moonshotai/kimi-k2.5' → 'moonshotai/kimi-k2.5'
        'ollama/qwen3-coder:30b'          → 'qwen3-coder:30b'
        'mistralai/devstral-2512'         → 'mistralai/devstral-2512'
    """
    PROVIDER_PREFIXES = ("openrouter/", "ollama/", "litellm_proxy/", "hosted_vllm/")
    for prefix in PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


def resolve_model_config(model: str) -> ModelConfig:
    """Resolve the actual constraints for a model.

    Resolution order:
    1. Check override table (exact match after stripping provider prefix)
    2. Query litellm's model registry
    3. Fall back to conservative defaults
    """
    bare = _strip_provider_prefix(model)

    # 1. Override table
    if bare in MODEL_OVERRIDES:
        return MODEL_OVERRIDES[bare]

    # 2. Litellm lookup
    try:
        import litellm
        info = litellm.get_model_info(model)
        if info:
            ctx = info.get("max_input_tokens") or info.get("max_tokens") or _DEFAULT_CONFIG.context_window
            out = info.get("max_output_tokens") or _DEFAULT_CONFIG.max_output_tokens
            # Sanity: max_output should never exceed context window
            if out > ctx:
                out = min(out, ctx // 2)
            return ModelConfig(
                context_window=ctx,
                max_output_tokens=out,
                supports_tool_calling=info.get("supports_function_calling", True),
            )
    except Exception:
        pass

    # 3. Conservative default
    return _DEFAULT_CONFIG
