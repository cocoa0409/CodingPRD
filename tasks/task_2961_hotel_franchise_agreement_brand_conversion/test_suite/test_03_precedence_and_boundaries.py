"""Which of two live objections is reported, and what happens exactly on a
threshold."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    ApiErrorId,
    assert_capacity_bands,
    assert_instant,
    assert_integer,
    assert_money,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

LIFE_SAFETY_MAJOR_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "MAJOR",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}
LIFE_SAFETY_CRITICAL_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}
GUESTROOM_MAJOR_LINE = {
    "category": "GUESTROOM",
    "priority": "MAJOR",
    "description": "Guestroom soft goods and case goods replacement",
    "estimated_cost": 2_400_000.00,
}


# ─── Life safety outranks channel readiness (PRD §2.9, §3.6) ──────────

def _open_blocked_two_ways(api):
    """An executed license whose opening fails two independent gates at once:
    an open life-safety line and a channel that was never connected."""
    world = fixtures.setup_accepted_plan(
        api, scope_lines=[LIFE_SAFETY_MAJOR_LINE, GUESTROOM_MAJOR_LINE]
    )
    for track, to_status in (
        ("TRAINING", "COMPLETED"),
        ("SYSTEMS", "PROVISIONED"),
        ("SYSTEMS", "VALIDATED"),
    ):
        get_success_data(
            api.advance_onboarding_milestone(
                world["agreement_id"], {"track": track, "to_status": to_status}, FDM_HEADERS
            )
        )
    fixtures.set_clock(api, "2026-11-01T00:00:00Z")
    world["response"] = api.open_agreement(world["agreement_id"], {}, BSD_HEADERS)
    return world


def test_opening_reports_the_open_life_safety_line_not_the_unconnected_channel(api):
    """PRD §2.9 places the life-safety gate in band 10 and the channel
    readiness gate in band 12, so when an unverified life-safety line and a
    NOT_CONNECTED channel are both live the response must name the
    higher-priority objection.

    Design: Difficulty/priority_pair_validation_conflict/open_rejected_with_life_safety_error_not_channel_not_connected
    """
    world = _open_blocked_two_ways(api)
    body = validate_error(world["response"], ApiErrorId.LIFE_SAFETY_ITEM_OPEN)

    assert world["response"].status_code == 409, (
        f"the life-safety objection is a 409, got {world['response'].status_code}"
    )
    assert body["error_id"] != "ERR_CHANNEL_NOT_CONNECTED", (
        "the lower-priority channel objection must not be reported first"
    )


def test_rejected_opening_leaves_the_license_and_the_scope_line_untouched(api):
    """PRD §2.9: a rejected request must not apply any part of its effect, so
    the license stays EXECUTED with opened_at null, the channel axis stays
    NOT_CONNECTED at the rung it actually reached, and the life-safety line is
    still PENDING.

    Design: Difficulty/priority_pair_validation_conflict/open_rejected_with_life_safety_error_not_channel_not_connected
    """
    world = _open_blocked_two_ways(api)
    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))

    assert agreement["status"] == "EXECUTED"
    assert agreement["opened_at"] is None
    assert agreement["channel_status"] == "NOT_CONNECTED"
    assert agreement["systems_status"] == "VALIDATED"
    assert agreement["training_status"] == "COMPLETED"

    rows, _ = validate_paginated_list(
        api.list_pip_items(world["plan_id"], BSD_HEADERS, {"limit": 100})
    )
    life_safety = [row for row in rows if row["category"] == "LIFE_SAFETY"][0]
    assert life_safety["status"] == "PENDING"


# ─── The consent block outranks transferee capacity (PRD §2.9, §3.9) ───

def _transfer_blocked_two_ways(api):
    """A defaulted license and a proposed owner who could never qualify: the
    consent block and the transferee capacity floor are both live."""
    world = fixtures.setup_accepted_plan(
        api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE, GUESTROOM_MAJOR_LINE]
    )
    world["weak_owner"] = fixtures.create_owner(
        api,
        legal_name="Rivermark Thin Equity LLC",
        contact_email="gp@rivermarkthin.example",
        liquid_assets_amount=300_000.00,
        net_worth_amount=1_500_000.00,
        credit_score=610,
        existing_units_count=0,
    )
    world = fixtures.setup_defaulted_plan(api, world, sweep_clock="2026-11-20T00:00:00Z")
    world["response"] = api.file_transfer_request(
        world["agreement_id"],
        {"request_type": "TRANSFER", "proposed_owner_id": world["weak_owner"]["id"]},
        make_owner_headers(world["owner_id"]),
    )
    return world


def test_transfer_filing_reports_the_default_block_not_the_transferee_capacity(api):
    """PRD §2.9 places the consent block in band 11 and the transferee capacity
    floor in band 14, so a filing that offends both must be refused for the
    default notice, even though the proposed owner is far below the ADEQUATE
    floor and would fail on its own.

    Design: Difficulty/priority_pair_validation_conflict/transfer_request_rejected_with_default_block_not_proposed_owner_capacity
    """
    world = _transfer_blocked_two_ways(api)
    body = validate_error(world["response"], ApiErrorId.TRANSFER_BLOCKED_BY_DEFAULT)

    assert world["response"].status_code == 409, (
        f"the consent block is a 409, got {world['response'].status_code}"
    )
    assert body["error_id"] != "ERR_PROPOSED_OWNER_CAPACITY_INSUFFICIENT", (
        "the lower-priority transferee capacity objection must not be reported first"
    )

    weak = get_success_data(api.get_owner(world["weak_owner"]["id"], FDM_HEADERS))
    assert_money(weak["capacity_score_standalone"], 14.87, "capacity_score_standalone")
    assert weak["capacity_band_standalone"] == "INSUFFICIENT"
    assert_capacity_bands(weak)


def test_rejected_transfer_filing_creates_no_consent_request(api):
    """PRD §2.9: the rejected filing leaves no request behind, so the
    license's consent collection is empty while the block that caused the
    refusal remains raised on the compliance axis.

    Design: Difficulty/priority_pair_validation_conflict/transfer_request_rejected_with_default_block_not_proposed_owner_capacity
    """
    world = _transfer_blocked_two_ways(api)

    rows, meta = validate_paginated_list(
        api.list_transfer_requests(FDM_HEADERS, {"agreement_id": world["agreement_id"]})
    )
    assert_integer(meta["total_count"], 0, "total_count")
    assert rows == [], f"no consent request may be created, got {len(rows)}"

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["transfer_consent_blocked"] is True
    assert agreement["compliance_status"] == "DEFAULT_NOTICE"


# ─── Exactly on the ADEQUATE capacity band (PRD §3.2, §3.3) ───────────

_BOUNDARY_OWNER = {
    "net_worth_amount": 10_500_000.00,
    "credit_score": 800,
    "existing_units_count": 0,
}


def _band_boundary_world(api):
    """Two owners 10,000.00 of liquidity apart, straddling the 55.00 ADEQUATE
    floor, each with an application reviewed on the STANDALONE basis."""
    world = fixtures.setup_reviewable_application(
        api,
        owner_overrides=dict(
            _BOUNDARY_OWNER,
            legal_name="Boundary Exact Lodging LLC",
            contact_email="cfo@boundaryexact.example",
            liquid_assets_amount=1_000_000.00,
        ),
        application_overrides={
            "property_name": "Boundary Exact Hotel",
            "market_code": "SEASO",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 14,
        },
    )
    below_owner = fixtures.create_owner(
        api,
        legal_name="Boundary Short Lodging LLC",
        contact_email="cfo@boundaryshort.example",
        liquid_assets_amount=990_000.00,
        **_BOUNDARY_OWNER,
    )
    below_application = fixtures.create_application(
        api,
        below_owner["id"],
        world["brand_id"],
        property_name="Boundary Short Hotel",
        market_code="SEASO",
        property_x_miles=40.00,
        property_y_miles=0.00,
        current_affiliation="INDEPENDENT",
        building_age_years=14,
    )
    fixtures.start_review(api, below_application["id"])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")

    world["at_band_owner_id"] = world["owner_id"]
    world["at_band_application_id"] = world["application_id"]
    world["below_owner_id"] = below_owner["id"]
    world["below_application_id"] = below_application["id"]
    world["at_band_application"] = fixtures.run_financial_review(
        api, world["at_band_application_id"], "STANDALONE",
        reviewer_notes="At-band applicant.",
    )
    world["below_application"] = fixtures.run_financial_review(
        api, world["below_application_id"], "STANDALONE",
        reviewer_notes="One cent-band below.",
    )
    return world


def test_capacity_score_of_exactly_fifty_five_passes_the_financial_review(api):
    """PRD §3.2 and §3.3: the ADEQUATE band is 55.00 or above and a review
    passes when the chosen variant is at least ADEQUATE, so an owner whose
    weighted roll-up lands on exactly 55.00 - 9.00 liquidity plus 21.00 net
    worth plus 25.00 credit - is ADEQUATE and its review PASSES.

    Design: Difficulty/boundary_precision_check/financial_review_passes_at_exactly_capacity_band_adequate
    """
    world = _band_boundary_world(api)

    owner = get_success_data(api.get_owner(world["at_band_owner_id"], FDM_HEADERS))
    assert_money(owner["capacity_score_standalone"], 55.00, "capacity_score_standalone")
    assert owner["capacity_band_standalone"] == "ADEQUATE"

    application = world["at_band_application"]
    assert application["financial_review_status"] == "PASSED"
    assert_money(application["capacity_score_at_review"], 55.00, "capacity_score_at_review")
    assert application["capacity_band_at_review"] == "ADEQUATE"
    assert application["status"] == "UNDER_REVIEW"


def test_capacity_score_just_below_fifty_five_fails_the_review_without_declining_it(api):
    """PRD §3.2 and §3.3: 10,000.00 less liquidity scores 19.80 on that
    component, and because each component is rounded to two decimals before it
    is weighted the roll-up is 54.91 - INSUFFICIENT, so the review FAILS while
    the application itself stays UNDER_REVIEW rather than being declined.

    Design: Difficulty/boundary_precision_check/financial_review_passes_at_exactly_capacity_band_adequate
    """
    world = _band_boundary_world(api)

    owner = get_success_data(api.get_owner(world["below_owner_id"], FDM_HEADERS))
    assert_money(owner["capacity_score_standalone"], 54.91, "capacity_score_standalone")
    assert owner["capacity_band_standalone"] == "INSUFFICIENT"

    application = world["below_application"]
    assert application["financial_review_status"] == "FAILED"
    assert_money(application["capacity_score_at_review"], 54.91, "capacity_score_at_review")
    assert application["capacity_band_at_review"] == "INSUFFICIENT"
    assert application["status"] == "UNDER_REVIEW", (
        f"a failed review must not decline the application, got {application['status']}"
    )


# ─── Exactly on the protected radius (PRD §3.4) ──────────────────────

_ON_RING_UNIT = {
    "unit_name": "Solaris Ridgeview",
    "market_code": "SEADT",
    "x_miles": 3.00,
    "y_miles": 4.00,
    "room_count": 150,
    "adr_amount": 240.00,
    "occupancy_pct": 68.00,
    "territory_start_date": "2018-04-01",
    "territory_end_date": "2038-04-01",
}


def _on_ring_world(api, finalize: bool = False):
    """One OPERATING unit exactly 5.00 miles from the proposed property, on a
    brand whose protected radius is 5.00."""
    world = fixtures.setup_reviewable_application(
        api,
        existing_units=[_ON_RING_UNIT],
        application_overrides={
            "property_name": "Origin Point Hotel",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    world["application"] = fixtures.run_impact_analysis(api, world["application_id"])
    if finalize:
        world["application"] = fixtures.finalize_impact(api, world["application_id"])
    return world


def test_unit_exactly_on_the_protected_radius_is_inside_the_preliminary_input_set(api):
    """PRD §3.4: the input set is every OPERATING unit of the brand whose
    distance is less than or equal to the protected radius, so a comparable at
    (3.00, 4.00) is exactly 5.00 miles out and counts.  Its proximity factor is
    zero at the ring, so it contributes nothing and the score is 0.00 - a real
    zero over one unit, not a null over an empty set.

    Design: Difficulty/boundary_precision_check/impact_study_counts_the_unit_sitting_exactly_on_the_protected_radius
    """
    world = _on_ring_world(api)
    application = world["application"]

    assert_integer(application["impact_unit_count_preliminary"], 1, "impact_unit_count_preliminary")
    assert application["preliminary_impact_score"] is not None, (
        "an empty-set null must not stand in for a computed zero"
    )
    assert_money(application["preliminary_impact_score"], 0.00, "preliminary_impact_score")
    assert_instant(
        application["claim_window_closes_at"],
        "2026-08-26T00:00:00.000Z",
        "claim_window_closes_at",
    )


def test_finalized_study_over_the_on_ring_unit_is_clear_at_a_zero_score(api):
    """PRD §3.4: finalizing recomputes the input set as it stands, then adds
    the sustained-claim uplift.  With no claims filed the final score equals
    the base score of 0.00, so the verdict is CLEAR and the study is FINAL.

    Design: Difficulty/boundary_precision_check/impact_study_counts_the_unit_sitting_exactly_on_the_protected_radius
    """
    world = _on_ring_world(api, finalize=True)
    application = world["application"]

    assert_integer(application["impact_unit_count_final"], 1, "impact_unit_count_final")
    assert_money(application["base_impact_score"], 0.00, "base_impact_score")
    assert_money(application["final_impact_score"], 0.00, "final_impact_score")
    assert application["encroachment_verdict"] == "CLEAR"
    assert application["impact_study_status"] == "FINAL"
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")
