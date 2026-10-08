#!/usr/bin/env python3
"""
Verify the section order in web_gui.py Create Script workflow
"""

import re


def analyze_create_script_workflow():
    with open('/Users/christhi/Dev/Github/linedrive/scriptcraft-app/web_gui.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the Create Script route
    create_match = re.search(r'@app\.route\("/create"', content)
    if not create_match:
        print("❌ Could not find /create route")
        return

    start_pos = create_match.start()

    # Find section appending order after YouTube details
    youtube_append = content.find(
        'final_script_with_tools += youtube_section', start_pos)
    demo_append = content.find(
        'final_script_with_tools += demo_section', start_pos)
    heygen_append = content.find(
        'final_script_with_tools += heygen_section', start_pos)

    sections = []
    if youtube_append > 0:
        sections.append(('YouTube Details', youtube_append))
    if demo_append > 0:
        sections.append(('Demo Packages', demo_append))
    if heygen_append > 0:
        sections.append(('HeyGen Section', heygen_append))

    # Sort by position in file
    sections.sort(key=lambda x: x[1])

    print("=" * 80)
    print("CREATE SCRIPT WORKFLOW - SECTION APPEND ORDER")
    print("=" * 80)

    if sections:
        for i, (name, pos) in enumerate(sections, 1):
            line_num = content[:pos].count('\n') + 1
            print(f"{i}. {name:20} (appended at line ~{line_num})")
    else:
        print("❌ Could not find any section appends")

    print("\n" + "=" * 80)
    print("DESIRED ORDER:")
    print("=" * 80)
    print("1. Main Script Content")
    print("2. YouTube Details")
    print("3. Demo Packages")
    print("4. HeyGen Ready Script")
    print("5. Curl Commands")

    # Verify order
    print("\n" + "=" * 80)
    if len(sections) >= 3:
        order_correct = (
            sections[0][0] == 'YouTube Details' and
            sections[1][0] == 'Demo Packages' and
            sections[2][0] == 'HeyGen Section'
        )

        if order_correct:
            print("✅ ORDER IS CORRECT!")
        else:
            print("❌ ORDER IS WRONG!")
            print(f"   Expected: YouTube → Demo → HeyGen")
            print(
                f"   Actual:   {sections[0][0]} → {sections[1][0]} → {sections[2][0]}")
    else:
        print("⚠️ Could not verify order - missing sections")


if __name__ == "__main__":
    analyze_create_script_workflow()
