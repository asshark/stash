package downloadchecker

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/google/uuid"
	"github.com/stashapp/stash/internal/manager/config"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/logger"
)

const (
	configFileName     = "download_directories.json"
	scansDirectoryName = "download_scans"
)

// DownloadDirectory represents a configured download directory
type DownloadDirectory struct {
	ID        string    `json:"id"`
	Path      string    `json:"path"`
	Name      string    `json:"name"`
	CreatedAt time.Time `json:"created_at"`
	LastScanID *string   `json:"last_scan_id,omitempty"`
	ActiveScanJobID *string `json:"active_scan_job_id,omitempty"`
}

// DownloadDirectoriesConfig represents the configuration file structure
type DownloadDirectoriesConfig struct {
	Directories []DownloadDirectory `json:"directories"`
}

// DownloadScanSummary represents summary information about a scan
type DownloadScanSummary struct {
	ScanID           string    `json:"scan_id"`
	DirectoryID      string    `json:"directory_id"`
	DirectoryPath   string    `json:"directory_path"`
	ScanStartedAt    time.Time `json:"scan_started_at"`
	ScanCompletedAt  *time.Time `json:"scan_completed_at,omitempty"`
	TotalScanned     int       `json:"total_scanned"`
	DuplicatesFound  int       `json:"duplicates_found"`
	Status           string    `json:"status"` // "running", "completed", "failed"
}

// DownloadDuplicateFile represents a duplicate file found during scan
type DownloadDuplicateFile struct {
	Path           string                    `json:"path" gqlgen:"path"`
	Phash          string                    `json:"phash" gqlgen:"phash"`
	FileSize       int64                     `json:"file_size" gqlgen:"file_size"`
	Width          int                       `json:"width" gqlgen:"width"`
	Height         int                       `json:"height" gqlgen:"height"`
	Duration       float64                   `json:"duration" gqlgen:"duration"`
	MatchingScenes []DownloadMatchingScene   `json:"matching_scenes" gqlgen:"matching_scenes"`
}

// DownloadMatchingScene represents a scene from the library that matches a duplicate file
type DownloadMatchingScene struct {
	ID       string  `json:"id" gqlgen:"id"`
	Title    string  `json:"title" gqlgen:"title"`
	Path     string  `json:"path" gqlgen:"path"`
	FileSize int64   `json:"file_size" gqlgen:"file_size"`
	Width    int     `json:"width" gqlgen:"width"`
	Height   int     `json:"height" gqlgen:"height"`
	Duration float64 `json:"duration" gqlgen:"duration"`
	Phash    string  `json:"phash,omitempty" gqlgen:"phash"`
}

// FilePhashInfo represents phash information for a file (used for caching phash across scans)
type FilePhashInfo struct {
	Path     string  `json:"path"`
	Phash    string  `json:"phash"`
	Width    int     `json:"width"`
	Height   int     `json:"height"`
	Duration float64 `json:"duration"`
	FileSize int64   `json:"file_size"`
}

// DownloadScanResult represents the full result of a scan
type DownloadScanResult struct {
	ScanID          string                 `json:"scan_id" gqlgen:"scan_id"`
	DirectoryID     string                 `json:"directory_id" gqlgen:"directory_id"`
	DirectoryPath   string                 `json:"directory_path" gqlgen:"directory_path"`
	ScanStartedAt   time.Time              `json:"scan_started_at" gqlgen:"scan_started_at"`
	ScanCompletedAt *time.Time             `json:"scan_completed_at,omitempty" gqlgen:"scan_completed_at"`
	TotalScanned    int                    `json:"total_scanned" gqlgen:"total_scanned"`
	DuplicatesFound int                    `json:"duplicates_found" gqlgen:"duplicates_found"`
	Files           []DownloadDuplicateFile `json:"files" gqlgen:"files"`
	// AllFilesPhash stores phash for all scanned files (not just duplicates) for reuse in next scan
	AllFilesPhash   []FilePhashInfo        `json:"all_files_phash,omitempty" gqlgen:"-"`
	Status          string                 `json:"status" gqlgen:"status"`
}

// getMetadataPathOrDefault returns the metadata path, or the config path as fallback
func getMetadataPathOrDefault() string {
	cfg := config.GetInstance()
	metadataPath := cfg.GetMetadataPath()
	if metadataPath == "" {
		// Use config directory as fallback
		metadataPath = cfg.GetConfigPath()
	}
	return metadataPath
}

