"""Acceptance, the exclusivity register and countersignature."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_engagement,
    assert_exclusivity_grant,
    build_deal,
    countersign_payload,
    draft_term_sheet,
    make_brand_rep_headers,
    register_brand,
    sanction_brand,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_acceptance_mints_a_pending_engagement_and_a_pending_grant(api):
    """PRD 3.4: "First, an **engagement** is minted, carrying `term_sheet_id` for the
    accepted paper, `opportunity_id` carried through for the later
    segregation-of-duties lookup, and `athlete_id` and `brand_id` copied from the
    opportunity. It opens with `contract_status` `PENDING_COUNTERSIGN` and
    `settlement_status` `UNBILLED`."
    PRD 3.4: "The term sheet's `provisional_fee_cents` is frozen onto the engagement
    under the same name, while `binding_fee_cents` stays null until countersignature."
    PRD 3.4: "`required_deliverable_count` is frozen as the sum of the opportunity's
    `planned_posts`, `planned_appearances` and `planned_shoots`, and
    `appearance_days_committed` takes the term sheet's `appearance_days`."
    PRD 3.4: "Second, an **exclusivity grant** is created in `PENDING` status for that
    athlete and category over the inclusive range just described, recording
    `athlete_id`, `engagement_id`, `category`, `start_date` and `end_date`, with
    `released_at` null. A `PENDING` grant already occupies the register for
    conflict-detection purposes even though it has not yet been counted into
    `active_exclusivity_count` — only `ACTIVE` grants are counted there."

    Design: Corner/state_machines/engagement_initial_states_are_pending_countersign_and_unbilled
    """
    deal = build_deal(stage="submitted")

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])
    )
    engagement = validate_success(response, 201)
    assert_engagement(engagement)

    assert engagement["contract_status"] == "PENDING_COUNTERSIGN"
    assert engagement["settlement_status"] == "UNBILLED"
    assert engagement["binding_fee_cents"] is None
    assert engagement["provisional_fee_cents"] == 2_621_400
    assert engagement["required_deliverable_count"] == 1
    assert engagement["base_fee_cents"] == 1_400_000
    assert engagement["term_start_date"] == "2026-09-01"
    assert engagement["term_end_date"] == "2027-02-28"

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "ACCEPTED"
    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert opportunity["status"] == "CONTRACTED"

    grants, _meta = validate_paginated(
        api.list_engagement_exclusivity_grants(engagement["id"], AGENT)
    )
    assert len(grants) == 1
    assert_exclusivity_grant(grants[0])
    assert grants[0]["status"] == "PENDING"
    assert grants[0]["start_date"] == "2026-09-01"
    assert grants[0]["end_date"] == "2027-08-31"

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 0


def test_acceptance_withdraws_the_sibling_paper_and_contracts_the_opportunity(api):
    """PRD 3.4: "Third, the parent opportunity moves `SCREENED → CONTRACTED`. Fourth,
    because that opportunity is now contracted, every *sibling* term sheet of the same
    opportunity whose `status` is `DRAFT`, `SUBMITTED` or `COUNTERED` is moved to
    `WITHDRAWN`. Competing papers cannot survive a signed deal."

    Design: Corner/state_machines/accept_withdraws_sibling_term_sheets_and_contracts_opportunity
    """
    deal = build_deal(stage="submitted")
    sibling = draft_term_sheet(
        deal["opportunity_id"], fee_cents=1_500_000, usage_rights_tier="SOCIAL_ONLY",
        territory="DOMESTIC", morals_clause_tier="TIER_C",
    )

    validate_success(
        api.accept_term_sheet(deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])),
        201,
    )

    accepted = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert accepted["status"] == "ACCEPTED"
    withdrawn = validate_success(api.get_term_sheet(sibling["id"], AGENT))
    assert withdrawn["status"] == "WITHDRAWN"
    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert opportunity["status"] == "CONTRACTED"

    rows, _meta = validate_paginated(
        api.list_term_sheets(AGENT, params={"opportunity_id": deal["opportunity_id"]})
    )
    assert len(rows) == 2
    assert not [r for r in rows if r["status"] in ("DRAFT", "SUBMITTED", "COUNTERED")]


def test_exclusivity_grants_conflict_on_a_shared_boundary_day(api):
    """PRD 3.4: "Acceptance would mint a grant covering the inclusive day range that
    begins on the engagement's `term_start_date` and ends on the day that is the
    requested number of exclusivity months later, minus one day — so a six-month lock
    starting on the first of March runs through the last day of August."
    PRD 3.4: "If any other exclusivity grant of the *same* `athlete_id` and the *same*
    `category` whose `status` is `PENDING` or `ACTIVE` shares even one calendar day
    with that range, the acceptance is refused with `ERR_EXCLUSIVITY_CONFLICT`. Grants
    that merely abut — one ending the day before the other begins — do not conflict;
    grants that share their boundary day do."

    Design: Corner/validations/exclusivity_conflict_inclusive_day_boundary_on_accept
    """
    first = build_deal(stage="pending")

    touching = build_deal(
        stage="submitted", clock=None, athlete=first["athlete"],
        brand_overrides={"name": "Volt Zero", "legal_entity_name": "Volt Zero Ltd"},
        opportunity_overrides={
            "requested_start_date": "2027-08-31", "requested_end_date": "2028-02-29",
        },
        term_sheet_overrides={"fee_cents": 1_000_000},
        screening_officer="co-screen-2",
    )
    adjacent = build_deal(
        stage="submitted", clock=None, athlete=first["athlete"],
        brand_overrides={"name": "Volt Plus", "legal_entity_name": "Volt Plus Ltd"},
        opportunity_overrides={
            "requested_start_date": "2027-09-01", "requested_end_date": "2028-03-01",
        },
        term_sheet_overrides={"fee_cents": 1_000_000},
        screening_officer="co-screen-2",
    )

    refused = api.accept_term_sheet(
        touching["term_sheet_id"], make_brand_rep_headers(touching["brand_id"])
    )
    validate_error(refused, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value, 409)
    still_open = validate_success(api.get_term_sheet(touching["term_sheet_id"], AGENT))
    assert still_open["status"] == "SUBMITTED"

    accepted = api.accept_term_sheet(
        adjacent["term_sheet_id"], make_brand_rep_headers(adjacent["brand_id"])
    )
    validate_success(accepted, 201)

    grants, _meta = validate_paginated(
        api.list_athlete_exclusivity_grants(first["athlete_id"], AGENT)
    )
    assert len(grants) == 2
    new_grant = [g for g in grants if g["start_date"] == "2027-09-01"]
    assert len(new_grant) == 1
    assert new_grant[0]["end_date"] == "2028-08-31"


def test_acceptance_after_the_offer_expiry_expires_the_paper(api):
    """PRD 3.4: "If acceptance is attempted when the logical clock has already passed
    `offer_expires_at`, the paper moves `SUBMITTED → EXPIRED` and the call is refused
    with `ERR_OFFER_EXPIRED`. No engagement is created, no grant is minted, and the
    paper is now terminal — a later, punctual acceptance attempt is impossible."

    Design: Corner/state_machines/late_accept_expires_offer_and_is_refused
    """
    deal = build_deal(stage="submitted")
    set_clock("2026-08-16T00:00:00Z")

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])
    )
    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "EXPIRED"

    rows, _meta = validate_paginated(
        api.list_engagements(AGENT, params={"term_sheet_id": deal["term_sheet_id"]})
    )
    assert rows == []

    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert opportunity["status"] == "SCREENED"


def test_fee_above_eight_times_the_card_rate_is_refused(api):
    """PRD 3.4: "The negotiated `fee_cents` must not exceed the athlete's
    `base_appearance_rate_cents` multiplied by eight, or the acceptance is refused
    with `ERR_FEE_CAP_EXCEEDED`."

    Design: Corner/validations/fee_cap_exceeded_alone_returns_fee_cap_error
    """
    deal = build_deal(stage="submitted", term_sheet_overrides={"fee_cents": 4_000_000})

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])
    )
    validate_error(response, ApiErrorId.ERR_FEE_CAP_EXCEEDED.value, 422)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "SUBMITTED"

    rows, _meta = validate_paginated(
        api.list_engagements(AGENT, params={"term_sheet_id": deal["term_sheet_id"]})
    )
    assert rows == []


def test_sanctioned_brand_outranks_the_fee_cap_on_acceptance(api):
    """PRD 2.8: "Only once all of that passes does the domain layer run, in this
    order: athlete bookability (`ERR_ATHLETE_NOT_BOOKABLE`), opportunity-screened
    (`ERR_OPPORTUNITY_NOT_SCREENED`), term-sheet from-state
    (`ERR_TERM_SHEET_INVALID_STATE`), offer expiry (`ERR_OFFER_EXPIRED`), engagement
    contract-status fitness (`ERR_ENGAGEMENT_NOT_ACTIVE`), engagement terminality for
    countersign and terminate (`ERR_ENGAGEMENT_ALREADY_TERMINAL`), booking from-state
    (`ERR_BOOKING_INVALID_STATE`), deliverable from-state
    (`ERR_DELIVERABLE_INVALID_STATE`), disclosure from-state
    (`ERR_DISCLOSURE_INVALID_STATE`), settlement billability
    (`ERR_SETTLEMENT_NOT_BILLABLE`), payout from-state (`ERR_PAYOUT_INVALID_STATE`),
    renewal window (`ERR_RENEWAL_WINDOW_CLOSED`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), brand sanction (`ERR_BRAND_SANCTIONED`), disclosure
    compliance (`ERR_DISCLOSURE_NOT_COMPLIANT`), morals-tier downgrade
    (`ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`), deliverable reference coherence
    (`ERR_BOOKING_ENGAGEMENT_MISMATCH`), shoot-inside-slot-window
    (`ERR_SLOT_WINDOW_VIOLATION`), athlete calendar overlap (`ERR_BOOKING_OVERLAP`),
    slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), booking-inside-term
    (`ERR_BOOKING_WINDOW_OUTSIDE_TERM`), exclusivity conflict
    (`ERR_EXCLUSIVITY_CONFLICT`), counter-round limit (`ERR_COUNTER_LIMIT_EXCEEDED`),
    duplicate disclosure (`ERR_DUPLICATE_DISCLOSURE`), fee cap
    (`ERR_FEE_CAP_EXCEEDED`) and finally the billable-set check
    (`ERR_NO_BILLABLE_DELIVERABLES`)."
    PRD 2.10: "While a brand is sanctioned, neither acceptance of its paper nor
    countersignature of its engagement may proceed; both are refused with
    `ERR_BRAND_SANCTIONED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_accept_with_sanctioned_brand_over_fee_cap
    """
    deal = build_deal(
        stage="submitted",
        opportunity_overrides={
            "proposed_fee_cents": 800_000, "planned_posts": 2,
            "planned_appearances": 1, "planned_shoots": 1,
        },
        term_sheet_overrides={"fee_cents": 4_000_000, "appearance_days": 2},
    )
    sanction_brand(deal["brand_id"], True, reason="Regulatory investigation opened")

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])
    )
    validate_error(response, ApiErrorId.ERR_BRAND_SANCTIONED.value, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_FEE_CAP_EXCEEDED.value


def test_refused_acceptance_mints_neither_engagement_nor_grant(api):
    """PRD 3.4: "Acceptance is the single most consequential call in the system, and
    it is guarded by five conditions before anything is written. The paper must be
    `SUBMITTED`. The acting `BrandRep`'s `X-User-ID` must equal the opportunity's
    `brand_id`. The logical clock must be at or before `offer_expires_at`. The brand
    must not be sanctioned, or the acceptance is refused with `ERR_BRAND_SANCTIONED`.
    The negotiated `fee_cents` must not exceed the athlete's
    `base_appearance_rate_cents` multiplied by eight, or the acceptance is refused
    with `ERR_FEE_CAP_EXCEEDED`. And the category slot the acceptance would occupy
    must be free, as described below."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_accept_with_sanctioned_brand_over_fee_cap
    """
    deal = build_deal(
        stage="submitted",
        opportunity_overrides={
            "proposed_fee_cents": 800_000, "planned_posts": 2,
            "planned_appearances": 1, "planned_shoots": 1,
        },
        term_sheet_overrides={"fee_cents": 4_000_000, "appearance_days": 2},
    )
    sanction_brand(deal["brand_id"], True, reason="Regulatory investigation opened")

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(deal["brand_id"])
    )
    validate_error(response, ApiErrorId.ERR_BRAND_SANCTIONED.value, 422)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "SUBMITTED"

    engagements, _meta = validate_paginated(
        api.list_engagements(AGENT, params={"term_sheet_id": deal["term_sheet_id"]})
    )
    assert engagements == []

    grants, _meta = validate_paginated(
        api.list_athlete_exclusivity_grants(deal["athlete_id"], AGENT)
    )
    assert grants == []


def test_another_brands_representative_may_not_accept_the_paper(api):
    """PRD 2.1: "When `X-User-Role` is `BrandRep`, `X-User-ID` is the `id` of the
    acting `Brand`; ownership checks on any resource that references a `Brand` compare
    the resource's brand foreign-key field — `brand_id` on an opportunity, or
    `brand_id` on an engagement — to `X-User-ID`."
    PRD 2.1: "Ownership is enforced on exactly eight operations: filing an
    opportunity, countering a term sheet, accepting a term sheet, submitting a
    deliverable, reviewing a deliverable, filing a disclosure record, remediating a
    disclosure record, and deciding a renewal option."

    Design: Corner/rbac/brand_rep_cannot_accept_another_brands_term_sheet
    """
    deal = build_deal(stage="submitted")
    other_brand = register_brand(
        name="Kite Footwear", category="FOOTWEAR", legal_entity_name="Kite Footwear LLC"
    )

    response = api.accept_term_sheet(
        deal["term_sheet_id"], make_brand_rep_headers(other_brand["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    term_sheet = validate_success(api.get_term_sheet(deal["term_sheet_id"], AGENT))
    assert term_sheet["status"] == "SUBMITTED"

    rows, _meta = validate_paginated(
        api.list_engagements(AGENT, params={"term_sheet_id": deal["term_sheet_id"]})
    )
    assert rows == []


def test_brand_rep_may_not_countersign_an_engagement(api):
    """PRD 2.1: "If the headers are well formed but the named role is not listed among
    the roles authorised for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.5: "A `FinanceManager` countersigns an engagement sitting in
    `PENDING_COUNTERSIGN`, supplying a `signed_by_reference` naming the executed paper
    copy, and the engagement moves `PENDING_COUNTERSIGN → ACTIVE`."

    Design: Corner/rbac/brand_rep_cannot_countersign_engagement_returns_forbidden_role
    """
    deal = build_deal(stage="pending")

    response = api.countersign_engagement(
        deal["engagement_id"], countersign_payload("CS-X"),
        make_brand_rep_headers(deal["brand_id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    engagement = validate_success(api.get_engagement(deal["engagement_id"], AGENT))
    assert engagement["contract_status"] == "PENDING_COUNTERSIGN"
    assert engagement["binding_fee_cents"] is None

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 0


def test_binding_fee_equals_the_provisional_fee_without_confirmed_bookings(api):
    """PRD 3.5: "With no qualifying bookings, the binding figure equals the
    provisional figure exactly; with one or more, it is strictly larger before the
    ceiling applies. Once written, `binding_fee_cents` is frozen — later bookings do
    not move it."
    PRD 3.6: "A new booking opens in `HOLD`, with `travel_cost_cents` 0, `travel_days`
    0, `outcome` null and `cancel_reason_code` null."

    Design: Corner/calculations/binding_equals_provisional_when_no_confirmed_bookings
    """
    deal = build_deal(stage="pending")
    booking = validate_success(
        api.create_appearance_booking(
            {
                "engagement_id": deal["engagement_id"],
                "city": "Chicago",
                "start_at": "2026-09-10T14:00:00Z",
                "end_at": "2026-09-10T22:00:00Z",
                "travel_buffer_hours": 12,
                "expected_engagement_version": deal["engagement"]["version"],
            },
            AGENT,
        ),
        201,
    )

    engagement = validate_success(
        api.countersign_engagement(
            deal["engagement_id"], countersign_payload("CS-C-0010"), FINANCE
        ),
        200,
    )

    held = validate_success(api.get_appearance_booking(booking["id"], AGENT))
    assert held["status"] == "HOLD"
    assert held["travel_days"] == 0
    assert engagement["binding_fee_cents"] == 2_621_400
    assert engagement["binding_fee_cents"] == engagement["provisional_fee_cents"]
    assert engagement["accrued_fee_cents"] == 0


def test_countersigning_an_active_engagement_is_refused(api):
    """PRD 3.5: "Countersignature is refused with `ERR_BRAND_SANCTIONED` while the
    brand is sanctioned, and countersigning an engagement that has already left
    `PENDING_COUNTERSIGN` — whether it is `ACTIVE`, `COMPLETED` or `TERMINATED` — is
    refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`."
    PRD 3.5: "Countersignature also propagates outward. Because the engagement went
    `ACTIVE`, its exclusivity grant moves `PENDING → ACTIVE`; because that grant became
    `ACTIVE`, the athlete's `active_exclusivity_count` increments by 1; and because
    that counter changed, the athlete's `exposure_risk_snapshot_score` is recomputed
    and rewritten."

    Design: Corner/state_machines/countersign_already_countersigned_engagement_is_refused
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")

    response = api.countersign_engagement(
        deal["engagement_id"], countersign_payload("CS-C-0003"), FINANCE
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_ALREADY_TERMINAL.value, 409)

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["active_exclusivity_count"] == 1

    engagement = validate_success(api.get_engagement(deal["engagement_id"], AGENT))
    assert engagement["contract_status"] == "ACTIVE"
    assert engagement["binding_fee_cents"] == 2_621_400


def test_engagement_reads_are_shared_across_the_agency_roles(api):
    """PRD 2.1: "There are exactly five roles: `TalentAgent`, `BrandRep`, `Athlete`,
    `ComplianceOfficer`, and `FinanceManager`."
    PRD 4: "| GET | `/engagements/{id}` | Read one engagement, both status dimensions
    and all derived figures. | TalentAgent, BrandRep, Athlete, ComplianceOfficer,
    FinanceManager |"

    Design: Corner/rbac/engagement_reads_are_shared_across_agency_roles
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")

    reads = [
        validate_success(api.get_engagement(deal["engagement_id"], AGENT), 200),
        validate_success(api.get_engagement(deal["engagement_id"], FINANCE), 200),
        validate_success(
            api.get_engagement(
                deal["engagement_id"], TEST_USERS["compliance_officer_headers"]
            ),
            200,
        ),
    ]
    for engagement in reads:
        assert engagement["contract_status"] == "ACTIVE"
        assert engagement["settlement_status"] == "UNBILLED"
        assert engagement["binding_fee_cents"] == 2_621_400
