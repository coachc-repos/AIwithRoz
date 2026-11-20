#!/usr/bin/env python3
"""
Workflow functions for LineDrive Console
Contains the main automation workflow logic
"""

from word_processing import convert_markdown_to_word
from text_processing import extract_teleprompter_text, enhance_demo_packages_formatting
from utils import sanitize_filename, extract_script_title
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))


async def run_demo_script_creator():
    """Run the Demo Script Creator workflow"""
    print("🎥 Launching Demo Script Creator...")

    # Implementation would go here - for now, placeholder
    print("🚧 Demo Script Creator - Implementation coming soon!")


async def run_script_to_demo_workflow():
    """Complete 4-Agent Script to Demo workflow with enhanced B-roll"""
    print("🎬 Complete 4-Agent Script → Demo Workflow")
    print("=" * 60)
    print("This complete workflow will:")
    print("1. 🧠 Topic Assistant: Enhance topic and create chapter breakdown")
    print("2. ✍️  Script Writer: Create comprehensive script from enhanced topic")
    print("3. 🔍 Script Reviewer: Review and provide feedback on script")
    print("4. 🎥 Demo Generator: Create demo packages from final script")
    print("5. 🎬 Enhanced B-roll: Download contextual videos with better keywords")
    print("6. �️  Thumbnail Generator: Create eye-catching video thumbnails")
    print("7. 📺 YouTube Metadata: Generate SEO-optimized upload details")
    print("8. �📁 Split demos for developer and everyday viewers")
    print()

    try:
        # Collect comprehensive input from user
        print("📝 SCRIPT CONFIGURATION")
        print("-" * 30)

        # Get script topic
        try:
            script_topic = input("📋 Enter your script topic: ").strip()
        except EOFError:
            print("\n❌ No input available. Exiting.")
            return
        if not script_topic:
            print("❌ No topic provided. Exiting.")
            return

        # Get topic description
        print("\n📄 TOPIC DESCRIPTION")
        print(
            "Provide additional details, context, or specific areas you want covered:"
        )
        try:
            topic_description = input(
                "📝 Enter topic description (optional): ").strip()
        except EOFError:
            topic_description = ""
            print("   Using empty description (EOF)")
        if not topic_description:
            topic_description = ""
            print("   No additional description provided")
        else:
            description_preview = (
                (topic_description[:100] + "...")
                if len(topic_description) > 100
                else topic_description
            )
            print(f"   Description: {description_preview}")

        # Get target audience
        print("\n🎯 TARGET AUDIENCE")
        print(
            "Examples: beginners, developers, students, business professionals, general audience, etc."
        )
        try:
            audience = input("👥 Enter target audience: ").strip()
        except EOFError:
            audience = "general audience"
            print(f"   Using default (EOF): {audience}")
        if not audience:
            audience = "general audience"
            print(f"   Using default: {audience}")

        # Get tone/style
        print("\n� TONE & STYLE")
        print(
            "Examples: conversational, professional, educational, casual, technical, entertaining, etc."
        )
        try:
            tone = input("💬 Enter desired tone: ").strip()
        except EOFError:
            tone = "conversational and educational"
            print(f"   Using default (EOF): {tone}")
        if not tone:
            tone = "conversational and educational"
            print(f"   Using default: {tone}")

        # Get verbosity preference
        print("\n🔧 LOGGING VERBOSITY")
        print("Choose logging level:")
        print("  • Minimal: Only essential progress, timestamps, and results")
        print("  • Verbose: Full agent traces, detailed workflow logging")
        try:
            verbose_choice = (
                input("📊 Enter choice (minimal/verbose) [default: minimal]: ")
                .strip()
                .lower()
            )
        except EOFError:
            verbose_choice = "minimal"
            print(f"   Using default (EOF): {verbose_choice}")
        if not verbose_choice:
            verbose_choice = "minimal"
            print(f"   Using default: {verbose_choice}")

        # Convert to boolean
        verbose = verbose_choice.startswith("v")

        # Get script length preference
        print("\n⏱️ SCRIPT LENGTH")
        print("Choose desired script length:")
        print("  • Short: 3-5 minutes (600-800 words)")
        print("  • Medium: 5-8 minutes (800-1200 words)")
        print("  • Long: 8-12 minutes (1200-1800 words)")
        print("  • Custom: Specify your own length")
        print("  • Or enter directly: e.g., '15 minutes', '10 minutes', '2000 words'")
        try:
            length_choice = (
                input(
                    "📏 Enter choice (short/medium/long/custom) or direct length [default: medium]: "
                )
                .strip()
                .lower()
            )
        except EOFError:
            length_choice = "medium"
            print(f"   Using default (EOF): {length_choice}")
        if not length_choice:
            length_choice = "medium"
            print(f"   Using default: {length_choice}")

        # Process length choice
        if length_choice.startswith("s"):
            script_length = "3-5 minutes (600-800 words)"
        elif length_choice.startswith("l"):
            script_length = "8-12 minutes (1200-1800 words)"
        elif length_choice.startswith("c"):
            try:
                custom_length = input(
                    "📝 Enter desired length (e.g., '10 minutes', '1500 words'): "
                ).strip()
                print(f"🔍 Custom length entered: '{custom_length}'")
                script_length = (
                    custom_length if custom_length else "5-8 minutes (800-1200 words)"
                )
                print(f"🔍 Final script_length set to: '{script_length}'")
            except EOFError:
                print("🔍 EOFError caught - using default length")
                script_length = "5-8 minutes (800-1200 words)"
        elif "minute" in length_choice or "word" in length_choice:
            # Direct length specification (e.g., "15 minutes", "1500 words")
            print(f"🔍 Direct length specification detected: '{length_choice}'")
            script_length = length_choice
            print(f"🔍 Final script_length set to: '{script_length}'")
        else:  # medium or default
            script_length = "5-8 minutes (800-1200 words)"

        print(f"\n🚀 STARTING COMPLETE 4-AGENT WORKFLOW")
        print("=" * 50)
        print(f"📋 Topic: {script_topic}")
        if topic_description:
            print(f"📄 Description: {topic_description}")
        print(f"👥 Audience: {audience}")
        print(f"💬 Tone: {tone}")
        print(f"⏱️ Length: {script_length}")
        print(f"🔧 Logging: {'VERBOSE' if verbose else 'MINIMAL'}")
        print("=" * 50)

        # Import and run the enhanced AutoGen system
        from linedrive_azure.agents.enhanced_autogen_system import EnhancedAutoGenSystem

        system = EnhancedAutoGenSystem(verbose=verbose)
        result = await system.run_complete_script_workflow_sequential(
            script_topic=script_topic,
            topic_description=topic_description,
            audience=audience,
            tone=tone,
            script_length=script_length,
        )

        if result.get("success"):
            print(f"\n🎉 COMPLETE 4-AGENT WORKFLOW FINISHED!")
            print("=" * 60)
            print(f"📋 Topic: {script_topic}")
            if topic_description:
                print(f"📄 Description: {topic_description}")
            print(f"👥 Audience: {audience}")
            print(f"💬 Tone: {tone}")
            print(f"⏱️ Length: {script_length}")
            print("-" * 60)
            print(f"✅ Topic Enhanced by Topic Assistant")
            print(f"✅ Script Created by Script Writer")
            print(f"✅ Script Reviewed by Script Reviewer")
            print(f"✅ Sequential Workflow Completed Successfully")

            # Generate a 4-digit script number based on current time
            # Format: HHMM (hour and minute) for uniqueness within a day
            script_number = datetime.now().strftime("%H%M")
            print(f"🔢 Script Number: {script_number}")

            # Add a script-number header (no boilerplate intro).
            introduction = f"""# Script #{script_number}: {script_topic}

---

"""

            # Combine introduction with script content
            raw_script_content = introduction + result["script_content"]

            # Enhanced script with bold tool formatting - ensuring tools appear properly
            from text_processing import (
                enhance_script_with_bold_tools,
                extract_tool_links_and_info,
            )

            enhanced_script_content = enhance_script_with_bold_tools(
                raw_script_content)
            print("✅ Script enhanced with bold tool formatting")

            # Use enhanced script as final content
            final_script_content = enhanced_script_content

            # Extract tool links for YouTube description - ensuring tools are captured
            tool_links = extract_tool_links_and_info(final_script_content)
            print(
                f"📊 Extracted {len(tool_links.splitlines())} tool references")

            # Add tool links to the script content for YouTube description
            final_script_with_tools = final_script_content + "\n\n" + "=" * 60 + "\n"
            final_script_with_tools += "📺 YOUTUBE VIDEO DESCRIPTION\n"
            final_script_with_tools += "=" * 60 + "\n"
            final_script_with_tools += (
                "Copy the section below for your YouTube video description:\n\n"
            )
            final_script_with_tools += f"🎥 {script_topic}\n\n"
            if topic_description:
                final_script_with_tools += f"{topic_description}\n\n"
            final_script_with_tools += tool_links
            final_script_with_tools += "\n\n🔔 Don't forget to SUBSCRIBE for more AI tools and productivity tips!"
            final_script_with_tools += "\n💬 What tools would you like to see featured next? Drop a comment below!"

            # Save results to files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Extract meaningful title from enhanced content or use description if available
            meaningful_title = (
                topic_description
                if topic_description
                and len(topic_description.strip()) > len(script_topic.strip())
                else script_topic
            )
            if not meaningful_title or len(meaningful_title.strip()) <= 3:
                # Try to extract title from the script content itself
                meaningful_title = (
                    extract_script_title(final_script_content) or "AI_Script"
                )

            sanitized_topic = sanitize_filename(meaningful_title)

            # Use Dev/Scripts directory
            output_dir = Path.home() / "Dev/Scripts"
            output_dir.mkdir(parents=True, exist_ok=True)

            # Save the complete formatted script with YouTube description (markdown)
            script_file = output_dir / f"{sanitized_topic}_{timestamp}.md"
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(final_script_with_tools)
            print(
                f"\n📄 Complete script with YouTube description: {script_file}")

            # Define Word file path (will be created later with YouTube + HeyGen)
            word_file = output_dir / f"{sanitized_topic}_{timestamp}.docx"
            print(f"� Word document will be created after YouTube + HeyGen sections")

            # Step 4.5: Download b-roll videos using ENHANCED function
            try:
                print(f"\n🎬 ENHANCED B-ROLL DOWNLOAD WITH CONTEXTUAL KEYWORDS")
                print("-" * 55)
                broll_dir = await extract_enhanced_visual_cues_and_download_broll(
                    final_script_content, script_topic, timestamp
                )
                if broll_dir:
                    print(
                        f"\n✅ Enhanced B-roll videos downloaded to: {broll_dir}")
                else:
                    print(f"\n⚠️ Enhanced B-roll video download skipped or failed")
            except Exception as broll_error:
                print(f"\n❌ Enhanced B-roll download error: {broll_error}")
                print("� Script creation will continue without b-roll videos")

            # Step 4.7: Generate YouTube Upload Details
            youtube_upload_details = None  # Initialize outside try block
            try:
                print(f"\n📺 STEP 4.7: YouTube Upload Details Generation")
                print("-" * 55)

                from linedrive_azure.agents import YouTubeUploadDetailsAgentClient

                youtube_agent = YouTubeUploadDetailsAgentClient()
                print("✅ YouTube Upload Details agent initialized")

                print("🚀 Generating upload details from created script...")
                youtube_result = youtube_agent.generate_upload_details(
                    script_content=final_script_content,
                    script_title=script_topic,
                    target_audience=audience,
                    video_length=script_length,
                    primary_keywords=None,
                    channel_focus=None,
                    timeout=180
                )

                if youtube_result.get("success", False):
                    youtube_upload_details = youtube_result.get(
                        "upload_details", "")
                    print(
                        f"✅ YouTube upload details generated ({len(youtube_upload_details)} characters)")

                    # Save standalone YouTube upload details file
                    youtube_filename = f"{sanitized_topic}_youtube_upload_{timestamp}.md"
                    youtube_file = output_dir / youtube_filename
                    youtube_file.write_text(
                        youtube_upload_details, encoding="utf-8")
                    print(f"📄 YouTube upload details saved: {youtube_file}")

                    # Append YouTube details to the main script markdown file
                    print("📝 Appending YouTube details to script markdown file...")
                    youtube_section = f"\n\n{'=' * 80}\n"
                    youtube_section += "# 📺 YOUTUBE UPLOAD DETAILS\n"
                    youtube_section += f"{'=' * 80}\n\n"
                    youtube_section += youtube_upload_details

                    with open(script_file, "a", encoding="utf-8") as f:
                        f.write(youtube_section)
                    print(f"✅ YouTube details appended to: {script_file}")

                    # Recreate Word document with YouTube details included
                    print("📘 Updating Word document with YouTube details...")
                    final_script_with_youtube = final_script_with_tools + youtube_section

                    # NEW: Extract HeyGen-ready host script
                    try:
                        print("🎬 Extracting HeyGen-ready host script...")
                        from text_processing import (
                            extract_heygen_host_script,
                            generate_heygen_curl_commands
                        )

                        heygen_script = extract_heygen_host_script(
                            final_script_content
                        )

                        if heygen_script:
                            heygen_section = f"\n\n{'=' * 80}\n"
                            heygen_section += "# 🎬 HEYGEN READY SCRIPT\n"
                            heygen_section += f"{'=' * 80}\n\n"
                            heygen_section += heygen_script

                            # Append to markdown file
                            with open(script_file, "a", encoding="utf-8") as f:
                                f.write(heygen_section)
                            print(f"✅ HeyGen section appended to: "
                                  f"{script_file}")

                            # Generate curl commands for HeyGen API
                            print("🚀 Generating HeyGen API curl commands...")
                            curl_commands = generate_heygen_curl_commands(
                                final_script_content + heygen_section,
                                script_number  # Use 4-digit script number instead of full title
                            )

                            if curl_commands:
                                # Append curl commands to markdown file
                                with open(script_file, "a",
                                          encoding="utf-8") as f:
                                    f.write(f"\n\n{curl_commands}\n")
                                curl_msg = (f"✅ HeyGen curl commands "
                                            f"appended to: {script_file}")
                                print(curl_msg)

                                # Create executable bash script with all curls
                                bash_script_path = str(script_file).replace(
                                    '.md', '_heygen_curls.sh'
                                )
                                try:
                                    # Extract curl commands by splitting
                                    parts = curl_commands.split(
                                        'curl --location')
                                    curl_list = []
                                    for part in parts[1:]:  # Skip first
                                        curl_cmd = 'curl --location' + \
                                            part.split('\n\n')[0]
                                        curl_list.append(curl_cmd)

                                    with open(bash_script_path, 'w', encoding='utf-8') as bash_file:
                                        bash_file.write('#!/bin/bash\n\n')
                                        bash_file.write(
                                            f'# HeyGen API Curl Commands for: {script_topic}\n')
                                        bash_file.write(
                                            f'# Generated: {sanitize_filename(script_topic)}\n')
                                        bash_file.write(
                                            f'# Total commands: {len(curl_list)}\n\n')

                                        for i, curl_cmd in enumerate(curl_list, 1):
                                            bash_file.write(
                                                f'echo "📹 Executing curl command {i}/{len(curl_list)}..."\n')
                                            bash_file.write(curl_cmd + '\n\n')
                                            bash_file.write(
                                                f'echo "✅ Command {i} complete"\n')
                                            bash_file.write('echo ""\n\n')

                                        bash_file.write(
                                            'echo "🎉 All HeyGen videos queued!"\n')

                                    # Make script executable
                                    import stat
                                    st = os.stat(bash_script_path)
                                    os.chmod(bash_script_path,
                                             st.st_mode | stat.S_IEXEC)

                                    print(
                                        f"✅ Bash script created: {bash_script_path}")
                                    print(
                                        f"   Run with: bash {os.path.basename(bash_script_path)}")

                                except Exception as bash_error:
                                    print(
                                        f"⚠️ Could not create bash script: {bash_error}")

                                # Add to script for Word document
                                heygen_full = heygen_section
                                heygen_full += f"\n\n{curl_commands}\n"
                                final_script_with_youtube += heygen_full

                                chars = len(heygen_script)
                                words = len(heygen_script.split())
                                print(f"✅ HeyGen section added "
                                      f"({chars} characters, {words} words)")
                            else:
                                # Just add HeyGen script without curls
                                final_script_with_youtube += heygen_section
                                chars = len(heygen_script)
                                words = len(heygen_script.split())
                                print(f"✅ HeyGen section added "
                                      f"({chars} characters, {words} words)")
                                print("⚠️ Could not generate curl commands")
                        else:
                            print("⚠️ No host dialogue found for "
                                  "HeyGen section")

                    except Exception as heygen_error:
                        error_msg = str(heygen_error)
                        print(f"⚠️ HeyGen section generation error: "
                              f"{error_msg}")

                    # Re-read the complete markdown file to ensure Word doc has everything
                    print("📘 Creating Word document from complete markdown file...")
                    with open(script_file, "r", encoding="utf-8") as f:
                        complete_markdown_content = f.read()

                    await convert_markdown_to_word(complete_markdown_content, word_file, "")

                    # Verify Word file was created with all sections
                    if word_file.exists():
                        file_size = word_file.stat().st_size
                        print(
                            f"✅ Word document created with YouTube + HeyGen: {word_file} ({file_size} bytes)")
                    else:
                        print(f"❌ Word file was not created: {word_file}")

                    print(
                        f"✅ Word document updated with YouTube details: {word_file}")

                    # Display quick summary
                    summary = youtube_agent.get_quick_summary(
                        youtube_upload_details)
                    print(f"\n📊 Quick Summary:")
                    print(f"   • Filename: {summary['filename']}")
                    print(f"   • Title: {summary['title'][:60]}...")
                    print(f"   • Tags: {summary['tags_count']} tags")
                    print(
                        f"   • Description: {summary['description_length']} chars")

                else:
                    error_msg = youtube_result.get("error", "Unknown error")
                    print(
                        f"❌ YouTube upload details generation failed: {error_msg}")
                    print("📝 Continuing workflow without upload details")

            except Exception as youtube_error:
                print(f"\n⚠️ YouTube upload details error: {youtube_error}")
                print("📝 Script creation will continue without YouTube metadata")

            # Step 4.8: Generate Emotional Thumbnails (using YouTube upload details)
            try:
                print(f"\n🖼️ STEP 4.8: Emotional Thumbnail Generation")
                print("-" * 55)

                # Debug: Show Python environment being used
                import sys
                print(f"🐍 Using Python: {sys.executable}")
                print(f"🐍 Python version: {sys.version.split()[0]}")

                from tools.media.emotional_thumbnail_generator import (
                    EmotionalThumbnailGenerator,
                )

                # Initialize generator
                thumbnail_gen = EmotionalThumbnailGenerator()
                print("✅ Emotional thumbnail generator initialized")

                # Generate 6 variations
                print("🚀 Generating 6 emotional thumbnail variations...")
                thumbnail_results = thumbnail_gen.generate_all_thumbnails(
                    script_title=script_topic,
                    script_content=final_script_content,
                    youtube_upload_details=youtube_upload_details
                )

                if thumbnail_results and thumbnail_results.get("variations"):
                    variations = thumbnail_results["variations"]
                    print(
                        f"\n✅ Generated {len(variations)} thumbnail variations")

                    # Display summary
                    for var in variations[:3]:  # Show first 3 details
                        print(
                            f"   • {var['emotion']}: {Path(var['filename']).name}")
                    if len(variations) > 3:
                        print(
                            f"   • ... and {len(variations) - 3} more variations")

                    print(
                        f"\n📁 Thumbnails saved to: {thumbnail_results['output_dir']}")

                    if thumbnail_results.get("base_text"):
                        print(
                            f"💬 Used thumbnail text: {thumbnail_results['base_text']}")
                else:
                    print(f"\n⚠️ No thumbnails generated")

            except Exception as thumb_error:
                print(
                    f"\n⚠️ Emotional thumbnail generation error: {thumb_error}")
                print("📝 Script creation will continue without thumbnails")

            # Step 5: Generate demo packages from the script
            try:
                print(f"\n🎥 STEP 5: Demo Package Generation")
                print("-" * 50)

                from linedrive_azure.agents.openai_demo_agent_client import (
                    OpenAIDemoAgentClient,
                )

                demo_client = OpenAIDemoAgentClient()
                demo_result = demo_client.generate_demo_packages(
                    final_script_with_tools,
                    max_tokens=12000,
                    audience=audience
                )

                if demo_result.get("success"):
                    demo_packages = demo_result["response"]
                    print(
                        f"✅ Demo packages created ({len(demo_packages)} characters)")

                    # Apply enhanced formatting to demo packages to preserve tools
                    from text_processing import enhance_demo_packages_formatting

                    enhanced_demo_packages = enhance_demo_packages_formatting(
                        demo_packages
                    )
                    print(f"✅ Demo packages enhanced with tool formatting")

                    # Create separate directory for demo packages
                    demo_output_dir = Path.home() / "Dev/Scripts"
                    demo_output_dir.mkdir(parents=True, exist_ok=True)

                    # Extract HeyGen-ready spoken content from demos
                    from text_processing import extract_demo_heygen_content

                    demo_heygen_content = extract_demo_heygen_content(
                        enhanced_demo_packages
                    )

                    # Prepare complete content with HeyGen section
                    complete_demo_content = enhanced_demo_packages
                    if demo_heygen_content:
                        complete_demo_content += f"\n\n{'=' * 80}\n"
                        complete_demo_content += "# 🎬 HEYGEN SECTION - Spoken Content Only\n"
                        complete_demo_content += f"{'=' * 80}\n\n"
                        complete_demo_content += demo_heygen_content
                        print(f"✅ HeyGen section prepared "
                              f"({len(demo_heygen_content)} characters)")

                    # Save demo packages (with enhanced formatting AND HeyGen section)
                    demo_file = (
                        demo_output_dir
                        / f"{sanitized_topic}_demo_packages_{timestamp}.md"
                    )
                    with open(demo_file, "w", encoding="utf-8") as f:
                        f.write(f"# Demo Packages for: {script_topic}\n")
                        f.write(
                            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        )
                        f.write(complete_demo_content)

                    print(f"📦 Demo packages saved: {demo_file}")

                    # Generate HeyGen curl commands for demo packages
                    if demo_heygen_content:
                        print("\n🎬 Generating HeyGen curl commands for demos...")
                        from text_processing import generate_heygen_curl_commands

                        demo_curl_commands = generate_heygen_curl_commands(
                            complete_demo_content,
                            # Use script number + Demo prefix
                            f"{script_number}-Demo"
                        )

                        if demo_curl_commands:
                            # Append curl commands to demo markdown file
                            with open(demo_file, "a", encoding="utf-8") as f:
                                f.write(f"\n\n{demo_curl_commands}\n")
                            print(
                                f"✅ Demo curl commands appended to: {demo_file}")

                            # Create executable bash script for demo curls
                            demo_bash_script_path = str(demo_file).replace(
                                '.md', '_heygen_curls.sh'
                            )
                            try:
                                # Extract curl commands
                                parts = demo_curl_commands.split(
                                    'curl --location')
                                curl_list = []
                                for part in parts[1:]:  # Skip first empty part
                                    curl_cmd = 'curl --location' + \
                                        part.split('\n\n')[0]
                                    curl_list.append(curl_cmd)

                                with open(demo_bash_script_path, 'w', encoding='utf-8') as bash_file:
                                    bash_file.write('#!/bin/bash\n\n')
                                    bash_file.write(
                                        f'# HeyGen API Curl Commands for Demo Packages: {script_topic}\n')
                                    bash_file.write(
                                        f'# Generated: {timestamp}\n')
                                    bash_file.write(
                                        f'# Total demo commands: {len(curl_list)}\n\n')

                                    for i, curl_cmd in enumerate(curl_list, 1):
                                        bash_file.write(
                                            f'echo "📹 Executing demo curl command {i}/{len(curl_list)}..."\n')
                                        bash_file.write(curl_cmd + '\n\n')
                                        bash_file.write(
                                            f'echo "✅ Demo command {i} complete"\n')
                                        bash_file.write('echo ""\n\n')

                                    bash_file.write(
                                        'echo "🎉 All demo HeyGen videos queued!"\n')

                                # Make script executable
                                Path(demo_bash_script_path).chmod(0o755)
                                print(
                                    f"✅ Demo bash script created: {demo_bash_script_path}")

                            except Exception as bash_error:
                                print(
                                    f"⚠️ Demo bash script creation failed: {bash_error}")
                        else:
                            print("⚠️ No demo curl commands generated")

                    # Convert enhanced demo packages to Word document (with HeyGen section)
                    try:
                        demo_word_file = (
                            demo_output_dir
                            / f"{sanitized_topic}_demo_packages_{timestamp}.docx"
                        )
                        print(
                            f"🔄 Converting demo packages to Word document: {demo_word_file}"
                        )
                        await convert_markdown_to_word(
                            complete_demo_content, demo_word_file, ""
                        )

                        # Verify Word file was created
                        if demo_word_file.exists():
                            file_size = demo_word_file.stat().st_size
                            print(
                                f"📘 Demo packages Word document created: {demo_word_file} ({file_size} bytes)"
                            )
                        else:
                            print(
                                f"❌ Demo packages Word file was not created: {demo_word_file}"
                            )

                    except Exception as word_error:
                        print(
                            f"⚠️ Demo packages Word conversion failed: {word_error}")
                        print("📝 Demo packages Markdown file still available")

                    # Try to split into developer and everyday sections
                    split_marker = "2) EVERYDAY-VIEWER DEMO PACKAGE"
                    if split_marker in enhanced_demo_packages:
                        split_index = enhanced_demo_packages.find(split_marker)
                        developer_demos = enhanced_demo_packages[:split_index].strip(
                        )
                        everyday_demos = enhanced_demo_packages[split_index:].strip(
                        )

                        # Save separate files
                        dev_file = (
                            demo_output_dir
                            / f"{sanitized_topic}_developer_demos_{timestamp}.md"
                        )
                        everyday_file = (
                            demo_output_dir
                            / f"{sanitized_topic}_everyday_demos_{timestamp}.md"
                        )

                        with open(dev_file, "w", encoding="utf-8") as f:
                            f.write(
                                f"# Developer Demo Package: {script_topic}\n")
                            f.write(
                                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            )
                            f.write(developer_demos)

                        with open(everyday_file, "w", encoding="utf-8") as f:
                            f.write(
                                f"# Everyday Viewer Demo Package: {script_topic}\n")
                            f.write(
                                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            )
                            f.write(everyday_demos)

                        print(f"👨‍💻 Developer demos saved: {dev_file}")
                        print(f"👥 Everyday demos saved: {everyday_file}")

                        # Convert individual demo files to Word
                        try:
                            # Developer demos to Word
                            dev_word_file = (
                                demo_output_dir
                                / f"{sanitized_topic}_developer_demos_{timestamp}.docx"
                            )
                            await convert_markdown_to_word(
                                developer_demos, dev_word_file, ""
                            )
                            if dev_word_file.exists():
                                dev_size = dev_word_file.stat().st_size
                                print(
                                    f"📘 Developer demos Word: {dev_word_file.name} ({dev_size} bytes)"
                                )

                            # Everyday demos to Word
                            everyday_word_file = (
                                demo_output_dir
                                / f"{sanitized_topic}_everyday_demos_{timestamp}.docx"
                            )
                            await convert_markdown_to_word(
                                everyday_demos, everyday_word_file, ""
                            )
                            if everyday_word_file.exists():
                                everyday_size = everyday_word_file.stat().st_size
                                print(
                                    f"📘 Everyday demos Word: {everyday_word_file.name} ({everyday_size} bytes)"
                                )

                        except Exception as split_word_error:
                            print(
                                f"⚠️ Individual demo Word conversion failed: {split_word_error}"
                            )

                        print("✅ Demo generation completed successfully")
                    else:
                        print(
                            "⚠️ Could not split demo sections - saved as single file")
                else:
                    print(
                        f"⚠️ Demo generation failed: {demo_result.get('error', 'Unknown error')}"
                    )
                    print("📝 Script files still available without demos")

            except Exception as demo_error:
                print(f"⚠️ Demo generation error: {demo_error}")
                print("📝 Script files still available without demos")

            # Display workflow statistics
            chapters_count = result.get("chapters_count", 0)
            if chapters_count > 0:
                print(f"\n📊 Workflow Statistics:")
                print(f"   📝 Chapters written individually: {chapters_count}")
                target_minutes = result.get("target_minutes_per_chapter", 0)
                if target_minutes > 0:
                    print(
                        f"   ⏱️ Target minutes per chapter: {target_minutes}+")

            print("\n📁 Script files saved to: ~/Dev/Scripts/")
            print("📦 Demo packages saved to: ~/Dev/Scripts/")
            print("🎬 Enhanced B-roll videos with contextual keywords applied!")

        else:
            error_msg = result.get("error", "Unknown error occurred")
            print(f"\n❌ 4-Agent workflow failed: {error_msg}")

    except Exception as e:
        print(f"\n❌ Workflow error: {e}")
        import traceback

        print(f"🔍 Error details: {traceback.format_exc()}")
        print("📝 Please check your configuration and try again")


