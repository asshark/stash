# Stash Migration Guide: Windows to Synology Docker (Custom Build)

This guide describes how to migrate Stash from Windows to Synology Docker using a **custom-built Docker image** from your modified source code.

**Use this guide if:**
- You have modified the Stash source code
- You want to test development branches
- You need features not yet in official releases
- You want full control over the build process

**If you just want to use the official Stash image, use `README_MIGRATION.md` instead.**

---

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Build Options](#build-options)
4. [Migration Process](#migration-process)
5. [Building on Windows](#building-on-windows)
6. [Building on Synology](#building-on-synology)
7. [Deployment](#deployment)
8. [Updating Your Custom Build](#updating-your-custom-build)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This migration involves:
- Building a custom Docker image from your source code
- Migrating database and configuration from Windows
- Deploying the custom image on Synology
- Maintaining the ability to edit plugins externally

**Key Differences from Standard Migration:**
- You build your own Docker image from source
- Image is named `stash/custom:latest` instead of `stashapp/stash:latest`
- You can include your own modifications and features
- Updates require rebuilding the image

**Estimated Time:**
- Build on Windows: 15-30 minutes + transfer time
- Build on Synology: 30-60 minutes
- Migration: 1-2 hours (same as standard)

---

## Prerequisites

### On Windows (Build Machine):

**Required:**
- Docker Desktop installed and running
- Git installed
- Source code of Stash (your modified version)
- At least 4GB free RAM for building
- 10GB free disk space for build artifacts

**Recommended:**
- Git Bash or WSL (Windows Subsystem for Linux)
- Fast internet connection (for downloading dependencies)
- SSD for faster builds

### On Synology (Target):

**Required:**
- Docker package installed (via Package Center)
- SSH access enabled
- Sufficient storage in `/volume2/video.xxx.clips/`
- At least 2GB free RAM for running

**For building on Synology (optional):**
- At least 4GB RAM (preferably 8GB)
- Git Server package installed
- Patience (builds take longer on NAS)

### Source Code:

Your Stash source code should be in a working directory with:
- `Makefile`
- `tools.go`
- `docker/build/x86_64/Dockerfile`
- All source files (pkg/, internal/, ui/, etc.)

---

## Build Options

You have two options for building the Docker image:

### Option 1: Build on Windows (Recommended)

**Advantages:**
- Faster build times (more powerful hardware)
- Doesn't consume Synology resources during build
- Can build while Synology is in use
- Easier to debug build issues

**Disadvantages:**
- Need to transfer image file (~1-2GB) to Synology
- Requires Docker Desktop on Windows

**Best for:** Most users, especially if Windows is your main development machine

### Option 2: Build on Synology

**Advantages:**
- No need to transfer large image files
- One-step process (build and deploy in place)
- Always builds for correct architecture

**Disadvantages:**
- Slower build times (NAS hardware is less powerful)
- Consumes Synology resources during build
- May impact other services during build
- Requires Git installation on Synology

**Best for:** Users with powerful NAS (8GB+ RAM) or limited bandwidth for transfers

---

## Migration Process

The overall process is similar to standard migration, with additional build steps:

```
1. Prepare Windows Environment
   └─→ Stop Stash on Windows
   └─→ Backup database and config
   └─→ Document library paths

2. Build Custom Docker Image
   └─→ [Option A] Build on Windows
   │    └─→ Export image to tar file
   │    └─→ Transfer to Synology
   │    └─→ Load image on Synology
   └─→ [Option B] Build on Synology
        └─→ Transfer source code
        └─→ Build directly on NAS

3. Prepare Synology
   └─→ Create directory structure
   └─→ Transfer config and database
   └─→ Run database migration

4. Deploy Container
   └─→ Configure docker-compose-custom-build.yml
   └─→ Start container
   └─→ Verify functionality

5. Post-Migration
   └─→ Test all features
   └─→ Setup backups
   └─→ Document update process
```

---

## Building on Windows

### Step 1: Prepare Build Environment

1. **Ensure Docker is running:**
   ```powershell
   # In PowerShell
   docker info
   ```
   
   If this fails, start Docker Desktop.

2. **Navigate to source directory:**
   ```bash
   # In Git Bash or WSL
   cd /s/MyProjects/stash/stash
   ```

3. **Verify source files:**
   ```bash
   ls -la Makefile tools.go docker/build/x86_64/Dockerfile
   ```

4. **Check Git status:**
   ```bash
   git status
   git log --oneline -5
   ```
   
   Make note of your current commit and branch.

### Step 2: Run Build Script

We'll use the provided `build_and_deploy.sh` script:

```bash
# Make script executable (if needed)
chmod +x build_and_deploy.sh

# Run in Windows mode
./build_and_deploy.sh windows
```

The script will:
1. Validate Docker and Git are available
2. Check source directory structure
3. Determine version and Git hash
4. Build frontend (Node.js) - ~5-10 minutes
5. Build backend (Go) - ~5-10 minutes
6. Create Docker image - ~2-5 minutes
7. Export image to `stash-custom.tar` - ~2-5 minutes

**Total time:** 15-30 minutes depending on hardware.

**Sample Output:**
```
======================================================================
Building Stash - Windows Mode
======================================================================
ℹ Build on Windows, export for transfer to Synology

✓ Docker is available and running
✓ Git is available
✓ Source directory validated

======================================================================
Building Docker Image
======================================================================

ℹ Build Information:
  Version: v0.27.0
  Git Hash: abc1234
  Branch: develop

ℹ Building image: stash/custom:latest
ℹ This may take 10-30 minutes depending on your hardware...

[... build output ...]

✓ Docker image built successfully using make!

======================================================================
Exporting Docker Image
======================================================================

ℹ Exporting image to: stash-custom.tar
✓ Image exported successfully!
ℹ Export file size: 1.2G

Do you want to compress the image with gzip? (y/N):
```

### Step 3: Compress Image (Optional)

If prompted, compress the image to reduce transfer time:

```bash
# If not compressed by script, do it manually:
gzip stash-custom.tar
```

This reduces size by ~60-70% but adds compression/decompression time.

### Step 4: Transfer to Synology

**Option A: Via SCP (Recommended)**
```bash
# From Git Bash or WSL
scp stash-custom.tar.gz admin@YOUR-SYNOLOGY-IP:/volume1/docker/stash/
```

**Option B: Via SMB/Network Share**
1. Map Synology network share on Windows
2. Copy `stash-custom.tar.gz` to `/volume1/docker/stash/`

**Option C: Via Synology File Station**
1. Open Synology web interface
2. Go to File Station
3. Navigate to `/volume1/docker/stash/`
4. Upload `stash-custom.tar.gz`

### Step 5: Load Image on Synology

```bash
# SSH into Synology
ssh admin@YOUR-SYNOLOGY-IP

# Navigate to directory
cd /volume1/docker/stash

# Decompress if needed
gunzip stash-custom.tar.gz

# Load Docker image
docker load -i stash-custom.tar

# Verify image is loaded
docker images | grep stash/custom
```

**Expected Output:**
```
REPOSITORY      TAG       IMAGE ID       CREATED          SIZE
stash/custom    latest    abc123def456   10 minutes ago   450MB
```

**Success!** Your custom image is now available on Synology.

---

## Building on Synology

### Step 1: Prepare Synology

1. **Install Git Server package:**
   - Open Package Center
   - Search for "Git Server"
   - Install

2. **Enable SSH:**
   - Control Panel → Terminal & SNMP
   - Enable SSH service

3. **Check resources:**
   ```bash
   ssh admin@YOUR-SYNOLOGY-IP
   free -h
   df -h
   ```
   
   Ensure you have:
   - At least 4GB RAM (8GB recommended)
   - At least 10GB free disk space

### Step 2: Transfer Source Code

**Option A: Git Clone (if source is in a repo)**
```bash
# SSH into Synology
ssh admin@YOUR-SYNOLOGY-IP

# Create working directory
mkdir -p /volume1/docker/stash-build
cd /volume1/docker/stash-build

# Clone your repository
git clone YOUR-REPO-URL stash-source
cd stash-source

# Checkout your branch
git checkout YOUR-BRANCH
```

**Option B: Transfer via SCP**
```bash
# From Windows (Git Bash)
cd /s/MyProjects/stash
tar -czf stash-source.tar.gz stash/
scp stash-source.tar.gz admin@YOUR-SYNOLOGY-IP:/volume1/docker/stash-build/

# On Synology
ssh admin@YOUR-SYNOLOGY-IP
cd /volume1/docker/stash-build
tar -xzf stash-source.tar.gz
cd stash
```

### Step 3: Run Build Script

```bash
# On Synology, in source directory
cd /volume1/docker/stash-build/stash

# Make script executable
chmod +x build_and_deploy.sh

# Run in Synology mode
./build_and_deploy.sh synology
```

The script will:
1. Validate environment
2. Warn about resource requirements
3. Build the Docker image
4. Show deployment instructions

**Total time:** 30-60 minutes (varies by NAS model)

**Note:** Build progress can be monitored, but it's CPU-intensive. Other services may slow down during build.

### Step 4: Monitor Build

During the build, you can monitor resources:

```bash
# In another SSH session
# Watch CPU and memory
watch -n 2 'ps aux | head -20'

# Check Docker build progress
docker ps -a
```

**Tip:** Schedule builds during low-usage hours.

---

## Deployment

Once you have the custom image (either from Windows or built on Synology), follow these steps:

### Step 1: Database Migration

**Follow the same database migration steps as in `README_MIGRATION.md`:**

1. Transfer database from Windows to Synology
2. Edit `path_mapping.txt` with your paths
3. Run `migrate_database.py`
4. Verify with `verify_migration.py`

These steps are **identical** regardless of which Docker image you use.

Refer to sections in `README_MIGRATION.md`:
- Phase 1: Backup Windows Installation
- Phase 2: Prepare Synology
- Phase 3: Database Migration

### Step 2: Transfer Docker Compose File

Copy the custom build Docker Compose file:

```bash
# On Synology
mkdir -p /volume1/docker/stash
cd /volume1/docker/stash

# Transfer docker-compose-custom-build.yml from Windows
# Via SCP from Windows:
# scp docker-compose-custom-build.yml admin@SYNOLOGY-IP:/volume1/docker/stash/

# Or create it directly on Synology with nano/vi
```

### Step 3: Configure Docker Compose

Edit `docker-compose-custom-build.yml`:

```bash
cd /volume1/docker/stash
nano docker-compose-custom-build.yml
```

**Update these sections:**

1. **Verify image name:**
   ```yaml
   services:
     stash:
       image: stash/custom:latest  # Ensure this matches your built image
   ```

2. **Update media library mappings:**
   ```yaml
   volumes:
     # ... existing volumes ...
     
     # Update these to match YOUR setup:
     - /volume2/video.xxx.clips/Clips:/data/Clips
     - /volume2/video.xxx.clips/Videos:/data/Videos
     # Add more as needed
   ```

3. **Verify config paths:**
   ```yaml
   volumes:
     - /volume2/video.xxx.clips/stash/config:/root/.stash
     - /volume2/video.xxx.clips/stash/database:/root/.stash/database
     - /volume2/video.xxx.clips/stash/blobs:/blobs
     # etc.
   ```

### Step 4: Verify Directory Structure

```bash
# Check that all directories exist
ls -la /volume2/video.xxx.clips/stash/

# Should show:
# config/
# database/
# blobs/
# generated/
# cache/
# metadata/
```

### Step 5: Start Container

```bash
cd /volume1/docker/stash

# Start in foreground to watch logs
docker compose -f docker-compose-custom-build.yml up

# Watch for any errors
# Once satisfied, Ctrl+C and start in background:
docker compose -f docker-compose-custom-build.yml up -d
```

### Step 6: Verify Deployment

```bash
# Check container status
docker compose -f docker-compose-custom-build.yml ps

# Should show:
# NAME            IMAGE                 STATUS
# stash-custom    stash/custom:latest   Up X minutes

# Check logs
docker compose -f docker-compose-custom-build.yml logs -f
```

### Step 7: Access and Test

1. **Open browser:**
   ```
   http://YOUR-SYNOLOGY-IP:9999
   ```

2. **Test functionality:**
   - Login with your credentials
   - Check library access
   - Verify scenes load
   - Test video playback
   - Check plugins work
   - Verify thumbnails/covers display

3. **Run a test scan:**
   - Settings → Tasks
   - Click "Scan"
   - Monitor progress

**If everything works, congratulations! Your custom build is deployed.**

---

## Updating Your Custom Build

When you make changes to the source code, you need to rebuild and redeploy:

### Method 1: Update from Windows

```bash
# 1. Make your code changes on Windows
cd /s/MyProjects/stash/stash

# 2. Rebuild image
./build_and_deploy.sh windows

# 3. Transfer new image to Synology
scp stash-custom.tar.gz admin@SYNOLOGY-IP:/volume1/docker/stash/

# 4. On Synology, load new image
ssh admin@SYNOLOGY-IP
cd /volume1/docker/stash
gunzip -f stash-custom.tar.gz
docker load -i stash-custom.tar

# 5. Restart container with new image
cd /volume1/docker/stash
docker compose -f docker-compose-custom-build.yml down
docker compose -f docker-compose-custom-build.yml up -d

# 6. Verify
docker compose -f docker-compose-custom-build.yml logs -f
```

### Method 2: Update on Synology (if building there)

```bash
# 1. SSH into Synology
ssh admin@SYNOLOGY-IP

# 2. Update source code
cd /volume1/docker/stash-build/stash
git pull  # or transfer new files

# 3. Rebuild image
./build_and_deploy.sh synology

# 4. Restart container
cd /volume1/docker/stash
docker compose -f docker-compose-custom-build.yml down
docker compose -f docker-compose-custom-build.yml up -d

# 5. Verify
docker compose -f docker-compose-custom-build.yml logs -f
```

### Quick Update Script

Create a helper script for easy updates:

```bash
# On Synology: /volume1/docker/stash/update-stash.sh
#!/bin/bash
cd /volume1/docker/stash

echo "Stopping container..."
docker compose -f docker-compose-custom-build.yml down

echo "Loading new image..."
if [ -f stash-custom.tar ]; then
    docker load -i stash-custom.tar
    echo "Starting container..."
    docker compose -f docker-compose-custom-build.yml up -d
    echo "Done! Checking logs..."
    docker compose -f docker-compose-custom-build.yml logs --tail=50
else
    echo "Error: stash-custom.tar not found"
    exit 1
fi
```

```bash
# Make executable
chmod +x /volume1/docker/stash/update-stash.sh

# Use it after transferring new image:
./update-stash.sh
```

### Cleanup Old Images

Over time, old images accumulate:

```bash
# View all Stash images
docker images | grep stash

# Remove old/dangling images
docker image prune -a

# Or remove specific old image
docker rmi IMAGE_ID
```

---

## Troubleshooting

### Build Issues

#### Issue: Build Fails on Windows

**Error: "Cannot connect to Docker daemon"**
```
Solution:
- Start Docker Desktop
- Wait for it to fully start (icon in system tray)
- Try build again
```

**Error: "No space left on device"**
```
Solution:
- Clean Docker: docker system prune -a
- Free up disk space
- Increase Docker Desktop's disk allocation
```

**Error: "make: command not found"**
```
Solution:
- Install make via Chocolatey: choco install make
- Or install Git for Windows (includes make)
- Or use WSL (has make built-in)
```

#### Issue: Build Fails on Synology

**Error: "Out of memory"**
```
Solution:
- Close other applications
- Increase swap size if possible
- Build on Windows instead
- Upgrade Synology RAM
```

**Error: "git: command not found"**
```
Solution:
- Install Git Server package from Package Center
- Or transfer pre-built image from Windows
```

### Deployment Issues

#### Issue: Container Won't Start with Custom Image

**Check image is loaded:**
```bash
docker images | grep stash/custom
```

**Check docker-compose.yml references correct image:**
```yaml
image: stash/custom:latest
```

**Check container logs:**
```bash
docker compose -f docker-compose-custom-build.yml logs
```

#### Issue: "exec format error"

**Cause:** Image was built for wrong architecture

**Solution:**
- Rebuild for correct architecture (amd64 for most Synology models)
- Check Synology CPU architecture: `uname -m`
- Ensure Dockerfile uses correct base images

#### Issue: Custom Features Don't Work

**Verify you're using the custom image:**
```bash
docker inspect stash-custom | grep Image
```

**Check build included your changes:**
```bash
# View image build date
docker images stash/custom

# Check running container
docker exec stash-custom stash --version
```

### Performance Issues

#### Custom Build is Slower

**Possible causes:**
- Debug symbols included
- Non-optimized build
- Missing release flags

**Solution:** Ensure build uses release flags (already in Dockerfile):
```dockerfile
ARG GITHASH
ARG STASH_VERSION
RUN make flags-release flags-pie stash
```

#### Large Image Size

**Check image size:**
```bash
docker images stash/custom
```

**Reduce size:**
- Clean build cache: `docker builder prune`
- Optimize Dockerfile (multi-stage builds already used)
- Remove unnecessary dependencies

---

## Advanced Topics

### Building with Custom Dockerfile

If you've modified the Dockerfile:

```bash
# Build with custom Dockerfile
docker build \
  --build-arg GITHASH=$(git rev-parse --short HEAD) \
  --build-arg STASH_VERSION=$(git describe --tags) \
  -t stash/custom:latest \
  -f docker/build/x86_64/Dockerfile \
  .
```

### Building with CUDA Support

For NVIDIA GPU support:

```bash
# Use CUDA Dockerfile
./build_and_deploy.sh windows
# But modify script to use Dockerfile-CUDA instead of Dockerfile

# Or manually:
docker build \
  --build-arg GITHASH=$(git rev-parse --short HEAD) \
  --build-arg STASH_VERSION=$(git describe --tags) \
  -t stash/cuda-custom:latest \
  -f docker/build/x86_64/Dockerfile-CUDA \
  .
```

Update docker-compose-custom-build.yml:
```yaml
image: stash/cuda-custom:latest
runtime: nvidia
```

### Automated Builds

Create a CI/CD pipeline to automatically build on code changes:

**Example GitHub Actions workflow:**
```yaml
name: Build Custom Stash

on:
  push:
    branches: [ develop ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Build Docker image
        run: |
          make docker-build
          docker tag stash/build:latest stash/custom:latest
          docker save stash/custom:latest | gzip > stash-custom.tar.gz
      - name: Upload artifact
        uses: actions/upload-artifact@v2
        with:
          name: stash-custom-image
          path: stash-custom.tar.gz
```

### Multi-Architecture Builds

Build for multiple architectures (if needed):

```bash
# Setup buildx
docker buildx create --use

# Build for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --build-arg GITHASH=$(git rev-parse --short HEAD) \
  --build-arg STASH_VERSION=$(git describe --tags) \
  -t stash/custom:latest \
  -f docker/build/x86_64/Dockerfile \
  --push \
  .
```

---

## Comparison: Custom vs Official Image

| Aspect | Custom Build | Official Image |
|--------|-------------|----------------|
| **Source** | Your modified code | Official releases |
| **Updates** | Manual rebuild | `docker pull` |
| **Features** | Your changes included | Only released features |
| **Build Time** | 15-60 minutes | Instant (just pull) |
| **Maintenance** | You maintain | Stash team maintains |
| **Support** | Self-support | Community support |
| **Stability** | Depends on changes | Tested releases |
| **Size** | Varies | Optimized |
| **Python** | Configure yourself | Included |

**When to use custom build:**
- ✅ Testing new features before release
- ✅ Implementing custom modifications
- ✅ Using development branches
- ✅ Contributing to Stash development
- ✅ Need control over exact build

**When to use official image:**
- ✅ Production use
- ✅ Want automatic updates
- ✅ Prefer stability over features
- ✅ Limited time/resources
- ✅ Need community support

---

## Maintenance Schedule

### Daily
- Monitor container health: `docker compose ps`
- Check logs for errors: `docker compose logs --tail=50`

### Weekly  
- Check for Docker image updates (if using your code repo)
- Backup database
- Review disk space usage

### Monthly
- Rebuild image with latest code changes
- Update base images in Dockerfile
- Clean old Docker images: `docker image prune -a`
- Vacuum database

### As Needed
- Rebuild after making code changes
- Update when pulling from upstream
- Rebuild after dependency updates

---

## Migration Checklist (Custom Build)

### Pre-Migration
- [ ] Source code ready and tested on Windows
- [ ] Docker and build tools installed
- [ ] Git repository committed and pushed
- [ ] Backup Windows installation
- [ ] Document current setup

### Build Phase
- [ ] Choose build method (Windows or Synology)
- [ ] Run build script successfully
- [ ] Verify image built correctly
- [ ] (Windows) Export and transfer image
- [ ] (Windows) Load image on Synology
- [ ] Verify image available on Synology

### Migration Phase (Same as Standard)
- [ ] Create Synology directory structure
- [ ] Transfer files to Synology
- [ ] Edit path_mapping.txt
- [ ] Run migrate_database.py
- [ ] Verify migration with verify_migration.py

### Deployment Phase
- [ ] Transfer docker-compose-custom-build.yml
- [ ] Edit volume mappings
- [ ] Set correct permissions
- [ ] Start container
- [ ] Check logs for errors
- [ ] Access web interface

### Verification
- [ ] Test library access
- [ ] Test video playback
- [ ] Verify plugins work
- [ ] Check custom features
- [ ] Perform test scan
- [ ] Verify metadata and images

### Post-Migration
- [ ] Setup automatic backups
- [ ] Document update procedure
- [ ] Test update process
- [ ] Configure monitoring
- [ ] Keep Windows backup for 2 weeks

---

## Additional Resources

- [Standard Migration Guide](README_MIGRATION.md) - For database and config migration
- [Stash Development Docs](https://github.com/stashapp/stash/blob/develop/docs/DEVELOPMENT.md)
- [Docker Build Documentation](https://docs.docker.com/engine/reference/commandline/build/)
- [Stash Discord](https://discord.gg/2TsNFKt) - For development help
- [Stash GitHub](https://github.com/stashapp/stash) - Source code

---

## Success!

Congratulations on deploying your custom-built Stash on Synology! 

You now have:
- ✅ Full control over your Stash build
- ✅ Ability to test and deploy your own features
- ✅ Custom modifications running in production
- ✅ Knowledge of the build and deployment process

Remember to document your changes and consider contributing back to the project!

Enjoy your customized Stash! 🚀

---

## Need Help?

For custom build issues:
1. Check build logs carefully
2. Verify Docker and dependencies
3. Test build locally first
4. Ask in Stash Discord #development channel
5. Review GitHub issues

For migration issues:
1. Refer to standard migration guide
2. Check troubleshooting sections
3. Verify database migration completed
4. Ask in Stash Discord #support channel

When reporting issues, include:
- Build method used (Windows/Synology)
- Git commit/branch
- Docker version
- Build logs/errors
- Steps already tried
















