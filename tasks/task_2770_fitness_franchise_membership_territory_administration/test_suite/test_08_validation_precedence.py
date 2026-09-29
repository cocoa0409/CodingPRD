"""Two precedence pairs where the earlier band must win over a genuine later violation.

Signing at a suspended club with a below-floor quote breaks a facility gate and a money
gate at once; filing an over-cap promotion into an occupied window breaks a territory-band
gate and a date-window gate at once. The follow-up call in each pair proves the later
violation was real all along.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_approved_promotion,
    create_member,
    create_promotion_payload,
    inspect_club,
    make_club_manager_headers,
    make_franchise_owner_headers,
    read_club,
    read_club_version,
    read_promotion,
    setup_single_club_franchise,
    waive_remediation,
)

BRAND = TEST_USERS["brand_administrator_headers"]


def _suspended_club_with_a_below_floor_quote() -> dict:
    """A club suspended by a failing inspection, plus an approved 30 percent promotion that
    prices the plan at 3150 cents against a 3600-cent floor."""
    scenario = setup_single_club_franchise(
        legal_name="Crestwood Fitness LLC",
        contact_email="ops@crestwoodfit.example",
        club_name="Crestwood Club",
    )
    scenario["promotion"] = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="DEEP30",
        discount_pct=0.30,
        starts_on="2026-08-01",
        ends_on="2026-08-31",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"],
        full_name="Rhea Sandoval",
        email="rhea.sandoval@example.com",
    )
    scenario["inspection"] = inspect_club(scenario["club"]["id"], "2026-07-15", 60, 60, 60, 60)
    return scenario


def _attempt_to_sign(scenario: dict):
    """One signing attempt quoting the deep discount, with a freshly read club version."""
    payload = create_agreement_payload(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        read_club_version(scenario["club"]["id"]),
        signed_on="2026-08-01",
        multi_club_access=False,
        promotion_id=scenario["promotion"]["id"],
    )
    return api_client.create_agreement(payload, make_club_manager_headers(scenario["club"]["id"]))


def _approved_quarter_long_promotion() -> dict:
    """An APPROVED promotion holding the whole of 2026-07-01 through 2026-09-30 on one
    franchisee-and-template channel."""
    scenario = setup_single_club_franchise(
        legal_name="Ironhaven Fitness LLC",
        contact_email="ops@ironhavenfit.example",
        club_name="Ironhaven Club",
    )
    scenario["existing_promotion"] = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="Q3BASE",
        discount_pct=0.10,
        starts_on="2026-07-01",
        ends_on="2026-09-30",
    )
    return scenario


def _file_promotion(scenario: dict, code: str, discount_pct: float):
    payload = create_promotion_payload(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code=code,
        discount_pct=discount_pct,
        starts_on="2026-08-01",
        ends_on="2026-08-31",
    )
    return api_client.create_promotion(
        payload, make_franchise_owner_headers(scenario["franchisee"]["id"])
    )


def test_facility_gate_answers_first_when_the_quote_is_also_below_the_floor():
    """Both the facility gate and the money gate are unsatisfied, and the facility band is
    evaluated earlier, so the caller learns the club is not operational.

    PRD 2.6: "The first band that rejects wins, and no later band is consulted; this matters
    because several bands can be simultaneously unsatisfied and the caller must receive the
    earlier code."

    Design: Difficulty/priority_pair_validation_conflict/facility_safety_gate_outranks_price_floor_on_agreement_create
    """
    scenario = _suspended_club_with_a_below_floor_quote()

    response = _attempt_to_sign(scenario)
    validate_error(response, ApiErrorId.ERR_CLUB_NOT_OPERATIONAL.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PRICE_BELOW_FLOOR.value


def test_a_non_compliant_club_is_barred_from_signing_at_all():
    """The inspection scored 51, which is what put the club into both a suspended status and
    a non-compliant equipment state at the moment of the attempt.

    PRD 3.3: "The home club must be `OPEN`, and its `equipment_compliance_state` must not be
    `NON_COMPLIANT`; either failure is refused with `ERR_CLUB_NOT_OPERATIONAL`."

    Design: Difficulty/priority_pair_validation_conflict/facility_safety_gate_outranks_price_floor_on_agreement_create
    """
    scenario = _suspended_club_with_a_below_floor_quote()

    assert scenario["inspection"]["score"] == 51
    assert scenario["inspection"]["status"] == "REMEDIATION_REQUIRED"
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "NON_COMPLIANT"
    assert club["status"] == "SUSPENDED"


def test_waiving_remediation_returns_the_club_to_service_on_watch():
    """A different auditor forgives the finding, which lifts the suspension and leaves the
    club on watch rather than compliant.

    PRD 3.9: "The waiver sets the club's `equipment_compliance_state` to `WATCH` — leaving
    `last_inspection_score` untouched, because the failing score is a historical fact — and
    returns a `SUSPENDED` club to `OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/facility_safety_gate_outranks_price_floor_on_agreement_create
    """
    scenario = _suspended_club_with_a_below_floor_quote()

    waived = waive_remediation(
        scenario["inspection"]["id"],
        auditor_id="auditor-2",
        reason="Replacement cardio floor already on order",
    )
    assert waived["status"] == "REMEDIATION_WAIVED"
    club = read_club(scenario["club"]["id"])
    assert club["equipment_compliance_state"] == "WATCH"
    assert club["status"] == "OPEN"
    assert club["last_inspection_score"] == 51


def test_money_gate_surfaces_once_the_facility_gate_is_satisfied():
    """With the club back in service the same request is refused for the reason that was
    always there: 4500 less 1350 is 3150, below the 3600-cent floor.

    PRD 3.3: "If the gross monthly dues computed above fall below the template's
    `floor_price_cents`, the signing is refused with `ERR_PRICE_BELOW_FLOOR` and no agreement
    is created; nothing is quietly lifted up to the floor."

    Design: Difficulty/priority_pair_validation_conflict/facility_safety_gate_outranks_price_floor_on_agreement_create
    """
    scenario = _suspended_club_with_a_below_floor_quote()
    waive_remediation(scenario["inspection"]["id"], auditor_id="auditor-2")

    response = _attempt_to_sign(scenario)
    validate_error(response, ApiErrorId.ERR_PRICE_BELOW_FLOOR.value)


def test_neither_refused_attempt_leaves_an_agreement_behind():
    """Both refusals are hard gates, so the club has no memberships at all and its live
    count is still zero.

    PRD 3.3: "What signing does *not* do is move the club's `active_agreement_count`: a
    `PENDING` agreement is not yet an active membership, and the counter only moves when the
    first payment lands, as §3.4 describes."

    Design: Difficulty/priority_pair_validation_conflict/facility_safety_gate_outranks_price_floor_on_agreement_create
    """
    scenario = _suspended_club_with_a_below_floor_quote()
    _attempt_to_sign(scenario)
    waive_remediation(scenario["inspection"]["id"], auditor_id="auditor-2")
    _attempt_to_sign(scenario)

    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0
    agreements, meta = validate_paginated(
        api_client.list_agreements(BRAND, params={"home_club_id": scenario["club"]["id"]})
    )
    assert meta["total_count"] == 0
    assert agreements == []


def test_discount_cap_answers_before_the_window_conflict_on_a_filing():
    """The filing breaks the brand cap and collides with an approved window at once, and the
    territory-and-uniqueness band is consulted before the date-window band.

    PRD 2.6: "**Territory protection and uniqueness.** `ERR_TERRITORY_ENCROACHMENT`,
    `ERR_TERRITORY_OCCUPIED`, `ERR_RELOCATION_PENDING`, `ERR_RELOCATION_REVISION_LIMIT`,
    `ERR_DISCOUNT_CAP_EXCEEDED`, `ERR_DUPLICATE_SETTLEMENT_PERIOD` and
    `ERR_DUPLICATE_ROYALTY_PERIOD`, all 409."

    Design: Difficulty/priority_pair_validation_conflict/discount_cap_outranks_promotion_window_conflict_on_promotion_create
    """
    scenario = _approved_quarter_long_promotion()

    response = _file_promotion(scenario, "AUG35", 0.35)
    validate_error(response, ApiErrorId.ERR_DISCOUNT_CAP_EXCEEDED.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value


def test_a_filing_at_exactly_the_cap_falls_through_to_the_window_band():
    """0.35 is above the cap and is stopped there, while 0.30 is not above it and is passed
    on to the later band, which refuses it for the window instead.

    PRD 3.2: "The schema band accepts a `discount_pct` as high as 0.500, but brand governance
    caps a franchise-level discount at 0.30 — thirty percent off list — and a filing above
    that cap is refused with `ERR_DISCOUNT_CAP_EXCEEDED`, while a value above 0.500 never
    gets that far and is refused as malformed with `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/discount_cap_outranks_promotion_window_conflict_on_promotion_create
    """
    scenario = _approved_quarter_long_promotion()

    over_cap = _file_promotion(scenario, "AUG35", 0.35)
    validate_error(over_cap, ApiErrorId.ERR_DISCOUNT_CAP_EXCEEDED.value)
    at_cap = _file_promotion(scenario, "AUG30", 0.30)
    validate_error(at_cap, ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value)


def test_a_compliant_discount_over_the_same_window_still_collides():
    """Dropping the discount to a tenth leaves the temporal violation untouched: the August
    window sits inside an approved quarter with no separation at all.

    PRD 3.2: "Overlapping windows and merely adjacent windows are both refused with
    `ERR_PROMO_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/discount_cap_outranks_promotion_window_conflict_on_promotion_create
    """
    scenario = _approved_quarter_long_promotion()

    response = _file_promotion(scenario, "AUG10", 0.10)
    validate_error(response, ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value)


def test_the_two_refused_filings_leave_the_channel_holding_one_promotion():
    """Neither refusal created a record, so the approved quarter-long discount is still the
    only promotion the franchisee owns.

    PRD 3.2: "When a new filing is compared against every other promotion for that same pair
    whose `status` is `PENDING_REVIEW` or `APPROVED`, the two closed windows must be separated
    by at least a full week — 7 whole days — on whichever side they meet: if the new window
    sits later, the gap from the existing promotion's `ends_on` to the new `starts_on` must be
    at least 7 days; if the new window sits earlier, the gap from the new `ends_on` to the
    existing promotion's `starts_on` must be at least 7 days."

    Design: Difficulty/priority_pair_validation_conflict/discount_cap_outranks_promotion_window_conflict_on_promotion_create
    """
    scenario = _approved_quarter_long_promotion()
    _file_promotion(scenario, "AUG35", 0.35)
    _file_promotion(scenario, "AUG10", 0.10)

    existing = read_promotion(scenario["existing_promotion"]["id"])
    assert existing["status"] == "APPROVED"
    assert existing["discount_pct"] == 0.10
    promotions, meta = validate_paginated(
        api_client.list_promotions(
            BRAND, params={"franchisee_id": scenario["franchisee"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert promotions[0]["code"] == "Q3BASE"
