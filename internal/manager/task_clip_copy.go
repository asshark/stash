package manager

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/stashapp/stash/pkg/job"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
	"github.com/stashapp/stash/pkg/scene"
)

// ClipCopyOptions represents the configuration for copying clips
type ClipCopyOptions struct {
	// Source folders to search for clips
	SourceFolders []string `json:"source_folders"`
	// Destination folder for copied clips
	DestinationFolder string `json:"destination_folder"`
	// Filter criteria for selecting clips to copy
	Filter *models.ClipFilterType `json:"filter"`
	// Whether to create subdirectories in destination based on source structure
	PreserveStructure bool `json:"preserve_structure"`
	// Whether to overwrite existing files in destination
	Overwrite bool `json:"overwrite"`
	// Whether this is a dry run (no actual copying)
	DryRun bool `json:"dry_run"`
	// Whether to move files instead of copying
	MoveFiles bool `json:"move_files"`
}

type ClipCopyJob struct {
	Options    ClipCopyOptions
	Repository models.Repository
	OnComplete func()
}

func (j *ClipCopyJob) Execute(ctx context.Context, progress *job.Progress) error {
	logger.Info("Starting clip copy task")

	// Validate options
	if err := j.validateOptions(); err != nil {
		return fmt.Errorf("invalid options: %w", err)
	}

	// Find clips matching the filter
	clips, err := j.findClips(ctx)
	if err != nil {
		return fmt.Errorf("error finding clips: %w", err)
	}

	if len(clips) == 0 {
		logger.Info("No clips found matching the filter criteria")
		return nil
	}

	logger.Infof("Found %d clips to copy", len(clips))
	progress.SetTotal(len(clips))

	// Copy each clip
	for i, clip := range clips {
		if job.IsCancelled(ctx) {
			logger.Info("Clip copy task cancelled by user")
			return nil
		}

		taskDesc := fmt.Sprintf("Copying clip: %s", clip.Title)
		progress.ExecuteTask(taskDesc, func() {
			if err := j.copyClip(ctx, clip); err != nil {
				logger.Errorf("Error copying clip %s: %v", clip.Title, err)
			}
			progress.Increment()
		})

		logger.Debugf("Copied clip %d/%d: %s", i+1, len(clips), clip.Title)
	}

	if j.OnComplete != nil {
		j.OnComplete()
	}

	logger.Info("Clip copy task completed successfully")
	return nil
}

func (j *ClipCopyJob) validateOptions() error {
	if len(j.Options.SourceFolders) == 0 {
		return fmt.Errorf("source folders must be specified")
	}

	if j.Options.DestinationFolder == "" {
		return fmt.Errorf("destination folder must be specified")
	}

	// Check if destination folder exists or can be created
	if !j.Options.DryRun {
		if err := os.MkdirAll(j.Options.DestinationFolder, 0755); err != nil {
			return fmt.Errorf("cannot create destination folder: %w", err)
		}
	}

	return nil
}

