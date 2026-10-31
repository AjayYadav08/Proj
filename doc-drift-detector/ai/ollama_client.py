"""
ai/ollama_client.py
===================
Lightweight, zero-dependency REST client for local Ollama instance.
Communicates directly with http://localhost:11434 (or OLLAMA_HOST).
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
PREFERRED_MODELS = [
    "llama3.2", "llama3.2:1b", "llama3.2:3b", "llama3.1",
    "llama3", "mistral", "qwen2.5", "qwen2.5-coder", "phi3"
]


class OllamaClient:
    """Zero-dependency HTTP client for interacting with a local Ollama daemon."""

    def __init__(self, host: str = DEFAULT_OLLAMA_HOST, timeout: float = 15.0):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._cached_available: Optional[bool] = None
        self._cached_models: Optional[List[str]] = None

    def is_available(self) -> bool:
        """Checks if the local Ollama server is running and responsive."""
        try:
            req = urllib.request.Request(
                f"{self.host}/api/tags",
                headers={"User-Agent": "DocDrift/1.0"}
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    self._cached_available = True
                    return True
        except Exception:
            pass
        self._cached_available = False
        return False

    def list_models(self) -> List[str]:
        """Returns list of model names downloaded in local Ollama."""
        if not self.is_available():
            return []
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                self._cached_models = models
                return models
        except Exception:
            return []

    def get_preferred_model(self) -> Optional[str]:
        """
        Determines the best available model on the user's Ollama instance.
        Prioritizes fast models: llama3.2 -> llama3 -> mistral -> first available.
        """
        installed = self.list_models()
        if not installed:
            return None

        # Check preferred list
        for preferred in PREFERRED_MODELS:
            for inst in installed:
                if inst == preferred or inst.startswith(f"{preferred}:"):
                    return inst

        # Return first installed model as fallback
        return installed[0]

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        json_format: bool = False,
        temperature: float = 0.1
    ) -> Optional[str]:
        """
        Executes a chat completion request to Ollama /api/chat.
        """
        active_model = model or self.get_preferred_model()
        if not active_model:
            return None

        payload: Dict[str, Any] = {
            "model": active_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        if json_format:
            payload["format"] = "json"

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.host}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                message = result.get("message", {})
                return message.get("content", "").strip()
        except Exception:
            return None

