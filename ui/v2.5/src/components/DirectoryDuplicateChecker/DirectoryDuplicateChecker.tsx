import React, { useState, useEffect, useRef } from "react";
import { Button, Card, Col, Row, Table } from "react-bootstrap";
import { useHistory, useLocation } from "react-router-dom";
import { FormattedMessage, FormattedDate, useIntl } from "react-intl";
import { useMutation, gql } from "@apollo/client";

import * as GQL from "src/core/generated-graphql";
import { LoadingIndicator } from "../Shared/LoadingIndicator";
import { ErrorMessage } from "../Shared/ErrorMessage";
import { Icon } from "../Shared/Icon";
import { faTrash, faPlus, faSearch, faEraser } from "@fortawesome/free-solid-svg-icons";
import { FolderSelectDialog } from "../Shared/FolderSelect/FolderSelectDialog";
import { ScanProgress } from "./ScanProgress";

const CLEAR_DOWNLOAD_DIRECTORY_SCANS = gql`
  mutation ClearDownloadDirectoryScans($directoryId: ID!) {
    clearDownloadDirectoryScans(directoryId: $directoryId)
  }
`;

const START_DOWNLOAD_DIRECTORY_SCAN = gql`
  mutation StartDownloadDirectoryScan($directoryId: ID!) {
    startDownloadDirectoryScan(directoryId: $directoryId)
  }
`;

const CLASSNAME = "directory-duplicate-checker";

