<script setup lang="ts">
import { ref } from "vue";

defineProps<{
  multiple?: boolean;
  accept?: string;
}>();

const emit = defineEmits<{
  (e: "add", files: File[]): void;
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const hovering = ref(false);

function onClick(): void {
  inputRef.value?.click();
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    onClick();
  }
}

function onChange(e: Event): void {
  const target = e.target as HTMLInputElement;
  if (target.files) {
    emit("add", Array.from(target.files));
    target.value = ""; // reset so same-file re-add works
  }
}

function onDragOver(e: DragEvent): void {
  e.preventDefault();
  hovering.value = true;
}

function onDragLeave(): void {
  hovering.value = false;
}

function onDrop(e: DragEvent): void {
  e.preventDefault();
  hovering.value = false;
  if (e.dataTransfer?.files) {
    emit("add", Array.from(e.dataTransfer.files));
  }
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ 'dropzone--hover': hovering }"
    role="button"
    tabindex="0"
    @click="onClick"
    @keydown="onKeydown"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      width="40"
      height="40"
      class="dropzone__icon"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
    <p class="dropzone__text">
      <slot>{{ $t("upload.drop") }}</slot>
    </p>
    <input
      ref="inputRef"
      class="dropzone__input"
      type="file"
      :multiple="multiple"
      :accept="accept"
      @change="onChange"
    />
  </div>
</template>

<style scoped>
.dropzone {
  border: 2px dashed var(--border);
  border-radius: var(--radius-lg);
  padding: 48px 24px;
  text-align: center;
  background: var(--bg-section);
  color: var(--text-secondary);
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition), transform var(--transition);
}
.dropzone:hover,
.dropzone:focus-visible {
  border-color: var(--brand-blue);
  background: var(--blue-light);
  outline: none;
}
.dropzone--hover {
  border-color: var(--brand-navy);
  background: var(--accent-light);
  transform: scale(1.01);
}
[data-theme="dark"] .dropzone--hover { border-color: var(--brand-blue); }
.dropzone__icon {
  color: var(--brand-navy);
  margin: 0 auto 12px;
}
[data-theme="dark"] .dropzone__icon { color: var(--brand-blue); }
.dropzone__text { margin: 0; font-size: 15px; }
.dropzone__input { display: none; }
</style>
