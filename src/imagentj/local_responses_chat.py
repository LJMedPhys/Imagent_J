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


class LocalResponsesChatOpenAI(ChatOpenAI):
    """ChatOpenAI whose Responses payloads always satisfy vLLM's strict schema."""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # Only the Responses API has an `input` list; Chat Completions payloads
        # carry `messages` and pass through untouched.
        if isinstance(payload.get("input"), list):
            _fill_missing_image_detail(payload["input"])
        return payload