func (j *ClipCopyJob) findClips(ctx context.Context) ([]*models.Clip, error) {
	// Query scenes from database that match the filter
	var clips []*models.Clip

	// Use scenes from Stash database instead of file system scan
	err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
		// Build combined filter: user filter + source folders filter
		sceneFilter := j.buildSceneFilter()

		logger.Infof("ClipCopy: User provided filter: %+v", j.Options.Filter)
		logger.Infof("ClipCopy: Built scene filter: %+v", sceneFilter)

		// Add source folders to filter
		// Each folder needs to have the full filter (rating, organized, etc.) applied
		if len(j.Options.SourceFolders) > 0 && sceneFilter != nil {
			// Create OR chain: (folder1 + filter) OR (folder2 + filter) OR ...
			var combinedFilter *models.SceneFilterType
			var lastOr *models.SceneFilterType

			sep := string(filepath.Separator)
			for _, folder := range j.Options.SourceFolders {
				if !strings.HasSuffix(folder, sep) {
					folder += sep
				}

				// Create a copy of the filter for this folder with path added
				folderFilter := &models.SceneFilterType{
					Rating100: sceneFilter.Rating100,
					Organized: sceneFilter.Organized,
					OCounter:  sceneFilter.OCounter,
					Duration:  sceneFilter.Duration,
					Path: &models.StringCriterionInput{
						Modifier: models.CriterionModifierEquals,
						Value:    folder + "%",
					},
				}

				if combinedFilter == nil {
					combinedFilter = folderFilter
					lastOr = folderFilter
				} else {
					lastOr.Or = folderFilter
					lastOr = folderFilter
				}
			}

			sceneFilter = combinedFilter
		} else if len(j.Options.SourceFolders) > 0 {
			// No user filter, just paths
			pathFilter := scene.PathsFilter(j.Options.SourceFolders)
			sceneFilter = pathFilter
		}

		logger.Infof("ClipCopy: Final scene filter with paths: %+v", sceneFilter)

		// Query scenes - use PerPage: -1 to get ALL results (not just default 25)
		perPage := -1
		findFilter := &models.FindFilterType{
			PerPage: &perPage,
		}
		scenes, err := scene.Query(ctx, j.Repository.Scene, sceneFilter, findFilter)
		if err != nil {
			return err
		}

		logger.Infof("Found %d scenes matching filter", len(scenes))

		// Convert scenes to clips
		for i, sc := range scenes {
			// Load scene files
			if err := sc.LoadFiles(ctx, j.Repository.Scene); err != nil {
				logger.Warnf("Cannot load files for scene %d: %v", sc.ID, err)
				continue
			}

			// Get first file path
			files := sc.Files.List()
			if len(files) == 0 {
				logger.Warnf("Scene %d has no files", sc.ID)
				continue
			}

			filePath := files[0].Base().Path

			// Convert scene to clip
			rating := 0
			if sc.Rating != nil {
				rating = *sc.Rating
			}

			if i < 3 {
				logger.Infof("Scene #%d: ID=%d, Rating=%d, Organized=%v, Path=%s",
					i+1, sc.ID, rating, sc.Organized, filePath)
			}

			clip := &models.Clip{
				ID:        sc.ID,
				Title:     filepath.Base(filePath),
				Rating:    rating,
				Organized: sc.Organized,
				OCounter:  0, // TODO: Add OCounter if available in Scene model
			}
			// Store the full path for copying
			clip.Code = filePath
			clips = append(clips, clip)
		}

		return nil
	})

	if err != nil {
		return nil, err
	}

	logger.Infof("Prepared %d clips for copying", len(clips))
	return clips, nil
}

func (j *ClipCopyJob) buildSceneFilter() *models.SceneFilterType {
	if j.Options.Filter == nil {
		return nil
	}

	sceneFilter := &models.SceneFilterType{}

	// Convert clip filter to scene filter
	if j.Options.Filter.Rating100 != nil {
		sceneFilter.Rating100 = j.Options.Filter.Rating100
	}

	if j.Options.Filter.Organized != nil {
		sceneFilter.Organized = j.Options.Filter.Organized
	}

	if j.Options.Filter.OCounter != nil {
		sceneFilter.OCounter = j.Options.Filter.OCounter
	}

	if j.Options.Filter.Duration != nil {
		sceneFilter.Duration = j.Options.Filter.Duration
	}

	if j.Options.Filter.Path != nil {
		sceneFilter.Path = j.Options.Filter.Path
	}

	// Add more filter conversions as needed...

	return sceneFilter
}

func (j *ClipCopyJob) scanFolderForClips(ctx context.Context, folderPath string) ([]*models.Clip, error) {
	var clips []*models.Clip

	err := filepath.Walk(folderPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// Skip directories
		if info.IsDir() {
			return nil
		}

		// Check if file is a video file (basic check by extension)
		ext := strings.ToLower(filepath.Ext(path))
		videoExts := []string{".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"}

		isVideo := false
		for _, videoExt := range videoExts {
			if ext == videoExt {
				isVideo = true
				break
			}
		}

		if isVideo {
			clip := &models.Clip{
				Title:     filepath.Base(path),
				Code:      filepath.Base(path),
				Details:   "",
				URL:       "",
				Date:      info.ModTime().Format("2006-01-02"),
				Rating:    50, // Default rating
				Organized: false,
				OCounter:  0,
			}
			clips = append(clips, clip)
		}

		return nil
	})

	return clips, err
}

func (j *ClipCopyJob) applyFilter(clips []*models.Clip) []*models.Clip {
	if j.Options.Filter == nil {
		return clips
	}

	var filteredClips []*models.Clip

	for _, clip := range clips {
		if j.clipMatchesFilter(clip) {
			filteredClips = append(filteredClips, clip)
		}
	}

	return filteredClips
}

