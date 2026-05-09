import base64
import io
import logging
import os
import re

import backoff
from openai import APIConnectionError, APIError, OpenAI, RateLimitError

from browseruse_bench.utils import load_eval_config

logger = logging.getLogger(__name__)

# Load eval configuration (returns {} if file missing — all .get() have fallbacks)
_EVAL_CFG = load_eval_config("Online-Mind2Web")
_MODEL_CFG = _EVAL_CFG


def encode_image(image):
    """Convert a PIL image to base64 string."""
    if image.mode == "RGBA":
        image = image.convert("RGB")
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def extract_predication(response, mode):
    """Extract binary success/failure from WebJudge response."""
    try:
        status_segment = response.lower().split('status:')[1]
        return 1 if "success" in status_segment else 0
    except Exception:
        return 0


def extract_failure_category(response: str) -> str | None:
    """Extract failure category (e.g., A1, A2, B1...) from WebJudge response.

    The evaluator prompt formats failure output as:
        Failure Category: <A1|A2|B1|...>

    Returns:
        The failure category string if found, otherwise None.
    """
    try:
        # Case-insensitive search for "Failure Category: X"
        match = re.search(r"Failure Category\s*:\s*([A-Za-z0-9_-]+)", response, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None


def extract_reasoning(response: str) -> str | None:
    """Extract the Reasoning/Thoughts block from evaluator response."""
    try:
        patterns = [
            r"Reasoning\s*:\s*(.+?)(?:\n(?:Category|Status)\s*:|$)",
            r"Thoughts\s*:\s*(.+?)(?:\nStatus\s*:|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
    except Exception:
        pass
    return None


class OpenaiEngine:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        stop=None,
        rate_limit: int = -1,
        model: str | None = None,
        tokenizer=None,
        temperature: float = 0,
        port: int = -1,
        endpoint_target_uri: str = "",
        **kwargs,
    ) -> None:
        """Init an OpenAI GPT/Codex engine

        Args:
            api_key: Auth key from OpenAI. Defaults to None.
            stop: Tokens indicate stop of sequence. Defaults to ["\n"].
            rate_limit: Max number of requests per minute. Defaults to -1.
            model: Model family. Defaults to None.
        """
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
        if api_key is None:
            raise ValueError("must pass api_key or set OPENAI_API_KEY in the environment")
        self.api_keys = [api_key]

        if base_url is None:
            base_url = os.getenv("OPENAI_BASE_URL", None)

        self.stop = stop if stop is not None else []
        self.temperature = temperature
        self.model = model
        # convert rate limit to minmum request interval
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.next_avil_time = [0] * len(self.api_keys)
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.last_usage = None

    @staticmethod
    def _log_error(details: dict) -> None:  # type: ignore[type-arg]
        logger.warning(
            f"Retrying in {details['wait']:0.1f} seconds due to {details['exception']}"
        )

    @backoff.on_exception(
        backoff.expo,
        (APIError, RateLimitError, APIConnectionError),
        max_tries=_MODEL_CFG.get("max_tries", 3),
        on_backoff=_log_error.__func__,  # type: ignore[attr-defined]
    )
    def generate(
        self,
        messages,
        max_new_tokens=None,
        temperature=None,
        model: str | None = None,
        **kwargs,
    ):
        if max_new_tokens is None:
            max_new_tokens = _MODEL_CFG.get("max_new_tokens") or _MODEL_CFG.get("max_tokens", 512)
        if temperature is None:
            temperature = self.temperature if self.temperature is not None else _MODEL_CFG.get("temperature", 0)
        resolved_model = model or self.model or ""
        response = self.client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            max_tokens=max_new_tokens,
            temperature=temperature,
            **kwargs,
        )
        self.last_usage = getattr(response, "usage", None)
        return [choice.message.content for choice in response.choices]