// getConfigPath returns the path to the download directories config file
func getConfigPath() (string, error) {
	metadataPath := getMetadataPathOrDefault()
	if metadataPath == "" {
		return "", fmt.Errorf("metadata path not configured")
	}
	return filepath.Join(metadataPath, configFileName), nil
}

// getScansDirectoryPath returns the path to the scans directory
func getScansDirectoryPath() (string, error) {
	metadataPath := getMetadataPathOrDefault()
	if metadataPath == "" {
		return "", fmt.Errorf("metadata path not configured")
	}
	return filepath.Join(metadataPath, scansDirectoryName), nil
}

// getScanDirectoryPath returns the path to scans for a specific directory
func getScanDirectoryPath(directoryID string) (string, error) {
	scansDir, err := getScansDirectoryPath()
	if err != nil {
		return "", err
	}
	return filepath.Join(scansDir, directoryID), nil
}

// LoadDirectories loads the download directories configuration
func LoadDirectories() (*DownloadDirectoriesConfig, error) {
	configPath, err := getConfigPath()
	if err != nil {
		return nil, err
	}

	// If file doesn't exist, return empty config
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return &DownloadDirectoriesConfig{
			Directories: []DownloadDirectory{},
		}, nil
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, fmt.Errorf("error reading config file: %w", err)
	}

	var config DownloadDirectoriesConfig
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, fmt.Errorf("error unmarshaling config: %w", err)
	}

	return &config, nil
}

// SaveDirectories saves the download directories configuration
func SaveDirectories(config *DownloadDirectoriesConfig) error {
	configPath, err := getConfigPath()
	if err != nil {
		return err
	}

	// Ensure metadata directory exists
	metadataPath := filepath.Dir(configPath)
	if err := fsutil.EnsureDir(metadataPath); err != nil {
		return fmt.Errorf("error creating metadata directory: %w", err)
	}

	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("error marshaling config: %w", err)
	}

	if err := os.WriteFile(configPath, data, 0644); err != nil {
		return fmt.Errorf("error writing config file: %w", err)
	}

	return nil
}

// AddDirectory adds a new download directory
func AddDirectory(path, name string) (*DownloadDirectory, error) {
	config, err := LoadDirectories()
	if err != nil {
		return nil, err
	}

	// Check if directory already exists
	for _, dir := range config.Directories {
		if dir.Path == path {
			return nil, fmt.Errorf("directory already exists: %s", path)
		}
	}

	directory := DownloadDirectory{
		ID:        uuid.New().String(),
		Path:      path,
		Name:      name,
		CreatedAt: time.Now(),
	}

	config.Directories = append(config.Directories, directory)

	if err := SaveDirectories(config); err != nil {
		return nil, err
	}

	return &directory, nil
}

// RemoveDirectory removes a download directory
func RemoveDirectory(directoryID string) error {
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	found := false
	for i, dir := range config.Directories {
		if dir.ID == directoryID {
			config.Directories = append(config.Directories[:i], config.Directories[i+1:]...)
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("directory not found: %s", directoryID)
	}

	return SaveDirectories(config)
}

// GetDirectory returns a directory by ID
func GetDirectory(directoryID string) (*DownloadDirectory, error) {
	config, err := LoadDirectories()
	if err != nil {
		return nil, err
	}

	for _, dir := range config.Directories {
		if dir.ID == directoryID {
			return &dir, nil
		}
	}

	return nil, fmt.Errorf("directory not found: %s", directoryID)
}

// UpdateDirectoryLastScan updates the last scan ID for a directory
func UpdateDirectoryLastScan(directoryID, scanID string) error {
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	for i := range config.Directories {
		if config.Directories[i].ID == directoryID {
			config.Directories[i].LastScanID = &scanID
			return SaveDirectories(config)
		}
	}

	return fmt.Errorf("directory not found: %s", directoryID)
}

// SetActiveScanJobID zapisuje aktywny job ID dla katalogu
func SetActiveScanJobID(directoryID, jobID string) error {
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	for i := range config.Directories {
		if config.Directories[i].ID == directoryID {
			config.Directories[i].ActiveScanJobID = &jobID
			return SaveDirectories(config)
		}
	}

	return fmt.Errorf("directory not found: %s", directoryID)
}

// ClearActiveScanJobID czyści aktywny job ID dla katalogu
func ClearActiveScanJobID(directoryID string) error {
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	for i := range config.Directories {
		if config.Directories[i].ID == directoryID {
			config.Directories[i].ActiveScanJobID = nil
			return SaveDirectories(config)
		}
	}

	return fmt.Errorf("directory not found: %s", directoryID)
}

// SaveScanResult saves a scan result to disk
func SaveScanResult(result *DownloadScanResult) error {
	logger.Infof("SaveScanResult called: DirectoryID=%s, ScanID=%s, Status=%s", result.DirectoryID, result.ScanID, result.Status)
	
	scanDir, err := getScanDirectoryPath(result.DirectoryID)
	if err != nil {
		logger.Errorf("Error getting scan directory path: %v", err)
		return err
	}

	logger.Infof("Scan directory path: %s", scanDir)

	// Ensure scan directory exists
	if err := fsutil.EnsureDirAll(scanDir); err != nil {
		logger.Errorf("Error creating scan directory: %v", err)
		return fmt.Errorf("error creating scan directory: %w", err)
	}

	scanPath := filepath.Join(scanDir, result.ScanID+".json")
	logger.Infof("Full scan file path: %s", scanPath)

	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		logger.Errorf("Error marshaling scan result: %v", err)
		return fmt.Errorf("error marshaling scan result: %w", err)
	}

	if err := os.WriteFile(scanPath, data, 0644); err != nil {
		logger.Errorf("Error writing scan result file: %v", err)
		return fmt.Errorf("error writing scan result: %w", err)
	}

	logger.Infof("Successfully saved scan result to %s (metadata path: %s)", scanPath, getMetadataPathOrDefault())

	return nil
}

