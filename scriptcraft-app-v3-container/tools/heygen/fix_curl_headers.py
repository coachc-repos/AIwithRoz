#!/usr/bin/env python3
"""
Remove comment headers from curl command generation
"""

file_path = "console_ui/text_processing.py"

with open(file_path, 'r') as f:
    content = f.read()

# Part 1 - Remove the 3 comment lines before curl command
old_part1 = '''        curl_cmd_part1 = f"""# Chapter {i} - Part 1: {chapter['title']}
# Content length: {len(part1)} characters
# Title: {script_title}-Ch{i}p1

curl --location 'https://api.heygen.com/v2/template/{template_id}/generate' \\'''

new_part1 = '''        curl_cmd_part1 = f"""curl --location 'https://api.heygen.com/v2/template/{template_id}/generate' \\'''

# Part 2 - Remove the 3 comment lines before curl command
old_part2 = '''        curl_cmd_part2 = f"""# Chapter {i} - Part 2: {chapter['title']}
# Content length: {len(part2)} characters
# Title: {script_title}-Ch{i}p2

curl --location 'https://api.heygen.com/v2/template/{template_id}/generate' \\'''

new_part2 = '''        curl_cmd_part2 = f"""curl --location 'https://api.heygen.com/v2/template/{template_id}/generate' \\'''

# Apply replacements
if old_part1 in content:
    content = content.replace(old_part1, new_part1)
    print("✅ Removed Part 1 comment headers")
else:
    print("❌ Could not find Part 1 section")

if old_part2 in content:
    content = content.replace(old_part2, new_part2)
    print("✅ Removed Part 2 comment headers")
else:
    print("❌ Could not find Part 2 section")

# Write back
with open(file_path, 'w') as f:
    f.write(content)

print("\n✅ Curl commands will now be generated back-to-back without section headers")
