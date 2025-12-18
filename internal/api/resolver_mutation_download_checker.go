package api

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"github.com/stashapp/stash/internal/manager"
	"github.com/stashapp/stash/pkg/downloadchecker"
	"github.com/stashapp/stash/pkg/logger"
)

func (r *mutationResolver) AddDownloadDirectory(ctx context.Context, path string, name string) (*downloadchecker.DownloadDirectory, error) {
	// Validate directory path
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("error getting absolute path: %w", err)
	}

	// Check if directory exists
	info, err := os.Stat(absPath)
	if err != nil {
		return nil, fmt.Errorf("directory does not exist or is not accessible: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("path is not a directory: %s", absPath)
	}

	dir, err := downloadchecker.AddDirectory(absPath, name)
	if err != nil {
		return nil, err
	}

	return dir, nil
}

func (r *mutationResolver) RemoveDownloadDirectory(ctx context.Context, directoryID string) (bool, error) {
	if err := downloadchecker.RemoveDirectory(directoryID); err != nil {
		return false, err
	}
	return true, nil
}

func (r *mutationResolver) StartDownloadDirectoryScan(ctx context.Context, directoryID string) (string, error) {
	// Get directory info
	dir, err := downloadchecker.GetDirectory(directoryID)
	if err != nil {
		return "", fmt.Errorf("directory not found: %w", err)
	}

	// Create and start the scan task
	mgr := manager.GetInstance()
	task := manager.NewDownloadScanTask(mgr.Repository, directoryID, dir.Path)

	jobID := mgr.JobManager.Add(ctx, fmt.Sprintf("Scanning download directory: %s", dir.Name), task)

	logger.Infof("Started download directory scan job %d for directory %s", jobID, dir.Path)

	// Save job ID in directory configuration
	jobIDStr := strconv.Itoa(jobID)
	if err := downloadchecker.SetActiveScanJobID(directoryID, jobIDStr); err != nil {
		logger.Warnf("Error saving active scan job ID for directory %s: %v", directoryID, err)
		// Don't fail the mutation if we can't save the job ID, but log a warning
	}

	return jobIDStr, nil
}

func (r *mutationResolver) ClearDownloadDirectoryScans(ctx context.Context, directoryID string) (bool, error) {
	if err := downloadchecker.ClearScanResults(directoryID); err != nil {
		logger.Errorf("Error clearing scan results for directory %s: %v", directoryID, err)
		return false, fmt.Errorf("error clearing scan results: %w", err)
	}
	logger.Infof("Successfully cleared scan results for directory %s", directoryID)
	return true, nil
}

