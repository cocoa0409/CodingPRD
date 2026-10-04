"""Corner coverage: optimistic concurrency control on the two OCC-guarded
writes, and the monotonic logical clock with its sweep report."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_alteration, estimate_alteration,
    make_agency_manager_headers, set_clock, setup_active_leased_oa,
    setup_active_owned_oa, setup_commenced_lease, validate_error,
    validate_paginated, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]


def test_oa_amend_stale_version_rejected_then_rebased_succeeds(api):
    """PRD §2.7: "Amending an occupancy agreement requires the request to carry
    `expected_oa_version` holding the `version` of the agreement as the client
    last observed it. If the agreement's current `version` has advanced since
    that observation — amendments may be issued in sequence, and each one
    rewrites `assigned_sf`, the term end, or the owned-space rates — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the stale
    writer to re-read and rebase before retrying."
    PRD §3.5: "The amendment increments the agreement's `version`, appends to
    `amendment_history` an entry recording `amended_at`, `delta_sf`, `old_sf`,
    `new_sf`, and the `note`, and applies `delta_sf` to `assigned_sf` — moving
    the owned building's `available_sf` in the opposite direction by the same
    amount."

    Design: Corner/cross_cutting_complexity/oa_amend_stale_version_rejected_then_rebased_succeeds
    """
    bundle = setup_active_owned_oa()
    oa, building = bundle["oa"], bundle["building"]
    oa_v = oa["version"]  # captured right after activation

    stale = api.amend_oa(oa["id"],
                         {"expected_oa_version": oa_v - 1, "delta_sf": 1000,
                          "note": "stale writer"}, OFFICER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    mid = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert mid["assigned_sf"] == 20000
    assert mid["version"] == oa_v, "the stale writer changed nothing"

    rebased = validate_success(api.amend_oa(
        oa["id"], {"expected_oa_version": oa_v, "delta_sf": 1000,
                   "note": "rebased writer"}, OFFICER), 200)
    assert rebased["version"] == oa_v + 1
    assert rebased["assigned_sf"] == 21000

    last = rebased["amendment_history"][-1]
    assert last["delta_sf"] == 1000
    assert last["old_sf"] == 20000
    assert last["new_sf"] == 21000

    building_after = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert building_after["available_sf"] == 29000, "delta debited"


def test_alteration_revise_stale_version_rejected(api):
    """PRD §2.7: "Revising an alteration request requires the request to carry
    `expected_alteration_version` holding the alteration's last observed
    `version`. A revision legitimately supersedes the pending estimate — it
    clears the estimate fields and reopens the request — so a stale revision is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.6: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource, including system-driven transitions,
    cascade effects, and computed-field recomputation."

    The version captured at create is stale once the estimate lands (the
    estimate is a mutation), so the revise carrying it is rejected and the
    estimate is untouched.

    Design: Corner/cross_cutting_complexity/alteration_revise_stale_version_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]

    alt = create_alteration(oa, agency)
    v_pre = alt["version"]
    estimate_alteration(alt, estimated_cost_cents=800000,
                        work_start_date="2028-03-01", work_end_date="2028-03-31")

    resp = api.revise_alteration(
        alt["id"], {"expected_alteration_version": v_pre, "scope_sf": 900},
        make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    assert alts[0]["status"] == "ESTIMATED", "no partial revision"
    assert alts[0]["estimated_cost_cents"] == 800000


def test_clock_set_is_monotonic_and_reports_transitions(api):
    """PRD §2.4: "The clock is monotonic: an attempt to set it to an instant
    earlier than its current reading is rejected with `ERR_INVALID_REQUEST`."
    PRD §2.4: "The clock-setting response reports `current_utc` plus the ids of
    everything the sweep moved: `transitioned_lease_ids`,
    `transitioned_oa_ids`, and `transitioned_plan_ids`."
    PRD §2.4: "A lease in `COMMENCED` moves to `EXPIRING` once the current date
    reaches the date eighteen months before its `end_date` (month arithmetic,
    with the day clamped to the month end when the target month is shorter)."

    Design: Corner/cross_cutting_complexity/clock_set_is_monotonic_and_reports_transitions
    """
    bundle = setup_commenced_lease()
    lease = bundle["lease"]

    forward = set_clock("2035-06-30T00:00:00Z")
    assert forward["current_utc"] == "2035-06-30T00:00:00Z"
    assert lease["id"] in forward["transitioned_lease_ids"], (
        "COMMENCED -> EXPIRING applied at end_date - 18 months")

    backwards = api.set_clock("2035-06-29T00:00:00Z", ADMIN)
    validate_error(backwards, ApiErrorId.ERR_INVALID_REQUEST)

    still_backwards = api.set_clock("2035-06-29T12:00:00Z", ADMIN)
    validate_error(still_backwards, ApiErrorId.ERR_INVALID_REQUEST, 400)
