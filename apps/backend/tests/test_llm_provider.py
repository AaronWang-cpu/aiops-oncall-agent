from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from super_ai.llm import (
    EmbeddingModel,
    LlmConfigurationError,
    OpenAICompatibleProvider,
    load_llm_provider_config,
)


class FakeChatModel:
    def __init__(self, response: object | None = "ok", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        if self.error is not None:
            raise self.error
        return self.response


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[1.0, 0.0, 0.5] for _text in texts]


class FakeAsyncEmbeddingClient:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def create(self, *, input: list[str], **_kwargs: object) -> dict[str, object]:
        self.inputs.append(input)
        return {"data": [{"embedding": [float(text.removeprefix("text-"))]} for text in input]}


def test_loads_tracked_deepseek_chat_defaults() -> None:
    config = load_llm_provider_config()

    assert config.provider == "deepseek-openai"
    assert config.api_key.startswith("sk-")
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.chat_model == "deepseek-flash"
    assert config.embedding_model == "text-embedding-v4"
    assert config.embedding_dimensions == 1024
    assert config.rerank_model == "qwen3-vl-rerank"
    assert config.rerank_url.endswith("/text-rerank/text-rerank")
    assert config.context_window_tokens == 1_048_576
    assert config.temperature == 0.2
    assert config.timeout_seconds == 120.0
    assert config.max_retries == 2


def test_tracked_defaults_keep_embedding_and_rerank_on_their_own_endpoint() -> None:
    config = load_llm_provider_config()

    assert config.embedding_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.embedding_base_url != config.base_url
    assert config.embedding_api_key.startswith("sk-")
    assert config.embedding_api_key != config.api_key
    assert config.rerank_api_key == config.embedding_api_key


