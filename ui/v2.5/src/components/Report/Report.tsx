import React from "react";
import { Helmet } from "react-helmet";
import { makeTitleProps } from "src/hooks/title";
import { useStats, useFindScenes, useFindPerformers, useConfiguration, useFindStudios } from "src/core/StashService";
import { LoadingIndicator } from "src/components/Shared/LoadingIndicator";
import { FormattedMessage, FormattedNumber } from "react-intl";
import { ListFilterModel } from "src/models/list-filter/filter";
import { SceneCard } from "src/components/Scenes/SceneCard";
import { PerformerCard } from "src/components/Performers/PerformerCard";
import { SceneQueue } from "src/models/sceneQueue";
import Slider from "@ant-design/react-slick";
import { getSlickSliderSettings } from "src/core/recommendations";
import * as GQL from "src/core/generated-graphql";
import { OrganizedCriterion } from "src/models/list-filter/criteria/organized";
import { GenderCriterion } from "src/models/list-filter/criteria/gender";
import { PathCriterion } from "src/models/list-filter/criteria/path";

interface LibraryStatsProps {
  library: GQL.StashConfig;
}

const LibraryStats: React.FC<LibraryStatsProps> = ({ library }) => {
  // Create filter for scenes in this library
  const scenesFilter = React.useMemo(() => {
    const filter = new ListFilterModel(GQL.FilterMode.Scenes);
    filter.itemsPerPage = 1; // We only need the count
    const pathCriterion = new PathCriterion();
    pathCriterion.value = library.path;
    filter.criteria.push(pathCriterion);
    return filter;
  }, [library.path]);

  // Create filter for organized scenes in this library
  const organizedScenesFilter = React.useMemo(() => {
    const filter = new ListFilterModel(GQL.FilterMode.Scenes);
    filter.itemsPerPage = 1; // We only need the count
    const pathCriterion = new PathCriterion();
    pathCriterion.value = library.path;
    filter.criteria.push(pathCriterion);
    const organizedCriterion = new OrganizedCriterion();
    organizedCriterion.value = "true";
    filter.criteria.push(organizedCriterion);
    return filter;
  }, [library.path]);

  // Use direct GraphQL queries for performers and studios with scenes_filter
  const { data: scenesData, loading: scenesLoading } = useFindScenes(scenesFilter);
  const { data: organizedScenesData, loading: organizedScenesLoading } = useFindScenes(organizedScenesFilter);
  
  // Query for scenes with ratings to calculate average
  const { data: ratedScenesData, loading: ratedScenesLoading } = GQL.useFindScenesQuery({
    variables: {
      filter: { per_page: -1 }, // Get all rated scenes
      scene_filter: {
        path: {
          value: library.path,
          modifier: GQL.CriterionModifier.Includes
        },
        rating100: {
          value: 0,
          modifier: GQL.CriterionModifier.GreaterThan
        }
      }
    }
  });

  const { data: performersData, loading: performersLoading } = GQL.useFindPerformersQuery({
    variables: {
      filter: { per_page: 1 },
      performer_filter: {
        scenes_filter: {
          path: {
            value: library.path,
            modifier: GQL.CriterionModifier.Includes
          }
        }
      }
    }
  });

  const { data: studiosData, loading: studiosLoading } = GQL.useFindStudiosQuery({
    variables: {
      filter: { per_page: 1 },
      studio_filter: {
        scenes_filter: {
          path: {
            value: library.path,
            modifier: GQL.CriterionModifier.Includes
          }
        }
      }
    }
  });

  // Calculate average rating
  const averageRating = React.useMemo(() => {
    if (!ratedScenesData?.findScenes.scenes.length) return 0;
    const total = ratedScenesData.findScenes.scenes.reduce((sum, scene) => sum + (scene.rating100 || 0), 0);
    return total / ratedScenesData.findScenes.scenes.length;
  }, [ratedScenesData]);

  const totalScenes = scenesData?.findScenes.count || 0;
  const organizedScenes = organizedScenesData?.findScenes.count || 0;
  const organizedPercentage = totalScenes > 0 ? (organizedScenes / totalScenes * 100) : 0;

  return (
    <tr>
      <td className="text-truncate" style={{ maxWidth: "300px" }} title={library.path}>
        {library.path}
      </td>
      <td className="text-center">
        {scenesLoading ? "-" : <FormattedNumber value={totalScenes} />}
      </td>
      <td className="text-center">
        {performersLoading ? "-" : <FormattedNumber value={performersData?.findPerformers.count || 0} />}
      </td>
      <td className="text-center">
        {studiosLoading ? "-" : <FormattedNumber value={studiosData?.findStudios.count || 0} />}
      </td>
      <td className="text-center">
        {ratedScenesLoading ? "-" : (
          ratedScenesData?.findScenes.scenes.length ? (
            <FormattedNumber value={averageRating / 20} maximumFractionDigits={2} />
          ) : "-"
        )}
      </td>
      <td className="text-center">
        {organizedScenesLoading ? "-" : <FormattedNumber value={organizedScenes} />}
      </td>
      <td className="text-center">
        {organizedScenesLoading || scenesLoading ? "-" : (
          <>
            <FormattedNumber value={organizedPercentage} maximumFractionDigits={2} />%
          </>
        )}
      </td>
    </tr>
  );
};

