"""LangChain adapter for Kimi's OpenAI-compatible Chat Completions API.

Kimi K3 requires the complete assistant message, including
``reasoning_content``, to be sent back on later tool-call turns.  ChatOpenAI
intentionally drops provider-specific response fields, so a plain ChatOpenAI
client can complete the first tool call and then fail on the second request.
This small adapter preserves the field without exposing it as normal message
content.
"""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


_KIMI_ASSISTANT_FIELDS = (
    # Kimi's reference API calls this ``reasoning_content``; the local
    # OpenAI-compatible server in this deployment emits ``reasoning`` instead.
    "reasoning_content",
    "reasoning",
    "reasoning_details",
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(warnings=False)
        except TypeError:  # Older OpenAI/Pydantic releases lack ``warnings``.
            return model_dump()
    return {}


def _provider_field(message: Any, field: str) -> Any:
    data = _as_mapping(message)
    if field in data:
        return data[field]
    extra = getattr(message, "model_extra", None)
    if isinstance(extra, Mapping) and field in extra:
        return extra[field]
    return getattr(message, field, None)


class KimiChatOpenAI(ChatOpenAI):
    """ChatOpenAI with lossless Kimi reasoning-history round trips."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        source_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # Kimi is served through Chat Completions.  Preserve its assistant-only
        # fields after ChatOpenAI has converted the LangChain messages.
        wire_messages = payload.get("messages")
        if isinstance(wire_messages, list):
            for source, wire in zip(source_messages, wire_messages):
                if not isinstance(source, AIMessage) or not isinstance(wire, dict):
                    continue
                for field in _KIMI_ASSISTANT_FIELDS:
                    if field in source.additional_kwargs:
                        wire[field] = source.additional_kwargs[field]
        return payload

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        response_data = _as_mapping(response)
        choices = response_data.get("choices") or []

        for index, generation in enumerate(result.generations):
            raw_message: Any = None
            typed_message: Any = None
            if index < len(choices):
                raw_choice = choices[index]
                raw_message = (
                    raw_choice.get("message")
                    if isinstance(raw_choice, Mapping)
                    else getattr(raw_choice, "message", None)
                )
            # OpenAI's typed object can retain provider extensions in
            # ``model_extra`` even when model_dump() omits them.
            typed_choices = getattr(response, "choices", None) or []
            if index < len(typed_choices):
                typed_message = getattr(typed_choices[index], "message", None)
            if raw_message is None:
                raw_message = typed_message

            for field in _KIMI_ASSISTANT_FIELDS:
                value = _provider_field(raw_message, field)
                if value is None and typed_message is not raw_message:
                    value = _provider_field(typed_message, field)
                if value is not None:
                    generation.message.additional_kwargs[field] = value
        return result

    def _convert_chunk_to_generation_chunk(
        self, chunk, default_chunk_class, base_generation_info
    ):
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation is None:
            return None

        choices = (chunk.get("choices") or []) if isinstance(chunk, dict) else []
        if choices:
            delta = choices[0].get("delta") or {}
            for field in _KIMI_ASSISTANT_FIELDS:
                if delta.get(field) is not None:
                    generation.message.additional_kwargs[field] = delta[field]
        return generation
