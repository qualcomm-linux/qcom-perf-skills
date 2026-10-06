#!/usr/bin/env python3
"""
code_analyzer.py - Code Analysis Module

Analyzes Python code using AST (Abstract Syntax Tree):
- Parse Python files
- Extract functions, classes, docstrings
- Identify architectural patterns
- Detect changes between commits

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import ast
import re
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    """Information about a function"""
    name: str
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    line_number: int = 0
    source_code: str = ""


@dataclass
class ClassInfo:
    """Information about a class"""
    name: str
    docstring: Optional[str] = None
    base_classes: List[str] = field(default_factory=list)
    methods: List[FunctionInfo] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    line_number: int = 0


@dataclass
class FileAnalysis:
    """Analysis results for a Python file"""
    file_path: str
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    module_docstring: Optional[str] = None
    patterns_detected: List[str] = field(default_factory=list)


class CodeAnalyzer:
    """Analyzes Python code and extracts structural information"""
    
    def __init__(self, repo_root: Optional[Path] = None):
        """
        Initialize CodeAnalyzer
        
        Args:
            repo_root: Root directory of repository
        """
        self.repo_root = repo_root or Path.cwd()
    
    def analyze_file(self, file_path: str) -> FileAnalysis:
        """
        Analyze a Python file
        
        Args:
            file_path: Path to Python file (relative to repo root)
            
        Returns:
            FileAnalysis object with extracted information
        """
        full_path = self.repo_root / file_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")
        
        # Read file content
        with open(full_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        # Parse AST
        try:
            tree = ast.parse(source_code, filename=str(full_path))
        except SyntaxError as e:
            print(f"WARNING: Syntax error in {file_path}: {e}")
            return FileAnalysis(file_path=file_path)
        
        # Extract information
        analysis = FileAnalysis(file_path=file_path)
        analysis.module_docstring = ast.get_docstring(tree)
        analysis.imports = self._extract_imports(tree)
        analysis.functions = self._extract_functions(tree, source_code)
        analysis.classes = self._extract_classes(tree, source_code)
        analysis.patterns_detected = self._detect_patterns(analysis)
        
        return analysis
    
    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extract import statements"""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
        return imports
    
    def _extract_functions(self, tree: ast.AST, source_code: str) -> List[FunctionInfo]:
        """Extract top-level functions"""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Only top-level functions (not methods)
                if not any(isinstance(parent, ast.ClassDef) 
                          for parent in ast.walk(tree) 
                          if hasattr(parent, 'body') and node in parent.body):
                    func_info = self._parse_function(node, source_code)
                    functions.append(func_info)
        return functions
    
    def _extract_classes(self, tree: ast.AST, source_code: str) -> List[ClassInfo]:
        """Extract class definitions"""
        classes = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_info = self._parse_class(node, source_code)
                classes.append(class_info)
        return classes
    
    def _parse_function(self, node: ast.FunctionDef, source_code: str) -> FunctionInfo:
        """Parse function node"""
        # Extract parameters
        parameters = [arg.arg for arg in node.args.args]
        
        # Extract decorators
        decorators = [self._get_decorator_name(dec) for dec in node.decorator_list]
        
        # Extract return type annotation
        return_type = None
        if node.returns:
            return_type = ast.unparse(node.returns) if hasattr(ast, 'unparse') else None
        
        # Extract source code
        source_lines = source_code.split('\n')
        func_source = '\n'.join(source_lines[node.lineno-1:node.end_lineno])
        
        return FunctionInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            parameters=parameters,
            return_type=return_type,
            decorators=decorators,
            line_number=node.lineno,
            source_code=func_source
        )
    
    def _parse_class(self, node: ast.ClassDef, source_code: str) -> ClassInfo:
        """Parse class node"""
        # Extract base classes
        base_classes = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_classes.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_classes.append(ast.unparse(base) if hasattr(ast, 'unparse') else str(base))
        
        # Extract decorators
        decorators = [self._get_decorator_name(dec) for dec in node.decorator_list]
        
        # Extract methods
        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_info = self._parse_function(item, source_code)
                methods.append(method_info)
        
        return ClassInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            base_classes=base_classes,
            methods=methods,
            decorators=decorators,
            line_number=node.lineno
        )
    
    def _get_decorator_name(self, decorator: ast.expr) -> str:
        """Extract decorator name"""
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                return decorator.func.id
        return str(decorator)
    
    def _detect_patterns(self, analysis: FileAnalysis) -> List[str]:
        """
        Detect architectural patterns in the code
        
        Returns:
            List of detected pattern names
        """
        patterns = []
        
        # Pattern 1: Benchmark implementations
        for cls in analysis.classes:
            if 'BenchmarkBase' in cls.base_classes:
                patterns.append('benchmark_implementation')
            if 'OutlierDetector' in cls.name:
                patterns.append('outlier_detector')
        
        # Pattern 2: Statistical methods
        for func in analysis.functions:
            if func.name.startswith('_detect_'):
                patterns.append('statistical_method')
        
        # Pattern 3: RCA methods
        for func in analysis.functions:
            if 'analyze' in func.name.lower() or 'rca' in func.name.lower():
                patterns.append('rca_method')
        
        # Pattern 4: Telemetry
        if 'telemetry' in analysis.file_path.lower():
            patterns.append('telemetry_component')
        
        return list(set(patterns))  # Remove duplicates
    
    def compare_versions(self, old_analysis: FileAnalysis, 
                        new_analysis: FileAnalysis) -> Dict[str, Any]:
        """
        Compare two versions of a file
        
        Args:
            old_analysis: Analysis of old version
            new_analysis: Analysis of new version
            
        Returns:
            Dict with changes detected
        """
        changes = {
            'functions_added': [],
            'functions_removed': [],
            'functions_modified': [],
            'classes_added': [],
            'classes_removed': [],
            'classes_modified': []
        }
        
        # Compare functions
        old_func_names = {f.name for f in old_analysis.functions}
        new_func_names = {f.name for f in new_analysis.functions}
        
        changes['functions_added'] = list(new_func_names - old_func_names)
        changes['functions_removed'] = list(old_func_names - new_func_names)
        
        # Check for modified functions
        for func in new_analysis.functions:
            if func.name in old_func_names:
                old_func = next(f for f in old_analysis.functions if f.name == func.name)
                if func.source_code != old_func.source_code:
                    changes['functions_modified'].append(func.name)
        
        # Compare classes
        old_class_names = {c.name for c in old_analysis.classes}
        new_class_names = {c.name for c in new_analysis.classes}
        
        changes['classes_added'] = list(new_class_names - old_class_names)
        changes['classes_removed'] = list(old_class_names - new_class_names)
        
        # Check for modified classes
        for cls in new_analysis.classes:
            if cls.name in old_class_names:
                old_cls = next(c for c in old_analysis.classes if c.name == cls.name)
                if cls.docstring != old_cls.docstring or len(cls.methods) != len(old_cls.methods):
                    changes['classes_modified'].append(cls.name)
        
        return changes


# Example usage
if __name__ == "__main__":
    # Test CodeAnalyzer
    analyzer = CodeAnalyzer()
    
    # Analyze a sample file
    test_file = "aibench/src/benchmark/coremark.py"
    
    try:
        analysis = analyzer.analyze_file(test_file)
        
        print(f"File: {analysis.file_path}")
        print(f"\nModule Docstring: {analysis.module_docstring[:100] if analysis.module_docstring else 'None'}...")
        print(f"\nImports: {len(analysis.imports)}")
        print(f"Functions: {len(analysis.functions)}")
        print(f"Classes: {len(analysis.classes)}")
        print(f"Patterns: {analysis.patterns_detected}")
        
        # Display classes
        print("\nClasses:")
        for cls in analysis.classes:
            print(f"  - {cls.name} (base: {cls.base_classes})")
            print(f"    Methods: {[m.name for m in cls.methods]}")
            if cls.docstring:
                print(f"    Docstring: {cls.docstring[:80]}...")
    
    except FileNotFoundError as e:
        print(f"File not found: {e}")
        print("This is expected if running outside the repository")