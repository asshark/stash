import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gql, useLazyQuery } from "@apollo/client";
import { Button, ButtonGroup, Form } from "react-bootstrap";
import { FormattedMessage, useIntl } from "react-intl";
import { Link } from "react-router-dom";
import * as GQL from "src/core/generated-graphql";
import { useFindPerformer, useConfiguration } from "src/core/StashService";
import { PerformerSelect, Performer as SelectPerformer } from "src/components/Performers/PerformerSelect";
import { ErrorMessage } from "src/components/Shared/ErrorMessage";
import { LoadingIndicator } from "src/components/Shared/LoadingIndicator";
import { RemoteSceneCardGrid } from "src/components/Shared/RemoteSceneCardGrid";
import { RemoteScene } from "src/components/Shared/RemoteSceneCard";
import { getStashboxBase, stashboxDisplayName } from "src/utils/stashbox";

type PerformerScenesResult = {
  stashBoxPerformerScenes: {
    count: number;
    scenes: RemoteScene[];
  };
};

type PerformerScenesVars = {
  input: {
    stash_box_endpoint?: string | null;
    stash_box_index?: number | null;
    performer_id: string;
  };
};

const STASHBOX_PERFORMER_SCENES = gql`
  query StashBoxPerformerScenes($input: StashBoxPerformerScenesInput!) {
    stashBoxPerformerScenes(input: $input) {
      count
      scenes {
        id
        title
        date
        urls
        performers
        studio
        parent_studio
        image_url
      }
    }
  }
`;

type SortMode = "date" | "title" | "studio";

interface IProps {
  preselectedPerformerId?: string;
  onMissingCountChange?: (count: number) => void;
}

