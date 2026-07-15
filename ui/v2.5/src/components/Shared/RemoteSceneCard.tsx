import React from "react";
import { Card } from "react-bootstrap";
import { TruncatedText } from "./TruncatedText";
import { Icon } from "./Icon";
import { faFilm, faExternalLinkAlt } from "@fortawesome/free-solid-svg-icons";

export type RemoteScene = {
  id: string;
  title?: string | null;
  date?: string | null;
  urls: string[];
  performers: string[];
  studio?: string | null;
  parent_studio?: string | null;
  image_url?: string | null;
};

interface IProps {
  scene: RemoteScene;
  stashboxBase?: string;
  actorName?: string;
  width?: number;
}

export const RemoteSceneCard: React.FC<IProps> = ({
  scene,
  stashboxBase,
  actorName,
  width,
}) => {
  const stashboxUrl = stashboxBase
    ? `${stashboxBase}scenes/${scene.id}`
    : undefined;

  const displayTitle = scene.title ?? scene.id;

  const searchTerms = [actorName, scene.title ?? scene.id]
    .filter(Boolean)
    .join(" ");
  const googleUrl = `https://www.google.com/search?q=${encodeURIComponent(searchTerms)}`;

  const studioLabel = scene.parent_studio
    ? `${scene.parent_studio} / ${scene.studio}`
    : scene.studio ?? undefined;

  const performersLabel = scene.performers.join(", ");

  const thumbnail = scene.image_url ? (
    <img
      className="scene-card-preview-image"
      loading="lazy"
      src={scene.image_url}
      alt={displayTitle}
    />
  ) : (
    <div className="scene-card-preview-image remote-scene-card-placeholder">
      <Icon icon={faFilm} />
    </div>
  );

  return (
    <Card
      className="scene-card grid-card remote-scene-card"
      style={width ? { width: `${width}px` } : undefined}
    >
      <div className="thumbnail-section">
        {stashboxUrl ? (
          <a
            href={stashboxUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="scene-card-link"
          >
            <div className="scene-card-preview">{thumbnail}</div>
          </a>
        ) : (
          <div className="scene-card-preview">{thumbnail}</div>
        )}
        {stashboxUrl && (
          <div className="scene-card-overlay">
            <a
              href={stashboxUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="scene-card-overlay-link"
              title="Otwórz na Stash-Box"
            >
              <Icon icon={faExternalLinkAlt} />
            </a>
          </div>
        )}
      </div>
      <div className="card-section">
        <a
          href={googleUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          <h5 className="card-section-title flex-aligned">
            <TruncatedText text={displayTitle} lineCount={2} />
          </h5>
        </a>
        <div className="remote-scene-card-details">
          {studioLabel && (
            <div className="remote-scene-card-studio">{studioLabel}</div>
          )}
          {scene.date && (
            <div className="remote-scene-card-date">{scene.date}</div>
          )}
          {performersLabel && (
            <div className="remote-scene-card-performers">
              <TruncatedText text={performersLabel} lineCount={2} />
            </div>
          )}
        </div>
      </div>
    </Card>
  );
};

export default RemoteSceneCard;