const Report: React.FC = () => {
  const titleProps = makeTitleProps("report");
  const { data: statsData, error: statsError, loading: statsLoading } = useStats();
  const { data: configData, loading: configLoading } = useConfiguration();

  // Create filters for most played scenes and performers
  const mostPlayedScenesFilter = new ListFilterModel(GQL.FilterMode.Scenes);
  mostPlayedScenesFilter.sortBy = "play_count";
  mostPlayedScenesFilter.sortDirection = GQL.SortDirectionEnum.Desc;
  mostPlayedScenesFilter.itemsPerPage = 5;

  const mostPlayedPerformersFilter = new ListFilterModel(GQL.FilterMode.Performers);
  mostPlayedPerformersFilter.sortBy = "play_count";
  mostPlayedPerformersFilter.sortDirection = GQL.SortDirectionEnum.Desc;
  mostPlayedPerformersFilter.itemsPerPage = 5;
  // Add female gender filter
  const femaleGenderCriterion3 = new GenderCriterion();
  femaleGenderCriterion3.value = ["Female"];
  mostPlayedPerformersFilter.criteria.push(femaleGenderCriterion3);

  // Create filters for new statistics
  const performersWithMostScenesFilter = new ListFilterModel(GQL.FilterMode.Performers);
  performersWithMostScenesFilter.sortBy = "scenes_count";
  performersWithMostScenesFilter.sortDirection = GQL.SortDirectionEnum.Desc;
  performersWithMostScenesFilter.itemsPerPage = 5;
  // Add female gender filter
  const femaleGenderCriterion = new GenderCriterion();
  femaleGenderCriterion.value = ["Female"];
  performersWithMostScenesFilter.criteria.push(femaleGenderCriterion);

  const scenesWithMostOCountFilter = new ListFilterModel(GQL.FilterMode.Scenes);
  scenesWithMostOCountFilter.sortBy = "o_counter";
  scenesWithMostOCountFilter.sortDirection = GQL.SortDirectionEnum.Desc;
  scenesWithMostOCountFilter.itemsPerPage = 5;

  const performersWithMostOCountFilter = new ListFilterModel(GQL.FilterMode.Performers);
  performersWithMostOCountFilter.sortBy = "o_counter";
  performersWithMostOCountFilter.sortDirection = GQL.SortDirectionEnum.Desc;
  performersWithMostOCountFilter.itemsPerPage = 5;
  // Add female gender filter
  const femaleGenderCriterion2 = new GenderCriterion();
  femaleGenderCriterion2.value = ["Female"];
  performersWithMostOCountFilter.criteria.push(femaleGenderCriterion2);

  // Create filter for organized scenes count
  const organizedScenesFilter = new ListFilterModel(GQL.FilterMode.Scenes);
  organizedScenesFilter.itemsPerPage = 1; // We only need the count
  const organizedCriterion = new OrganizedCriterion();
  organizedCriterion.value = "true";
  organizedScenesFilter.criteria.push(organizedCriterion);

  // Query for high-rated organized scenes from specific folders (ready to copy)
  // Each folder must have the full filter applied (rating + organized + path)
  const { data: readyToCopyData, loading: readyToCopyLoading } = GQL.useFindScenesQuery({
    variables: {
      filter: { per_page: 1 }, // We only need the count
      scene_filter: {
        OR: {
          rating100: {
            value: 79,
            modifier: GQL.CriterionModifier.GreaterThan
          },
          organized: true,
          path: {
            value: "L:\\Clips",
            modifier: GQL.CriterionModifier.Includes
          },
          OR: {
            rating100: {
              value: 79,
              modifier: GQL.CriterionModifier.GreaterThan
            },
            organized: true,
            path: {
              value: "u:\\Clips2",
              modifier: GQL.CriterionModifier.Includes
            },
            OR: {
              rating100: {
                value: 79,
                modifier: GQL.CriterionModifier.GreaterThan
              },
              organized: true,
              path: {
                value: "w:\\Clips30",
                modifier: GQL.CriterionModifier.Includes
              },
              OR: {
                rating100: {
                  value: 79,
                  modifier: GQL.CriterionModifier.GreaterThan
                },
                organized: true,
                path: {
                  value: "w:\\Clips31",
                  modifier: GQL.CriterionModifier.Includes
                },
                OR: {
                  rating100: {
                    value: 79,
                    modifier: GQL.CriterionModifier.GreaterThan
                  },
                  organized: true,
                  path: {
                    value: "u:\\PornHubs",
                    modifier: GQL.CriterionModifier.Includes
                  }
                }
              }
            }
          }
        }
      }
    }
  });

  const { data: scenesData, loading: scenesLoading } = useFindScenes(mostPlayedScenesFilter);
  const { data: performersData, loading: performersLoading } = useFindPerformers(mostPlayedPerformersFilter);
  const { data: organizedScenesData, loading: organizedScenesLoading } = useFindScenes(organizedScenesFilter);
  const { data: performersWithMostScenesData, loading: performersWithMostScenesLoading } = useFindPerformers(performersWithMostScenesFilter);
  const { data: scenesWithMostOCountData, loading: scenesWithMostOCountLoading } = useFindScenes(scenesWithMostOCountFilter);
  const { data: performersWithMostOCountData, loading: performersWithMostOCountLoading } = useFindPerformers(performersWithMostOCountFilter);

  // Query for all scenes with ratings to calculate performer averages
  const { data: ratedScenesForPerformersData, loading: ratedScenesForPerformersLoading } = GQL.useFindScenesQuery({
    variables: {
      filter: { per_page: -1 }, // Get all rated scenes
      scene_filter: {
        rating100: {
          value: 0,
          modifier: GQL.CriterionModifier.GreaterThan
        }
      }
    }
  });

  // Calculate performers with highest average clip ratings
  const topRatedPerformers = React.useMemo(() => {
    if (!ratedScenesForPerformersData?.findScenes.scenes) return [];

    // Map to store performer ratings
    const performerRatings = new Map<string, { ratings: number[], performer: any }>();

    // Aggregate ratings by performer
    ratedScenesForPerformersData.findScenes.scenes.forEach(scene => {
      if (scene.rating100 && scene.performers) {
        scene.performers.forEach(performer => {
          // Only include female performers
          if (performer.gender === GQL.GenderEnum.Female) {
            if (!performerRatings.has(performer.id)) {
              performerRatings.set(performer.id, { ratings: [], performer });
            }
            performerRatings.get(performer.id)!.ratings.push(scene.rating100!);
          }
        });
      }
    });

    // Calculate averages and sort
    const performersWithAverages = Array.from(performerRatings.entries()).map(([id, data]) => {
      const average = data.ratings.reduce((sum, r) => sum + r, 0) / data.ratings.length;
      return {
        performer: data.performer,
        averageRating: average,
        ratedClipsCount: data.ratings.length
      };
    });

    // Sort by average rating descending and take top 5
    return performersWithAverages
      .sort((a, b) => b.averageRating - a.averageRating)
      .slice(0, 5);
  }, [ratedScenesForPerformersData]);

  if (statsError) return <span>{statsError.message}</span>;
  if (statsLoading || !statsData) return <LoadingIndicator />;

  const scenesQueue = SceneQueue.fromListFilterModel(mostPlayedScenesFilter);
  const scenesWithOCountQueue = SceneQueue.fromListFilterModel(scenesWithMostOCountFilter);

  return (
    <>
      <Helmet {...titleProps} />
      <div className="container-fluid">
        <h1>Report</h1>
        
        {/* First Section - Basic Statistics */}
        <div className="row mb-4">
          <div className="col-12">
            <h2>Podstawowe statystyki</h2>
            <div className="row stats">
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    <FormattedNumber value={statsData.stats.scene_count} />
                  </p>
                  <p className="heading">Ilość scen</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    {organizedScenesLoading ? (
                      "-"
                    ) : (
                      <>
                        <FormattedNumber value={organizedScenesData?.findScenes.count || 0} />
                        {statsData.stats.scene_count > 0 && (
                          <span style={{ fontSize: '0.8em', fontWeight: 'normal' }}>
                            {" "}({((organizedScenesData?.findScenes.count || 0) / statsData.stats.scene_count * 100).toFixed(2)}%)
                          </span>
                        )}
                      </>
                    )}
                  </p>
                  <p className="heading">Uporządkowane sceny</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    <FormattedNumber value={statsData.stats.scenes_played} />
                  </p>
                  <p className="heading">Obejrzane sceny</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    <FormattedNumber value={statsData.stats.total_play_count} />
                  </p>
                  <p className="heading">Łączna liczba odtworzeń</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    <FormattedNumber value={statsData.stats.performer_count} />
                  </p>
                  <p className="heading">Ilość aktorów</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    <FormattedNumber value={statsData.stats.studio_count} />
                  </p>
                  <p className="heading">Ilość studiów</p>
                </div>
              </div>
              <div className="col-md-2 col-sm-4 col-6 mb-3">
                <div className="stats-element">
                  <p className="title">
                    {readyToCopyLoading ? (
                      "-"
                    ) : (
                      <FormattedNumber value={readyToCopyData?.findScenes.count || 0} />
                    )}
                  </p>
                  <p className="heading">Gotowe do skopiowania</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Second Section - Library Statistics */}
        <div className="row mb-4">
          <div className="col-12">
            <h2>Statystyki bibliotek</h2>
            {configLoading ? (
              <LoadingIndicator />
            ) : (
              <div className="table-responsive">
                <table className="table table-striped">
                  <thead>
                    <tr>
                      <th>Biblioteka</th>
                      <th className="text-center">Sceny</th>
                      <th className="text-center">Aktorzy</th>
                      <th className="text-center">Studia</th>
                      <th className="text-center">Średnia ocena</th>
                      <th className="text-center">Uporządkowane</th>
                      <th className="text-center">% Uporządkowanych</th>
                    </tr>
                  </thead>
                  <tbody>
                    {configData?.configuration.general.stashes.map((library, index) => (
                      <LibraryStats key={index} library={library} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Third Section - Most Played Scenes */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 najczęściej odtwarzanych scen</h3>
            {scenesLoading ? (
              <LoadingIndicator />
            ) : (
              <Slider
                {...getSlickSliderSettings(
                  scenesData?.findScenes.count || 5,
                  false
                )}
              >
                {scenesData?.findScenes.scenes.map((scene, index) => (
                  <SceneCard
                    key={scene.id}
                    scene={scene}
                    queue={scenesQueue}
                    index={index}
                    zoomIndex={1}
                  />
                ))}
              </Slider>
            )}
          </div>
        </div>

        {/* Fourth Section - Most Played Performers */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 najczęściej odtwarzanych aktorek</h3>
            {performersLoading ? (
              <LoadingIndicator />
            ) : (
              <Slider
                {...getSlickSliderSettings(
                  performersData?.findPerformers.count || 5,
                  false
                )}
              >
                {performersData?.findPerformers.performers.map((performer) => (
                  <PerformerCard
                    key={performer.id}
                    performer={performer}
                    zoomIndex={1}
                  />
                ))}
              </Slider>
            )}
          </div>
        </div>

        {/* Fifth Section - Performers with Most Scenes */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 aktorek z największą liczbą scen</h3>
            {performersWithMostScenesLoading ? (
              <LoadingIndicator />
            ) : (
              <Slider
                {...getSlickSliderSettings(
                  performersWithMostScenesData?.findPerformers.count || 5,
                  false
                )}
              >
                {performersWithMostScenesData?.findPerformers.performers.map((performer) => (
                  <PerformerCard
                    key={performer.id}
                    performer={performer}
                    zoomIndex={1}
                  />
                ))}
              </Slider>
            )}
          </div>
        </div>

        {/* Sixth Section - Scenes with Most O Count */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 scen z największą liczbą O Count</h3>
            {scenesWithMostOCountLoading ? (
              <LoadingIndicator />
            ) : (
              <Slider
                {...getSlickSliderSettings(
                  scenesWithMostOCountData?.findScenes.count || 5,
                  false
                )}
              >
                {scenesWithMostOCountData?.findScenes.scenes.map((scene, index) => (
                  <SceneCard
                    key={scene.id}
                    scene={scene}
                    queue={scenesWithOCountQueue}
                    index={index}
                    zoomIndex={1}
                  />
                ))}
              </Slider>
            )}
          </div>
        </div>

        {/* Seventh Section - Performers with Most O Count */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 aktorek z największą liczbą O Count</h3>
            {performersWithMostOCountLoading ? (
              <LoadingIndicator />
            ) : (
              <Slider
                {...getSlickSliderSettings(
                  performersWithMostOCountData?.findPerformers.count || 5,
                  false
                )}
              >
                {performersWithMostOCountData?.findPerformers.performers.map((performer) => (
                  <PerformerCard
                    key={performer.id}
                    performer={performer}
                    zoomIndex={1}
                  />
                ))}
              </Slider>
            )}
          </div>
        </div>

        {/* Eighth Section - Performers with Highest Average Clip Ratings */}
        <div className="row mb-4">
          <div className="col-12">
            <h3>5 aktorek z najwyższą średnią ocen klipów</h3>
            {ratedScenesForPerformersLoading ? (
              <LoadingIndicator />
            ) : topRatedPerformers.length > 0 ? (
              <div className="table-responsive">
                <table className="table table-striped">
                  <thead>
                    <tr>
                      <th>Miejsce</th>
                      <th>Aktorka</th>
                      <th className="text-center">Średnia ocen</th>
                      <th className="text-center">Liczba ocenionych klipów</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topRatedPerformers.map((item, index) => (
                      <tr key={item.performer.id}>
                        <td className="text-center">{index + 1}</td>
                        <td>
                          <a href={`/performers/${item.performer.id}`}>
                            {item.performer.name}
                          </a>
                        </td>
                        <td className="text-center">
                          <FormattedNumber value={item.averageRating / 20} minimumFractionDigits={2} maximumFractionDigits={2} />
                        </td>
                        <td className="text-center">
                          <FormattedNumber value={item.ratedClipsCount} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center">
                <p>Brak ocenionych klipów z aktorkami</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};

export default Report;


