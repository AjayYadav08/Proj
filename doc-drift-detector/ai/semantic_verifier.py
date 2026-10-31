"""
ai/semantic_verifier.py
=======================
Layer 2: AI Semantic Verification via Ollama.

Evaluates candidate (code_change, doc_match) pairs using a local LLM to:
1. Verify whether the prose is genuinely out-of-date or merely mentions the feature.
2. Produce a clear, human-like explanation of WHY the documentation drifted.
3. Eliminate edge-case false positives that static rules might miss.
"""

from dataclasses import dataclass
import json
from typing import Optional, Tuple

from detectors import CodeChange
from utils.doc_finder import DocMatch
from .ollama_client import OllamaClient


@dataclass
class VerificationResult:
    is_drift: bool
    confidence: float
    reasoning: str
    suggested_action: str


SYSTEM_PROMPT = """You are an expert Documentation Drift Verification Agent.
Your job is to determine whether a given documentation sentence is rendered factually out-of-date,
misleading, or inaccurate because of a code change in a Pull Request.

Guidelines:
- Return is_drift=true ONLY if the documentation states a specific fact, default value, flag, or signature that has now changed.
- If the documentation is just a general conceptual description that remains true despite the code change, return is_drift=false.
- Respond ONLY with valid JSON conforming to this schema:
{
  "is_drift": boolean,
  "confidence": float (between 0.0 and 1.0),
  "reasoning": "Concise 1-sentence explanation of why this is or is not drift",
  "suggested_action": "Specific edit instruction if drifted"
}"""


class SemanticVerifier:
    """Verifies potential drift issues using Ollama LLM reasoning."""

    def __init__(self, client: Optional[OllamaClient] = None):
        self.client = client or OllamaClient()

    def verify_candidate(
        self,
        change: CodeChange,
        match: DocMatch,
        model: Optional[str] = None
    ) -> Optional[VerificationResult]:
        """
        Sends candidate drift pair to Ollama to verify if documentation genuinely drifted.
        """
        if not self.client.is_available():
            return None

        # Build context prompt
        diff_summary = ""
        if change.old_value is not None and change.new_value is not None:
            diff_summary = f"Changed from '{change.old_value}' to '{change.new_value}'"
        elif change.old_name is not None and change.new_name is not None:
            diff_summary = f"Renamed from '{change.old_name}' to '{change.new_name}'"

        user_content = (
            f"CODE CHANGE:\n"
            f"- File: {change.file}:{change.line}\n"
            f"- Change Type: {change.change_type}\n"
            f"- Name: {change.name}\n"
            f"- Details: {diff_summary}\n\n"
            f"DOCUMENTATION CONTEXT:\n"
            f"- File: {match.file_path}:{match.line_number}\n"
            f"- Text: \"{match.sentence}\"\n\n"
            f"Does this documentation sentence contain factually outdated information based on this code change?"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        response_text = self.client.chat(messages, model=model, json_format=True, temperature=0.1)
        if not response_text:
            return None

        try:
            data = json.loads(response_text)
            return VerificationResult(
                is_drift=bool(data.get("is_drift", False)),
                confidence=float(data.get("confidence", 0.8)),
                reasoning=str(data.get("reasoning", "")),
                suggested_action=str(data.get("suggested_action", ""))
            )
        except Exception:
            return None
