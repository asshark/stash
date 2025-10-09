import React from "react";
import { Helmet } from "react-helmet";
import { makeTitleProps } from "src/hooks/title";
import { useStats, useFindScenes, useFindPerformers } from "src/core/StashService";
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

const Report: React.FC = () => {
  const titleProps = makeTitleProps("report");
  const { data: statsData, error: statsError, loading: statsLoading } = useStats();

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

  const { data: scenesData, loading: scenesLoading } = useFindScenes(mostPlayedScenesFilter);
  const { data: performersData, loading: performersLoading } = useFindPerformers(mostPlayedPerformersFilter);
  const { data: organizedScenesData, loading: organizedScenesLoading } = useFindScenes(organizedScenesFilter);
  const { data: performersWithMostScenesData, loading: performersWithMostScenesLoading } = useFindPerformers(performersWithMostScenesFilter);
  const { data: scenesWithMostOCountData, loading: scenesWithMostOCountLoading } = useFindScenes(scenesWithMostOCountFilter);
  const { data: performersWithMostOCountData, loading: performersWithMostOCountLoading } = useFindPerformers(performersWithMostOCountFilter);

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
                      <FormattedNumber value={organizedScenesData?.findScenes.count || 0} />
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
            </div>
          </div>
        </div>

        {/* Second Section - Most Played Scenes */}
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

        {/* Third Section - Most Played Performers */}
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

        {/* Fourth Section - Performers with Most Scenes */}
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

        {/* Fifth Section - Scenes with Most O Count */}
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

        {/* Sixth Section - Performers with Most O Count */}
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
      </div>
    </>
  );
};

export default Report;


