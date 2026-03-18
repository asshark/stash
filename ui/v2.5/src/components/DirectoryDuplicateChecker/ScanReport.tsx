import React, { useState, useMemo, useEffect, useRef } from "react";
import {
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
  Accordion,
  Spinner,
} from "react-bootstrap";
import { gql, useMutation, useApolloClient } from "@apollo/client";
import { useParams, useHistory } from "react-router-dom";
import { FormattedMessage, FormattedNumber, useIntl } from "react-intl";

import * as GQL from "src/core/generated-graphql";
import { LoadingIndicator } from "../Shared/LoadingIndicator";
import { ErrorMessage } from "../Shared/ErrorMessage";
import { Icon } from "../Shared/Icon";
import { faTrash, faArrowLeft, faPlay, faCheckCircle, faEquals, faArrowUp, faArrowDown, faSpinner } from "@fortawesome/free-solid-svg-icons";
import { FileSize } from "../Shared/FileSize";
import { Pagination } from "src/components/List/Pagination";
import TextUtils from "src/utils/text";
import { getPlatformURL } from "src/core/createClient";
import { useMonitorJob } from "src/utils/job";

const CLASSNAME = "directory-duplicate-checker-report";

const REPLACE_DUPLICATE_WITH_SCENE = gql`
  mutation ReplaceDuplicateWithScene($sceneId: ID!, $duplicatePath: String!) {
    replaceDuplicateWithScene(scene_id: $sceneId, duplicate_path: $duplicatePath)
  }
`;