export const ActorMissingScenes: React.FC<IProps> = ({
  preselectedPerformerId,
  onMissingCountChange,
}) => {
  const intl = useIntl();
  const config = useConfiguration();

  const [selectedPerformer, setSelectedPerformer] = useState<SelectPerformer | null>(null);
  const [selectedStashID, setSelectedStashID] = useState<GQL.StashId | null>(null);
  const [searchFilter, setSearchFilter] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("date");

  const { data: performerData } = useFindPerformer(selectedPerformer?.id ?? "");
  const stashIDs = performerData?.findPerformer?.stash_ids ?? [];

  const { data: preselectedData } = useFindPerformer(preselectedPerformerId ?? "");
  useEffect(() => {
    const p = preselectedData?.findPerformer;
    if (preselectedPerformerId && p && !selectedPerformer) {
      setSelectedPerformer({
        id: p.id,
        name: p.name,
        alias_list: p.alias_list,
        disambiguation: p.disambiguation,
        image_path: p.image_path,
        birthdate: p.birthdate,
        death_date: p.death_date,
      });
    }
  }, [preselectedPerformerId, preselectedData, selectedPerformer]);

  useEffect(() => {
    if (!stashIDs.length) {
      setSelectedStashID(null);
      return;
    }
    if (
      !selectedStashID ||
      !stashIDs.some(
        (s) => s.stash_id === selectedStashID.stash_id && s.endpoint === selectedStashID.endpoint
      )
    ) {
      setSelectedStashID(stashIDs[0]);
    }
  }, [stashIDs, selectedStashID]);

  const [fetchLocalScenes, localScenesState] = useLazyQuery<
    {
      findScenes: {
        scenes: Array<{
          id: string;
          urls: string[];
          stash_ids: Array<{ endpoint: string; stash_id: string }>;
        }>;
      };
    },
    { filter: GQL.FindFilterType; scene_filter: GQL.SceneFilterType }
  >(gql`
    query ActorMissingScenesLocal($filter: FindFilterType, $scene_filter: SceneFilterType) {
      findScenes(filter: $filter, scene_filter: $scene_filter) {
        scenes {
          id
          urls
          stash_ids {
            endpoint
            stash_id
          }
        }
      }
    }
  `);

  const [fetchRemoteScenes, remoteScenesState] = useLazyQuery<
    PerformerScenesResult,
    PerformerScenesVars
  >(STASHBOX_PERFORMER_SCENES, { fetchPolicy: "network-only" });

  const [localCount, setLocalCount] = useState(0);
  const [remoteCount, setRemoteCount] = useState(0);
  const [missingScenes, setMissingScenes] = useState<RemoteScene[]>([]);
  const [error, setError] = useState<string | null>(null);

  const stashBoxes = config.data?.configuration?.general?.stashBoxes ?? [];

  const stashBoxLabel = useCallback(
    (endpoint: string) => {
      const index = stashBoxes.findIndex((box) => box.endpoint === endpoint);
      if (index === -1) return endpoint;
      return stashboxDisplayName(stashBoxes[index].name, index);
    },
    [stashBoxes]
  );

  const onSelectPerformer = (items: SelectPerformer[]) => {
    setSelectedPerformer(items[0] ?? null);
    setLocalCount(0);
    setRemoteCount(0);
    setMissingScenes([]);
  };

  const generateReport = useCallback(async () => {
    if (!selectedPerformer || !selectedStashID) return;

    setError(null);
    setMissingScenes([]);
    setLocalCount(0);
    setRemoteCount(0);

    try {
      const [localResult, remoteResult] = await Promise.all([
        fetchLocalScenes({
          variables: {
            filter: { per_page: -1 },
            scene_filter: {
              performers: {
                modifier: GQL.CriterionModifier.Includes,
                value: [selectedPerformer.id],
              },
            },
          },
        }),
        fetchRemoteScenes({
          variables: {
            input: {
              stash_box_endpoint: selectedStashID.endpoint,
              performer_id: selectedStashID.stash_id,
            },
          },
        }),
      ]);

      if (localResult.errors?.length) throw new Error(localResult.errors[0].message);
      if (remoteResult.errors?.length) throw new Error(remoteResult.errors[0].message);

      const localScenes = localResult.data?.findScenes.scenes ?? [];
      const remoteScenes = remoteResult.data?.stashBoxPerformerScenes.scenes ?? [];

      const localStashIDs = new Set(
        localScenes.flatMap((scene) =>
          scene.stash_ids
            .filter((id) => id.endpoint === selectedStashID.endpoint)
            .map((id) => id.stash_id)
        )
      );
      const localURLs = new Set(
        localScenes
          .flatMap((scene) => scene.urls ?? [])
          .map((url) => url.trim())
          .filter((url) => url.length > 0)
      );

      const missing = remoteScenes.filter((scene) => {
        if (localStashIDs.has(scene.id)) return false;
        const remoteUrls = (scene.urls ?? []).map((url) => url.trim()).filter((url) => url.length > 0);
        return !remoteUrls.some((url) => localURLs.has(url));
      });

      setLocalCount(localScenes.length);
      setRemoteCount(remoteScenes.length);
      setMissingScenes(missing);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchLocalScenes, fetchRemoteScenes, selectedPerformer, selectedStashID]);

  useEffect(() => {
    if (
      preselectedPerformerId &&
      selectedPerformer &&
      selectedStashID &&
      localCount === 0 &&
      remoteCount === 0 &&
      missingScenes.length === 0 &&
      !error
    ) {
      generateReport();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectedPerformerId, selectedPerformer, selectedStashID]);

  useEffect(() => {
    const isLoading = localScenesState.loading || remoteScenesState.loading;
    if (!isLoading && (localCount > 0 || remoteCount > 0)) {
      onMissingCountChange?.(missingScenes.length);
    }
  }, [missingScenes.length, localCount, remoteCount, localScenesState.loading, remoteScenesState.loading, onMissingCountChange]);

  const isLoading = localScenesState.loading || remoteScenesState.loading;
  const combinedError = error ?? localScenesState.error?.message ?? remoteScenesState.error?.message;
  const stashboxBase = selectedStashID?.endpoint ? getStashboxBase(selectedStashID.endpoint) : undefined;

  const filteredScenes = useMemo(() => {
    if (!searchFilter.trim()) return missingScenes;
    const lower = searchFilter.toLowerCase();
    return missingScenes.filter((scene) => {
      if (scene.title?.toLowerCase().includes(lower)) return true;
      if (scene.studio?.toLowerCase().includes(lower)) return true;
      if (scene.parent_studio?.toLowerCase().includes(lower)) return true;
      return scene.performers.some((p) => p.toLowerCase().includes(lower));
    });
  }, [missingScenes, searchFilter]);

  const sortedScenes = useMemo(() => {
    const scenes = [...filteredScenes];
    if (sortMode === "title") {
      scenes.sort((a, b) => (a.title ?? "").localeCompare(b.title ?? ""));
    } else if (sortMode === "studio") {
      scenes.sort((a, b) => {
        const sa = a.studio ?? "";
        const sb = b.studio ?? "";
        return sa.localeCompare(sb);
      });
    } else {
      scenes.sort((a, b) => {
        const da = a.date ?? "";
        const db = b.date ?? "";
        return db.localeCompare(da);
      });
    }
    return scenes;
  }, [filteredScenes, sortMode]);

  const hasReport = !isLoading && (localCount > 0 || remoteCount > 0);

  return (
    <div className="ActorMissingScenes">
      {!preselectedPerformerId && (
        <div className="mb-3">
          <Form.Group className="mb-2">
            <Form.Label>
              <FormattedMessage id="actor_missing_scenes.select_actor" />
            </Form.Label>
            <PerformerSelect
              values={selectedPerformer ? [selectedPerformer] : []}
              onSelect={onSelectPerformer}
              isMulti={false}
              creatable={false}
              noSelectionString={intl.formatMessage({
                id: "actor_missing_scenes.select_actor_placeholder",
              })}
            />
          </Form.Group>
        </div>
      )}

      <div className="mb-3">
        <Form.Group>
          <Form.Label>
            <FormattedMessage id="actor_missing_scenes.select_stash_id" />
          </Form.Label>
          <Form.Control
            as="select"
            value={
              selectedStashID
                ? `${selectedStashID.endpoint}|${selectedStashID.stash_id}`
                : ""
            }
            onChange={(event) => {
              const [endpoint, stashIDValue] = event.target.value.split("|");
              const stashID = stashIDs.find(
                (id) => id.endpoint === endpoint && id.stash_id === stashIDValue
              );
              setSelectedStashID(stashID ?? null);
            }}
            disabled={!stashIDs.length}
          >
            {!stashIDs.length && (
              <option value="">
                {intl.formatMessage({ id: "actor_missing_scenes.no_stash_ids" })}
              </option>
            )}
            {stashIDs.map((id) => (
              <option
                key={`${id.endpoint}-${id.stash_id}`}
                value={`${id.endpoint}|${id.stash_id}`}
              >
                {id.stash_id} - {stashBoxLabel(id.endpoint)}
              </option>
            ))}
          </Form.Control>
        </Form.Group>
      </div>

      {!preselectedPerformerId && (
        <div className="mb-3">
          <Button
            onClick={generateReport}
            disabled={!selectedPerformer || !selectedStashID || isLoading}
          >
            <FormattedMessage id="actor_missing_scenes.generate_report" />
          </Button>
        </div>
      )}

      {isLoading && <LoadingIndicator />}
      {combinedError && <ErrorMessage error={combinedError} />}

      {hasReport && (
        <div>
          <div className="mb-2 d-flex align-items-center flex-wrap gap-2">
            <span>
              <FormattedMessage id="actor_missing_scenes.report_total_local" />{" "}
              {selectedPerformer ? (
                <Link to={`/performers/${selectedPerformer.id}/scenes`}>
                  {localCount}
                </Link>
              ) : (
                localCount
              )}
              {" · "}
              <FormattedMessage id="actor_missing_scenes.report_total_remote" />{" "}
              {remoteCount}
              {" · "}
              <FormattedMessage id="actor_missing_scenes.report_missing" />{" "}
              {sortedScenes.length}
              {searchFilter && ` / ${missingScenes.length}`}
            </span>
          </div>

          {missingScenes.length > 0 && (
            <div className="row mb-3">
              <div className="col-md-3 col-lg-2">
                <Form.Control
                  type="search"
                  placeholder={intl.formatMessage({
                    id: "missing_scenes.search_placeholder",
                  })}
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                />
              </div>
              <div className="col-auto d-flex align-items-center">
                <ButtonGroup size="sm">
                  <Button
                    variant={sortMode === "date" ? "primary" : "outline-secondary"}
                    onClick={() => setSortMode("date")}
                  >
                    <FormattedMessage id="missing_scenes.sort_by_date" />
                  </Button>
                  <Button
                    variant={sortMode === "title" ? "primary" : "outline-secondary"}
                    onClick={() => setSortMode("title")}
                  >
                    <FormattedMessage id="missing_scenes.sort_by_title" />
                  </Button>
                  <Button
                    variant={sortMode === "studio" ? "primary" : "outline-secondary"}
                    onClick={() => setSortMode("studio")}
                  >
                    <FormattedMessage id="missing_scenes.sort_by_studio" />
                  </Button>
                </ButtonGroup>
              </div>
            </div>
          )}

          {missingScenes.length === 0 ? (
            <FormattedMessage id="actor_missing_scenes.report_empty" />
          ) : sortedScenes.length === 0 ? (
            <FormattedMessage id="missing_scenes.no_results" />
          ) : (
            <RemoteSceneCardGrid
              scenes={sortedScenes}
              stashboxBase={stashboxBase}
              actorName={selectedPerformer?.name}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default ActorMissingScenes;
