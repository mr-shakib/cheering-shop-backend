/* Uploads go straight to object storage: ask the API for a presigned PUT,
 * send the bytes there, and keep the returned public_url. The PUT must carry
 * exactly the headers the API signed, Content-Type included. */
import { ApiError, post } from "./api";

interface PresignedUpload {
  upload_url: string;
  public_url: string;
  key: string;
  method: string;
  headers: Record<string, string>;
}

export const ACCEPT = {
  image: "image/jpeg,image/png,image/webp",
  imageOrGif: "image/jpeg,image/png,image/webp,image/gif",
  document: "image/jpeg,image/png,image/webp,application/pdf",
  video: "video/mp4,video/quicktime,video/webm",
  banner: "image/jpeg,image/png,image/webp,image/gif,application/json,.json",
} as const;

export async function uploadFile(file: File, onProgress?: (fraction: number) => void): Promise<string> {
  // Browsers report Lottie files as "" or "application/json" depending on the OS.
  const fileType = file.type || (file.name.endsWith(".json") ? "application/json" : "application/octet-stream");
  const presigned = await post<PresignedUpload>("/admin/uploads/presigned-url", {
    file_type: fileType,
    file_name: file.name,
  });

  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(presigned.method || "PUT", presigned.upload_url);
    for (const [k, v] of Object.entries(presigned.headers)) xhr.setRequestHeader(k, v);
    if (!Object.keys(presigned.headers).some((k) => k.toLowerCase() === "content-type")) {
      xhr.setRequestHeader("Content-Type", fileType);
    }
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new ApiError(xhr.status, "UPLOAD_FAILED", `The storage server refused the upload (HTTP ${xhr.status}).`));
    xhr.onerror = () =>
      reject(
        new ApiError(
          0,
          "UPLOAD_FAILED",
          "Could not reach the storage server. Check the bucket's CORS rules allow this origin.",
        ),
      );
    xhr.send(file);
  });

  return presigned.public_url;
}
