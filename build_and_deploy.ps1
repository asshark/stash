# Stash Custom Build and Deploy Script (PowerShell)
# ====================================================
#
# PowerShell version of build_and_deploy.sh for Windows users
#
# Usage:
#   .\build_and_deploy.ps1 -Mode windows
#   .\build_and_deploy.ps1 -Mode help
#
# Prerequisites:
#   - Docker Desktop installed and running
#   - Git installed
#   - Source code in current directory

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("windows", "help")]
    [string]$Mode = "help"
)

# Configuration
$ImageName = "stash/custom"
$ImageTag = "latest"
$FullImageName = "${ImageName}:${ImageTag}"
$ExportFile = "stash-custom.tar"
$Dockerfile = "docker\build\x86_64\Dockerfile"

# ============================================================
# FUNCTION DEFINITIONS (must be before use)
# ============================================================

# Colors for output
function Write-Header {
    param([string]$Message)
    Write-Host "======================================================================" -ForegroundColor Blue
    Write-Host $Message -ForegroundColor Blue
    Write-Host "======================================================================" -ForegroundColor Blue
    Write-Host ""
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Write-Warning {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

function Write-Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Cyan
}

function Test-Docker {
    Write-Info "Checking Docker..."
    
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-ErrorMsg "Docker is not installed or not in PATH"
        Write-Info "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
        exit 1
    }
    
    try {
        $null = docker info 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorMsg "Docker daemon is not running"
            Write-Info "Please start Docker Desktop and wait for it to fully start"
            exit 1
        }
    }
    catch {
        Write-ErrorMsg "Docker daemon is not running"
        exit 1
    }
    
    Write-Success "Docker is available and running"
}

function Test-Git {
    Write-Info "Checking Git..."
    
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-ErrorMsg "Git is not installed or not in PATH"
        Write-Info "Please install Git from: https://git-scm.com/download/win"
        exit 1
    }
    
    Write-Success "Git is available"
}

function Test-Source {
    Write-Info "Validating source directory..."
    
    if (-not (Test-Path "Makefile") -or -not (Test-Path "tools.go")) {
        Write-ErrorMsg "This script must be run from the Stash source root directory"
        Write-Info "Expected files: Makefile, tools.go"
        exit 1
    }
    
    if (-not (Test-Path $Dockerfile)) {
        Write-ErrorMsg "Dockerfile not found at: $Dockerfile"
        exit 1
    }
    
    Write-Success "Source directory validated"
}

function Get-BuildInfo {
    Write-Info "Build Information:"
    
    # Get Git hash
    try {
        $script:GitHash = git rev-parse --short HEAD 2>$null
        if (-not $script:GitHash) { $script:GitHash = "unknown" }
    }
    catch {
        $script:GitHash = "unknown"
    }
    
    # Get version from git tags
    try {
        $script:StashVersion = git describe --tags --abbrev=0 2>$null
        if (-not $script:StashVersion) { $script:StashVersion = "dev" }
    }
    catch {
        $script:StashVersion = "dev"
    }
    
    # Get branch name
    try {
        $Branch = git rev-parse --abbrev-ref HEAD 2>$null
        if (-not $Branch) { $Branch = "unknown" }
    }
    catch {
        $Branch = "unknown"
    }
    
    Write-Host "  Version: $script:StashVersion"
    Write-Host "  Git Hash: $script:GitHash"
    Write-Host "  Branch: $Branch"
    Write-Host ""
}

