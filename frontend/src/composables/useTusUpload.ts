import * as tus from "tus-js-client";
import { ref } from "vue";

export interface TusProgress {
  bytesUploaded: number;
  bytesTotal: number;
  percent: number;
}

export interface UseTusUpload {
  uploading: ReturnType<typeof ref<boolean>>;
  progress: ReturnType<typeof ref<TusProgress>>;
  error: ReturnType<typeof ref<string | null>>;
  upload: (file: File, uploadUrl: string) => Promise<void>;
  abort: () => void;
}

export function useTusUpload(): UseTusUpload {
  const uploading = ref(false);
  const progress = ref<TusProgress>({ bytesUploaded: 0, bytesTotal: 0, percent: 0 });
  const error = ref<string | null>(null);

  let current: tus.Upload | null = null;

  function upload(file: File, uploadUrl: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      uploading.value = true;
      error.value = null;
      progress.value = { bytesUploaded: 0, bytesTotal: file.size, percent: 0 };

      // The backend pre-creates the upload resource and returns its URL in
      // POST /api/transfers, so we pass `uploadUrl` (resume-existing) and
      // intentionally OMIT `endpoint` (create-new). Setting both caused
      // tus-js-client to POST a creation request against an already-created
      // resource on the first retry after a network blip → 405/409.
      const up = new tus.Upload(file, {
        uploadUrl,
        chunkSize: 5 * 1024 * 1024,
        retryDelays: [0, 1000, 3000, 5000],
        metadata: {
          filename: file.name,
          filetype: file.type || "application/octet-stream",
        },
        onError(err: Error) {
          error.value = err.message;
          uploading.value = false;
          current = null;
          reject(err);
        },
        onProgress(bytesUploaded: number, bytesTotal: number) {
          const percent = bytesTotal > 0 ? (bytesUploaded / bytesTotal) * 100 : 0;
          progress.value = { bytesUploaded, bytesTotal, percent };
        },
        onSuccess() {
          uploading.value = false;
          current = null;
          resolve();
        },
      });
      current = up;
      up.start();
    });
  }

  function abort(): void {
    if (current) {
      void current.abort(true);
      current = null;
      uploading.value = false;
    }
  }

  return { uploading, progress, error, upload, abort };
}
