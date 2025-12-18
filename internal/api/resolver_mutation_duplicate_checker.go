package api

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"

	"github.com/stashapp/stash/internal/manager"
	"github.com/stashapp/stash/pkg/duplicatechecker"
	"github.com/stashapp/stash/pkg/downloadchecker"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/job"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
)

func (r *mutationResolver) DeleteDuplicateFiles(ctx context.Context, paths []string) (bool, error) {
	if len(paths) == 0 {
		return false, fmt.Errorf("no paths provided")
	}

	// For security, we need to validate that all paths are absolute
	// Since we don't have the original directory context, we'll validate that
	// paths are absolute and exist
	for _, path := range paths {
		if !filepath.IsAbs(path) {
			return false, fmt.Errorf("path must be absolute: %s", path)
		}
	}

	logger.Infof("Deleting %d duplicate files", len(paths))

	// Delete files safely
	if err := duplicatechecker.DeleteFilesSafely(paths); err != nil {
		return false, fmt.Errorf("error deleting files: %w", err)
	}

	// Also remove files from download checker scan results
	logger.Infof("Removing files from download checker scan results...")
	if err := downloadchecker.RemoveFilesFromScanResultByPaths(paths); err != nil {
		logger.Warnf("Error removing files from download checker scan results: %v", err)
		// Don't fail the mutation if we can't update scan results, but log a warning
	}

	logger.Infof("Successfully deleted %d duplicate files", len(paths))
	return true, nil
}

func (r *mutationResolver) ReplaceDuplicateWithScene(ctx context.Context, sceneID string, duplicatePath string) (string, error) {
	if duplicatePath == "" {
		return "", fmt.Errorf("duplicate path is required")
	}

	if !filepath.IsAbs(duplicatePath) {
		return "", fmt.Errorf("duplicate path must be absolute: %s", duplicatePath)
	}

	sceneIntID, err := strconv.Atoi(sceneID)
	if err != nil {
		return "", fmt.Errorf("converting scene id: %w", err)
	}

	// Ensure the duplicate file exists before queuing the job
	if _, err := os.Stat(duplicatePath); err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("duplicate file does not exist: %s", duplicatePath)
		}
		return "", fmt.Errorf("error accessing duplicate file %s: %w", duplicatePath, err)
	}

	logger.Infof("Queuing replaceDuplicateWithScene job for scene %s and duplicate %s", sceneID, duplicatePath)

	mgr := manager.GetInstance()

	j := job.MakeJobExec(func(jobCtx context.Context, progress *job.Progress) error {
		repo := mgr.Repository

		// Load scene and its primary file to get the library path
		var scene *models.Scene
		var primaryFile *models.VideoFile

		if err := repo.WithReadTxn(jobCtx, func(ctx context.Context) error {
			var findErr error
			scene, findErr = repo.Scene.Find(ctx, sceneIntID)
			if findErr != nil {
				return fmt.Errorf("finding scene: %w", findErr)
			}
			if scene == nil {
				return fmt.Errorf("scene not found: %s", sceneID)
			}

			if err := scene.LoadPrimaryFile(ctx, repo.File); err != nil {
				return fmt.Errorf("loading primary file: %w", err)
			}

			primaryFile = scene.Files.Primary()
			if primaryFile == nil {
				return fmt.Errorf("scene %s has no primary file", sceneID)
			}

			return nil
		}); err != nil {
			return err
		}

		libraryPath := primaryFile.Base().Path
		if libraryPath == "" {
			// Fallback to scene.Path if for some reason Base().Path is empty
			libraryPath = scene.Path
		}

		if libraryPath == "" {
			return fmt.Errorf("scene %s has no known library file path", sceneID)
		}

		// Ensure destination directory exists
		destDir := filepath.Dir(libraryPath)
		if err := fsutil.EnsureDirAll(destDir); err != nil {
			return fmt.Errorf("creating destination directory %s: %w", destDir, err)
		}

		// Copy the duplicate file over the existing library file (keep source file)
		if err := copyFileReplacing(duplicatePath, libraryPath); err != nil {
			return fmt.Errorf("replacing library file %s with %s: %w", libraryPath, duplicatePath, err)
		}

		// Note: We do NOT remove the duplicate entry from download checker scan results
		// because the source file remains in the Download directory. The report will
		// be updated after metadata scan to reflect the new library file data.

		logger.Infof("Finished filesystem replaceDuplicateWithScene for scene %s (source file kept at %s)", sceneID, duplicatePath)
		return nil
	})

	jobID := mgr.JobManager.Add(ctx, fmt.Sprintf("Replacing file for scene %s", sceneID), j)
	logger.Infof("Queued replaceDuplicateWithScene job %d for scene %s", jobID, sceneID)

	return strconv.Itoa(jobID), nil
}

// copyFileReplacing copies a file from src to dst, replacing any existing destination file.
// The source file is kept intact (not deleted).
func copyFileReplacing(src, dst string) error {
	if src == dst {
		// Nothing to do
		return nil
	}

	// Remove destination if it exists so that we can safely replace it.
	if err := os.Remove(dst); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("removing existing destination file %s: %w", dst, err)
	}

	// Open source file for reading
	srcFile, err := os.Open(src)
	if err != nil {
		return fmt.Errorf("opening source file %s: %w", src, err)
	}
	defer srcFile.Close()

	// Create destination file
	dstFile, err := os.Create(dst)
	if err != nil {
		return fmt.Errorf("creating destination file %s: %w", dst, err)
	}

	// Copy file contents
	if _, err := io.Copy(dstFile, srcFile); err != nil {
		dstFile.Close()
		return fmt.Errorf("copying from %s to %s: %w", src, dst, err)
	}

	// Close destination file
	if err := dstFile.Close(); err != nil {
		return fmt.Errorf("closing destination file %s: %w", dst, err)
	}

	// Source file is kept - do not delete it
	logger.Infof("Copied file from %s to %s (source file kept)", src, dst)
	return nil
}

