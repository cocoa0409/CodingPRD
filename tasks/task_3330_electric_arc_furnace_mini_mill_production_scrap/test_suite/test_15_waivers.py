"""Power waiver uniqueness (PRD §3.10)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    make_mill, make_grade, make_heat,
)

ED = TEST_USERS["energy_dispatcher_headers"]


def test_power_waiver_duplicate_scope_rejected():
    """PRD §3.10: "Uniqueness is enforced per target: at most one waiver per
    (scope, scope_id) pair — one per heat, one per event — and a duplicate grant
    fails with `ERR_WAIVER_DUPLICATE` (HTTP 409)."

    Design: Corner/endpoints/power_waiver_duplicate_scope_rejected
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    grade = make_grade(mill["id"], grade_code="GR40")
    h1 = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                   planned_tap_at="2026-09-15T12:00:00Z")
    h2 = make_heat(mill["id"], grade["id"], target_tap_weight_tons=8,
                   planned_tap_at="2026-09-15T14:00:00Z")

    first = validate_success(
        api_client.grant_waiver(
            mill["id"], {"scope": "HEAT", "scope_id": h1["id"], "reason": "first waiver"},
            ED), 201)
    assert first["scope"] == "HEAT"

    dup = api_client.grant_waiver(
        mill["id"], {"scope": "HEAT", "scope_id": h1["id"], "reason": "duplicate attempt"},
        ED)
    validate_error(dup, ApiErrorId.ERR_WAIVER_DUPLICATE, 409)

    other = validate_success(
        api_client.grant_waiver(
            mill["id"], {"scope": "HEAT", "scope_id": h2["id"], "reason": "different heat"},
            ED), 201)
    assert other["scope_id"] == h2["id"]
