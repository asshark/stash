#!/usr/bin/env python3
"""
Stash Database Migration Verification Script
=============================================

This script verifies that the database migration was successful
and provides detailed statistics about the paths in the database.

Usage:
    python verify_migration.py <database_path>

Example:
    python verify_migration.py stash-go.sqlite

The script will:
1. Check for remaining Windows-style paths
2. Show statistics about path prefixes
3. Verify path consistency
4. Generate a verification report
"""

import sqlite3
import sys
import os
from collections import defaultdict
from datetime import datetime


class MigrationVerifier:
    def __init__(self, db_path):
        self.db_path = db_path
        self.issues = []
        self.stats = {
            'total_folders': 0,
            'total_files': 0,
            'windows_style_folders': 0,
            'windows_style_files': 0,
            'linux_style_folders': 0,
            'linux_style_files': 0,
            'folder_prefixes': defaultdict(int),
            'file_prefixes': defaultdict(int)
        }
    
    def run(self):
        """Execute verification."""
        print("=" * 70)
        print("Stash Database Migration Verification")
        print("=" * 70)
        print()
        
        if not self._validate_database():
            return False
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            self._analyze_folders(cursor)
            self._analyze_files(cursor)
            self._check_consistency(cursor)
            
            conn.close()
            
            self._display_results()
            self._generate_report()
            
            return len(self.issues) == 0
            
        except sqlite3.Error as e:
            print(f"❌ Database error: {e}")
            return False
    
    def _validate_database(self):
        """Validate database exists and is valid."""
        if not os.path.exists(self.db_path):
            print(f"❌ Database file not found: {self.db_path}")
            return False
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            if 'folders' not in tables or 'files' not in tables:
                print(f"❌ Database doesn't appear to be a Stash database")
                return False
                
        except sqlite3.Error:
            print(f"❌ Invalid SQLite database")
            return False
        
        return True
    
    def _is_windows_path(self, path):
        """Check if path looks like a Windows path."""
        if not path:
            return False
        return ':' in path or '\\' in path
    
    def _get_path_prefix(self, path):
        """Extract the root prefix from a path."""
        if not path:
            return "(empty)"
        
        # For Windows paths
        if ':' in path:
            parts = path.split('\\')
            return parts[0] if parts else path
        
        # For Unix paths
        parts = path.split('/')
        # Get first two parts (e.g., /volume2/video.xxx.clips -> /volume2)
        # or (e.g., /data/Clips -> /data)
        if len(parts) >= 3:
            return f"/{parts[1]}/{parts[2]}"
        elif len(parts) >= 2:
            return f"/{parts[1]}"
        else:
            return path
    
    def _analyze_folders(self, cursor):
        """Analyze folder paths."""
        print("Analyzing folder paths...")
        
        cursor.execute("SELECT id, path FROM folders")
        folders = cursor.fetchall()
        
        self.stats['total_folders'] = len(folders)
        
        for folder_id, path in folders:
            if self._is_windows_path(path):
                self.stats['windows_style_folders'] += 1
                self.issues.append(f"Windows-style folder path: {path} (ID: {folder_id})")
            else:
                self.stats['linux_style_folders'] += 1
            
            prefix = self._get_path_prefix(path)
            self.stats['folder_prefixes'][prefix] += 1
        
        print(f"  Total folders: {self.stats['total_folders']}")
        print(f"  Linux-style: {self.stats['linux_style_folders']}")
        print(f"  Windows-style: {self.stats['windows_style_folders']}")
        if self.stats['windows_style_folders'] > 0:
            print(f"  ⚠️  Found {self.stats['windows_style_folders']} Windows-style paths!")
        print()
    
    def _analyze_files(self, cursor):
        """Analyze file paths."""
        print("Analyzing file paths...")
        
        # Count files - note they only contain basename, not full paths
        cursor.execute("SELECT COUNT(*) FROM files")
        file_count = cursor.fetchone()[0]
        
        self.stats['total_files'] = file_count
        self.stats['linux_style_files'] = file_count
        self.stats['windows_style_files'] = 0
        
        print(f"  Total files: {self.stats['total_files']}")
        print(f"  Note: Files table only stores basename (filename)")
        print(f"        Full paths are in folders table")
        print()
    
    def _check_consistency(self, cursor):
        """Check for consistency issues."""
        print("Checking consistency...")
        
        # Check for empty paths in folders
        cursor.execute("SELECT COUNT(*) FROM folders WHERE path IS NULL OR path = ''")
        empty_folders = cursor.fetchone()[0]
        
        # Check for empty basename in files
        cursor.execute("SELECT COUNT(*) FROM files WHERE basename IS NULL OR basename = ''")
        empty_files = cursor.fetchone()[0]
        
        if empty_folders > 0:
            self.issues.append(f"Found {empty_folders} folders with empty paths")
            print(f"  ⚠️  {empty_folders} folders with empty paths")
        
        if empty_files > 0:
            self.issues.append(f"Found {empty_files} files with empty basename")
            print(f"  ⚠️  {empty_files} files with empty basename")
        
        if empty_folders == 0 and empty_files == 0:
            print(f"  ✅ No empty paths/basenames found")
        
        print()
    
    def _display_results(self):
        """Display verification results."""
        print("=" * 70)
        print("VERIFICATION RESULTS")
        print("=" * 70)
        print()
        
        # Summary
        print("Summary:")
        print("-" * 70)
        print(f"Total folders: {self.stats['total_folders']}")
        print(f"Total files: {self.stats['total_files']}")
        print()
        
        # Migration status
        if self.stats['windows_style_folders'] == 0:
            print("✅ MIGRATION SUCCESSFUL!")
            print("   All folder paths have been converted to Linux-style paths.")
            print("   (Files table only stores basenames, not full paths)")
        else:
            print("⚠️  MIGRATION INCOMPLETE!")
            print(f"   {self.stats['windows_style_folders']} folders still have Windows-style paths")
            print()
            print("   This may indicate:")
            print("   - Some paths were not included in path_mapping.txt")
            print("   - The migration script did not complete successfully")
            print("   - Manual review and re-migration may be needed")
        print()
        
        # Path prefixes
        if self.stats['folder_prefixes']:
            print("Folder Path Prefixes:")
            print("-" * 70)
            for prefix, count in sorted(self.stats['folder_prefixes'].items(), 
                                       key=lambda x: x[1], reverse=True)[:10]:
                print(f"  {prefix:40s} {count:6d} folders")
            print()
        
        # Issues
        if self.issues:
            print("Issues Found:")
            print("-" * 70)
            for i, issue in enumerate(self.issues[:20], 1):
                print(f"{i:3d}. {issue}")
            
            if len(self.issues) > 20:
                print(f"     ... and {len(self.issues) - 20} more issues")
            print()
        else:
            print("✅ No issues found!")
            print()
    
    def _generate_report(self):
        """Generate verification report."""
        report_path = f"{self.db_path}.verification_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write("Stash Database Verification Report\n")
                f.write("=" * 70 + "\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Database: {self.db_path}\n")
                f.write("\n")
                
                f.write("Statistics:\n")
                f.write("-" * 70 + "\n")
                f.write(f"Total folders: {self.stats['total_folders']}\n")
                f.write(f"Linux-style folders: {self.stats['linux_style_folders']}\n")
                f.write(f"Windows-style folders: {self.stats['windows_style_folders']}\n")
                f.write(f"Total files: {self.stats['total_files']}\n")
                f.write(f"Linux-style files: {self.stats['linux_style_files']}\n")
                f.write(f"Windows-style files: {self.stats['windows_style_files']}\n")
                f.write("\n")
                
                f.write("Folder Path Prefixes:\n")
                f.write("-" * 70 + "\n")
                for prefix, count in sorted(self.stats['folder_prefixes'].items(), 
                                           key=lambda x: x[1], reverse=True):
                    f.write(f"{prefix}: {count}\n")
                f.write("\n")
                
                f.write("File Path Prefixes:\n")
                f.write("-" * 70 + "\n")
                for prefix, count in sorted(self.stats['file_prefixes'].items(), 
                                           key=lambda x: x[1], reverse=True):
                    f.write(f"{prefix}: {count}\n")
                f.write("\n")
                
                if self.issues:
                    f.write("Issues Found:\n")
                    f.write("-" * 70 + "\n")
                    for issue in self.issues:
                        f.write(f"{issue}\n")
                    f.write("\n")
                
                status = "SUCCESSFUL" if len(self.issues) == 0 else "INCOMPLETE"
                f.write(f"Migration Status: {status}\n")
            
            print(f"📄 Verification report saved: {report_path}")
            
        except Exception as e:
            print(f"⚠️  Could not save report: {e}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python verify_migration.py <database_path>")
        print("\nExample:")
        print("  python verify_migration.py stash-go.sqlite")
        sys.exit(1)
    
    db_path = sys.argv[1]
    
    verifier = MigrationVerifier(db_path)
    success = verifier.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

