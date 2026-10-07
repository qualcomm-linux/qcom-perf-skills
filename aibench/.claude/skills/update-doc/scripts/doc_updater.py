#!/usr/bin/env python3
"""
doc_updater.py - Documentation Updater

Updates Architecture.md with new documentation:
- Read current document
- Identify sections to update
- Merge new documentation
- Preserve manual sections
- Update table of contents
- Validate markdown syntax

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class DocUpdater:
    """Updates Architecture.md with new documentation"""
    
    def __init__(self, doc_path: Optional[Path] = None):
        """
        Initialize DocUpdater
        
        Args:
            doc_path: Path to Architecture.md (default: auto-detect)
        """
        if doc_path is None:
            # Auto-detect Architecture.md location
            repo_root = Path.cwd()
            while repo_root != repo_root.parent:
                arch_doc = repo_root / "benchmarks" / "documentation" / "Architecture.md"
                if arch_doc.exists():
                    self.doc_path = arch_doc
                    break
                repo_root = repo_root.parent
            else:
                raise FileNotFoundError("Architecture.md not found")
        else:
            self.doc_path = Path(doc_path)
        
        self.content = ""
        self.sections = {}
    
    def read_document(self) -> str:
        """
        Read current Architecture.md
        
        Returns:
            Document content as string
        """
        with open(self.doc_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
        
        # Parse sections
        self._parse_sections()
        
        return self.content
    
    def _parse_sections(self):
        """Parse document into sections"""
        # Find all section headers (## Section Title)
        pattern = r'^(#{2,3})\s+(\d+\.?\d*\.?\d*)\s+(.+)$'
        
        lines = self.content.split('\n')
        current_section = None
        section_content = []
        
        for i, line in enumerate(lines):
            match = re.match(pattern, line)
            if match:
                # Save previous section
                if current_section:
                    self.sections[current_section] = {
                        'title': section_content[0] if section_content else '',
                        'content': '\n'.join(section_content[1:]),
                        'line_start': section_content[0] if section_content else 0
                    }
                
                # Start new section
                level = len(match.group(1))
                number = match.group(2)
                title = match.group(3)
                current_section = number
                section_content = [line]
            else:
                if current_section:
                    section_content.append(line)
        
        # Save last section
        if current_section and section_content:
            self.sections[current_section] = {
                'title': section_content[0],
                'content': '\n'.join(section_content[1:]),
                'line_start': 0
            }
    
    def find_section(self, section_number: str) -> Optional[Dict]:
        """
        Find a section by number
        
        Args:
            section_number: Section number (e.g., "5", "5.2", "5.2.1")
            
        Returns:
            Section dict or None if not found
        """
        return self.sections.get(section_number)
    
    def update_section(self, section_number: str, new_content: str, 
                      preserve_manual: bool = True) -> bool:
        """
        Update a section with new content
        
        Args:
            section_number: Section number to update
            new_content: New content for the section
            preserve_manual: Whether to preserve manual sections
            
        Returns:
            True if updated, False if section not found
        """
        section = self.find_section(section_number)
        if not section:
            print(f"WARNING: Section {section_number} not found")
            return False
        
        # Check for manual markers
        if preserve_manual and '<!-- MANUAL' in section['content']:
            print(f"INFO: Section {section_number} contains manual content, preserving")
            # Extract manual sections
            manual_sections = self._extract_manual_sections(section['content'])
            # Merge with new content
            new_content = self._merge_with_manual(new_content, manual_sections)
        
        # Update section content
        section['content'] = new_content
        
        return True
    
    def _extract_manual_sections(self, content: str) -> List[Tuple[str, str]]:
        """
        Extract manual sections marked with <!-- MANUAL --> tags
        
        Args:
            content: Section content
            
        Returns:
            List of (marker, content) tuples
        """
        manual_sections = []
        pattern = r'<!-- MANUAL: (.+?) -->(.+?)<!-- /MANUAL -->'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            marker = match.group(1)
            manual_content = match.group(2)
            manual_sections.append((marker, manual_content))
        
        return manual_sections
    
    def _merge_with_manual(self, new_content: str, 
                          manual_sections: List[Tuple[str, str]]) -> str:
        """
        Merge new content with preserved manual sections
        
        Args:
            new_content: New auto-generated content
            manual_sections: List of manual sections to preserve
            
        Returns:
            Merged content
        """
        # For now, append manual sections at the end
        # In a full implementation, this would be more sophisticated
        merged = new_content
        
        for marker, content in manual_sections:
            merged += f"\n\n<!-- MANUAL: {marker} -->{content}<!-- /MANUAL -->"
        
        return merged
    
    def write_document(self) -> bool:
        """
        Write updated document back to file
        
        Returns:
            True if successful
        """
        # Reconstruct document from sections
        lines = []
        
        # Add header (everything before first section)
        header_end = self.content.find('\n## ')
        if header_end > 0:
            lines.append(self.content[:header_end])
        
        # Add sections in order
        for section_num in sorted(self.sections.keys(), key=self._section_sort_key):
            section = self.sections[section_num]
            lines.append(section['title'])
            lines.append(section['content'])
        
        # Write to file
        new_content = '\n'.join(lines)
        
        with open(self.doc_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True
    
    def _section_sort_key(self, section_num: str) -> Tuple:
        """
        Generate sort key for section numbers
        
        Args:
            section_num: Section number string (e.g., "5.2.1")
            
        Returns:
            Tuple for sorting
        """
        parts = section_num.split('.')
        return tuple(int(p) if p.isdigit() else 0 for p in parts)
    
    def validate_markdown(self) -> List[str]:
        """
        Validate markdown syntax
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check for unclosed code blocks
        code_block_count = self.content.count('```')
        if code_block_count % 2 != 0:
            errors.append("Unclosed code block detected")
        
        # Check for broken links
        link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        for match in re.finditer(link_pattern, self.content):
            link_text = match.group(1)
            link_url = match.group(2)
            
            # Check for empty links
            if not link_url.strip():
                errors.append(f"Empty link: [{link_text}]()")
        
        # Check for malformed headers
        lines = self.content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('#'):
                # Check for space after #
                if not re.match(r'^#+\s', line):
                    errors.append(f"Line {i+1}: Malformed header (missing space after #)")
        
        return errors
    
    def update_table_of_contents(self) -> bool:
        """
        Update table of contents based on current sections
        
        Returns:
            True if successful
        """
        # Find TOC section
        toc_start = self.content.find('## Table of Contents')
        if toc_start == -1:
            print("WARNING: Table of Contents not found")
            return False
        
        # Find end of TOC (next ## header)
        toc_end = self.content.find('\n## ', toc_start + 1)
        if toc_end == -1:
            toc_end = len(self.content)
        
        # Generate new TOC
        toc_lines = ['## Table of Contents', '']
        
        for section_num in sorted(self.sections.keys(), key=self._section_sort_key):
            section = self.sections[section_num]
            # Extract title from section header
            title_match = re.search(r'##\s+\d+\.?\d*\.?\d*\s+(.+)$', section['title'])
            if title_match:
                title = title_match.group(1)
                indent = '  ' * (section_num.count('.'))
                anchor = title.lower().replace(' ', '-').replace('&', '').replace('(', '').replace(')', '')
                toc_lines.append(f"{indent}{section_num}. [{title}](#{section_num.replace('.', '')}-{anchor})")
        
        toc_lines.append('')
        
        # Replace TOC
        new_toc = '\n'.join(toc_lines)
        self.content = self.content[:toc_start] + new_toc + self.content[toc_end:]
        
        return True
    
    def get_section_list(self) -> List[str]:
        """
        Get list of all section numbers
        
        Returns:
            List of section numbers
        """
        return sorted(self.sections.keys(), key=self._section_sort_key)


# Example usage
if __name__ == "__main__":
    # Test DocUpdater
    try:
        updater = DocUpdater()
        
        print(f"Document: {updater.doc_path}")
        
        # Read document
        content = updater.read_document()
        print(f"\nDocument length: {len(content)} characters")
        print(f"Sections found: {len(updater.sections)}")
        
        # List sections
        print("\nSections:")
        for section_num in updater.get_section_list()[:10]:  # Show first 10
            section = updater.sections[section_num]
            title_match = re.search(r'##\s+\d+\.?\d*\.?\d*\s+(.+)$', section['title'])
            if title_match:
                print(f"  {section_num}: {title_match.group(1)}")
        
        # Validate markdown
        errors = updater.validate_markdown()
        if errors:
            print(f"\nValidation errors: {len(errors)}")
            for error in errors[:5]:  # Show first 5
                print(f"  - {error}")
        else:
            print("\n✓ Markdown validation passed")
    
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("This is expected if running outside the repository")