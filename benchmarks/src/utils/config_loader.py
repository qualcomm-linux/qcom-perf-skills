"""
config_loader.py - Robust YAML parser and configuration loader
Includes standard PyYAML loading with a clean, stdlib-only fallback parser.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from pathlib import Path
from typing import Any, Dict

def parse_simple_yaml(content: str) -> Dict[str, Any]:
    """
    A lightweight, stdlib-only fallback YAML parser that handles:
    - Key-value pairs (e.g. port: COM7)
    - Indented nested dictionaries
    - List of strings/items (e.g. - coremark)
    - Comments and blank lines
    """
    result: Dict[str, Any] = {}
    lines = content.splitlines()
    
    # Track current nesting stack
    stack = [( -1, result)]
    
    for line_num, line in enumerate(lines):
        # Strip comments
        if "#" in line:
            line = line.split("#", 1)[0]
            
        stripped = line.strip()
        if not stripped:
            continue
            
        # Calculate indentation level
        indent = len(line) - len(line.lstrip())
        
        # Pop stack until we find the parent level
        while stack and stack[-1][0] >= indent:
            stack.pop()
            
        if not stack:
            # Fallback to root if stack gets corrupted
            stack = [(-1, result)]
            
        _, parent_dict = stack[-1]
        
        # Handle list items
        if stripped.startswith("- "):
            val = stripped[2:].strip()
            # If parent is not a list, turn its key into a list or initialize it
            # For simplicity, if we see a list, we'll append to a list in the parent
            list_key = "_list"
            if list_key not in parent_dict:
                parent_dict[list_key] = []
            parent_dict[list_key].append(val)
            continue
            
        # Handle key-value pairs
        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            
            # Remove optional quotes
            if val.startswith(('"', "'")) and val.endswith(('"', "'")) and len(val) >= 2:
                val = val[1:-1]
                
            # Type conversions
            if val.lower() == "true":
                typed_val: Any = True
            elif val.lower() == "false":
                typed_val = False
            elif val.lower() == "none" or val == "":
                typed_val = None
            else:
                try:
                    if "." in val:
                        typed_val = float(val)
                    else:
                        typed_val = int(val)
                except ValueError:
                    typed_val = val
                    
            if val == "":
                # Nested dict starts
                new_dict: Dict[str, Any] = {}
                parent_dict[key] = new_dict
                stack.append((indent, new_dict))
            else:
                parent_dict[key] = typed_val
                
    # Post-process to flatten any single-key "_list" fields
    def flatten_lists(d: Dict[str, Any]):
        for k, v in list(d.items()):
            if isinstance(v, dict):
                flatten_lists(v)
                if "_list" in v and len(v) == 1:
                    d[k] = v["_list"]
            elif k == "_list":
                pass
        if "_list" in d and len(d) > 1:
            # Merge list under parent key
            pass
            
    flatten_lists(result)
    return result

def load_yaml_config(file_path: Path) -> Dict[str, Any]:
    """
    Load a YAML configuration file.
    Prefers PyYAML (yaml) if installed, otherwise falls back to our robust internal parser.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
        
    content = path.read_text(encoding="utf-8")
    
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        # Fallback to our custom simple parser
        return parse_simple_yaml(content)