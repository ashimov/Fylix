<script setup lang="ts">
import { computed, ref } from "vue";

const props = defineProps<{
  modelValue: string[];
  placeholder?: string;
  max?: number;
  validator?: (v: string) => boolean;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string[]): void;
}>();

const draft = ref("");
const error = ref<string | null>(null);

const atMax = computed(() => !!props.max && props.modelValue.length >= props.max);

function pushChip(raw: string): void {
  const v = raw.trim().replace(/,|;$/, "");
  if (!v) return;
  if (atMax.value) {
    error.value = `maximum ${props.max}`;
    return;
  }
  if (props.validator && !props.validator(v)) {
    error.value = v;
    return;
  }
  if (props.modelValue.includes(v)) {
    draft.value = "";
    return;
  }
  emit("update:modelValue", [...props.modelValue, v]);
  draft.value = "";
  error.value = null;
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter" || e.key === "," || e.key === ";") {
    e.preventDefault();
    pushChip(draft.value);
  } else if (e.key === "Backspace" && !draft.value && props.modelValue.length) {
    const next = props.modelValue.slice(0, -1);
    emit("update:modelValue", next);
  }
}

function onBlur(): void {
  if (draft.value.trim()) pushChip(draft.value);
}

function remove(i: number): void {
  const next = props.modelValue.slice();
  next.splice(i, 1);
  emit("update:modelValue", next);
}
</script>

<template>
  <div class="chips">
    <div class="chips__box" :class="{ 'chips__box--error': error }">
      <span v-for="(c, i) in modelValue" :key="c" class="chip">
        {{ c }}
        <button
          type="button"
          class="chip__remove"
          :aria-label="`Remove ${c}`"
          @click="remove(i)"
        >&times;</button>
      </span>
      <input
        v-model="draft"
        class="chips__input"
        type="text"
        :placeholder="modelValue.length === 0 ? placeholder : ''"
        :disabled="atMax"
        @keydown="onKeydown"
        @blur="onBlur"
      />
    </div>
    <p v-if="error" class="chips__error">{{ error }}</p>
  </div>
</template>

<style scoped>
.chips { width: 100%; }
.chips__box {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color var(--transition);
}
.chips__box:focus-within {
  border-color: var(--brand-blue);
  box-shadow: 0 0 0 3px var(--blue-ring);
}
.chips__box--error { border-color: var(--danger); }
.chips__input {
  flex: 1;
  min-width: 120px;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text);
  padding: 4px 6px;
  font-size: 14px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--tag-bg);
  color: var(--brand-navy);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
}
[data-theme="dark"] .chip { color: var(--brand-blue); }
.chip__remove {
  color: inherit;
  opacity: 0.6;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  transition: opacity 150ms;
}
.chip__remove:hover { opacity: 1; }
.chips__error {
  margin-top: 4px;
  color: var(--danger);
  font-size: 13px;
}
</style>
