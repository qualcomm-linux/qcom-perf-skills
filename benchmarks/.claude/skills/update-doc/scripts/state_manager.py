#!/usr/bin/env python3
"""
state_manager.py - State Persistence Manager

Manages persistent state for the update-doc skill:
- Load/save commit_tracker.json
- Track processed commits
- Maintain update history
- Handle state file corruption

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class StateManager:
    """Manages persistent state for commit tracking"""
    
    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize StateManager
        
        Args:
            state_file: Path to commit_tracker.json (default: auto-detect)
        """
        if state_file is None:
            # Auto-detect state file location
            skill_dir = Path(__file__).parent.parent
            self.state_file = skill_dir / "state" / "commit_tracker.json"
        else:
            self.state_file = Path(state_file)
        
        # Ensure state directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize state
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """
        Load state from file
        
        Returns:
            State dictionary
        """
        if not self.state_file.exists():
            # First run - create empty state
            return {
                "last_processed_commit": None,
                "last_update_timestamp": None,
                "documentation_version": "1.0",
                "sections_updated": [],
                "update_history": []
            }
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            return state
        except json.JSONDecodeError as e:
            print(f"WARNING: State file corrupted: {e}")
            print("Creating new state file...")
            return {
                "last_processed_commit": None,
                "last_update_timestamp": None,
                "documentation_version": "1.0",
                "sections_updated": [],
                "update_history": []
            }
    
    def _save_state(self):
        """Save state to file"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def get_last_processed_commit(self) -> Optional[str]:
        """
        Get last processed commit ID
        
        Returns:
            Commit ID or None if first run
        """
        return self.state.get("last_processed_commit")
    
    def update_state(self, commit_id: str, changed_files: List[str], 
                    sections_affected: List[str]):
        """
        Update state with new processed commit
        
        Args:
            commit_id: Commit ID that was processed
            changed_files: List of files changed in this commit
            sections_affected: List of Architecture.md sections updated
        """
        # Update last processed commit
        self.state["last_processed_commit"] = commit_id
        self.state["last_update_timestamp"] = datetime.now().isoformat()
        
        # Update sections list (unique)
        for section in sections_affected:
            if section not in self.state["sections_updated"]:
                self.state["sections_updated"].append(section)
        
        # Add to history
        history_entry = {
            "commit_id": commit_id,
            "timestamp": datetime.now().isoformat(),
            "files_changed": changed_files,
            "sections_affected": sections_affected,
            "status": "success"
        }
        self.state["update_history"].append(history_entry)
        
        # Keep only last 100 entries
        if len(self.state["update_history"]) > 100:
            self.state["update_history"] = self.state["update_history"][-100:]
        
        # Save to file
        self._save_state()
    
    def get_update_history(self, limit: int = 10) -> List[Dict]:
        """
        Get recent update history
        
        Args:
            limit: Number of recent entries to return
            
        Returns:
            List of history entries
        """
        history = self.state.get("update_history", [])
        return history[-limit:]
    
    def reset_state(self):
        """Reset state (for --force-full-scan)"""
        self.state = {
            "last_processed_commit": None,
            "last_update_timestamp": None,
            "documentation_version": "1.0",
            "sections_updated": [],
            "update_history": []
        }
        self._save_state()
    
    def get_sections_updated(self) -> List[str]:
        """
        Get list of sections that have been updated
        
        Returns:
            List of section numbers
        """
        return self.state.get("sections_updated", [])
    
    def get_last_update_timestamp(self) -> Optional[str]:
        """
        Get timestamp of last update
        
        Returns:
            ISO8601 timestamp or None
        """
        return self.state.get("last_update_timestamp")
    
    def add_error_entry(self, commit_id: str, error_message: str):
        """
        Add error entry to history
        
        Args:
            commit_id: Commit ID that failed
            error_message: Error message
        """
        error_entry = {
            "commit_id": commit_id,
            "timestamp": datetime.now().isoformat(),
            "files_changed": [],
            "sections_affected": [],
            "status": "error",
            "error_message": error_message
        }
        self.state["update_history"].append(error_entry)
        
        # Keep only last 100 entries
        if len(self.state["update_history"]) > 100:
            self.state["update_history"] = self.state["update_history"][-100:]
        
        self._save_state()
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about state
        
        Returns:
            Dictionary with statistics
        """
        history = self.state.get("update_history", [])
        
        total_updates = len(history)
        successful_updates = sum(1 for h in history if h.get("status") == "success")
        failed_updates = sum(1 for h in history if h.get("status") == "error")
        
        return {
            "total_updates": total_updates,
            "successful_updates": successful_updates,
            "failed_updates": failed_updates,
            "last_processed_commit": self.state.get("last_processed_commit"),
            "last_update_timestamp": self.state.get("last_update_timestamp"),
            "sections_updated_count": len(self.state.get("sections_updated", []))
        }


# Example usage
if __name__ == "__main__":
    # Test StateManager
    state_mgr = StateManager()
    
    print("State File:", state_mgr.state_file)
    print("\nCurrent State:")
    print(json.dumps(state_mgr.state, indent=2))
    
    # Get last processed commit
    last_commit = state_mgr.get_last_processed_commit()
    print(f"\nLast Processed Commit: {last_commit or 'None (first run)'}")
    
    # Get statistics
    stats = state_mgr.get_statistics()
    print("\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Get recent history
    history = state_mgr.get_update_history(limit=5)
    print(f"\nRecent History ({len(history)} entries):")
    for entry in history:
        print(f"  {entry['commit_id']}: {entry['status']} - {entry.get('sections_affected', [])}")