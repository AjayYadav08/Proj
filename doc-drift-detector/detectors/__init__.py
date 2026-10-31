"""
detectors
=========
STEP 2: EXTRACT CODE CHANGES (semantic)

Contains specialized semantic detectors for:
- DEFAULT_VALUE_CHANGED: constants, kwargs, config keys, .env
- FLAG_RENAMED: CLI flags (--old-flag -> --new-flag) and config keys
- PARAM_CHANGED: function signature & default parameter modifications
- FEATURE_REMOVED: deleted functions/classes no longer in codebase
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CodeChange:
    """Represents a semantic code change detected in a PR diff."""
    change_type: str
    name: str
    file: str
    line: int
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    old_name: Optional[str] = None
    new_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert code change object to dictionary format."""
        data = {
            "type": self.change_type,
            "name": self.name,
            "file": self.file,
            "line": self.line,
        }
        if self.old_value is not None:
            data["old_value"] = self.old_value
        if self.new_value is not None:
            data["new_value"] = self.new_value
        if self.old_name is not None:
            data["old_name"] = self.old_name
        if self.new_name is not None:
            data["new_name"] = self.new_name
        if self.details:
            data["details"] = self.details
        return data


from .default_value import detect_default_values
from .flag_rename import detect_flag_renames
from .param_change import detect_param_changes
from .feature_remove import detect_feature_removals

__all__ = [
    "CodeChange",
    "detect_default_values",
    "detect_flag_renames",
    "detect_param_changes",
    "detect_feature_removals",
]