export const ScanReport: React.FC = () => {
  const intl = useIntl();
  const history = useHistory();
  const client = useApolloClient();
  const { scanId } = useParams<{ scanId: string }>();
  const query = new URLSearchParams(history.location.search);
  const currentPage = Number.parseInt(query.get("page") ?? "1", 10);
  const pageSize = Number.parseInt(query.get("size") ?? "20", 10);

  const [currentPageSize, setCurrentPageSize] = useState(pageSize);
  const [checkedFiles, setCheckedFiles] = useState<Record<string, boolean>>({});
  const [deleting, setDeleting] = useState(false);
  const [replaceJobIds, setReplaceJobIds] = useState<Record<string, string>>({}); // sceneId -> jobId
  const hasRedirectedRef = useRef(false);

  const { data, loading, error, refetch } = (GQL as any).useDownloadScanResultQuery({
    variables: { scanId: scanId! },
    skip: !scanId,
    fetchPolicy: "network-only",
    notifyOnNetworkStatusChange: false,
  });

  // Monitor replace jobs using jobs subscription + polling fallback
  const jobsSubscribe = GQL.useJobsSubscribeSubscription();
  const replaceJobIdsRef = useRef(replaceJobIds);
  
  // Keep ref in sync with state
  useEffect(() => {
    replaceJobIdsRef.current = replaceJobIds;
  }, [replaceJobIds]);
  
  // Helper function to handle job completion
  const handleJobCompletion = useRef((sceneId: string) => {
    console.log("Replace job finished, refreshing scan result for scene:", sceneId);
    // Wait a bit for backend to update the scene data
    setTimeout(async () => {
      console.log("Refreshing scan result after replace job completion");
      // Evict scene from cache to force fresh data
      try {
        client.cache.evict({ id: `Scene:${sceneId}` });
        // Also evict the scan result query cache
        client.cache.evict({ 
          fieldName: "downloadScanResult",
        });
        client.cache.gc();
      } catch (e) {
        console.error("Error evicting cache:", e);
      }
      
      // Refresh the scan result to get updated scene data
      // The backend resolver will fetch fresh scene data from database
      try {
        const result = await refetch({
          variables: { scanId: scanId! },
          fetchPolicy: "network-only",
        });
        
        console.log("Scan result refetched:", {
          filesCount: result.data?.downloadScanResult?.files?.length,
          sceneId,
          // Log scene data for debugging
          sceneData: result.data?.downloadScanResult?.files?.find((f: any) => 
            f.matching_scenes?.some((s: any) => s.id === sceneId)
          )?.matching_scenes?.find((s: any) => s.id === sceneId),
        });
      } catch (error) {
        console.error("Error refetching scan result:", error);
      }
      setDeleting(false);
    }, 2000); // Delay to ensure backend has updated the scene data
  });
  
  // Monitor via websocket subscription
  useEffect(() => {
    if (!jobsSubscribe.data) {
      return;
    }

    const event = jobsSubscribe.data.jobsSubscribe;
    const jobId = event.job.id;
    
    // Check if this job is one we're monitoring using ref to avoid stale closure
    const currentReplaceJobIds = replaceJobIdsRef.current;
    const jobKey = Object.keys(currentReplaceJobIds).find(key => currentReplaceJobIds[key] === jobId);
    const resolvedSceneId = jobKey?.startsWith("replace_") ? jobKey.substring("replace_".length) : jobKey;
    
    console.log("JobsSubscribe event:", {
      jobId,
      status: event.job.status,
      type: event.type,
      monitoringJobs: Object.keys(currentReplaceJobIds),
      isMonitored: !!resolvedSceneId,
      sceneId: resolvedSceneId,
    });
    
    if (!jobKey || !resolvedSceneId) {
      return;
    }

    console.log("Replace job status update:", {
      sceneId: resolvedSceneId,
      jobId,
      status: event.job.status,
      type: event.type,
    });

    if (event.type === GQL.JobStatusUpdateType.Remove || 
        (event.job.status === GQL.JobStatus.Finished || 
         event.job.status === GQL.JobStatus.Failed || 
         event.job.status === GQL.JobStatus.Cancelled)) {
      
      // Remove job ID from map
      setReplaceJobIds(prev => {
        const newMap = { ...prev };
        delete newMap[jobKey];
        return newMap;
      });

      if (event.job.status === GQL.JobStatus.Finished) {
        handleJobCompletion.current(resolvedSceneId);
      } else {
        setDeleting(false);
      }
    }
  }, [jobsSubscribe.data, scanId, refetch, client]);
  
  const scanResult = data?.downloadScanResult;
  const directoryId = scanResult?.directory_id;

  // Query to get directory info and check for active scan
  const { data: directoriesData, refetch: refetchDirectories } = (GQL as any).useDownloadDirectoriesQuery({
    skip: !directoryId,
    fetchPolicy: "cache-first",
    notifyOnNetworkStatusChange: false,
  });

  const [findJob] = GQL.useFindJobLazyQuery();
  
  // Polling fallback for all jobs (in case websocket doesn't work)
  const pollingIntervalRef = useRef<number | null>(null);
  
  useEffect(() => {
    const currentReplaceJobIds = replaceJobIdsRef.current;
    const jobIds = Object.values(currentReplaceJobIds);
    
    if (jobIds.length === 0) {
      // Stop polling if no jobs to monitor
      if (pollingIntervalRef.current) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      return;
    }
    
    // Start polling if not already polling
    if (!pollingIntervalRef.current) {
      pollingIntervalRef.current = window.setInterval(async () => {
        const currentReplaceJobIds = replaceJobIdsRef.current;
        const jobIds = Object.values(currentReplaceJobIds);
        
        for (const jobId of jobIds) {
          try {
            const result = await findJob({
              variables: { input: { id: jobId } },
              fetchPolicy: "network-only",
            });
            
            const job = result.data?.findJob;
            if (!job) {
              continue;
            }
            
            const jobKey = Object.keys(currentReplaceJobIds).find(key => currentReplaceJobIds[key] === jobId);
            const resolvedSceneId = jobKey?.startsWith("replace_") ? jobKey.substring("replace_".length) : jobKey;
            if (!jobKey || !resolvedSceneId) {
              continue;
            }
            
            if (job.status === GQL.JobStatus.Finished || 
                job.status === GQL.JobStatus.Failed || 
                job.status === GQL.JobStatus.Cancelled) {
              
              console.log("Replace job finished via polling:", {
                sceneId: resolvedSceneId,
                jobId,
                status: job.status,
              });
              
              // Remove job ID from map
              setReplaceJobIds(prev => {
                const newMap = { ...prev };
                delete newMap[jobKey];
                return newMap;
              });
              
              if (job.status === GQL.JobStatus.Finished) {
                handleJobCompletion.current(resolvedSceneId);
              } else {
                setDeleting(false);
              }
            }
          } catch (error) {
            console.error("Error polling job status:", error);
          }
        }
      }, 2000); // Poll every 2 seconds
    }
    
    return () => {
      if (pollingIntervalRef.current) {
        window.clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [replaceJobIds, findJob]);
  const [deleteDuplicateFiles] = GQL.useDeleteDuplicateFilesMutation();
  const [metadataScan] = GQL.useMetadataScanMutation();
  const [replaceDuplicateWithScene] = useMutation(REPLACE_DUPLICATE_WITH_SCENE);

  useEffect(() => {
    setCurrentPageSize(pageSize);
  }, [pageSize]);

  // Monitor active scan and redirect to new report when completed
  useEffect(() => {
    if (!directoryId || hasRedirectedRef.current || !directoriesData?.downloadDirectories) {
      return;
    }

    const directory = directoriesData.downloadDirectories.find((dir: any) => dir.id === directoryId);
    if (!directory?.active_scan_job_id) {
      return;
    }

    const checkJobStatus = async () => {
      try {
        const result = await findJob({
          variables: { input: { id: directory.active_scan_job_id } },
          fetchPolicy: "network-only",
        });

        const job = result.data?.findJob;
        if (job && job.status === GQL.JobStatus.Finished) {
          // Job finished, wait for backend to save and redirect to new report
          hasRedirectedRef.current = true;
          setTimeout(async () => {
            const updatedResult = await refetchDirectories();
            const updatedDirectory = updatedResult.data?.downloadDirectories?.find(
              (dir: any) => dir.id === directoryId
            );
            if (updatedDirectory?.last_scan_id && updatedDirectory.last_scan_id !== scanId) {
              history.push(`/directoryDuplicateChecker/scan/${updatedDirectory.last_scan_id}`);
            }
          }, 1500);
        } else if (job && (job.status === GQL.JobStatus.Failed || job.status === GQL.JobStatus.Cancelled)) {
          // Job failed or cancelled, stop monitoring
          hasRedirectedRef.current = true;
        }
      } catch (error) {
        console.error("Error checking job status:", error);
      }
    };

    // Check immediately and then poll every 3 seconds
    checkJobStatus();
    const intervalId = setInterval(checkJobStatus, 3000);

    return () => {
      clearInterval(intervalId);
    };
  }, [directoryId, directoriesData, findJob, refetchDirectories, history, scanId]);

  const files = scanResult?.files || [];

  // Type for file groups
  interface FileGroup {
    phash: string;
    files: typeof files;
    isExactDuplicate: boolean;
    hasMatchingScenes: boolean;
    hasBetterQuality: boolean; // Download file has better quality than library scene
    hasWorseQuality: boolean; // Download file has worse quality than library scene
    hasSameQuality: boolean; // Download file has same quality as library scene
  }

  // Calculate quality score for a file (higher = better)
  const getQualityScore = (file: typeof files[0]): number => {
    const resolution = (file.width || 0) * (file.height || 0);
    const fileSize = file.file_size || 0;
    // Weight resolution more than file size (resolution is more important)
    return resolution * 2 + fileSize;
  };

  // Compare quality between download file and library scene
  const compareQuality = (downloadFile: typeof files[0], libraryScene: typeof files[0]["matching_scenes"][0]): "better" | "worse" | "same" => {
    const downloadScore = getQualityScore(downloadFile);
    const libraryScore = (libraryScene.width || 0) * (libraryScene.height || 0) * 2 + (libraryScene.file_size || 0);
    
    if (downloadScore > libraryScore * 1.1) { // 10% threshold to avoid minor differences
      return "better";
    } else if (downloadScore < libraryScore * 0.9) { // 10% threshold
      return "worse";
    }
    return "same";
  };

  // Check if any file in group has better/worse/same quality than matching scenes
  const checkQualityComparison = (groupFiles: typeof files): { better: boolean; worse: boolean; same: boolean } => {
    let hasBetter = false;
    let hasWorse = false;
    let hasSame = false;

    for (const file of groupFiles) {
      if (file.matching_scenes && file.matching_scenes.length > 0) {
        for (const scene of file.matching_scenes) {
          const comparison = compareQuality(file, scene);
          if (comparison === "better") {
            hasBetter = true;
          } else if (comparison === "worse") {
            hasWorse = true;
          } else if (comparison === "same") {
            hasSame = true;
          }
        }
      }
    }

    return { better: hasBetter, worse: hasWorse, same: hasSame };
  };

  // Check if two files are exact duplicates (same phash, size, resolution, duration)
  const isExactDuplicate = (file1: typeof files[0], file2: typeof files[0]): boolean => {
    return (
      file1.phash === file2.phash &&
      file1.file_size === file2.file_size &&
      file1.width === file2.width &&
      file1.height === file2.height &&
      Math.abs((file1.duration || 0) - (file2.duration || 0)) < 0.01
    );
  };

  // Check if all files in a group are exact duplicates
  const areAllExactDuplicates = (groupFiles: typeof files): boolean => {
    if (groupFiles.length <= 1) return false;
    const first = groupFiles[0];
    return groupFiles.every((file) => isExactDuplicate(file, first));
  };

  // Group files by phash and matching scenes
  const groupedFiles = useMemo(() => {
    const groups: FileGroup[] = [];
    const processedPaths = new Set<string>();

    // First, group files that have matching_scenes (duplicates between Download and library)
    const filesWithMatchingScenes = files.filter((f) => f.matching_scenes && f.matching_scenes.length > 0);
    const filesWithoutMatchingScenes = files.filter((f) => !f.matching_scenes || f.matching_scenes.length === 0);

    // Group files with matching scenes by phash
    const matchingScenesGroups = new Map<string, typeof files>();
    filesWithMatchingScenes.forEach((file) => {
      if (processedPaths.has(file.path)) return;
      const phash = file.phash;
      if (!matchingScenesGroups.has(phash)) {
        matchingScenesGroups.set(phash, []);
      }
      matchingScenesGroups.get(phash)!.push(file);
      processedPaths.add(file.path);
    });

    // Convert matching scenes groups to FileGroup objects
    matchingScenesGroups.forEach((groupFiles, phash) => {
      const qualityComparison = checkQualityComparison(groupFiles);
      if (groupFiles.length > 1) {
        groups.push({
          phash,
          files: groupFiles,
          isExactDuplicate: areAllExactDuplicates(groupFiles),
          hasMatchingScenes: true,
          hasBetterQuality: qualityComparison.better,
          hasWorseQuality: qualityComparison.worse,
          hasSameQuality: qualityComparison.same,
        });
      } else {
        // Single file with matching scenes - add as individual
        groups.push({
          phash,
          files: groupFiles,
          isExactDuplicate: false,
          hasMatchingScenes: true,
          hasBetterQuality: qualityComparison.better,
          hasWorseQuality: qualityComparison.worse,
          hasSameQuality: qualityComparison.same,
        });
      }
    });

    // Then, group remaining files (without matching scenes) by phash (duplicates only in Download)
    const downloadOnlyGroups = new Map<string, typeof files>();
    filesWithoutMatchingScenes.forEach((file) => {
      if (processedPaths.has(file.path)) return;
      const phash = file.phash;
      if (!downloadOnlyGroups.has(phash)) {
        downloadOnlyGroups.set(phash, []);
      }
      downloadOnlyGroups.get(phash)!.push(file);
      processedPaths.add(file.path);
    });

    // Convert download-only groups to FileGroup objects (only if more than one file)
    downloadOnlyGroups.forEach((groupFiles, phash) => {
      if (groupFiles.length > 1) {
        groups.push({
          phash,
          files: groupFiles,
          isExactDuplicate: areAllExactDuplicates(groupFiles),
          hasMatchingScenes: false,
          hasBetterQuality: false,
          hasWorseQuality: false,
          hasSameQuality: false,
        });
      }
    });

    // Add remaining unprocessed files as individual items
    files.forEach((file) => {
      if (!processedPaths.has(file.path)) {
        groups.push({
          phash: file.phash,
          files: [file],
          isExactDuplicate: false,
          hasMatchingScenes: false,
          hasBetterQuality: false,
          hasWorseQuality: false,
          hasSameQuality: false,
        });
      }
    });

    return groups;
  }, [files]);

  const setQuery = (q: Record<string, string | number | undefined>) => {
    const newQuery = new URLSearchParams(query);
    for (const key of Object.keys(q)) {
      const value = q[key];
      if (value !== undefined) {
        newQuery.set(key, String(value));
      } else {
        newQuery.delete(key);
      }
    }
    history.push({ search: newQuery.toString() });
  };

  const handleCheck = (checked: boolean, path: string) => {
    setCheckedFiles({ ...checkedFiles, [path]: checked });
  };

  const handleDeleteChecked = async () => {
    const pathsToDelete = Object.keys(checkedFiles).filter(
      (path) => checkedFiles[path]
    );

    if (pathsToDelete.length === 0) {
      return;
    }

    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: `${pathsToDelete.length} file${pathsToDelete.length > 1 ? "s" : ""}` }
        )
      )
    ) {
      return;
    }

    setDeleting(true);
    try {
      await deleteDuplicateFiles({
        variables: { paths: pathsToDelete },
      });

      // Wait a bit for backend to save changes
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Refetch to update the list
      await refetch();
      setCheckedFiles({});
    } catch (error) {
      console.error("Error deleting files:", error);
    } finally {
      setDeleting(false);
    }
  };

  const [destroyScenes] = GQL.useScenesDestroyMutation();

  const handleDeleteSingle = async (path: string) => {
    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: "this file" }
        )
      )
    ) {
      return;
    }

    setDeleting(true);
    try {
      await deleteDuplicateFiles({
        variables: { paths: [path] },
      });

      // Wait a bit for backend to save changes
      await new Promise(resolve => setTimeout(resolve, 500));
      
      await refetch();
    } catch (error) {
      console.error("Error deleting file:", error);
    } finally {
      setDeleting(false);
    }
  };

  const handleReplaceOriginal = async (scene: any, duplicatePath: string) => {
    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: "Zamień plik w bibliotece tym nowym?" }
        )
      )
    ) {
      return;
    }

    setDeleting(true);
    try {
      const replaceResult = await replaceDuplicateWithScene({
        variables: {
          sceneId: scene.id,
          duplicatePath,
        },
      });

      // replaceDuplicateWithScene now returns job ID - monitor it first
      const replaceJobId = replaceResult.data?.replaceDuplicateWithScene;
      if (!replaceJobId) {
        console.warn("No job ID returned from replaceDuplicateWithScene");
        setDeleting(false);
        return;
      }

      console.log("ReplaceDuplicateWithScene job started:", replaceJobId, "for scene:", scene.id);
      
      // Store replace job ID to show spinner
      setReplaceJobIds(prev => ({
        ...prev,
        [`replace_${scene.id}`]: replaceJobId,
      }));
      
      // Monitor the replace job, and when it finishes, start metadata scan
      const checkReplaceJobStatus = async () => {
        try {
          const jobResult = await findJob({
            variables: { input: { id: replaceJobId } },
            fetchPolicy: "network-only",
          });
          
          const job = jobResult.data?.findJob;
          if (!job) {
            // Job not found, might have finished already
            console.log("Replace job not found, assuming finished");
            // Remove replace job ID
            setReplaceJobIds(prev => {
              const newMap = { ...prev };
              delete newMap[`replace_${scene.id}`];
              return newMap;
            });
            startMetadataScan(scene, duplicatePath);
            return;
          }
          
          if (job.status === GQL.JobStatus.Finished) {
            console.log("Replace job finished successfully, starting metadata scan");
            // Remove replace job ID
            setReplaceJobIds(prev => {
              const newMap = { ...prev };
              delete newMap[`replace_${scene.id}`];
              return newMap;
            });
            startMetadataScan(scene, duplicatePath);
          } else if (job.status === GQL.JobStatus.Failed || job.status === GQL.JobStatus.Cancelled) {
            console.error("Replace job failed or cancelled:", job.status, job.error);
            // Remove replace job ID
            setReplaceJobIds(prev => {
              const newMap = { ...prev };
              delete newMap[`replace_${scene.id}`];
              return newMap;
            });
            setDeleting(false);
            alert(`Replace job failed: ${job.error || job.status}`);
          } else {
            // Job still running, check again in 2 seconds
            setTimeout(checkReplaceJobStatus, 2000);
          }
        } catch (error) {
          console.error("Error checking replace job status:", error);
          // Remove replace job ID on error
          setReplaceJobIds(prev => {
            const newMap = { ...prev };
            delete newMap[`replace_${scene.id}`];
            return newMap;
          });
          setDeleting(false);
        }
      };
      
      // Start checking job status
      setTimeout(checkReplaceJobStatus, 1000);
      
    } catch (error) {
      console.error("Error replacing original scene file with duplicate:", error);
      setDeleting(false);
    }
  };
  
  const startMetadataScan = async (scene: any, filePath: string) => {
    try {
      // After replace, the file is now at the library path, not duplicatePath
      // We need to use the library path (scene.path) for metadata scan
      const scanPath = scene.path || filePath;
      console.log("Starting metadata scan for replaced file:", scanPath);
      const result = await metadataScan({
        variables: {
          input: {
            paths: [scanPath],
            rescan: true,
            scanGeneratePhashes: true,
          },
        },
      });
      
      // Start monitoring the metadata scan job for this specific scene
      if (result.data?.metadataScan) {
        console.log("Metadata scan job started:", result.data.metadataScan, "for scene:", scene.id);
        setReplaceJobIds(prev => ({
          ...prev,
          [scene.id]: result.data!.metadataScan,
        }));
      } else {
        console.warn("No job ID returned from metadata scan");
        // If no job ID returned, just refresh immediately
        await refetch({
          variables: { scanId: scanId! },
          fetchPolicy: "network-only",
        });
        setDeleting(false);
      }
    } catch (error) {
      console.error("Error starting metadata scan:", error);
      setDeleting(false);
    }
  };

  const handleDeleteOriginal = async (sceneId: string) => {
    if (
      !confirm(
        intl.formatMessage(
          { id: "dialogs.delete_confirm" },
          { entityName: intl.formatMessage({ id: "scene" }) }
        )
      )
    ) {
      return;
    }

    setDeleting(true);
    try {
      await destroyScenes({
        variables: {
          ids: [sceneId],
          delete_file: true,
          delete_generated: true,
        },
      });

      // Wait a bit for backend to apply changes
      await new Promise((resolve) => setTimeout(resolve, 500));

      // Refetch scan result to update the report
      await refetch();
    } catch (error) {
      console.error("Error deleting original scene:", error);
    } finally {
      setDeleting(false);
    }
  };

  const pageOptions = useMemo(() => {
    const pageSizes = [10, 20, 30, 40, 50, 100, 150, 200, 250, 500];

    const filteredSizes = pageSizes.filter((s, i) => {
      return groupedFiles.length > s || i == 0 || groupedFiles.length > pageSizes[i - 1];
    });

    return filteredSizes.map((size) => {
      return (
        <option key={size} value={size}>
          {size}
        </option>
      );
    });
  }, [groupedFiles.length]);

  const filteredGroups = groupedFiles.slice(
    (currentPage - 1) * currentPageSize,
    currentPage * currentPageSize
  );
  const checkCount = Object.keys(checkedFiles).filter(
    (path) => checkedFiles[path]
  ).length;

  // Handler for deleting all files in a group except one
  const handleDeleteGroupExceptOne = async (group: FileGroup, keepIndex: number = 0) => {
    const filesToDelete = group.files.filter((_, index) => index !== keepIndex);
    const pathsToDelete = filesToDelete.map((f) => f.path);

    if (pathsToDelete.length === 0) {
      return;
    }

    if (
      !confirm(
        intl.formatMessage(
          { id: "directory_duplicate_checker.delete_group_confirm" },
          { count: pathsToDelete.length }
        )
      )
    ) {
      return;
    }

    setDeleting(true);
    try {
      await deleteDuplicateFiles({
        variables: { paths: pathsToDelete },
      });

      // Wait a bit for backend to save changes
      await new Promise((resolve) => setTimeout(resolve, 500));

      // Refetch to update the list
      await refetch();
      setCheckedFiles({});
    } catch (error) {
      console.error("Error deleting files:", error);
    } finally {
      setDeleting(false);
    }
  };

  // Handler for playing video file
  const handlePlayFile = (filePath: string) => {
    const streamUrl = getPlatformURL("file/stream");
    streamUrl.searchParams.set("path", filePath);
    window.open(streamUrl.toString(), "_blank");
  };

  if (loading) {
    return <LoadingIndicator />;
  }

  if (error) {
    return <ErrorMessage error={error.message} />;
  }

  if (!scanResult) {
    return <ErrorMessage error="Scan result not found" />;
  }

  return (
    <div className={CLASSNAME}>
      <div className="container-fluid">
        <Row className="mb-3">
          <Col>
            <Button variant="secondary" onClick={() => history.push("/directoryDuplicateChecker")}>
              <Icon icon={faArrowLeft} />
              <FormattedMessage id="actions.back" />
            </Button>
          </Col>
        </Row>

        <Row>
          <Col>
            <h1>
              <FormattedMessage id="directory_duplicate_checker.scan_report" />
            </h1>
            <h5>
              <FormattedMessage
                id="directory_duplicate_checker.directory"
                values={{ directory: scanResult.directory_path }}
              />
            </h5>
          </Col>
        </Row>

        <Row className="mb-4">
          <Col>
            <Card>
              <Card.Body>
                <Row>
                  <Col>
                    <FormattedMessage id="directory_duplicate_checker.stats.total_scanned" />
                    : <FormattedNumber value={scanResult.total_scanned} />
                  </Col>
                  <Col>
                    <FormattedMessage id="directory_duplicate_checker.stats.duplicates_found" />
                    : <FormattedNumber value={scanResult.duplicates_found} />
                  </Col>
                </Row>
              </Card.Body>
            </Card>
          </Col>
        </Row>

        {files.length > 0 && (
          <>
            <Row className="mb-2">
              <Col>
                <Button
                  variant="danger"
                  disabled={checkCount === 0 || deleting}
                  onClick={handleDeleteChecked}
                >
                  <Icon icon={faTrash} />
                  <FormattedMessage id="actions.delete" />
                  {checkCount > 0 && ` (${checkCount})`}
                </Button>
              </Col>
              <Col md="auto">
                <Form.Control
                  as="select"
                  className="btn-secondary"
                  value={currentPageSize}
                  onChange={(e) => {
                    setCurrentPageSize(Number.parseInt(e.currentTarget.value, 10));
                    setQuery({ size: e.currentTarget.value, page: 1 });
                  }}
                >
                  {pageOptions}
                </Form.Control>
              </Col>
            </Row>

            <Accordion>
              {filteredGroups.map((group, groupIndex) => {
                const eventKey = `group-${groupIndex}`;
                const isGroup = group.files.length > 1;
                
                const renderFileCard = (file: typeof group.files[0], fileIndex: number) => (
                            <Card key={file.path} className="file-card mb-3">
                              <Card.Body>
                                <Row>
                                  <Col xs={12} md={6}>
                                    <div className="mb-2">
                                      <strong>
                                        <FormattedMessage id="directory_duplicate_checker.file_path" />
                                      </strong>
                                      <div className="text-break" title={file.path}>
                                        {file.path}
                                      </div>
                                    </div>
                                  </Col>
                                  <Col xs={12} md={6}>
                                    <div className="mb-2">
                                      <Button
                                        variant="primary"
                                        size="sm"
                                        className="mr-2"
                                        onClick={() => handlePlayFile(file.path)}
                                      >
                                        <Icon icon={faPlay} />
                                        <FormattedMessage id="directory_duplicate_checker.play_file" />
                                      </Button>
                                      <Form.Check
                                        inline
                                        checked={checkedFiles[file.path] || false}
                                        onChange={(e) =>
                                          handleCheck(e.currentTarget.checked, file.path)
                                        }
                                      />
                                      <Button
                                        variant="danger"
                                        size="sm"
                                        className="ml-2"
                                        disabled={deleting}
                                        onClick={() => handleDeleteSingle(file.path)}
                                      >
                                        <Icon icon={faTrash} />{" "}
                                        <span>Usuń nowy</span>
                                      </Button>
                                    </div>
                                  </Col>
                                </Row>
                                <Row>
                                  <Col xs={6} md={3}>
                                    <div className="mb-2">
                                      <strong>
                                        <FormattedMessage id="directory_duplicate_checker.resolution" />
                                      </strong>
                                      <div>
                                        {file.width > 0 && file.height > 0
                                          ? `${file.width}x${file.height}`
                                          : "-"}
                                      </div>
                                    </div>
                                  </Col>
                                  <Col xs={6} md={3}>
                                    <div className="mb-2">
                                      <strong>
                                        <FormattedMessage id="filesize" />
                                      </strong>
                                      <div>
                                        <FileSize size={file.file_size} />
                                      </div>
                                    </div>
                                  </Col>
                                  <Col xs={6} md={3}>
                                    <div className="mb-2">
                                      <strong>
                                        <FormattedMessage id="duration" />
                                      </strong>
                                      <div>
                                        {file.duration > 0
                                          ? TextUtils.secondsToTimestamp(file.duration)
                                          : "-"}
                                      </div>
                                    </div>
                                  </Col>
                                  <Col xs={6} md={3}>
                                    <div className="mb-2">
                                      <strong>
                                        <FormattedMessage id="phash" />
                                      </strong>
                                      <div>
                                        <code>{file.phash}</code>
                                      </div>
                                    </div>
                                  </Col>
                                </Row>
                                {file.matching_scenes && file.matching_scenes.length > 0 && (
                                  <>
                                    {file.matching_scenes.map((scene, sceneIndex) => (
                                      <React.Fragment key={scene.id || sceneIndex}>
                                        <Row className="mt-3">
                                          <Col xs={12}>
                                            <div className="mb-2 border-top pt-2">
                                              <strong>
                                                <FormattedMessage id="directory_duplicate_checker.matching_scene" />
                                                {file.matching_scenes.length > 1 && ` #${sceneIndex + 1}`}
                                              </strong>
                                            </div>
                                          </Col>
                                        </Row>
                                        <Row>
                                          <Col xs={12} md={6}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="title" />
                                              </strong>
                                              <div>
                                                {scene.title}
                                              </div>
                                            </div>
                                          </Col>
                                          <Col xs={12} md={6}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="path" />
                                              </strong>
                                              <div className="text-break" title={scene.path}>
                                                {scene.path}
                                              </div>
                                            </div>
                                          </Col>
                                        </Row>
                                        <Row>
                                          <Col xs={6} md={3}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="directory_duplicate_checker.resolution" />
                                              </strong>
                                              <div>
                                                {scene.width > 0 && scene.height > 0
                                                  ? `${scene.width}x${scene.height}`
                                                  : "-"}
                                              </div>
                                            </div>
                                          </Col>
                                          <Col xs={6} md={3}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="filesize" />
                                              </strong>
                                              <div>
                                                <FileSize size={scene.file_size} />
                                              </div>
                                            </div>
                                          </Col>
                                          <Col xs={6} md={3}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="duration" />
                                              </strong>
                                              <div>
                                                {scene.duration && scene.duration > 0
                                                  ? TextUtils.secondsToTimestamp(scene.duration)
                                                  : "-"}
                                              </div>
                                            </div>
                                          </Col>
                                          <Col xs={6} md={3}>
                                            <div className="mb-2">
                                              <strong>
                                                <FormattedMessage id="phash" />
                                              </strong>
                                              <div>
                                                <code>{scene.phash || "-"}</code>
                                              </div>
                                            </div>
                                          </Col>
                                        </Row>
                                        <Row>
                                          <Col xs={12}>
                                            <div className="mb-2">
                                              <a
                                                href={`/scenes/${scene.id}`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="mr-2"
                                              >
                                                <FormattedMessage id="directory_duplicate_checker.view_scene" />
                                              </a>
                                              <Button
                                                variant="outline-primary"
                                                size="sm"
                                                className="ml-2"
                                                disabled={deleting || !!replaceJobIds[scene.id] || !!replaceJobIds[`replace_${scene.id}`]}
                                                onClick={() => handleReplaceOriginal(scene, file.path)}
                                              >
                                                {replaceJobIds[scene.id] || replaceJobIds[`replace_${scene.id}`] ? (
                                                  <>
                                                    <Spinner animation="border" size="sm" className="mr-1" />
                                                    Zamienianie...
                                                  </>
                                                ) : (
                                                  "Zamień"
                                                )}
                                              </Button>
                                              <Button
                                                variant="outline-danger"
                                                size="sm"
                                                disabled={deleting}
                                                className="ml-2"
                                                onClick={() => handleDeleteOriginal(scene.id)}
                                              >
                                                Usuń Oryginał
                                              </Button>
                                            </div>
                                          </Col>
                                        </Row>
                                      </React.Fragment>
                                    ))}
                                  </>
                                )}
                              </Card.Body>
                            </Card>
                );
                
                return (
                  <Card key={eventKey} className="file-group-card">
                    {isGroup ? (
                      <>
                        <Accordion.Toggle as={Card.Header} eventKey={eventKey}>
                          <div className="d-flex align-items-center justify-content-between">
                            <div className="d-flex align-items-center">
                              {(() => {
                                // Check if any scene in this group is being replaced
                                const isReplacing = group.files.some(file => 
                                  file.matching_scenes?.some(scene => 
                                    replaceJobIds[scene.id] || replaceJobIds[`replace_${scene.id}`]
                                  )
                                );
                                
                                if (isReplacing) {
                                  return (
                                    <Spinner animation="border" size="sm" className="mr-2" role="status">
                                      <span className="sr-only">Replacing...</span>
                                    </Spinner>
                                  );
                                }
                                
                                // Show quality indicators
                                if (group.isExactDuplicate) {
                                  return (
                                    <Icon icon={faEquals} className="mr-2 text-success" title={intl.formatMessage({ id: "directory_duplicate_checker.exact_duplicate" })} />
                                  );
                                }
                                if (group.hasBetterQuality) {
                                  return (
                                    <Icon icon={faArrowUp} className="mr-2 text-success" title={intl.formatMessage({ id: "directory_duplicate_checker.better_quality" })} />
                                  );
                                }
                                if (group.hasWorseQuality) {
                                  return (
                                    <Icon icon={faArrowDown} className="mr-2 text-warning" title={intl.formatMessage({ id: "directory_duplicate_checker.worse_quality" })} />
                                  );
                                }
                                if (group.hasSameQuality) {
                                  return (
                                    <Icon icon={faEquals} className="mr-2 text-info" title={intl.formatMessage({ id: "directory_duplicate_checker.same_quality" })} />
                                  );
                                }
                                return null;
                              })()}
                              <span className="mr-2">
                                <code>{group.phash}</code>
                              </span>
                              <span className="text-muted">
                                <FormattedMessage
                                  id="directory_duplicate_checker.files_in_group"
                                  values={{ count: group.files.length }}
                                />
                              </span>
                            </div>
                            <Button
                              variant="danger"
                              size="sm"
                              disabled={deleting}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteGroupExceptOne(group);
                              }}
                            >
                              <Icon icon={faTrash} />
                              <FormattedMessage id="directory_duplicate_checker.delete_all_except_one" />
                            </Button>
                          </div>
                        </Accordion.Toggle>
                        <Accordion.Collapse eventKey={eventKey}>
                          <Card.Body>
                            <div className="file-group-files">
                              {group.files.map((file, fileIndex) => renderFileCard(file, fileIndex))}
                            </div>
                          </Card.Body>
                        </Accordion.Collapse>
                      </>
                    ) : (
                      <Card.Body>
                        <div className="d-flex align-items-center mb-2">
                          {(() => {
                            // Check if any scene in this group is being replaced
                            const isReplacing = group.files.some(file => 
                              file.matching_scenes?.some(scene => 
                                replaceJobIds[scene.id] || replaceJobIds[`replace_${scene.id}`]
                              )
                            );
                            
                            if (isReplacing) {
                              return (
                                <>
                                  <Spinner animation="border" size="sm" className="mr-2" role="status">
                                    <span className="sr-only">Replacing...</span>
                                  </Spinner>
                                  <span className="mr-2">
                                    <code>{group.phash}</code>
                                  </span>
                                </>
                              );
                            }
                            
                            // Show quality indicators
                            return (
                              <>
                                {group.isExactDuplicate && (
                                  <Icon icon={faEquals} className="mr-2 text-success" title={intl.formatMessage({ id: "directory_duplicate_checker.exact_duplicate" })} />
                                )}
                                {group.hasBetterQuality && (
                                  <Icon icon={faArrowUp} className="mr-2 text-success" title={intl.formatMessage({ id: "directory_duplicate_checker.better_quality" })} />
                                )}
                                {group.hasWorseQuality && (
                                  <Icon icon={faArrowDown} className="mr-2 text-warning" title={intl.formatMessage({ id: "directory_duplicate_checker.worse_quality" })} />
                                )}
                                {group.hasSameQuality && !group.isExactDuplicate && (
                                  <Icon icon={faEquals} className="mr-2 text-info" title={intl.formatMessage({ id: "directory_duplicate_checker.same_quality" })} />
                                )}
                                <span className="mr-2">
                                  <code>{group.phash}</code>
                                </span>
                              </>
                            );
                          })()}
                        </div>
                        {group.files.map((file, fileIndex) => renderFileCard(file, fileIndex))}
                      </Card.Body>
                    )}
                  </Card>
                );
              })}
            </Accordion>

            <Pagination
              itemsPerPage={currentPageSize}
              currentPage={currentPage}
              totalItems={groupedFiles.length}
              onChangePage={(page) => setQuery({ page })}
            />
          </>
        )}

        {files.length === 0 && (
          <Row>
            <Col>
              <Card>
                <Card.Body>
                  <FormattedMessage id="directory_duplicate_checker.no_duplicates" />
                </Card.Body>
              </Card>
            </Col>
          </Row>
        )}
      </div>
    </div>
  );
};

export default ScanReport;

