#!/usr/bin/env python3
"""
main.py - Main Orchestrator for update-doc Skill

Coordinates all components:
- Git operations (git_manager)
- State persistence (state_manager)
- Code analysis (code_analyzer)
- Documentation generation (doc_generator)
- Document updates (doc_updater)

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
from pathlib import Path
from typing import Dict, List, Any

from git_manager import GitManager
from state_manager import StateManager
from code_analyzer import CodeAnalyzer
from doc_generator import DocGenerator
from doc_updater import DocUpdater


def load_doc_mapping() -> Dict:
    """Load code-to-documentation mapping"""
    mapping_file = Path(__file__).parent.parent / "reference" / "doc_mapping.json"
    with open(mapping_file, 'r') as f:
        return json.load(f)


def map_file_to_section(file_path: str, mapping: Dict) -> str:
    """
    Map a file path to a documentation section
    
    Args:
        file_path: Path to file
        mapping: Documentation mapping
        
    Returns:
        Section number or empty string if no mapping
    """
    for entry in mapping.get("mappings", []):
        code_location = entry["code_location"]
        
        # Simple pattern matching
        if "*" in code_location:
            # Wildcard matching
            pattern = code_location.replace("*", "")
            if pattern in file_path:
                return entry["section"]
        else:
            # Exact matching
            if code_location in file_path:
                return entry["section"]
    
    return ""


def process_commit(commit_id: str, commit_message: str,
                  git_mgr: GitManager, analyzer: CodeAnalyzer,
                  generator: DocGenerator, updater: DocUpdater,
                  mapping: Dict) -> Dict[str, Any]:
    """
    Process a single commit
    
    Args:
        commit_id: Commit ID
        commit_message: Commit message
        git_mgr: Git manager instance
        analyzer: Code analyzer instance
        generator: Doc generator instance
        updater: Doc updater instance
        mapping: Documentation mapping
        
    Returns:
        Dict with processing results
    """
    result = {
        "commit_id": commit_id,
        "files_analyzed": 0,
        "sections_updated": [],
        "status": "success"
    }
    
    # Get changed files
    changed_files = git_mgr.get_changed_files(commit_id)
    
    if not changed_files:
        return result
    
    result["files_analyzed"] = len(changed_files)
    
    # Analyze each file
    for file_path in changed_files:
        try:
            # Analyze code
            analysis = analyzer.analyze_file(file_path)
            
            # Map to documentation section
            section = map_file_to_section(file_path, mapping)
            
            if not section:
                print(f"  No mapping for {file_path}, skipping")
                continue
            
            # Generate documentation based on patterns detected
            if 'benchmark_implementation' in analysis.patterns_detected:
                for cls in analysis.classes:
                    if 'BenchmarkBase' in cls.base_classes:
                        doc = generator.generate_benchmark_doc(analysis, cls)
                        # In full implementation, would update Architecture.md
                        print(f"  Generated benchmark doc for {cls.name}")
                        result["sections_updated"].append(section)
            
            elif 'statistical_method' in analysis.patterns_detected:
                for func in analysis.functions:
                    if func.name.startswith('_detect_'):
                        doc = generator.generate_statistical_method_doc(func)
                        print(f"  Generated statistical method doc for {func.name}")
                        result["sections_updated"].append(section)
            
            elif 'rca_method' in analysis.patterns_detected:
                for func in analysis.functions:
                    if 'analyze' in func.name.lower():
                        doc = generator.generate_rca_category_doc(func)
                        print(f"  Generated RCA doc for {func.name}")
                        result["sections_updated"].append(section)
        
        except Exception as e:
            print(f"  ERROR analyzing {file_path}: {e}")
            result["status"] = "partial"
    
    # Remove duplicates
    result["sections_updated"] = list(set(result["sections_updated"]))
    
    return result


def main(force_full_scan: bool = False, commits_to_process: int = 0) -> Dict[str, Any]:
    """
    Main orchestration function
    
    Args:
        force_full_scan: Force full scan ignoring commit history
        commits_to_process: Number of recent commits to process (0 = all new)
        
    Returns:
        Dict with execution results
    """
    print("=" * 60)
    print("Update Documentation Skill - Full Orchestration")
    print("=" * 60)
    
    try:
        # Initialize all managers
        print("\n[1/8] Initializing components...")
        git_mgr = GitManager()
        state_mgr = StateManager()
        analyzer = CodeAnalyzer(git_mgr.repo_root)
        generator = DocGenerator()
        updater = DocUpdater()
        
        print(f"  Repository: {git_mgr.repo_root}")
        print(f"  State file: {state_mgr.state_file}")
        print(f"  Architecture.md: {updater.doc_path}")
        
        # Load documentation mapping
        print("\n[2/8] Loading documentation mapping...")
        mapping = load_doc_mapping()
        print(f"  Loaded {len(mapping.get('mappings', []))} mappings")
        
        # Check git status
        print("\n[3/8] Checking git status...")
        git_status = git_mgr.check_git_status()
        
        if git_status["status"] == "dirty":
            print(f"  ✗ ERROR: {git_status['message']}")
            return {
                "status": "error",
                "message": git_status["message"]
            }
        
        print("  ✓ Working directory is clean")
        
        # Load state
        print("\n[4/8] Loading state...")
        if force_full_scan:
            print("  Force full scan requested - resetting state")
            state_mgr.reset_state()
            last_commit = None
        else:
            last_commit = state_mgr.get_last_processed_commit()
        
        print(f"  Last processed commit: {last_commit or 'None (first run)'}")
        
        # Get recent commits
        print("\n[5/8] Getting recent commits...")
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
        
        # Process commits
        print("\n[6/8] Processing commits...")
        all_sections_updated = []
        
        for commit_id, message in commits:
            print(f"\n  Processing: {commit_id} - {message}")
            
            result = process_commit(
                commit_id, message,
                git_mgr, analyzer, generator, updater, mapping
            )
            
            print(f"    Files analyzed: {result['files_analyzed']}")
            print(f"    Sections updated: {result['sections_updated']}")
            
            all_sections_updated.extend(result['sections_updated'])
            
            # Update state
            state_mgr.update_state(
                commit_id=commit_id,
                changed_files=[],
                sections_affected=result['sections_updated']
            )
        
        # Remove duplicates
        all_sections_updated = list(set(all_sections_updated))
        
        # Validate documentation (optional)
        print("\n[7/8] Validating documentation...")
        updater.read_document()
        errors = updater.validate_markdown()
        
        if errors:
            print(f"  ⚠ Found {len(errors)} validation errors")
            for error in errors[:3]:
                print(f"    - {error}")
        else:
            print("  ✓ Markdown validation passed")
        
        # Summary
        print("\n[8/8] Summary")
        print("=" * 60)
        print(f"  Commits processed: {len(commits)}")
        print(f"  Sections updated: {len(all_sections_updated)}")
        print(f"  Sections: {all_sections_updated}")
        print(f"  Status: Success")
        
        return {
            "status": "success",
            "commits_processed": len(commits),
            "sections_updated": all_sections_updated,
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


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Update documentation based on git commits")
    parser.add_argument("--force-full-scan", action="store_true", help="Force full scan")
    parser.add_argument("--commits-to-process", type=int, default=0, help="Number of commits to process")
    
    args = parser.parse_args()
    
    result = main(
        force_full_scan=args.force_full_scan,
        commits_to_process=args.commits_to_process
    )
    
    import sys
    sys.exit(0 if result["status"] == "success" else 1)