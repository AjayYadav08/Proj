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
You compare a code change against a documentation sentence to check if the documentation is now factually outdated.

Rules:
1. If the documentation mentions an old value (e.g. '30 seconds') but the code changed it (e.g. to '60'), this is DRIFT: return {"is_drift": true, ...}.
2. If the documentation mentions an old flag (e.g. '--legacy-auth') or deleted function, this is DRIFT: return {"is_drift": true, ...}.
3. If the documentation does not contradict the code change, return {"is_drift": false, ...}.

Always respond in valid JSON format:
{
  "is_drift": boolean,
  "confidence": float (between 0.0 and 1.0),
  "reasoning": "1-sentence explanation of why this is or is not drift",
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
            f"Code Change: Identifier '{change.name}' {diff_summary} in {change.file}:{change.line}.\n"
            f"Documentation Sentence: \"{match.sentence}\"\n\n"
            f"Does this documentation sentence contain factually outdated information based on this code change? Respond in JSON:"
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

