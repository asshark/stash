package models

import "context"

type ClipFilterType struct {
	OperatorFilter[ClipFilterType]
	ID       *IntCriterionInput    `json:"id"`
	Title    *StringCriterionInput `json:"title"`
	Code     *StringCriterionInput `json:"code"`
	Details  *StringCriterionInput `json:"details"`
	// Filter by file checksum
	Checksum *StringCriterionInput `json:"checksum"`
	// Filter by path
	Path *StringCriterionInput `json:"path"`
	// Filter by file count
	FileCount *IntCriterionInput `json:"file_count"`
	// Filter by rating expressed as 1-100
	Rating100 *IntCriterionInput `json:"rating100"`
	// Filter by organized
	Organized *bool `json:"organized"`
	// Filter by o-counter
	OCounter *IntCriterionInput `json:"o_counter"`
	// Filter by resolution
	Resolution *ResolutionCriterionInput `json:"resolution"`
	// Filter by orientation
	Orientation *OrientationCriterionInput `json:"orientation"`
	// Filter by framerate
	Framerate *IntCriterionInput `json:"framerate"`
	// Filter by bitrate
	Bitrate *IntCriterionInput `json:"bitrate"`
	// Filter by video codec
	VideoCodec *StringCriterionInput `json:"video_codec"`
	// Filter by audio codec
	AudioCodec *StringCriterionInput `json:"audio_codec"`
	// Filter by duration (in seconds)
	Duration *IntCriterionInput `json:"duration"`
	// Filter to only include clips which have markers. `true` or `false`
	HasMarkers *string `json:"has_markers"`
	// Filter to only include clips missing this property
	IsMissing *string `json:"is_missing"`
	// Filter to only include clips with this studio
	Studios *HierarchicalMultiCriterionInput `json:"studios"`
	// Filter to only include clips with these tags
	Tags *HierarchicalMultiCriterionInput `json:"tags"`
	// Filter by tag count
	TagCount *IntCriterionInput `json:"tag_count"`
	// Filter to only include clips with performers with these tags
	PerformerTags *HierarchicalMultiCriterionInput `json:"performer_tags"`
	// Filter to only include clips with these performers
	Performers *MultiCriterionInput `json:"performers"`
	// Filter by performer count
	PerformerCount *IntCriterionInput `json:"performer_count"`
	// Filter clips that have performers that have been favorited
	PerformerFavorite *bool `json:"performer_favorite"`
	// Filter clips by performer age at time of clip
	PerformerAge *IntCriterionInput `json:"performer_age"`
	// Filter by date
	Date *DateCriterionInput `json:"date"`
	// Filter by url
	URL *StringCriterionInput `json:"url"`
	// Filter by galleries
	Galleries *MultiCriterionInput `json:"galleries"`
	// Filter by movie
	Movies *MultiCriterionInput `json:"movies"`
	// Filter by movie count
	MovieCount *IntCriterionInput `json:"movie_count"`
	// Filter by file size
	FileSize *IntCriterionInput `json:"file_size"`
	// Filter by filename
	Filename *StringCriterionInput `json:"filename"`
	// Filter by parent folder
	ParentFolder *HierarchicalMultiCriterionInput `json:"parent_folder"`
}

// ClipCopyOptions represents the configuration for copying clips
type ClipCopyOptions struct {
	// Source folders to search for clips
	SourceFolders []string `json:"source_folders"`
	// Destination folder for copied clips
	DestinationFolder string `json:"destination_folder"`
	// Filter criteria for selecting clips to copy
	Filter *ClipFilterType `json:"filter"`
	// Whether to create subdirectories in destination based on source structure
	PreserveStructure bool `json:"preserve_structure"`
	// Whether to overwrite existing files in destination
	Overwrite bool `json:"overwrite"`
	// Whether this is a dry run (no actual copying)
	DryRun bool `json:"dry_run"`
}

// Clip represents a clip entity
type Clip struct {
	ID        int    `db:"id" json:"id"`
	Title     string `db:"title" json:"title"`
	Code      string `db:"code" json:"code"`
	Details   string `db:"details" json:"details"`
	URL       string `db:"url" json:"url"`
	Date      string `db:"date" json:"date"`
	Rating    int    `db:"rating" json:"rating"`
	Organized bool   `db:"organized" json:"organized"`
	OCounter  int    `db:"o_counter" json:"o_counter"`
	CreatedAt string `db:"created_at" json:"created_at"`
	UpdatedAt string `db:"updated_at" json:"updated_at"`
}

// ClipRepository defines the interface for clip data access
type ClipRepository interface {
	Find(ctx context.Context, id int) (*Clip, error)
	FindMany(ctx context.Context, ids []int) ([]*Clip, error)
	FindByPath(ctx context.Context, path string) (*Clip, error)
	Query(ctx context.Context, clipFilter *ClipFilterType, findFilter *FindFilterType) ([]*Clip, int, error)
	Count(ctx context.Context) (int, error)
	CountByFilter(ctx context.Context, clipFilter *ClipFilterType) (int, error)
}




