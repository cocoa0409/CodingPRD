"""Collateral-side refusals: labels, placement fields, the clock, filings, conversion.

Every case here is a request the platform must turn away, and several of them
violate two rules at once so that the ladder of §2.7 decides which refusal the
caller actually sees. The refused writes must also leave nothing behind — no row,
no version bump, no moved clock.
"""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assert_lien_filing,
    assert_manufactured_unit,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
LATER_CLOCK = "2026-09-01T00:00:00Z"
BACKWARD_CLOCK = "2026-08-15T00:00:00Z"

DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}
PINE_RIDGE = {
    "name": "Pine Ridge MHC",
    "state_code": "GA",
    "lot_count": 180,
    "monthly_lot_rent_cents": 52000,
}

# ─── One label, two parcels ───
SHARED_HUD_LABEL = "ALB0412345"
FIRST_PARCEL = {"land_parcel_apn": "072-114-003", "land_county": "Bibb"}
SECOND_PARCEL = {"land_parcel_apn": "072-990-114", "land_county": "Bibb"}
FIRST_MODEL_YEAR = 2018
SECOND_UNIT = {
    "model_year": 2020,
    "width_class": "SINGLE_WIDE",
    "square_feet": 980,
    "condition_grade": "EXCELLENT",
    "installation_type": "PIER_AND_ANCHOR",
    "wind_zone": 1,
}
CONTESTED_LOT = "A-14"
OTHER_LOT = "B-02"

# ─── A guide that is real but not yet in force ───
FUTURE_GUIDE = {
    "guide_edition": "NADA-2026-FALL",
    "effective_date": LATER_CLOCK,
    "base_value_per_sqft_cents": 4600,
}

# ─── The loan whose lien never gets perfected ───
PRINCIPAL_CENTS = 1500000
REQUESTED_TERM_MONTHS = 240
FOUNDATION_UNIT = {"installation_type": "PERMANENT_FOUNDATION", "wind_zone": 1}
PIERED_UNIT = {"installation_type": "PIER_AND_ANCHOR", "wind_zone": 2}
MAX_FILING_ATTEMPTS = 3


def _borrower(api):
    """One obligor, on a clock pinned to the platform's own default instant."""
    fixtures.set_clock(api, CLOCK)
    return fixtures.register_borrower(api, **DANA)


def _unit_holding_the_shared_label(api, borrower_id):
    """The first unit to claim ALB0412345, sitting on the first parcel."""
    return fixtures.register_private_land_unit(
        api,
        borrower_id,
        hud_label_number=SHARED_HUD_LABEL,
        model_year=FIRST_MODEL_YEAR,
        **FIRST_PARCEL,
    )


def _draft_loan_on_a_private_parcel(api, unit_overrides):
    """A DRAFT loan whose collateral is an unconverted private-land unit."""
    scenario = fixtures.setup_private_land_collateral(
        api,
        clock=CLOCK,
        borrower_overrides=DANA,
        unit_overrides=unit_overrides,
        record_documents=False,
    )
    scenario["valuation"] = fixtures.create_certified_valuation(
        api, scenario["unit"]["id"], scenario["guide"]["id"]
    )
    scenario["loan"] = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        scenario["valuation"]["id"],
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    return scenario


