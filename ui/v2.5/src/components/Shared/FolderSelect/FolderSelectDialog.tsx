import React, { useState, useEffect } from "react";
import { FormattedMessage } from "react-intl";
import { Button, Modal } from "react-bootstrap";
import { useLocation } from "react-router-dom";
import { FolderSelect } from "./FolderSelect";

interface IProps {
  defaultValue?: string;
  onClose: (directory?: string) => void;
  show?: boolean;
  allowOnDirectoryDuplicateChecker?: boolean; // If false, dialog won't render on /directoryDuplicateChecker
}


export const FolderSelectDialog: React.FC<IProps> = ({
  defaultValue: currentValue,
  onClose,
  show = false,
  allowOnDirectoryDuplicateChecker = true, // Default to true for backward compatibility
}) => {
  const location = useLocation();
  const [currentDirectory, setCurrentDirectory] = useState<string>(
    currentValue ?? ""
  );

  const shouldShowModal = show && 
    (location.pathname === "/settings" || location.pathname === "/setup" || 
     (location.pathname.startsWith("/directoryDuplicateChecker") && allowOnDirectoryDuplicateChecker));
  
  // CRITICAL: Don't render Modal at all if it shouldn't be visible
  // This prevents Modal from staying visible through Portal after navigation
  if (!shouldShowModal) {
    return null;
  }
  
  // CRITICAL: Don't render if show is false - check this FIRST before any other logic
  if (!show) {
    return null;
  }
  
  // CRITICAL: If allowOnDirectoryDuplicateChecker is false, NEVER render on /directoryDuplicateChecker
  // This prevents dialog from SettingsToolsPanel from appearing on DirectoryDuplicateChecker page
  // Check this BEFORE any other location checks
  if (!allowOnDirectoryDuplicateChecker && location.pathname.startsWith("/directoryDuplicateChecker")) {
    return null;
  }
  
  // CRITICAL: If we're not on /settings, /setup, or /directoryDuplicateChecker, don't render at all
  if (location.pathname !== "/settings" && 
      location.pathname !== "/setup" && 
      !location.pathname.startsWith("/directoryDuplicateChecker")) {
    return null;
  }

  // CRITICAL: Force close Modal if location changes and dialog shouldn't be visible
  // This prevents Modal from staying visible through Portal after navigation
  useEffect(() => {
    const shouldBeVisible = show && 
      (location.pathname === "/settings" || location.pathname === "/setup" || 
       (location.pathname.startsWith("/directoryDuplicateChecker") && allowOnDirectoryDuplicateChecker));
    
    if (!shouldBeVisible && show) {
      onClose();
    }
  }, [location.pathname, show, allowOnDirectoryDuplicateChecker, onClose]);

  // Don't render if we're not on allowed page
  const isAllowedPage = location.pathname === "/settings" || 
                       location.pathname === "/setup" || 
                       location.pathname.startsWith("/directoryDuplicateChecker");
  
  // Don't render if we're not on an allowed page (show is already checked above)
  if (!isAllowedPage) {
    return null;
  }

  return (
    <Modal
      key={`folder-select-modal-${location.pathname}-${
        shouldShowModal ? "show" : "hide"
      }-${allowOnDirectoryDuplicateChecker ? "allow" : "block"}`}
      show={shouldShowModal}
      onHide={() => onClose()}
      title=""
      backdrop
      keyboard
    >
      <Modal.Header>
        <FormattedMessage id="actions.select_directory" />
      </Modal.Header>
      <Modal.Body>
        <div className="dialog-content">
          <FolderSelect
            currentDirectory={currentDirectory}
            onChangeDirectory={setCurrentDirectory}
          />
        </div>
      </Modal.Body>
      <Modal.Footer>
        <Button variant="secondary" onClick={() => onClose()}>
          <FormattedMessage id="actions.cancel" />
        </Button>
        <Button
          variant="success"
          onClick={() => onClose(currentDirectory)}
        >
          <FormattedMessage id="actions.confirm" />
        </Button>
      </Modal.Footer>
    </Modal>
  );
};
