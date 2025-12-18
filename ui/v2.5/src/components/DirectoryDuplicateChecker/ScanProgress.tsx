import React, { useEffect, useRef } from "react";
import { Button, Card, Col, Row } from "react-bootstrap";
import { FormattedMessage } from "react-intl";
import { Icon } from "../Shared/Icon";
import { faTimes } from "@fortawesome/free-solid-svg-icons";
import { useMonitorJob } from "src/utils/job";
import { JobStatus } from "src/core/generated-graphql";
import { LoadingIndicator } from "../Shared/LoadingIndicator";

interface ScanProgressProps {
  jobId: string;
  onComplete?: (scanId?: string) => void;
  onClose: () => void;
}

export const ScanProgress: React.FC<ScanProgressProps> = ({
  jobId,
  onComplete,
  onClose,
}) => {
  const hasCalledOnCompleteRef = useRef(false);
  
  // Reset when jobId changes
  useEffect(() => {
    hasCalledOnCompleteRef.current = false;
  }, [jobId]);
  
  const { job } = useMonitorJob(jobId);

  // Monitor job status and call onComplete when finished
  useEffect(() => {
    if (
      job &&
      (job.status === JobStatus.Finished ||
       job.status === JobStatus.Failed ||
       job.status === JobStatus.Cancelled) &&
      !hasCalledOnCompleteRef.current
    ) {
      hasCalledOnCompleteRef.current = true;
      onComplete?.();
    }
  }, [job?.status, onComplete]);

  if (!job) {
    return null;
  }

  const progressPercent = job.progress !== null && job.progress !== undefined
    ? Math.round(job.progress * 100)
    : undefined;

  return (
    <div
      style={{
        position: "fixed",
        right: "20px",
        top: "80px",
        width: "300px",
        zIndex: 1000,
      }}
    >
      <Card>
        <Card.Header>
          <Row>
            <Col>
              <FormattedMessage id="directory_duplicate_checker.scanning" />
            </Col>
            <Col xs="auto">
              <Button variant="link" size="sm" onClick={onClose}>
                <Icon icon={faTimes} />
              </Button>
            </Col>
          </Row>
        </Card.Header>
        <Card.Body>
          {job.status === JobStatus.Running && (
            <>
              <div className="mb-2">
                <LoadingIndicator inline small message={job.description} />
              </div>
              {progressPercent !== undefined && (
                <div className="mb-2">
                  <div className="progress">
                    <div
                      className="progress-bar"
                      role="progressbar"
                      style={{ width: `${progressPercent}%` }}
                      aria-valuenow={progressPercent}
                      aria-valuemin={0}
                      aria-valuemax={100}
                    >
                      {progressPercent}%
                    </div>
                  </div>
                </div>
              )}
              {job.subTasks && job.subTasks.length > 0 && (
                <div className="small text-muted">
                  {job.subTasks[job.subTasks.length - 1]}
                </div>
              )}
            </>
          )}
          {job.status === JobStatus.Finished && (
            <div>
              <FormattedMessage id="directory_duplicate_checker.scan_completed" />
            </div>
          )}
          {job.status === JobStatus.Failed && (
            <div className="text-danger">
              <FormattedMessage id="directory_duplicate_checker.scan_failed" />
              {job.error && <div className="small">{job.error}</div>}
            </div>
          )}
        </Card.Body>
      </Card>
    </div>
  );
};

