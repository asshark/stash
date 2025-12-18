package api

import (
	"context"

	"github.com/stashapp/stash/pkg/downloadchecker"
)

func (r *downloadMatchingSceneResolver) Duration(ctx context.Context, obj *downloadchecker.DownloadMatchingScene) (*float64, error) {
	if obj.Duration == 0 {
		return nil, nil
	}
	return &obj.Duration, nil
}

