package manager

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
	"slices"
	"strconv"
	"strings"
	"text/template"
	"time"

	"github.com/stashapp/stash/internal/manager/config"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/file"
	"github.com/stashapp/stash/pkg/job"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
	"github.com/stashapp/stash/pkg/scene"
)

// StudioDirectoryMapEntry is one sandbox studio → directory row including optional child-studio filters.
type StudioDirectoryMapEntry struct {
	Directory                string
	ExcludedChildStudioNames []string
	IncludedChildStudioNames []string
}

// OrganizeScenesByStudioOptions configures sandboxOrganizeScenesByStudio.
type OrganizeScenesByStudioOptions struct {
	StudioDirectoryByName map[string]StudioDirectoryMapEntry
	DryMode               bool
	DryRunLogPath           string
	ReFormatFileName        bool
	FileNameFormat          string
	FilenamePlaceholders *FilenamePlaceholderOptions
	// FileCountLimit: nil = unlimited (non-dry); 0 = create destination folders only; N>0 = max N successful moves per scene studio (leaf studio), not per mapped anchor. Ignored when DryMode.
	FileCountLimit *int
	// GroupByYear: when true, append /<year> under the studio destination path when the scene has a date.
	GroupByYear bool
}

// OrganizeScenesByStudioJob moves scene primary files under library paths based on studio hierarchy.
type OrganizeScenesByStudioJob struct {
	Options    OrganizeScenesByStudioOptions
	Repository models.Repository
}

// studioOrganizeStats counts primary files per mapped studio (anchor name from hierarchy).
type studioOrganizeStats struct {
	Total           int
	AlreadyCorrect  int
	ToMove          int
}

// sceneOrganizePlan is the resolved destination path and basename for one scene.
type sceneOrganizePlan struct {
	SceneID        int
	Title          string
	PrimaryPath    string
	DestDir        string
	TargetBasename string
	ExpectedPath   string
	AnchorName     string
	// LeafStudioID is the scene's assigned studio (hierarchy leaf); used for per-studio move caps.
	LeafStudioID int
}

type organizeMoveConflict struct {
	SceneID     int
	Title       string
	SourcePath  string
	DestPath    string
	AnchorName  string
	LeafStudioID int
	SourceSize  string
	DestSize    string
}

