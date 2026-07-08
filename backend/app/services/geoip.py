"""MaxMind GeoLite2 country lookup.

Gracefully becomes a no-op (returns None for all lookups) when the mmdb file
is missing. This is the dev default since the operator has to download the
DB separately from MaxMind.

The class is thread-safe for reads.
"""

from __future__ import annotations

import logging
from pathlib import Path

import geoip2.database
import geoip2.errors

log = logging.getLogger(__name__)


class GeoIPReader:
    def __init__(self, *, db_path: Path | None) -> None:
        self.db_path = db_path
        self._reader: geoip2.database.Reader | None = None
        if db_path is not None and db_path.exists():
            try:
                self._reader = geoip2.database.Reader(db_path)
                log.info("geoip: loaded %s", db_path)
            except Exception:
                log.exception("geoip: failed to open %s; disabling", db_path)
        else:
            log.info("geoip: db at %s missing; disabled", db_path)

    @property
    def enabled(self) -> bool:
        return self._reader is not None

    def country(self, ip: str) -> str | None:
        if self._reader is None:
            return None
        try:
            return self._reader.country(ip).country.iso_code
        except geoip2.errors.AddressNotFoundError:
            return None
        except Exception:
            log.exception("geoip: lookup failed for %s", ip)
            return None

    def is_country_allowed(self, ip: str, *, allowed: list[str]) -> bool:
        """Fail-closed when the reader is disabled but policy expected to enforce.

        Callers pass `allowed` as the configured country allow-list. When this
        reader is disabled (no mmdb), we cannot verify country — return True
        only if callers have NOT passed an explicit allow-list (i.e. policy is
        not actively enforced). When `allowed` is non-empty and reader is off,
        return False to make the misconfiguration visible.
        """
        if self._reader is None:
            return not allowed  # True if allowed is empty (no policy), False otherwise
        country = self.country(ip)
        if country is None:
            return True  # unknown IP — allow (IPv6 loopback, unregistered ranges)
        return country.upper() in {c.upper() for c in allowed}

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
