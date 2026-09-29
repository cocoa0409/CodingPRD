"""Validation rules and the ordered refusal ladder.

Every test here fires one request (or one short sequence of requests) that
violates more than one of the PRD's rules at once, and pins the single error the
PRD says the caller must see. The ladder of §2.8 is the contract: authentication,
then role, then body schema including its conditional required fields, then
pagination, then path existence, then body foreign keys, then ownership, then
segregation of duties, then the version guards, then the addressed record's own
state, then the cross-entity gates, and only then the safety, referential,
temporal, constraint and fiscal rules. Each test also drives the same request
through to the admission that follows once the winning rule is satisfied, which
is what proves the refusal was the only thing standing in the way.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_BILL_INSERT_NOT_SUPPORTED,
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CANCELLATION_BLOCKED_APPEAL,
    ERR_CLAIM_NOT_FOUND,
    ERR_CONTRACTOR_CAPACITY_EXCEEDED,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND,
    ERR_DUPLICATE_ACTIVE_ENROLLMENT,
    ERR_ENROLLMENT_TERMINAL,
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_ENROLLMENT_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_list_envelope,
    assert_nulls,
    assert_refused,
    entries_of_type,
)
from test_helpers.constants import (
    CANCELLATION_FEE_CENTS,
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    COVERAGE_EFFECTIVE_AT,
    DEFAULT_LIMIT,
    ENROLLMENT_TERM_START,
    MAX_LIMIT,
    MIN_OFFSET,
    ROLE_APPEALS_OFFICER,
    ROLE_PARTNER_BRAND_REVIEWER,
)
from test_helpers.test_users import (
    APPEALS_OFFICER,
    APPEALS_OFFICER_USER_ID,
    BILLING_OPS,
    CLAIMS_ADJUSTER_USER_ID,
    CUSTOMER_SERVICE_REP,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    make_headers,
    make_network_contractor_headers,
    make_partner_brand_reviewer_headers,
    make_policyholder_headers,
)

# A syntactically valid identifier that names no row in any collection.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

# Clock positions used by the appeal-window boundary test: the denial instant
# advanced by exactly the 30-day window, and one millisecond past it.
APPEAL_BOUNDARY = "2026-10-10T08:00:00.000Z"
APPEAL_BOUNDARY_PLUS_1MS = "2026-10-10T08:00:00.001Z"


# ── Private helpers ──
#
# Three write endpoints below settle a record that already exists rather than
# creating one, so they answer 200 rather than 201; these wrappers pin that
# status instead of borrowing a shared helper that expects a creation.


def _open_appeal(api, claim_id, premises_id, **overrides):
    """Open a policyholder appeal against a denied claim."""
    response = api.create_appeal(
        claim_id, factories.appeal_payload(**overrides), make_policyholder_headers(premises_id)
    )
    return validate_success(response, 200)


def _billing_event(api, enrollment_id, event_type, effective_date, **overrides):
    """Post an accepted billing event against an enrollment."""
    response = api.create_billing_event(
        enrollment_id,
        factories.billing_event_payload(event_type, effective_date, **overrides),
        BILLING_OPS,
    )
    return validate_success(response, 200)


def _ledger_page(api, **params):
    """Every ledger row matching the filters, with the pagination meta."""
    return validate_paginated(api.list_ledger_entries(PLATFORM_ADMIN, params=params or None))


class TestPaginationBounds:
    """The pagination tier of the ladder, and the defaults beneath it."""

    def test_pagination_bounds_reject_limit_zero_and_limit_over_one_hundred(self, api):
        """Both ends of the legal window are inclusive, and offset is checked separately.

        PRD: "A `limit` below 1, a `limit` above 100, an `offset` below 0, or a non-integer value for either is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/pagination_bounds_reject_limit_zero_and_limit_over_one_hundred
        """
        fixtures.set_clock(api, CLOCK_START)
        partner_a = fixtures.create_partner(api, name="Cascadia Water", utility_type="WATER")
        partner_b = fixtures.create_partner(api, name="Cascadia Sewer", utility_type="WASTEWATER")

        assert_refused(
            api.list_partners(PLATFORM_ADMIN, params={"limit": 0}), ERR_INVALID_PAGINATION, 400
        )
        assert_refused(
            api.list_partners(PLATFORM_ADMIN, params={"limit": MAX_LIMIT + 1}),
            ERR_INVALID_PAGINATION,
            400,
        )
        assert_refused(
            api.list_partners(PLATFORM_ADMIN, params={"offset": -1}), ERR_INVALID_PAGINATION, 400
        )

        # 100 is the inclusive ceiling and 1 the inclusive floor.
        rows, meta = assert_list_envelope(
            api.list_partners(PLATFORM_ADMIN, params={"limit": MAX_LIMIT}), 2
        )
        assert meta["limit"] == MAX_LIMIT
        assert meta["offset"] == MIN_OFFSET
        assert meta["has_more"] is False
        assert_ids_in_order(rows, [partner_a["id"], partner_b["id"]])

        rows, meta = assert_list_envelope(
            api.list_partners(PLATFORM_ADMIN, params={"limit": 1, "offset": 1}), 2
        )
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False
        assert_ids_in_order(rows, [partner_b["id"]])

        _, meta = assert_list_envelope(api.list_partners(PLATFORM_ADMIN), 2)
        assert meta["limit"] == DEFAULT_LIMIT
        assert meta["offset"] == MIN_OFFSET


class TestIdentityGuards:
    """Ownership and segregation of duties, above every business rule below them."""

    def test_appeal_decided_by_the_denying_adjuster_is_segregation_of_duties(self, api):
        """The same appeal decision is refused for one officer and admitted for another.

        PRD: "A caller whose `X-User-ID` equals the claim's `triage_decided_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, and this is checked ahead of any state or business condition."

        Design: Corner/validations/appeal_decided_by_the_denying_adjuster_is_segregation_of_duties
        """
        world = fixtures.active_coverage(api)
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="INSIDE_HOME",
            incident_description="Interior riser dripping.",
        )
        denied = fixtures.deny_claim(
            api,
            claim["id"],
            "OWNERSHIP_INELIGIBLE",
            coverage_note="Interior plumbing is outside the curb-stop boundary.",
        )
        assert denied["triage_decided_by_user_id"] == CLAIMS_ADJUSTER_USER_ID

        appealed = _open_appeal(
            api,
            claim["id"],
            world["premises_id"],
            appeal_reason="The utility told me the curb stop was covered.",
        )
        assert_fields(appealed, {"status": "APPEAL_OPEN", "appeal_count": 1})
        version_before = appealed["version"]

        # Both callers hold the AppealsOfficer role, so the role gate cannot be
        # what refuses the first one.
        own_denial = make_headers(ROLE_APPEALS_OFFICER, CLAIMS_ADJUSTER_USER_ID)
        assert_refused(
            api.decide_appeal(
                claim["id"],
                factories.appeal_decision_payload("OVERTURN", rationale="Reviewing my own denial."),
                own_denial,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        untouched = fixtures.refresh_claim(api, claim["id"])
        assert_fields(untouched, {"status": "APPEAL_OPEN", "version": version_before})
        assert_nulls(untouched, ["appeal_decided_by_user_id"])

        final = validate_success(
            api.decide_appeal(
                claim["id"],
                factories.appeal_decision_payload(
                    "OVERTURN", rationale="Ownership boundary was misread at triage."
                ),
                APPEALS_OFFICER,
            ),
            200,
        )
        assert_fields(
            final,
            {"status": "APPROVED", "appeal_decided_by_user_id": APPEALS_OFFICER_USER_ID},
        )
        assert_nulls(final, ["denial_reason"])

        # The hold is recomputed by the decision, not left behind.
        assert fixtures.refresh_enrollment(api, world["enrollment_id"])["retention_hold"] is False

    def test_dispatch_events_by_another_contractor_return_not_resource_owner(self, api):
        """An interloping crew is refused on ownership even when its event is also illegal.

        PRD: "A contractor works the job by posting events against the dispatch, and only the `NetworkContractor` whose own identity matches the dispatch's `contractor_id` may do so; anyone else is refused with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/dispatch_events_by_another_contractor_return_not_resource_owner
        """
        world = fixtures.active_coverage(api)
        owner = fixtures.create_contractor(
            api,
            name="Alder Plumbing",
            license_number="OR-PL-4411",
            license_expires_on="2027-06-30",
        )
        other = fixtures.create_contractor(
            api,
            name="Ridgeline Plumbing",
            license_number="OR-PL-4412",
            license_expires_on="2027-06-30",
            hourly_rate_cents=6000,
            sla_compliance_pct=70,
        )
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="URGENT",
            incident_description="Curb stop leaking.",
        )
        approved = fixtures.approve_claim(
            api, claim["id"], coverage_note="Covered curb-stop failure."
        )
        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            approved["version"],
            owner["id"],
            window_start="2026-09-10T09:00:00.000Z",
        )
        assert dispatch["version"] == 1

        interloper = make_network_contractor_headers(other["id"])
        assert_refused(
            api.create_dispatch_event(dispatch["id"], factories.accept_event_payload(), interloper),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        # ARRIVE is illegal from ASSIGNED as well, and ownership still wins.
        assert_refused(
            api.create_dispatch_event(dispatch["id"], factories.arrive_event_payload(), interloper),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )

        untouched = fixtures.refresh_dispatch(api, dispatch["id"])
        assert_fields(untouched, {"status": "ASSIGNED", "version": 1})
        assert_nulls(untouched, ["responded_at"])

        accepted = validate_success(
            api.create_dispatch_event(
                dispatch["id"],
                factories.accept_event_payload(),
                make_network_contractor_headers(owner["id"]),
            ),
            200,
        )
        assert_fields(accepted, {"status": "ACCEPTED", "response_minutes": 0, "version": 2})
        assert_instant(accepted["assigned_at"], CLOCK_COVERAGE_ACTIVE, "assigned_at")
        assert_instant(accepted["responded_at"], CLOCK_COVERAGE_ACTIVE, "responded_at")

        assert_list_envelope(
            api.list_dispatches(PLATFORM_ADMIN, params={"contractor_id": other["id"]}), 0
        )


class TestRefusalLadderPrecedence:
    """One request that breaks several rules at once, fired up the ladder."""

    def test_unauthenticated_and_unauthorized_precede_every_business_rule(self, api):
        """Five callers, one URL, one already-violated state gate: five different errors.

        PRD: "Which error the caller sees is not a matter of implementation convenience: validations are evaluated in a strict ascending precedence, the **first** violated rule produces the response, and no later rule is evaluated."

        Design: Corner/validations/unauthenticated_and_unauthorized_precede_every_business_rule
        """
        world = fixtures.active_partner_with_product(api)
        other_partner = fixtures.create_partner(
            api,
            name="Willamette Sewer",
            utility_type="WASTEWATER",
            bill_insert_supported=False,
        )
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="Autumn Curb Stop Drop",
            drop_date="2026-08-20",
            requested_quantity=500,
        )
        # The campaign never leaves DRAFT, so the state gate is violated on all
        # five calls and only the ladder can produce five different answers.
        assert_fields(campaign, {"status": "DRAFT", "version": 1})

        decision = factories.campaign_approval_payload(
            decision_note="Looks good.", approved_quantity=None
        )
        foreign_reviewer = make_partner_brand_reviewer_headers(other_partner["id"])
        rightful_reviewer = make_partner_brand_reviewer_headers(world["partner_id"])

        assert_refused(
            api.decide_campaign(
                campaign["id"], decision, make_headers(ROLE_PARTNER_BRAND_REVIEWER, "")
            ),
            ERR_UNAUTHENTICATED,
            401,
        )
        assert_refused(
            api.decide_campaign(campaign["id"], decision, CUSTOMER_SERVICE_REP),
            ERR_UNAUTHORIZED,
            403,
        )
        assert_refused(
            api.decide_campaign(UNKNOWN_ID, decision, foreign_reviewer),
            ERR_CAMPAIGN_NOT_FOUND,
            404,
        )
        assert_refused(
            api.decide_campaign(campaign["id"], decision, foreign_reviewer),
            ERR_NOT_RESOURCE_OWNER,
            403,
        )
        assert_refused(
            api.decide_campaign(campaign["id"], decision, rightful_reviewer),
            ERR_INVALID_CAMPAIGN_STATE,
            409,
        )

        after = validate_success(api.get_campaign(campaign["id"], PLATFORM_ADMIN))
        assert_fields(after, {"status": "DRAFT", "version": 1})
        assert_nulls(after, ["decision_by_user_id", "approved_quantity"])

    def test_path_id_existence_outranks_body_foreign_key_existence(self, api):
        """A bad path id and a bad body id in one request report the path failure.

        PRD: "Because this tier sits below tier 5, a request with both a bad path identifier and a bad body identifier reports the path failure."

        Design: Corner/validations/path_id_existence_outranks_body_foreign_key_existence
        """
        world = fixtures.active_coverage(api)
        contractor = fixtures.create_contractor(
            api,
            name="Alder Plumbing",
            license_number="OR-PL-4411",
            license_expires_on="2027-06-30",
        )
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="URGENT",
            incident_description="Curb stop leaking.",
        )
        approved = fixtures.approve_claim(
            api, claim["id"], coverage_note="Covered curb-stop failure."
        )
        claim_version = approved["version"]
        assert claim_version == 2
        window = "2026-09-10T09:00:00.000Z"

        # Unknown claim in the path AND unknown contractor in the body.
        assert_refused(
            api.create_dispatch(
                UNKNOWN_ID,
                factories.manual_dispatch_payload(claim_version, window, UNKNOWN_ID),
                OPERATIONS_ADMIN,
            ),
            ERR_CLAIM_NOT_FOUND,
            404,
        )
        # Path resolves, so the body foreign key is reached.
        assert_refused(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(claim_version, window, UNKNOWN_ID),
                OPERATIONS_ADMIN,
            ),
            ERR_CONTRACTOR_NOT_FOUND,
            404,
        )
        # The body-foreign-key tier reaches supersedes_dispatch_id too, above
        # the claim-state gate a supersede on an APPROVED claim would trip.
        assert_refused(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(
                    claim_version, window, contractor["id"], supersedes_dispatch_id=UNKNOWN_ID
                ),
                OPERATIONS_ADMIN,
            ),
            ERR_DISPATCH_NOT_FOUND,
            404,
        )
        # A non-integer expected_claim_version is a schema fault, not a stale one.
        assert_refused(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(UNKNOWN_ID, window, contractor["id"]),
                OPERATIONS_ADMIN,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        created = validate_success(
            api.create_dispatch(
                claim["id"],
                factories.manual_dispatch_payload(claim_version, window, contractor["id"]),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert_fields(created, {"status": "ASSIGNED", "selection_mode": "MANUAL"})
        assert_fields(fixtures.refresh_claim(api, claim["id"]), {"status": "DISPATCHED", "version": 3})

    def test_occ_stale_version_outranks_the_state_gate(self, api):
        """A terminal enrollment addressed with a stale version answers 412, not 409.

        PRD: "The five version guards of §2.6 fire next, each with its own 412 code on the operation that requires it: `ERR_STALE_CLAIM_VERSION` on dispatch creation, `ERR_STALE_ENROLLMENT_VERSION` on a renewal notice, `ERR_STALE_PREMISES_VERSION` on enrollment creation, `ERR_STALE_PARTNER_VERSION` on a partner status change, and `ERR_STALE_COMPLAINT_VERSION` on a complaint response."

        Design: Corner/validations/occ_stale_version_outranks_the_state_gate
        """
        world = fixtures.active_coverage(api)
        activated = world["enrollment"]
        assert_fields(activated, {"coverage_status": "ACTIVE", "version": 2})
        stale_version = activated["version"]

        cancelled = fixtures.cancel_enrollment(
            api, world["enrollment_id"], "2026-09-20", reason="MOVED"
        )
        assert_fields(
            cancelled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "version": 3,
            },
        )
        current_version = cancelled["version"]

        notice = factories.renewal_notice_payload(2599, "2027-08-05", stale_version)
        assert_refused(
            api.create_renewal_notice(world["enrollment_id"], notice, BILLING_OPS),
            ERR_STALE_ENROLLMENT_VERSION,
            412,
        )
        # The identical body, now carrying the live version, reaches the state gate.
        fresh_notice = factories.renewal_notice_payload(2599, "2027-08-05", current_version)
        assert_refused(
            api.create_renewal_notice(world["enrollment_id"], fresh_notice, BILLING_OPS),
            ERR_ENROLLMENT_TERMINAL,
            409,
        )

        after = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(after, {"version": current_version, "renewal_notice_status": "NONE"})


class TestConditionalAndCrossEntityRules:
    """Rules whose inputs live in a sibling field or two entities away."""

    def test_conditional_amount_required_is_shape_sensitive_to_event_type(self, api):
        """One payload shape is legal for a missed payment and illegal for the other two.

        PRD: "So does one **conditional** requirement whose shape depends on a sibling field: `amount_cents` must be present when a billing event's `event_type` is `PREMIUM_PAYMENT`, `INSERT_REMITTANCE` or `WRITE_OFF`, and `remedy_amount_cents` must be present when a complaint response's `remedy_type` is `BENEFIT_REVERSAL` or `PREMIUM_REFUND`."

        Design: Corner/validations/conditional_amount_required_is_shape_sensitive_to_event_type
        """
        # prepaid_amount_cents is left out so the DIRECT_BILL default is observable.
        world = fixtures.enrolled_premises(api, prepaid_amount_cents=None)
        created = world["enrollment"]
        assert_fields(
            created,
            {"prepaid_amount_cents": 29988, "premium_collected_cents": 0, "version": 1},
        )

        world = fixtures.activate_coverage(api, world)
        assert_fields(world["enrollment"], {"coverage_status": "ACTIVE", "version": 2})
        enrollment_id = world["enrollment_id"]

        # A missed payment is outside the three types that name an amount, so the
        # omission is legal and the event still moves the billing dimension.
        missed = _billing_event(api, enrollment_id, "MISSED_PAYMENT", "2026-09-11")
        assert_fields(
            missed,
            {
                "billing_status": "PAST_DUE",
                "past_due_since": "2026-09-11",
                "premium_collected_cents": 0,
                "version": 3,
            },
        )
        assert_list_envelope(
            api.list_ledger_entries(PLATFORM_ADMIN, params={"enrollment_id": enrollment_id}), 0
        )

        # The identical omission on the two types that do name an amount.
        for event_type in ("WRITE_OFF", "PREMIUM_PAYMENT"):
            assert_refused(
                api.create_billing_event(
                    enrollment_id,
                    factories.billing_event_payload(event_type, "2026-09-12"),
                    BILLING_OPS,
                ),
                ERR_INVALID_REQUEST,
                400,
            )

        held = fixtures.refresh_enrollment(api, enrollment_id)
        assert_fields(held, {"version": 3, "billing_status": "PAST_DUE"})

        paid = _billing_event(
            api, enrollment_id, "PREMIUM_PAYMENT", "2026-09-12", amount_cents=2499
        )
        assert_fields(
            paid,
            {
                "billing_status": "CURRENT",
                "premium_collected_cents": 2499,
                "version": 4,
            },
        )
        assert_nulls(paid, ["past_due_since"])

        rows, meta = _ledger_page(api, enrollment_id=enrollment_id)
        assert meta["total_count"] == 1, (
            f"one cash row is expected, got total_count {meta['total_count']}"
        )
        assert_fields(
            rows[0],
            {"ledger_kind": "CASH", "entry_type": "PREMIUM_PAYMENT", "amount_cents": 2499},
        )

    def test_bill_insert_billing_mode_needs_partner_support(self, api):
        """The flag that decides the request lives two hops from the payload.

        PRD: "A partner whose `bill_insert_supported` is false cannot host a bill-inserted policy, and the attempt is refused with `ERR_BILL_INSERT_NOT_SUPPORTED`."

        Design: Corner/validations/bill_insert_billing_mode_needs_partner_support
        """
        fixtures.set_clock(api, CLOCK_START)
        sewer_partner = fixtures.create_partner(
            api,
            name="Willamette Sewer",
            utility_type="WASTEWATER",
            bill_insert_supported=False,
        )
        sewer_product = fixtures.file_product(
            api,
            sewer_partner["id"],
            name="Sewer Guard Basic",
            line_type="SEWER_LATERAL",
            ownership_boundary="PROPERTY_LINE",
            required_owned_segment="SEWER_PROPERTY_LINE_TO_MAIN",
            monthly_price_cents=3299,
            per_occurrence_cap_cents=900000,
            annual_cap_cents=1200000,
        )
        fixtures.activate_partner(
            api, sewer_partner["id"], fixtures.refresh_partner_version(api, sewer_partner["id"])
        )
        sewer_premises = fixtures.create_premises(
            api,
            sewer_partner["id"],
            street_address="44 Birch Ln",
            owned_segments=["SEWER_PROPERTY_LINE_TO_MAIN"],
        )
        assert sewer_premises["version"] == 1

        # The second partner differs only in bill_insert_supported.
        water = fixtures.active_partner_with_product(api)
        water_premises = fixtures.create_premises(api, water["partner_id"])

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)

        assert_refused(
            api.create_enrollment(
                factories.bill_insert_enrollment_payload(
                    sewer_premises["id"], sewer_product["id"], sewer_premises["version"]
                ),
                CUSTOMER_SERVICE_REP,
            ),
            ERR_BILL_INSERT_NOT_SUPPORTED,
            422,
        )
        assert_list_envelope(
            api.list_enrollments(PLATFORM_ADMIN, params={"premises_id": sewer_premises["id"]}), 0
        )
        assert fixtures.refresh_premises_version(api, sewer_premises["id"]) == 1

        # The same premises and product, with the mode the partner does support.
        sewer_enrollment = fixtures.create_enrollment(
            api,
            sewer_premises["id"],
            sewer_product["id"],
            sewer_premises["version"],
            # Omitted so the DIRECT_BILL default of twelve monthly premiums applies.
            prepaid_amount_cents=None,
        )
        assert_fields(
            sewer_enrollment,
            {
                "billing_mode": "DIRECT_BILL",
                "monthly_price_cents": 3299,
                "prepaid_amount_cents": 39588,
            },
        )

        water_enrollment = fixtures.create_bill_insert_enrollment(
            api, water_premises["id"], water["product_id"], water_premises["version"]
        )
        assert_fields(
            water_enrollment,
            {
                "billing_mode": "BILL_INSERT",
                "prepaid_amount_cents": 0,
                "billing_status": "CURRENT",
            },
        )

        for enrollment_id in (sewer_enrollment["id"], water_enrollment["id"]):
            current = fixtures.refresh_enrollment(api, enrollment_id)
            assert current["coverage_status"] == "PENDING_WAITING_PERIOD", (
                f"enrollment {enrollment_id} should still be waiting, "
                f"got {current['coverage_status']!r}"
            )
            assert_instant(
                current["coverage_effective_at"], COVERAGE_EFFECTIVE_AT, "coverage_effective_at"
            )

    def test_approved_quantity_above_requested_is_invalid_request(self, api):
        """The ceiling is the campaign's own requested quantity, and it is one-sided.

        PRD: "An approval moves the campaign `PARTNER_REVIEW → APPROVED` and sets `approved_quantity` to the supplied value, defaulting to the campaign's `requested_quantity` when the decision omits it; a supplied `approved_quantity` above `requested_quantity` is refused with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/approved_quantity_above_requested_is_invalid_request
        """
        world = fixtures.active_partner_with_product(api)
        reviewer = make_partner_brand_reviewer_headers(world["partner_id"])

        campaigns = []
        # The two drops are 21 days apart, the partner's min_days_between_drops.
        for name, drop_date in (
            ("August curb-stop postcard", "2026-08-05"),
            ("September curb-stop postcard", "2026-08-26"),
        ):
            campaign = fixtures.create_campaign(
                api,
                world["partner_id"],
                world["product_id"],
                name=name,
                drop_date=drop_date,
                requested_quantity=500,
            )
            assert campaign["requested_quantity"] == 500
            assert_nulls(campaign, ["approved_quantity"])
            submitted = fixtures.submit_campaign(api, campaign["id"])
            assert_fields(submitted, {"status": "PARTNER_REVIEW", "version": 2})
            campaigns.append(campaign["id"])

        # 750 is a perfectly valid positive integer; only the stored 500 rejects it.
        assert_refused(
            api.decide_campaign(
                campaigns[0],
                factories.campaign_approval_payload(
                    decision_note="Raise the print run.", approved_quantity=750
                ),
                reviewer,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        untouched = validate_success(api.get_campaign(campaigns[0], PLATFORM_ADMIN))
        assert_fields(untouched, {"status": "PARTNER_REVIEW", "version": 2})
        assert_nulls(untouched, ["approved_quantity", "decision_by_user_id"])

        # Exactly equal to the requested quantity is admitted.
        approved = validate_success(
            api.decide_campaign(
                campaigns[0],
                factories.campaign_approval_payload(
                    decision_note="Trim the print run.", approved_quantity=500
                ),
                reviewer,
            ),
            200,
        )
        assert_fields(
            approved,
            {
                "status": "APPROVED",
                "approved_quantity": 500,
                "decision_by_user_id": world["partner_id"],
                "version": 3,
            },
        )

        # Omitting the field defaults it to the requested quantity.
        defaulted = validate_success(
            api.decide_campaign(
                campaigns[1],
                factories.campaign_approval_payload(
                    decision_note="Approve as requested.", approved_quantity=None
                ),
                reviewer,
            ),
            200,
        )
        assert_fields(defaulted, {"status": "APPROVED", "approved_quantity": 500})


class TestConstraintAndTemporalAggregates:
    """Constraint and temporal rules whose input is live state, not a stored flag."""

    def test_duplicate_active_enrollment_is_blocked_but_a_cancelled_one_frees_the_slot(self, api):
        """The same address and product pair is refused, then admitted after cancellation.

        PRD: "And an address may not hold two live policies on the same product — if an existing enrollment on that `product_id` is `PENDING_WAITING_PERIOD`, `ACTIVE` or `SUSPENDED_NONPAY`, the second is refused with `ERR_DUPLICATE_ACTIVE_ENROLLMENT`."

        Design: Corner/validations/duplicate_active_enrollment_is_blocked_but_a_cancelled_one_frees_the_slot
        """
        world = fixtures.enrolled_premises(api)
        first = world["enrollment"]
        assert_fields(
            first,
            {
                "coverage_status": "PENDING_WAITING_PERIOD",
                "term_start": ENROLLMENT_TERM_START,
                "version": 1,
            },
        )
        # Selling the policy stamps the address even though nothing suppresses it:
        # the already-enrolled reason is campaign-scoped, not a standing one.
        premises = validate_success(api.get_premises(world["premises_id"], PLATFORM_ADMIN))
        assert_fields(premises, {"version": 2, "suppression_reason": "NONE"})

        duplicate = factories.enrollment_payload(
            world["premises_id"], world["product_id"], premises["version"]
        )
        assert_refused(
            api.create_enrollment(duplicate, CUSTOMER_SERVICE_REP),
            ERR_DUPLICATE_ACTIVE_ENROLLMENT,
            422,
        )

        # Five of August's thirty-one days are earned, and five days is inside the
        # free-look window, so no fee is charged.
        cancelled = fixtures.cancel_enrollment(api, first["id"], "2026-08-10")
        assert_fields(
            cancelled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "refund_cents": 29585,
                "cancellation_fee_cents": 0,
                "credit_cents": 0,
            },
        )
        # The cancellation writes no premises row, so the refused request's own
        # version guard is still current.
        assert fixtures.refresh_premises_version(api, world["premises_id"]) == 2

        second = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], premises["version"]
        )
        assert second["id"] != first["id"], "the second policy must be a distinct record"
        assert_fields(
            second,
            {"coverage_status": "PENDING_WAITING_PERIOD", "term_start": ENROLLMENT_TERM_START},
        )

        assert_list_envelope(
            api.list_enrollments(PLATFORM_ADMIN, params={"premises_id": world["premises_id"]}), 2
        )
        assert_list_envelope(
            api.list_enrollments(
                PLATFORM_ADMIN,
                params={"premises_id": world["premises_id"], "coverage_status": "CANCELLED"},
            ),
            1,
        )

    def test_cancellation_blocked_by_an_open_appeal_then_allowed_after_the_appeal_closes(self, api):
        """The identical cancellation body flips from 422 to 200 without touching the policy.

        PRD: "One thing blocks it outright: a policy whose `retention_hold` is true — meaning at least one of its claims has an appeal open — is refused with `ERR_CANCELLATION_BLOCKED_APPEAL`."

        Design: Corner/validations/cancellation_blocked_by_an_open_appeal_then_allowed_after_the_appeal_closes
        """
        world = fixtures.active_coverage(api)
        assert world["enrollment"]["retention_hold"] is False
        enrollment_id = world["enrollment_id"]

        claim = fixtures.file_claim(
            api,
            enrollment_id,
            defect_location="INSIDE_HOME",
            incident_description="Interior riser weeping at the elbow.",
        )
        denied = fixtures.deny_claim(
            api,
            claim["id"],
            "OWNERSHIP_INELIGIBLE",
            coverage_note="Interior plumbing sits inside the curb-stop boundary.",
        )
        assert denied["status"] == "DENIED"
        assert_instant(denied["denied_at"], CLOCK_COVERAGE_ACTIVE, "denied_at")

        appealed = _open_appeal(
            api,
            claim["id"],
            world["premises_id"],
            appeal_reason="The utility told me interior work was included.",
        )
        assert_fields(
            appealed,
            {"status": "APPEAL_OPEN", "appeal_source": "POLICYHOLDER", "appeal_count": 1},
        )
        held = fixtures.refresh_enrollment(api, enrollment_id)
        assert_fields(held, {"retention_hold": True, "coverage_status": "ACTIVE"})

        cancellation = factories.cancellation_payload("2026-09-20")
        assert_refused(
            api.cancel_enrollment(enrollment_id, cancellation, CUSTOMER_SERVICE_REP),
            ERR_CANCELLATION_BLOCKED_APPEAL,
            422,
        )
        untouched = fixtures.refresh_enrollment(api, enrollment_id)
        assert_fields(untouched, {"coverage_status": "ACTIVE", "billing_status": "CURRENT"})
        assert_nulls(untouched, ["refund_cents", "cancellation_effective_date"])
        _, meta = _ledger_page(api, enrollment_id=enrollment_id)
        assert meta["total_count"] == 0, (
            f"the refused cancellation must write no ledger row, got {meta['total_count']}"
        )

        # The officer is not the adjuster who denied, so the decision is admissible.
        upheld = validate_success(
            api.decide_appeal(
                claim["id"],
                factories.appeal_decision_payload(
                    "UPHOLD",
                    rationale="The defect is on the interior riser, outside the covered segment.",
                ),
                APPEALS_OFFICER,
            ),
            200,
        )
        assert_fields(
            upheld,
            {
                "status": "APPEAL_UPHELD_DENIAL",
                "appeal_decided_by_user_id": APPEALS_OFFICER_USER_ID,
            },
        )
        assert fixtures.refresh_enrollment(api, enrollment_id)["retention_hold"] is False

        # 27 of August's 31 days plus 19 of September's 30 gives 2177 + 1583; the
        # 46 elapsed days are past the free-look window, so the fee applies.
        settled = validate_success(
            api.cancel_enrollment(enrollment_id, cancellation, CUSTOMER_SERVICE_REP), 200
        )
        assert_fields(
            settled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "cancellation_reason": "CUSTOMER_REQUEST",
                "cancellation_effective_date": "2026-09-20",
                "refund_cents": 23728,
                "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
                "credit_cents": 0,
            },
        )

        rows, meta = _ledger_page(api, enrollment_id=enrollment_id)
        assert meta["total_count"] == 2, (
            f"the settlement books two cash rows, got {meta['total_count']}"
        )
        refunds = entries_of_type(rows, "PRORATION_REFUND")
        fees = entries_of_type(rows, "CANCELLATION_FEE")
        assert len(refunds) == 1 and len(fees) == 1, (
            "expected exactly one proration refund and one cancellation fee row"
        )
        assert_fields(refunds[0], {"ledger_kind": "CASH", "amount_cents": -23728})
        assert_fields(fees[0], {"ledger_kind": "CASH", "amount_cents": CANCELLATION_FEE_CENTS})

    def test_appeal_window_expiry_is_temporal_not_state(self, api):
        """Two claims denied at one instant, appealed one millisecond apart.

        PRD: "And the appeal must arrive within 30 days of `denied_at`; once the logical clock passes `denied_at` plus 30 days the request is refused with `ERR_APPEAL_WINDOW_EXPIRED`, the boundary being inclusive on the appellant's side — an appeal at exactly the 30-day instant is still accepted."

        Design: Corner/validations/appeal_window_expiry_is_temporal_not_state
        """
        world = fixtures.active_coverage(api)
        claim_a = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="INSIDE_HOME",
            incident_description="Interior riser weeping at the elbow.",
        )
        claim_b = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="INSIDE_HOME",
            incident_description="Second interior riser weeping at the elbow.",
        )
        note = "Interior plumbing sits inside the curb-stop boundary."
        denied_a = fixtures.deny_claim(api, claim_a["id"], "OWNERSHIP_INELIGIBLE", coverage_note=note)
        denied_b = fixtures.deny_claim(api, claim_b["id"], "OWNERSHIP_INELIGIBLE", coverage_note=note)
        assert denied_a["status"] == "DENIED"
        assert_instant(denied_a["denied_at"], CLOCK_COVERAGE_ACTIVE, "denied_at")
        assert_instant(denied_b["denied_at"], CLOCK_COVERAGE_ACTIVE, "denied_at")

        # No overnight run happens anywhere in this test, so both claims are still
        # DENIED and only the temporal rule can refuse the second appeal.
        fixtures.set_clock(api, APPEAL_BOUNDARY)
        appealed = _open_appeal(
            api,
            claim_a["id"],
            world["premises_id"],
            appeal_reason="The utility told me interior work was included.",
        )
        assert_fields(appealed, {"status": "APPEAL_OPEN", "appeal_count": 1})
        assert_instant(appealed["appeal_opened_at"], APPEAL_BOUNDARY, "appeal_opened_at")

        fixtures.set_clock(api, APPEAL_BOUNDARY_PLUS_1MS)
        assert_refused(
            api.create_appeal(
                claim_b["id"],
                factories.appeal_payload(
                    appeal_reason="The utility told me interior work was included."
                ),
                make_policyholder_headers(world["premises_id"]),
            ),
            ERR_APPEAL_WINDOW_EXPIRED,
            422,
        )

        untouched = fixtures.refresh_claim(api, claim_b["id"])
        assert_fields(untouched, {"status": "DENIED", "appeal_count": 0})
        assert_nulls(untouched, ["appeal_opened_at", "appeal_source"])

        # The accepted appeal alone placed the retention hold.
        assert fixtures.refresh_enrollment(api, world["enrollment_id"])["retention_hold"] is True

    def test_contractor_capacity_is_an_aggregate_over_open_dispatches(self, api):
        """Three impeccable dispatches, one ceiling, and the refusal lifts on completion.

        PRD: "When it was, `selection_mode` is `MANUAL`, the scoring pass is skipped entirely, and the named contractor is used — but every eligibility condition is still enforced individually, so that a bad manual choice fails with a precise reason rather than a generic one: a contractor whose `status` is not `ACTIVE` is refused with `ERR_CONTRACTOR_NOT_ACTIVE`, an expired licence with `ERR_CONTRACTOR_LICENSE_EXPIRED`, a missing certification with `ERR_CONTRACTOR_NOT_CERTIFIED`, a full book with `ERR_CONTRACTOR_CAPACITY_EXCEEDED`, and a contractor who cannot pull permits on a product whose `permit_covered` is true with `ERR_PERMIT_REQUIRED`."

        Design: Corner/validations/contractor_capacity_is_an_aggregate_over_open_dispatches
        """
        world = fixtures.active_coverage(api)
        contractor = fixtures.create_contractor(
            api,
            name="Alder Plumbing",
            license_number="OR-PL-4411",
            license_expires_on="2027-06-30",
            max_open_dispatches=2,
        )
        assert_fields(contractor, {"max_open_dispatches": 2, "open_dispatch_count": 0})

        claims = []
        for location, description in (
            ("CURB_STOP_TO_METER", "Curb stop weeping into the parking strip."),
            ("METER_TO_HOME", "Meter-to-home run leaking under the lawn."),
            ("CURB_STOP_TO_METER", "Second curb-stop seep further along the run."),
        ):
            claim = fixtures.file_claim(
                api,
                world["enrollment_id"],
                defect_location=location,
                incident_description=description,
            )
            approved = fixtures.approve_claim(api, claim["id"])
            assert approved["version"] == 2
            claims.append(claim["id"])

        # Three different days, so no window conflict can precede the ceiling.
        first = fixtures.dispatch_claim_to(
            api, claims[0], 2, contractor["id"], window_start="2026-09-10T09:00:00.000Z"
        )
        assert first["status"] == "ASSIGNED"
        fixtures.dispatch_claim_to(
            api, claims[1], 2, contractor["id"], window_start="2026-09-11T09:00:00.000Z"
        )
        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 2

        third = factories.manual_dispatch_payload(2, "2026-09-12T09:00:00.000Z", contractor["id"])
        assert_refused(
            api.create_dispatch(claims[2], third, OPERATIONS_ADMIN),
            ERR_CONTRACTOR_CAPACITY_EXCEEDED,
            422,
        )
        assert_fields(fixtures.refresh_claim(api, claims[2]), {"status": "APPROVED", "version": 2})
        assert_list_envelope(
            api.list_dispatches(PLATFORM_ADMIN, params={"contractor_id": contractor["id"]}), 2
        )

        accepted = fixtures.accept_dispatch(api, first["id"], contractor["id"])
        assert accepted["status"] == "ACCEPTED"
        completed = fixtures.complete_dispatch(
            api, first["id"], contractor["id"], labor_cents=100000, materials_cents=50000
        )
        assert_fields(
            completed,
            {
                "status": "COMPLETED",
                "invoice_total_cents": 150000,
                "benefit_paid_cents": 150000,
            },
        )
        # A completed dispatch leaves the open set, so the aggregate falls.
        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 1

        # The byte-identical request now fits under the ceiling.
        retried = validate_success(
            api.create_dispatch(claims[2], third, OPERATIONS_ADMIN), 201
        )
        assert_fields(retried, {"status": "ASSIGNED", "selection_mode": "MANUAL"})
        assert retried["id"] != first["id"], "the retry must create a new dispatch"

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(
            enrollment,
            {
                "annual_benefit_used_cents": 150000,
                "cap_status": "WITHIN_CAP",
                "annual_benefit_reserved_cents": 456000,
            },
        )