func (j *OrganizeScenesByStudioJob) Execute(ctx context.Context, progress *job.Progress) error {
	cfg := config.GetInstance()
	stashPaths := cfg.GetStashPaths()

	if err := j.validateDirectories(stashPaths); err != nil {
		logger.Errorf("[sandbox organize scenes by studio] directory validation failed, aborting: %v\n%s", err, string(debug.Stack()))
		return err
	}

	studioIDs, err := j.resolveMappedStudioIDs(ctx)
	if err != nil {
		logger.Errorf("[sandbox organize scenes by studio] resolving studios failed: %v\n%s", err, string(debug.Stack()))
		return err
	}
	if len(studioIDs) == 0 {
		return fmt.Errorf("no studios matched the provided names")
	}

	depth := -1
	sceneFilter := &models.SceneFilterType{
		Studios: &models.HierarchicalMultiCriterionInput{
			Modifier: models.CriterionModifierIncludes,
			Value:    studioIDs,
			Depth:    &depth,
		},
	}

	var total int
	if err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
		var err error
		_, total, err = scene.QueryWithCount(ctx, j.Repository.Scene, sceneFilter, &models.FindFilterType{})
		return err
	}); err != nil {
		return fmt.Errorf("counting scenes: %w", err)
	}
	progress.SetTotal(total)
	if total == 0 {
		logger.Info("[sandbox organize scenes by studio] no scenes matched")
		return nil
	}

	foldersOnly := false
	moveLimit := -1
	if !j.Options.DryMode && j.Options.FileCountLimit != nil {
		v := *j.Options.FileCountLimit
		if v < 0 {
			return fmt.Errorf("fileCountLimit must be >= 0")
		}
		if v == 0 {
			foldersOnly = true
		} else {
			moveLimit = v
		}
	}
	moveCountByLeafStudio := make(map[int]int)
	var conflicts []organizeMoveConflict

	var nameTpl *template.Template
	if j.Options.ReFormatFileName {
		format := strings.TrimSpace(j.Options.FileNameFormat)
		if format == "" {
			format = DefaultOrganizeSceneFileNameFormat
		}
		var err error
		nameTpl, err = parseOrganizeSceneFilenameTemplate(format)
		if err != nil {
			return fmt.Errorf("fileNameFormat: %w", err)
		}
	}

	stats := j.newEmptyStudioStatsMap()
	unclassified := 0

	var runLog *os.File
	logPath, err := j.resolveRunLogPath()
	if err != nil {
		return err
	}
	if logPath != "" {
		if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
			return fmt.Errorf("creating organize log directory: %w", err)
		}
		runLog, err = os.Create(logPath)
		if err != nil {
			return fmt.Errorf("creating organize log file: %w", err)
		}
		defer runLog.Close()
		logger.Infof("[sandbox organize scenes by studio] logging to %s", logPath)
		if err := j.writeRunLogPreamble(runLog); err != nil {
			return err
		}
	}

	studioCache := make(map[int]*models.Studio)

	const batchSize = 500
	page := 1
	for more := true; more; {
		if job.IsCancelled(ctx) {
			logger.Info("[sandbox organize scenes by studio] cancelled")
			return nil
		}
		perPage := batchSize
		findFilter := &models.FindFilterType{Page: &page, PerPage: &perPage}
		var scenes []*models.Scene
		if err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
			var err error
			scenes, err = scene.Query(ctx, j.Repository.Scene, sceneFilter, findFilter)
			return err
		}); err != nil {
			return fmt.Errorf("querying scenes: %w", err)
		}
		if len(scenes) < batchSize {
			more = false
		} else {
			page++
		}

		for _, sc := range scenes {
			if job.IsCancelled(ctx) {
				return nil
			}

			plan, err := j.buildOrganizeScenePlan(ctx, sc.ID, studioCache, nameTpl)
			unclassified += j.recordOrganizeSceneStats(stats, plan, err)
			if err != nil {
				logger.Warnf("[sandbox organize scenes by studio] scene %d: %v", sc.ID, err)
				progress.Increment()
				continue
			}
			if plan.AnchorName == "" || plan.DestDir == "" || plan.PrimaryPath == "" {
				progress.Increment()
				continue
			}

			title := plan.Title
			if fsutil.PathEqual(plan.PrimaryPath, plan.ExpectedPath) {
				progress.Increment()
				continue
			}
			exists, existsErr := pathExists(plan.ExpectedPath)
			if existsErr != nil {
				logger.Warnf("[sandbox organize scenes by studio] checking destination for scene %d (%s): %v", sc.ID, title, existsErr)
			}
			if exists {
				sourceSize, _ := humanFileSize(plan.PrimaryPath)
				destSize, _ := humanFileSize(plan.ExpectedPath)
				conflicts = append(conflicts, organizeMoveConflict{
					SceneID:      sc.ID,
					Title:        title,
					SourcePath:   plan.PrimaryPath,
					DestPath:     plan.ExpectedPath,
					AnchorName:   plan.AnchorName,
					LeafStudioID: plan.LeafStudioID,
					SourceSize:   sourceSize,
					DestSize:     destSize,
				})
			}

			if runLog != nil {
				if _, err := fmt.Fprintf(runLog, "%d\t%s\t%s => %s\n", sc.ID, title, plan.PrimaryPath, plan.ExpectedPath); err != nil {
					return err
				}
			}

			if j.Options.DryMode {
				progress.Increment()
				continue
			}

			destDir := plan.DestDir
			basename := plan.TargetBasename

			if foldersOnly {
				progress.ExecuteTask(fmt.Sprintf("Ensure folders: %s", destDir), func() {
					if err := j.Repository.WithTxn(ctx, func(ctx context.Context) error {
						return j.ensureOrganizeDestTree(ctx, cfg, destDir)
					}); err != nil {
						logger.Errorf("[sandbox organize scenes by studio] folders for scene %d (%s): %v", sc.ID, title, err)
					}
					progress.Increment()
				})
				continue
			}

			if moveLimit >= 0 && moveCountByLeafStudio[plan.LeafStudioID] >= moveLimit {
				progress.Increment()
				continue
			}

			if job.IsCancelled(ctx) {
				progress.Increment()
				continue
			}

			progress.ExecuteTask(fmt.Sprintf("Moving: %s", basename), func() {
				var movedOK bool
				if err := j.Repository.WithTxn(ctx, func(ctx context.Context) error {
					err := j.moveScenePrimary(ctx, cfg, sc.ID, destDir, basename)
					movedOK = err == nil
					return err
				}); err != nil {
					logger.Errorf("[sandbox organize scenes by studio] scene %d (%s): %v", sc.ID, title, err)
				}
				if moveLimit >= 0 && movedOK {
					moveCountByLeafStudio[plan.LeafStudioID]++
				}
				progress.Increment()
			})
		}
	}
	j.logStudioSummary(stats, unclassified)

	if runLog != nil {
		if err := j.writeRunLogSummary(runLog, stats, unclassified); err != nil {
			return err
		}
		if err := j.writeMoveConflictsSection(runLog, conflicts); err != nil {
			return err
		}
	}

	progress.SetProcessed(total)
	logger.Info("[sandbox organize scenes by studio] finished")
	return nil
}