def test_loads_explicit_project_config_file(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="test-secret",
        base_url="https://example.test/v1",
        chat_model="qwen-test-chat",
        embedding_model="qwen-test-embedding",
        embedding_dimensions=768,
        rerank_model="qwen-test-rerank",
        temperature=0.7,
        timeout_seconds=45,
        max_retries=4,
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.api_key == "test-secret"
    assert config.base_url == "https://example.test/v1"
    assert config.chat_model == "qwen-test-chat"
    assert config.embedding_model == "qwen-test-embedding"
    assert config.embedding_dimensions == 768
    assert config.rerank_model == "qwen-test-rerank"
    assert config.temperature == 0.7
    assert config.timeout_seconds == 45.0
    assert config.max_retries == 4


def test_merges_user_project_config_file(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="",
        chat_model="",
        embedding_model="",
    )
    (tmp_path / "user.project.json").write_text(
        json.dumps(
            {
                "llm": {
                    "apiKey": "merged-secret",
                    "chatModel": "merged-chat",
                    "embeddingModel": "merged-embedding",
                    "modelCapabilities": {"merged-chat": {"contextWindowTokens": 262144}},
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.api_key == "merged-secret"
    assert config.chat_model == "merged-chat"
    assert config.embedding_model == "merged-embedding"
    assert config.context_window_tokens == 262144
    assert config.base_url == "https://api.deepseek.com/v1"


def test_auxiliary_endpoints_reuse_the_chat_configuration_when_unset(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, api_key="chat-secret")

    config = load_llm_provider_config(config_path=config_path)

    assert config.embedding_base_url == config.base_url
    assert config.embedding_api_key == "chat-secret"
    assert config.rerank_api_key == "chat-secret"


def test_auxiliary_endpoints_can_point_at_another_provider(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="chat-secret",
        embedding_base_url="https://embeddings.example.test/v1",
        embedding_api_key="embedding-secret",
        rerank_api_key="rerank-secret",
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.embedding_base_url == "https://embeddings.example.test/v1"
    assert config.embedding_api_key == "embedding-secret"
    assert config.rerank_api_key == "rerank-secret"
    assert "chat-secret" not in repr(config)
    assert "embedding-secret" not in repr(config)
    assert "rerank-secret" not in repr(config)


def test_blank_auxiliary_credentials_reuse_the_chat_configuration(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="chat-secret",
        embedding_base_url="",
        embedding_api_key="",
        rerank_api_key="",
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.embedding_base_url == config.base_url
    assert config.embedding_api_key == "chat-secret"
    assert config.rerank_api_key == "chat-secret"


def test_non_string_auxiliary_endpoint_is_rejected(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, api_key="chat-secret")
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    raw_config["llm"]["embeddingApiKey"] = 123
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    with pytest.raises(LlmConfigurationError, match="embeddingApiKey"):
        load_llm_provider_config(config_path=config_path)


def test_missing_api_key_fails_safely(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, api_key="")

    with pytest.raises(LlmConfigurationError) as exc_info:
        load_llm_provider_config(config_path=config_path)

    message = str(exc_info.value)
    assert "apiKey" in message
    assert "sk-" not in message


def test_chat_model_requires_matching_capability_profile(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, api_key="test-secret")
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    raw_config["llm"]["chatModel"] = "unprofiled-model"
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    with pytest.raises(LlmConfigurationError, match="unprofiled-model"):
        load_llm_provider_config(config_path=config_path)


def test_provider_constructs_model_with_config() -> None:
    config = load_llm_provider_config()
    captured: dict[str, Any] = {}

    def fake_factory(factory_config: object) -> FakeChatModel:
        captured["config"] = factory_config
        return FakeChatModel()

    provider = OpenAICompatibleProvider(config=config, model_factory=fake_factory)

    model = provider.create_chat_model()

    assert isinstance(model, FakeChatModel)
    assert captured["config"] is config


def test_provider_constructs_embedding_model_with_config() -> None:
    config = load_llm_provider_config()
    captured: dict[str, object] = {}

    def fake_embedding_factory(factory_config: object) -> EmbeddingModel:
        captured["config"] = factory_config
        return FakeEmbeddingModel()

    provider = OpenAICompatibleProvider(
        config=config,
        model_factory=lambda _: FakeChatModel(),
        embedding_factory=fake_embedding_factory,
    )

    model = provider.create_embedding_model()

    assert isinstance(model, FakeEmbeddingModel)
    assert captured["config"] is config


@pytest.mark.asyncio
async def test_default_embedding_model_preserves_raw_text_inputs_and_batches_by_ten() -> None:
    config = load_llm_provider_config()
    provider = OpenAICompatibleProvider(config=config, model_factory=lambda _: FakeChatModel())

    model = provider.create_embedding_model()
    embedding_model = cast(Any, model)
    fake_client = FakeAsyncEmbeddingClient()
    embedding_model.async_client = fake_client
    texts = [f"text-{index}" for index in range(11)]

    vectors = await embedding_model.aembed_documents(texts)

    assert embedding_model.check_embedding_ctx_length is False
    assert embedding_model.dimensions == config.embedding_dimensions
    assert embedding_model.openai_api_base == config.embedding_base_url
    assert embedding_model.chunk_size == 10
    assert fake_client.inputs == [texts[:10], texts[10:]]
    assert vectors == [[float(index)] for index in range(11)]


@pytest.mark.asyncio
async def test_readiness_succeeds_without_exposing_secret() -> None:
    config = load_llm_provider_config()
    fake_model = FakeChatModel(response="ready")
    provider = OpenAICompatibleProvider(config=config, model_factory=lambda _: fake_model)

    result = await provider.check_readiness()

    assert result.ok is True
    assert result.provider == "deepseek-openai"
    assert result.model == "deepseek-flash"
    assert result.base_url == "https://api.deepseek.com/v1"
    assert result.error is None
    assert result.latency_ms >= 0
    assert config.api_key not in repr(result)
    assert fake_model.inputs


@pytest.mark.asyncio
async def test_readiness_failure_is_safe() -> None:
    config = load_llm_provider_config()
    provider = OpenAICompatibleProvider(
        config=config,
        model_factory=lambda _: FakeChatModel(error=RuntimeError("provider unavailable")),
    )

    result = await provider.check_readiness()

    assert result.ok is False
    assert result.error == "provider unavailable"
    assert config.api_key not in repr(result)


def test_provider_source_does_not_import_dashscope() -> None:
    source_root = Path("src/super_ai/llm")
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))

    assert "dashscope" not in source.lower()


# ---------- 诊断专用模型：独立策略，不影响聊天模型 ----------


def test_diagnostic_model_disables_retries_and_clamps_timeout() -> None:
    config = load_llm_provider_config()
    captured: dict[str, object] = {}

    def fake_factory(factory_config: object) -> FakeChatModel:
        captured["config"] = factory_config
        return FakeChatModel()

    provider = OpenAICompatibleProvider(config=config, model_factory=fake_factory)

    provider.create_diagnostic_model(timeout_seconds=45)

    diagnostic_config = cast(Any, captured["config"])
    assert diagnostic_config.max_retries == 0
    assert diagnostic_config.timeout_seconds == 45.0
    assert diagnostic_config is not config
    assert config.max_retries == 2
    assert config.timeout_seconds == 120.0


def test_diagnostic_model_never_exceeds_configured_timeout() -> None:
    config = load_llm_provider_config()
    captured: list[object] = []

    def fake_factory(factory_config: object) -> FakeChatModel:
        captured.append(factory_config)
        return FakeChatModel()

    provider = OpenAICompatibleProvider(config=config, model_factory=fake_factory)

    provider.create_diagnostic_model(timeout_seconds=600)

    assert cast(Any, captured[0]).timeout_seconds == config.timeout_seconds


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_diagnostic_model_rejects_non_positive_timeout(timeout_seconds: float) -> None:
    config = load_llm_provider_config()
    provider = OpenAICompatibleProvider(config=config, model_factory=lambda _: FakeChatModel())

    with pytest.raises(ValueError, match="positive"):
        provider.create_diagnostic_model(timeout_seconds=timeout_seconds)


def test_chat_model_keeps_configured_retries_after_diagnostic_use() -> None:
    config = load_llm_provider_config()
    captured: list[object] = []

    def fake_factory(factory_config: object) -> FakeChatModel:
        captured.append(factory_config)
        return FakeChatModel()

    provider = OpenAICompatibleProvider(config=config, model_factory=fake_factory)

    provider.create_diagnostic_model(timeout_seconds=30)
    provider.create_chat_model()

    assert cast(Any, captured[0]).max_retries == 0
    assert cast(Any, captured[1]) is config
    assert config.max_retries == 2


def _write_config(
    tmp_path: Path,
    *,
    api_key: str,
    base_url: str = "https://api.deepseek.com/v1",
    chat_model: str = "deepseek-flash",
    embedding_model: str = "text-embedding-v4",
    embedding_dimensions: int = 1024,
    embedding_base_url: str | None = None,
    embedding_api_key: str | None = None,
    rerank_model: str = "qwen3-vl-rerank",
    rerank_url: str = "https://example.test/rerank",
    rerank_api_key: str | None = None,
    context_window_tokens: int = 1_048_576,
    temperature: float = 0.2,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> Path:
    llm: dict[str, object] = {
        "provider": "deepseek-openai",
        "apiKey": api_key,
        "baseUrl": base_url,
        "chatModel": chat_model,
        "embeddingModel": embedding_model,
        "embeddingDimensions": embedding_dimensions,
        "rerankModel": rerank_model,
        "rerankUrl": rerank_url,
        "modelCapabilities": {chat_model: {"contextWindowTokens": context_window_tokens}},
        "temperature": temperature,
        "timeoutSeconds": timeout_seconds,
        "maxRetries": max_retries,
    }
    for key, value in {
        "embeddingBaseUrl": embedding_base_url,
        "embeddingApiKey": embedding_api_key,
        "rerankApiKey": rerank_api_key,
    }.items():
        if value is not None:
            llm[key] = value
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps({"llm": llm}), encoding="utf-8")
    return config_path
