import React from "react";
import { RemoteSceneCard, RemoteScene } from "./RemoteSceneCard";
import {
  useCardWidth,
  useContainerDimensions,
} from "./GridCard/GridCard";

const zoomWidths = [280, 340, 480, 640];
const DEFAULT_ZOOM = 1;

interface IProps {
  scenes: RemoteScene[];
  stashboxBase?: string;
  actorName?: string;
}

export const RemoteSceneCardGrid: React.FC<IProps> = ({
  scenes,
  stashboxBase,
  actorName,
}) => {
  const [componentRef, { width: containerWidth }] = useContainerDimensions();
  const cardWidth = useCardWidth(containerWidth, DEFAULT_ZOOM, zoomWidths);

  return (
    <div className="row justify-content-center" ref={componentRef}>
      {scenes.map((scene) => (
        <RemoteSceneCard
          key={scene.id}
          scene={scene}
          stashboxBase={stashboxBase}
          actorName={actorName}
          width={cardWidth}
        />
      ))}
    </div>
  );
};

export default RemoteSceneCardGrid;
