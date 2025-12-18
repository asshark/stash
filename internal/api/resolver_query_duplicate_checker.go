package api

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
	"github.com/stashapp/stash/pkg/duplicatechecker"
)

func (r *queryResolver) CheckDirectoryDuplicates(ctx context.Context, directory string) (*DirectoryDuplicateCheckResult, error) {
	result := &DirectoryDuplicateCheckResult{
		Files:           []*DuplicateFile{},
		TotalScanned:    0,
		DuplicatesFound: 0,
	}

	// Validate directory path
	absDir, err := filepath.Abs(directory)
	if err != nil {
		return nil, fmt.Errorf("error getting absolute path for directory: %w", err)
	}

	// Check if directory exists
	info, err := os.Stat(absDir)
	if err != nil {
		return nil, fmt.Errorf("directory does not exist or is not accessible: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("path is not a directory: %s", absDir)
	}

	// Scan directory for video files
	logger.Infof("Scanning directory for video files: %s", absDir)
	videoFiles, err := duplicatechecker.ScanDirectoryForVideoFiles(absDir)
	if err != nil {
		return nil, fmt.Errorf("error scanning directory: %w", err)
	}

	result.TotalScanned = len(videoFiles)
	logger.Infof("Found %d video files", result.TotalScanned)

	// First pass: Calculate phash for all files and store them
	type FileWithPhash struct {
		VideoFile duplicatechecker.VideoFileInfo
		Phash     *uint64
		PhashStr  string
	}
	filesWithPhash := make([]FileWithPhash, 0, len(videoFiles))
	phashToFiles := make(map[uint64][]FileWithPhash)

	for _, videoFile := range videoFiles {
		// Calculate phash
		phash, _, err := duplicatechecker.CalculatePhashForFile(videoFile.Path)
		if err != nil {
			logger.Warnf("Error calculating phash for %s: %v", videoFile.Path, err)
			continue
		}

		// Check if phash is nil
		if phash == nil {
			logger.Warnf("Phash is nil for %s", videoFile.Path)
			continue
		}

		phashStr := strconv.FormatUint(uint64(*phash), 16)
		logger.Infof("Calculated phash for %s: %s", videoFile.Path, phashStr)
		fileWithPhash := FileWithPhash{
			VideoFile: videoFile,
			Phash:     phash,
			PhashStr:  phashStr,
		}
		filesWithPhash = append(filesWithPhash, fileWithPhash)
		phashToFiles[*phash] = append(phashToFiles[*phash], fileWithPhash)
	}

	// Second pass: Find duplicates within directory and check database
	processedPhashes := make(map[uint64]bool)
	for _, fileWithPhash := range filesWithPhash {
		phash := *fileWithPhash.Phash

		// Skip if we already processed this phash group
		if processedPhashes[phash] {
			continue
		}

		// Check if there are multiple files with the same phash in the directory
		filesWithSamePhash := phashToFiles[phash]
		isDuplicateInDirectory := len(filesWithSamePhash) > 1

		// Check if phash exists in database
		var matchingScenes []*models.Scene
		if err := r.withReadTxn(ctx, func(ctx context.Context) error {
			var err error
			logger.Infof("Searching for scenes with phash: %s (int64: %d)", fileWithPhash.PhashStr, int64(phash))
			matchingScenes, err = duplicatechecker.FindScenesByPhash(ctx, r.repository, int64(phash))
			if err != nil {
				return err
			}
			logger.Infof("Found %d matching scenes for phash %s", len(matchingScenes), fileWithPhash.PhashStr)

			// Load required data for scenes
			for _, scene := range matchingScenes {
				// Load primary file for scene paths
				if err := scene.LoadPrimaryFile(ctx, r.repository.File); err != nil {
					logger.Warnf("Error loading primary file for scene %d: %v", scene.ID, err)
				}
			}

			return nil
		}); err != nil {
			logger.Warnf("Error finding scenes by phash for %s: %v", fileWithPhash.VideoFile.Path, err)
			continue
		}

		logger.Infof("File %s: isDuplicateInDirectory=%v, matchingScenesInDB=%d", 
			fileWithPhash.VideoFile.Path, isDuplicateInDirectory, len(matchingScenes))

		// Add to duplicates if:
		// 1. There are multiple files with the same phash in the directory, OR
		// 2. The phash exists in the database (file is duplicate of something already in Stash)
		if isDuplicateInDirectory || len(matchingScenes) > 0 {
			// Mark this phash group as processed
			processedPhashes[phash] = true

			// Add all files with this phash as duplicates
			for _, file := range filesWithSamePhash {
				duplicateFile := &DuplicateFile{
					Path:           file.VideoFile.Path,
					Phash:          file.PhashStr,
					MatchingScenes: matchingScenes,
					FileSize:       int(file.VideoFile.Size),
				}
				result.Files = append(result.Files, duplicateFile)
				result.DuplicatesFound++
			}
		}
	}

	return result, nil
}

