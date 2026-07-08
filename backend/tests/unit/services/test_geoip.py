from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.geoip import GeoIPReader


def test_returns_none_when_db_missing(tmp_path: Path) -> None:
    r = GeoIPReader(db_path=tmp_path / "nonexistent.mmdb")
    assert r.country("8.8.8.8") is None


def test_returns_none_when_db_path_is_none() -> None:
    r = GeoIPReader(db_path=None)
    assert r.country("8.8.8.8") is None


def test_country_lookup_returns_iso_code(monkeypatch, tmp_path: Path) -> None:
    # Stub the geoip2 Reader to avoid needing a real mmdb file.
    fake_db = tmp_path / "fake.mmdb"
    fake_db.write_bytes(b"x")  # make it exist

    fake_reader = MagicMock()
    fake_reader.country.return_value = MagicMock(country=MagicMock(iso_code="KZ"))

    def fake_open(path):
        return fake_reader

    import geoip2.database
    monkeypatch.setattr(geoip2.database, "Reader", fake_open)

    r = GeoIPReader(db_path=fake_db)
    assert r.country("203.0.113.5") == "KZ"


def test_address_not_found_returns_none(monkeypatch, tmp_path: Path) -> None:
    fake_db = tmp_path / "fake.mmdb"
    fake_db.write_bytes(b"x")

    import geoip2.database
    import geoip2.errors

    fake_reader = MagicMock()
    fake_reader.country.side_effect = geoip2.errors.AddressNotFoundError("nope")
    monkeypatch.setattr(geoip2.database, "Reader", lambda p: fake_reader)

    r = GeoIPReader(db_path=fake_db)
    assert r.country("10.0.0.1") is None


def test_is_country_allowed_fail_closed_with_allowlist_and_no_db(tmp_path: Path) -> None:
    # When reader is disabled (no DB) but caller has an explicit allow-list,
    # we cannot verify country — return False (fail-closed, makes misconfiguration visible).
    r = GeoIPReader(db_path=None)
    assert r.is_country_allowed("any-ip", allowed=["KZ"]) is False


def test_is_country_allowed_fail_open_with_empty_allowlist_and_no_db(tmp_path: Path) -> None:
    # When reader is disabled and no allow-list is set, policy is not enforced — return True.
    r = GeoIPReader(db_path=None)
    assert r.is_country_allowed("any-ip", allowed=[]) is True


def test_is_country_allowed_rejects_unknown_country(monkeypatch, tmp_path: Path) -> None:
    fake_db = tmp_path / "fake.mmdb"
    fake_db.write_bytes(b"x")

    fake_reader = MagicMock()
    fake_reader.country.return_value = MagicMock(country=MagicMock(iso_code="RU"))

    import geoip2.database
    monkeypatch.setattr(geoip2.database, "Reader", lambda p: fake_reader)

    r = GeoIPReader(db_path=fake_db)
    assert r.is_country_allowed("8.8.8.8", allowed=["KZ", "UZ", "KG"]) is False
    assert r.is_country_allowed("8.8.8.8", allowed=["RU", "KZ"]) is True