export const DirectoryDuplicateChecker: React.FC = () => {
  const intl = useIntl();
  const history = useHistory();
  const location = useLocation();
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [scanningJobId, setScanningJobId] = useState<string | undefined>();
  const [scanningDirectoryId, setScanningDirectoryId] = useState<string | undefined>();

  // Defensive: this route is exact, but keep skip in sync if the component is reused.
  const isOnReportPage = location.pathname.startsWith(
    "/directoryDuplicateChecker/scan/"
  );

  // Close add-directory dialog when entering the page or returning from a scan report.
  useEffect(() => {
    setShowAddDialog(false);
  }, [location.pathname]);

  const { data, loading, error, refetch } = (GQL as any).useDownloadDirectoriesQuery({
    // Skip query if on report page
    skip: isOnReportPage,
    // Use cache-first to avoid unnecessary network requests
    fetchPolicy: "cache-first",
    // Don't notify on network status changes to reduce re-renders
    notifyOnNetworkStatusChange: false,
  });

  const [findJob] = GQL.useFindJobLazyQuery();
  const checkedJobsRef = useRef<Set<string>>(new Set());
  const isCheckingRef = useRef(false);
  const hasMountedRef = useRef(false);
  const isMountedRef = useRef(true);
  const refetchRef = useRef(refetch);
  const checkTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastDirectoriesRef = useRef<string>("");

  // Keep refetch ref up to date
  useEffect(() => {
    refetchRef.current = refetch;
  }, [refetch]);

  // Track component mount/unmount status
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Mark component as mounted (no need to refetch on mount - cache-first will use cache)
  useEffect(() => {
    if (!loading) {
      hasMountedRef.current = true;
    }
  }, [loading]);

  // Detect active scans on mount and when directories data changes
  // Only check when directories data actually changes, not when scanning state changes
  useEffect(() => {
    // Don't check if component unmounted, on report page, still loading, or already checking
    if (!isMountedRef.current || isOnReportPage || loading || isCheckingRef.current) {
      return;
    }

    const directories = data?.downloadDirectories || [];
    
    // Create a string representation of directories for comparison
    const directoriesKey = JSON.stringify(directories.map((d: any) => ({ id: d.id, active_scan_job_id: d.active_scan_job_id })));
    
    // Skip if directories haven't actually changed
    if (directoriesKey === lastDirectoriesRef.current) {
      return;
    }
    
    lastDirectoriesRef.current = directoriesKey;
    
    // Clear any pending timeout
    if (checkTimeoutRef.current) {
      clearTimeout(checkTimeoutRef.current);
    }
    
    // Debounce the check to avoid rapid successive calls
    checkTimeoutRef.current = setTimeout(() => {
      if (!isMountedRef.current) {
        return;
      }
      
      // Check each directory for active scan job
      const checkActiveScans = async () => {
      isCheckingRef.current = true;
      
      try {
        // Always check all directories for active scan jobs
        // This handles both new scans and returning to component after leaving
        const directoriesWithActiveScans = directories.filter((dir: any) => dir.active_scan_job_id);
        
        if (directoriesWithActiveScans.length === 0) {
          // No active scans, clear state if set
          setScanningJobId((prev) => {
            if (prev) {
              console.log("No active scans found, clearing scanning job ID");
              return undefined;
            }
            return prev;
          });
          setScanningDirectoryId((prev) => {
            if (prev) {
              return undefined;
            }
            return prev;
          });
          isCheckingRef.current = false;
          return;
        }
        
        // Clear checked jobs for new check cycle
        checkedJobsRef.current.clear();
        
        // Check all directories for active scan jobs
        const promises = directoriesWithActiveScans.map(async (dir: any) => {
          const jobId = dir.active_scan_job_id;
          
          // Skip if we already checked this job ID in this check cycle
          if (checkedJobsRef.current.has(jobId)) {
            return;
          }

          checkedJobsRef.current.add(jobId);
          
          try {
            const result = await findJob({
              variables: { input: { id: jobId } },
              fetchPolicy: "network-only",
            });
            
            const job = result.data?.findJob;
            
            if (job) {
              if (job.status === GQL.JobStatus.Running) {
                // Job is still running, show progress
                setScanningJobId(jobId);
                setScanningDirectoryId(dir.id);
              } else if (
                job.status === GQL.JobStatus.Finished ||
                job.status === GQL.JobStatus.Failed ||
                job.status === GQL.JobStatus.Cancelled
              ) {
                // Job finished, clear active scan job ID from directory config
                checkedJobsRef.current.delete(jobId);
                // Clear scanning state
                setScanningJobId((prev) => (prev === jobId ? undefined : prev));
                setScanningDirectoryId((prev) => (prev === dir.id ? undefined : prev));
                // Refresh data after a delay to allow backend to save
                // Use ref from ref to avoid triggering useEffect again
                setTimeout(() => {
                  if (isMountedRef.current) {
                    refetchRef.current();
                  }
                }, 1500);
              }
            } else {
              // Job not found (probably already finished and removed)
              checkedJobsRef.current.delete(jobId);
              // Clear scanning state
              setScanningJobId((prev) => (prev === jobId ? undefined : prev));
              setScanningDirectoryId((prev) => (prev === dir.id ? undefined : prev));
            }
          } catch (error) {
            console.error("Error checking job status:", error);
            checkedJobsRef.current.delete(jobId);
          }
        });
        
        await Promise.all(promises);
      } finally {
        isCheckingRef.current = false;
      }
    };
    
    if (directories.length > 0) {
      checkActiveScans();
    }
    }, 300); // Debounce by 300ms
    
    // Cleanup timeout on unmount
    return () => {
      if (checkTimeoutRef.current) {
        clearTimeout(checkTimeoutRef.current);
      }
    };
    // Only run when directories data actually changes, not when refetch is called
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.downloadDirectories, loading, findJob, isOnReportPage]);

  // Poll for active scan status while scanning is active
  useEffect(() => {
    // Don't poll if component unmounted, on report page, or no active scan
    if (!isMountedRef.current || isOnReportPage || !scanningJobId || !scanningDirectoryId) {
      return;
    }

    const intervalId = setInterval(async () => {
      // Check if component is still mounted before making request
      if (!isMountedRef.current) {
        clearInterval(intervalId);
        return;
      }

      try {
        const result = await findJob({
          variables: { input: { id: scanningJobId } },
          fetchPolicy: "network-only",
        });
        
        // Check again after async operation
        if (!isMountedRef.current) {
          return;
        }
        
        const job = result.data?.findJob;
        if (!job || job.status !== GQL.JobStatus.Running) {
          // Job finished or not found, clear state and refresh
          setScanningJobId(undefined);
          setScanningDirectoryId(undefined);
          if (isMountedRef.current) {
            setTimeout(() => {
              if (isMountedRef.current) {
                refetchRef.current();
              }
            }, 500);
          }
        }
      } catch (error) {
        console.error("Error polling job status:", error);
      }
    }, 3000); // Poll every 3 seconds

    return () => {
      clearInterval(intervalId);
    };
  }, [scanningJobId, scanningDirectoryId, findJob, isOnReportPage]);

  const [addDirectory] = (GQL as any).useAddDownloadDirectoryMutation({
    onCompleted: () => {
      refetch();
      setShowAddDialog(false);
    },
    onError: (error: any) => {
      console.error("Error adding directory:", error);
      // Keep dialog open on error so user can try again
    },
  });

  const [removeDirectory] = (GQL as any).useRemoveDownloadDirectoryMutation({
    onCompleted: () => {
      refetch();
    },
  });

  const [startScan] = useMutation(START_DOWNLOAD_DIRECTORY_SCAN, {
    onCompleted: async (data: any) => {
      const jobId = data?.startDownloadDirectoryScan;
      if (jobId) {
        console.log("Scan started, job ID:", jobId);
        // Set scanning job ID immediately
        setScanningJobId(jobId);
        // Refetch directories multiple times to ensure we get updated active_scan_job_id
        // Backend might need a moment to update the directory record
        setTimeout(async () => {
          await refetch();
          // Second refetch after a bit more time to ensure data is updated
          setTimeout(async () => {
            await refetch();
          }, 1000);
        }, 500);
      } else {
        console.warn("startDownloadDirectoryScan did not return a job ID");
      }
    },
    onError: (error: any) => {
      console.error("Error starting scan:", error);
    },
  });

  const [clearScans] = useMutation(CLEAR_DOWNLOAD_DIRECTORY_SCANS, {
    onCompleted: () => {
      refetch();
    },
  });

  const handleAddDirectory = async (directory?: string) => {
    if (!directory) {
      setShowAddDialog(false);
      return;
    }

    try {
      await addDirectory({
        variables: {
          path: directory,
          name: directory.split(/[/\\]/).pop() || directory,
        },
      });
      // Dialog will be closed in onCompleted callback
    } catch (error: any) {
      console.error("Error adding directory:", error);
      // Error handling is done in onError callback
    }
  };

  const handleRemoveDirectory = async (directoryId: string) => {
    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: "this directory" }
        )
      )
    ) {
      return;
    }

    try {
      await removeDirectory({
        variables: { directoryId },
      });
    } catch (error) {
      console.error("Error removing directory:", error);
    }
  };

  const handleStartScan = async (directoryId: string) => {
    try {
      console.log("Starting scan for directory:", directoryId);
      // Clear any previous scanning state
      setScanningJobId(undefined);
      setScanningDirectoryId(undefined);
      // Set new scanning state
      setScanningDirectoryId(directoryId);
      await startScan({
        variables: { directoryId },
      });
      // Note: scanningJobId will be set in onCompleted callback
    } catch (error) {
      console.error("Error starting scan:", error);
      setScanningDirectoryId(undefined);
      setScanningJobId(undefined);
    }
  };

  const handleViewReport = (scanId: string) => {
    history.push(`/directoryDuplicateChecker/scan/${scanId}`);
  };

  const handleClearScans = async (directoryId: string, refetchScans?: () => void) => {
    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: intl.formatMessage({ id: "directory_duplicate_checker.scan_results" }) }
        )
      )
    ) {
      return;
    }

    try {
      await clearScans({
        variables: { directoryId },
      });
      // Refetch scans query to update UI immediately
      if (refetchScans) {
        setTimeout(() => {
          refetchScans();
        }, 500);
      }
      // Also refetch main directories list to update LastScanID
      setTimeout(() => {
        refetch();
      }, 500);
    } catch (error) {
      console.error("Error clearing scans:", error);
    }
  };

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error) {
    return <ErrorMessage error={error.message} />;
  }

  const directories = data?.downloadDirectories || [];

  return (
    <div className={CLASSNAME}>
      <div className="container-fluid">
        <Row>
          <Col>
            <h1>
              <FormattedMessage id="directory_duplicate_checker.title" />
            </h1>
          </Col>
        </Row>

        <Row className="mb-3">
          <Col>
            <Button
              variant="primary"
              onClick={() => setShowAddDialog(true)}
            >
              <Icon icon={faPlus} />
              <FormattedMessage id="actions.add" />{" "}
              <FormattedMessage id="directory_duplicate_checker.directory" />
            </Button>
          </Col>
        </Row>

        {directories.length === 0 ? (
          <Row>
            <Col>
              <Card>
                <Card.Body>
                  <FormattedMessage id="directory_duplicate_checker.no_directories" />
                </Card.Body>
              </Card>
            </Col>
          </Row>
        ) : (
          <div className="table-list">
            <Table striped bordered>
              <thead>
                <tr>
                  <th>
                    <FormattedMessage id="name" />
                  </th>
                  <th>
                    <FormattedMessage id="path" />
                  </th>
                  <th>
                    <FormattedMessage id="directory_duplicate_checker.last_scan" />
                  </th>
                  <th>
                    <FormattedMessage id="actions.actions" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {directories.map((dir: any) => (
                  <DirectoryRow
                    key={dir.id}
                    directory={dir}
                    isScanning={
                      dir.id === scanningDirectoryId && !!scanningJobId
                    }
                    onRemove={handleRemoveDirectory}
                    onStartScan={handleStartScan}
                    onViewReport={handleViewReport}
                    onClearScans={handleClearScans}
                  />
                ))}
              </tbody>
            </Table>
          </div>
        )}

        {showAddDialog && (
          <FolderSelectDialog
            show={showAddDialog}
            allowOnDirectoryDuplicateChecker={true}
            onClose={handleAddDirectory}
          />
        )}

        {scanningJobId && scanningDirectoryId && (
          <ScanProgress
            jobId={scanningJobId}
            onComplete={async () => {
              console.log("=== Scan completed, refetching data ===");
              // Wait a bit for the backend to finish saving
              await new Promise(resolve => setTimeout(resolve, 1500));
              
              // Save directory ID before clearing state
              const completedDirectoryId = scanningDirectoryId;
              
              // Clear scanning state first
              setScanningJobId(undefined);
              setScanningDirectoryId(undefined);
              
              // Refetch to get the latest scan results and updated directory data
              const refetchResult = await refetch();
              
              // Find the directory and get the new scan ID
              const directories = refetchResult.data?.downloadDirectories || [];
              const directory = directories.find((dir: any) => dir.id === completedDirectoryId);
              
              if (directory && directory.last_scan_id) {
                // Redirect to the new scan report
                console.log("=== Redirecting to new scan report:", directory.last_scan_id);
                history.push(`/directoryDuplicateChecker/scan/${directory.last_scan_id}`);
              } else {
                console.log("=== No new scan ID found, staying on current page");
              }
            }}
            onClose={() => {
              setScanningJobId(undefined);
              setScanningDirectoryId(undefined);
            }}
          />
        )}
      </div>
    </div>
  );
};

