#!/bin/bash
#
# Stash Custom Build and Deploy Script
# =====================================
#
# This script builds a custom Docker image from source and optionally
# deploys it to Synology NAS.
#
# Usage:
#   ./build_and_deploy.sh [windows|synology|help]
#
# Modes:
#   windows   - Build on Windows, save image to tar file for transfer
#   synology  - Build directly on Synology (requires Git and Docker)
#   help      - Show this help message
#
# Prerequisites:
#   - Docker installed and running
#   - For Windows mode: Git Bash or WSL
#   - For Synology mode: SSH access and sufficient resources (4GB+ RAM)
#

set -e

# Configuration
IMAGE_NAME="stash/custom"
IMAGE_TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"
EXPORT_FILE="stash-custom.tar"
DOCKERFILE="docker/build/x86_64/Dockerfile"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}======================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}======================================================================${NC}"
    echo
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running"
        exit 1
    fi
    
    print_success "Docker is available and running"
}

check_git() {
    if ! command -v git &> /dev/null; then
        print_error "Git is not installed or not in PATH"
        exit 1
    fi
    print_success "Git is available"
}

check_source() {
    if [ ! -f "Makefile" ] || [ ! -f "tools.go" ]; then
        print_error "This script must be run from the Stash source root directory"
        print_info "Expected files: Makefile, tools.go"
        exit 1
    fi
    
    if [ ! -f "$DOCKERFILE" ]; then
        print_error "Dockerfile not found at: $DOCKERFILE"
        exit 1
    fi
    
    print_success "Source directory validated"
}

get_build_info() {
    # Get Git hash
    GITHASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    
    # Get version from git tags or use dev
    STASH_VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "dev")
    
    # Get branch name
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    
    print_info "Build Information:"
    echo "  Version: $STASH_VERSION"
    echo "  Git Hash: $GITHASH"
    echo "  Branch: $BRANCH"
    echo
}

build_image() {
    print_header "Building Docker Image"
    
    get_build_info
    
    print_info "Building image: $FULL_IMAGE_NAME"
    print_info "This may take 10-30 minutes depending on your hardware..."
    echo
    
    # Build using make command (recommended)
    if command -v make &> /dev/null; then
        print_info "Using Makefile to build Docker image..."
        
        # Export variables for make
        export GITHASH
        export STASH_VERSION
        
        if make docker-build; then
            # Tag with our custom name
            docker tag stash/build:latest "$FULL_IMAGE_NAME"
            print_success "Docker image built successfully using make!"
        else
            print_error "Build failed using make"
            exit 1
        fi
    else
        # Fallback to direct docker build
        print_warning "make not found, using direct docker build..."
        
        if docker build \
            --build-arg GITHASH="$GITHASH" \
            --build-arg STASH_VERSION="$STASH_VERSION" \
            -t "$FULL_IMAGE_NAME" \
            -f "$DOCKERFILE" \
            .; then
            print_success "Docker image built successfully!"
        else
            print_error "Docker build failed"
            exit 1
        fi
    fi
    
    echo
    print_info "Image details:"
    docker images "$IMAGE_NAME"
    echo
}

export_image() {
    print_header "Exporting Docker Image"
    
    print_info "Exporting image to: $EXPORT_FILE"
    print_info "This may take several minutes..."
    
    if docker save "$FULL_IMAGE_NAME" -o "$EXPORT_FILE"; then
        print_success "Image exported successfully!"
        
        # Show file size
        if command -v du &> /dev/null; then
            SIZE=$(du -h "$EXPORT_FILE" | cut -f1)
            print_info "Export file size: $SIZE"
        fi
        
        # Compress if gzip is available
        if command -v gzip &> /dev/null; then
            echo
            read -p "Do you want to compress the image with gzip? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                print_info "Compressing image..."
                gzip -f "$EXPORT_FILE"
                EXPORT_FILE="${EXPORT_FILE}.gz"
                print_success "Image compressed to: $EXPORT_FILE"
                
                if command -v du &> /dev/null; then
                    SIZE=$(du -h "$EXPORT_FILE" | cut -f1)
                    print_info "Compressed file size: $SIZE"
                fi
            fi
        fi
    else
        print_error "Failed to export image"
        exit 1
    fi
}

