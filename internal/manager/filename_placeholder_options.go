package manager

// FilenamePlaceholderOptions configures how template fields .Performers and .StudioPath are built.
// Set via GraphQL input `filenamePlaceholders`; nil or nil sub-fields mean defaults.
type FilenamePlaceholderOptions struct {
	Performers *PerformersPlaceholderOpts
	StudioPath *StudioPathPlaceholderOpts
}

// PerformersPlaceholderOpts controls the .Performers / .FemalePerformers template values.
type PerformersPlaceholderOpts struct {
	// GenderFilter: FEMALE (default), MALE, ANY — same semantics as GraphQL enum.
	GenderFilter string
	Separator    string // default ", "
	SortBy       string // NAME (default) or RATING100
}

// StudioPathPlaceholderOpts controls the .StudioPath template value.
type StudioPathPlaceholderOpts struct {
	StudioJoiner    string // default "_"
	StripWhitespace bool
}

func (o *OrganizeScenesByStudioOptions) effectivePerformersPlaceholderOpts() PerformersPlaceholderOpts {
	var p PerformersPlaceholderOpts
	if o.FilenamePlaceholders != nil && o.FilenamePlaceholders.Performers != nil {
		fp := o.FilenamePlaceholders.Performers
		p.GenderFilter = fp.GenderFilter
		p.Separator = fp.Separator
		p.SortBy = fp.SortBy
	}
	if p.GenderFilter == "" {
		p.GenderFilter = "FEMALE"
	}
	if p.Separator == "" {
		p.Separator = ", "
	}
	if p.SortBy == "" {
		p.SortBy = "NAME"
	}
	return p
}

func (o *OrganizeScenesByStudioOptions) effectiveStudioPathPlaceholderOpts() StudioPathPlaceholderOpts {
	var s StudioPathPlaceholderOpts
	if o.FilenamePlaceholders != nil && o.FilenamePlaceholders.StudioPath != nil {
		sp := o.FilenamePlaceholders.StudioPath
		s.StudioJoiner = sp.StudioJoiner
		s.StripWhitespace = sp.StripWhitespace
	}
	if s.StudioJoiner == "" {
		s.StudioJoiner = "_"
	}
	return s
}