async def run_script_polisher_workflow():
    """Script Polisher workflow with enhanced B-roll processing"""
    print("🪄 Script Polisher → Demo Workflow")
    print("=" * 60)
    print("This 2-agent workflow will:")
    print(
        "1. 🪄 Script Polisher: Polish your near-final script with chapters, visual cues, and tools"
    )
    print("2. 🎥 Demo Generator: Create demo packages from the polished script")
    print("3. 🎬 Enhanced B-roll: Download contextual videos with better keywords")
    print()
    print("Perfect for scripts that need final production preparation!")
    print()

    try:
        # Get script input
        print("📝 SCRIPT INPUT")
        print("-" * 30)
        print("Provide your near-final script that needs polishing:")
        print("  1. Load from file")
        print("  2. Paste script content")

        try:
            input_choice = input("\n👆 Select input method (1-2): ").strip()
        except EOFError:
            print("\n❌ No input available. Exiting.")
            return

        script_content = ""

        if input_choice == "1":
            # Load from file
            scripts_dir = Path.home() / "Dev/Scripts"
            if scripts_dir.exists():
                print(f"\n📁 Looking for scripts in: {scripts_dir}")
                script_files = list(scripts_dir.glob("*.md"))
                if script_files:
                    # Sort by modification date (most recent first)
                    script_files.sort(
                        key=lambda f: f.stat().st_mtime, reverse=True)

                    print("\n📋 10 Most Recent Script Files:")
                    print("-" * 50)
                    for i, script_file in enumerate(script_files[:10], 1):
                        file_size = script_file.stat().st_size
                        # Get modification time and format it
                        mod_time = datetime.fromtimestamp(
                            script_file.stat().st_mtime)
                        date_str = mod_time.strftime("%Y-%m-%d %H:%M")
                        print(f"  {i}. {script_file.name}")
                        print(f"     📅 {date_str} | 📄 {file_size} bytes")

                    try:
                        file_choice = input(
                            f"\n👆 Select file " f"(1-{min(len(script_files), 10)}): "
                        ).strip()
                        file_idx = int(file_choice) - 1
                        if 0 <= file_idx < len(script_files):
                            selected_file = script_files[file_idx]
                            script_content = selected_file.read_text(
                                encoding="utf-8")
                            print(
                                f"✅ Loaded script: {selected_file.name} "
                                f"({len(script_content)} characters)"
                            )
                        else:
                            print("❌ Invalid file selection.")
                            return
                    except (ValueError, EOFError):
                        print("❌ Invalid selection.")
                        return
                else:
                    print("❌ No .md script files found.")
                    return
            else:
                print("❌ Scripts directory not found.")
                return

        elif input_choice == "2":
            # Paste script content
            print(
                "\n📝 Paste your script content (type 'END_SCRIPT' on a new line when finished):"
            )
            script_lines = []
            try:
                while True:
                    line = input()
                    if line.strip() == "END_SCRIPT":
                        break
                    script_lines.append(line)
                script_content = "\n".join(script_lines)
                print(
                    f"\n✅ Script content received ({len(script_content)} characters)"
                )
            except EOFError:
                script_content = "\n".join(script_lines)
                print(
                    f"\n✅ Script content received ({len(script_content)} characters)"
                )

        if not script_content.strip():
            print("❌ No script content provided. Exiting.")
            return

        # Get additional workflow parameters
        print("\n🎯 POLISHING CONFIGURATION")
        print("-" * 30)

        # Get target audience
        try:
            audience = input(
                "👥 Enter target audience (or Enter for 'general'): "
            ).strip()
        except EOFError:
            audience = "general"
            print(f"   Using default (EOF): {audience}")
        if not audience:
            audience = "general"
            print(f"   Using default: {audience}")

        # Get production type
        try:
            production_type = input(
                "🎬 Enter production type (video/podcast/social, or Enter for 'video'): "
            ).strip()
        except EOFError:
            production_type = "video"
            print(f"   Using default (EOF): {production_type}")
        if not production_type:
            production_type = "video"
            print(f"   Using default: {production_type}")

        # Extract or get script title
        script_title = extract_script_title(script_content)
        print(f"📝 Detected script title: '{script_title}'")

        print("\n🔄 AGENT WORKFLOW EXECUTION")
        print("=" * 50)

        # Step 1: Polish the script
        print("\n🪄 STEP 1: Script Polishing")
        print("-" * 40)
        print("🚀 Initializing script polisher agent...")

        try:
            from linedrive_azure.agents.script_polisher_agent_client import (
                ScriptPolisherAgentClient,
            )

            polisher_agent = ScriptPolisherAgentClient()
            print("✅ Script polisher agent initialized")

            print(
                "🔄 Polishing script with chapters, visual cues, and tool integration..."
            )
            print(f"📝 Script length: {len(script_content)} characters")
            print(f"📋 Script title: {script_title}")
            print(f"👥 Target audience: {audience}")
            print(f"🎬 Production type: {production_type}")
            print(f"\n⏳ Sending to Azure AI Agent... (this will take 1-3 minutes)")
            print("=" * 60)

            polish_result = polisher_agent.polish_script(
                raw_script=script_content,
                script_title=script_title,
                target_audience=audience,
                production_type=production_type,
                timeout=300,
            )

            if polish_result.get("success", False):
                polished_script = polish_result.get("response", "")
                print(
                    f"✅ Script polished successfully ({len(polished_script)} characters)"
                )

                # Generate script number for HeyGen
                script_number = datetime.now().strftime("%H%M")
                print(f"🔢 Script Number: {script_number}")

                # Save polished script
                polished_scripts_dir = Path.home() / "Dev/Scripts/Polished Scripts"
                polished_scripts_dir.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_title = sanitize_filename(script_title)
                polished_filename = f"{safe_title}_polished_{timestamp}.md"
                polished_path = polished_scripts_dir / polished_filename

                polished_path.write_text(polished_script, encoding="utf-8")
                print(f"📄 Polished script saved: {polished_path}")

                # Generate HeyGen section and curl commands for polished script
                print("\n🎬 STEP 1.6: Generating HeyGen Content")
                print("-" * 40)
                try:
                    from text_processing import (
                        extract_heygen_host_script,
                        generate_heygen_curl_commands
                    )

                    heygen_script = extract_heygen_host_script(polished_script)

                    if heygen_script:
                        heygen_section = f"\n\n{'=' * 80}\n"
                        heygen_section += "# 🎬 HEYGEN READY SCRIPT\n"
                        heygen_section += f"{'=' * 80}\n\n"
                        heygen_section += heygen_script
                        print(
                            f"✅ HeyGen section generated ({len(heygen_script)} characters)")

                        # Append HeyGen section to polished script
                        polished_script_with_heygen = polished_script + heygen_section

                        # Update the markdown file with HeyGen section
                        polished_path.write_text(
                            polished_script_with_heygen, encoding="utf-8")
                        print(f"✅ HeyGen section added to: {polished_path}")

                        # Generate curl commands
                        curl_commands = generate_heygen_curl_commands(
                            polished_script_with_heygen,
                            script_number  # Use script number instead of full title
                        )

                        if curl_commands:
                            # Save bash script
                            bash_script_filename = f"{safe_title}_polished_heygen_curls_{timestamp}.sh"
                            bash_script_path = polished_scripts_dir / bash_script_filename

                            bash_script_path.write_text(
                                curl_commands, encoding="utf-8")
                            bash_script_path.chmod(0o755)  # Make executable
                            print(
                                f"✅ HeyGen curl bash script saved: {bash_script_path}")
                        else:
                            print(
                                "⚠️ No curl commands generated (no chapters found)")
                    else:
                        print(
                            "⚠️ HeyGen section generation skipped (no chapters found)")
                        polished_script_with_heygen = polished_script

                except Exception as heygen_error:
                    print(f"⚠️ HeyGen generation failed: {heygen_error}")
                    polished_script_with_heygen = polished_script

                # Create teleprompter version of polished script
                print("\n📺 STEP 1.5: Creating Teleprompter Version")
                print("-" * 40)
                teleprompter_content = extract_teleprompter_text(
                    polished_script)

                # Save teleprompter version
                teleprompter_filename = f"{safe_title}_teleprompter_{timestamp}.md"
                teleprompter_path = polished_scripts_dir / teleprompter_filename
                teleprompter_path.write_text(
                    teleprompter_content, encoding="utf-8")
                print(f"📺 Teleprompter version saved: {teleprompter_path}")

                # Convert teleprompter version to Word document
                teleprompter_word_filename = (
                    f"{safe_title}_teleprompter_{timestamp}.docx"
                )
                teleprompter_word_path = (
                    polished_scripts_dir / teleprompter_word_filename
                )

                try:
                    await convert_markdown_to_word(
                        teleprompter_content, teleprompter_word_path, ""
                    )
                    if teleprompter_word_path.exists():
                        file_size = teleprompter_word_path.stat().st_size
                        print(
                            f"📺 Teleprompter Word document created: {teleprompter_word_path} ({file_size} bytes)"
                        )
                except Exception as word_error:
                    print(
                        f"⚠️ Teleprompter Word conversion failed: {word_error}")

                # Convert polished script to Word document (with HeyGen section)
                polished_word_filename = f"{safe_title}_polished_{timestamp}.docx"
                polished_word_path = polished_scripts_dir / polished_word_filename

                try:
                    await convert_markdown_to_word(
                        polished_script_with_heygen, polished_word_path, ""
                    )
                    if polished_word_path.exists():
                        file_size = polished_word_path.stat().st_size
                        print(
                            f"📘 Polished script Word document created: {polished_word_path} ({file_size} bytes)"
                        )
                except Exception as word_error:
                    print(
                        f"⚠️ Polished script Word conversion failed: {word_error}")

            else:
                print(
                    f"❌ Script polishing failed: {polish_result.get('error', 'Unknown error')}"
                )
                return

        except Exception as e:
            print(f"❌ Error initializing script polisher: {e}")
            return

        # Step 1.7: Enhanced B-roll processing for polished script
        try:
            print(f"\n🎬 STEP 1.7: ENHANCED B-ROLL DOWNLOAD WITH CONTEXTUAL KEYWORDS")
            print("-" * 55)
            print("🔄 Using polished script for better visual cue extraction...")

            broll_dir = await extract_enhanced_visual_cues_and_download_broll(
                polished_script, script_title, timestamp
            )
            if broll_dir:
                print(f"\n✅ Enhanced B-roll videos downloaded to: {broll_dir}")
            else:
                print(f"\n⚠️ Enhanced B-roll video download skipped or failed")
        except Exception as broll_error:
            print(f"\n❌ Enhanced B-roll download error: {broll_error}")
            print("📝 Script polishing will continue without b-roll videos")

        # Step 1.8: Generate YouTube Upload Details
        youtube_upload_details = None  # Initialize outside try block
        try:
            print(f"\n📺 STEP 1.8: YOUTUBE UPLOAD DETAILS GENERATION")
            print("-" * 55)

            from linedrive_azure.agents import YouTubeUploadDetailsAgentClient

            youtube_agent = YouTubeUploadDetailsAgentClient()
            print("✅ YouTube Upload Details agent initialized")

            print("🚀 Generating upload details from polished script...")
            youtube_result = youtube_agent.generate_upload_details(
                script_content=polished_script,
                script_title=script_title,
                target_audience=audience,
                video_length=None,  # Polisher workflow doesn't track length
                primary_keywords=None,
                channel_focus=None,
                timeout=180
            )

            if youtube_result.get("success", False):
                youtube_upload_details = youtube_result.get(
                    "upload_details", "")
                print(
                    f"✅ YouTube upload details generated ({len(youtube_upload_details)} characters)")

                # Save standalone YouTube upload details file
                youtube_filename = f"{safe_title}_youtube_upload_{timestamp}.md"
                youtube_path = polished_scripts_dir / youtube_filename
                youtube_path.write_text(
                    youtube_upload_details, encoding="utf-8")
                print(f"📄 YouTube upload details saved: {youtube_path}")

                # Append YouTube details to the polished script markdown file
                print("📝 Appending YouTube details to polished script markdown...")
                youtube_section = f"\n\n{'=' * 80}\n"
                youtube_section += "# 📺 YOUTUBE UPLOAD DETAILS\n"
                youtube_section += f"{'=' * 80}\n\n"
                youtube_section += youtube_upload_details

                with open(polished_path, "a", encoding="utf-8") as f:
                    f.write(youtube_section)
                print(f"✅ YouTube details appended to: {polished_path}")

                # Recreate Word document with YouTube details included
                print("📘 Updating polished Word document with YouTube details...")
                polished_with_youtube = polished_script_with_heygen + youtube_section
                await convert_markdown_to_word(polished_with_youtube, polished_word_path, "")
                print(
                    f"✅ Polished Word document updated: {polished_word_path}")

                # Display quick summary
                summary = youtube_agent.get_quick_summary(
                    youtube_upload_details)
                print(f"\n📊 Quick Summary:")
                print(f"   • Filename: {summary['filename']}")
                print(f"   • Title: {summary['title'][:60]}...")
                print(f"   • Tags: {summary['tags_count']} tags")
                print(
                    f"   • Description: {summary['description_length']} chars")

            else:
                error_msg = youtube_result.get("error", "Unknown error")
                print(
                    f"❌ YouTube upload details generation failed: {error_msg}")
                print("📝 Continuing workflow without upload details")

        except Exception as youtube_error:
            print(f"\n❌ YouTube upload details error: {youtube_error}")
            print("📝 Script polishing will continue without YouTube metadata")

        # Step 2: Generate demo packages
        print("\n🎥 STEP 2: Demo Package Generation")
        print("-" * 40)
        print("🔄 Initializing demo creation agent...")

        try:
            from linedrive_azure.agents.openai_demo_agent_client import (
                OpenAIDemoAgentClient,
            )

            demo_agent = OpenAIDemoAgentClient()
            print("✅ Demo creation agent initialized")

            print("🚀 Generating demo packages from polished script...")
            demo_result = demo_agent.generate_demo_packages(
                script_text=polished_script, max_tokens=8000, audience=audience
            )

            if demo_result.get("success", False):
                demo_packages = demo_result.get("response", "")
                print(
                    f"✅ Demo packages generated ({len(demo_packages)} characters)")

                # Enhanced formatting to preserve tool formatting
                print("✨ Enhancing demo packages with bold field formatting...")
                from text_processing import (
                    enhance_demo_packages_formatting,
                    extract_demo_heygen_content
                )

                enhanced_demo_packages = enhance_demo_packages_formatting(
                    demo_packages)

                # Extract HeyGen-ready spoken content from demos
                demo_heygen_content = extract_demo_heygen_content(
                    enhanced_demo_packages
                )

                # Prepare complete content with HeyGen section
                complete_demo_content = enhanced_demo_packages
                if demo_heygen_content:
                    complete_demo_content += f"\n\n{'=' * 80}\n"
                    complete_demo_content += "# 🎬 HEYGEN READY SCRIPT\n"
                    complete_demo_content += f"{'=' * 80}\n\n"
                    complete_demo_content += demo_heygen_content
                    print(
                        f"✅ Demo HeyGen section prepared ({len(demo_heygen_content)} characters)")

                    # Generate curl commands for demo HeyGen content
                    from text_processing import generate_heygen_curl_commands
                    demo_curl_commands = generate_heygen_curl_commands(
                        complete_demo_content,
                        script_number  # Use script number instead of full title
                    )

                    if demo_curl_commands:
                        # Save bash script for demo curl commands
                        demo_bash_filename = f"{safe_title}_demo_heygen_curls_{timestamp}.sh"
                        demo_bash_path = polished_scripts_dir / demo_bash_filename
                        demo_bash_path.write_text(
                            demo_curl_commands, encoding="utf-8")
                        demo_bash_path.chmod(0o755)  # Make executable
                        print(
                            f"✅ Demo HeyGen curl bash script saved: {demo_bash_path}")
                    else:
                        print("⚠️ No demo curl commands generated")

                # Save demo packages (with HeyGen section)
                demo_filename = f"{safe_title}_demo_{timestamp}.md"
                demo_path = polished_scripts_dir / demo_filename
                demo_path.write_text(complete_demo_content, encoding="utf-8")
                print(f"📄 Enhanced demo packages saved: {demo_path}")

                # Create teleprompter version of demo packages
                print("\n📺 Creating teleprompter version of demo packages...")
                demo_teleprompter_content = extract_teleprompter_text(
                    enhanced_demo_packages
                )

                # Save demo teleprompter version
                demo_teleprompter_filename = (
                    f"{safe_title}_demo_teleprompter_{timestamp}.md"
                )
                demo_teleprompter_path = (
                    polished_scripts_dir / demo_teleprompter_filename
                )
                demo_teleprompter_path.write_text(
                    demo_teleprompter_content, encoding="utf-8"
                )
                print(
                    f"📺 Demo teleprompter version saved: {demo_teleprompter_path}")

                # Convert demo teleprompter to Word
                demo_teleprompter_word_filename = (
                    f"{safe_title}_demo_teleprompter_{timestamp}.docx"
                )
                demo_teleprompter_word_path = (
                    polished_scripts_dir / demo_teleprompter_word_filename
                )

                try:
                    await convert_markdown_to_word(
                        demo_teleprompter_content, demo_teleprompter_word_path, ""
                    )
                    if demo_teleprompter_word_path.exists():
                        file_size = demo_teleprompter_word_path.stat().st_size
                        print(
                            f"📺 Demo teleprompter Word document created: {demo_teleprompter_word_path} ({file_size} bytes)"
                        )
                except Exception as word_error:
                    print(
                        f"⚠️ Demo teleprompter Word conversion failed: {word_error}")

                # Convert to Word document (with HeyGen section)
                word_filename = f"{safe_title}_demo_{timestamp}.docx"
                word_path = polished_scripts_dir / word_filename

                try:
                    await convert_markdown_to_word(
                        complete_demo_content, word_path, ""
                    )
                    if word_path.exists():
                        file_size = word_path.stat().st_size
                        print(
                            f"📘 Demo Word document created: {word_path} ({file_size} bytes)"
                        )
                except Exception as word_error:
                    print(f"⚠️ Word document creation failed: {word_error}")

                print(
                    "✅ Script polishing, demo generation, and B-roll download completed!"
                )
                print("\n📝 FILES CREATED:")
                print(f"   • Polished Script: {polished_path.name}")
                print(f"   • Teleprompter Script: {teleprompter_path.name}")
                print(f"   • Demo Packages: {demo_path.name}")
                print(f"   • Demo Teleprompter: {demo_teleprompter_path.name}")
                print("   • Word versions of all above files")
                if broll_dir:
                    print(
                        f"   • Enhanced B-roll videos: {Path(broll_dir).name}/")

            else:
                error_msg = demo_result.get("error", "Unknown error")
                print(f"❌ Demo generation failed: {error_msg}")
                print("� Polished script still available")

        except Exception as e:
            print(f"❌ Error in demo generation: {e}")
            print("📝 Polished script still available")

        print("\n📁 Files saved to: ~/Dev/Scripts/Polished Scripts/")
        print("🔧 Workflow type: 2_agent_polisher_demo_with_enhanced_broll")

    except Exception as e:
        print(f"❌ Error in polisher workflow: {e}")
        import traceback

        print(f"🔍 Error details: {traceback.format_exc()}")
    finally:
        try:
            input("\n⏎ Press Enter to continue...")
        except EOFError:
            pass  # Handle piped input gracefully