func (j *OrganizeScenesByStudioJob) newEmptyStudioStatsMap() map[string]*studioOrganizeStats {
	m := make(map[string]*studioOrganizeStats, len(j.Options.StudioDirectoryByName))
	for name := range j.Options.StudioDirectoryByName {
		m[name] = &studioOrganizeStats{}
	}
	return m
}

func (j *OrganizeScenesByStudioJob) buildOrganizeScenePlan(
	ctx context.Context,
	sceneID int,
	studioCache map[int]*models.Studio,
	nameTpl *template.Template,
) (sceneOrganizePlan, error) {
	var plan sceneOrganizePlan
	plan.SceneID = sceneID
	err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
		s, err := j.Repository.Scene.Find(ctx, sceneID)
		if err != nil {
			return err
		}
		if err := s.LoadPrimaryFile(ctx, j.Repository.File); err != nil {
			return err
		}
		pf := s.Files.Primary()
		if pf == nil {
			return fmt.Errorf("no primary file")
		}
		plan.PrimaryPath = pf.Base().Path
		ext := filepath.Ext(plan.PrimaryPath)

		a, d, err := j.mappedAnchorNameAndDestDirInTxn(ctx, s, studioCache)
		if err != nil {
			return err
		}
		plan.AnchorName = a
		plan.DestDir = d
		if strings.TrimSpace(s.Title) != "" {
			plan.Title = strings.TrimSpace(s.Title)
		} else {
			plan.Title = fmt.Sprintf("(scene %d)", s.ID)
		}

		if plan.AnchorName == "" || plan.DestDir == "" {
			return nil
		}
		if s.StudioID != nil {
			plan.LeafStudioID = *s.StudioID
		}

		plan.TargetBasename = filepath.Base(plan.PrimaryPath)
		if j.Options.ReFormatFileName && nameTpl != nil {
			stem, ok, err := j.renderOrganizeBasenameStemInTxn(ctx, s, studioCache, nameTpl)
			if err != nil {
				return err
			}
			if ok {
				plan.TargetBasename = stem + ext
			}
		}
		plan.ExpectedPath = filepath.Join(plan.DestDir, plan.TargetBasename)
		return nil
	})
	return plan, err
}

// recordOrganizeSceneStats updates per-anchor counters for one scene. Returns 1 if unclassified, else 0.
func (j *OrganizeScenesByStudioJob) recordOrganizeSceneStats(stats map[string]*studioOrganizeStats, plan sceneOrganizePlan, err error) int {
	if err != nil {
		return 1
	}
	if plan.AnchorName == "" || plan.DestDir == "" || plan.PrimaryPath == "" {
		return 1
	}
	row := stats[plan.AnchorName]
	if row == nil {
		return 1
	}
	row.Total++
	if fsutil.PathEqual(plan.PrimaryPath, plan.ExpectedPath) {
		row.AlreadyCorrect++
	} else {
		row.ToMove++
	}
	return 0
}

