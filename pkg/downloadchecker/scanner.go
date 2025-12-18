package downloadchecker

import (
	"context"
	"fmt"
	"io/fs"
	"path/filepath"

	"github.com/stashapp/stash/internal/manager/config"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
)

// VideoFileInfo contains information about a video file found during scanning
type VideoFileInfo struct {
	Path     string
	Size     int64
	Phash    *uint64
	Duration float64
	Width    int
	Height   int
}

// ScanDirectoryForVideoFiles recursively scans a directory for video files
func ScanDirectoryForVideoFiles(directory string) ([]VideoFileInfo, error) {
	var videoFiles []VideoFileInfo

	cfg := config.GetInstance()
	videoExts := cfg.GetVideoExtensions()

	err := filepath.WalkDir(directory, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			logger.Warnf("Error accessing path %s: %v", path, err)
			return nil // Continue scanning despite errors
		}

		if d.IsDir() {
			return nil
		}

		// Check if file has video extension
		if !fsutil.MatchExtension(path, videoExts) {
			return nil
		}

		info, err := d.Info()
		if err != nil {
			logger.Warnf("Error getting file info for %s: %v", path, err)
			return nil
		}

		// Skip zero-length files
		if info.Size() == 0 {
			logger.Debugf("Skipping zero-length file: %s", path)
			return nil
		}

		videoFiles = append(videoFiles, VideoFileInfo{
			Path: path,
			Size: info.Size(),
		})

		return nil
	})

	return videoFiles, err
}

// CalculatePhashForFile calculates phash for a video file
// This function is a wrapper that avoids import cycle by accepting ffmpeg/ffprobe instances
func CalculatePhashForFile(filePath string, ffmpegInstance interface{}, ffprobeInstance interface{}) (*uint64, float64, error) {
	// Type assertions will be handled by the caller
	// This is a placeholder - actual implementation will be in task_download_scan.go
	return nil, 0, fmt.Errorf("not implemented - use duplicatechecker.CalculatePhashForFile instead")
}

// FindScenesByPhash finds scenes in the database that have the given phash
func FindScenesByPhash(ctx context.Context, repository models.Repository, phash int64) ([]*models.Scene, error) {
	fingerprint := models.Fingerprint{
		Type:        models.FingerprintTypePhash,
		Fingerprint: phash,
	}

	scenes, err := repository.Scene.FindByFingerprints(ctx, []models.Fingerprint{fingerprint})
	if err != nil {
		return nil, fmt.Errorf("error finding scenes by phash: %w", err)
	}

	return scenes, nil
}

