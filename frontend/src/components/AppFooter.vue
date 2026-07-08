<script setup lang="ts">
import hawkLogo from "@/assets/hawk-logo.png";

// Injected at build time by vite.config.ts `define` from package.json.
const version = __APP_VERSION__;
</script>

<template>
  <footer class="footer">
    <!-- Ambient aurora glow -->
    <div class="footer__aurora" aria-hidden="true"></div>
    <!-- Shimmering top accent line -->
    <div class="footer__accent" aria-hidden="true"></div>

    <div class="footer__inner">
      <p class="footer__tagline">
        {{ $t("footer.copyright") }}
        <span class="footer__version" aria-label="version">v{{ version }}</span>
      </p>

      <div class="footer__info">
        <span class="footer__built">
          <span class="footer__built-label">Built with</span>
          <a
            href="https://github.com/ashimov/HawkAPI"
            target="_blank"
            rel="noreferrer"
            class="footer__hawk-link"
            aria-label="HawkAPI — open in new tab"
          >
            <img
              :src="hawkLogo"
              alt="Hawk"
              class="footer__hawk-icon"
              loading="lazy"
            />
          </a>
        </span>

        <span class="footer__sep" aria-hidden="true"></span>

        <span class="footer__dev">
          Developed by
          <a
            href="https://linkedin.com/in/berik-ashimov"
            target="_blank"
            rel="noreferrer"
            class="footer__dev-link"
          >
            Berik Ashimov
          </a>
        </span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.footer {
  position: relative;
  background:
    radial-gradient(
      ellipse at 50% 120%,
      rgba(148, 189, 229, 0.12) 0%,
      transparent 55%
    ),
    linear-gradient(135deg, #272666 0%, #1c1c50 100%);
  padding: 40px 24px 32px;
  overflow: hidden;
  isolation: isolate;
}

/* Soft breathing aurora behind content */
.footer__aurora {
  position: absolute;
  inset: 0;
  z-index: 0;
  background:
    radial-gradient(
      circle at 20% 80%,
      rgba(148, 189, 229, 0.1) 0%,
      transparent 35%
    ),
    radial-gradient(
      circle at 80% 20%,
      rgba(148, 189, 229, 0.08) 0%,
      transparent 40%
    );
  animation: footer-breathe 8s ease-in-out infinite alternate;
  pointer-events: none;
}

@keyframes footer-breathe {
  0% {
    opacity: 0.6;
    transform: scale(1);
  }
  100% {
    opacity: 1;
    transform: scale(1.08);
  }
}

/* Animated shimmering accent line */
.footer__accent {
  position: absolute;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 240px;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(148, 189, 229, 0.15) 20%,
    #94bde5 50%,
    rgba(148, 189, 229, 0.15) 80%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: accent-shimmer 4s ease-in-out infinite;
}

@keyframes accent-shimmer {
  0%,
  100% {
    background-position: 100% 0;
    opacity: 0.6;
  }
  50% {
    background-position: 0% 0;
    opacity: 1;
  }
}

.footer__inner {
  position: relative;
  z-index: 1;
  max-width: 1240px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.footer__tagline {
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.5);
  text-align: center;
  letter-spacing: 0.015em;
  margin: 0;
}

.footer__version {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.45);
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(148, 189, 229, 0.18);
  border-radius: 4px;
  letter-spacing: 0.03em;
  vertical-align: middle;
}

.footer__info {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 0.76rem;
  color: rgba(255, 255, 255, 0.4);
  letter-spacing: 0.02em;
}

.footer__built,
.footer__dev {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.footer__built-label {
  transition: color 220ms ease;
}

.footer__built:hover .footer__built-label {
  color: rgba(255, 255, 255, 0.7);
}

/* Hawk link + icon */
.footer__hawk-link {
  display: inline-flex;
  align-items: center;
  color: #94bde5;
  text-decoration: none;
  padding: 2px;
  border-radius: 6px;
  transition: transform 220ms ease;
}

.footer__hawk-link:focus-visible {
  outline: 2px solid #94bde5;
  outline-offset: 3px;
}

.footer__hawk-icon {
  height: 22px;
  width: auto;
  transform-origin: center;
  transition: transform 300ms ease;
}

/* Exactly the PharmaTransfer/AIPrompts hover behaviour:
   scale + slight anti-clockwise tilt. Idle state has no animation. */
.footer__hawk-link:hover .footer__hawk-icon {
  transform: scale(1.2) rotate(-8deg);
}

/* Developer link */
.footer__dev-link {
  color: #94bde5;
  font-weight: 600;
  text-decoration: none;
  position: relative;
  padding: 2px 1px;
  transition: color 220ms ease;
}

.footer__dev-link::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -1px;
  width: 100%;
  height: 1px;
  background: currentColor;
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform 280ms cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.footer__dev-link:hover {
  color: #fff;
}

.footer__dev-link:hover::after {
  transform: scaleX(1);
}

.footer__dev-link:focus-visible {
  outline: 2px solid #94bde5;
  outline-offset: 3px;
  border-radius: 3px;
}

/* Tiny dot separator */
.footer__sep {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.25);
  flex-shrink: 0;
}

/* Reduced motion: calm everything down */
@media (prefers-reduced-motion: reduce) {
  .footer__aurora,
  .footer__accent {
    animation: none;
  }
  .footer__hawk-link:hover .footer__hawk-icon {
    transform: none;
  }
}

@media (max-width: 600px) {
  .footer {
    padding: 32px 20px 28px;
  }
  .footer__info {
    flex-direction: column;
    gap: 8px;
  }
  .footer__sep {
    display: none;
  }
}
</style>