func (j *OrganizeScenesByStudioJob) logStudioSummary(stats map[string]*studioOrganizeStats, unclassified int) {
	names := j.sortedMappedStudioNames()
	for _, name := range names {
		s := stats[name]
		if s == nil {
			continue
		}
		logger.Infof("[sandbox organize scenes by studio] studio %q: total=%d already_correct=%d to_move=%d",
			name, s.Total, s.AlreadyCorrect, s.ToMove)
	}
	if unclassified > 0 {
		logger.Infof("[sandbox organize scenes by studio] unclassified (no primary / no mapped path / load error): %d", unclassified)
	}
}

func (j *OrganizeScenesByStudioJob) sortedMappedStudioNames() []string {
	names := make([]string, 0, len(j.Options.StudioDirectoryByName))
	for n := range j.Options.StudioDirectoryByName {
		names = append(names, n)
	}
	slices.Sort(names)
	return names
}

func (j *OrganizeScenesByStudioJob) writeRunLogPreamble(f *os.File) error {
	mode := "apply"
	if j.Options.DryMode {
		mode = "dry-run"
	}
	if _, err := fmt.Fprintf(f, "# sandbox organize scenes by studio — %s %s\n", mode, time.Now().Format(time.RFC3339)); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(f, "# scene_id\ttitle\tsource_path => dest_path (to_move only)\n"); err != nil {
		return err
	}
	return nil
}

func (j *OrganizeScenesByStudioJob) writeRunLogSummary(f *os.File, stats map[string]*studioOrganizeStats, unclassified int) error {
	if _, err := fmt.Fprintf(f, "\n# Summary per mapped studio (studio_name\ttotal\talready_correct\tto_move)\n"); err != nil {
		return err
	}
	for _, name := range j.sortedMappedStudioNames() {
		s := stats[name]
		if s == nil {
			continue
		}
		if _, err := fmt.Fprintf(f, "%s\t%d\t%d\t%d\n", name, s.Total, s.AlreadyCorrect, s.ToMove); err != nil {
			return err
		}
	}
	if unclassified > 0 {
		if _, err := fmt.Fprintf(f, "# unclassified (no primary / no mapped path / load error): %d\n", unclassified); err != nil {
			return err
		}
	}
	return nil
}

func (j *OrganizeScenesByStudioJob) writeMoveConflictsSection(f *os.File, conflicts []organizeMoveConflict) error {
	if _, err := fmt.Fprintf(f, "\n# destination already exists conflicts (these moves would fail in non-dry mode)\n"); err != nil {
		return err
	}
	if _, err := fmt.Fprintf(f, "# scene_id\tanchor_studio\tleaf_studio_id\tsource_size\tdest_size\ttitle\tsource_path => dest_path\n"); err != nil {
		return err
	}
	for _, c := range conflicts {
		if _, err := fmt.Fprintf(f, "%d\t%s\t%d\t%s\t%s\t%s\t%s => %s\n", c.SceneID, c.AnchorName, c.LeafStudioID, c.SourceSize, c.DestSize, c.Title, c.SourcePath, c.DestPath); err != nil {
			return err
		}
	}
	return nil
}

func (j *OrganizeScenesByStudioJob) validateDirectories(stashPaths config.StashConfigs) error {
	for name, ent := range j.Options.StudioDirectoryByName {
		clean := filepath.Clean(ent.Directory)
		if stashPaths.GetStashFromDirPath(clean) == nil {
			return fmt.Errorf("directory for studio %q (%s) is not within any configured library path", name, clean)
		}
	}
	return nil
}

func (j *OrganizeScenesByStudioJob) resolveMappedStudioIDs(ctx context.Context) ([]string, error) {
	var ids []string
	var nonRoot []string
	if err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
		for _, name := range j.sortedMappedStudioNames() {
			st, err := j.Repository.Studio.FindByName(ctx, name, false)
			if err != nil {
				return fmt.Errorf("studio %q: %w", name, err)
			}
			if st == nil {
				return fmt.Errorf("studio %q not found in database", name)
			}
			if st.ParentID != nil {
				nonRoot = append(nonRoot, fmt.Sprintf("%q (studio id %d, parent_studio_id %d)", name, st.ID, *st.ParentID))
			}
			ids = append(ids, strconv.Itoa(st.ID))
		}
		return nil
	}); err != nil {
		return nil, err
	}
	if len(nonRoot) > 0 {
		return nil, fmt.Errorf(
			"every studio in studioDirectories must be a root studio (no parent studio). These entries have a parent set: %s",
			strings.Join(nonRoot, "; "),
		)
	}
	return ids, nil
}

