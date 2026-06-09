import { useEffect, useState } from "react";
import { useJobQueue, useJobsSubscribe } from "src/core/StashService";
import * as GQL from "src/core/generated-graphql";

export type SyncedJobFragment = Pick<
  GQL.Job,
  | "id"
  | "status"
  | "subTasks"
  | "description"
  | "progress"
  | "error"
  | "startTime"
>;

export function isActiveJobStatus(status: GQL.JobStatus) {
  return (
    status === GQL.JobStatus.Ready ||
    status === GQL.JobStatus.Running ||
    status === GQL.JobStatus.Stopping
  );
}

/**
 * Keeps the job queue in sync with GraphQL query + jobsSubscribe.
 * Avoids wiping the UI when a refetch briefly returns an empty queue while jobs still run on the server.
 */
export function useSyncedJobQueue() {
  const jobStatus = useJobQueue();
  const jobsSubscribe = useJobsSubscribe();
  const [queue, setQueue] = useState<SyncedJobFragment[]>([]);

  useEffect(() => {
    const serverQueue = jobStatus.data?.jobQueue;
    if (serverQueue === undefined) {
      return;
    }
    // GraphQL may return null instead of [] when the queue is empty.
    const serverJobs = serverQueue ?? [];

    setQueue((prev) => {
      if (serverJobs.length > 0) {
        return serverJobs as SyncedJobFragment[];
      }
      const activePrev = prev.filter((j) => isActiveJobStatus(j.status));
      if (activePrev.length > 0) {
        return prev;
      }
      return [];
    });
  }, [jobStatus]);

  useEffect(() => {
    if (!jobsSubscribe.data) {
      return;
    }

    const event = jobsSubscribe.data.jobsSubscribe;

    function updateJob() {
      setQueue((q) =>
        q.map((j) =>
          j.id === event.job.id ? (event.job as SyncedJobFragment) : j
        )
      );
    }

    switch (event.type) {
      case GQL.JobStatusUpdateType.Add:
        setQueue((q) => {
          if (q.some((j) => j.id === event.job.id)) {
            return q.map((j) =>
              j.id === event.job.id ? (event.job as SyncedJobFragment) : j
            );
          }
          return q.concat([event.job as SyncedJobFragment]);
        });
        break;
      case GQL.JobStatusUpdateType.Remove:
        updateJob();
        setTimeout(() => {
          setQueue((q) => q.filter((j) => j.id !== event.job.id));
        }, 10000);
        break;
      case GQL.JobStatusUpdateType.Update:
        updateJob();
        break;
    }
  }, [jobsSubscribe.data]);

  const hasActiveJobs = queue.some((j) => isActiveJobStatus(j.status));

  return { queue, hasActiveJobs, refetch: jobStatus.refetch };
}
