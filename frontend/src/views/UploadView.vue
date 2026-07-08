<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { createTransfer } from "@/api/transfers";
import { ApiError } from "@/api/client";
import type { FileDescriptor } from "@/api/types";
import ChipInput from "@/components/ChipInput.vue";
import FileDropZone from "@/components/FileDropZone.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import { useTusUpload } from "@/composables/useTusUpload";

const router = useRouter();

const files = ref<File[]>([]);
const senderEmail = ref("");
const senderEmailTouched = ref(false);
const recipientEmails = ref<string[]>([]);
const message = ref("");
const ttlDays = ref(7);
const submitError = ref<string | null>(null);
// Per-file status during `submit()`. Key = `${name}:${size}` for dedup;
// value = "pending" (not yet started), "uploading", "done", or an error
// string. A per-file failure sets the status but does not abort remaining
// files — after the loop we check if any failed and keep the user on the
// form (with submitError) instead of navigating to the success page.
const fileStatus = ref<Record<string, string>>({});
function fileKey(f: File): string {
  return `${f.name}:${f.size}`;
}
function statusOf(f: File): string {
  return fileStatus.value[fileKey(f)] ?? "pending";
}

const { uploading, progress, upload } = useTusUpload();

const MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB — backend default

const totalBytes = computed(() => files.value.reduce((sum, f) => sum + f.size, 0));
const overLimit = computed(() => totalBytes.value > MAX_TOTAL_BYTES);
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function isValidEmail(v: string): boolean {
  return emailRegex.test(v);
}

const senderEmailError = computed<string | null>(() => {
  if (!senderEmailTouched.value) return null;
  if (!senderEmail.value.trim()) return "required";
  if (!emailRegex.test(senderEmail.value.trim())) return "invalid";
  return null;
});

const canSubmit = computed(() => {
  if (uploading.value) return false;
  if (files.value.length === 0) return false;
  if (overLimit.value) return false;
  if (!emailRegex.test(senderEmail.value)) return false;
  if (recipientEmails.value.length === 0) return false;
  return true;
});

// Track aggregate progress across multiple files.
const completedBytes = ref(0);
const aggregatePercent = computed(() => {
  if (totalBytes.value === 0) return 0;
  const current = uploading.value ? progress.value?.bytesUploaded ?? 0 : 0;
  return ((completedBytes.value + current) / totalBytes.value) * 100;
});

function addFiles(newFiles: File[]): void {
  for (const f of newFiles) {
    // de-dup by name + size
    if (!files.value.some((e) => e.name === f.name && e.size === f.size)) {
      files.value.push(f);
    }
  }
}

function removeFile(i: number): void {
  files.value.splice(i, 1);
}