func (j *OrganizeScenesByStudioJob) resolveRunLogPath() (string, error) {
	p := strings.TrimSpace(j.Options.DryRunLogPath)
	if p == "" {
		return "", nil
	}
	return filepath.Clean(p), nil
}

// mappedAnchorNameAndDestDirInTxn returns the mapped anchor studio name (a key in StudioDirectoryByName)
// and destination directory without basename. Empty strings if the scene is not covered by the map.
// ctx must be a read transaction context.
func (j *OrganizeScenesByStudioJob) mappedAnchorNameAndDestDirInTxn(ctx context.Context, sc *models.Scene, cache map[int]*models.Studio) (anchorName, destDir string, err error) {
	if sc.StudioID == nil {
		return "", "", nil
	}
	chain, err := j.studioChainLeafToRootInTxn(ctx, *sc.StudioID, cache)
	if err != nil {
		return "", "", err
	}
	anchorIdx := -1
	var anchorEntry StudioDirectoryMapEntry
	for i := range chain {
		ent, ok := j.Options.StudioDirectoryByName[chain[i].Name]
		if !ok {
			continue
		}
		if !organizeAnchorMatchesChildFilters(chain, i, ent.ExcludedChildStudioNames, ent.IncludedChildStudioNames) {
			continue
		}
		anchorIdx = i
		anchorEntry = ent
		break
	}
	if anchorIdx < 0 {
		return "", "", nil
	}
	anchorName = chain[anchorIdx].Name
	base := filepath.Clean(anchorEntry.Directory)
	var parts []string
	for k := anchorIdx - 1; k >= 0; k-- {
		parts = append(parts, sanitizePathSegment(chain[k].Name))
	}
	var dest string
	if len(parts) == 0 {
		dest = normalizeOrganizeDestDir(base)
	} else {
		dest = normalizeOrganizeDestDir(filepath.Join(append([]string{base}, parts...)...))
	}
	if j.Options.GroupByYear && sc.Date != nil {
		dest = normalizeOrganizeDestDir(filepath.Join(dest, sanitizePathSegment(strconv.Itoa(sc.Date.Year()))))
	}
	return anchorName, dest, nil
}

// organizeAnchorMatchesChildFilters reports whether the anchor at anchorIdx may be used for this scene chain.
// excluded: any match on the leaf→anchor path (excluding the anchor) rejects the anchor.
// included: when non-empty, at least one match on that path is required; when empty, no include filter.
func organizeAnchorMatchesChildFilters(chain []*models.Studio, anchorIdx int, excluded, included []string) bool {
	if organizeStudioChainTouchesChildNameList(chain, anchorIdx, excluded) {
		return false
	}
	if len(included) == 0 {
		return true
	}
	return organizeStudioChainTouchesChildNameList(chain, anchorIdx, included)
}

// organizeStudioChainTouchesChildNameList reports whether any studio on the path from the leaf
// (chain[0]) toward but not including the anchor at anchorIdx matches one of the names (case-insensitive).
func organizeStudioChainTouchesChildNameList(chain []*models.Studio, anchorIdx int, names []string) bool {
	if len(names) == 0 {
		return false
	}
	for k := 0; k < anchorIdx; k++ {
		leafSide := strings.TrimSpace(chain[k].Name)
		for _, n := range names {
			n = strings.TrimSpace(n)
			if n == "" {
				continue
			}
			if strings.EqualFold(leafSide, n) {
				return true
			}
		}
	}
	return false
}

func normalizeOrganizeDestDir(dir string) string {
	return fsutil.CanonicalizePath(filepath.Clean(dir))
}

func (j *OrganizeScenesByStudioJob) studioChainLeafToRootInTxn(ctx context.Context, leafStudioID int, cache map[int]*models.Studio) ([]*models.Studio, error) {
	var chain []*models.Studio
	curID := leafStudioID
	for i := 0; i < 256; i++ {
		st, err := j.getStudioCachedInTxn(ctx, curID, cache)
		if err != nil {
			return nil, err
		}
		if st == nil {
			return nil, fmt.Errorf("studio id %d not found", curID)
		}
		chain = append(chain, st)
		if st.ParentID == nil {
			break
		}
		curID = *st.ParentID
	}
	return chain, nil
}

