#!/bin/bash
# ==============================================================================
# HeyGen Video Downloader
# ==============================================================================
# Downloads completed videos from HeyGen API
# 
# Usage: 
#   ./download_heygen_videos.sh                    # Download all recent videos
#   ./download_heygen_videos.sh <video_id>         # Download specific video
#   ./download_heygen_videos.sh --list             # List recent videos only
#
# Requirements:
#   - curl
#   - jq (for JSON parsing)
#
# ==============================================================================

# Configuration
API_KEY="${HEYGEN_API_KEY:?HEYGEN_API_KEY is required}"
OUTPUT_DIR="${HEYGEN_OUTPUT_DIR:-$HOME/Dev/Videos/Edited/Final}"
DEFAULT_PROJECT="HeyGen_Downloads"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==============================================================================
# Helper Functions
# ==============================================================================

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

check_dependencies() {
    if ! command -v curl &> /dev/null; then
        log_error "curl is required but not installed."
        exit 1
    fi
    
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not installed."
        log_info "Install with: brew install jq"
        exit 1
    fi
}

# ==============================================================================
# API Functions
# ==============================================================================

# Get video status and URL
get_video_status() {
    local video_id="$1"
    
    curl -s --location "https://api.heygen.com/v1/video_status.get?video_id=${video_id}" \
        --header "X-Api-Key: ${API_KEY}"
}

# List recent videos
list_videos() {
    log_info "Fetching recent videos from HeyGen..."
    
    response=$(curl -s --location "https://api.heygen.com/v1/video.list" \
        --header "X-Api-Key: ${API_KEY}")
    
    if [ $? -ne 0 ]; then
        log_error "Failed to fetch video list"
        return 1
    fi
    
    # Check for errors
    error=$(echo "$response" | jq -r '.error // empty')
    if [ -n "$error" ]; then
        log_error "API Error: $error"
        return 1
    fi
    
    echo "$response"
}

# Download a single video
download_video() {
    local video_id="$1"
    local project_name="${2:-$DEFAULT_PROJECT}"
    
    log_info "Checking status for video: $video_id"
    
    # Get video status
    status_response=$(get_video_status "$video_id")
    
    if [ $? -ne 0 ]; then
        log_error "Failed to get status for video: $video_id"
        return 1
    fi
    
    # Parse status
    status=$(echo "$status_response" | jq -r '.data.status // "unknown"')
    video_url=$(echo "$status_response" | jq -r '.data.video_url // empty')
    video_title=$(echo "$status_response" | jq -r '.data.video_title // empty')
    
    echo "   Status: $status"
    
    if [ "$status" != "completed" ]; then
        log_warning "Video not ready (status: $status)"
        return 1
    fi
    
    if [ -z "$video_url" ]; then
        log_error "No video URL found"
        return 1
    fi
    
    # Create output directory
    local output_path="$OUTPUT_DIR/$project_name/aroll"
    mkdir -p "$output_path"
    
    # Generate filename
    local safe_title=$(echo "$video_title" | tr -cd '[:alnum:] _-' | tr ' ' '_')
    if [ -z "$safe_title" ]; then
        safe_title="video"
    fi
    local filename="heygen_${safe_title}_${video_id:0:8}.mp4"
    local full_path="$output_path/$filename"
    
    # Check if already downloaded
    if [ -f "$full_path" ]; then
        log_warning "Video already exists: $filename"
        return 0
    fi
    
    log_info "Downloading: $filename"
    
    # Download video
    curl -s --location "$video_url" --output "$full_path"
    
    if [ $? -eq 0 ] && [ -f "$full_path" ]; then
        local size=$(du -h "$full_path" | cut -f1)
        log_success "Downloaded: $filename ($size)"
        echo "   Path: $full_path"
    else
        log_error "Failed to download video"
        return 1
    fi
}

# Download all completed videos from recent list
download_all_recent() {
    local project_name="${1:-$DEFAULT_PROJECT}"
    
    log_info "Fetching recent videos..."
    
    videos_response=$(list_videos)
    
    if [ $? -ne 0 ]; then
        return 1
    fi
    
    # Extract video IDs
    video_ids=$(echo "$videos_response" | jq -r '.data.videos[]?.video_id // empty')
    
    if [ -z "$video_ids" ]; then
        log_warning "No videos found"
        return 0
    fi
    
    # Count videos
    count=$(echo "$video_ids" | wc -l | tr -d ' ')
    log_info "Found $count videos"
    echo ""
    
    # Download each video
    downloaded=0
    failed=0
    skipped=0
    
    while IFS= read -r video_id; do
        if [ -n "$video_id" ]; then
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            result=$(download_video "$video_id" "$project_name")
            echo "$result"
            
            if echo "$result" | grep -q "Downloaded:"; then
                ((downloaded++))
            elif echo "$result" | grep -q "already exists"; then
                ((skipped++))
            else
                ((failed++))
            fi
            echo ""
        fi
    done <<< "$video_ids"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    log_info "Summary:"
    echo "   Downloaded: $downloaded"
    echo "   Skipped (already exist): $skipped"
    echo "   Failed/Not Ready: $failed"
    echo ""
    log_success "Videos saved to: $OUTPUT_DIR/$project_name/aroll/"
}

# Show list of recent videos
show_list() {
    log_info "Fetching recent videos..."
    
    videos_response=$(list_videos)
    
    if [ $? -ne 0 ]; then
        return 1
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf "%-40s %-12s %-20s\n" "VIDEO ID" "STATUS" "TITLE"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    echo "$videos_response" | jq -r '.data.videos[] | "\(.video_id)\t\(.status)\t\(.video_title // "Untitled")"' | \
    while IFS=$'\t' read -r id status title; do
        # Truncate title if too long
        title="${title:0:20}"
        printf "%-40s %-12s %-20s\n" "$id" "$status" "$title"
    done
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # Count by status
    completed=$(echo "$videos_response" | jq '[.data.videos[] | select(.status == "completed")] | length')
    processing=$(echo "$videos_response" | jq '[.data.videos[] | select(.status == "processing")] | length')
    pending=$(echo "$videos_response" | jq '[.data.videos[] | select(.status == "pending" or .status == "waiting")] | length')
    
    echo "Summary: $completed completed, $processing processing, $pending pending"
}

# ==============================================================================
# Main Script
# ==============================================================================

main() {
    echo ""
    echo "🎬 HeyGen Video Downloader"
    echo "=========================="
    echo ""
    
    check_dependencies
    
    case "$1" in
        --list|-l)
            show_list
            ;;
        --help|-h)
            echo "Usage:"
            echo "  $0                     Download all recent completed videos"
            echo "  $0 <video_id>          Download a specific video"
            echo "  $0 --list              List recent videos without downloading"
            echo "  $0 --project <name>    Download to specific project folder"
            echo ""
            echo "Environment variables:"
            echo "  HEYGEN_API_KEY         API key (default: uses stored key)"
            echo "  HEYGEN_OUTPUT_DIR      Base output directory"
            echo ""
            ;;
        --project|-p)
            if [ -z "$2" ]; then
                log_error "Please specify a project name"
                exit 1
            fi
            download_all_recent "$2"
            ;;
        "")
            download_all_recent
            ;;
        *)
            # Assume it's a video ID
            download_video "$1"
            ;;
    esac
}

main "$@"