show_windows_instructions() {
    print_header "Next Steps for Windows Build"
    
    echo "The Docker image has been built and exported."
    echo
    echo "To deploy to Synology:"
    echo
    echo "1. Transfer the image file to Synology:"
    if [ -f "$EXPORT_FILE" ]; then
        echo "   scp $EXPORT_FILE admin@YOUR-SYNOLOGY-IP:/volume1/docker/stash/"
    else
        echo "   scp stash-custom.tar admin@YOUR-SYNOLOGY-IP:/volume1/docker/stash/"
    fi
    echo
    echo "2. SSH into Synology:"
    echo "   ssh admin@YOUR-SYNOLOGY-IP"
    echo
    echo "3. Load the Docker image:"
    if [[ "$EXPORT_FILE" == *.gz ]]; then
        echo "   cd /volume1/docker/stash"
        echo "   gunzip stash-custom.tar.gz"
        echo "   docker load -i stash-custom.tar"
    else
        echo "   docker load -i /volume1/docker/stash/$EXPORT_FILE"
    fi
    echo
    echo "4. Verify the image was loaded:"
    echo "   docker images | grep stash/custom"
    echo
    echo "5. Start the container:"
    echo "   cd /volume1/docker/stash"
    echo "   docker compose -f docker-compose-custom-build.yml up -d"
    echo
    echo "6. Check logs:"
    echo "   docker compose -f docker-compose-custom-build.yml logs -f"
    echo
}

show_synology_instructions() {
    print_header "Next Steps for Synology Build"
    
    echo "The Docker image has been built on Synology."
    echo
    echo "To start Stash:"
    echo
    echo "1. Verify the image:"
    echo "   docker images | grep stash/custom"
    echo
    echo "2. Start the container:"
    echo "   cd /volume1/docker/stash"
    echo "   docker compose -f docker-compose-custom-build.yml up -d"
    echo
    echo "3. Check logs:"
    echo "   docker compose -f docker-compose-custom-build.yml logs -f"
    echo
    echo "4. Access Stash:"
    echo "   http://YOUR-SYNOLOGY-IP:9999"
    echo
}

mode_windows() {
    print_header "Building Stash - Windows Mode"
    print_info "Build on Windows, export for transfer to Synology"
    echo
    
    check_docker
    check_git
    check_source
    
    build_image
    export_image
    
    show_windows_instructions
    
    print_success "Build complete!"
}

mode_synology() {
    print_header "Building Stash - Synology Mode"
    print_info "Build directly on Synology NAS"
    echo
    
    print_warning "Building on Synology requires:"
    print_warning "- At least 4GB RAM"
    print_warning "- Git installed"
    print_warning "- Docker package installed"
    print_warning "- Build may take 30-60 minutes"
    echo
    
    read -p "Continue with Synology build? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Build cancelled"
        exit 0
    fi
    
    check_docker
    check_git
    check_source
    
    build_image
    
    show_synology_instructions
    
    print_success "Build complete!"
}

show_help() {
    cat << EOF
Stash Custom Build and Deploy Script
=====================================

Usage: $0 [MODE]

Modes:
  windows   Build on Windows, save image to tar file for transfer to Synology
  synology  Build directly on Synology NAS (requires more resources)
  help      Show this help message

Examples:
  $0 windows          # Build on Windows and export
  $0 synology         # Build on Synology
  $0 help             # Show this help

Prerequisites:
  - Docker installed and running
  - Git installed
  - For Windows: Git Bash or WSL recommended
  - For Synology: SSH access, 4GB+ RAM, Git package installed

Build Process:
  1. Validates environment (Docker, Git, source files)
  2. Determines version and git information
  3. Builds frontend (Node.js)
  4. Builds backend (Go)
  5. Creates final Docker image
  6. (Windows mode) Exports image to tar file
  7. Shows deployment instructions

Custom Image Name: $FULL_IMAGE_NAME

For more information, see README_MIGRATION_CUSTOM_BUILD.md

EOF
}

# Main script
main() {
    if [ $# -eq 0 ]; then
        print_error "No mode specified"
        echo
        show_help
        exit 1
    fi
    
    case "$1" in
        windows)
            mode_windows
            ;;
        synology)
            mode_synology
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown mode: $1"
            echo
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
















