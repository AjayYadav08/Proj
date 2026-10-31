"""Utility modules for Documentation Drift Detector.
"""
from .diff_parser import parse_diff, get_git_diff, FileDiff, DiffLine, DiffHunk
from .doc_finder import find_documentation_files, search_name_in_docs, DocMatch
from .reporter import DriftReporter

__all__ = [
    "parse_diff",
    "get_git_diff",
    "FileDiff",
    "DiffLine",
    "DiffHunk",
    "find_documentation_files",
    "search_name_in_docs",
    "DocMatch",
    "DriftReporter",
]

