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


SYSTEM_PROMPT = """You are an expert technical documentation editor.
Your job is to update a single documentation sentence so it accurately reflects a code change.

Strict Rules:
1. Replace ONLY the outdated value, flag name, or parameter with the new one from the code change.
2. Preserve the author's tone, formatting, and markdown (backticks ``, bold **, list markers -).
3. Do NOT output code blocks, markdown headers, or multiple lines.
4. Do NOT add explanations, commentary, or filler text.
5. Output ONLY the single updated sentence — nothing else."""


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
            f"Original sentence: \"{sentence}\"\n"
            f"Code Change: '{change.name}' {diff_summary} in {change.file}:{change.line}.\n"
            f"Write ONLY the corrected sentence (no code blocks, no extra lines):"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        rewritten = self.client.chat(messages, model=model, temperature=0.1)
        if not rewritten:
            return None

        # Clean up surrounding quotes the LLM may have added
        cleaned = rewritten.strip()
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()

        # If LLM returned a code block, extract first usable line
        if "```" in cleaned:
            lines = [ln for ln in cleaned.splitlines() if ln.strip() and not ln.strip().startswith("```")]
            cleaned = lines[0].strip() if lines else ""

        # If LLM returned multiple lines, take only the first (the sentence itself)
        if "\n" in cleaned:
            cleaned = cleaned.splitlines()[0].strip()

        return cleaned if cleaned else None