func (j *ClipCopyJob) clipMatchesFilter(clip *models.Clip) bool {
	filter := j.Options.Filter

	// Check rating filter
	if filter.Rating100 != nil {
		if !j.matchesIntCriterion(clip.Rating, filter.Rating100) {
			return false
		}
	}

	// Check organized filter
	if filter.Organized != nil {
		if clip.Organized != *filter.Organized {
			return false
		}
	}

	// Check o-counter filter
	if filter.OCounter != nil {
		if !j.matchesIntCriterion(clip.OCounter, filter.OCounter) {
			return false
		}
	}

	// Add more filter criteria as needed...

	return true
}

func (j *ClipCopyJob) matchesIntCriterion(value int, criterion *models.IntCriterionInput) bool {
	if criterion == nil {
		return true
	}

	switch criterion.Modifier {
	case models.CriterionModifierEquals:
		return value == criterion.Value
	case models.CriterionModifierNotEquals:
		return value != criterion.Value
	case models.CriterionModifierGreaterThan:
		return value > criterion.Value
	case models.CriterionModifierLessThan:
		return value < criterion.Value
	case models.CriterionModifierBetween:
		return criterion.Value2 != nil &&
			value >= criterion.Value && value <= *criterion.Value2
	default:
		return true
	}
}

func (j *ClipCopyJob) copyClip(ctx context.Context, clip *models.Clip) error {
	operation := "copy"
	if j.Options.MoveFiles {
		operation = "move"
	}

	if j.Options.DryRun {
		logger.Debugf("DRY RUN: Would %s clip %s", operation, clip.Title)
		return nil
	}

	// Find the source file
	sourcePath, err := j.findClipSourcePath(clip)
	if err != nil {
		return fmt.Errorf("cannot find source file for clip %s: %w", clip.Title, err)
	}

	// Determine destination path
	destPath, err := j.getDestinationPath(clip, sourcePath)
	if err != nil {
		return fmt.Errorf("cannot determine destination path: %w", err)
	}

	// Check if destination already exists
	if !j.Options.Overwrite {
		if _, err := os.Stat(destPath); err == nil {
			logger.Debugf("Skipping %s - file already exists", destPath)
			return nil
		}
	}

	// Create destination directory if needed
	destDir := filepath.Dir(destPath)
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return fmt.Errorf("cannot create destination directory: %w", err)
	}

	// Copy or move the file
	if j.Options.MoveFiles {
		if err := j.moveFile(sourcePath, destPath); err != nil {
			return fmt.Errorf("failed to move file: %w", err)
		}
		logger.Debugf("Successfully moved %s to %s", sourcePath, destPath)
	} else {
		if err := j.copyFile(sourcePath, destPath); err != nil {
			return fmt.Errorf("failed to copy file: %w", err)
		}
		logger.Debugf("Successfully copied %s to %s", sourcePath, destPath)
	}

	return nil
}

func (j *ClipCopyJob) findClipSourcePath(clip *models.Clip) (string, error) {
	// clip.Code stores the full file path
	if clip.Code != "" {
		return clip.Code, nil
	}
	return "", fmt.Errorf("source file path not found for clip %s", clip.Title)
}

func (j *ClipCopyJob) getDestinationPath(clip *models.Clip, sourcePath string) (string, error) {
	if j.Options.PreserveStructure {
		// Preserve the folder structure from source
		relPath, err := filepath.Rel(j.Options.SourceFolders[0], sourcePath)
		if err != nil {
			return "", err
		}
		return filepath.Join(j.Options.DestinationFolder, relPath), nil
	} else {
		// Copy directly to destination folder
		return filepath.Join(j.Options.DestinationFolder, filepath.Base(sourcePath)), nil
	}
}

func (j *ClipCopyJob) copyFile(src, dst string) error {
	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, sourceFile)
	if err != nil {
		return err
	}

	return destFile.Sync()
}

func (j *ClipCopyJob) moveFile(src, dst string) error {
	// Try to rename first (works if on same filesystem)
	err := os.Rename(src, dst)
	if err == nil {
		return nil
	}

	// If rename fails, copy and delete
	if err := j.copyFile(src, dst); err != nil {
		return err
	}

	// Delete the source file after successful copy
	if err := os.Remove(src); err != nil {
		logger.Warnf("Failed to delete source file %s after move: %v", src, err)
		return err
	}

	return nil
}