# Enhanced B-roll Visual Cue Extraction Functions


def extract_contextual_keywords(script_content: str) -> list:
    """Extract specific contextual keywords from script content for better
    B-roll search - enhanced to detect tools, websites, and products"""
    import re

    keywords = []
    lines = script_content.split("\n")

    # Enhanced patterns for tools, brands, and specific technologies
    brand_patterns = [
        # Major tech companies and platforms
        r"\b(Netflix|Amazon|Google|Apple|Microsoft|Meta|Facebook|Twitter|X\.com|"
        r"Instagram|TikTok|YouTube|LinkedIn|Slack|Zoom|Teams|Discord)\b",
        # AI and ML tools/platforms
        r"\b(ChatGPT|GPT-4|OpenAI|Claude|Anthropic|Gemini|Bard|Copilot|"
        r"Midjourney|DALL-E|Stable Diffusion|Hugging Face|LangChain)\b",
        # Productivity and business tools
        r"\b(Notion|Airtable|Monday\.com|Asana|Trello|Salesforce|HubSpot|"
        r"Canva|Figma|Adobe|Photoshop|Illustrator|InDesign)\b",
        # Development and tech tools
        r"\b(GitHub|GitLab|Docker|Kubernetes|AWS|Azure|GCP|Visual Studio|"
        r"VS Code|PyCharm|Jupyter|Anaconda|TensorFlow|PyTorch)\b",
        # Streaming and content platforms
        r"\b(Spotify|Apple Music|Twitch|OnlyFans|Patreon|Substack|Medium|"
        r"WordPress|Shopify|Squarespace)\b",
        # Financial and crypto
        r"\b(PayPal|Venmo|Cash App|Coinbase|Bitcoin|Ethereum|Robinhood|"
        r"Stripe|Square|QuickBooks)\b",
    ]

    # Technical terms and concepts
    technical_patterns = [
        r"\b(AI|artificial intelligence|machine learning|deep learning|neural networks|"
        r"blockchain|cryptocurrency|automation|robotics|IoT|cloud computing)\b",
        r"\b(productivity|workflow|efficiency|optimization|analytics|data science|"
        r"big data|visualization|dashboard|reporting)\b",
        r"\b(healthcare|telemedicine|fintech|edtech|martech|proptech|"
        r"e-commerce|digital marketing|content creation)\b",
        r"\b(remote work|hybrid work|collaboration|video conferencing|"
        r"project management|agile|scrum|DevOps)\b",
    ]

    # Industry-specific terms
    industry_patterns = [
        r"\b(startup|unicorn|venture capital|IPO|SaaS|API|SDK|plugin|"
        r"integration|platform|ecosystem)\b",
        r"\b(streaming|podcasting|creator economy|influencer|social media|"
        r"content marketing|SEO|digital advertising)\b",
        r"\b(cybersecurity|privacy|GDPR|compliance|encryption|"
        r"two-factor authentication|biometrics)\b",
    ]

    all_patterns = brand_patterns + technical_patterns + industry_patterns

    # Extract matches from script content
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or len(line) < 10:
            continue

        # Look for specific tools, brands, and technical terms
        for pattern in all_patterns:
            matches = re.findall(pattern, line, re.IGNORECASE)
            for match in matches:
                clean_match = match.strip()
                if clean_match and clean_match.lower() not in [
                    k.lower() for k in keywords
                ]:
                    keywords.append(clean_match)

    # Extract quoted phrases that might be product names or specific concepts
    quoted_phrases = re.findall(r'"([^"]{3,25})"', script_content)
    for phrase in quoted_phrases:
        if len(phrase.split()) <= 4:  # Keep short phrases only
            keywords.append(phrase)

    # Look for capitalized terms that might be products/tools (but be more selective)
    for line in lines:
        if len(line) < 100:  # Focus on shorter lines
            # Look for patterns like "Using [Tool]" or "with [Product]"
            tool_patterns = [
                r"using\s+([A-Z][a-zA-Z]{2,15})",
                r"with\s+([A-Z][a-zA-Z]{2,15})",
                r"through\s+([A-Z][a-zA-Z]{2,15})",
                r"via\s+([A-Z][a-zA-Z]{2,15})",
                r"on\s+([A-Z][a-zA-Z]{2,15})",
            ]

            for pattern in tool_patterns:
                matches = re.findall(pattern, line, re.IGNORECASE)
                for match in matches:
                    if match not in keywords and len(match) > 3:
                        keywords.append(match)

    # Return top contextual keywords (limit to avoid too many)
    return keywords[:15]


