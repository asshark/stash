# Stash Migration Guide: Windows to Synology Docker

This guide will help you migrate your Stash installation from Windows to Synology NAS running in Docker.

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Pre-Migration Preparation](#pre-migration-preparation)
4. [Migration Steps](#migration-steps)
5. [Post-Migration](#post-migration)
6. [Troubleshooting](#troubleshooting)
7. [Plugin Management](#plugin-management)

---

## Overview

This migration involves:
- Moving Stash configuration from Windows to Synology
- Migrating SQLite database with path translation
- Setting up Docker container on Synology
- Preserving plugins and custom configurations
- Maintaining existing blobs and media library structure

**Estimated Time:** 1-2 hours (depending on database size)

---

## Prerequisites

### On Windows:
- Administrative access to current Stash installation
- Ability to stop Stash service
- Access to `C:\Users\areks\.stash\` directory
- Access to network shares on Synology

### On Synology:
- Docker package installed (via Package Center)
- SSH access enabled (optional, but recommended)
- Sufficient storage space in `/volume2/video.xxx.clips/`
- Python 3 installed (for migration scripts)

### Knowledge Requirements:
- Basic understanding of Docker
- Familiarity with command line (Windows and Linux)
- Understanding of file paths and directory structures

---

## Pre-Migration Preparation

### Step 1: Document Current Setup

1. Open Stash on Windows and note down:
   - All library paths (Settings → Library)
   - Example: `L:\Clips`, `M:\Videos`, etc.

2. Check your current Stash version:
   - Look at the footer of the Stash web interface
   - Or check `stash.exe` properties

3. Note any custom configurations:
   - Scrapers installed
   - StashDB/Stash-box connections
   - Custom CSS themes
   - Plugin configurations

### Step 2: Map Windows Drives to Synology Paths

Create a mapping table of your Windows network drives to actual Synology paths:

| Windows Drive | Synology Path | Docker Container Path |
|--------------|---------------|----------------------|
| `L:\Clips` | `/volume2/video.xxx.clips/Clips` | `/data/Clips` |
| `M:\Videos` | `/volume2/video.xxx.clips/Videos` | `/data/Videos` |
| ... | ... | ... |

The Docker container path will be what's stored in the database after migration.

### Step 3: Stop Stash on Windows

**IMPORTANT:** Ensure Stash is completely stopped before proceeding.

1. Close Stash web interface
2. Stop `stash.exe` process
3. Verify it's not running in Task Manager

---

## Migration Steps

### Phase 1: Backup Windows Installation

#### 1.1 Backup Database and Configuration

```powershell
# Open PowerShell as Administrator
cd C:\Users\areks\.stash

# Create backup directory
mkdir C:\Stash-Backup
mkdir C:\Stash-Backup\config

# Copy database
copy stash-go.sqlite C:\Stash-Backup\
copy stash-go.sqlite-shm C:\Stash-Backup\
copy stash-go.sqlite-wal C:\Stash-Backup\

# Copy configuration
copy config.yml C:\Stash-Backup\config\

# Copy plugins directory (if exists)
xcopy /E /I plugins C:\Stash-Backup\config\plugins

# Copy scrapers directory (if exists)
xcopy /E /I scrapers C:\Stash-Backup\config\scrapers
```

#### 1.2 Verify Backup

```powershell
dir C:\Stash-Backup
```

Ensure you see:
- `stash-go.sqlite` (main database file)
- `stash-go.sqlite-shm` and `stash-go.sqlite-wal` (if present)
- `config\` directory with your files

### Phase 2: Prepare Synology

#### 2.1 Create Directory Structure

Connect to Synology via SSH or File Station and create directories:

```bash
# Via SSH
ssh admin@your-synology-ip

# Create directory structure
cd /volume2/video.xxx.clips/stash
mkdir -p config database generated metadata cache

# Note: blobs directory should already exist
# If not, create it:
# mkdir -p blobs
```

Or via File Station:
1. Navigate to `/volume2/video.xxx.clips/stash/`
2. Create folders: `config`, `database`, `generated`, `metadata`, `cache`

#### 2.2 Transfer Files to Synology

Copy the backup from Windows to Synology:

**Method 1: Via Network Share**
1. Map Synology network share on Windows
2. Copy `C:\Stash-Backup\` contents to `/volume2/video.xxx.clips/stash/`

**Method 2: Via SSH/SCP**
```powershell
# From Windows PowerShell
scp -r C:\Stash-Backup\* admin@your-synology-ip:/volume2/video.xxx.clips/stash/database/
```

After transfer, verify file structure on Synology:
```
/volume2/video.xxx.clips/stash/
├── config/
│   ├── config.yml
│   ├── plugins/
│   └── scrapers/
├── database/
│   ├── stash-go.sqlite
│   ├── stash-go.sqlite-shm
│   └── stash-go.sqlite-wal
├── blobs/          (already exists with your data)
├── generated/      (empty for now)
├── cache/          (empty for now)
└── metadata/       (empty for now)
```

### Phase 3: Database Migration

#### 3.1 Prepare Path Mapping File

1. Copy migration scripts to Synology:
   - `migrate_database.py`
   - `path_mapping.txt`
   - `verify_migration.py`

2. Edit `path_mapping.txt` with your actual paths:

```bash
# Connect via SSH
cd /volume2/video.xxx.clips/stash/database

# Edit path_mapping.txt
nano path_mapping.txt
```

Add your mappings (one per line):
```
L:\Clips|/data/Clips
M:\Videos|/data/Videos
N:\Media|/data/Media
```

**Important Notes:**
- Use the Docker container paths (e.g., `/data/Clips`) NOT the Synology paths
- These container paths will be mapped to actual Synology paths in `docker-compose.yml`
- Windows paths are case-insensitive
- Don't add trailing slashes

#### 3.2 Run Migration Script

```bash
cd /volume2/video.xxx.clips/stash/database

# Install Python if not present
# On Synology DSM 7: Python 3 should be available

# Run migration
python3 migrate_database.py stash-go.sqlite path_mapping.txt
```

The script will:
1. Create a backup of the database
2. Show you current paths
3. Ask for confirmation
4. Update all paths in the database
5. Generate a migration report

**Sample Output:**
```
======================================================================
Stash Database Migration
======================================================================

Creating backup: stash-go.sqlite.backup_20250423_143022
✅ Backup created successfully

Loading path mappings from: path_mapping.txt
✅ Loaded 3 path mapping(s):

   L:\Clips -> /data/Clips
   M:\Videos -> /data/Videos
   N:\Media -> /data/Media

Current paths in database (sample):
----------------------------------------------------------------------

Folders:
  L:\Clips\Scene1
  L:\Clips\Scene2
  M:\Videos\Movies

Do you want to proceed with migration? (yes/no): yes

Migrating folder paths...
✅ Updated 1250 folder path(s)

Migrating file paths...
✅ Updated 5430 file path(s)

Verifying migration...
✅ No Windows-style paths found

======================================================================
✅ Migration completed successfully!
======================================================================

Backup saved at: stash-go.sqlite.backup_20250423_143022
Folders updated: 1250
Files updated: 5430
```

#### 3.3 Verify Migration

```bash
python3 verify_migration.py stash-go.sqlite
```

This will show:
- Statistics about paths in your database
- Any remaining Windows-style paths
- Path prefix distribution

**Expected Output (Successful):**
```
======================================================================
Stash Database Migration Verification
======================================================================

Analyzing folder paths...
  Total folders: 1250
  Linux-style: 1250
  Windows-style: 0

Analyzing file paths...
  Total files: 5430
  Linux-style: 5430
  Windows-style: 0

======================================================================
VERIFICATION RESULTS
======================================================================

✅ MIGRATION SUCCESSFUL!
   All paths have been converted to Linux-style paths.
```

### Phase 4: Docker Setup

#### 4.1 Transfer docker-compose.yml to Synology

Copy `docker-compose.yml` to a working directory on Synology:

```bash
# Create working directory
mkdir -p /volume1/docker/stash
cd /volume1/docker/stash

# Copy docker-compose.yml here (via scp, File Station, or nano)
```

#### 4.2 Edit docker-compose.yml

Update the volume mappings to match your setup:

```yaml
volumes:
  # ... existing volumes ...
  
  # IMPORTANT: Update these media library mappings!
  - /volume2/video.xxx.clips/Clips:/data/Clips
  - /volume2/video.xxx.clips/Videos:/data/Videos
  - /volume2/video.xxx.clips/Media:/data/Media
  # Add more as needed
```

**Critical:** The paths on the RIGHT side (container paths like `/data/Clips`) must match what you put in `path_mapping.txt` during database migration!

#### 4.3 Review and Adjust Settings

Check these sections in `docker-compose.yml`:

1. **Port mapping:**
   ```yaml
   ports:
     - "9999:9999"
   ```
   Change `9999` to another port if needed.

2. **Timezone:**
   ```yaml
   environment:
     - TZ=Europe/Warsaw
   ```
   Adjust to your timezone.

3. **Stash configuration paths:**
   ```yaml
   volumes:
     - /volume2/video.xxx.clips/stash/config:/root/.stash
     - /volume2/video.xxx.clips/stash/database:/root/.stash/database
   ```
   
   **IMPORTANT:** The database directory is mapped separately to ensure proper path resolution!

#### 4.4 Set Permissions

```bash
# Ensure proper permissions
chmod -R 755 /volume2/video.xxx.clips/stash/
```

Or use Synology File Station:
1. Right-click on `stash` folder
2. Properties → Permissions
3. Ensure read/write access for Docker user

### Phase 5: Launch Stash

#### 5.1 Start Docker Container

```bash
cd /volume1/docker/stash

# Pull latest Stash image
docker compose pull

# Start in foreground to see logs
docker compose up
```

Watch the logs for any errors. You should see:
```
stash  | Starting Stash...
stash  | Version: vX.X.X
stash  | Migrating database...
stash  | Database migration complete
stash  | Starting web server on port 9999
```

If everything looks good, press `Ctrl+C` and start in background:

```bash
docker compose up -d
```

#### 5.2 Access Stash

Open web browser and navigate to:
```
http://your-synology-ip:9999
```

You should see your Stash interface with all your data!

#### 5.3 Initial Verification

1. **Check Library Access:**
   - Go to Settings → Library
   - Verify all your libraries are listed
   - Click on a library and browse to ensure files are accessible

2. **Check Scenes:**
   - Browse your scenes
   - Verify thumbnails load (from blobs)
   - Check that video playback works

3. **Check Performers/Studios/Tags:**
   - Verify all your metadata is present
   - Check images load correctly

---

## Post-Migration

### Verify Everything Works

#### Database and Paths
- [ ] All libraries are accessible
- [ ] Scene counts match your Windows installation
- [ ] File paths are correct in scene details
- [ ] No broken links or missing files

#### Media Playback
- [ ] Video playback works
- [ ] Preview generation works (test with a new scan)
- [ ] Screenshots and thumbnails display correctly

#### Metadata and Images
- [ ] Performer images load
- [ ] Studio logos display
- [ ] Tag images appear
- [ ] Scene covers show correctly

#### Plugins
- [ ] All plugins are listed in Settings → Plugins
- [ ] Plugins can be executed
- [ ] Plugin logs show no errors

### Configuration Updates

#### Update config.yml (if needed)

```bash
cd /volume2/video.xxx.clips/stash/config
nano config.yml
```

You may need to update:
- Database path (should be `/root/.stash/database/stash-go.sqlite`)
- Generated path (should be `/generated`)
- Cache path (should be `/cache`)
- Blobs path (should be `/blobs`)

#### Re-scan Library (Optional)

If you want Stash to verify all files:

1. Go to Settings → Tasks
2. Click "Scan" button
3. Choose "Scan" (not Clean)
4. Monitor progress

### Optimization

#### Enable Auto-Start

Ensure Docker container starts with Synology:

```yaml
# In docker-compose.yml
services:
  stash:
    restart: unless-stopped
```

This is already set in the provided `docker-compose.yml`.

#### Setup Scheduled Tasks

In Synology DSM:
1. Control Panel → Task Scheduler
2. Create tasks for:
   - Automatic scanning (if desired)
   - Database backup
   - Clean temporary files

#### Database Maintenance

Set up periodic backups:

```bash
# Create backup script
nano /volume2/video.xxx.clips/stash/backup.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/volume2/video.xxx.clips/stash/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
cp /volume2/video.xxx.clips/stash/database/stash-go.sqlite \
   "$BACKUP_DIR/stash-go.sqlite.$DATE"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/stash-go.sqlite.* | tail -n +8 | xargs rm -f

echo "Backup completed: $DATE"
```

```bash
chmod +x /volume2/video.xxx.clips/stash/backup.sh
```

---

## Troubleshooting

### Issue: Container Won't Start

**Check logs:**
```bash
docker compose logs
```

**Common causes:**
- Port 9999 already in use
- Permission issues on volumes
- Database file locked

**Solutions:**
```bash
# Change port in docker-compose.yml
ports:
  - "9998:9999"

# Fix permissions
chmod -R 755 /volume2/video.xxx.clips/stash/

# Ensure database isn't locked
rm /volume2/video.xxx.clips/stash/database/*.sqlite-shm
rm /volume2/video.xxx.clips/stash/database/*.sqlite-wal
```

### Issue: Files Not Found / Empty Library

**Symptoms:**
- Library shows 0 scenes
- "File not found" errors

**Causes:**
- Volume mappings don't match database paths
- Database migration incomplete

**Solutions:**
1. Verify `docker-compose.yml` volume mappings match `path_mapping.txt`
2. Re-run migration script
3. Check with verify_migration.py

**Debug:**
```bash
# Enter container
docker exec -it stash /bin/sh

# Check if files are visible
ls -la /data/Clips/
```

### Issue: Plugins Don't Work

**Symptoms:**
- Plugins not listed
- Plugin errors in logs

**Causes:**
- Plugins not copied to correct location
- Python dependencies missing
- Permission issues

**Solutions:**
```bash
# Verify plugin location
ls -la /volume2/video.xxx.clips/stash/config/plugins/

# Check plugin config
docker exec -it stash cat /root/.stash/config.yml | grep plugin

# Check container logs
docker compose logs | grep -i plugin
```

### Issue: Slow Performance

**Causes:**
- Large database
- Insufficient resources
- Network latency

**Solutions:**
1. Increase Docker resource limits in Synology
2. Enable cache in config.yml
3. Use wired connection instead of WiFi
4. Consider database optimization:

```bash
# Optimize database
docker exec -it stash /bin/sh
cd /root/.stash/database
sqlite3 stash-go.sqlite "VACUUM;"
sqlite3 stash-go.sqlite "ANALYZE;"
```

### Issue: Can't Access from Network

**Solutions:**
1. Check Synology firewall rules
2. Ensure port is forwarded correctly
3. Verify Docker network mode

```bash
# Test from another machine
curl http://synology-ip:9999
```

### Database Corruption

If database appears corrupted:

```bash
# Restore from backup
cd /volume2/video.xxx.clips/stash/database
cp stash-go.sqlite.backup_XXXXXXXX stash-go.sqlite

# Restart container
docker compose restart
```

---

## Plugin Management

### Plugin Directory Structure

```
/volume2/video.xxx.clips/stash/config/plugins/
├── myplugin1/
│   ├── myplugin1.yml
│   ├── myplugin1.py
│   ├── requirements.txt (optional)
│   └── ... (other files)
├── myplugin2/
│   ├── myplugin2.yml
│   └── myplugin2.py
└── ...
```

### Editing Plugins Externally

#### Via SMB/CIFS Share

1. Enable SMB on Synology (Control Panel → File Services)
2. Map network drive on Windows:
   ```
   \\synology-ip\volume2\video.xxx.clips\stash\config\plugins
   ```
3. Edit files with your favorite editor (VS Code, Notepad++, etc.)

#### Via File Station

1. Open Synology File Station
2. Navigate to `/volume2/video.xxx.clips/stash/config/plugins/`
3. Right-click file → Edit (or download, edit, upload)

#### Via SSH

```bash
ssh admin@synology-ip
cd /volume2/video.xxx.clips/stash/config/plugins/myplugin
nano myplugin.py
```

### Installing New Plugins

#### From Community Scrapers

1. In Stash web interface:
   - Settings → Metadata Providers
   - Available Scrapers → Community (stable)
   - Click Install

2. Plugin files are automatically downloaded to:
   ```
   /volume2/video.xxx.clips/stash/config/scrapers/
   ```

#### Manual Installation

1. Create plugin directory:
   ```bash
   mkdir -p /volume2/video.xxx.clips/stash/config/plugins/newplugin
   ```

2. Copy plugin files:
   ```bash
   cd /volume2/video.xxx.clips/stash/config/plugins/newplugin
   # Upload your .py and .yml files here
   ```

3. Restart Stash:
   ```bash
   docker compose restart
   ```

4. Verify in Stash:
   - Settings → Plugins
   - Your plugin should appear in the list

### Python Dependencies

If your plugin requires additional Python packages:

1. Create a `requirements.txt` in plugin directory:
   ```
   requests==2.28.0
   beautifulsoup4==4.11.0
   ```

2. Install in container:
   ```bash
   docker exec -it stash /bin/sh
   pip install -r /root/.stash/plugins/myplugin/requirements.txt
   ```

Or create a custom Dockerfile (advanced).

### Debugging Plugins

#### View Plugin Logs

In Stash web interface:
- Settings → Logs
- Look for plugin-related messages

Or via Docker:
```bash
docker compose logs -f | grep -i plugin
```

#### Test Plugin from Command Line

```bash
# Enter container
docker exec -it stash /bin/sh

# Run plugin manually
cd /root/.stash/plugins/myplugin
python myplugin.py
```

### Backup Plugins

Plugins are included in your config directory:

```bash
# Backup plugins
tar -czf plugins_backup.tar.gz /volume2/video.xxx.clips/stash/config/plugins/

# Restore plugins
tar -xzf plugins_backup.tar.gz -C /
```

---

## Maintenance Schedule

### Daily
- Monitor Docker container health
- Check Stash logs for errors

### Weekly
- Backup database
- Clean cache if needed
- Review disk space usage

### Monthly
- Update Stash to latest version:
  ```bash
  docker compose pull
  docker compose up -d
  ```
- Vacuum database:
  ```bash
  docker exec -it stash sqlite3 /root/.stash/database/stash-go.sqlite "VACUUM;"
  ```
- Review and clean old backups

---

## Additional Resources

- [Stash Documentation](https://docs.stashapp.cc)
- [Stash GitHub](https://github.com/stashapp/stash)
- [Stash Discord](https://discord.gg/2TsNFKt)
- [Stash Discourse Forum](https://discourse.stashapp.cc)
- [Docker Documentation](https://docs.docker.com/)
- [Synology Docker Guide](https://www.synology.com/en-global/dsm/packages/Docker)

---

## Migration Checklist

Use this checklist to track your progress:

### Pre-Migration
- [ ] Document current Windows setup
- [ ] Create path mapping table
- [ ] Stop Stash on Windows
- [ ] Backup database and config
- [ ] Verify backup integrity

### Migration
- [ ] Create Synology directory structure
- [ ] Transfer files to Synology
- [ ] Edit path_mapping.txt with correct paths
- [ ] Run migrate_database.py
- [ ] Verify migration with verify_migration.py
- [ ] Edit docker-compose.yml with volume mappings
- [ ] Set correct permissions

### Launch
- [ ] Pull Docker image
- [ ] Start container
- [ ] Check logs for errors
- [ ] Access Stash web interface
- [ ] Verify libraries are accessible

### Post-Migration
- [ ] Test video playback
- [ ] Verify metadata displays correctly
- [ ] Check plugins work
- [ ] Test search functionality
- [ ] Perform a test scan
- [ ] Setup automatic backups
- [ ] Configure auto-start

### Cleanup
- [ ] Keep Windows backup for 1-2 weeks
- [ ] Remove Windows installation (after verification)
- [ ] Document any custom configurations
- [ ] Share your experience with the community!

---

## Success!

Congratulations! You've successfully migrated Stash from Windows to Synology Docker.

Your Stash instance is now:
- ✅ Running in a Docker container for better isolation
- ✅ Using optimized Linux paths
- ✅ Accessible from any device on your network
- ✅ Easy to backup and restore
- ✅ Ready for external plugin editing

Enjoy your newly migrated Stash! 🎉

---

## Need Help?

If you encounter issues not covered in this guide:

1. Check Stash logs: `docker compose logs -f`
2. Review Docker container status: `docker compose ps`
3. Search [Stash Discord](https://discord.gg/2TsNFKt)
4. Ask on [Stash Discourse](https://discourse.stashapp.cc)
5. Review [GitHub Issues](https://github.com/stashapp/stash/issues)

When asking for help, provide:
- Stash version
- Docker Compose version
- Synology DSM version
- Relevant log excerpts
- Steps you've already tried