function formatSize(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[u]}`;
}

async function submit(): Promise<void> {
  senderEmailTouched.value = true;
  if (!canSubmit.value) return;
  submitError.value = null;
  completedBytes.value = 0;

  const body = {
    sender_email: senderEmail.value.trim(),
    recipient_emails: recipientEmails.value,
    message: message.value.trim() || null,
    ttl_days: ttlDays.value,
    files: files.value.map<FileDescriptor>((f) => ({
      filename: f.name,
      size: f.size,
    })),
  };

  // Reset per-file status — every file starts fresh at "pending".
  fileStatus.value = Object.fromEntries(files.value.map((f) => [fileKey(f), "pending"]));

  let resp;
  try {
    resp = await createTransfer(body);
  } catch (e) {
    if (e instanceof ApiError) {
      submitError.value = `${e.status}: ${e.message}`;
    } else if (e instanceof Error) {
      submitError.value = e.message;
    } else {
      submitError.value = "Unknown error";
    }
    return;
  }

  // Per-file upload loop. A failure on one file does NOT abort the
  // remaining — the user sees a red status next to the offender and
  // keeps the others' progress.
  const failed: string[] = [];
  for (const f of files.value) {
    const key = fileKey(f);
    const url = resp.upload_urls[f.name];
    if (!url) {
      fileStatus.value[key] = `no upload URL`;
      failed.push(f.name);
      continue;
    }
    fileStatus.value[key] = "uploading";
    try {
      await upload(f, url);
      fileStatus.value[key] = "done";
      completedBytes.value += f.size;
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : "upload failed";
      fileStatus.value[key] = msg;
      failed.push(f.name);
    }
  }

  if (failed.length > 0) {
    // Keep the user on the form so they can retry individual files or
    // fix the underlying issue. Transfer is NOT marked ready until
    // every file lands (worker also guards via status='uploading' check).
    submitError.value = `${failed.length} файл(ов) не загрузились: ${failed.join(", ")}. Проверьте подключение и повторите.`;
    return;
  }

  // Stash the token in sessionStorage instead of the URL so it
  // doesn't leak via browser history, Referer on the success page,
  // or any HTTP-proxy logs between client and our Nginx.
  // UploadSuccessView consumes (reads then removes) the entry.
  sessionStorage.setItem("fylix:last-upload-token", resp.download_token);
  router.push({ name: "uploaded" });
}
</script>

<template>
  <section class="upload">
    <h1 class="upload__title">{{ $t("upload.title") }}</h1>

    <FileDropZone multiple @add="addFiles" />

    <ul v-if="files.length" class="files">
      <li
        v-for="(f, i) in files"
        :key="f.name + f.size"
        class="file"
        :class="{
          'file--uploading': statusOf(f) === 'uploading',
          'file--done': statusOf(f) === 'done',
          'file--error': statusOf(f) !== 'pending' && statusOf(f) !== 'uploading' && statusOf(f) !== 'done',
        }"
      >
        <span class="file__name">{{ f.name }}</span>
        <span class="file__size">{{ formatSize(f.size) }}</span>
        <span v-if="statusOf(f) === 'uploading'" class="file__status file__status--uploading">
          {{ $t("upload.uploading", { percent: Math.round(aggregatePercent) }) }}
        </span>
        <span v-else-if="statusOf(f) === 'done'" class="file__status file__status--done" aria-label="uploaded">✓</span>
        <span v-else-if="statusOf(f) !== 'pending'" class="file__status file__status--error" :title="statusOf(f)">✗</span>
        <button
          class="file__remove"
          type="button"
          @click="removeFile(i)"
          :disabled="uploading"
          aria-label="Remove"
        >
          &times;
        </button>
      </li>
    </ul>

    <p v-if="overLimit" class="limit-warning">
      {{ $t("errors.fileTooLarge", { gb: 2 }) }} — total {{ formatSize(totalBytes) }}
    </p>

    <form class="form" @submit.prevent="submit">
      <label class="field">
        <span class="field__label">
          {{ $t("upload.senderEmail") }}
          <span class="field__required" aria-label="required">*</span>
        </span>
        <input
          v-model="senderEmail"
          type="email"
          class="field__input"
          :class="{ 'field__input--error': senderEmailError }"
          autocomplete="email"
          required
          aria-required="true"
          :aria-invalid="senderEmailError !== null"
          @blur="senderEmailTouched = true"
        />
        <span v-if="senderEmailError === 'required'" class="field__error">
          {{ $t("errors.senderEmailRequired") }}
        </span>
        <span v-else-if="senderEmailError === 'invalid'" class="field__error">
          {{ $t("errors.invalidEmail") }}
        </span>
      </label>

      <label class="field">
        <span class="field__label">
          {{ $t("upload.recipientEmails") }}
          <span class="field__required" aria-label="required">*</span>
        </span>
        <ChipInput
          v-model="recipientEmails"
          :placeholder="$t('upload.recipientEmails')"
          :max="20"
          :validator="isValidEmail"
        />
      </label>

      <label class="field">
        <span class="field__label">{{ $t("upload.message") }}</span>
        <textarea
          v-model="message"
          class="field__textarea"
          maxlength="2000"
          rows="3"
        />
      </label>

      <label class="field field--narrow">
        <span class="field__label">{{ $t("upload.ttl") }}</span>
        <select v-model.number="ttlDays" class="field__input">
          <option v-for="d in [1, 3, 7]" :key="d" :value="d">
            {{ $t("upload.ttlDays", { n: d }) }}
          </option>
        </select>
      </label>

      <div v-if="uploading" class="progress-wrap">
        <ProgressBar :percent="aggregatePercent" :label="$t('upload.uploading', { percent: Math.round(aggregatePercent) })" />
      </div>

      <p v-if="submitError" class="error">{{ submitError }}</p>

      <div class="actions">
        <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
          <span v-if="!uploading">{{ $t("upload.send") }}</span>
          <span v-else>{{ $t("upload.uploading", { percent: Math.round(aggregatePercent) }) }}</span>
        </button>
      </div>

      <p class="limits-hint">{{ $t("upload.limits", { gb: 2, days: 7 }) }}</p>
    </form>
  </section>
</template>

<style scoped>
.upload {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 32px;
  box-shadow: var(--shadow-card);
}
.upload__title {
  margin: 0 0 24px;
  font-size: 28px;
}
.files {
  list-style: none;
  padding: 0;
  margin: 16px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.file {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--bg-section);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
}
.file__name {
  flex: 1;
  color: var(--text);
  font-size: 14px;
  word-break: break-all;
}
.file__size {
  color: var(--text-secondary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.file__remove {
  color: var(--text-secondary);
  font-size: 18px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 6px;
  transition: background var(--transition), color var(--transition);
}
.file__remove:hover {
  background: var(--danger);
  color: #fff;
}
.file__remove:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.file__status {
  font-size: 13px;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
}
.file__status--uploading {
  background: var(--blue-light, #dbeafe);
  color: var(--brand-blue, #2563eb);
}
.file__status--done {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success, #16a34a);
  font-weight: 700;
}
.file__status--error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--danger, #dc2626);
  font-weight: 700;
  cursor: help;
}
.file--done .file__name { text-decoration: line-through; opacity: 0.7; }
.file--error { background: rgba(239, 68, 68, 0.06); }
.limit-warning {
  margin-top: 12px;
  color: var(--danger);
  font-size: 14px;
}
.form {
  margin-top: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field--narrow { max-width: 240px; }
.field__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.field__required {
  color: var(--danger);
  font-weight: 700;
}
.field__input,
.field__textarea {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  transition: border-color var(--transition), box-shadow var(--transition);
}
.field__input:focus,
.field__textarea:focus {
  outline: none;
  border-color: var(--brand-blue);
  box-shadow: 0 0 0 3px var(--blue-ring);
}
.field__input--error {
  border-color: var(--danger);
}
.field__input--error:focus {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15);
}
.field__error {
  color: var(--danger);
  font-size: 12px;
  margin-top: 2px;
}
.field__textarea { resize: vertical; }
.progress-wrap { margin-top: 8px; }
.error {
  padding: 10px 14px;
  background: rgba(239, 68, 68, 0.08);
  color: var(--danger);
  border-radius: var(--radius);
  font-size: 14px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
.btn {
  padding: 12px 28px;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 14px;
  transition: background var(--transition), transform var(--transition), box-shadow var(--transition);
}
.btn--primary {
  background: var(--brand-navy);
  color: #fff;
}
.btn--primary:hover:not(:disabled) {
  background: var(--brand-navy-dark);
  transform: translateY(-1px);
  box-shadow: var(--shadow-hover);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.limits-hint {
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  margin: 0;
}
</style>
