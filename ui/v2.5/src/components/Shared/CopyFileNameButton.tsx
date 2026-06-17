import React from "react";
import { Button } from "react-bootstrap";
import { faCopy } from "@fortawesome/free-solid-svg-icons";
import { useIntl } from "react-intl";
import { Icon } from "./Icon";
import { useToast } from "src/hooks/Toast";
import TextUtils from "src/utils/text";

interface ICopyFileNameButtonProps {
  path: string;
}

export const CopyFileNameButton: React.FC<ICopyFileNameButtonProps> = ({
  path,
}) => {
  const intl = useIntl();
  const Toast = useToast();

  async function onClick() {
    const filename = TextUtils.fileBaseNameFromPath(path);

    if (!navigator.clipboard) {
      Toast.error(
        intl.formatMessage({ id: "toast.clipboard_access_denied" })
      );
      return;
    }

    try {
      await navigator.clipboard.writeText(filename);
      Toast.success(intl.formatMessage({ id: "toast.filename_copied" }));
    } catch {
      Toast.error(
        intl.formatMessage({ id: "toast.clipboard_access_denied" })
      );
    }
  }

  return (
    <Button
      className="minimal reveal-in-filesystem-button"
      title={intl.formatMessage({ id: "actions.copy_filename" })}
      onClick={onClick}
    >
      <Icon icon={faCopy} />
    </Button>
  );
};
