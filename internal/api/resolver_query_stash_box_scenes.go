package api

import (
	"context"

	stashboxgraphql "github.com/stashapp/stash/pkg/stashbox/graphql"
)

func (r *queryResolver) StashBoxStudioScenes(ctx context.Context, input StashBoxStudioScenesInput) (*StashBoxStudioScenesResult, error) {
	box, err := resolveStashBox(input.StashBoxIndex, input.StashBoxEndpoint)
	if err != nil {
		return nil, err
	}

	client := r.newStashBoxClient(*box)
	scenes, err := client.QueryScenesByStudioID(ctx, input.StudioID)
	if err != nil {
		return nil, err
	}

	result := &StashBoxStudioScenesResult{
		Count:  0,
		Scenes: make([]*StashBoxStudioScene, 0, len(scenes)),
	}

	for _, scene := range scenes {
		if scene == nil {
			continue
		}

		urls := make([]string, 0, len(scene.Urls))
		for _, u := range scene.Urls {
			if u == nil {
				continue
			}
			urls = append(urls, u.URL)
		}

		performers := make([]string, 0, len(scene.Performers))
		for _, performer := range scene.Performers {
			if performer == nil || performer.Performer == nil {
				continue
			}
			if performer.Performer.Gender == nil ||
				*performer.Performer.Gender != stashboxgraphql.GenderEnumFemale {
				continue
			}
			name := performer.Performer.Name
			if performer.As != nil && *performer.As != "" {
				name = name + " (as " + *performer.As + ")"
			}
			performers = append(performers, name)
		}

		result.Scenes = append(result.Scenes, &StashBoxStudioScene{
			ID:         scene.ID,
			Title:      scene.Title,
			Date:       scene.Date,
			Urls:       urls,
			Performers: performers,
		})
	}

	result.Count = len(result.Scenes)
	return result, nil
}

func (r *queryResolver) StashBoxPerformerScenes(ctx context.Context, input StashBoxPerformerScenesInput) (*StashBoxPerformerScenesResult, error) {
	box, err := resolveStashBox(input.StashBoxIndex, input.StashBoxEndpoint)
	if err != nil {
		return nil, err
	}

	client := r.newStashBoxClient(*box)
	scenes, err := client.QueryScenesByPerformerID(ctx, input.PerformerID)
	if err != nil {
		return nil, err
	}

	result := &StashBoxPerformerScenesResult{
		Count:  0,
		Scenes: make([]*StashBoxPerformerScene, 0, len(scenes)),
	}

	for _, scene := range scenes {
		if scene == nil {
			continue
		}

		urls := make([]string, 0, len(scene.Urls))
		for _, u := range scene.Urls {
			if u == nil {
				continue
			}
			urls = append(urls, u.URL)
		}

		performers := make([]string, 0, len(scene.Performers))
		for _, performer := range scene.Performers {
			if performer == nil || performer.Performer == nil {
				continue
			}
			if performer.Performer.Gender == nil ||
				*performer.Performer.Gender != stashboxgraphql.GenderEnumFemale {
				continue
			}
			name := performer.Performer.Name
			if performer.As != nil && *performer.As != "" {
				name = name + " (as " + *performer.As + ")"
			}
			performers = append(performers, name)
		}

		result.Scenes = append(result.Scenes, &StashBoxPerformerScene{
			ID:         scene.ID,
			Title:      scene.Title,
			Date:       scene.Date,
			Urls:       urls,
			Performers: performers,
		})
	}

	result.Count = len(result.Scenes)
	return result, nil
}
