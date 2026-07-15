import React from "react";
import * as GQL from "src/core/generated-graphql";
import { StudioMissingScenes } from "src/components/StudioMissingScenes/StudioMissingScenes";

interface IProps {
  studio: GQL.StudioDataFragment;
  onMissingCountChange?: (count: number) => void;
}

export const StudioMissingPanel: React.FC<IProps> = ({
  studio,
  onMissingCountChange,
}) => {
  return (
    <StudioMissingScenes
      preselectedStudioId={studio.id}
      onMissingCountChange={onMissingCountChange}
    />
  );
};
