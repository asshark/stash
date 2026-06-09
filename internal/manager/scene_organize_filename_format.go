package manager

import (
	"bytes"
	"context"
	"fmt"
	"sort"
	"strings"
	"text/template"
	"unicode"
	"unicode/utf8"

	"github.com/stashapp/stash/pkg/models"
)

// DefaultOrganizeSceneFileNameFormat is the default Go text/template for the primary video
// basename **without extension** (the original extension is always appended by the caller).
//
// Template fields (see also filenamePlaceholders in GraphQL):
//   - Performers: performer names (gender / separator / sort from options)
//   - FemalePerformers: same string as Performers (legacy alias)
//   - Title, StudioPath, Date
//
// Example:
//
//	Blanche Bradburry, Vinna Reed - Nylon-clad Pleasure [21FootArt_21Sextury(Network)] (2013-04-06).wmv
const DefaultOrganizeSceneFileNameFormat = `{{.Performers}} - {{.Title}} [{{.StudioPath}}]{{if .Date}} ({{.Date}}){{end}}`

const organizeSceneBasenameMaxRunes = 200

// organizeSceneFilenameData is passed to text/template for the basename stem.
type organizeSceneFilenameData struct {
	Performers       string
	FemalePerformers string // legacy alias; always identical to Performers when set
	Title            string
	StudioPath       string
	Date             string
}

func isFemalePerformerGender(g *models.GenderEnum) bool {
	if g == nil {
		return false
	}
	switch *g {
	case models.GenderEnumFemale, models.GenderEnumTransgenderFemale:
		return true
	default:
		return false
	}
}

func isMalePerformerGender(g *models.GenderEnum) bool {
	if g == nil {
		return false
	}
	switch *g {
	case models.GenderEnumMale, models.GenderEnumTransgenderMale:
		return true
	default:
		return false
	}
}

func performerMatchesGenderFilter(g *models.GenderEnum, filter string) bool {
	switch strings.ToUpper(strings.TrimSpace(filter)) {
	case "ANY":
		return true
	case "MALE":
		return isMalePerformerGender(g)
	case "FEMALE", "":
		return isFemalePerformerGender(g)
	default:
		return isFemalePerformerGender(g)
	}
}

type performerPick struct {
	name   string
	rating int
}

func (j *OrganizeScenesByStudioJob) performersForPlaceholder(ctx context.Context, s *models.Scene) ([]string, error) {
	pOpts := j.Options.effectivePerformersPlaceholderOpts()
	if err := s.LoadPerformerIDs(ctx, j.Repository.Scene); err != nil {
		return nil, err
	}
	ids := s.PerformerIDs.List()
	if len(ids) == 0 {
		return nil, nil
	}
	var rows []performerPick
	for _, id := range ids {
		p, err := j.Repository.Performer.Find(ctx, id)
		if err != nil {
			return nil, err
		}
		if p == nil {
			continue
		}
		if !performerMatchesGenderFilter(p.Gender, pOpts.GenderFilter) {
			continue
		}
		n := strings.TrimSpace(p.Name)
		if n == "" {
			continue
		}
		rk := -1
		if p.Rating != nil {
			rk = *p.Rating
		}
		rows = append(rows, performerPick{name: n, rating: rk})
	}

	switch strings.ToUpper(strings.TrimSpace(pOpts.SortBy)) {
	case "RATING100", "RATING":
		sort.SliceStable(rows, func(i, j int) bool {
			if rows[i].rating != rows[j].rating {
				return rows[i].rating > rows[j].rating
			}
			return strings.ToLower(rows[i].name) < strings.ToLower(rows[j].name)
		})
	default: // NAME
		sort.SliceStable(rows, func(i, j int) bool {
			return strings.ToLower(rows[i].name) < strings.ToLower(rows[j].name)
		})
	}

	out := make([]string, len(rows))
	for i := range rows {
		out[i] = rows[i].name
	}
	return out, nil
}

