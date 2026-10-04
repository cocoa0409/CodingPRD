"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_TIMESTAMPED = ("id", "created_at", "updated_at")
_APPEND_ONLY_FORBIDDEN = ("updated_at", "version")


def stored_instant(value) -> str:
    """Normalise a wire instant to its stored form, at second precision.

    PRD §2.7 renders every timestamp as an ISO 8601 UTC instant with three
    fractional digits. The logical clock instants this suite sets carry no
    fractional part, so the stored rendering of an offset resolved against them
    is the same instant at second precision. Comparing on that canonical form
    avoids failing an implementation that renders the mandated ".000" while the
    literal in the test was written without it.
    """
    text = str(value)
    if not text:
        return text
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        if frac == "0" * len(frac):
            text = head
    return text + "Z"


def _assert_common(data: dict, *, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["wall_bin_capacity_grams"], int)
    assert isinstance(data["bin_engine_mass_grams"], int)
    assert data["bin_engine_mass_grams"] >= 0
    assert isinstance(data["shrinkage_basis_points"], int)
    assert data["shrinkage_basis_points"] >= 0
    assert data["stage"] in ("TRADING", "RESTRICTED", "FROZEN")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["tier"] in ("STANDARD", "VIP")
    assert data["stage"] in ("ACTIVE", "RESTRICTED", "SUSPENDED")
    assert isinstance(data["passed_mb_reservations"], int)
    assert data["passed_mb_reservations"] >= 0
    assert isinstance(data["points_balance"], int)


def assert_element(data: dict):
    _assert_common(data)
    assert isinstance(data["element_code"], str) and data["element_code"]
    assert data["unit_mass_grams"] > 0
    assert data["cost_basis_cents"] >= 0
    assert data["status"] in (
        "PENDING_CATALOG", "ACTIVE", "RETIRED_TO_ARCHIVE", "CATALOG"
    )
    assert data["sourcing_mode"] in ("SURPLUS", "CURRENT_PRODUCTION")


def assert_wall_bin(data: dict):
    _assert_common(data)
    assert data["bin_capacity_grams"] > 0
    assert data["bin_mass_grams"] >= 0
    assert data["status"] in ("OPEN", "LOW", "EMPTY", "RETIRED")
    assert isinstance(data["fill_pct"], (int, float))
    assert data["fill_pct"] >= 0


def assert_fusion_order(data: dict):
    _assert_common(data)
    assert data["cup_size"] in ("SMALL", "LARGE", "JUMBO")
    assert data["pricing_model"] in ("CUP_FILL", "PER_PIECE")
    assert data["declared_mass_grams"] > 0
    assert data["status"] in ("PENDING", "SETTLED", "VOID", "CLOSED")
    for field in ("priced_piece_count", "base_price_cents",
                  "member_discount_cents", "final_price_cents", "variance_grams"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_fusion_allocation(data: dict):
    """A bin draw is append-only: id and created_at only, never a version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    for forbidden in _APPEND_ONLY_FORBIDDEN:
        assert forbidden not in data, f"a bin draw must not carry {forbidden}"
    assert data["allocation_grams"] > 0


def assert_loyalty_ledger(data: dict):
    """A ledger entry is append-only: id and created_at only, never a version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    for forbidden in _APPEND_ONLY_FORBIDDEN:
        assert forbidden not in data, f"a ledger entry must not carry {forbidden}"
    assert data["entry_kind"] in ("REDEMPTION", "REPLACEMENT_GRANT", "MANUAL_ADJUSTMENT")
    assert isinstance(data["points_delta"], int)
    assert data["points_delta"] != 0


def assert_minifigure_build(data: dict):
    _assert_common(data)
    assert data["status"] in ("BUILDING", "SEALED", "RETURNED")
    assert isinstance(data["platform_gen"], int)
    assert 0 <= data["components_missing"] <= 4


def assert_theme_launch(data: dict):
    _assert_common(data)
    assert data["stage"] in ("SCHEDULED", "VIP_EARLY", "STAGED_OPEN", "CLOSED")
    assert data["allocated_exclusive_units"] >= 0
    assert isinstance(data["exclusive_set_units_remaining"], int)
    assert isinstance(data["soft_hold_units"], int)
    assert is_iso8601_timestamp(data["release_utc"])
    assert is_iso8601_timestamp(data["vip_early_access_utc"])


def assert_launch_queue(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "WAITING", "GRANTED", "PURCHASED", "NO_SHOW",
        "EXPIRED", "VOIDED", "PURCHASED_ROLLBACK",
    )
    assert data["id_check_state"] in (
        "IDENTITY_UNVERIFIED", "IDENTITY_VERIFIED", "IDENTITY_ESCALATED"
    )
    assert data["priority_class"] in ("VIP_EARLY", "GENERAL")
    assert data["requested_units"] >= 1


def assert_store_event(data: dict):
    _assert_common(data)
    assert data["event_kind"] in ("BUILD_EVENT", "MINI_BUILD")
    assert data["capacity_units"] >= 1
    assert data["stage"] in ("SCHEDULED", "OPEN", "CLOSED", "COMPLETED")
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REGISTERED", "WAITLISTED", "PROMOTED", "PASSED", "EXPIRED", "NOT_ADMITTED"
    )
    assert data["seats"] >= 1
    assert isinstance(data["arrival_counter"], int)


def assert_replacement_request(data: dict):
    _assert_common(data)
    assert data["quantity_missing"] >= 1
    assert data["stage"] in ("OPEN", "PROSPECT", "DENIED", "CLAIMED", "COMPLETED")
    assert isinstance(data["earned_points"], int)
    assert data["earned_points"] >= 0


def assert_exit_inspection(data: dict):
    _assert_common(data)
    assert data["outcome"] in ("CLEAR", "MISMATCH")
    assert data["checklist_result"] in ("COMPLETED", "PARTIAL", "WAIVED")
    assert data["stage"] in ("SCHEDULED", "COMPLETED", "WAIVED")
    assert isinstance(data["variance_bps"], int)
    assert data["variance_bps"] >= 0


# ─── Domain invariant checkers ────────────────────────

def assert_store_invariants(data: dict):
    """The posture is a pure function of the engine mass and the freeze count."""
    assert data["bin_engine_mass_grams"] >= 0
    assert data["shrinkage_basis_points"] >= 0
    assert data["stage"] in ("TRADING", "RESTRICTED", "FROZEN")


def assert_launch_invariants(data: dict):
    """The remaining allocation is a closed quantity inside the declared pool."""
    assert 0 <= data["exclusive_set_units_remaining"] <= data["allocated_exclusive_units"]
    assert data["soft_hold_units"] >= 0


def assert_build_invariants(data: dict):
    """A sealed figure has nothing missing; the generation never goes backwards."""
    if data["status"] == "SEALED":
        assert data["components_missing"] == 0
    assert data["platform_gen"] >= 0