def convert_brand_to_generic_search(search_term: str) -> str:
    """
    Convert brand-specific search terms to generic alternatives that work better
    with stock video sites (which can't show copyrighted/trademarked content)
    """
    search_lower = search_term.lower()

    # Streaming and entertainment platforms
    brand_mappings = {
        'netflix': 'streaming service interface laptop',
        'youtube': 'video platform website browser',
        'spotify': 'music streaming app mobile',
        'twitch': 'live streaming platform gaming',
        'hulu': 'streaming video service television',
        'disney plus': 'streaming entertainment app',
        'amazon prime': 'streaming video subscription service',

        # Social media platforms
        'facebook': 'social media platform mobile phone',
        'instagram': 'social media photo app smartphone',
        'twitter': 'social media feed smartphone',
        'x.com': 'social media platform mobile',
        'tiktok': 'short video social app mobile',
        'linkedin': 'professional networking platform laptop',
        'snapchat': 'messaging app smartphone camera',

        # AI and tech tools
        'chatgpt': 'ai chatbot interface conversation',
        'openai': 'artificial intelligence technology',
        'claude': 'ai assistant text interface',
        'gemini': 'ai conversation interface',
        'bard': 'ai text generation interface',
        'midjourney': 'ai art generation computer',
        'dall-e': 'ai image generation software',

        # Productivity and collaboration
        'slack': 'team messaging collaboration tool',
        'zoom': 'video conference call meeting',
        'microsoft teams': 'video meeting collaboration software',
        'discord': 'voice chat community platform',
        'notion': 'productivity notes software interface',
        'asana': 'project management dashboard software',
        'trello': 'project board organization software',
        'monday.com': 'workflow management software',
        'airtable': 'database spreadsheet software interface',

        # Design and creative tools
        'figma': 'design software interface wireframe',
        'canva': 'graphic design editor software',
        'adobe': 'creative software design tool',
        'photoshop': 'image editing software interface',
        'illustrator': 'vector graphics design software',

        # Development and tech platforms
        'github': 'code repository development software',
        'docker': 'container virtualization technology',
        'aws': 'cloud computing dashboard interface',
        'azure': 'cloud platform dashboard technology',
        'google cloud': 'cloud computing services platform',

        # E-commerce and business
        'shopify': 'e-commerce store dashboard',
        'amazon': 'online shopping website browser',
        'ebay': 'online marketplace shopping',
        'etsy': 'handmade marketplace online store',

        # Finance and crypto
        'paypal': 'online payment service mobile',
        'venmo': 'mobile payment app smartphone',
        'coinbase': 'cryptocurrency exchange platform',
        'bitcoin': 'cryptocurrency digital currency',
        'robinhood': 'stock trading app mobile',
    }

    # Check each brand mapping
    for brand, generic_term in brand_mappings.items():
        if brand in search_lower:
            print(f"      🔄 Brand mapping: '{brand}' → '{generic_term}'")
            return generic_term

    # If no specific mapping, check for generic brand patterns
    if any(term in search_lower for term in ['interface', 'app', 'platform', 'service']):
        # Already has generic terms, just remove brand names
        for brand in brand_mappings.keys():
            search_lower = search_lower.replace(brand, '').strip()
        return search_lower if search_lower else 'professional software interface'

    return search_term


