"""Deployment stipends (provisional vs final variants), the FOB lodging
ledger's pinned per-night rounding, bunk occupancy compensation, FOB capacity
rejection, and the wellness-check resolution gate."""
from test_helpers import (
    CHECK_IN_CLOCK,
    ApiErrorId,
    accept_deployment,
    assert_wellness_check,
    check_in_deployment,
    create_fob_site,
    demobe_deployment,
    get_deployment,
    get_fob_site,
    list_deployment_wellness_checks,
    make_deployable_volunteer,
    offer_deployment,
    set_clock,
    setup_accepted_deployment,
    setup_on_site_deployment,
    setup_open_operation,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_stipend_provisional_uses_planned_duration(api):
    """PRD §3.4: "The **provisional** variant, computed at acceptance and stored in `stipend_provisional_cents`, takes its day count from the operation's `duration_days` — the forward-looking plan."
    PRD §3.4: "first determine the day count; then the per-diem subtotal is the day count multiplied by the daily per-diem of 6500 cents (`PER_DIEM_DAILY_CENTS`); then the travel tier is `LONG` when the per-diem subtotal reaches 200000 cents (`TRAVEL_TIER_THRESHOLD_CENTS`) and `SHORT` below it — the tier is keyed on the per-diem subtotal alone, which resolves the apparent circularity between tier and total; then the travel allowance is 45000 cents (`TRAVEL_TIER_LONG_CENTS`) for the long tier or 15000 cents (`TRAVEL_TIER_SHORT_CENTS`) for the short; finally the stipend is the per-diem subtotal plus the travel allowance, an exact integer number of cents."

    Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_divergence
    """
    bundle = setup_accepted_deployment()
    deployment = get_deployment(bundle["deployment"]["id"])
    assert deployment["status"] == "ACCEPTED"
    # 4 planned days x 6500 = 26000 (< 200000 threshold) + SHORT tier 15000.
    assert deployment["stipend_provisional_cents"] == 41000
    assert deployment["stipend_final_cents"] is None


def test_stipend_final_uses_actual_days_and_diverges(api):
    """PRD §3.4: "The **final** variant, computed at demobilization and stored in `stipend_final_cents`, takes its day count from the chronological actuals: the elapsed time from `checked_in_at` to `demobed_at`, divided by 24 hours and rounded up to a whole day, with a minimum of 1 day."
    PRD §3.4: "**The stipend** is computed twice, by the same pinned recipe with a different day count, which is why the provisional and final figures differ whenever actual days on site differ from the plan."

    Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_divergence
    """
    bundle = setup_on_site_deployment()  # checked in at 2026-09-10T08:00:00Z
    set_clock("2026-09-12T17:00:00Z")
    demobe_deployment(bundle["deployment"]["id"])
    deployment = get_deployment(bundle["deployment"]["id"])
    assert deployment["status"] == "DEMOBED"
    # 57 elapsed hours -> ceil(57/24) = 3 days -> 3 x 6500 + 15000.
    assert deployment["stipend_provisional_cents"] == 41000
    assert deployment["stipend_final_cents"] == 34500
    assert deployment["stipend_final_cents"] != deployment["stipend_provisional_cents"]


def _setup_lodging_stay(nightly_rate_cents=1235):
    """ON_SITE deployment with needs_lodging against a fresh FOB."""
    return setup_on_site_deployment(
        offer_overrides={"needs_lodging": True},
        with_fob={
            "name": "FOB Alpha", "bunks_total": 2,
            "nightly_rate_cents": nightly_rate_cents,
        },
    )


def test_lodging_rounds_per_night_then_sums(api):
    """PRD §3.4: "The stay length in nights is the count of UTC calendar dates from the date of `checked_in_at` inclusive to the date of `demobed_at` exclusive, with a minimum of 1 night."
    PRD §3.4: "Each night's charge is the base's `nightly_rate_cents` increased by the 7% utility surcharge (`FOB_UTILITY_SURCHARGE_PCT` of 0.07), and that product is rounded half up to integer cents per night first. The stay cost is then the night count multiplied by that per-night integer charge, and the stay cost is added into the base's `lodging_cost_cents`. Rounding only a grand total at the end is forbidden — the per-night rounding is the contract."

    Design: Difficulty/combinatorial_formula/lodging_per_night_rounding_order_pinned
    """
    bundle = _setup_lodging_stay()
    set_clock("2026-09-13T09:00:00Z")
    demobe_deployment(bundle["deployment"]["id"])
    fob = get_fob_site(bundle["operation"]["id"], bundle["fob"]["id"])
    # 3 nights (Sep 10, 11, 12) x round_half_up(1235 x 1.07) = 3 x 1321.
    assert fob["lodging_cost_cents"] == 3963
    # The forbidden sum-then-round order would yield 3964.
    assert fob["lodging_cost_cents"] != 3964


def test_lodging_stay_releases_bunk_on_demobe(api):
    """PRD §3.4: "if a bunk was held, the base's `bunks_occupied` decreases by 1 and the stay is finalized into the base's `lodging_cost_cents`"

    Design: Difficulty/combinatorial_formula/lodging_per_night_rounding_order_pinned
    """
    bundle = _setup_lodging_stay()
    set_clock("2026-09-13T09:00:00Z")
    demobe_deployment(bundle["deployment"]["id"])
    fob = get_fob_site(bundle["operation"]["id"], bundle["fob"]["id"])
    assert fob["bunks_occupied"] == 0
    deployment = get_deployment(bundle["deployment"]["id"])
    assert deployment["status"] == "DEMOBED"


def test_check_in_allocates_bunk_and_increments_occupancy(api):
    """PRD §3.4: "The bunk is allocated from the base with the most free bunks, ties broken by the earliest `created_at`; the deployment's `fob_site_id` is set to that base and its `bunks_occupied` increases by 1."

    Design: Difficulty/compensating_invariant/fob_bunk_occupancy_compensation
    """
    bundle = setup_accepted_deployment(
        offer_overrides={"needs_lodging": True},
        with_fob={"name": "FOB Alpha", "bunks_total": 2, "nightly_rate_cents": 1000},
    )
    set_clock(CHECK_IN_CLOCK)
    deployment = check_in_deployment(bundle["deployment"]["id"])
    assert deployment["status"] == "ON_SITE"
    assert deployment["fob_site_id"] == bundle["fob"]["id"]
    fob = get_fob_site(bundle["operation"]["id"], bundle["fob"]["id"])
    assert fob["bunks_occupied"] == 1


def test_demobe_restores_bunk_invariant(api, operations_lead_headers):
    """PRD §3.4: "Demobilization is a bundle of side effects: `demobed_at` is stamped with `current_utc` and `duty_status` returns to `RESTING`; if a bunk was held, the base's `bunks_occupied` decreases by 1 and the stay is finalized into the base's `lodging_cost_cents`"
    PRD §3.4: "some forward operating base of the operation must have `bunks_occupied` strictly less than `bunks_total`" (bunks_occupied tracks the deployments lodging there).

    Design: Difficulty/compensating_invariant/fob_bunk_occupancy_compensation
    """
    bundle = _setup_lodging_stay(nightly_rate_cents=1000)
    set_clock("2026-09-11T09:00:00Z")
    demobe_deployment(bundle["deployment"]["id"])
    fob = get_fob_site(bundle["operation"]["id"], bundle["fob"]["id"])
    assert fob["bunks_occupied"] == 0
    items, _meta = validate_paginated(
        api.list_deployments(
            operations_lead_headers, params={"fob_site_id": bundle["fob"]["id"]},
        )
    )
    still_lodging = [d for d in items if d["status"] in ("ON_SITE", "SAFETY_HOLD")]
    assert fob["bunks_occupied"] == len(still_lodging) == 0


def test_full_fob_rejects_lodging_check_in(api, operations_lead_headers):
    """PRD §3.4: "When the deployment's `needs_lodging` is true, a bunk must exist: some forward operating base of the operation must have `bunks_occupied` strictly less than `bunks_total` — a base at exactly full capacity admits no one, while one short by exactly one bunk admits exactly one more arrival — and if every base is full the check-in is rejected with `ERR_FOB_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/fob_full_checkin_rejected
    """
    set_clock()
    v1 = make_deployable_volunteer(full_name="Ada Voss", email="ada@x.org", skills=["CHAINSAW"])
    v2 = make_deployable_volunteer(full_name="Bo Karr", email="bo@x.org", skills=["CHAINSAW"])
    _incident, operation = setup_open_operation()
    create_fob_site(operation["id"], name="FOB Tiny", bunks_total=1, nightly_rate_cents=1000)
    d1 = offer_deployment(operation["id"], v1["id"], needs_lodging=True)
    d1 = accept_deployment(d1["id"], v1["id"])
    d2 = offer_deployment(operation["id"], v2["id"], needs_lodging=True)
    d2 = accept_deployment(d2["id"], v2["id"])
    set_clock(CHECK_IN_CLOCK)
    check_in_deployment(d1["id"])  # occupies the only bunk
    resp = api.patch_deployment(d2["id"], {"status": "ON_SITE"}, operations_lead_headers)
    validate_error(resp, ApiErrorId.ERR_FOB_CAPACITY_EXCEEDED)
    after = get_deployment(d2["id"])
    assert after["status"] == "ACCEPTED"
    assert after["fob_site_id"] is None


def test_wellness_check_requires_notes_to_resolve(api, safety_officer_headers):
    """PRD §3.4: "if the volunteer's `fatigue_hours` has reached 30 (`WELLNESS_FATIGUE_THRESHOLD_HOURS`) or the actual on-site stay spans at least 10 days (`WELLNESS_LONG_DEPLOYMENT_DAYS`), an `OPEN` `WellnessCheck` is created for the deployment with `reason` `FATIGUE_THRESHOLD` or `LONG_DEPLOYMENT` respectively."
    PRD §3.8: "A `SafetyOfficer` resolves a check by supplying non-empty `resolved_notes`, moving it to the terminal `RESOLVED` state; the notes are required, and the field stays null while the check is open."

    Design: Corner/state_machines/wellness_check_resolve_requires_notes
    """
    bundle = setup_on_site_deployment(
        volunteer_overrides={"full_name": "Long Haul", "email": "long@x.org"},
        op_overrides={"title": "Long Op", "duration_days": 14, "start_date": "2026-09-05"},
        offer_overrides={
            "planned_start": "2026-09-05T08:00:00Z",
            "planned_end": "2026-09-19T08:00:00Z",
        },
        at_clock="2026-09-05T08:00:00Z",
    )
    set_clock("2026-09-19T09:00:00Z")
    demobe_deployment(bundle["deployment"]["id"])
    checks = list_deployment_wellness_checks(bundle["deployment"]["id"])
    assert len(checks) == 1
    check = checks[0]
    assert_wellness_check(check)
    assert check["status"] == "OPEN"
    assert check["reason"] == "LONG_DEPLOYMENT"
    assert check["resolved_notes"] is None
    resp = api.patch_wellness_check(check["id"], {"status": "RESOLVED"}, safety_officer_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    data = validate_success(
        api.patch_wellness_check(
            check["id"],
            {"status": "RESOLVED", "resolved_notes": "Debrief complete; cleared for roster."},
            safety_officer_headers,
        ),
        200,
    )
    assert data["status"] == "RESOLVED"
