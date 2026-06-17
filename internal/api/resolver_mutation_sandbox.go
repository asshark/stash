package api

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	"github.com/stashapp/stash/internal/manager"
	"github.com/stashapp/stash/pkg/logger"
)

func (r *mutationResolver) SandboxOrganizeScenesByStudio(ctx context.Context, input OrganizeScenesByStudioInput) (string, error) {
	opts, err := organizeScenesByStudioOptionsFromInput(input)
	if err != nil {
		return "", err
	}

	mgr := manager.GetInstance()
	job := &manager.OrganizeScenesByStudioJob{
		Options:    opts,
		Repository: mgr.Repository,
	}
	id := mgr.JobManager.Add(ctx, "[Sandbox] Organize scenes by studio", job)
	logger.Infof("sandbox organize scenes by studio: queued job %d", id)
	return strconv.Itoa(id), nil
}

func (r *mutationResolver) SandboxSetSceneDatesFromFilename(ctx context.Context, input SetSceneDatesFromFilenameInput) (string, error) {
	var opts manager.SetSceneDatesFromFilenameOptions

	for _, p := range input.Paths {
		if s := strings.TrimSpace(p); s != "" {
			opts.Paths = append(opts.Paths, s)
		}
	}
	for _, f := range input.Formats {
		if !f.IsValid() {
			return "", fmt.Errorf("invalid filename date format %q", f)
		}
		opts.Formats = append(opts.Formats, manager.SceneDateFilenameFormat(f))
	}
	if input.Override != nil {
		opts.Override = *input.Override
	}
	if input.DryMode != nil {
		opts.DryMode = *input.DryMode
	}

	mgr := manager.GetInstance()
	job := &manager.SetSceneDatesFromFilenameJob{
		Options:    opts,
		Repository: mgr.Repository,
	}
	id := mgr.JobManager.Add(ctx, "[Sandbox] Set scene dates from filename", job)
	logger.Infof("sandbox set scene dates from filename: queued job %d", id)
	return strconv.Itoa(id), nil
}

func organizeScenesByStudioOptionsFromInput(input OrganizeScenesByStudioInput) (manager.OrganizeScenesByStudioOptions, error) {
	var out manager.OrganizeScenesByStudioOptions
	if len(input.StudioDirectories) == 0 {
		return out, fmt.Errorf("studioDirectories must not be empty")
	}
	out.StudioDirectoryByName = make(map[string]manager.StudioDirectoryMapEntry, len(input.StudioDirectories))
	for _, e := range input.StudioDirectories {
		name := strings.TrimSpace(e.StudioName)
		dir := strings.TrimSpace(e.DirectoryPath)
		if name == "" || dir == "" {
			return out, fmt.Errorf("studioDirectories entries must have non-empty studioName and directoryPath")
		}
		if _, dup := out.StudioDirectoryByName[name]; dup {
			return out, fmt.Errorf("duplicate studioName %q in studioDirectories", name)
		}
		var excluded []string
		for _, x := range e.ExcludedChildStudios {
			if s := strings.TrimSpace(x); s != "" {
				excluded = append(excluded, s)
			}
		}
		var included []string
		for _, x := range e.IncludedChildStudios {
			if s := strings.TrimSpace(x); s != "" {
				included = append(included, s)
			}
		}
		out.StudioDirectoryByName[name] = manager.StudioDirectoryMapEntry{
			Directory:                dir,
			ExcludedChildStudioNames: excluded,
			IncludedChildStudioNames: included,
		}
	}
	if input.DryMode != nil && *input.DryMode {
		out.DryMode = true
	}
	if input.DryRunLogPath != nil {
		out.DryRunLogPath = strings.TrimSpace(*input.DryRunLogPath)
	}
	if input.FileCountLimit != nil {
		v := *input.FileCountLimit
		if v < 0 {
			return out, fmt.Errorf("fileCountLimit must be >= 0")
		}
		cp := v
		out.FileCountLimit = &cp
	}
	if input.GroupByYear != nil && *input.GroupByYear {
		out.GroupByYear = true
	}
	if input.ReFormatFileName != nil && *input.ReFormatFileName {
		out.ReFormatFileName = true
	}
	if input.FileNameFormat != nil {
		out.FileNameFormat = strings.TrimSpace(*input.FileNameFormat)
	}
	if input.FilenamePlaceholders != nil {
		out.FilenamePlaceholders = &manager.FilenamePlaceholderOptions{}
		if p := input.FilenamePlaceholders.Performers; p != nil {
			out.FilenamePlaceholders.Performers = &manager.PerformersPlaceholderOpts{}
			if p.GenderFilter != nil {
				out.FilenamePlaceholders.Performers.GenderFilter = string(*p.GenderFilter)
			}
			if p.Separator != nil {
				out.FilenamePlaceholders.Performers.Separator = *p.Separator
			}
			if p.SortBy != nil {
				out.FilenamePlaceholders.Performers.SortBy = string(*p.SortBy)
			}
		}
		if sp := input.FilenamePlaceholders.StudioPath; sp != nil {
			out.FilenamePlaceholders.StudioPath = &manager.StudioPathPlaceholderOpts{}
			if sp.StudioJoiner != nil {
				out.FilenamePlaceholders.StudioPath.StudioJoiner = *sp.StudioJoiner
			}
			if sp.StripWhitespaceFromStudioNames != nil {
				out.FilenamePlaceholders.StudioPath.StripWhitespace = *sp.StripWhitespaceFromStudioNames
			}
		}
	}
	return out, nil
}
