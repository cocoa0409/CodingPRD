"""Window creation: OCC, term, quota, exclusive-ratio gate (PRD §2.5, §2.6, §3.2)."""
from test_helpers import (
    ApiErrorId,
    RM,
    create_active_property,
    create_window,
    current_property_version,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_window_payload


def test_stale_version_beats_window_outside_term(api):
    """PRD §2.5: "When a request fails multiple checks, the error surfaced
    to the caller is determined by a fixed priority order, evaluated from
    the top of this list downward — a request is rejected with the first
    applicable error" with ERR_STALE_VERSION at priority 5 and
    ERR_WINDOW_OUTSIDE_TERM at priority 7.

    A create carrying both a stale expected_property_version and a schedule
    outside the property term fails with ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_pair_on_window_create
    """
    prop = create_active_property(term_end="2027-03-01T00:00:00Z")
    version_at_activate = current_property_version(prop["id"])
    # A first successful create advances the property version.
    create_window(prop["id"], scheduled_start="2026-09-15T18:00:00Z",
                  scheduled_end="2026-09-15T20:00:00Z")
    stale_version = version_at_activate
    payload = create_window_payload(
        prop["id"],
        stale_version,
        scheduled_start="2028-01-01T18:00:00Z",  # outside term
        scheduled_end="2028-01-01T20:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_stale_property_version_rejected_even_with_valid_schedule(api):
    """PRD §2.6: "Creating a `StreamingWindow` via the windows-creation
    endpoint requires a non-optional `expected_property_version` field
    carrying the client's last observed `version` of the owning
    `RightsProperty`. If another writer has advanced the property's version
    since the client last read it — for example, by scheduling a different
    replacement window against the same predecessor — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_pair_on_window_create
    """
    prop = create_active_property(term_end="2027-03-01T00:00:00Z")
    version_at_activate = current_property_version(prop["id"])
    create_window(prop["id"], scheduled_start="2026-09-15T18:00:00Z",
                  scheduled_end="2026-09-15T20:00:00Z")
    payload = create_window_payload(
        prop["id"],
        version_at_activate,  # stale: first create advanced the version
        scheduled_start="2026-10-01T18:00:00Z",
        scheduled_end="2026-10-01T20:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_property_version_on_window_create(api):
    """PRD §2.6: "Creating a `StreamingWindow` via the windows-creation
    endpoint requires a non-optional `expected_property_version` field
    carrying the client's last observed `version` of the owning
    `RightsProperty` ... the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_property_version_on_window_create
    """
    prop = create_active_property()
    observed = current_property_version(prop["id"])
    create_window(prop["id"], scheduled_start="2026-10-06T18:00:00Z",
                  scheduled_end="2026-10-06T21:00:00Z")
    payload = create_window_payload(
        prop["id"],
        observed,
        scheduled_start="2026-10-07T18:00:00Z",
        scheduled_end="2026-10-07T21:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_window_create_outside_property_term(api):
    """PRD §3.2: "both `scheduled_start` and `scheduled_end` must fall inside
    the property's term (so `term_start <= scheduled_start` and
    `scheduled_end <= term_end`), and `replay_hours` must be at least 0; a
    failure surfaces `ERR_WINDOW_OUTSIDE_TERM` (HTTP 422)."

    Design: Corner/validations/window_create_outside_property_term
    """
    prop = create_active_property(term_end="2027-03-01T00:00:00Z")
    version = current_property_version(prop["id"])
    payload = create_window_payload(
        prop["id"],
        version,
        scheduled_start="2026-08-01T18:00:00Z",  # before term_start
        scheduled_end="2026-08-01T21:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_TERM)


def test_window_quota_exceeded_on_simulcast(api):
    """PRD §3.2: "creating a `SIMULCAST` window requires
    `simulcast_windows_consumed` to be strictly less than
    `simulcast_windows_count` ... a failure surfaces
    `ERR_WINDOW_QUOTA_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/window_quota_exceeded_on_simulcast
    """
    prop = create_active_property(simulcast_windows_count=1, exclusive_windows_count=2)
    create_window(prop["id"], rights_mode="SIMULCAST",
                  scheduled_start="2026-10-01T18:00:00Z",
                  scheduled_end="2026-10-01T21:00:00Z")
    version = current_property_version(prop["id"])
    payload = create_window_payload(
        prop["id"],
        version,
        rights_mode="SIMULCAST",
        scheduled_start="2026-10-02T18:00:00Z",
        scheduled_end="2026-10-02T21:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_WINDOW_QUOTA_EXCEEDED)


def test_exclusive_ratio_equality_passes_then_breach_rejects(api):
    """PRD §3.2: "letting `total` be `simulcast_windows_consumed +
    exclusive_windows_consumed` **after** the new window is counted, the
    ratio is the integer floor of 100 times `exclusive_windows_consumed`
    divided by the maximum of `total` and 1, and creation is rejected with
    `ERR_EXCLUSIVE_RATIO_BREACH` (HTTP 422) when this floored ratio is
    strictly less than the property's `minimum_exclusive_ratio_pct`. A ratio
    exactly equal to the minimum passes — the rejection condition is strict
    less-than."

    minimum 50: EXCLUSIVE then SIMULCAST lands at exactly 50 (admitted); a
    second SIMULCAST would floor to 33 and is rejected.

    Design: Difficulty/boundary_precision_check/exclusive_ratio_floor_equality_passes
    """
    prop = create_active_property(
        minimum_exclusive_ratio_pct=50,
        simulcast_windows_count=6,
        exclusive_windows_count=6,
    )
    create_window(prop["id"], rights_mode="EXCLUSIVE",
                  scheduled_start="2026-09-14T18:00:00Z",
                  scheduled_end="2026-09-14T20:00:00Z")
    # ratio after this SIMULCAST: floor(100*1/2) = 50 == minimum -> admitted
    admitted = create_window(prop["id"], rights_mode="SIMULCAST",
                             scheduled_start="2026-09-15T18:00:00Z",
                             scheduled_end="2026-09-15T20:00:00Z")
    assert admitted["status"] == "SCHEDULED"
    version = current_property_version(prop["id"])
    payload = create_window_payload(
        prop["id"],
        version,
        rights_mode="SIMULCAST",
        scheduled_start="2026-09-16T18:00:00Z",
        scheduled_end="2026-09-16T20:00:00Z",
    )
    resp = api.create_window(payload, RM)
    # ratio would become floor(100*1/3) = 33 < 50
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_RATIO_BREACH)


def test_exclusive_ratio_below_minimum_rejected_immediately(api):
    """PRD §3.2: "creation is rejected with `ERR_EXCLUSIVE_RATIO_BREACH`
    (HTTP 422) when this floored ratio is strictly less than the property's
    `minimum_exclusive_ratio_pct`."

    With minimum 50 and no EXCLUSIVE window, the first SIMULCAST floors to 0
    and is rejected at once.

    Design: Difficulty/boundary_precision_check/exclusive_ratio_floor_equality_passes
    """
    prop = create_active_property(
        minimum_exclusive_ratio_pct=50,
        simulcast_windows_count=6,
        exclusive_windows_count=6,
    )
    version = current_property_version(prop["id"])
    payload = create_window_payload(
        prop["id"],
        version,
        rights_mode="SIMULCAST",
        scheduled_start="2026-09-16T18:00:00Z",
        scheduled_end="2026-09-16T20:00:00Z",
    )
    resp = api.create_window(payload, RM)
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_RATIO_BREACH)
    prop_after = get_success_data(api.get_property(prop["id"], RM))
    assert prop_after["simulcast_windows_consumed"] == 0
