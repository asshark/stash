package manager

import (
	"context"
	"fmt"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/stashapp/stash/internal/manager/config"
	"github.com/stashapp/stash/pkg/fsutil"
	"github.com/stashapp/stash/pkg/job"
	"github.com/stashapp/stash/pkg/logger"
	"github.com/stashapp/stash/pkg/models"
	"github.com/stashapp/stash/pkg/scene"
)

// SceneDateFilenameFormat identifies one date pattern recognized in scene file names.
// Values match the GraphQL SceneFilenameDateFormat enum names.
type SceneDateFilenameFormat string

const (
	SceneDateFormatYMDDash   SceneDateFilenameFormat = "YYYY_MM_DD"
	SceneDateFormatDMYDash   SceneDateFilenameFormat = "DD_MM_YYYY"
	SceneDateFormatYMDDot    SceneDateFilenameFormat = "YYYY_DOT_MM_DOT_DD"
	SceneDateFormatDMYDot    SceneDateFilenameFormat = "DD_DOT_MM_DOT_YYYY"
	SceneDateFormatYearParen SceneDateFilenameFormat = "YEAR_IN_PARENTHESES"
)

// AllSceneDateFilenameFormats is the default matching order: full dates first, bare year last.
var AllSceneDateFilenameFormats = []SceneDateFilenameFormat{
	SceneDateFormatYMDDash,
	SceneDateFormatDMYDash,
	SceneDateFormatYMDDot,
	SceneDateFormatDMYDot,
	SceneDateFormatYearParen,
}

// SetSceneDatesFromFilenameOptions configures sandboxSetSceneDatesFromFilename.
type SetSceneDatesFromFilenameOptions struct {
	// Paths restricts scanning to scenes whose primary file lies under one of these
	// directories. Empty means all scenes.
	Paths []string
	// Formats are tried in order; first match wins. Empty means AllSceneDateFilenameFormats.
	Formats []SceneDateFilenameFormat
	// Override: when true, the extracted date replaces any existing scene date.
	// When false, only scenes with an empty date are updated.
	Override bool
	// DryMode: when true, only log; no database writes.
	DryMode bool
}

// SetSceneDatesFromFilenameJob scans scenes and sets the scene date parsed from the
// primary file basename.
type SetSceneDatesFromFilenameJob struct {
	Options    SetSceneDatesFromFilenameOptions
	Repository models.Repository
}

type sceneFilenameDateMatcher struct {
	format SceneDateFilenameFormat
	re     *regexp.Regexp
	// parse converts the regex submatches into a date; ok is false when the
	// matched digits do not form a valid calendar date.
	parse func(m []string) (models.Date, bool)
}

var sceneFilenameYMDDashRe = regexp.MustCompile(`(?:^|\D)((?:19|20)\d{2})-(\d{2})-(\d{2})(?:\D|$)`)
var sceneFilenameDMYDashRe = regexp.MustCompile(`(?:^|\D)(\d{2})-(\d{2})-((?:19|20)\d{2})(?:\D|$)`)
var sceneFilenameYMDDotRe = regexp.MustCompile(`(?:^|\D)((?:19|20)\d{2})\.(\d{2})\.(\d{2})(?:\D|$)`)
var sceneFilenameDMYDotRe = regexp.MustCompile(`(?:^|\D)(\d{2})\.(\d{2})\.((?:19|20)\d{2})(?:\D|$)`)
var sceneFilenameYearParenRe = regexp.MustCompile(`\(((?:19|20)\d{2})(?:[^0-9)][^)]*)?\)`)

func parseFullSceneDate(year, month, day string) (models.Date, bool) {
	y, _ := strconv.Atoi(year)
	m, _ := strconv.Atoi(month)
	d, _ := strconv.Atoi(day)
	if m < 1 || m > 12 || d < 1 || d > 31 {
		return models.Date{}, false
	}
	t := time.Date(y, time.Month(m), d, 0, 0, 0, 0, time.UTC)
	// reject normalized overflow dates such as Feb 30
	if t.Year() != y || int(t.Month()) != m || t.Day() != d {
		return models.Date{}, false
	}
	return models.Date{Time: t, Precision: models.DatePrecisionDay}, true
}