function Build-Image {
    Write-Header "Building Docker Image"
    
    Get-BuildInfo
    
    Write-Info "Building image: $FullImageName"
    Write-Info "This may take 10-30 minutes depending on your hardware..."
    Write-Host ""
    
    # Check if make is available
    if (Get-Command make -ErrorAction SilentlyContinue) {
        Write-Info "Using Makefile to build Docker image..."
        
        $env:GITHASH = $script:GitHash
        $env:STASH_VERSION = $script:StashVersion
        
        make docker-build
        
        if ($LASTEXITCODE -eq 0) {
            # Tag with our custom name
            docker tag stash/build:latest $FullImageName
            Write-Success "Docker image built successfully using make!"
        }
        else {
            Write-ErrorMsg "Build failed using make"
            exit 1
        }
    }
    else {
        Write-Warning "make not found, using direct docker build..."
        
        docker build `
            --build-arg GITHASH="$script:GitHash" `
            --build-arg STASH_VERSION="$script:StashVersion" `
            -t $FullImageName `
            -f $Dockerfile `
            .
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Docker image built successfully!"
        }
        else {
            Write-ErrorMsg "Docker build failed"
            exit 1
        }
    }
    
    Write-Host ""
    Write-Info "Image details:"
    docker images $ImageName
    Write-Host ""
}

function Export-Image {
    Write-Header "Exporting Docker Image"
    
    Write-Info "Exporting image to: $ExportFile"
    Write-Info "This may take several minutes..."
    
    docker save $FullImageName -o $ExportFile
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Image exported successfully!"
        
        $FileSize = (Get-Item $ExportFile).Length
        $FileSizeMB = [math]::Round($FileSize / 1MB, 2)
        Write-Info "Export file size: $FileSizeMB MB"
        
        # Ask about compression
        Write-Host ""
        $Compress = Read-Host "Do you want to compress the image with 7-Zip/gzip? (y/N)"
        
        if ($Compress -eq 'y' -or $Compress -eq 'Y') {
            # Try 7-Zip first
            if (Get-Command 7z -ErrorAction SilentlyContinue) {
                Write-Info "Compressing with 7-Zip..."
                7z a -tgzip "$ExportFile.gz" $ExportFile
                Remove-Item $ExportFile
                $script:ExportFile = "$ExportFile.gz"
                
                $CompressedSize = (Get-Item $script:ExportFile).Length
                $CompressedSizeMB = [math]::Round($CompressedSize / 1MB, 2)
                Write-Success "Image compressed to: $script:ExportFile"
                Write-Info "Compressed file size: $CompressedSizeMB MB"
            }
            # Try gzip (if available through Git Bash or WSL)
            elseif (Get-Command gzip -ErrorAction SilentlyContinue) {
                Write-Info "Compressing with gzip..."
                gzip -f $ExportFile
                $script:ExportFile = "$ExportFile.gz"
                
                $CompressedSize = (Get-Item $script:ExportFile).Length
                $CompressedSizeMB = [math]::Round($CompressedSize / 1MB, 2)
                Write-Success "Image compressed to: $script:ExportFile"
                Write-Info "Compressed file size: $CompressedSizeMB MB"
            }
            else {
                Write-Warning "No compression tool found (7-Zip or gzip)"
                Write-Info "You can manually compress the file later"
            }
        }
    }
    else {
        Write-ErrorMsg "Failed to export image"
        exit 1
    }
}

function Show-WindowsInstructions {
    Write-Header "Next Steps for Windows Build"
    
    Write-Host "The Docker image has been built and exported." -ForegroundColor Green
    Write-Host ""
    Write-Host "To deploy to Synology:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Transfer the image file to Synology:"
    Write-Host "   scp $script:ExportFile admin@YOUR-SYNOLOGY-IP:/volume1/docker/stash/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "   Or copy via network share/File Station"
    Write-Host ""
    Write-Host "2. SSH into Synology:"
    Write-Host "   ssh admin@YOUR-SYNOLOGY-IP" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "3. Load the Docker image:"
    if ($script:ExportFile -match "\.gz$") {
        Write-Host "   cd /volume1/docker/stash" -ForegroundColor Cyan
        Write-Host "   gunzip stash-custom.tar.gz" -ForegroundColor Cyan
        Write-Host "   docker load -i stash-custom.tar" -ForegroundColor Cyan
    }
    else {
        Write-Host "   docker load -i /volume1/docker/stash/$script:ExportFile" -ForegroundColor Cyan
    }
    Write-Host ""
    Write-Host "4. Verify the image was loaded:"
    Write-Host "   docker images | grep stash/custom" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "5. Start the container:"
    Write-Host "   cd /volume1/docker/stash" -ForegroundColor Cyan
    Write-Host "   docker compose -f docker-compose-custom-build.yml up -d" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "6. Check logs:"
    Write-Host "   docker compose -f docker-compose-custom-build.yml logs -f" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Help {
    @"
Stash Custom Build and Deploy Script (PowerShell)
==================================================

Usage: .\build_and_deploy.ps1 -Mode <MODE>

Modes:
  windows   Build on Windows, save image to tar file for transfer to Synology
  help      Show this help message

Examples:
  .\build_and_deploy.ps1 -Mode windows
  .\build_and_deploy.ps1 -Mode help

Prerequisites:
  - Docker Desktop installed and running
  - Git installed
  - Run from Stash source root directory

Build Process:
  1. Validates environment (Docker, Git, source files)
  2. Determines version and git information
  3. Builds frontend (Node.js)
  4. Builds backend (Go)
  5. Creates final Docker image
  6. Exports image to tar file
  7. Shows deployment instructions

Custom Image Name: $FullImageName

For more information, see README_MIGRATION_CUSTOM_BUILD.md

"@
}

# Main script
function Main {
    switch ($Mode) {
        "windows" {
            Write-Header "Building Stash - Windows Mode"
            Write-Info "Build on Windows, export for transfer to Synology"
            Write-Host ""
            
            Test-Docker
            Test-Git
            Test-Source
            
            Build-Image
            Export-Image
            
            Show-WindowsInstructions
            
            Write-Success "Build complete!"
        }
        "help" {
            Show-Help
        }
        default {
            Write-ErrorMsg "Unknown mode: $Mode"
            Write-Host ""
            Show-Help
            exit 1
        }
    }
}

# Run main function
Main