def generate_enhanced_visual_cue_variations(
    visual_cue: str, contextual_keywords: list
) -> list:
    """Generate smart search variations using specific contextual keywords"""
    import re

    variations = []

    # Add the original cue
    variations.append(visual_cue)

    # Create specific visual cues based on contextual keywords found in script
    for keyword in contextual_keywords[:8]:  # Use more keywords for variety
        keyword_lower = keyword.lower()

        # Platform-specific visual cues
        if keyword_lower in [
            "netflix",
            "youtube",
            "tiktok",
            "instagram",
            "spotify",
            "twitch",
            "linkedin",
        ]:
            # Try specific branded searches first
            variations.extend(
                [
                    f"{keyword} interface on computer screen",
                    f"person using {keyword} mobile app",
                    f"{keyword} streaming video content",
                    f"{keyword} user dashboard and navigation",
                ]
            )
            # Add generic but relevant fallbacks for when branded content isn't available
            if keyword_lower in ["netflix", "spotify"]:
                variations.extend(
                    [
                        "streaming service interface",
                        "video streaming platform",
                        "entertainment app on device",
                        "person watching streaming content",
                        "streaming video on laptop",
                        "mobile streaming app interface",
                    ]
                )
            elif keyword_lower == "youtube":
                variations.extend(
                    [
                        "video platform interface",
                        "content creator recording",
                        "video upload interface",
                        "social media content creation",
                    ]
                )
            elif keyword_lower in ["tiktok", "instagram"]:
                variations.extend(
                    [
                        "social media mobile app",
                        "social media content creation",
                        "vertical video content",
                        "mobile social platform",
                    ]
                )

        # AI/Tech tool specific cues
        elif keyword_lower in [
            "chatgpt",
            "openai",
            "claude",
            "copilot",
            "gemini",
            "bard",
            "midjourney",
        ]:
            variations.extend(
                [
                    f"{keyword} AI chat conversation",
                    f"person typing with {keyword} assistant",
                    f"{keyword} text generation interface",
                    f"{keyword} AI workflow demonstration",
                ]
            )

        # Big tech company cues
        elif keyword_lower in [
            "google",
            "microsoft",
            "apple",
            "amazon",
            "meta",
            "facebook",
        ]:
            variations.extend(
                [
                    f"{keyword} office building exterior",
                    f"{keyword} product showcase display",
                    f"{keyword} technology demonstration",
                    f"{keyword} headquarters campus view",
                ]
            )

        # Developer tools
        elif keyword_lower in [
            "github",
            "docker",
            "aws",
            "azure",
            "vscode",
            "jupyter",
            "kubernetes",
        ]:
            variations.extend(
                [
                    f"{keyword} code development screen",
                    f"developer using {keyword} platform",
                    f"{keyword} programming environment",
                    f"{keyword} cloud dashboard interface",
                ]
            )

        # Productivity tools
        elif keyword_lower in [
            "notion",
            "slack",
            "zoom",
            "teams",
            "asana",
            "trello",
            "monday.com",
        ]:
            # Try specific branded searches first
            variations.extend(
                [
                    f"{keyword} team collaboration session",
                    f"{keyword} productivity workspace",
                    f"remote meeting using {keyword}",
                    f"{keyword} project management board",
                ]
            )
            # Add generic but relevant fallbacks
            variations.extend(
                [
                    "team collaboration software",
                    "project management interface",
                    "remote work productivity tools",
                    "business communication platform",
                    "task management dashboard",
                    "team workspace interface",
                ]
            )

        # Financial/Crypto
        elif keyword_lower in [
            "bitcoin",
            "ethereum",
            "cryptocurrency",
            "paypal",
            "stripe",
        ]:
            variations.extend(
                [
                    f"{keyword} trading chart analysis",
                    f"{keyword} digital wallet interface",
                    f"{keyword} financial transaction",
                    f"{keyword} market price display",
                ]
            )

        # Creative tools
        elif keyword_lower in ["photoshop", "figma", "canva", "adobe"]:
            variations.extend(
                [
                    f"{keyword} creative design process",
                    f"designer using {keyword} software",
                    f"{keyword} graphic design workspace",
                    f"{keyword} creative project editing",
                ]
            )

        # E-commerce/Business
        elif keyword_lower in ["shopify", "salesforce", "hubspot"]:
            variations.extend(
                [
                    f"{keyword} business dashboard",
                    f"{keyword} e-commerce store setup",
                    f"{keyword} sales analytics screen",
                    f"{keyword} customer management system",
                ]
            )

        # Streaming/Content
        elif keyword_lower in ["twitch", "patreon", "substack", "medium"]:
            variations.extend(
                [
                    f"{keyword} content creator workspace",
                    f"{keyword} streaming setup studio",
                    f"{keyword} content publishing interface",
                    f"{keyword} audience engagement metrics",
                ]
            )

        # General tech/AI terms
        elif any(
            term in keyword_lower
            for term in [
                "ai",
                "artificial intelligence",
                "machine learning",
                "automation",
                "blockchain",
                "cloud",
            ]
        ):
            variations.extend(
                [
                    f"{keyword} technology visualization",
                    f"{keyword} data processing screen",
                    f"{keyword} innovation workspace",
                    f"{keyword} digital transformation",
                ]
            )

        else:
            # Generic but contextual variations for other specific keywords
            variations.extend(
                [
                    f"{keyword} professional environment",
                    f"{keyword} workplace demonstration",
                    f"{keyword} technology integration",
                    f"professional using {keyword} tools",
                ]
            )

    # Add some general enhanced variations
    base_words = visual_cue.lower().split()[:2]
    if base_words:
        base_term = " ".join(base_words)
        variations.extend(
            [
                f"modern {base_term} office setup",
                f"professional {base_term} workspace",
                f"sleek {base_term} technology display",
                f"hands working with {base_term} interface",
                f"{base_term} screen close-up view",
                f"business team discussing {base_term}",
            ]
        )

    # Remove duplicates while preserving order
    seen = set()
    unique_variations = []
    for variation in variations:
        if variation.lower() not in seen and len(variation.strip()) > 5:
            seen.add(variation.lower())
            unique_variations.append(variation)

    # Return diverse set of variations
    return unique_variations[:15]


