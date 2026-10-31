"""
ai
==
AI-Powered Semantic Verification and Prose Rewriting module.
Integrates with local Ollama daemon (e.g. Llama 3.2, Mistral).
"""

from .ollama_client import OllamaClient
from .semantic_verifier import SemanticVerifier, VerificationResult
from .prose_rewriter import ProseRewriter

__all__ = [
    "OllamaClient",
    "SemanticVerifier",
    "VerificationResult",
    "ProseRewriter",
]

