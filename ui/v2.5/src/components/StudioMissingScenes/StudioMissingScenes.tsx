import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gql, useLazyQuery } from "@apollo/client";
import { Button, ButtonGroup, Form } from "react-bootstrap";
import { FormattedMessage, useIntl } from "react-intl";
import { Link } from "react-router-dom";
import * as GQL from "src/core/generated-graphql";
import { useFindStudio, useConfiguration } from "src/core/StashService";
import { StudioSelect, Studio as SelectStudio } from "src/components/Studios/StudioSelect";
import { ErrorMessage } from "src/components/Shared/ErrorMessage";
import { LoadingIndicator } from "src/components/Shared/LoadingIndicator";
import { RemoteSceneCardGrid } from "src/components/Shared/RemoteSceneCardGrid";
import { RemoteScene } from "src/components/Shared/RemoteSceneCard";
import { getStashboxBase, stashboxDisplayName } from "src/utils/stashbox";

type StudioScenesResult = {
  stashBoxStudioScenes: {
    count: number;
    scenes: RemoteScene[];
  };
};

type StudioScenesVars = {
  input: {
    stash_box_endpoint?: string | null;
    stash_box_index?: number | null;
    studio_id: string;
  };
};

const STASHBOX_STUDIO_SCENES = gql`
  query StashBoxStudioScenes($input: StashBoxStudioScenesInput!) {
    stashBoxStudioScenes(input: $input) {
      count
      scenes {
        id
        title
        date
        urls
        performers
        image_url
      }
    }
  }
`;

type SortMode = "date" | "title" | "performers";

interface IProps {
  preselectedStudioId?: string;
  onMissingCountChange?: (count: number) => void;
}

export const StudioMissingScenes: React.FC<IProps> = ({
  preselectedStudioId,
  onMissingCountChange,
}) => {
  const intl = useIntl();
  const config = useConfiguration();

  const [selectedStudio, setSelectedStudio] = useState<SelectStudio | null>(null);
  const [selectedStashID, setSelectedStashID] = useState<GQL.StashId | null>(null);
  const [searchFilter, setSearchFilter] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("date");

  const { data: studioData } = useFindStudio(selectedStudio?.id ?? "");
  const stashIDs = studioData?.findStudio?.stash_ids ?? [];

  const { data: preselectedData } = useFindStudio(preselectedStudioId ?? "");
  useEffect(() => {
    const s = preselectedData?.findStudio;
    if (preselectedStudioId && s && !selectedStudio) {
      setSelectedStudio({
        id: s.id,
        name: s.name,
        aliases: s.aliases,
        image_path: s.image_path,
      });
    }
  }, [preselectedStudioId, preselectedData, selectedStudio]);

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
    query StudioMissingScenesLocal($filter: FindFilterType, $scene_filter: SceneFilterType) {
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
    StudioScenesResult,
    StudioScenesVars
  >(STASHBOX_STUDIO_SCENES, { fetchPolicy: "network-only" });

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

  const onSelectStudio = (items: SelectStudio[]) => {
    setSelectedStudio(items[0] ?? null);
    setLocalCount(0);
    setRemoteCount(0);
    setMissingScenes([]);
  };

  const generateReport = useCallback(async () => {
    if (!selectedStudio || !selectedStashID) return;

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
              studios: {
                modifier: GQL.CriterionModifier.Includes,
                value: [selectedStudio.id],
              },
            },
          },
        }),
        fetchRemoteScenes({
          variables: {
            input: {
              stash_box_endpoint: selectedStashID.endpoint,
              studio_id: selectedStashID.stash_id,
            },
          },
        }),
      ]);

      if (localResult.errors?.length) throw new Error(localResult.errors[0].message);
      if (remoteResult.errors?.length) throw new Error(remoteResult.errors[0].message);

      const localScenes = localResult.data?.findScenes.scenes ?? [];
      const remoteScenes = remoteResult.data?.stashBoxStudioScenes.scenes ?? [];

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
  }, [fetchLocalScenes, fetchRemoteScenes, selectedStudio, selectedStashID]);

  useEffect(() => {
    if (
      preselectedStudioId &&
      selectedStudio &&
      selectedStashID &&
      localCount === 0 &&
      remoteCount === 0 &&
      missingScenes.length === 0 &&
      !error
    ) {
      generateReport();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preselectedStudioId, selectedStudio, selectedStashID]);

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
      return scene.performers.some((p) => p.toLowerCase().includes(lower));
    });
  }, [missingScenes, searchFilter]);

  const sortedScenes = useMemo(() => {
    const scenes = [...filteredScenes];
    if (sortMode === "title") {
      scenes.sort((a, b) => (a.title ?? "").localeCompare(b.title ?? ""));
    } else if (sortMode === "performers") {
      scenes.sort((a, b) => {
        const pa = a.performers[0] ?? "";
        const pb = b.performers[0] ?? "";
        return pa.localeCompare(pb);
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
    <div className="StudioMissingScenes">
      {!preselectedStudioId && (
        <div className="mb-3">
          <Form.Group className="mb-2">
            <Form.Label>
              <FormattedMessage id="studio_missing_scenes.select_studio" />
            </Form.Label>
            <StudioSelect
              values={selectedStudio ? [selectedStudio] : []}
              onSelect={onSelectStudio}
              isMulti={false}
              creatable={false}
              noSelectionString={intl.formatMessage({
                id: "studio_missing_scenes.select_studio_placeholder",
              })}
            />
          </Form.Group>
        </div>
      )}

      <div className="mb-3">
        <Form.Group>
          <Form.Label>
            <FormattedMessage id="studio_missing_scenes.select_stash_id" />
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
                {intl.formatMessage({ id: "studio_missing_scenes.no_stash_ids" })}
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

      {!preselectedStudioId && (
        <div className="mb-3">
          <Button
            onClick={generateReport}
            disabled={!selectedStudio || !selectedStashID || isLoading}
          >
            <FormattedMessage id="studio_missing_scenes.generate_report" />
          </Button>
        </div>
      )}

      {isLoading && <LoadingIndicator />}
      {combinedError && <ErrorMessage error={combinedError} />}

      {hasReport && (
        <div>
          <div className="mb-2 d-flex align-items-center flex-wrap gap-2">
            <span>
              <FormattedMessage id="studio_missing_scenes.report_total_local" />{" "}
              {selectedStudio ? (
                <Link to={`/studios/${selectedStudio.id}/scenes`}>
                  {localCount}
                </Link>
              ) : (
                localCount
              )}
              {" · "}
              <FormattedMessage id="studio_missing_scenes.report_total_remote" />{" "}
              {remoteCount}
              {" · "}
              <FormattedMessage id="studio_missing_scenes.report_missing" />{" "}
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
                    variant={sortMode === "performers" ? "primary" : "outline-secondary"}
                    onClick={() => setSortMode("performers")}
                  >
                    <FormattedMessage id="missing_scenes.sort_by_performers" />
                  </Button>
                </ButtonGroup>
              </div>
            </div>
          )}

          {missingScenes.length === 0 ? (
            <FormattedMessage id="studio_missing_scenes.report_empty" />
          ) : sortedScenes.length === 0 ? (
            <FormattedMessage id="missing_scenes.no_results" />
          ) : (
            <RemoteSceneCardGrid
              scenes={sortedScenes}
              stashboxBase={stashboxBase}
            />
          )}
        </div>
      )}
    </div>
  );
};

export default StudioMissingScenes;