// LoadScanResult loads a scan result from disk
func LoadScanResult(directoryID, scanID string) (*DownloadScanResult, error) {
	scanDir, err := getScanDirectoryPath(directoryID)
	if err != nil {
		return nil, err
	}

	scanPath := filepath.Join(scanDir, scanID+".json")

	data, err := os.ReadFile(scanPath)
	if err != nil {
		return nil, fmt.Errorf("error reading scan result: %w", err)
	}

	var result DownloadScanResult
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("error unmarshaling scan result: %w", err)
	}

	return &result, nil
}

// ListScans lists all scans for a directory
func ListScans(directoryID string) ([]DownloadScanSummary, error) {
	scanDir, err := getScanDirectoryPath(directoryID)
	if err != nil {
		return nil, err
	}

	// If directory doesn't exist, return empty list
	if _, err := os.Stat(scanDir); os.IsNotExist(err) {
		return []DownloadScanSummary{}, nil
	}

	entries, err := os.ReadDir(scanDir)
	if err != nil {
		return nil, fmt.Errorf("error reading scan directory: %w", err)
	}

	var scans []DownloadScanSummary
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		if filepath.Ext(entry.Name()) != ".json" {
			continue
		}

		scanID := entry.Name()[:len(entry.Name())-5] // Remove .json extension
		result, err := LoadScanResult(directoryID, scanID)
		if err != nil {
			logger.Warnf("Error loading scan %s: %v", scanID, err)
			continue
		}

		summary := DownloadScanSummary{
			ScanID:          result.ScanID,
			DirectoryID:     result.DirectoryID,
			DirectoryPath:   result.DirectoryPath,
			ScanStartedAt:   result.ScanStartedAt,
			ScanCompletedAt: result.ScanCompletedAt,
			TotalScanned:    result.TotalScanned,
			DuplicatesFound: result.DuplicatesFound,
			Status:          result.Status,
		}

		scans = append(scans, summary)
	}

	// Sort scans by ScanStartedAt descending (newest first)
	sort.Slice(scans, func(i, j int) bool {
		return scans[i].ScanStartedAt.After(scans[j].ScanStartedAt)
	})

	return scans, nil
}

// RemoveFilesFromScanResult removes specified files from a scan result and updates statistics
func RemoveFilesFromScanResult(scanID string, filePaths []string) error {
	// First, we need to find which directory this scan belongs to
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	// Try to find the scan in all directories
	var foundResult *DownloadScanResult
	for _, dir := range config.Directories {
		result, err := LoadScanResult(dir.ID, scanID)
		if err == nil {
			foundResult = result
			break
		}
	}

	if foundResult == nil {
		return fmt.Errorf("scan result not found: %s", scanID)
	}

	// Create a map of paths to remove for quick lookup
	pathsToRemove := make(map[string]bool)
	for _, path := range filePaths {
		pathsToRemove[path] = true
	}

	// Remove files from the result
	originalCount := len(foundResult.Files)
	foundResult.Files = make([]DownloadDuplicateFile, 0, originalCount)
	removedCount := 0

	for _, file := range foundResult.Files {
		if !pathsToRemove[file.Path] {
			foundResult.Files = append(foundResult.Files, file)
		} else {
			removedCount++
		}
	}

	// Update duplicates found count
	foundResult.DuplicatesFound -= removedCount
	if foundResult.DuplicatesFound < 0 {
		foundResult.DuplicatesFound = 0
	}

	// Save the updated result
	return SaveScanResult(foundResult)
}

