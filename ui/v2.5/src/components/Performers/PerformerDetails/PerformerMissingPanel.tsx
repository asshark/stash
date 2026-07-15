import React from "react";
import * as GQL from "src/core/generated-graphql";
import { ActorMissingScenes } from "src/components/ActorMissingScenes/ActorMissingScenes";

interface IProps {
  performer: GQL.PerformerDataFragment;
  onMissingCountChange?: (count: number) => void;
}

export const PerformerMissingPanel: React.FC<IProps> = ({
  performer,
  onMissingCountChange,
}) => {
  return (
    <ActorMissingScenes
      preselectedPerformerId={performer.id}
      onMissingCountChange={onMissingCountChange}
    />
  );
};
