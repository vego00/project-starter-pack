import { useEffect, useState } from "react";
import { ApiError, getPackageFiles, packageUrl } from "./api";
import type { PackageFile } from "./api";

// The build bundle shown as files: a list on the left, the chosen file's text on the right.
// Read-only; the zip download stays the way to take it away.
export function PackageFiles({ journeyId }: { journeyId: string }) {
  const [files, setFiles] = useState<PackageFile[] | null>(null);
  const [failure, setFailure] = useState("");
  const [open, setOpen] = useState("BUILD.md");

  useEffect(() => {
    let live = true;
    setFiles(null);
    setFailure("");
    getPackageFiles(journeyId)
      .then((loaded) => live && setFiles(loaded))
      .catch(
        (error: unknown) =>
          live &&
          setFailure(
            error instanceof ApiError
              ? error.message
              : "빌드 묶음을 불러오지 못했어요.",
          ),
      );
    return () => {
      live = false;
    };
  }, [journeyId]);

  if (failure)
    return (
      <p className="alert" role="alert">
        {failure}
      </p>
    );
  if (files === null)
    return <p className="package-loading muted">빌드 묶음을 불러오는 중…</p>;

  const shown = files.find((file) => file.path === open) ?? files[0];
  return (
    <div className="package-files">
      <nav aria-label="빌드 묶음 파일">
        {files.map((file) => (
          <button
            key={file.path}
            className={`quiet${file === shown ? " on" : ""}`}
            aria-current={file === shown ? "true" : undefined}
            style={{ paddingLeft: 8 + 12 * file.path.split("/").length - 12 }}
            title={file.path}
            onClick={() => setOpen(file.path)}
          >
            {file.path}
          </button>
        ))}
        <a className="button quiet" href={packageUrl(journeyId)} download>
          전체 다운로드
        </a>
      </nav>
      {shown && (
        <section aria-label={shown.path}>
          <h3>{shown.path}</h3>
          <pre>{shown.content}</pre>
        </section>
      )}
    </div>
  );
}
