package api

import (
	"net/http"
	"net/url"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/stashapp/stash/internal/manager"
	"github.com/stashapp/stash/pkg/downloadchecker"
	"github.com/stashapp/stash/pkg/ffmpeg"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/logger"
)

type fileRoutes struct {
	routes
}

func (fr fileRoutes) Routes() chi.Router {
	r := chi.NewRouter()

	r.Get("/stream", fr.StreamFileByPath)

	return r
}

func (fr fileRoutes) StreamFileByPath(w http.ResponseWriter, r *http.Request) {
	logger.Infof("StreamFileByPath: request received - Method: %s, Path: %s, Query: %s", r.Method, r.URL.Path, r.URL.RawQuery)
	
	// Get path from query parameter
	pathParam := r.URL.Query().Get("path")
	if pathParam == "" {
		logger.Warnf("StreamFileByPath: path parameter is missing")
		http.Error(w, "path parameter is required", http.StatusBadRequest)
		return
	}

	// Decode URL-encoded path
	decodedPath, err := url.QueryUnescape(pathParam)
	if err != nil {
		logger.Warnf("Error decoding path parameter: %v", err)
		decodedPath = pathParam // Fallback to original if decoding fails
	}

	logger.Debugf("StreamFileByPath: decoded path: %s", decodedPath)

	// Normalize the path
	normalizedPath, err := filepath.Abs(decodedPath)
	if err != nil {
		logger.Warnf("Error getting absolute path: %v, using cleaned path", err)
		normalizedPath = filepath.Clean(decodedPath)
	}

	logger.Debugf("StreamFileByPath: normalized path: %s", normalizedPath)

	// Validate that the file exists
	exists, err := fsutil.FileExists(normalizedPath)
	if err != nil {
		logger.Warnf("StreamFileByPath: error checking file existence: %v", err)
		http.Error(w, http.StatusText(404), 404)
		return
	}
	if !exists {
		logger.Warnf("StreamFileByPath: file does not exist: %s", normalizedPath)
		http.Error(w, http.StatusText(404), 404)
		return
	}

	// Validate that the file is within a configured download directory
	// This is a security measure to prevent streaming arbitrary files
	config, err := downloadchecker.LoadDirectories()
	if err != nil {
		logger.Errorf("Error loading download directories: %v", err)
		http.Error(w, "Internal server error", http.StatusInternalServerError)
		return
	}

	// Normalize allowed directories for comparison
	allowedDirs := make([]string, 0, len(config.Directories))
	for _, dir := range config.Directories {
		// Normalize directory path
		normalizedDir, err := filepath.Abs(dir.Path)
		if err != nil {
			normalizedDir = filepath.Clean(dir.Path)
		}
		// Ensure trailing separator is consistent
		normalizedDir = filepath.Clean(normalizedDir)
		allowedDirs = append(allowedDirs, normalizedDir)
		logger.Debugf("StreamFileByPath: allowed directory: %s -> %s", dir.Path, normalizedDir)
	}

	// Check if path is within allowed directories
	isAllowed := fsutil.IsPathInDirs(allowedDirs, normalizedPath)
	
	// On Windows, also try case-insensitive comparison as fallback
	if !isAllowed && runtime.GOOS == "windows" {
		normalizedPathLower := strings.ToLower(normalizedPath)
		for _, allowedDir := range allowedDirs {
			allowedDirLower := strings.ToLower(allowedDir)
			if fsutil.IsPathInDir(allowedDirLower, normalizedPathLower) {
				logger.Debugf("StreamFileByPath: path matched with case-insensitive comparison")
				isAllowed = true
				break
			}
		}
	}

	if !isAllowed {
		logger.Warnf("StreamFileByPath: file path %s is not within any configured download directory", normalizedPath)
		logger.Warnf("StreamFileByPath: allowed directories: %v", allowedDirs)
		http.Error(w, "File path is not within a configured download directory", http.StatusForbidden)
		return
	}

	logger.Debugf("StreamFileByPath: streaming file: %s", normalizedPath)

	// Check if file is a video file
	cfg := manager.GetInstance().Config
	videoExts := cfg.GetVideoExtensions()
	if !fsutil.MatchExtension(normalizedPath, videoExts) {
		http.Error(w, "File is not a video file", http.StatusBadRequest)
		return
	}

	// Stream the file directly
	streamRequestCtx := ffmpeg.NewStreamRequestContext(w, r)
	_ = manager.GetInstance().ReadLockManager.ReadLock(streamRequestCtx, normalizedPath)

	_, filename := filepath.Split(normalizedPath)
	contentDisposition := "inline; filename=\"" + filename + "\""
	w.Header().Set("Content-Disposition", contentDisposition)
	w.Header().Set("Content-Type", "video/mp4") // Default to mp4, browser will handle the actual format

	http.ServeFile(w, r, normalizedPath)
}

