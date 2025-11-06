#!/usr/bin/env python3
"""
Stash Database Path Migration Script
=====================================

This script migrates path references in a Stash SQLite database from
Windows paths to Linux/Synology paths.

Usage:
    python migrate_database.py <database_path> <path_mapping_file>

Example:
    python migrate_database.py stash-go.sqlite path_mapping.txt

The script will:
1. Create a backup of the database
2. Read path mappings from the mapping file
3. Update paths in the database
4. Verify the migration
5. Generate a migration report

IMPORTANT: Run this script BEFORE starting Stash in Docker!
"""

import sqlite3
import sys
import os
import shutil
from datetime import datetime
from pathlib import Path
import re


class DatabaseMigrator:
    def __init__(self, db_path, mapping_file):
        self.db_path = db_path
        self.mapping_file = mapping_file
        self.path_mappings = []
        self.backup_path = None
        self.stats = {
            'folders_updated': 0,
            'files_updated': 0,
            'errors': []
        }
    
    def run(self):
        """Execute the full migration process."""
        print("=" * 70)
        print("Stash Database Path Migration")
        print("=" * 70)
        print()
        
        # Validate inputs
        if not self._validate_inputs():
            return False
        
        # Create backup
        if not self._create_backup():
            return False
        
        # Load path mappings
        if not self._load_mappings():
            return False
        
        # Connect to database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Show current state
            self._show_current_paths(cursor)
            
            # Confirm before proceeding
            if not self._confirm_migration():
                print("\n❌ Migration cancelled by user.")
                conn.close()
                return False
            
            # Perform migration
            # Note: Only folders table needs migration as it contains full paths
            # Files table only contains basename (filename without path)
            self._migrate_folders(cursor)
            self._migrate_files(cursor)  # This is a no-op but kept for stats
            
            # Commit changes
            conn.commit()
            
            # Verify migration
            self._verify_migration(cursor)
            
            conn.close()
            
            # Generate report
            self._generate_report()
            
            print("\n" + "=" * 70)
            print("✅ Migration completed successfully!")
            print("=" * 70)
            print(f"\nBackup saved at: {self.backup_path}")
            print(f"Folders updated: {self.stats['folders_updated']}")
            print(f"Total files (count only): {self.stats['total_files']}")
            
            if self.stats['errors']:
                print(f"\n⚠️  Warnings: {len(self.stats['errors'])}")
                for error in self.stats['errors'][:5]:
                    print(f"  - {error}")
                if len(self.stats['errors']) > 5:
                    print(f"  ... and {len(self.stats['errors']) - 5} more")
            
            return True
            
        except sqlite3.Error as e:
            print(f"\n❌ Database error: {e}")
            if self.backup_path and os.path.exists(self.backup_path):
                print(f"\n⚠️  You can restore from backup: {self.backup_path}")
            return False
    
    def _validate_inputs(self):
        """Validate input files exist."""
        if not os.path.exists(self.db_path):
            print(f"❌ Database file not found: {self.db_path}")
            return False
        
        if not os.path.exists(self.mapping_file):
            print(f"❌ Mapping file not found: {self.mapping_file}")
            return False
        
        # Check if it's a valid SQLite database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            if 'folders' not in tables or 'files' not in tables:
                print(f"❌ Database doesn't appear to be a Stash database")
                print(f"   Missing 'folders' or 'files' tables")
                return False
                
        except sqlite3.Error as e:
            print(f"❌ Invalid SQLite database: {e}")
            return False
        
        return True
    
    def _create_backup(self):
        """Create a backup of the database."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.backup_path = f"{self.db_path}.backup_{timestamp}"
        
        try:
            print(f"Creating backup: {self.backup_path}")
            shutil.copy2(self.db_path, self.backup_path)
            print("✅ Backup created successfully\n")
            return True
        except Exception as e:
            print(f"❌ Failed to create backup: {e}")
            return False
    
    def _load_mappings(self):
        """Load path mappings from file."""
        print(f"Loading path mappings from: {self.mapping_file}")
        
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse mapping
                    if '|' not in line:
                        print(f"⚠️  Warning: Invalid format on line {line_num}: {line}")
                        continue
                    
                    parts = line.split('|')
                    if len(parts) != 2:
                        print(f"⚠️  Warning: Invalid format on line {line_num}: {line}")
                        continue
                    
                    windows_path = parts[0].strip()
                    synology_path = parts[1].strip()
                    
                    # Normalize Windows path (handle both forward and back slashes)
                    windows_path = windows_path.replace('/', '\\')
                    
                    self.path_mappings.append({
                        'windows': windows_path,
                        'synology': synology_path,
                        'windows_lower': windows_path.lower()
                    })
            
            if not self.path_mappings:
                print("❌ No valid path mappings found in file")
                return False
            
            print(f"✅ Loaded {len(self.path_mappings)} path mapping(s):\n")
            for mapping in self.path_mappings:
                print(f"   {mapping['windows']} -> {mapping['synology']}")
            print()
            
            # Sort by length (longest first) to handle nested paths correctly
            self.path_mappings.sort(key=lambda x: len(x['windows']), reverse=True)
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to load mappings: {e}")
            return False
    
    def _show_current_paths(self, cursor):
        """Show sample of current paths in database."""
        print("Current paths in database (sample):")
        print("-" * 70)
        
        # Show folder paths
        cursor.execute("SELECT path FROM folders ORDER BY path LIMIT 10")
        folders = cursor.fetchall()
        
        if folders:
            print("\nFolders:")
            for (path,) in folders:
                print(f"  {path}")
        
        # Show file basenames (note: only basename, not full path)
        cursor.execute("SELECT basename FROM files ORDER BY basename LIMIT 10")
        files = cursor.fetchall()
        
        if files:
            print("\nFiles (basename - filename only):")
            for (basename,) in files:
                print(f"  {basename}")
        
        print("\n" + "-" * 70 + "\n")
    
    def _confirm_migration(self):
        """Ask user to confirm migration."""
        response = input("Do you want to proceed with migration? (yes/no): ")
        return response.lower() in ['yes', 'y']
    
    def _convert_path(self, path):
        """Convert a single path using the mappings."""
        if not path:
            return path
        
        # Normalize path separators for comparison
        normalized_path = path.replace('/', '\\')
        normalized_lower = normalized_path.lower()
        
        # Try each mapping
        for mapping in self.path_mappings:
            windows_path = mapping['windows']
            windows_lower = mapping['windows_lower']
            synology_path = mapping['synology']
            
            # Check if path starts with this Windows path
            if normalized_lower.startswith(windows_lower):
                # Replace the Windows path with Synology path
                relative_part = normalized_path[len(windows_path):]
                
                # Convert backslashes to forward slashes
                relative_part = relative_part.replace('\\', '/')
                
                # Remove leading slash if present
                if relative_part.startswith('/'):
                    relative_part = relative_part[1:]
                
                # Construct new path
                if relative_part:
                    new_path = f"{synology_path}/{relative_part}" if not synology_path.endswith('/') else f"{synology_path}{relative_part}"
                else:
                    new_path = synology_path
                
                # Normalize multiple slashes
                new_path = re.sub(r'/+', '/', new_path)
                
                return new_path
        
        # No mapping found
        return None
    
    def _migrate_folders(self, cursor):
        """Migrate folder paths."""
        print("Migrating folder paths...")
        
        cursor.execute("SELECT id, path FROM folders")
        folders = cursor.fetchall()
        
        updates = []
        for folder_id, old_path in folders:
            new_path = self._convert_path(old_path)
            
            if new_path and new_path != old_path:
                updates.append((new_path, folder_id))
                self.stats['folders_updated'] += 1
            elif new_path is None:
                self.stats['errors'].append(f"No mapping for folder: {old_path}")
        
        # Perform batch update
        if updates:
            cursor.executemany("UPDATE folders SET path = ? WHERE id = ?", updates)
            print(f"✅ Updated {len(updates)} folder path(s)")
        else:
            print("⚠️  No folder paths needed updating")
    
    def _migrate_files(self, cursor):
        """Migrate file paths - NOT NEEDED for Stash."""
        # Stash stores only basename (filename) in files table, not full paths
        # The full path is constructed from folders.path + files.basename
        # So we only need to migrate the folders table
        print("Files table: Skipped (only basename stored, full paths are in folders table)")
        
        # Count files for stats
        cursor.execute("SELECT COUNT(*) FROM files")
        self.stats['total_files'] = cursor.fetchone()[0]
        self.stats['files_updated'] = 0
    
    def _verify_migration(self, cursor):
        """Verify migration results."""
        print("\nVerifying migration...")
        
        # Check for remaining Windows paths
        cursor.execute("""
            SELECT path FROM folders 
            WHERE path LIKE '%:%' OR path LIKE '%\\\\%'
            LIMIT 5
        """)
        remaining_folders = cursor.fetchall()
        
        cursor.execute("""
            SELECT basename FROM files 
            WHERE basename LIKE '%:%' OR basename LIKE '%\\\\%'
            LIMIT 5
        """)
        remaining_files = cursor.fetchall()
        
        if remaining_folders or remaining_files:
            print("⚠️  Warning: Some Windows-style paths still remain:")
            if remaining_folders:
                print("\n  Folders:")
                for (path,) in remaining_folders:
                    print(f"    {path}")
            if remaining_files:
                print("\n  Files:")
                for (path,) in remaining_files:
                    print(f"    {path}")
        else:
            print("✅ No Windows-style paths found")
    
    def _generate_report(self):
        """Generate migration report."""
        report_path = f"{self.db_path}.migration_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("Stash Database Migration Report\n")
                f.write("=" * 70 + "\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Database: {self.db_path}\n")
                f.write(f"Mapping file: {self.mapping_file}\n")
                f.write(f"Backup: {self.backup_path}\n")
                f.write("\n")
                
                f.write("Path Mappings:\n")
                f.write("-" * 70 + "\n")
                for mapping in self.path_mappings:
                    f.write(f"{mapping['windows']} -> {mapping['synology']}\n")
                f.write("\n")
                
                f.write("Statistics:\n")
                f.write("-" * 70 + "\n")
                f.write(f"Folders updated: {self.stats['folders_updated']}\n")
                f.write(f"Files (total count): {self.stats['total_files']}\n")
                f.write(f"Note: Files table stores only basename, not full paths\n")
                f.write(f"Warnings: {len(self.stats['errors'])}\n")
                f.write("\n")
                
                if self.stats['errors']:
                    f.write("Warnings/Errors:\n")
                    f.write("-" * 70 + "\n")
                    for error in self.stats['errors']:
                        f.write(f"{error}\n")
            
            print(f"\n📄 Migration report saved: {report_path}")
            
        except Exception as e:
            print(f"⚠️  Could not save report: {e}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python migrate_database.py <database_path> <path_mapping_file>")
        print("\nExample:")
        print("  python migrate_database.py stash-go.sqlite path_mapping.txt")
        sys.exit(1)
    
    db_path = sys.argv[1]
    mapping_file = sys.argv[2]
    
    migrator = DatabaseMigrator(db_path, mapping_file)
    success = migrator.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

