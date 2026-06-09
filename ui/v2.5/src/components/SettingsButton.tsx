import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import React from "react";
import { Button } from "react-bootstrap";
import { useIntl } from "react-intl";
import { faCog } from "@fortawesome/free-solid-svg-icons";
import { useSyncedJobQueue } from "src/hooks/useSyncedJobQueue";

export const SettingsButton: React.FC = () => {
  const intl = useIntl();
  const { hasActiveJobs } = useSyncedJobQueue();

  return (
    <Button
      className="minimal d-flex align-items-center h-100"
      title={intl.formatMessage({ id: "settings" })}
    >
      <FontAwesomeIcon icon={faCog} spin={hasActiveJobs} />
    </Button>
  );
};
