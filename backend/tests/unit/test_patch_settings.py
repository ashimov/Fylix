"""PatchSettingsRequest — typed partial-update DTO with range validation
and extra="forbid" for unknown keys."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.admin import PatchSettingsRequest


def test_empty_payload_yields_empty_changes() -> None:
    p = PatchSettingsRequest.model_validate({})
    assert p.to_changes() == {}


def test_single_field_partial_update() -> None:
    p = PatchSettingsRequest.model_validate({"max_ttl_days": 14})
    assert p.to_changes() == {"max_ttl_days": 14}


def test_multiple_fields_partial_update() -> None:
    p = PatchSettingsRequest.model_validate(
        {"max_transfer_size_gb": 5, "rate_hourly": 20, "geoip_enabled": True}
    )
    changes = p.to_changes()
    assert changes == {
        "max_transfer_size_gb": 5,
        "rate_hourly": 20,
        "geoip_enabled": True,
    }


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        PatchSettingsRequest.model_validate({"not_a_real_key": 42})


def test_max_transfer_size_enforces_upper_bound() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 100"):
        PatchSettingsRequest.model_validate({"max_transfer_size_gb": 101})


def test_max_ttl_enforces_upper_bound() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 90"):
        PatchSettingsRequest.model_validate({"max_ttl_days": 91})


def test_rate_hourly_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        PatchSettingsRequest.model_validate({"rate_hourly": 0})


def test_audit_retention_enforces_minimum() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 30"):
        PatchSettingsRequest.model_validate({"audit_retention_days": 29})


def test_geoip_countries_accepts_list_of_strings() -> None:
    p = PatchSettingsRequest.model_validate({"geoip_countries": ["KZ", "UZ", "KG"]})
    assert p.to_changes() == {"geoip_countries": ["KZ", "UZ", "KG"]}


def test_wrong_type_for_int_field_is_rejected() -> None:
    """Previously `dict[str, Any]` would accept a list here and corrupt the DB."""
    with pytest.raises(ValidationError):
        PatchSettingsRequest.model_validate({"rate_hourly": ["not", "an", "int"]})


def test_wrong_type_for_bool_field_rejects_list() -> None:
    with pytest.raises(ValidationError):
        PatchSettingsRequest.model_validate({"geoip_enabled": []})


def test_extension_blacklist_accepts_list_of_strings() -> None:
    p = PatchSettingsRequest.model_validate({"extension_blacklist": ["exe", "bat", "scr"]})
    assert p.to_changes() == {"extension_blacklist": ["exe", "bat", "scr"]}


def test_fields_explicitly_unset_do_not_appear_in_changes() -> None:
    """Partial-update semantics: only fields the client sent round-trip through."""
    p = PatchSettingsRequest.model_validate({"rate_hourly": 15})
    changes = p.to_changes()
    assert "rate_daily" not in changes
    assert "max_ttl_days" not in changes
