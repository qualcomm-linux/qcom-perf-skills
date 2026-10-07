#!/usr/bin/env python3
"""
doc_generator.py - Documentation Generator

Generates markdown documentation from code analysis:
- Create function documentation
- Create class documentation
- Generate code examples
- Build parameter tables
- Format consistently

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from typing import Dict, List, Optional
from pathlib import Path
from code_analyzer import FileAnalysis, ClassInfo, FunctionInfo


class DocGenerator:
    """Generates markdown documentation from code analysis"""
    
    def __init__(self):
        """Initialize DocGenerator"""
        pass
    
    def generate_benchmark_doc(self, analysis: FileAnalysis, 
                               class_info: ClassInfo) -> str:
        """
        Generate documentation for a benchmark implementation
        
        Args:
            analysis: File analysis results
            class_info: Class information for the benchmark
            
        Returns:
            Markdown documentation string
        """
        doc = []
        
        # Extract benchmark name (remove "Benchmark" suffix)
        benchmark_name = class_info.name.replace("Benchmark", "")
        
        # Header
        doc.append(f"#### 5.2.X {benchmark_name}")
        doc.append("")
        
        # Purpose (from docstring)
        if class_info.docstring:
            doc.append(f"**Purpose**: {class_info.docstring.split(chr(10))[0]}")
            doc.append("")
        
        # Category (would need to be extracted from config)
        doc.append("**Category**: [Extract from config]")
        doc.append("")
        
        # Implementation
        doc.append(f"**Implementation**: `{analysis.file_path}`")
        doc.append("")
        
        # Metrics (from run() method)
        run_method = next((m for m in class_info.methods if m.name == "run"), None)
        if run_method and run_method.docstring:
            doc.append("**Metrics Extracted:**")
            doc.append(f"- {run_method.docstring}")
            doc.append("")
        
        # Methods
        doc.append("**Lifecycle Methods:**")
        for method in class_info.methods:
            if method.name in ["setup", "run", "teardown"]:
                doc.append(f"- `{method.name}()`: {method.docstring or 'No description'}")
        doc.append("")
        
        return "\n".join(doc)
    
    def generate_function_doc(self, func_info: FunctionInfo) -> str:
        """
        Generate documentation for a function
        
        Args:
            func_info: Function information
            
        Returns:
            Markdown documentation string
        """
        doc = []
        
        # Function signature
        params = ", ".join(func_info.parameters)
        doc.append(f"**`{func_info.name}({params})`**")
        doc.append("")
        
        # Docstring
        if func_info.docstring:
            doc.append(func_info.docstring)
            doc.append("")
        
        # Parameters table
        if func_info.parameters:
            doc.append("**Parameters:**")
            for param in func_info.parameters:
                doc.append(f"- `{param}`: [Type and description]")
            doc.append("")
        
        # Return type
        if func_info.return_type:
            doc.append(f"**Returns**: `{func_info.return_type}`")
            doc.append("")
        
        return "\n".join(doc)
    
    def generate_class_doc(self, class_info: ClassInfo) -> str:
        """
        Generate documentation for a class
        
        Args:
            class_info: Class information
            
        Returns:
            Markdown documentation string
        """
        doc = []
        
        # Class header
        doc.append(f"### {class_info.name}")
        doc.append("")
        
        # Inheritance
        if class_info.base_classes:
            bases = ", ".join(class_info.base_classes)
            doc.append(f"**Inherits from**: `{bases}`")
            doc.append("")
        
        # Docstring
        if class_info.docstring:
            doc.append(class_info.docstring)
            doc.append("")
        
        # Methods
        if class_info.methods:
            doc.append("**Methods:**")
            doc.append("")
            for method in class_info.methods:
                doc.append(f"#### `{method.name}()`")
                if method.docstring:
                    doc.append(method.docstring)
                doc.append("")
        
        return "\n".join(doc)
    
    def generate_code_example(self, code: str, language: str = "python") -> str:
        """
        Generate a formatted code example
        
        Args:
            code: Source code
            language: Programming language for syntax highlighting
            
        Returns:
            Markdown code block
        """
        return f"```{language}\n{code}\n```"
    
    def generate_parameter_table(self, parameters: List[Dict[str, str]]) -> str:
        """
        Generate a markdown table for parameters
        
        Args:
            parameters: List of parameter dicts with 'name', 'type', 'description'
            
        Returns:
            Markdown table string
        """
        if not parameters:
            return ""
        
        table = []
        table.append("| Parameter | Type | Description |")
        table.append("|-----------|------|-------------|")
        
        for param in parameters:
            name = param.get('name', '')
            ptype = param.get('type', '')
            desc = param.get('description', '')
            table.append(f"| `{name}` | `{ptype}` | {desc} |")
        
        return "\n".join(table)
    
    def generate_statistical_method_doc(self, func_info: FunctionInfo) -> str:
        """
        Generate documentation for a statistical method
        
        Args:
            func_info: Function information
            
        Returns:
            Markdown documentation string
        """
        doc = []
        
        # Extract method name (remove _detect_ prefix)
        method_name = func_info.name.replace("_detect_", "").replace("_", " ").title()
        
        doc.append(f"#### 8.2.X {method_name}")
        doc.append("")
        
        # Purpose
        if func_info.docstring:
            doc.append(f"**Purpose**: {func_info.docstring.split(chr(10))[0]}")
            doc.append("")
        
        # Implementation
        doc.append("**Implementation:**")
        doc.append(self.generate_code_example(func_info.source_code))
        doc.append("")
        
        # Parameters
        if func_info.parameters:
            doc.append("**Parameters:**")
            for param in func_info.parameters:
                doc.append(f"- `{param}`")
            doc.append("")
        
        return "\n".join(doc)
    
    def generate_rca_category_doc(self, func_info: FunctionInfo) -> str:
        """
        Generate documentation for an RCA category
        
        Args:
            func_info: Function information
            
        Returns:
            Markdown documentation string
        """
        doc = []
        
        # Extract category name
        category_name = func_info.name.replace("detect_", "").replace("_", " ").title()
        
        doc.append(f"#### 9.2.X {category_name}")
        doc.append("")
        
        # Purpose
        if func_info.docstring:
            doc.append(f"**Purpose**: {func_info.docstring}")
            doc.append("")
        
        # Detection logic
        doc.append("**Detection Logic:**")
        doc.append(self.generate_code_example(func_info.source_code))
        doc.append("")
        
        return "\n".join(doc)
    
    def generate_section_summary(self, file_analyses: List[FileAnalysis]) -> str:
        """
        Generate a summary for a documentation section
        
        Args:
            file_analyses: List of file analyses for this section
            
        Returns:
            Markdown summary string
        """
        doc = []
        
        total_files = len(file_analyses)
        total_classes = sum(len(a.classes) for a in file_analyses)
        total_functions = sum(len(a.functions) for a in file_analyses)
        
        doc.append(f"**Summary**: {total_files} files analyzed")
        doc.append(f"- Classes: {total_classes}")
        doc.append(f"- Functions: {total_functions}")
        doc.append("")
        
        return "\n".join(doc)
    
    def format_docstring(self, docstring: Optional[str], 
                        max_length: int = 200) -> str:
        """
        Format a docstring for display
        
        Args:
            docstring: Raw docstring
            max_length: Maximum length before truncation
            
        Returns:
            Formatted docstring
        """
        if not docstring:
            return "No description available"
        
        # Take first line
        first_line = docstring.split('\n')[0].strip()
        
        # Truncate if too long
        if len(first_line) > max_length:
            first_line = first_line[:max_length] + "..."
        
        return first_line


# Example usage
if __name__ == "__main__":
    from code_analyzer import CodeAnalyzer, FunctionInfo, ClassInfo
    
    # Test DocGenerator
    generator = DocGenerator()
    
    # Create sample function info
    func_info = FunctionInfo(
        name="_detect_median_delta",
        docstring="Detect regression using median delta method",
        parameters=["baseline_data", "current_data"],
        return_type="Optional[Dict]",
        line_number=100,
        source_code="def _detect_median_delta(baseline, current):\n    return None"
    )
    
    # Generate documentation
    print("=== Function Documentation ===")
    print(generator.generate_function_doc(func_info))
    
    print("\n=== Statistical Method Documentation ===")
    print(generator.generate_statistical_method_doc(func_info))
    
    # Create sample class info
    class_info = ClassInfo(
        name="CoremarkBenchmark",
        docstring="CoreMark CPU benchmark implementation",
        base_classes=["BenchmarkBase"],
        methods=[
            FunctionInfo(name="setup", docstring="Setup phase"),
            FunctionInfo(name="run", docstring="Execute benchmark"),
            FunctionInfo(name="teardown", docstring="Cleanup phase")
        ],
        line_number=50
    )
    
    print("\n=== Class Documentation ===")
    print(generator.generate_class_doc(class_info))
    
    # Generate parameter table
    params = [
        {"name": "baseline", "type": "List[float]", "description": "Baseline metric values"},
        {"name": "current", "type": "List[float]", "description": "Current metric values"}
    ]
    
    print("\n=== Parameter Table ===")
    print(generator.generate_parameter_table(params))