def test_a_hud_label_is_unique_across_the_platform_not_across_a_parcel(api):
    """PRD §3.2: "Registering a second unit under a `hud_label_number` another unit
    already carries is refused with `ERR_DUPLICATE_HUD_LABEL` (HTTP 409)."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that starts
    at 1 and increments by exactly one on every mutation."

    Design: Corner/validations/second_unit_reusing_a_hud_label_is_refused
    """
    borrower = _borrower(api)
    incumbent = _unit_holding_the_shared_label(api, borrower["id"])
    assert_manufactured_unit(incumbent)
    assert incumbent["hud_label_number"] == SHARED_HUD_LABEL
    assert incumbent["version"] == 1

    validate_error(
        api.create_unit(
            factories.private_land_unit_payload(
                borrower["id"],
                hud_label_number=SHARED_HUD_LABEL,
                **SECOND_PARCEL,
                **SECOND_UNIT,
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_DUPLICATE_HUD_LABEL.value,
        409,
    )

    rows, meta = validate_paginated(api.list_units(fixtures.CLOSER))
    assert meta["total_count"] == 1, (
        "an entirely different parcel is no defence: the refused create persisted "
        "nothing"
    )
    assert rows[0]["id"] == incumbent["id"]

    survivor = fixtures.read_unit(api, incumbent["id"])
    assert survivor["model_year"] == FIRST_MODEL_YEAR
    assert survivor["version"] == 1, "the refusal did not mutate the sitting unit"


def test_a_private_land_payload_must_leave_the_community_slot_empty(api):
    """PRD §3.2: "A private-land placement requires a non-null
    `land_owner_borrower_id` naming the fee owner of the parcel, a `land_parcel_apn`
    (the assessor parcel number), and a `land_county` (the recording county for the
    land-home instruments), and it requires `community_id` to be null. Any other
    combination — community fields on private land, or land fields on a community lot —
    is rejected with `ERR_PLACEMENT_FIELDS_INCONSISTENT` (HTTP 422)."
    PRD §2.7: "Requests are validated in a fixed order and the first failure wins; no
    later check may mask an earlier one."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."

    Design: Corner/validations/private_land_unit_carrying_a_community_id_is_refused
    """
    borrower = _borrower(api)
    community = fixtures.register_community(api, **PINE_RIDGE)

    validate_error(
        api.create_unit(
            factories.private_land_unit_payload(
                borrower["id"],
                community_id=community["id"],
                lot_number=CONTESTED_LOT,
                placement_start_date=CLOCK,
                **FIRST_PARCEL,
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_PLACEMENT_FIELDS_INCONSISTENT.value,
        422,
    )

    assert fixtures.read_community(api, community["id"])["version"] == 1, (
        "both references were real, so the payload is not a bad-reference failure"
    )
    _, meta = validate_paginated(
        api.list_units(fixtures.CLOSER, {"community_id": community["id"]})
    )
    assert meta["total_count"] == 0, (
        "the platform refused rather than silently preferring one of the two "
        "placements"
    )


def test_the_duplicate_label_is_reported_before_the_placement_contradiction(api):
    """PRD §2.7: "Requests are validated in a fixed order and the first failure wins;
    no later check may mask an earlier one."
    PRD §2.7: "Below the shape layer come the domain-specific checks, in this order:
    guide effectiveness for a valuation; duplicate HUD label, placement-field
    consistency and lot-occupancy conflict for a unit registration; the two
    stale-version checks of §2.9, with the unit check on valuation creation preceding
    the loan check on policy creation; then the state-machine gates — unit
    classification state, recovery hold, valuation certifiability, operator-agreement
    state, filing state, recovery-path availability, recovery-case state, loan
    underwriting state, loan servicing state, and payment-reversal eligibility, in
    that sequence."
    PRD §3.2: "Registering a second unit under a `hud_label_number` another unit
    already carries is refused with `ERR_DUPLICATE_HUD_LABEL` (HTTP 409)."
    PRD §3.2: "Any other combination — community fields on private land, or land
    fields on a community lot — is rejected with `ERR_PLACEMENT_FIELDS_INCONSISTENT`
    (HTTP 422)."

    Design: Corner/validations/duplicate_label_error_precedes_inconsistent_placement_error
    """
    borrower = _borrower(api)
    community = fixtures.register_community(api, **PINE_RIDGE)
    incumbent = _unit_holding_the_shared_label(api, borrower["id"])

    validate_error(
        api.create_unit(
            factories.private_land_unit_payload(
                borrower["id"],
                hud_label_number=SHARED_HUD_LABEL,
                community_id=community["id"],
                lot_number=OTHER_LOT,
                placement_start_date=CLOCK,
                **SECOND_PARCEL,
                **SECOND_UNIT,
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_DUPLICATE_HUD_LABEL.value,
        409,
    )

    rows, meta = validate_paginated(api.list_units(fixtures.CLOSER))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == incumbent["id"]
    assert rows[0]["model_year"] == FIRST_MODEL_YEAR


def test_a_stored_guide_that_is_not_yet_in_force_cannot_be_cited(api):
    """PRD §3.3: "The cited guide must already be in force: if its `effective_date` is
    after the logical clock, the request is refused with `ERR_GUIDE_NOT_EFFECTIVE`
    (HTTP 422)."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that starts
    at 1 and increments by exactly one on every mutation."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."

    Design: Corner/validations/valuation_against_a_guide_not_yet_effective_is_refused
    """
    borrower = _borrower(api)
    guide = fixtures.publish_guide(api, **FUTURE_GUIDE)
    unit = fixtures.register_private_land_unit(api, borrower["id"], **FIRST_PARCEL)
    assert_instant_equals(
        guide["effective_date"], LATER_CLOCK, "BookValueGuide.effective_date"
    )

    validate_error(
        api.create_valuation(
            factories.valuation_payload(
                unit["id"], guide["id"], unit["version"], "ORIGINATION"
            ),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_GUIDE_NOT_EFFECTIVE.value,
        422,
    )

    assert fixtures.read_unit(api, unit["id"])["version"] == unit["version"], (
        "a refused valuation does not bump the unit it was going to value"
    )
    _, meta = validate_paginated(
        api.list_valuations(fixtures.ANALYST, {"unit_id": unit["id"]})
    )
    assert meta["total_count"] == 0


def test_the_clock_accepts_the_instant_it_already_holds_but_never_an_earlier_one(api):
    """PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`, and the server must not fall back to real time in that
    state."
    PRD §2.4: "The clock may only move forward or stay where it is; a request that
    would move it backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Setting
    the clock mutates no entity — it only changes what subsequent reads of the clock
    return, which is echoed back as `current_utc`."

    Design: Corner/validations/clock_may_stand_still_but_never_run_backwards
    """
    advanced = validate_success(api.set_clock(LATER_CLOCK, fixtures.ADMIN))
    assert_instant_equals(advanced["current_utc"], LATER_CLOCK, "clock.current_utc")

    validate_error(
        api.set_clock(BACKWARD_CLOCK, fixtures.ADMIN),
        ApiErrorId.ERR_CLOCK_REGRESSION.value,
        422,
    )

    standing_still = validate_success(api.set_clock(LATER_CLOCK, fixtures.ADMIN))
    assert_instant_equals(
        standing_still["current_utc"], LATER_CLOCK, "clock.current_utc"
    )
    assert standing_still["current_utc"] == advanced["current_utc"], (
        "the rejected instant was still ahead of the platform's default, yet it was "
        "behind the clock, so it never landed"
    )


def test_the_wrong_instrument_is_reported_before_the_missing_documents(api):
    """PRD §3.5: "The chosen instrument must match the loan's
    `collateral_classification` — title lien for `PERSONAL_PROPERTY`, deed of trust for
    `REAL_PROPERTY` — and a mismatch is refused with `ERR_FILING_TYPE_MISMATCH`
    (HTTP 422)."
    PRD §3.5: "A title lien requires both `TITLE_APPLICATION` and `LIEN_ENTRY_FORM`. A
    land-home deed of trust requires all three of `DEED_OF_TRUST`,
    `AFFIXATION_AFFIDAVIT` and `TITLE_SURRENDER_RECEIPT`. The platform records the
    shortfall in `missing_documents`, which holds exactly those required codes for the
    chosen `filing_type` that are absent from `submitted_documents`. A tender that
    omits any required code is refused with `ERR_FILING_DOCUMENTS_INCOMPLETE`
    (HTTP 422), and the same document check applies again on every re-tender."
    PRD §2.7: "Only after all of those does the system evaluate the substantive credit,
    perfection, insurance and cash rules: segregation of duties, then valuation variant
    suitability, then filing-type match, filing document completeness and the filing
    attempt limit, then insurance date ordering and coverage-period overlap, then
    land-document completeness for a conversion, then the three funding insurance gates
    (existence of active coverage, wind endorsement sufficiency, dwelling coverage
    sufficiency), then force-placement eligibility, then the operator-agreement
    requirement for funding, then lender access rights for possession, then perfection
    establishment, then the LTV cap and the term floor, then borrower suspension, then
    the exposure cap, then default eligibility, then the cure-period,
    redemption-window-open and redemption-window-closed timing checks, and finally the
    two cash-integrity checks on a payment: overpayment refusal and payoff-amount
    exactness."
    PRD §3.2: "Every newly registered unit starts with `classification` at
    `PERSONAL_PROPERTY`, `title_status` at `ACTIVE_TITLE`, `recovery_hold` false, and
    both land-document flags — `deed_recorded` and `affixation_affidavit_recorded` —
    false."
    PRD §2.10: "A unit's classification is snapshotted onto every loan written against
    it, and when the unit's classification changes the snapshot on every non-terminal
    loan is re-synced."
    PRD §3.4: "A new loan starts with `underwriting_state` `DRAFT`, `servicing_state`
    `NOT_SERVICING` and `perfection_state` `UNPERFECTED`."

    Design: Corner/validations/filing_type_mismatch_error_precedes_incomplete_documents_error
    """
    scenario = _draft_loan_on_a_private_parcel(api, FOUNDATION_UNIT)
    loan_id = scenario["loan"]["id"]
    assert scenario["unit"]["classification"] == "PERSONAL_PROPERTY"
    assert scenario["loan"]["collateral_classification"] == "PERSONAL_PROPERTY"

    validate_error(
        api.create_lien_filing(
            factories.deed_of_trust_payload(
                loan_id, submitted_documents=["DEED_OF_TRUST"]
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_FILING_TYPE_MISMATCH.value,
        422,
    )

    validate_error(
        api.create_lien_filing(
            factories.title_lien_payload(
                loan_id, submitted_documents=["TITLE_APPLICATION"]
            ),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_FILING_DOCUMENTS_INCOMPLETE.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_lien_filings(fixtures.CLOSER, {"loan_id": loan_id})
    )
    assert meta["total_count"] == 0, "neither refused tender opened a filing"
    assert fixtures.read_loan(api, loan_id)["perfection_state"] == "UNPERFECTED"


def test_the_ceiling_is_checked_before_the_increment_so_only_the_fourth_tender_fails(api):
    """PRD §3.5: "A successful tender copies `unit_id` onto the filing from the loan's
    collateral — the caller never supplies it — computes `missing_documents`, opens the
    filing at `status` `SUBMITTED` with `attempt_number` 1, and advances the loan's lien
    dimension from `UNPERFECTED` to `FILING_SUBMITTED` while incrementing the loan's
    `version`. The new filing's `agency_reference`, `rejection_code`, `recorded_at` and
    `released_at` all start null."
    PRD §3.5: "The recording office answers through a `PlatformAdmin`, who reports an
    `outcome` of either `RECORDED` or `REJECTED` on a filing whose `status` is
    `SUBMITTED`. Reporting an outcome on a filing that is not `SUBMITTED` is refused
    with `ERR_FILING_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "A `REJECTED` outcome moves the filing from `SUBMITTED` to `REJECTED`,
    stores the supplied `rejection_code` — one of `MISSING_DOCUMENT`, `NAME_MISMATCH` or
    `FEE_SHORTFALL` — and returns the loan's lien dimension from `FILING_SUBMITTED` to
    `UNPERFECTED`."
    PRD §3.5: "A `ClosingAgent` re-tenders a `REJECTED` filing with a corrected
    `submitted_documents` list, which moves the filing back from `REJECTED` to
    `SUBMITTED`, increases `attempt_number` by exactly one, clears `rejection_code` back
    to null, recomputes `missing_documents` from the new list, and returns the loan's
    lien dimension from `UNPERFECTED` to `FILING_SUBMITTED`, incrementing the loan's
    `version`. Patience is finite: three attempts is the ceiling, so a re-tender is only
    permitted while `attempt_number` is still below 3 at the moment of the call, and an
    attempt beyond that is refused with `ERR_FILING_ATTEMPT_LIMIT` (HTTP 409)."
    PRD §3.5: "When the recorded instrument is a `TITLE_LIEN`, it additionally moves the
    unit's `title_status` from `ACTIVE_TITLE` to `TITLE_ENCUMBERED`, because the state
    has now noted the lender on the certificate of title."

    Design: Corner/validations/fourth_filing_attempt_is_refused_at_the_attempt_limit
    """
    scenario = _draft_loan_on_a_private_parcel(api, PIERED_UNIT)
    loan_id = scenario["loan"]["id"]
    filing = fixtures.tender_filing(api, factories.title_lien_payload(loan_id))
    filing_id = filing["id"]

    assert_lien_filing(filing)
    assert filing["attempt_number"] == 1
    assert filing["status"] == "SUBMITTED"
    assert filing["missing_documents"] == []
    assert filing["agency_reference"] is None
    assert filing["unit_id"] == scenario["unit"]["id"]

    first_rejection = fixtures.record_filing_outcome(
        api, filing_id, "REJECTED", rejection_code="NAME_MISMATCH"
    )
    assert first_rejection["status"] == "REJECTED"
    assert first_rejection["rejection_code"] == "NAME_MISMATCH"
    assert fixtures.read_loan(api, loan_id)["perfection_state"] == "UNPERFECTED"

    validate_error(
        api.agency_response(
            filing_id,
            factories.agency_response_payload(
                "RECORDED", factories.unique_agency_reference()
            ),
            fixtures.ADMIN,
        ),
        ApiErrorId.ERR_FILING_INVALID_STATE.value,
        409,
    )

    for attempt, rejection_code in ((2, "FEE_SHORTFALL"), (3, "MISSING_DOCUMENT")):
        retendered = validate_success(
            api.resubmit_lien_filing(
                filing_id,
                factories.resubmit_payload(["TITLE_APPLICATION", "LIEN_ENTRY_FORM"]),
                fixtures.CLOSER,
            )
        )
        assert retendered["attempt_number"] == attempt
        assert retendered["status"] == "SUBMITTED"
        assert retendered["rejection_code"] is None
        fixtures.record_filing_outcome(
            api, filing_id, "REJECTED", rejection_code=rejection_code
        )

    validate_error(
        api.resubmit_lien_filing(
            filing_id,
            factories.resubmit_payload(["TITLE_APPLICATION", "LIEN_ENTRY_FORM"]),
            fixtures.CLOSER,
        ),
        ApiErrorId.ERR_FILING_ATTEMPT_LIMIT.value,
        409,
    )

    exhausted = fixtures.read_filing(api, filing_id)
    assert exhausted["attempt_number"] == MAX_FILING_ATTEMPTS, (
        "the refused fourth tender did not consume an attempt"
    )
    assert exhausted["status"] == "REJECTED"
    assert exhausted["rejection_code"] == "MISSING_DOCUMENT"
    assert exhausted["agency_reference"] is None
    assert exhausted["recorded_at"] is None
    assert fixtures.read_loan(api, loan_id)["perfection_state"] == "UNPERFECTED"
    assert fixtures.read_unit(api, scenario["unit"]["id"])["title_status"] == (
        "ACTIVE_TITLE"
    ), "no recording ever happened, so the certificate of title is unencumbered"


def test_each_conversion_action_demands_its_own_source_classification(api):
    """PRD §3.8: "An `action` that does not match the unit's current classification —
    initiating from anything but `PERSONAL_PROPERTY`, completing from anything but
    `CONVERSION_PENDING`, rescinding from anything but `REAL_PROPERTY` — is refused with
    `ERR_UNIT_CLASSIFICATION_INVALID_STATE` (HTTP 409). Every conversion call increments
    the unit's `version`."
    PRD §3.8: "It is nonetheless gated on real paperwork: the unit's `placement_type`
    must be `PRIVATE_LAND`, and both `deed_recorded` and `affixation_affidavit_recorded`
    must already be true. A unit on a community lot, or one missing either land
    document, is refused with `ERR_LAND_DOCUMENTS_INCOMPLETE` (HTTP 409)."
    PRD §3.2: "Every newly registered unit starts with `classification` at
    `PERSONAL_PROPERTY`, `title_status` at `ACTIVE_TITLE`, `recovery_hold` false, and
    both land-document flags — `deed_recorded` and `affixation_affidavit_recorded` —
    false."

    Design: Corner/validations/rescinding_a_classification_that_was_never_converted_is_refused
    """
    borrower = _borrower(api)
    unit = fixtures.register_private_land_unit(
        api, borrower["id"], **FIRST_PARCEL, **FOUNDATION_UNIT
    )
    assert unit["classification"] == "PERSONAL_PROPERTY"
    assert unit["deed_recorded"] is False
    assert unit["affixation_affidavit_recorded"] is False

    for action in ("RESCIND", "COMPLETE"):
        validate_error(
            api.convert_classification(unit["id"], action, fixtures.CLOSER),
            ApiErrorId.ERR_UNIT_CLASSIFICATION_INVALID_STATE.value,
            409,
        )

    validate_error(
        api.convert_classification(unit["id"], "INITIATE", fixtures.CLOSER),
        ApiErrorId.ERR_LAND_DOCUMENTS_INCOMPLETE.value,
        409,
    )

    untouched = fixtures.read_unit(api, unit["id"])
    assert untouched["classification"] == "PERSONAL_PROPERTY", (
        "INITIATE cleared the classification gate and was stopped by the paperwork "
        "gate instead, and neither refusal moved the unit"
    )
    assert untouched["version"] == unit["version"]
    assert untouched["deed_recorded"] is False
    assert untouched["affixation_affidavit_recorded"] is False