// RemoveFilesFromScanResultByPaths removes files from scan results by finding scans that contain them
// This is a fallback method when scanID is not available
func RemoveFilesFromScanResultByPaths(filePaths []string) error {
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	// Normalize paths for comparison
	pathsToRemove := make(map[string]bool)
	for _, path := range filePaths {
		normalized, err := filepath.Abs(path)
		if err != nil {
			normalized = filepath.Clean(path)
		}
		pathsToRemove[normalized] = true
		// Also add original path in case it's stored differently
		pathsToRemove[filepath.Clean(path)] = true
	}

	// Check all directories and their scans
	for _, dir := range config.Directories {
		scans, err := ListScans(dir.ID)
		if err != nil {
			continue
		}

		for _, scanSummary := range scans {
			result, err := LoadScanResult(dir.ID, scanSummary.ScanID)
			if err != nil {
				continue
			}

			// Check if any of the files to remove are in this scan
			hasFilesToRemove := false
			for _, file := range result.Files {
				// Normalize file path for comparison
				normalizedFilePath, err := filepath.Abs(file.Path)
				if err != nil {
					normalizedFilePath = filepath.Clean(file.Path)
				}
				if pathsToRemove[normalizedFilePath] || pathsToRemove[file.Path] {
					hasFilesToRemove = true
					break
				}
			}

			if hasFilesToRemove {
				// Remove files from this scan
				originalFiles := result.Files
				result.Files = make([]DownloadDuplicateFile, 0, len(originalFiles))
				removedCount := 0

				for _, file := range originalFiles {
					// Normalize file path for comparison
					normalizedFilePath, err := filepath.Abs(file.Path)
					if err != nil {
						normalizedFilePath = filepath.Clean(file.Path)
					}
					
					shouldRemove := pathsToRemove[normalizedFilePath] || pathsToRemove[file.Path]
					if !shouldRemove {
						result.Files = append(result.Files, file)
					} else {
						removedCount++
						logger.Infof("Removing file %s from scan %s", file.Path, scanSummary.ScanID)
					}
				}

				// Update duplicates found count
				result.DuplicatesFound -= removedCount
				if result.DuplicatesFound < 0 {
					result.DuplicatesFound = 0
				}

				logger.Infof("Updated scan %s: removed %d files, remaining duplicates: %d", scanSummary.ScanID, removedCount, result.DuplicatesFound)

				// Save the updated result
				if err := SaveScanResult(result); err != nil {
					logger.Errorf("Error saving updated scan result %s: %v", scanSummary.ScanID, err)
				} else {
					logger.Infof("Successfully saved updated scan result %s", scanSummary.ScanID)
				}
			}
		}
	}

	return nil
}

// ClearScanResults removes all scan results for a directory
func ClearScanResults(directoryID string) error {
	scanDir, err := getScanDirectoryPath(directoryID)
	if err != nil {
		return err
	}

	// If directory doesn't exist, nothing to clear
	if _, err := os.Stat(scanDir); os.IsNotExist(err) {
		return nil
	}

	// Remove all files in the scan directory
	entries, err := os.ReadDir(scanDir)
	if err != nil {
		return fmt.Errorf("error reading scan directory: %w", err)
	}

	for _, entry := range entries {
		if !entry.IsDir() && filepath.Ext(entry.Name()) == ".json" {
			filePath := filepath.Join(scanDir, entry.Name())
			if err := os.Remove(filePath); err != nil {
				logger.Warnf("Error removing scan file %s: %v", filePath, err)
			} else {
				logger.Infof("Removed scan file: %s", filePath)
			}
		}
	}

	// Clear last scan ID in directory config
	config, err := LoadDirectories()
	if err != nil {
		return err
	}

	for i := range config.Directories {
		if config.Directories[i].ID == directoryID {
			config.Directories[i].LastScanID = nil
			return SaveDirectories(config)
		}
	}

	return fmt.Errorf("directory not found: %s", directoryID)
}

