"""LLM Provider abstraction for Phase 13 AI Explanation Layer.

Defines the base interface and concrete provider implementations (Gemini, Mock).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import json
import os
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMProviderError(Exception):
    """Raised when an LLM provider fails during invocation."""

    pass


class LLMTimeoutError(LLMProviderError):
    """Raised when an LLM call exceeds the configured timeout."""

    pass


class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'gemini', 'mock')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the underlying model (e.g. 'gemini-2.5-flash', 'mock-v1')."""
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a response text from the LLM given a prompt and system prompt.

        Returns raw output string (expected to be JSON format).
        """
        pass


class MockLLMProvider(BaseLLMProvider):
    """Deterministic Mock LLM Provider for testing and local development without API keys."""

    def __init__(
        self,
        model_name: str = "mock-financial-explainer-v1",
        custom_response: Optional[str] = None,
        simulate_error: Optional[str] = None,
        simulate_timeout: bool = False,
    ):
        self._model_name = model_name
        self.custom_response = custom_response
        self.simulate_error = simulate_error
        self.simulate_timeout = simulate_timeout

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if self.simulate_timeout:
            raise LLMTimeoutError("Mock provider simulated timeout")

        if self.simulate_error:
            raise LLMProviderError(f"Mock provider error: {self.simulate_error}")

        if self.custom_response:
            return self.custom_response

        # Check if chat response is expected (plain text)
        if "plain text" in system_prompt.lower():
            return "Based on your verified financial records, the deterministic analysis evaluates the cash flow impact and liquidity status for this scenario."

        # Default mock deterministic response payload for JSON explain requests
        mock_payload = {
            "summary": "This scenario evaluation demonstrates the financial impact based on your historical records.",
            "cash_flow_impact_narrative": "Historical baseline cash flow and projected scenario cash flow have been evaluated deterministically.",
            "liquidity_narrative": "Liquidity evaluation reflects the verified account balances on file.",
            "key_tradeoffs": [
                "Evaluates current period liquidity against future obligations.",
                "Considers historical savings rate relative to the scenario amount."
            ],
            "data_limitations_noted": [
                "Analysis is restricted strictly to verified transaction records."
            ]
        }
        return json.dumps(mock_payload)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API provider implementation using the official google-genai SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        if api_key is not None:
            self._api_key = api_key
        else:
            self._api_key = (
                settings.gemini_api_key
                or settings.llm_api_key
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("LLM_API_KEY")
                or ""
            )
        raw_model = model_name or settings.llm_model or os.getenv("LLM_MODEL") or "gemini-3.5-flash"
        raw_model_str = str(raw_model).strip()
        if not raw_model_str or raw_model_str in ("...", "<Gemini model>", "None", "", "gpt-4o-mini", "gemini-flash-latest"):
            raw_model_str = "gemini-3.5-flash"
        self._model_name = raw_model_str
        self._timeout = timeout_seconds or settings.llm_timeout_seconds
        self._client = None


    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_client(self):
        if not self._api_key:
            raise LLMProviderError("Gemini API key is not configured.")
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except ImportError as e:
                raise LLMProviderError(f"google-genai package is not installed: {e}")
            except Exception as e:
                raise LLMProviderError(f"Failed to initialize Gemini client: {e}")
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else settings.llm_temperature
        tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=temp,
                max_output_tokens=tokens,
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "summary": {"type": "STRING"},
                        "cash_flow_impact_narrative": {"type": "STRING"},
                        "liquidity_narrative": {"type": "STRING"},
                        "key_tradeoffs": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        },
                        "data_limitations_noted": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        }
                    },
                    "required": [
                        "summary",
                        "cash_flow_impact_narrative",
                        "liquidity_narrative",
                        "key_tradeoffs",
                        "data_limitations_noted"
                    ]
                }
            )

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                ),
                timeout=float(self._timeout),
            )

            content = response.text or "{}"
            return content
        except asyncio.TimeoutError:
            logger.warning("Gemini request timed out after %s seconds", self._timeout)
            raise LLMTimeoutError(f"Gemini call timed out after {self._timeout}s")
        except Exception as e:
            logger.error("Gemini API call failed: %s", e)
            raise LLMProviderError(f"Gemini API error: {str(e)}")


def get_llm_provider() -> Optional[BaseLLMProvider]:
    """Factory to retrieve configured LLM provider or None if disabled."""
    provider_type = (settings.llm_provider or "none").lower().strip()
    if provider_type == "gemini":
        return GeminiProvider()
    elif provider_type == "mock":
        return MockLLMProvider()
    elif provider_type in ("none", "", "disabled"):
        return None
    else:
        logger.warning("Unknown LLM provider '%s'. Disabling AI explanation layer.", provider_type)
        return None
