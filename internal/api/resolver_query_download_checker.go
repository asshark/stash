package api

import (
	"context"
	"strconv"

	"github.com/stashapp/stash/pkg/downloadchecker"
	"github.com/stashapp/stash/pkg/logger"
)

func (r *queryResolver) DownloadDirectories(ctx context.Context) ([]*downloadchecker.DownloadDirectory, error) {
	config, err := downloadchecker.LoadDirectories()
	if err != nil {
		return nil, err
	}

	result := make([]*downloadchecker.DownloadDirectory, 0, len(config.Directories))
	for i := range config.Directories {
		result = append(result, &config.Directories[i])
	}

	return result, nil
}

func (r *queryResolver) DownloadDirectoryScans(ctx context.Context, directoryID string) ([]*downloadchecker.DownloadScanSummary, error) {
	scans, err := downloadchecker.ListScans(directoryID)
	if err != nil {
		logger.Errorf("Error listing scans for directory %s: %v", directoryID, err)
		return nil, err
	}

	result := make([]*downloadchecker.DownloadScanSummary, 0, len(scans))
	for i := range scans {
		result = append(result, &scans[i])
	}

	return result, nil
}

func (r *queryResolver) DownloadScanResult(ctx context.Context, scanID string) (*downloadchecker.DownloadScanResult, error) {
	// We need to find which directory this scan belongs to
	// First, try to load from all directories
	config, err := downloadchecker.LoadDirectories()
	if err != nil {
		return nil, err
	}

	var result *downloadchecker.DownloadScanResult
	for _, dir := range config.Directories {
		loadedResult, err := downloadchecker.LoadScanResult(dir.ID, scanID)
		if err == nil {
			result = loadedResult
			break
		}
	}

	if result == nil {
		return nil, nil // Not found
	}

	// Update scene data from database to ensure we have the latest information
	// This is important after file replacement operations
	// Only update scenes that might have changed (optimization: skip if no matching scenes)
	hasMatchingScenes := false
	for i := range result.Files {
		if len(result.Files[i].MatchingScenes) > 0 {
			hasMatchingScenes = true
			break
		}
	}
	
	if hasMatchingScenes {
		logger.Debugf("Updating scene data in scan result %s", scanID)
		if err := r.withReadTxn(ctx, func(ctx context.Context) error {
			updatedCount := 0
			for i := range result.Files {
				file := &result.Files[i]
				for j := range file.MatchingScenes {
					scene := &file.MatchingScenes[j]
					sceneID, err := strconv.Atoi(scene.ID)
					if err != nil {
						logger.Warnf("Invalid scene ID in scan result: %s", scene.ID)
						continue
					}

					// Load scene from database
					dbScene, err := r.repository.Scene.Find(ctx, sceneID)
					if err != nil {
						logger.Warnf("Error loading scene %d from database: %v", sceneID, err)
						continue
					}

					if dbScene == nil {
						logger.Warnf("Scene %d not found in database", sceneID)
						continue
					}

					// Load primary file to get updated metadata
					if err := dbScene.LoadPrimaryFile(ctx, r.repository.File); err != nil {
						logger.Warnf("Error loading primary file for scene %d: %v", sceneID, err)
						continue
					}

					primaryFile := dbScene.Files.Primary()
					if primaryFile != nil {
						oldSize := scene.FileSize
						oldWidth := scene.Width
						oldHeight := scene.Height
						oldDuration := scene.Duration
						
						// Update scene data with fresh data from database
						scene.FileSize = primaryFile.Size
						scene.Width = primaryFile.Width
						scene.Height = primaryFile.Height
						scene.Duration = primaryFile.Duration
						// Keep the original phash from scan for matching purposes
						// but update path in case it changed
						if dbScene.Path != "" {
							scene.Path = dbScene.Path
						}
						
						// Log if data changed
						if oldSize != scene.FileSize || oldWidth != scene.Width || oldHeight != scene.Height || oldDuration != scene.Duration {
							logger.Infof("Updated scene %d data: size %d->%d, resolution %dx%d->%dx%d, duration %.2f->%.2f",
								sceneID, oldSize, scene.FileSize, oldWidth, oldHeight, scene.Width, scene.Height, oldDuration, scene.Duration)
							updatedCount++
						}
					}
				}
			}
			if updatedCount > 0 {
				logger.Infof("Updated %d scenes in scan result %s", updatedCount, scanID)
			}
			return nil
		}); err != nil {
			logger.Warnf("Error updating scene data in scan result: %v", err)
			// Return result anyway, even if update failed
		}
	}

	return result, nil
}

