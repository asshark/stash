import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gql, useLazyQuery } from "@apollo/client";
import { Button, Card, Form, Table } from "react-bootstrap";
import { FormattedMessage, useIntl } from "react-intl";
import * as GQL from "src/core/generated-graphql";
import { useFindPerformer, useConfiguration } from "src/core/StashService";
import { PerformerSelect } from "src/components/Performers/PerformerSelect";
import { ErrorMessage } from "src/components/Shared/ErrorMessage";
import { LoadingIndicator } from "src/components/Shared/LoadingIndicator";
import { ExternalLink } from "src/components/Shared/ExternalLink";
import { getStashboxBase, stashboxDisplayName } from "src/utils/stashbox";

type RemoteScene = {
  id: string;
  title?: string | null;
  date?: string | null;
  urls: string[];
  performers: string[];
};

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
      }
    }
  }
`;

export const ActorMissingScenes: React.FC = () => {
  const intl = useIntl();
  const config = useConfiguration();

  const [selectedPerformer, setSelectedPerformer] = useState<GQL.Performer | null>(
    null
  );
  const [selectedStashID, setSelectedStashID] = useState<GQL.StashId | null>(
    null
  );

  const { data: performerData } = useFindPerformer(selectedPerformer?.id ?? "");
  const stashIDs = performerData?.findPerformer?.stash_ids ?? [];

  useEffect(() => {
    if (!stashIDs.length) {
      setSelectedStashID(null);
      return;
    }

    if (
      !selectedStashID ||
      !stashIDs.some(
        (s) =>
          s.stash_id === selectedStashID.stash_id &&
          s.endpoint === selectedStashID.endpoint
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
          stash_ids: Array<{
            endpoint: string;
            stash_id: string;
          }>;
        }>;
      };
    },
    {
      filter: GQL.FindFilterType;
      scene_filter: GQL.SceneFilterType;
    }
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
      if (index === -1) {
        return endpoint;
      }
      return stashboxDisplayName(stashBoxes[index].name, index);
    },
    [stashBoxes]
  );

  const onSelectPerformer = (items: GQL.Performer[]) => {
    setSelectedPerformer(items[0] ?? null);
    setLocalCount(0);
    setRemoteCount(0);
    setMissingScenes([]);
  };

  const generateReport = useCallback(async () => {
    if (!selectedPerformer || !selectedStashID) {
      return;
    }

    setError(null);
    setMissingScenes([]);
    setLocalCount(0);
    setRemoteCount(0);

    try {
      const [localResult, remoteResult] = await Promise.all([
        fetchLocalScenes({
          variables: {
            filter: {
              per_page: -1,
            },
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

      if (localResult.errors?.length) {
        throw new Error(localResult.errors[0].message);
      }
      if (remoteResult.errors?.length) {
        throw new Error(remoteResult.errors[0].message);
      }

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
        if (localStashIDs.has(scene.id)) {
          return false;
        }
        const remoteUrls = (scene.urls ?? [])
          .map((url) => url.trim())
          .filter((url) => url.length > 0);
        return !remoteUrls.some((url) => localURLs.has(url));
      });

      setLocalCount(localScenes.length);
      setRemoteCount(remoteScenes.length);
      setMissingScenes(missing);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [fetchLocalScenes, fetchRemoteScenes, selectedPerformer, selectedStashID]);

  const isLoading = localScenesState.loading || remoteScenesState.loading;
  const combinedError =
    error ??
    localScenesState.error?.message ??
    remoteScenesState.error?.message;
  const stashboxBase = selectedStashID?.endpoint
    ? getStashboxBase(selectedStashID.endpoint)
    : undefined;
  const unknownYearLabel = intl.formatMessage({ id: "unknown" });
  const groupedMissingScenes = useMemo(() => {
    const groups = new Map<string, RemoteScene[]>();

    missingScenes.forEach((scene) => {
      const year = scene.date?.slice(0, 4);
      const yearLabel =
        year && /^\d{4}$/.test(year) ? year : unknownYearLabel;
      const entry = groups.get(yearLabel);
      if (entry) {
        entry.push(scene);
      } else {
        groups.set(yearLabel, [scene]);
      }
    });

    const entries = Array.from(groups.entries());
    entries.sort((a, b) => {
      const aYear = a[0] === unknownYearLabel ? -1 : parseInt(a[0], 10);
      const bYear = b[0] === unknownYearLabel ? -1 : parseInt(b[0], 10);
      if (aYear === bYear) {
        return 0;
      }
      if (aYear === -1) {
        return 1;
      }
      if (bYear === -1) {
        return -1;
      }
      return bYear - aYear;
    });
    return entries;
  }, [missingScenes, unknownYearLabel]);

  return (
    <div className="ActorMissingScenes">
      <Card>
        <Card.Header>
          <FormattedMessage id="actor_missing_scenes.title" />
        </Card.Header>
        <Card.Body>
          <Form>
            <Form.Group>
              <Form.Label>
                <FormattedMessage id="actor_missing_scenes.select_actor" />
              </Form.Label>
              <PerformerSelect
                values={selectedPerformer ? [selectedPerformer] : []}
                onSelect={onSelectPerformer}
                isMulti={false}
                creatable={false}
                closeMenuOnSelect
                noSelectionString={intl.formatMessage({
                  id: "actor_missing_scenes.select_actor_placeholder",
                })}
              />
            </Form.Group>
            <Form.Group className="mt-3">
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
                  const [endpoint, stashIDValue] =
                    event.target.value.split("|");
                  const stashID = stashIDs.find(
                    (id) =>
                      id.endpoint === endpoint && id.stash_id === stashIDValue
                  );
                  setSelectedStashID(stashID ?? null);
                }}
                disabled={!stashIDs.length}
              >
                {!stashIDs.length && (
                  <option value="">
                    {intl.formatMessage({
                      id: "actor_missing_scenes.no_stash_ids",
                    })}
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
            <div className="mt-3">
              <Button
                onClick={generateReport}
                disabled={!selectedPerformer || !selectedStashID || isLoading}
              >
                <FormattedMessage id="actor_missing_scenes.generate_report" />
              </Button>
            </div>
          </Form>
        </Card.Body>
      </Card>

      {isLoading && <LoadingIndicator />}

      {combinedError && <ErrorMessage error={combinedError} />}

      {!isLoading && (localCount > 0 || remoteCount > 0) && (
        <Card className="mt-3">
          <Card.Header>
            <FormattedMessage id="actor_missing_scenes.report_title" />
          </Card.Header>
          <Card.Body>
            <div className="mb-3">
              <strong>
                <FormattedMessage id="actor_missing_scenes.report_total_local" />
              </strong>{" "}
              {localCount}
              <br />
              <strong>
                <FormattedMessage id="actor_missing_scenes.report_total_remote" />
              </strong>{" "}
              {remoteCount}
              <br />
              <strong>
                <FormattedMessage id="actor_missing_scenes.report_missing" />
              </strong>{" "}
              {missingScenes.length}
            </div>

            {missingScenes.length === 0 ? (
              <FormattedMessage id="actor_missing_scenes.report_empty" />
            ) : (
              groupedMissingScenes.map(([year, scenes]) => (
                <div key={year} className="mb-4">
                  <div className="mb-2">
                    <strong>{year}</strong> ({scenes.length})
                  </div>
                  <Table
                    striped
                    bordered
                    hover
                    responsive
                    className="ActorMissingScenes-table"
                  >
                    <thead>
                      <tr>
                        <th>
                          <FormattedMessage id="stash_id" />
                        </th>
                        <th>
                          <FormattedMessage id="performers" />
                        </th>
                        <th>
                          <FormattedMessage id="title" />
                        </th>
                        <th>
                          <FormattedMessage id="date" />
                        </th>
                        <th>
                          <FormattedMessage id="url" />
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {scenes.map((scene) => {
                        const url =
                          scene.urls?.[0] ??
                          (stashboxBase
                            ? `${stashboxBase}scenes/${scene.id}`
                            : "");
                        const performers = scene.performers?.join(", ") ?? "";
                        return (
                          <tr key={scene.id} className="ActorMissingScenes-row">
                            <td className="ActorMissingScenes-stash-id">
                              {stashboxBase ? (
                                <ExternalLink
                                  href={`${stashboxBase}scenes/${scene.id}`}
                                >
                                  {scene.id}
                                </ExternalLink>
                              ) : (
                                scene.id
                              )}
                            </td>
                            <td className="ActorMissingScenes-performers">
                              {performers}
                            </td>
                            <td className="ActorMissingScenes-title">
                              {scene.title}
                            </td>
                            <td className="ActorMissingScenes-date">
                              {scene.date}
                            </td>
                            <td>
                              {url ? (
                                <ExternalLink href={url}>{url}</ExternalLink>
                              ) : (
                                ""
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </Table>
                </div>
              ))
            )}
          </Card.Body>
        </Card>
      )}
    </div>
  );
};

export default ActorMissingScenes;
