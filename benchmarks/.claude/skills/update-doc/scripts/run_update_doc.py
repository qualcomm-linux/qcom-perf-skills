#!/usr/bin/env python3
"""
run_update_doc.py - Entry Point for update-doc Skill

Wrapper script for skill invocation. Handles CLI arguments and calls main orchestrator.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import argparse
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from git_manager import GitManager
from state_manager import StateManager


def run_update_doc(force_full_scan=False, commits_to_process=0):
    """
    Main entry point for update-doc skill
    
    Args:
        force_full_scan: Force full scan ignoring commit history
        commits_to_process: Number of recent commits to process (0 = all new)
        
    Returns:
        Dict with execution results
    """
    print("=" * 60)
    print("Update Documentation Skill")
    print("=" * 60)
    
    try:
        # Initialize managers
        print("\n[1/7] Initializing managers...")
        git_mgr = GitManager()
        state_mgr = StateManager()
        
        print(f"  Repository: {git_mgr.repo_root}")
        print(f"  State file: {state_mgr.state_file}")
        
        # Check git status
        print("\n[2/7] Checking git status...")
        git_status = git_mgr.check_git_status()
        
        if git_status["status"] == "dirty":
            print(f"  ✗ ERROR: {git_status['message']}")
            print(f"  Files with changes:")
            for file in git_status.get("files", []):
                print(f"    - {file}")
            print("\n  Please commit or stash changes before running update-doc")
            return {
                "status": "error",
                "message": git_status["message"]
            }
        
        print("  ✓ Working directory is clean")
        
        # Load state
        print("\n[3/7] Loading state...")
        if force_full_scan:
            print("  Force full scan requested - resetting state")
            state_mgr.reset_state()
            last_commit = None
        else:
            last_commit = state_mgr.get_last_processed_commit()
        
        print(f"  Last processed commit: {last_commit or 'None (first run)'}")
        
        # Get recent commits
        print("\n[4/7] Getting recent commits...")
        commits = git_mgr.get_commits_since(last_commit)
        
        if commits_to_process > 0:
            commits = commits[:commits_to_process]
        
        print(f"  Found {len(commits)} new commits to process")
        
        if not commits:
            print("\n✓ No new commits to process - documentation is up to date")
            return {
                "status": "success",
                "commits_processed": 0,
                "message": "Already up to date"
            }
        
        # Display commits
        print("\n  Commits to process:")
        for commit_id, message in commits[:5]:  # Show first 5
            print(f"    {commit_id}: {message}")
        if len(commits) > 5:
            print(f"    ... and {len(commits) - 5} more")
        
        # Process commits (placeholder - full implementation in main.py)
        print("\n[5/7] Analyzing code changes...")
        print("  NOTE: Full code analysis not yet implemented")
        print("  This is a skeleton implementation showing the workflow")
        
        total_files_changed = 0
        for commit_id, message in commits:
            files = git_mgr.get_changed_files(commit_id)
            total_files_changed += len(files)
            if files:
                print(f"  {commit_id}: {len(files)} files changed")
        
        print(f"\n  Total files changed: {total_files_changed}")
        
        # Generate documentation (placeholder)
        print("\n[6/7] Generating documentation...")
        print("  NOTE: Documentation generation not yet implemented")
        
        # Update state
        print("\n[7/7] Updating state...")
        if commits:
            last_commit_id = commits[-1][0]
            state_mgr.update_state(
                commit_id=last_commit_id,
                changed_files=[],
                sections_affected=[]
            )
            print(f"  ✓ State updated with commit: {last_commit_id}")
        
        # Summary
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"  Commits processed: {len(commits)}")
        print(f"  Files analyzed: {total_files_changed}")
        print(f"  Status: Success")
        
        # Statistics
        stats = state_mgr.get_statistics()
        print("\n  State Statistics:")
        print(f"    Total updates: {stats['total_updates']}")
        print(f"    Successful: {stats['successful_updates']}")
        print(f"    Failed: {stats['failed_updates']}")
        
        return {
            "status": "success",
            "commits_processed": len(commits),
            "files_analyzed": total_files_changed,
            "sections_updated": [],
            "state_file_updated": True
        }
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e)
        }


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Update Architecture.md based on recent git commits",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--force-full-scan",
        action="store_true",
        help="Force full scan ignoring commit history"
    )
    
    parser.add_argument(
        "--commits-to-process",
        type=int,
        default=0,
        help="Number of recent commits to process (0 = all new)"
    )
    
    args = parser.parse_args()
    
    result = run_update_doc(
        force_full_scan=args.force_full_scan,
        commits_to_process=args.commits_to_process
    )
    
    # Exit with appropriate code
    if result["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()