func sceneFilenameDateMatcherFor(format SceneDateFilenameFormat) (sceneFilenameDateMatcher, error) {
	switch format {
	case SceneDateFormatYMDDash:
		return sceneFilenameDateMatcher{format, sceneFilenameYMDDashRe, func(m []string) (models.Date, bool) {
			return parseFullSceneDate(m[1], m[2], m[3])
		}}, nil
	case SceneDateFormatDMYDash:
		return sceneFilenameDateMatcher{format, sceneFilenameDMYDashRe, func(m []string) (models.Date, bool) {
			return parseFullSceneDate(m[3], m[2], m[1])
		}}, nil
	case SceneDateFormatYMDDot:
		return sceneFilenameDateMatcher{format, sceneFilenameYMDDotRe, func(m []string) (models.Date, bool) {
			return parseFullSceneDate(m[1], m[2], m[3])
		}}, nil
	case SceneDateFormatDMYDot:
		return sceneFilenameDateMatcher{format, sceneFilenameDMYDotRe, func(m []string) (models.Date, bool) {
			return parseFullSceneDate(m[3], m[2], m[1])
		}}, nil
	case SceneDateFormatYearParen:
		return sceneFilenameDateMatcher{format, sceneFilenameYearParenRe, func(m []string) (models.Date, bool) {
			y, _ := strconv.Atoi(m[1])
			return models.DateFromYear(y), true
		}}, nil
	default:
		return sceneFilenameDateMatcher{}, fmt.Errorf("unknown filename date format %q", format)
	}
}

const sceneDateFromFilenameLogPrefix = "[sandbox set scene dates from filename]"

func (j *SetSceneDatesFromFilenameJob) Execute(ctx context.Context, progress *job.Progress) error {
	matchers, err := j.buildMatchers()
	if err != nil {
		return err
	}

	scanDirs, err := j.resolveScanDirs()
	if err != nil {
		return err
	}

	mode := "apply"
	if j.Options.DryMode {
		mode = "dry-run"
	}
	logger.Infof("%s starting (%s, override=%t, paths=%d, formats=%d)",
		sceneDateFromFilenameLogPrefix, mode, j.Options.Override, len(scanDirs), len(matchers))

	var total int
	if err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
		var err error
		_, total, err = scene.QueryWithCount(ctx, j.Repository.Scene, nil, &models.FindFilterType{})
		return err
	}); err != nil {
		return fmt.Errorf("counting scenes: %w", err)
	}
	progress.SetTotal(total)
	if total == 0 {
		logger.Infof("%s no scenes in database", sceneDateFromFilenameLogPrefix)
		return nil
	}

	var stats struct {
		scanned        int
		outsidePaths   int
		noPrimaryFile  int
		dateAlreadySet int
		noMatch        int
		updated        int
		failed         int
	}

	const batchSize = 500
	sortBy := "id"
	page := 1
	for more := true; more; {
		if job.IsCancelled(ctx) {
			logger.Infof("%s cancelled", sceneDateFromFilenameLogPrefix)
			return nil
		}
		perPage := batchSize
		findFilter := &models.FindFilterType{Page: &page, PerPage: &perPage, Sort: &sortBy}
		var scenes []*models.Scene
		if err := j.Repository.WithReadTxn(ctx, func(ctx context.Context) error {
			var err error
			scenes, err = scene.Query(ctx, j.Repository.Scene, nil, findFilter)
			if err != nil {
				return err
			}
			for _, sc := range scenes {
				if err := sc.LoadPrimaryFile(ctx, j.Repository.File); err != nil {
					return fmt.Errorf("loading primary file for scene %d: %w", sc.ID, err)
				}
			}
			return nil
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
				logger.Infof("%s cancelled", sceneDateFromFilenameLogPrefix)
				return nil
			}
			stats.scanned++
			progress.Increment()

			pf := sc.Files.Primary()
			if pf == nil {
				stats.noPrimaryFile++
				continue
			}
			path := pf.Base().Path

			if len(scanDirs) > 0 && !fsutil.IsPathInDirs(scanDirs, path) {
				stats.outsidePaths++
				continue
			}

			if sc.Date != nil && !j.Options.Override {
				stats.dateAlreadySet++
				continue
			}

			basename := filepath.Base(path)
			stem := strings.TrimSuffix(basename, filepath.Ext(basename))

			date, format, ok := extractSceneDateFromFilename(stem, matchers)
			if !ok {
				stats.noMatch++
				logger.Debugf("%s scene %d: no date found in %q", sceneDateFromFilenameLogPrefix, sc.ID, basename)
				continue
			}

			// skip no-op overrides so logs only list real changes
			if sc.Date != nil && sc.Date.String() == date.String() {
				stats.dateAlreadySet++
				continue
			}

			oldDate := "empty"
			if sc.Date != nil {
				oldDate = sc.Date.String()
			}
			logger.Infof("%s scene %d (%s): %s date %s -> %s (format %s)",
				sceneDateFromFilenameLogPrefix, sc.ID, basename, settingVerb(j.Options.DryMode), oldDate, date.String(), format)

			if j.Options.DryMode {
				stats.updated++
				continue
			}

			scenePartial := models.NewScenePartial()
			scenePartial.Date = models.NewOptionalDate(date)
			if err := j.Repository.WithTxn(ctx, func(ctx context.Context) error {
				_, err := j.Repository.Scene.UpdatePartial(ctx, sc.ID, scenePartial)
				return err
			}); err != nil {
				stats.failed++
				logger.Errorf("%s scene %d (%s): updating date failed: %v", sceneDateFromFilenameLogPrefix, sc.ID, basename, err)
				continue
			}
			stats.updated++
		}
	}

	updatedLabel := "updated"
	if j.Options.DryMode {
		updatedLabel = "would update"
	}
	logger.Infof("%s finished: scanned=%d %s=%d already_set=%d no_match=%d no_primary_file=%d outside_paths=%d failed=%d",
		sceneDateFromFilenameLogPrefix, stats.scanned, updatedLabel, stats.updated,
		stats.dateAlreadySet, stats.noMatch, stats.noPrimaryFile, stats.outsidePaths, stats.failed)
	return nil
}

