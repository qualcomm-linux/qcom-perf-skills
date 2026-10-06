#!/usr/bin/env python3
"""
git_manager.py - Git Operations Manager

Handles all git-related operations:
- Check branch status (clean/dirty)
- Get recent commits
- Get changed files per commit
- Extract commit metadata

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import subprocess
import os
from typing import List, Tuple, Dict, Optional
from pathlib import Path


class GitManager:
    """Manages git operations for the update-doc skill"""
    
    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize GitManager
        
        Args:
            repo_root: Root directory of git repository (default: auto-detect)
        """
        if repo_root is None:
            # Auto-detect repo root
            self.repo_root = self._find_repo_root()
        else:
            self.repo_root = Path(repo_root)
        
        if not self._is_git_repo():
            raise ValueError(f"Not a git repository: {self.repo_root}")
    
    def _find_repo_root(self) -> Path:
        """Find git repository root by walking up directory tree"""
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        raise ValueError("Not inside a git repository")
    
    def _is_git_repo(self) -> bool:
        """Check if directory is a git repository"""
        return (self.repo_root / ".git").exists()
    
    def _run_git_command(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """
        Run a git command
        
        Args:
            args: Git command arguments (e.g., ['status', '--porcelain'])
            check: Whether to raise exception on non-zero exit code
            
        Returns:
            CompletedProcess object with stdout, stderr, returncode
        """
        cmd = ['git'] + args
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=check
        )
        return result
    
    def check_git_status(self) -> Dict[str, any]:
        """
        Check if working directory is clean
        
        Returns:
            Dict with 'status' ('clean' or 'dirty') and optional 'message'
        """
        result = self._run_git_command(['status', '--porcelain'])
        
        if result.stdout.strip():
            return {
                "status": "dirty",
                "message": "Working directory has uncommitted changes",
                "files": result.stdout.strip().split('\n')
            }
        
        return {"status": "clean"}
    
    def get_commits_since(self, last_commit_id: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Get all commits since last processed commit
        
        Args:
            last_commit_id: Last processed commit ID (None = get all commits)
            
        Returns:
            List of (commit_id, commit_message) tuples
        """
        if last_commit_id is None:
            # First run - get all commits
            args = ['log', '--oneline', '--reverse']
        else:
            # Incremental - get commits after last processed
            args = ['log', f'{last_commit_id}..HEAD', '--oneline', '--reverse']
        
        result = self._run_git_command(args)
        
        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split(' ', 1)
            if len(parts) == 2:
                commit_id, message = parts
                commits.append((commit_id, message))
            elif len(parts) == 1:
                # Commit with no message
                commits.append((parts[0], ""))
        
        return commits
    
    def get_changed_files(self, commit_id: str, filter_path: str = "aibench/") -> List[str]:
        """
        Get files changed in a specific commit
        
        Args:
            commit_id: Commit ID to analyze
            filter_path: Only return files under this path (default: aibench/)
            
        Returns:
            List of changed file paths
        """
        args = ['show', '--name-only', '--pretty=format:', commit_id]
        result = self._run_git_command(args)
        
        files = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # Filter for Python files in aibench/ folder
            if line.startswith(filter_path) and line.endswith('.py'):
                files.append(line)
        
        return files
    
    def get_commit_message(self, commit_id: str) -> str:
        """
        Get commit message for a specific commit
        
        Args:
            commit_id: Commit ID
            
        Returns:
            Commit message
        """
        args = ['log', '-1', '--pretty=format:%s', commit_id]
        result = self._run_git_command(args)
        return result.stdout.strip()
    
    def get_commit_diff(self, commit_id: str, file_path: str) -> str:
        """
        Get diff for a specific file in a commit
        
        Args:
            commit_id: Commit ID
            file_path: Path to file
            
        Returns:
            Diff output
        """
        args = ['show', f'{commit_id}:{file_path}']
        result = self._run_git_command(args, check=False)
        
        if result.returncode != 0:
            return ""
        
        return result.stdout
    
    def get_current_commit(self) -> str:
        """
        Get current HEAD commit ID
        
        Returns:
            Current commit ID
        """
        args = ['rev-parse', 'HEAD']
        result = self._run_git_command(args)
        return result.stdout.strip()
    
    def commit_exists(self, commit_id: str) -> bool:
        """
        Check if a commit exists in the repository
        
        Args:
            commit_id: Commit ID to check
            
        Returns:
            True if commit exists, False otherwise
        """
        args = ['cat-file', '-t', commit_id]
        result = self._run_git_command(args, check=False)
        return result.returncode == 0


# Example usage
if __name__ == "__main__":
    # Test GitManager
    git_mgr = GitManager()
    
    print("Git Repository Root:", git_mgr.repo_root)
    
    # Check status
    status = git_mgr.check_git_status()
    print(f"\nGit Status: {status['status']}")
    if status['status'] == 'dirty':
        print(f"Message: {status['message']}")
        print(f"Files: {status['files']}")
    
    # Get current commit
    current_commit = git_mgr.get_current_commit()
    print(f"\nCurrent Commit: {current_commit}")
    
    # Get recent commits (last 5)
    commits = git_mgr.get_commits_since(None)
    print(f"\nTotal Commits: {len(commits)}")
    print("Last 5 commits:")
    for commit_id, message in commits[-5:]:
        print(f"  {commit_id}: {message}")
        
        # Get changed files
        files = git_mgr.get_changed_files(commit_id)
        if files:
            print(f"    Changed files: {files}")