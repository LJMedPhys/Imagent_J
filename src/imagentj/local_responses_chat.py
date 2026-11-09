"""ChatOpenAI for a local OpenAI-compatible *Responses* endpoint (vLLM, SGLang).

vLLM validates every request body against the openai SDK's TypedDicts, and there
``ResponseInputImageParam.detail`` is ``Required``. OpenAI's own server treats a
missing ``detail`` as ``"auto"``; vLLM answers HTTP 400::

    1 validation error for ResponseInputImageParam
    detail
      Field required [type=missing, input_value={'type': 'input_image', ...}]

langchain-openai forwards ``detail`` only when the source block carried one
(``_convert_to_responses`` in chat_models/base.py). The app's own vision tools
always set ``detail: "high"`` and are fine. The deep-agent ``read_file`` tool is
not: it attaches an image as a plain ``{"type": "image", "base64": ...}`` block
with no detail, so the first time the general-purpose subagent "verifies" a PNG
by reading it, the very next model call is rejected and the exception unwinds
through the ``task`` tool into the supervisor, ending the whole turn as
"Agent error" (2026-09-11 12:08 UTC, cell_tracking_testset1).

Fixing it at the model boundary covers every source at once — user uploads,
tool results, ``function_call_output`` and ``computer_call_output`` items alike.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

# OpenAI's documented default for an omitted `detail`.
_DEFAULT_IMAGE_DETAIL = "auto"


def _fill_missing_image_detail(node: Any) -> None:
    """Recursively stamp ``detail`` onto every ``input_image`` block lacking one.

    Walks dicts and lists only; strings (including multi-MB base64 payloads) are
    leaves and never inspected. Mutates in place — the payload is freshly built
    per request, and a block that already carries a detail is left untouched.
    """
    if isinstance(node, dict):
        if node.get("type") == "input_image" and not node.get("detail"):
            node["detail"] = _DEFAULT_IMAGE_DETAIL
        for value in node.values():
            _fill_missing_image_detail(value)
    elif isinstance(node, list):
        for value in node:
            _fill_missing_image_detail(value)


def _drop_stale_reasoning(items: list) -> list:
    """Drop ``reasoning`` items that precede the last user message.

    OpenAI's server discards reasoning from earlier turns on its own. vLLM does
    not: Kimi K3's chat template renders every replayed reasoning item back into
    the prompt (measured 2026-11-04: a 2.6k-token stale reasoning item raised a
    two-turn prompt from 169 to 2,370 input tokens). On a long supervisor thread
    that was ~14k tokens of dead reasoning resent on every call. Reasoning inside
    the current turn's tool loop (after the last user message) is kept.
    """
    last_user = max(
        (i for i, item in enumerate(items)
         if isinstance(item, dict) and item.get("role") == "user"),
        default=-1,
    )
    return [
        item for i, item in enumerate(items)
        if i >= last_user
        or not (isinstance(item, dict) and item.get("type") == "reasoning")
    ]


class LocalResponsesChatOpenAI(ChatOpenAI):
    """ChatOpenAI whose Responses payloads satisfy vLLM's strict schema and
    carry no reasoning from earlier turns."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # Only the Responses API has an `input` list; Chat Completions payloads
        # carry `messages` and pass through untouched.
        if isinstance(payload.get("input"), list):
            _fill_missing_image_detail(payload["input"])
            payload["input"] = _drop_stale_reasoning(payload["input"])
        return payload
