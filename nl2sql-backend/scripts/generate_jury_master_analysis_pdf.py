"""Master PDF Generator Script for NL2SQL Technical Project Analysis & Jury Defense Guide.
Compiles all 28 sections into a publication-grade, professional technical document.
"""

import sys
import shutil
from pathlib import Path

# Add current scripts directory and parent to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
WORKSPACE_DIR = BACKEND_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, PageBreak, Spacer

from pdf_sections.styles import NumberedCanvas, MARGIN
from pdf_sections.part1_overview_and_stack import build_part1
from pdf_sections.part2_deep_code_and_key_snippets import build_part2
from pdf_sections.part3_api_db_ai_security import build_part3
from pdf_sections.part4_performance_design_architecture import build_part4
from pdf_sections.part5_jury_questions_bank import build_part5
from pdf_sections.part6_testing_devops_presentation_revision import build_part6


def generate_master_pdf():
    # Target output paths
    docs_dir = WORKSPACE_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    primary_pdf_path = docs_dir / "NL2SQL_Technical_Project_Analysis_and_Jury_Defense.pdf"
    
    print(f"[*] Building Master Technical Defense PDF at: {primary_pdf_path}")
    
    doc = SimpleDocTemplate(
        str(primary_pdf_path),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    
    story = []
    
    # 1. Part 1: Overview, Stack, Folders, Inventory (Sections 1 - 4)
    print("  -> Compiling Part 1 (Sections 1-4)...")
    story.extend(build_part1())
    story.append(PageBreak())
    
    # 2. Part 2: Deep Code Analysis, Key Code Explanation, Complete Data Flow (Sections 5 - 7)
    print("  -> Compiling Part 2 (Sections 5-7)...")
    story.extend(build_part2())
    story.append(PageBreak())
    
    # 3. Part 3: API, Database, AI/ML/RAG, Security Analysis (Sections 8 - 11)
    print("  -> Compiling Part 3 (Sections 8-11)...")
    story.extend(build_part3())
    story.append(PageBreak())
    
    # 4. Part 4: Error Handling, Performance, Scalability, Design Decisions, Dependencies (Sections 12 - 16)
    print("  -> Compiling Part 4 (Sections 12-16)...")
    story.extend(build_part4())
    story.append(PageBreak())
    
    # 5. Part 5: Jury Must Know, Question Bank A-R, Hard Cross-Questions, Show Me The Code (Sections 17 - 20)
    print("  -> Compiling Part 5 (Sections 17-20)...")
    story.extend(build_part5())
    story.append(PageBreak())
    
    # 6. Part 6: Testing Matrix, DevOps, Weaknesses, 5-Min Presentation, 30s Pitch, 2-Min Briefing, Revision Sheet, Glossary (Sections 21 - 28)
    print("  -> Compiling Part 6 (Sections 21-28)...")
    story.extend(build_part6())
    
    # Build Document with NumberedCanvas
    print("  -> Rendering document with two-pass NumberedCanvas...")
    doc.build(story, canvasmaker=NumberedCanvas)
    
    size_bytes = primary_pdf_path.stat().st_size
    size_kb = size_bytes / 1024
    print(f"[+] Successfully generated: {primary_pdf_path} ({size_kb:.1f} KB)")
    
    # Copy to workspace root and backend docs for convenience
    root_copy = WORKSPACE_DIR / "NL2SQL_Technical_Project_Analysis_and_Jury_Defense.pdf"
    backend_docs_dir = BACKEND_DIR / "docs"
    backend_docs_dir.mkdir(parents=True, exist_ok=True)
    backend_copy = backend_docs_dir / "NL2SQL_Technical_Project_Analysis_and_Jury_Defense.pdf"
    
    shutil.copy2(primary_pdf_path, root_copy)
    shutil.copy2(primary_pdf_path, backend_copy)
    
    print(f"[+] Replicated to root: {root_copy}")
    print(f"[+] Replicated to backend docs: {backend_copy}")
    return primary_pdf_path


if __name__ == "__main__":
    generate_master_pdf()
