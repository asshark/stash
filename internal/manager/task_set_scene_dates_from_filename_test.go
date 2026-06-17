package manager

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestExtractSceneDateFromFilename(t *testing.T) {
	allMatchers := func() []sceneFilenameDateMatcher {
		j := &SetSceneDatesFromFilenameJob{}
		m, err := j.buildMatchers()
		if err != nil {
			t.Fatalf("buildMatchers: %v", err)
		}
		return m
	}()

	tests := []struct {
		name       string
		stem       string
		wantDate   string
		wantFormat SceneDateFilenameFormat
		wantOk     bool
	}{
		{"ymd dash", "Studio - Title 2021-05-12 1080p", "2021-05-12", SceneDateFormatYMDDash, true},
		{"dmy dash", "Title 12-05-2021", "2021-05-12", SceneDateFormatDMYDash, true},
		{"ymd dot", "Studio.2021.05.12.Title", "2021-05-12", SceneDateFormatYMDDot, true},
		{"dmy dot", "Title 31.12.1999", "1999-12-31", SceneDateFormatDMYDot, true},
		{"year parens", "Some Movie (2021)", "2021", SceneDateFormatYearParen, true},
		{"year parens with suffix", "Some Movie (2021_remastered final)", "2021", SceneDateFormatYearParen, true},
		{"year parens with technical suffix", "Jennifer - Hide Nylons [HideNylons_PantyhoseSecret] (2012_HD_422_94 MB)", "2012", SceneDateFormatYearParen, true},
		{"invalid month", "Title 2021-13-12", "", "", false},
		{"invalid day feb 30", "Title 2021-02-30", "", "", false},
		{"resolution not a year", "Title (1080p)", "", "", false},
		{"no date", "Just a title", "", "", false},
		{"year not in parens ignored", "Title 2021", "", "", false},
		{"5 digit number not a date", "Title 20211-05-12x", "", "", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			date, format, ok := extractSceneDateFromFilename(tt.stem, allMatchers)
			if ok != tt.wantOk {
				t.Fatalf("ok = %v, want %v", ok, tt.wantOk)
			}
			if !ok {
				return
			}
			if date.String() != tt.wantDate {
				t.Errorf("date = %q, want %q", date.String(), tt.wantDate)
			}
			if format != tt.wantFormat {
				t.Errorf("format = %q, want %q", format, tt.wantFormat)
			}
		})
	}
}

func TestExtractSceneDateFromFilenameFormatOrder(t *testing.T) {
	// ambiguous "12-05-2021" style: with DMY listed first, day/month order follows DMY
	j := &SetSceneDatesFromFilenameJob{
		Options: SetSceneDatesFromFilenameOptions{
			Formats: []SceneDateFilenameFormat{SceneDateFormatDMYDash},
		},
	}
	matchers, err := j.buildMatchers()
	if err != nil {
		t.Fatalf("buildMatchers: %v", err)
	}
	date, _, ok := extractSceneDateFromFilename("Title 01-02-2021", matchers)
	if !ok {
		t.Fatal("expected match")
	}
	if date.String() != "2021-02-01" {
		t.Errorf("date = %q, want 2021-02-01", date.String())
	}

	// unknown format errors out
	j = &SetSceneDatesFromFilenameJob{
		Options: SetSceneDatesFromFilenameOptions{
			Formats: []SceneDateFilenameFormat{"BOGUS"},
		},
	}
	if _, err := j.buildMatchers(); err == nil {
		t.Error("expected error for unknown format")
	}
}

func TestExtractSceneDateFromCommaAviFilename(t *testing.T) {
	// Some files use ",avi" instead of ".avi" — Ext() does not strip it; stem still contains the year.
	basename := "Jennifer - Hide Nylons [HideNylons_PantyhoseSecret] (2012_HD_422_94 MB),avi"
	stem := strings.TrimSuffix(basename, filepath.Ext(basename))

	j := &SetSceneDatesFromFilenameJob{}
	matchers, err := j.buildMatchers()
	if err != nil {
		t.Fatalf("buildMatchers: %v", err)
	}
	date, format, ok := extractSceneDateFromFilename(stem, matchers)
	if !ok {
		t.Fatalf("expected match for stem %q", stem)
	}
	if date.String() != "2012" {
		t.Errorf("date = %q, want 2012", date.String())
	}
	if format != SceneDateFormatYearParen {
		t.Errorf("format = %q, want %s", format, SceneDateFormatYearParen)
	}
}
