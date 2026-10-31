"""
ai/prose_rewriter.py
====================
Layer 3: AI Prose Rewriting via Ollama.

Generates natural, context-aware sentence and paragraph updates for confirmed
documentation drift issues using local Ollama LLMs.
"""

from typing import Optional

from detectors import CodeChange
from .ollama_client import OllamaClient


SYSTEM_PROMPT = """You are an expert technical writer and software documentation editor.
Your job is to rewrite a documentation sentence so it accurately reflects a recent code change in a Pull Request.

Strict Rules:
1. Preserve the original author's exact tone, formatting, and markdown tags (e.g. backticks ``, bold **, list markers -).
2. ONLY update the fact, default number, flag name, or parameter that changed in the code.
3. Keep the sentence concise and natural.
4. Output ONLY the rewritten sentence without quotes, explanations, or markdown code fences."""


class ProseRewriter:
    """Generates natural documentation sentence rewrites using local Ollama LLMs."""

    def __init__(self, client: Optional[OllamaClient] = None):
        self.client = client or OllamaClient()

    def rewrite_sentence(
        self,
        sentence: str,
        change: CodeChange,
        model: Optional[str] = None
    ) -> Optional[str]:
        """
        Uses Ollama to generate a fluent rewrite of the outdated sentence.
        """
        if not self.client.is_available():
            return None

        diff_summary = ""
        if change.old_value is not None and change.new_value is not None:
            diff_summary = f"- Old value/signature: {change.old_value}\n- New value/signature: {change.new_value}"
        elif change.old_name is not None and change.new_name is not None:
            diff_summary = f"- Old name: {change.old_name}\n- New name: {change.new_name}"

        user_content = (
            f"Original documentation sentence:\n"
            f"\"{sentence}\"\n\n"
            f"Code Change in {change.file}:{change.line} ({change.change_type}):\n"
            f"- Identifier: {change.name}\n"
            f"{diff_summary}\n\n"
            f"Updated sentence:"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        rewritten = self.client.chat(messages, model=model, temperature=0.1)
        if not rewritten:
            return None

        # Clean up any surrounding quotes or backticks if LLM added them
        cleaned = rewritten.strip()
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()

        return cleaned if cleaned else None