interface DirectoryRowProps {
  directory: any; // Will be GQL.DownloadDirectory after codegen
  isScanning?: boolean;
  onRemove: (id: string) => void;
  onStartScan: (id: string) => void;
  onViewReport: (scanId: string) => void;
  onClearScans: (id: string, refetchScans?: () => void) => void;
}

const DirectoryRow: React.FC<DirectoryRowProps> = ({
  directory,
  isScanning = false,
  onRemove,
  onStartScan,
  onViewReport,
  onClearScans,
}) => {
  const { data: scansData, refetch: refetchScans } = (GQL as any).useDownloadDirectoryScansQuery({
    variables: { directoryId: directory.id },
    skip: !directory.id,
    // Poll for updates while scanning
    pollInterval: isScanning ? 2000 : 0,
    // Always hit the network when (re)fetching scans so that clearing/rescanning is reflected immediately
    fetchPolicy: "network-only",
    // Don't notify on network status changes to reduce re-renders
    notifyOnNetworkStatusChange: false,
  });

  // Refetch scans when scanning completes or when active_scan_job_id is cleared
  const prevIsScanningRef = useRef(isScanning);
  const prevActiveScanJobIdRef = useRef(directory.active_scan_job_id);
  const hasRefetchedRef = useRef(false);
  
  useEffect(() => {
    // Only refetch if scanning just finished (was true, now false) OR active_scan_job_id was cleared
    const scanningFinished = prevIsScanningRef.current && !isScanning;
    const activeScanCleared = prevActiveScanJobIdRef.current && !directory.active_scan_job_id;
    
    if ((scanningFinished || activeScanCleared) && !hasRefetchedRef.current) {
      hasRefetchedRef.current = true;
      console.log("Scan finished or active scan cleared, refetching scans for directory:", directory.id);
      // Wait a bit for the backend to finish saving
      setTimeout(() => {
        refetchScans();
        // Reset flag after refetch completes
        setTimeout(() => {
          hasRefetchedRef.current = false;
        }, 2000);
      }, 1000);
    }
    
    prevIsScanningRef.current = isScanning;
    prevActiveScanJobIdRef.current = directory.active_scan_job_id;
  }, [isScanning, directory.active_scan_job_id, refetchScans, directory.id]);

  // Find the most recent completed scan by completion time
  const completedScans =
    scansData?.downloadDirectoryScans?.filter(
      (scan: any) => scan.status === "completed" && scan.scan_completed_at
    ) ?? [];

  const lastScan =
    completedScans.length > 0
      ? completedScans.slice().sort(
          (a: any, b: any) =>
            new Date(b.scan_completed_at).getTime() -
            new Date(a.scan_completed_at).getTime()
        )[0]
      : undefined;
  const hasLastScan = !!lastScan;

  return (
    <tr>
      <td>
        <span>{directory.name}</span>
      </td>
      <td className="text-break">
        <span>{directory.path}</span>
      </td>
      <td>
        <span>
          {hasLastScan ? (
            <>
              <FormattedDate
                value={new Date(lastScan.scan_completed_at!)}
                year="numeric"
                month="short"
                day="numeric"
                hour="2-digit"
                minute="2-digit"
              />
              {lastScan.duplicates_found > 0 && (
                <>
                  {" "}
                  (
                  <FormattedMessage
                    id="directory_duplicate_checker.duplicates_found"
                    values={{ count: lastScan.duplicates_found }}
                  />
                  )
                </>
              )}
            </>
          ) : (
            <FormattedMessage id="none" />
          )}
        </span>
      </td>
      <td>
        <Button
          variant="primary"
          size="sm"
          className="mr-2"
          onClick={() => onStartScan(directory.id)}
        >
          <Icon icon={faSearch} />
          <FormattedMessage id="directory_duplicate_checker.check_duplicates" />
        </Button>
        {hasLastScan && (
          <Button
            variant="secondary"
            size="sm"
            className="mr-2"
            onClick={() => onViewReport(lastScan.scan_id)}
          >
            <FormattedMessage id="directory_duplicate_checker.view_report" />
          </Button>
        )}
        {hasLastScan && (
          <Button
            variant="warning"
            size="sm"
            className="mr-2"
            onClick={() => onClearScans(directory.id, refetchScans)}
          >
            <Icon icon={faEraser} />
            <FormattedMessage id="actions.clear" />
          </Button>
        )}
        <Button
          variant="danger"
          size="sm"
          onClick={() => onRemove(directory.id)}
        >
          <Icon icon={faTrash} />
        </Button>
      </td>
    </tr>
  );
};

export default DirectoryDuplicateChecker;
