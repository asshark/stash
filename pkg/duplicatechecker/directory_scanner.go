package duplicatechecker

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"

	"github.com/stashapp/stash/internal/manager"
	"github.com/stashapp/stash/internal/manager/config"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/hash/videophash"
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
func CalculatePhashForFile(filePath string) (*uint64, float64, error) {
	instance := manager.GetInstance()
	if instance == nil {
		return nil, 0, fmt.Errorf("manager instance not available")
	}

	ffmpegInstance := instance.FFMpeg
	ffprobeInstance := instance.FFProbe

	if ffmpegInstance == nil || ffprobeInstance == nil {
		return nil, 0, fmt.Errorf("ffmpeg/ffprobe not available")
	}

	// Get video file info using ffprobe
	videoFile, err := ffprobeInstance.NewVideoFile(filePath)
	if err != nil {
		return nil, 0, fmt.Errorf("error probing video file %s: %w", filePath, err)
	}

	// Create VideoFile model for phash generation
	vf := &models.VideoFile{
		BaseFile: &models.BaseFile{Path: filePath},
		Duration: videoFile.FileDuration,
	}

	// Generate phash
	phash, err := videophash.Generate(ffmpegInstance, vf)
	if err != nil {
		return nil, 0, fmt.Errorf("error generating phash for %s: %w", filePath, err)
	}

	return phash, videoFile.FileDuration, nil
}

// GetVideoFileProperties retrieves full video file properties including width, height, and duration
func GetVideoFileProperties(filePath string) (width int, height int, duration float64, err error) {
	instance := manager.GetInstance()
	if instance == nil {
		return 0, 0, 0, fmt.Errorf("manager instance not available")
	}

	ffprobeInstance := instance.FFProbe
	if ffprobeInstance == nil {
		return 0, 0, 0, fmt.Errorf("ffprobe not available")
	}

	// Get video file info using ffprobe
	videoFile, err := ffprobeInstance.NewVideoFile(filePath)
	if err != nil {
		return 0, 0, 0, fmt.Errorf("error probing video file %s: %w", filePath, err)
	}

	return videoFile.Width, videoFile.Height, videoFile.FileDuration, nil
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

// ValidatePathsInDirectory validates that all paths are within the specified directory
// This is a security measure to prevent deleting files outside the intended directory
func ValidatePathsInDirectory(paths []string, directory string) error {
	absDir, err := filepath.Abs(directory)
	if err != nil {
		return fmt.Errorf("error getting absolute path for directory: %w", err)
	}

	for _, path := range paths {
		absPath, err := filepath.Abs(path)
		if err != nil {
			return fmt.Errorf("error getting absolute path for %s: %w", path, err)
		}

		rel, err := filepath.Rel(absDir, absPath)
		if err != nil {
			return fmt.Errorf("error checking if path is in directory: %w", err)
		}

		// Check if path is outside directory (contains "..")
		if rel == ".." || len(rel) > 2 && rel[:3] == "../" {
			return fmt.Errorf("path %s is outside directory %s", path, directory)
		}
	}

	return nil
}

// DeleteFilesSafely deletes files from the filesystem safely
func DeleteFilesSafely(paths []string) error {
	for _, path := range paths {
		if err := os.Remove(path); err != nil {
			if !os.IsNotExist(err) {
				return fmt.Errorf("error deleting file %s: %w", path, err)
			}
			// File doesn't exist, which is fine
			logger.Debugf("File %s does not exist, skipping", path)
		} else {
			logger.Infof("Deleted file: %s", path)
		}
	}

	return nil
}