func (j *OrganizeScenesByStudioJob) getStudioCachedInTxn(ctx context.Context, id int, cache map[int]*models.Studio) (*models.Studio, error) {
	if s, ok := cache[id]; ok {
		return s, nil
	}
	st, err := j.Repository.Studio.Find(ctx, id)
	if err != nil {
		return nil, err
	}
	cache[id] = st
	return st, nil
}

func (j *OrganizeScenesByStudioJob) resolveOrganizeDestFolder(ctx context.Context, cfg *config.Config, destDir string) (*models.Folder, error) {
	destDir = normalizeOrganizeDestDir(destDir)
	stashPaths := cfg.GetStashPaths()
	if stashPaths.GetStashFromDirPath(destDir) == nil {
		return nil, fmt.Errorf("destination directory %s is not within a configured library path", destDir)
	}
	folder, err := file.GetOrCreateFolderHierarchy(ctx, j.Repository.Folder, destDir, stashPaths.Paths())
	if err != nil {
		return nil, fmt.Errorf("folder hierarchy: %w", err)
	}
	if folder == nil {
		return nil, fmt.Errorf("could not resolve folder for %s", destDir)
	}
	return folder, nil
}

func (j *OrganizeScenesByStudioJob) ensureOrganizeDestTree(ctx context.Context, cfg *config.Config, destDir string) error {
	folder, err := j.resolveOrganizeDestFolder(ctx, cfg, destDir)
	if err != nil {
		return err
	}
	mover := file.NewMover(j.Repository.File, j.Repository.Folder, cfg.GetStashPaths().Paths())
	return mover.CreateFolderHierarchy(folder.Path)
}

func (j *OrganizeScenesByStudioJob) moveScenePrimary(ctx context.Context, cfg *config.Config, sceneID int, destDir string, basename string) error {
	stashPaths := cfg.GetStashPaths()
	mover := file.NewMover(j.Repository.File, j.Repository.Folder, stashPaths.Paths())
	mover.RegisterHooks(ctx)

	folder, err := j.resolveOrganizeDestFolder(ctx, cfg, destDir)
	if err != nil {
		return err
	}

	if err := mover.CreateFolderHierarchy(folder.Path); err != nil {
		return fmt.Errorf("mkdir on disk: %w", err)
	}

	sc, err := j.Repository.Scene.Find(ctx, sceneID)
	if err != nil {
		return err
	}
	if err := sc.LoadPrimaryFile(ctx, j.Repository.File); err != nil {
		return err
	}
	pf := sc.Files.Primary()
	if pf == nil {
		return fmt.Errorf("no primary file")
	}
	if pf.Base().ZipFileID != nil {
		return fmt.Errorf("primary file is inside a zip archive")
	}

	return mover.Move(ctx, pf, folder, basename)
}

func sanitizePathSegment(name string) string {
	s := strings.TrimSpace(name)
	repl := strings.NewReplacer(
		`<`, "_",
		`>`, "_",
		`:`, "_",
		`"`, "_",
		`/`, "_",
		`\`, "_",
		`|`, "_",
		`?`, "_",
		`*`, "_",
	)
	s = repl.Replace(s)
	if s == "" || s == "." || s == ".." {
		return "_studio"
	}
	return s
}

func pathExists(path string) (bool, error) {
	_, err := os.Stat(path)
	if err == nil {
		return true, nil
	}
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	return false, err
}

func humanFileSize(path string) (string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return "n/a", err
	}
	if info.IsDir() {
		return "dir", nil
	}
	size := float64(info.Size())
	units := []string{"B", "KB", "MB", "GB", "TB"}
	unit := units[0]
	for i := 0; i < len(units)-1 && size >= 1024; i++ {
		size /= 1024
		unit = units[i+1]
	}
	if unit == "B" {
		return fmt.Sprintf("%d %s", info.Size(), unit), nil
	}
	return fmt.Sprintf("%.2f %s", size, unit), nil
}