func stripAllUnicodeWhitespace(s string) string {
	var b strings.Builder
	for _, r := range s {
		if !unicode.IsSpace(r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func (j *OrganizeScenesByStudioJob) studioPathForPlaceholder(ctx context.Context, s *models.Scene, cache map[int]*models.Studio) (string, error) {
	sOpts := j.Options.effectiveStudioPathPlaceholderOpts()
	if s.StudioID == nil {
		return "", nil
	}
	chain, err := j.studioChainLeafToRootInTxn(ctx, *s.StudioID, cache)
	if err != nil {
		return "", err
	}
	var parts []string
	for _, st := range chain {
		n := strings.TrimSpace(st.Name)
		if sOpts.StripWhitespace {
			n = stripAllUnicodeWhitespace(n)
		}
		parts = append(parts, n)
	}
	return strings.Join(parts, sOpts.StudioJoiner), nil
}

func sceneDateString(s *models.Scene) string {
	if s.Date == nil {
		return ""
	}
	return s.Date.String()
}

func (j *OrganizeScenesByStudioJob) renderOrganizeBasenameStemInTxn(
	ctx context.Context,
	s *models.Scene,
	studioCache map[int]*models.Studio,
	tpl *template.Template,
) (stem string, ok bool, err error) {
	pOpts := j.Options.effectivePerformersPlaceholderOpts()

	names, err := j.performersForPlaceholder(ctx, s)
	if err != nil {
		return "", false, err
	}
	if len(names) == 0 {
		return "", false, nil
	}
	title := strings.TrimSpace(s.Title)
	if title == "" {
		return "", false, nil
	}
	studioPath, err := j.studioPathForPlaceholder(ctx, s, studioCache)
	if err != nil {
		return "", false, err
	}
	if strings.TrimSpace(studioPath) == "" {
		return "", false, nil
	}
	dateStr := sceneDateString(s)

	titleSafe := sanitizeWindowsPathSegment(title)
	studioPathSafe := sanitizeWindowsPathSegment(studioPath)

	for n := len(names); n > 0; n-- {
		perfJoined := strings.Join(names[:n], pOpts.Separator)
		if n < len(names) {
			perfJoined += "..."
		}
		perfSafe := sanitizeWindowsPathSegment(perfJoined)

		data := organizeSceneFilenameData{
			Performers:       perfSafe,
			FemalePerformers: perfSafe,
			Title:            titleSafe,
			StudioPath:       studioPathSafe,
			Date:             dateStr,
		}
		var buf bytes.Buffer
		if err := tpl.Execute(&buf, &data); err != nil {
			return "", false, fmt.Errorf("executing file name template: %w", err)
		}
		raw := strings.TrimSpace(buf.String())
		cand := sanitizeInvalidWindowsFilenameChars(raw)
		if cand == "" {
			continue
		}
		if utf8.RuneCountInString(cand) <= organizeSceneBasenameMaxRunes {
			return cand, true, nil
		}
	}
	var buf bytes.Buffer
	perfSafe := sanitizeWindowsPathSegment(names[0])
	if len(names) > 1 {
		perfSafe = sanitizeWindowsPathSegment(names[0] + "...")
	}
	data := organizeSceneFilenameData{
		Performers:       perfSafe,
		FemalePerformers: perfSafe,
		Title:            titleSafe,
		StudioPath:       studioPathSafe,
		Date:             dateStr,
	}
	if err := tpl.Execute(&buf, &data); err != nil {
		return "", false, fmt.Errorf("executing file name template: %w", err)
	}
	cand := sanitizeInvalidWindowsFilenameChars(strings.TrimSpace(buf.String()))
	if cand == "" {
		return "", false, nil
	}
	return truncateStringRunes(cand, organizeSceneBasenameMaxRunes), true, nil
}

func sanitizeWindowsPathSegment(s string) string {
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
	s = strings.TrimRight(s, " .")
	return strings.TrimSpace(s)
}

func sanitizeInvalidWindowsFilenameChars(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch r {
		case '<', '>', ':', '"', '/', '\\', '|', '?', '*':
			b.WriteRune('_')
		case 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31:
			continue
		default:
			b.WriteRune(r)
		}
	}
	out := strings.TrimRight(b.String(), " .")
	return strings.TrimSpace(out)
}

func truncateStringRunes(s string, maxRunes int) string {
	if maxRunes <= 0 {
		return ""
	}
	var b strings.Builder
	n := 0
	for _, r := range s {
		if n >= maxRunes {
			break
		}
		b.WriteRune(r)
		n++
	}
	return strings.TrimRight(b.String(), " .")
}

func parseOrganizeSceneFilenameTemplate(format string) (*template.Template, error) {
	return template.New("organizeSceneFilename").Option("missingkey=error").Parse(format)
}
