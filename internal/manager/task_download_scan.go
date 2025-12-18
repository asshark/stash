package manager

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/stashapp/stash/pkg/downloadchecker"
	"github.com/stashapp/stash/pkg/hash/videophash"
	"github.com/stashapp/stash/pkg/job"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
)

// DownloadScanTask performs a scan of a download directory for duplicates
type DownloadScanTask struct {
	repository   models.Repository
	directoryID  string
	directoryPath string
}

// NewDownloadScanTask creates a new DownloadScanTask
func NewDownloadScanTask(repository models.Repository, directoryID string, directoryPath string) job.JobExec {
	return &DownloadScanTask{
		repository:    repository,
		directoryID:   directoryID,
		directoryPath: directoryPath,
	}
}

func (t *DownloadScanTask) Execute(ctx context.Context, progress *job.Progress) error {
	scanID := uuid.New().String()
	startTime := time.Now()

	// Always clear active scan job ID when function exits
	defer func() {
		if err := downloadchecker.ClearActiveScanJobID(t.directoryID); err != nil {
			logger.Warnf("Error clearing active scan job ID for directory %s: %v", t.directoryID, err)
		} else {
			logger.Infof("Cleared active scan job ID for directory %s", t.directoryID)
		}
	}()

	// Create initial scan result
	scanResult := &downloadchecker.DownloadScanResult{
		ScanID:        scanID,
		DirectoryID:   t.directoryID,
		DirectoryPath: t.directoryPath,
		ScanStartedAt: startTime,
		TotalScanned:  0,
		DuplicatesFound: 0,
		Files:         []downloadchecker.DownloadDuplicateFile{},
		Status:        "running",
	}

	// Save initial scan result
	if err := downloadchecker.SaveScanResult(scanResult); err != nil {
		logger.Errorf("Error saving initial scan result: %v", err)
	}

	// Scan directory for video files
	logger.Infof("Scanning directory for video files: %s", t.directoryPath)
	progress.ExecuteTask("Scanning directory for video files", func() {
		// This is a placeholder - actual scanning happens below
	})

	videoFiles, err := downloadchecker.ScanDirectoryForVideoFiles(t.directoryPath)
	if err != nil {
		scanResult.Status = "failed"
		downloadchecker.SaveScanResult(scanResult)
		return fmt.Errorf("error scanning directory: %w", err)
	}

	totalFiles := len(videoFiles)
	scanResult.TotalScanned = totalFiles
	logger.Infof("Found %d video files", totalFiles)

	if totalFiles == 0 {
		completedTime := time.Now()
		scanResult.ScanCompletedAt = &completedTime
		scanResult.Status = "completed"
		if err := downloadchecker.SaveScanResult(scanResult); err != nil {
			logger.Errorf("Error saving scan result: %v", err)
		}
		if err := downloadchecker.UpdateDirectoryLastScan(t.directoryID, scanID); err != nil {
			logger.Warnf("Error updating directory last scan: %v", err)
		}
		return nil
	}

	// Load previous scan results to reuse phash for existing files
	previousScanPhashMap := make(map[string]string) // path -> phash string
	previousScanFileMap := make(map[string]*downloadchecker.FilePhashInfo) // path -> file info
	logger.Infof("Loading previous scan results for directory %s to reuse phash", t.directoryID)
	previousScans, err := downloadchecker.ListScans(t.directoryID)
	if err != nil {
		logger.Warnf("Error listing previous scans: %v", err)
	} else {
		logger.Infof("Found %d previous scans for directory %s", len(previousScans), t.directoryID)
		if len(previousScans) > 0 {
			// Load the most recent completed scan
			for _, scanSummary := range previousScans {
				logger.Infof("Checking scan %s with status %s", scanSummary.ScanID, scanSummary.Status)
				if scanSummary.Status == "completed" {
					logger.Infof("Loading completed scan %s to reuse phash", scanSummary.ScanID)
					prevResult, err := downloadchecker.LoadScanResult(t.directoryID, scanSummary.ScanID)
					if err != nil {
						logger.Warnf("Error loading scan result %s: %v", scanSummary.ScanID, err)
						continue
					}
					// First, try to load from AllFilesPhash (new format with all files)
					if len(prevResult.AllFilesPhash) > 0 {
						logger.Infof("Loading phash from AllFilesPhash (new format) for scan %s", scanSummary.ScanID)
						for _, filePhash := range prevResult.AllFilesPhash {
							if filePhash.Phash != "" {
								previousScanPhashMap[filePhash.Path] = filePhash.Phash
								// Store full file info for reuse of other properties
								fileCopy := filePhash
								previousScanFileMap[filePhash.Path] = &fileCopy
							}
						}
						logger.Infof("Loaded %d files with phash from previous scan %s (from AllFilesPhash)", len(previousScanPhashMap), scanSummary.ScanID)
					} else {
						// Fallback to old format: build map from Files (only duplicates)
						logger.Infof("Loading phash from Files (old format) for scan %s", scanSummary.ScanID)
						for _, file := range prevResult.Files {
							if file.Phash != "" {
								previousScanPhashMap[file.Path] = file.Phash
								// Convert to FilePhashInfo format
								filePhashInfo := &downloadchecker.FilePhashInfo{
									Path:     file.Path,
									Phash:    file.Phash,
									Width:    file.Width,
									Height:   file.Height,
									Duration: file.Duration,
									FileSize: file.FileSize,
								}
								previousScanFileMap[file.Path] = filePhashInfo
							}
						}
						logger.Infof("Loaded %d files with phash from previous scan %s (from Files, old format)", len(previousScanPhashMap), scanSummary.ScanID)
					}
					break // Use only the most recent scan
				}
			}
		}
	}
	if len(previousScanPhashMap) == 0 {
		logger.Infof("No previous scan results found with phash data for directory %s - will calculate phash for all files", t.directoryID)
	} else {
		logger.Infof("Will reuse phash for %d files from previous scan", len(previousScanPhashMap))
	}

	// Process each file
	type FileWithPhash struct {
		VideoFile downloadchecker.VideoFileInfo
		Phash     *uint64
		PhashStr  string
		Width     int
		Height    int
		Duration  float64
	}
	filesWithPhash := make([]FileWithPhash, 0, totalFiles)
	phashToFiles := make(map[uint64][]FileWithPhash)

	processedCount := 0
	for i, videoFile := range videoFiles {
		if job.IsCancelled(ctx) {
			scanResult.Status = "cancelled"
			downloadchecker.SaveScanResult(scanResult)
			return nil
		}

		filePath := videoFile.Path
		progress.ExecuteTask(fmt.Sprintf("Processing file %d/%d: %s", i+1, totalFiles, filePath), func() {
			// Check if we have phash from previous scan
			var phash *uint64
			var duration float64
			var width, height int
			var phashStr string
			var useExistingPhash bool

			// Check if file exists in previous scan
			if prevFile, exists := previousScanFileMap[filePath]; exists && prevFile.Phash != "" {
				// Use phash from previous scan
				if prevPhashStr, ok := previousScanPhashMap[filePath]; ok {
					phashUint64, err := strconv.ParseUint(prevPhashStr, 16, 64)
					if err == nil {
						phashUint64Val := phashUint64
						phash = &phashUint64Val
						phashStr = prevPhashStr
						useExistingPhash = true
						
						// Reuse other properties from previous scan if available
						width = prevFile.Width
						height = prevFile.Height
						duration = prevFile.Duration
						
						logger.Infof("Reusing phash for %s from previous scan: %s", filePath, phashStr)
					}
				}
			}

			// If we don't have phash from previous scan, calculate it
			if !useExistingPhash {
				if GetInstance() != nil && GetInstance().FFMpeg != nil && GetInstance().FFProbe != nil {
					// Get video file info using ffprobe
					videoFileInfo, err := GetInstance().FFProbe.NewVideoFile(videoFile.Path)
					if err != nil {
						logger.Warnf("Error probing video file %s: %v", videoFile.Path, err)
						return
					}

					// Create VideoFile model for phash generation
					vf := &models.VideoFile{
						BaseFile: &models.BaseFile{Path: videoFile.Path},
						Duration: videoFileInfo.FileDuration,
					}

					// Generate phash
					phash, err = videophash.Generate(GetInstance().FFMpeg, vf)
					if err != nil {
						logger.Warnf("Error calculating phash for %s: %v", videoFile.Path, err)
						return
					}

					duration = videoFileInfo.FileDuration

					// Get video properties from the same videoFileInfo
					width = videoFileInfo.Width
					height = videoFileInfo.Height
					if videoFileInfo.FileDuration > 0 {
						duration = videoFileInfo.FileDuration
					}

					if phash == nil {
						logger.Warnf("Phash is nil for %s", videoFile.Path)
						return
					}

					phashStr = strconv.FormatUint(uint64(*phash), 16)
					logger.Infof("Calculated new phash for %s: %s", videoFile.Path, phashStr)
				} else {
					logger.Warnf("FFMpeg/FFProbe not available for %s", videoFile.Path)
					return
				}
			}

			if phash == nil {
				logger.Warnf("Phash is nil for %s", videoFile.Path)
				return
			}

			fileWithPhash := FileWithPhash{
				VideoFile: videoFile,
				Phash:     phash,
				PhashStr:  phashStr,
				Width:     width,
				Height:    height,
				Duration:  duration,
			}
			filesWithPhash = append(filesWithPhash, fileWithPhash)
			phashToFiles[*phash] = append(phashToFiles[*phash], fileWithPhash)
			processedCount++
		})

		// Update progress after processing file (use processedCount, not i)
		// SetPercent expects value between 0 and 1, not 0-100
		if totalFiles > 0 {
			progressPercent := float64(processedCount) / float64(totalFiles)
			progress.SetPercent(progressPercent)
		}

		// Update scan result periodically
		if (i+1)%10 == 0 {
			scanResult.TotalScanned = processedCount
			if err := downloadchecker.SaveScanResult(scanResult); err != nil {
				logger.Warnf("Error saving scan result: %v", err)
			}
		}
	}

	// Second pass: Find duplicates within directory and check database
	progress.ExecuteTask("Finding duplicates in library", func() {
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
			if err := t.repository.WithTxn(ctx, func(ctx context.Context) error {
				var err error
				matchingScenes, err = downloadchecker.FindScenesByPhash(ctx, t.repository, int64(phash))
				if err != nil {
					return err
				}

				// Load required data for scenes
				for _, scene := range matchingScenes {
					if err := scene.LoadPrimaryFile(ctx, t.repository.File); err != nil {
						logger.Warnf("Error loading primary file for scene %d: %v", scene.ID, err)
					}
				}

				return nil
			}); err != nil {
				logger.Warnf("Error finding scenes by phash for %s: %v", fileWithPhash.VideoFile.Path, err)
				continue
			}

			// Add to duplicates if:
			// 1. There are multiple files with the same phash in the directory, OR
			// 2. The phash exists in the database (file is duplicate of something already in Stash)
			if isDuplicateInDirectory || len(matchingScenes) > 0 {
				processedPhashes[phash] = true

				// Add all files with this phash as duplicates
				for _, file := range filesWithSamePhash {
					// Convert matching scenes to downloadchecker format
					matchingScenesList := make([]downloadchecker.DownloadMatchingScene, 0, len(matchingScenes))
					for _, scene := range matchingScenes {
						scenePhash := ""
						sceneWidth := 0
						sceneHeight := 0
						sceneFileSize := int64(0)
						sceneDuration := float64(0)

						// Get scene file properties from primary file
						if scene.Files.PrimaryLoaded() {
							primaryFile := scene.Files.Primary()
							if primaryFile != nil {
								sceneFileSize = primaryFile.Size
								sceneWidth = primaryFile.Width
								sceneHeight = primaryFile.Height
								// Use DurationFinite to handle Inf/NaN values
								sceneDuration = primaryFile.DurationFinite()
								
								logger.Infof("Scene %d: Width=%d, Height=%d, Size=%d, Duration=%.2f (raw=%.2f), Path=%s", 
									scene.ID, sceneWidth, sceneHeight, sceneFileSize, sceneDuration, primaryFile.Duration, primaryFile.Path)
								
								// Get phash from fingerprints
								if primaryFile.Fingerprints != nil {
									for _, fp := range primaryFile.Fingerprints {
										if fp.Type == models.FingerprintTypePhash {
											if phashVal, ok := fp.Fingerprint.(int64); ok {
												scenePhash = strconv.FormatInt(phashVal, 16)
											}
											break
										}
									}
								}
							} else {
								logger.Warnf("Scene %d: Primary file is nil", scene.ID)
							}
						} else {
							logger.Warnf("Scene %d: Primary file not loaded", scene.ID)
						}

						matchingScenesList = append(matchingScenesList, downloadchecker.DownloadMatchingScene{
							ID:       strconv.Itoa(scene.ID),
							Title:    scene.GetTitle(),
							Path:     scene.Path,
							FileSize: sceneFileSize,
							Width:    sceneWidth,
							Height:   sceneHeight,
							Duration: sceneDuration,
							Phash:    scenePhash,
						})
					}

					duplicateFile := downloadchecker.DownloadDuplicateFile{
						Path:           file.VideoFile.Path,
						Phash:          file.PhashStr,
						FileSize:       file.VideoFile.Size,
						Width:          file.Width,
						Height:         file.Height,
						Duration:       file.Duration,
						MatchingScenes: matchingScenesList,
					}
					scanResult.Files = append(scanResult.Files, duplicateFile)
					scanResult.DuplicatesFound++
				}
			}
		}
	})

	// Mark scan as completed
	completedTime := time.Now()
	scanResult.ScanCompletedAt = &completedTime
	scanResult.Status = "completed"
	scanResult.TotalScanned = processedCount

	// Save phash for all scanned files (not just duplicates) for reuse in next scan
	scanResult.AllFilesPhash = make([]downloadchecker.FilePhashInfo, 0, len(filesWithPhash))
	for _, fileWithPhash := range filesWithPhash {
		if fileWithPhash.Phash != nil && fileWithPhash.PhashStr != "" {
			scanResult.AllFilesPhash = append(scanResult.AllFilesPhash, downloadchecker.FilePhashInfo{
				Path:     fileWithPhash.VideoFile.Path,
				Phash:    fileWithPhash.PhashStr,
				Width:    fileWithPhash.Width,
				Height:   fileWithPhash.Height,
				Duration: fileWithPhash.Duration,
				FileSize: fileWithPhash.VideoFile.Size,
			})
		}
	}
	logger.Infof("Saved phash for %d files (all scanned files) for reuse in next scan", len(scanResult.AllFilesPhash))

	logger.Infof("Preparing to save scan result: DirectoryID=%s, ScanID=%s, TotalScanned=%d, DuplicatesFound=%d", 
		t.directoryID, scanID, scanResult.TotalScanned, scanResult.DuplicatesFound)

	// Save final scan result
	if err := downloadchecker.SaveScanResult(scanResult); err != nil {
		logger.Errorf("Error saving final scan result: %v", err)
		return fmt.Errorf("error saving scan result: %w", err)
	}

	logger.Infof("Successfully saved scan result for DirectoryID=%s, ScanID=%s", t.directoryID, scanID)

	// Update directory's last scan ID
	if err := downloadchecker.UpdateDirectoryLastScan(t.directoryID, scanID); err != nil {
		logger.Warnf("Error updating directory last scan: %v", err)
	} else {
		logger.Infof("Successfully updated directory last scan ID for DirectoryID=%s, ScanID=%s", t.directoryID, scanID)
	}

	logger.Infof("Download directory scan completed: %d files scanned, %d duplicates found", scanResult.TotalScanned, scanResult.DuplicatesFound)
	progress.SetPercent(100)

	return nil
}

