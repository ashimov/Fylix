<script setup lang="ts">
import { useI18n } from "vue-i18n";
const { t } = useI18n();
</script>

<template>
  <article class="legal">
    <h1 class="legal__title">{{ t("legal.title") }}</h1>
    <p class="legal__body">{{ t("legal.body") }}</p>

    <section class="legal__section">
      <h2>Data we collect</h2>
      <ul>
        <li>Sender and recipient email addresses (for delivery notifications and audit)</li>
        <li>Upload IP address and approximate geolocation (for abuse prevention)</li>
        <li>File names, sizes, MIME types — NOT file contents (those are encrypted)</li>
        <li>Download timestamps and IP addresses of each download</li>
      </ul>
    </section>

    <section class="legal__section">
      <h2>Retention</h2>
      <p>
        Files are automatically deleted 7 days after upload (configurable per transfer,
        maximum 7 days). The per-transfer encryption key is destroyed on deletion —
        files become mathematically unrecoverable even if ciphertext survives on backups.
      </p>
    </section>

    <section class="legal__section">
      <h2>Your rights</h2>
      <p>
        The sender can delete a transfer early or revoke its link at any time via the
        sender panel (the link sent in the upload confirmation email).
        For data access or removal requests beyond an active transfer, contact
        <a href="mailto:it@example.com">it@example.com</a>.
      </p>
    </section>

    <p class="legal__placeholder">
      <em>{{ t("legal.body") }}</em>
    </p>
  </article>
</template>

<style scoped>
.legal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 32px;
  box-shadow: var(--shadow-card);
}
.legal__title {
  font-size: 28px;
  margin: 0 0 24px;
}
.legal__body {
  color: var(--text-secondary);
  margin-bottom: 16px;
}
.legal__section {
  margin-top: 24px;
}
.legal__section h2 {
  font-size: 18px;
  margin-bottom: 8px;
  color: var(--brand-navy);
}
[data-theme="dark"] .legal__section h2 { color: var(--brand-blue); }
.legal__section p,
.legal__section ul { color: var(--text-secondary); }
.legal__section ul { padding-left: 20px; margin-top: 4px; }
.legal__section li { margin: 4px 0; }
.legal__section a { color: var(--brand-navy); font-weight: 600; }
[data-theme="dark"] .legal__section a { color: var(--brand-blue); }
.legal__placeholder {
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px dashed var(--border);
  color: var(--muted);
  font-size: 13px;
}
</style>
