"""Custody transfers, the dual state dimensions, window chaining, and the
return track with its depreciation dispute window."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_valuation,
    complete_return,
    complete_transfer,
    create_case,
    create_custody_transfer_payload,
    create_valued_asset,
    decide_retention,
    dismiss_case,
    dispute_return,
    get_asset,
    initiate_return,
    intake_asset,
    make_claimant_headers,
    resolve_return_dispute,
    schedule_transfer,
    set_clock,
    submit_valuation,
    validate_created,
    validate_error,
)


def test_asset_parallel_dimensions_independent(api):
    """PRD §2.8: "An asset carries two independent state dimensions that
    evolve without lockstep coupling."
    PRD §2.8: "A valuation adjudication advances the legal track without
    touching custody; a custody transfer moves the custody track without
    touching the legal track."
    PRD §3.2: "`STORAGE` lands the asset `IN_STORAGE`, `MAINTENANCE_SHOP`
    lands it `IN_MAINTENANCE`, `OTHER` lands it `SECURED`, and
    `CLAIMANT_PREMISES` lands it `TRANSFERRED_OUT`."
    PRD §3.2: "the asset's `current_condition_grade` is overwritten with that
    arrival grade"

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_independent
    """
    case = create_case(
        case_number="26-MJ-0005", judicial_district="W.D. Tex.",
        forfeiture_type="ADMINISTRATIVE", lead_agency_code="CBP",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="sedan",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="FAIR",
    )
    valuation = submit_valuation(
        asset["id"], method="BLUE_BOOK", raw_value_cents=1_600_000,
        assessed_condition_grade="FAIR",
    )
    accept_valuation(valuation["id"])
    valued = get_asset(asset["id"])
    assert valued["custody_state"] == "INTAKE"
    assert valued["legal_state"] == "VALUED", (
        "legal moved SEIZED -> VALUATION_PENDING -> VALUED while custody "
        "stayed INTAKE"
    )

    decide_retention(asset["id"], "SELL")
    reviewing = get_asset(asset["id"])
    assert reviewing["legal_state"] == "DISPOSITION_REVIEW"
    assert reviewing["custody_state"] == "INTAKE", (
        "decide-retention moved the legal track only"
    )

    # The custody cycle IN_STORAGE -> IN_MAINTENANCE -> IN_STORAGE runs while
    # legal stays DISPOSITION_REVIEW.
    t1 = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-1",
        to_location_ref="warehouse-7",
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-02T08:00:00Z",
    )
    complete_transfer(t1["id"], "FAIR")
    t2 = schedule_transfer(
        asset["id"], to_location_kind="MAINTENANCE_SHOP",
        from_location_ref="warehouse-7", to_location_ref="shop-3",
        window_start="2026-09-02T08:00:00Z", window_end="2026-09-03T08:00:00Z",
    )
    complete_transfer(t2["id"], "FAIR")
    t3 = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="shop-3",
        to_location_ref="warehouse-7",
        window_start="2026-09-03T08:00:00Z", window_end="2026-09-04T08:00:00Z",
    )
    complete_transfer(t3["id"], "GOOD")

    after = get_asset(asset["id"])
    assert after["custody_state"] == "IN_STORAGE"
    assert after["legal_state"] == "DISPOSITION_REVIEW", (
        "three custody moves left the legal dimension untouched"
    )
    assert after["current_condition_grade"] == "GOOD", (
        "the last transfer's condition_on_arrival overwrote the grade"
    )


def test_custody_window_contiguity(api):
    """PRD §3.2: "the new transfer's `window_start` must equal the greatest
    `window_end` among the asset's non-`CANCELLED` transfers, so both a gap
    and an overlap are rejected with `ERR_CUSTODY_WINDOW_BREAK`; the asset's
    very first transfer is exempt from the chain check."

    Design: Difficulty/resource_temporal_overlap/custody_window_contiguity
    """
    case = create_case(
        case_number="26-MJ-0015", judicial_district="D. Kan.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="box van",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    t1 = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-4",
        to_location_ref="warehouse-1",
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-02T08:00:00Z",
    )
    complete_transfer(t1["id"], "GOOD")

    gap = api.create_custody_transfer(
        create_custody_transfer_payload(
            asset["id"], from_location_ref="warehouse-1",
            to_location_ref="warehouse-2", to_location_kind="STORAGE",
            window_start="2026-09-02T09:00:00Z",
            window_end="2026-09-03T09:00:00Z",
        ),
        TEST_USERS["asset_custodian_headers"],
    )
    validate_error(gap, ApiErrorId.ERR_CUSTODY_WINDOW_BREAK)

    overlap = api.create_custody_transfer(
        create_custody_transfer_payload(
            asset["id"], from_location_ref="warehouse-1",
            to_location_ref="warehouse-2", to_location_kind="STORAGE",
            window_start="2026-09-01T12:00:00Z",
            window_end="2026-09-02T12:00:00Z",
        ),
        TEST_USERS["asset_custodian_headers"],
    )
    validate_error(overlap, ApiErrorId.ERR_CUSTODY_WINDOW_BREAK)

    chained = validate_created(
        api.create_custody_transfer(
            create_custody_transfer_payload(
                asset["id"], from_location_ref="warehouse-1",
                to_location_ref="warehouse-2", to_location_kind="STORAGE",
                window_start="2026-09-02T08:00:00Z",
                window_end="2026-09-03T08:00:00Z",
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    assert chained["status"] == "SCHEDULED", (
        "exact adjacency window_start == the chain's greatest window_end "
        "chains legally"
    )


def test_complete_return_requires_physical_handover(api):
    """PRD §3.8: "The `AssetManager` completes the return by recording the
    `return_condition_grade`, and the call requires `custody_state` to be
    `TRANSFERRED_OUT` — the claimant-premises transfer must have completed
    first, otherwise `ERR_INVALID_STATE`."
    PRD §3.8: "the grade-step term is eight hundred basis points (8%) for each
    full grade step the return grade sits below the `seizure_condition_grade`"
    PRD §3.8: "The time term is fifty basis points (0.5%) for each whole
    calendar month held from `seized_on` to the current logical clock time"
    PRD §3.8: "The two terms sum and the sum is capped at six thousand basis
    points (60%); the resulting fraction of `appraised_value_cents`, rounded
    half up to whole cents, is the depreciation."

    Design: Corner/state_machines/complete_return_requires_physical_handover
    """
    set_clock("2026-09-05T08:00:00Z")
    case = create_case(
        case_number="26-MJ-1014", judicial_district="S.D. Fla.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="convertible",
        seized_on="2026-09-05T00:00:00Z", seizure_condition_grade="GOOD",
    )
    valuation = submit_valuation(
        asset["id"], method="CERTIFIED_APPRAISAL", raw_value_cents=2_000_000,
        assessed_condition_grade="GOOD",
    )
    accept_valuation(valuation["id"])
    storage = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-7",
        to_location_ref="warehouse-3",
        window_start="2026-09-05T09:00:00Z", window_end="2026-09-06T09:00:00Z",
    )
    complete_transfer(storage["id"], "GOOD")
    dismiss_case(case["id"])
    initiate_return(asset["id"])

    early = api.complete_return(
        asset["id"], "POOR", TEST_USERS["asset_manager_headers"]
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    assert early.status_code == 409, (
        "custody is RELEASED_FOR_RETURN, not yet TRANSFERRED_OUT"
    )

    handover = schedule_transfer(
        asset["id"], to_location_kind="CLAIMANT_PREMISES",
        from_location_ref="warehouse-3", to_location_ref="claimant-home",
        window_start="2026-09-06T09:00:00Z", window_end="2026-09-07T09:00:00Z",
    )
    complete_transfer(handover["id"], "POOR")
    handed = get_asset(asset["id"])
    assert handed["custody_state"] == "TRANSFERRED_OUT"
    assert handed["current_condition_grade"] == "POOR"

    set_clock("2026-12-10T00:00:00Z")
    done = complete_return(asset["id"], "POOR")
    assert done["legal_state"] == "RETURNED"
    assert done["returned_at"] == "2026-12-10T00:00:00Z"
    # GOOD -> POOR is 2 grade steps (1600 bps) plus 3 whole months held
    # (150 bps) = 1750 bps of appraised 1800000.
    assert done["computed_depreciation_cents"] == 315_000


def test_dispute_after_window_expired_rejected(api):
    """PRD §3.8: "the call requires the current logical clock time to be no
    later than `returned_at` plus those thirty days — a later attempt is
    rejected with `ERR_DISPUTE_WINDOW_EXPIRED`."
    PRD §3.8: "That computed depreciation is zero when the asset was never
    appraised — a null `appraised_value_cents` yields zero."

    Design: Corner/errors/dispute_after_window_expired_rejected
    """
    case = create_case(
        case_number="26-MJ-1029", judicial_district="D. Colo.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="wagon",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    storage = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-3",
        to_location_ref="warehouse-4",
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-02T08:00:00Z",
    )
    complete_transfer(storage["id"], "GOOD")
    dismiss_case(case["id"])
    initiate_return(asset["id"])
    handover = schedule_transfer(
        asset["id"], to_location_kind="CLAIMANT_PREMISES",
        from_location_ref="warehouse-4", to_location_ref="claimant-home",
        window_start="2026-09-02T08:00:00Z", window_end="2026-09-03T08:00:00Z",
    )
    complete_transfer(handover["id"], "GOOD")
    set_clock("2026-09-10T00:00:00Z")
    done = complete_return(asset["id"], "GOOD")
    assert done["computed_depreciation_cents"] == 0, (
        "no ACCEPTED valuation: the null-appraisal path yields zero"
    )
    assert done["returned_at"] == "2026-09-10T00:00:00Z"

    set_clock("2026-10-11T00:00:00Z")
    resp = api.dispute_return(
        asset["id"], 100_000, make_claimant_headers("cl-orma")
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)
    assert resp.status_code == 409, (
        "2026-10-11 is past returned_at + 30 days (2026-10-10)"
    )
    assert get_asset(asset["id"])["legal_state"] == "RETURNED"


def test_resolve_depreciation_exceeds_value_then_resolves(api):
    """PRD §3.8: "A `CourtOfficial` then resolves the dispute by fixing
    `final_depreciation_cents`, which must not exceed the asset's
    `appraised_value_cents`; an over-value adjudication is rejected with
    `ERR_DEPRECIATION_EXCEEDS_VALUE`"
    PRD §3.8: "A valid dispute records the assertion as
    `dispute_claimed_depreciation_cents` and moves the legal track from
    `RETURNED` to `DISPUTED`."
    PRD §3.8: "Resolution records the adjudicated figure on the asset and
    moves the legal track from `DISPUTED` to `RESOLVED`, terminal."

    Design: Corner/errors/resolve_depreciation_exceeds_value_then_resolves
    """
    case = create_case(
        case_number="26-MJ-1030", judicial_district="S.D. Fla.",
        forfeiture_type="CIVIL", lead_agency_code="FBI",
    )
    asset, _valuation = create_valued_asset(
        case["id"], raw_value_cents=2_000_000, grade="GOOD",
        method="CERTIFIED_APPRAISAL", description="roadster",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    storage = schedule_transfer(
        asset["id"], to_location_kind="STORAGE", from_location_ref="impound-5",
        to_location_ref="warehouse-6",
        window_start="2026-09-01T08:00:00Z", window_end="2026-09-02T08:00:00Z",
    )
    complete_transfer(storage["id"], "GOOD")
    dismiss_case(case["id"])
    initiate_return(asset["id"])
    handover = schedule_transfer(
        asset["id"], to_location_kind="CLAIMANT_PREMISES",
        from_location_ref="warehouse-6", to_location_ref="claimant-home",
        window_start="2026-09-02T08:00:00Z", window_end="2026-09-03T08:00:00Z",
    )
    complete_transfer(handover["id"], "POOR")
    set_clock("2026-09-10T00:00:00Z")
    complete_return(asset["id"], "POOR")
    set_clock("2026-09-20T00:00:00Z")
    dispute_return(asset["id"], 500_000, "cl-orma")

    disputed = get_asset(asset["id"])
    assert disputed["legal_state"] == "DISPUTED"
    assert disputed["dispute_claimed_depreciation_cents"] == 500_000, (
        "the dispute at 2026-09-20 is inside returned_at + 30 days"
    )

    over = api.resolve_return_dispute(
        asset["id"], 1_800_001, TEST_USERS["court_official_headers"]
    )
    validate_error(over, ApiErrorId.ERR_DEPRECIATION_EXCEEDS_VALUE)
    assert over.status_code == 422, (
        "1800001 exceeds the appraised 1800000"
    )

    resolved = resolve_return_dispute(asset["id"], 300_000)
    assert resolved["legal_state"] == "RESOLVED"
    assert resolved["final_depreciation_cents"] == 300_000