async def extract_enhanced_visual_cues_and_download_broll(
    script_content: str, topic: str, timestamp: str
) -> str:
    """
    Enhanced visual cue extraction with contextual keyword analysis
    Uses both Pexels and Pixabay for diverse B-roll sources with duplicate detection
    """
    print(f"\n🎬 ENHANCED VISUAL CUES EXTRACTION FOR B-ROLL")
    print("=" * 55)

    try:
        # Import required modules
        import sys
        import re  # For filename cleaning

        sys.path.append("./tools/media")

        from pexels_video_downloader import PexelsVideoDownloader

        pexels_available = True

        # Check if Pixabay downloader exists
        try:
            from pixabay_video_downloader import PixabayVideoDownloader

            pixabay_available = True
        except ImportError:
            pixabay_available = False
            print("⚠️ Pixabay downloader not available, using Pexels only")

        # Extract contextual keywords from script content first
        print("🔍 Analyzing script for contextual keywords...")
        contextual_keywords = extract_contextual_keywords(script_content)

        if contextual_keywords:
            print(f"📊 Found {len(contextual_keywords)} contextual keywords:")
            for i, keyword in enumerate(contextual_keywords, 1):
                print(f"   {i}. {keyword}")
        else:
            print("   ⚠️ No specific contextual keywords found - using generic")

        # Create proper bRoll directory (same as downloaders use)
        broll_base_dir = Path.home() / "Dev/Videos/bRoll"
        broll_base_dir.mkdir(parents=True, exist_ok=True)

        topic_safe = sanitize_filename(topic)
        topic_broll_dir = broll_base_dir / f"broll_{topic_safe}_{timestamp}"
        topic_broll_dir.mkdir(exist_ok=True)

        print(f"📁 B-roll directory: {topic_broll_dir}")

        # Extract visual cues from script
        visual_cues = []
        lines = script_content.split("\n")

        print("\n🔍 Extracting Visual Cues from script...")

        # Look for explicit visual cue sections
        for i, line in enumerate(lines):
            line = line.strip()
            if line.lower().startswith("visual cue") or "visual:" in line.lower():
                cue_text = line.split(":", 1)[-1].strip()
                if len(cue_text) > 10:
                    visual_cues.append(cue_text)

                # Look at next few lines for additional context
                for j in range(1, 4):
                    if i + j < len(lines):
                        next_line = lines[i + j].strip()
                        if (
                            next_line
                            and not next_line.startswith("#")
                            and len(next_line) > 20
                        ):
                            # Extract additional context from surrounding text
                            context_words = next_line.split()[
                                :8]  # First 8 words
                            context_phrase = " ".join(context_words)
                            if context_phrase not in cue_text:
                                enhanced_cue = f"{cue_text} {context_phrase}"
                                visual_cues.append(enhanced_cue)
                            break

        # If no explicit visual cues found, generate enhanced ones from content
        if not visual_cues:
            print(
                "🔍 No explicit Visual Cues found. Generating smart contextual cues..."
            )

            # Create highly specific visual cues using extracted keywords
            # Prioritize specific tools and platforms over generic terms
            prioritized_keywords = []
            generic_keywords = []

            for keyword in contextual_keywords:
                keyword_lower = keyword.lower()
                # Check if keyword is a specific tool/platform
                if any(
                    tool in keyword_lower
                    for tool in [
                        "trello",
                        "asana",
                        "salesforce",
                        "hubspot",
                        "slack",
                        "zoom",
                        "notion",
                        "teams",
                        "monday.com",
                        "airtable",
                        "github",
                        "docker",
                        "aws",
                        "azure",
                        "netflix",
                        "youtube",
                        "spotify",
                        "photoshop",
                        "figma",
                        "canva",
                        "chatgpt",
                        "openai",
                        "claude",
                        "gemini",
                    ]
                ):
                    prioritized_keywords.append(keyword)
                else:
                    generic_keywords.append(keyword)

            # Use prioritized tools first, then fill with generic terms
            keywords_to_use = (prioritized_keywords + generic_keywords)[
                :8
            ]  # Use top 8 total

            print(f"🎯 Prioritized tools: {prioritized_keywords}")
            print(
                f"🔧 Keywords for visual cues: {keywords_to_use[:5]}..."
            )  # Show first 5

            for keyword in keywords_to_use:
                keyword_lower = keyword.lower()

                # Platform/Service specific cues
                if keyword_lower in [
                    "netflix",
                    "youtube",
                    "amazon",
                    "spotify",
                    "twitch",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} interface on laptop screen",
                            f"person browsing {keyword} content",
                            f"{keyword} mobile app interface",
                        ]
                    )

                # AI/Tech specific cues
                elif keyword_lower in [
                    "chatgpt",
                    "ai",
                    "openai",
                    "claude",
                    "gemini",
                    "bard",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} conversation interface",
                            f"person using {keyword} assistant",
                            f"{keyword} text generation screen",
                        ]
                    )

                # Big Tech company cues
                elif keyword_lower in [
                    "google",
                    "microsoft",
                    "apple",
                    "meta",
                    "facebook",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} office building campus",
                            f"{keyword} technology demonstration",
                            f"{keyword} product showcase",
                        ]
                    )

                # Development/Tech tools
                elif keyword_lower in [
                    "github",
                    "docker",
                    "vscode",
                    "aws",
                    "azure",
                    "kubernetes",
                ]:
                    visual_cues.extend(
                        [
                            f"developer using {keyword} platform",
                            f"{keyword} programming interface",
                            f"{keyword} development workspace",
                        ]
                    )

                # Business/Productivity tools - ENHANCED with more tools
                elif keyword_lower in [
                    "slack",
                    "zoom",
                    "notion",
                    "teams",
                    "trello",
                    "asana",
                    "monday.com",
                    "airtable",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} team collaboration workspace",
                            f"professional using {keyword} interface",
                            f"{keyword} project management dashboard",
                        ]
                    )

                # CRM/Sales tools - NEW CATEGORY
                elif keyword_lower in ["salesforce", "hubspot", "crm", "pipedrive"]:
                    visual_cues.extend(
                        [
                            f"{keyword} sales dashboard interface",
                            f"business professional using {keyword}",
                            f"{keyword} customer management system",
                        ]
                    )

                # Creative/Design tools - NEW CATEGORY
                elif keyword_lower in [
                    "photoshop",
                    "figma",
                    "canva",
                    "adobe",
                    "illustrator",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} creative design workspace",
                            f"designer using {keyword} software",
                            f"{keyword} graphic editing interface",
                        ]
                    )

                # Analytics/Data tools - NEW CATEGORY
                elif keyword_lower in [
                    "analytics",
                    "data science",
                    "tableau",
                    "powerbi",
                ]:
                    visual_cues.extend(
                        [
                            f"{keyword} dashboard with charts",
                            f"analyst using {keyword} software",
                            f"{keyword} data visualization screen",
                        ]
                    )

                # Workflow/Automation tools - NEW CATEGORY
                elif keyword_lower in ["workflow", "automation", "zapier", "ifttt"]:
                    visual_cues.extend(
                        [
                            f"{keyword} process automation interface",
                            f"professional setting up {keyword}",
                            f"{keyword} integration dashboard",
                        ]
                    )

                else:
                    # More specific generic cues based on keyword type
                    if any(
                        term in keyword_lower
                        for term in ["productivity", "project", "management"]
                    ):
                        visual_cues.extend(
                            [
                                f"{keyword} software interface",
                                f"team using {keyword} tools",
                            ]
                        )
                    elif any(
                        term in keyword_lower
                        for term in [
                            "artificial",
                            "intelligence",
                            "machine",
                            "learning",
                        ]
                    ):
                        visual_cues.extend(
                            [
                                f"{keyword} technology visualization",
                                f"{keyword} neural network display",
                            ]
                        )
                    else:
                        # Fallback for truly unknown tools
                        visual_cues.extend(
                            [
                                f"{keyword} professional software interface",
                                f"business team using {keyword} platform",
                            ]
                        )

            # Add topic-based cues enhanced with context
            topic_words = topic.lower().split()
            if contextual_keywords and len(topic_words) >= 2:
                top_keywords = contextual_keywords[:2]
                for kw in top_keywords:
                    visual_cues.extend(
                        [
                            f"{kw} and {' '.join(topic_words[:2])} integration",
                            f"professional using {kw} for {topic_words[0]}",
                            f"{kw} impact on {' '.join(topic_words[:2])}",
                        ]
                    )
            else:
                # Fallback with more specific generic cues
                visual_cues.extend(
                    [
                        f"{' '.join(topic_words[:2])} modern office workspace",
                        f"{' '.join(topic_words[:2])} technology demonstration",
                        f"business analytics and {topic_words[0]} data",
                        f"professional team discussing {topic_words[0]}",
                    ]
                )

            # Add some industry-specific visual elements
            topic_full = topic.lower()
            if "job" in topic_full or "career" in topic_full:
                visual_cues.extend(
                    [
                        "job interview professional setting",
                        "career development meeting",
                        "workplace diversity and inclusion",
                    ]
                )
            elif "technology" in topic_full or "ai" in topic_full:
                visual_cues.extend(
                    [
                        "futuristic technology interface",
                        "AI robot and human interaction",
                        "data center server room",
                    ]
                )
            elif "business" in topic_full:
                visual_cues.extend(
                    [
                        "corporate boardroom meeting",
                        "business handshake agreement",
                        "startup office environment",
                    ]
                )

        if not visual_cues:
            print("⚠️ No Visual Cues could be generated. Skipping b-roll.")
            return str(topic_broll_dir)

        print(f"✅ Generated {len(visual_cues)} enhanced visual cues:")
        for i, cue in enumerate(visual_cues, 1):
            cue_preview = cue[:60] + "..." if len(cue) > 60 else cue
            print(f"  {i}. {cue_preview}")

        # Initialize downloaders
        print(f"\n🔧 Initializing video downloaders...")

        # Initialize Pexels downloader
        pexels_downloader = PexelsVideoDownloader()
        pexels_downloader.output_dir = topic_broll_dir
        pexels_downloader.metadata_file = (
            topic_broll_dir / "pexels_video_metadata_log.json"
        )
        pexels_downloader.metadata_log = pexels_downloader._load_metadata_log()
        print("   ✅ Pexels downloader ready")

        # Initialize Pixabay downloader if available
        pixabay_downloader = None
        if pixabay_available:
            pixabay_downloader = PixabayVideoDownloader(
                api_key="52113911-b5f6394f010b214e1f07599f2"
            )
            pixabay_downloader.output_dir = topic_broll_dir
            pixabay_downloader.metadata_file = (
                topic_broll_dir / "pixabay_video_metadata_log.json"
            )
            pixabay_downloader.metadata_log = pixabay_downloader._load_metadata_log()
            print("   ✅ Pixabay downloader ready")

        total_sources = 2 if pixabay_available else 1
        print(
            f"   📊 Using {total_sources} video source{'s' if total_sources > 1 else ''}"
        )

        print(f"\n📥 DOWNLOADING ENHANCED B-ROLL VIDEOS FROM MULTIPLE SOURCES")
        print("=" * 60)

        downloaded_files = []
        downloaded_video_ids = set()  # Track video IDs to prevent duplicates
        used_search_terms = set()  # Track used search terms for uniqueness

        for i, visual_cue in enumerate(visual_cues, 1):
            print(
                f"\n🎯 Enhanced Visual Cue {i}/{len(visual_cues)}: "
                f"{visual_cue[:50]}..."
            )

            # Generate enhanced search variations with contextual keywords
            search_variations = generate_enhanced_visual_cue_variations(
                visual_cue, contextual_keywords
            )

            # Filter out already used search terms and get unique variations
            # PRIORITIZE: Try branded-specific terms first, then fallback to generic
            branded_variations = []
            generic_variations = []

            # Extract brand names from contextual keywords (platform names, company names)
            brand_keywords = [kw for kw in contextual_keywords if any(
                brand in kw.lower() for brand in [
                    'netflix', 'youtube', 'tiktok', 'instagram', 'spotify',
                    'twitch', 'linkedin', 'chatgpt', 'openai', 'claude',
                    'copilot', 'gemini', 'google', 'microsoft', 'apple',
                    'amazon', 'meta', 'facebook', 'github', 'docker',
                    'aws', 'azure', 'notion', 'slack', 'zoom', 'teams'
                ]
            )]

            for variation in search_variations:
                variation_key = variation.lower().strip()
                if variation_key not in used_search_terms:
                    # Check if variation contains specific brand name
                    is_branded = any(
                        brand_kw.lower() in variation_key
                        for brand_kw in brand_keywords
                    )
                    if is_branded:
                        branded_variations.append(variation)
                    else:
                        generic_variations.append(variation)
                    used_search_terms.add(variation_key)

            # Combine with branded terms first
            unique_variations = branded_variations + generic_variations

            print(f"🔍 Generated {len(unique_variations)} unique variations:")
            print(f"   📌 Branded/Specific: {len(branded_variations)}")
            print(f"   🌐 Generic fallbacks: {len(generic_variations)}")
            # Show max 6
            for j, variation in enumerate(unique_variations[:6], 1):
                marker = "📌" if j <= len(branded_variations) else "🌐"
                print(f"   {marker} {j}. {variation}")

            # Download videos using unique search terms from multiple sources
            cue_downloads = []
            max_downloads_per_cue = 3  # Limit downloads per visual cue

            # Use unique search variations to prevent duplicate searches
            for j, search_term in enumerate(
                unique_variations[:max_downloads_per_cue], 1
            ):
                # Determine if this is a branded or generic search
                is_branded = any(
                    keyword.lower() in search_term.lower()
                    for keyword in contextual_keywords
                )
                search_type = "📌 BRANDED" if is_branded else "🌐 GENERIC"

                print(
                    f"\n   🎬 {search_type} Search {j}/{min(len(unique_variations), max_downloads_per_cue)}: "
                    f"'{search_term}'..."
                )

                # Try Pexels first
                try:
                    print(f"      🔍 Searching Pexels...")
                    videos = pexels_downloader.search_videos(
                        search_term, per_page=5)

                    if videos:
                        # Find first video that hasn't been downloaded yet
                        selected_video = None
                        for video in videos:
                            video_id = str(video.get("id", ""))
                            video_url = video.get("video_files", [{}])[0].get(
                                "link", ""
                            )
                            unique_id = f"pexels_{video_id}_{video_url}"

                            if unique_id not in downloaded_video_ids:
                                selected_video = video
                                downloaded_video_ids.add(unique_id)
                                break

                        if selected_video:
                            user_name = selected_video.get("user", {}).get(
                                "name", "Unknown"
                            )
                            duration = selected_video.get("duration", 0)
                            print(
                                f"      ✅ Pexels: {user_name} - {duration}s (unique)"
                            )

                            # Create descriptive filename based on search term
                            clean_term = re.sub(r"[^\w\s-]", "", search_term)
                            clean_term = re.sub(r"\s+", "_", clean_term)[:30]
                            filename_base = f"Pexels_{clean_term}_VC{i:02d}"

                            downloaded_file = pexels_downloader.download_video(
                                selected_video, filename_base
                            )

                            if downloaded_file and Path(downloaded_file).exists():
                                cue_downloads.append(downloaded_file)
                                file_size = Path(downloaded_file).stat().st_size / (
                                    1024 * 1024
                                )
                                file_name = Path(downloaded_file).name
                                print(
                                    f"      ✅ Pexels Downloaded: {file_name} ({file_size:.1f} MB)"
                                )
                            else:
                                print(f"      ❌ Pexels download failed")
                        else:
                            print(
                                f"      ⚠️ All Pexels videos already downloaded for: {search_term}"
                            )
                    else:
                        print(
                            f"      ⚠️ No Pexels videos found for: {search_term}")

                except Exception as e:
                    print(f"      ❌ Pexels error for '{search_term}': {e}")

                # Try Pixabay if available
                if pixabay_available and pixabay_downloader:
                    try:
                        print(f"      🔍 Searching Pixabay...")
                        videos = pixabay_downloader.search_videos(
                            search_term, per_page=5
                        )

                        if videos:
                            # Find first video that hasn't been downloaded yet
                            selected_video = None
                            for video in videos:
                                video_id = str(video.get("id", ""))
                                # Pixabay uses different structure, adapt as needed
                                video_url = (
                                    video.get("videos", {})
                                    .get("large", {})
                                    .get("url", "")
                                )
                                unique_id = f"pixabay_{video_id}_{video_url}"

                                if unique_id not in downloaded_video_ids:
                                    selected_video = video
                                    downloaded_video_ids.add(unique_id)
                                    break

                            if selected_video:
                                user_name = selected_video.get(
                                    "user", "Unknown")
                                duration = selected_video.get("duration", 0)
                                print(
                                    f"      ✅ Pixabay: {user_name} - {duration}s (unique)"
                                )

                                # Create descriptive filename based on search term
                                clean_term = re.sub(
                                    r"[^\w\s-]", "", search_term)
                                clean_term = re.sub(
                                    r"\s+", "_", clean_term)[:30]
                                filename_base = f"Pixabay_{clean_term}_VC{i:02d}"

                                downloaded_file = pixabay_downloader.download_video(
                                    selected_video, filename_base
                                )

                                if downloaded_file and Path(downloaded_file).exists():
                                    cue_downloads.append(downloaded_file)
                                    file_size = Path(downloaded_file).stat().st_size / (
                                        1024 * 1024
                                    )
                                    file_name = Path(downloaded_file).name
                                    print(
                                        f"      ✅ Pixabay Downloaded: {file_name} ({file_size:.1f} MB)"
                                    )
                                else:
                                    print(f"      ❌ Pixabay download failed")
                            else:
                                print(
                                    f"      ⚠️ All Pixabay videos already downloaded for: {search_term}"
                                )
                        else:
                            print(
                                f"      ⚠️ No Pixabay videos found for: {search_term}")

                    except Exception as e:
                        print(
                            f"      ❌ Pixabay error for '{search_term}': {e}")

            downloaded_files.extend(cue_downloads)
            print(
                f"   📊 Downloaded {len(cue_downloads)} unique videos for enhanced cue from {total_sources} source{'s' if total_sources > 1 else ''}"
            )

        print(f"\n🎉 ENHANCED MULTI-SOURCE B-ROLL DOWNLOAD COMPLETE!")
        print(
            f"📊 Downloaded {len(downloaded_files)} videos with contextual keywords from {total_sources} source{'s' if total_sources > 1 else ''}"
        )
        print(f"📁 All enhanced videos saved to: {topic_broll_dir}")

        if downloaded_files:
            print(f"\n📋 Enhanced B-roll files:")
            for file_path in downloaded_files:
                file_size = Path(file_path).stat().st_size / (1024 * 1024)
                source = "Pexels" if "Pexels_" in Path(
                    file_path).name else "Pixabay"
                print(
                    f"   • [{source}] {Path(file_path).name} ({file_size:.1f} MB)")

        return str(topic_broll_dir)

    except ImportError:
        print("❌ Video downloaders not available. Install required packages.")
        return str(topic_broll_dir) if "topic_broll_dir" in locals() else ""
    except Exception as e:
        print(f"❌ Enhanced multi-source B-roll download failed: {e}")
        import traceback

        print(f"🔍 Error details: {traceback.format_exc()}")
        return str(topic_broll_dir) if "topic_broll_dir" in locals() else ""