func settingVerb(dry bool) string {
	if dry {
		return "would set"
	}
	return "setting"
}

func (j *SetSceneDatesFromFilenameJob) buildMatchers() ([]sceneFilenameDateMatcher, error) {
	formats := j.Options.Formats
	if len(formats) == 0 {
		formats = AllSceneDateFilenameFormats
	}
	matchers := make([]sceneFilenameDateMatcher, 0, len(formats))
	seen := make(map[SceneDateFilenameFormat]bool, len(formats))
	for _, f := range formats {
		if seen[f] {
			continue
		}
		seen[f] = true
		m, err := sceneFilenameDateMatcherFor(f)
		if err != nil {
			return nil, err
		}
		matchers = append(matchers, m)
	}
	return matchers, nil
}

// resolveScanDirs validates the configured paths against the stash libraries and
// returns the cleaned directory list. Empty input means all libraries (no filter).
func (j *SetSceneDatesFromFilenameJob) resolveScanDirs() ([]string, error) {
	if len(j.Options.Paths) == 0 {
		return nil, nil
	}
	stashPaths := config.GetInstance().GetStashPaths()
	var dirs []string
	for _, p := range j.Options.Paths {
		clean := filepath.Clean(strings.TrimSpace(p))
		if clean == "" || clean == "." {
			continue
		}
		if stashPaths.GetStashFromDirPath(clean) == nil {
			return nil, fmt.Errorf("path %q is not within any configured library path", p)
		}
		dirs = append(dirs, clean)
	}
	return dirs, nil
}

// extractSceneDateFromFilename tries each matcher in order on the file basename stem
// and returns the first valid date.
func extractSceneDateFromFilename(stem string, matchers []sceneFilenameDateMatcher) (models.Date, SceneDateFilenameFormat, bool) {
	for _, m := range matchers {
		sm := m.re.FindStringSubmatch(stem)
		if sm == nil {
			continue
		}
		date, ok := m.parse(sm)
		if !ok {
			continue
		}
		return date, m.format, true
	}
	return models.Date{}, "", false
}
