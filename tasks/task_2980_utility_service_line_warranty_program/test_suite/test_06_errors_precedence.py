"""Refusal precedence and error-identifier tests (PRD §2.8, §5).

Every test in this module drives a request that violates more than one rule at
once and pins which of the competing refusals the caller is entitled to see, or
pins that each addressed collection answers with its own not-found identifier.
The HTTP status of every refusal is cross-checked against the PRD §5 catalogue by
``assert_refused``.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_REQUEST,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PARTNER_NOT_FOUND,
    ERR_PREMISES_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_error_shape,
    assert_fields,
    assert_list_envelope,
    assert_refused,
    assert_request_meta,
)
from test_helpers.constants import (
    CLOCK_START,
    ENROLLMENT_TERM_END,
    ENROLLMENT_TERM_START,
    ROLE_MARKETING_OPS,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CUSTOMER_SERVICE_REP,
    EMPTY_USER_ID_HEADERS,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_partner_brand_reviewer_headers,
)

# A well-formed UUID that matches no row of any collection (PRD §2.4: "Any
# identifier a client sends in a path segment or a request body must be a
# well-formed UUID").
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# The two shapes of a missing identity from PRD §2.1, carried under a role that
# the target operation does not admit. The blank form sends the empty string
# rather than a whitespace run, because a whitespace header value never leaves
# the client.
NO_USER_ID_MARKETING_OPS = {
    "X-User-Role": ROLE_MARKETING_OPS,
    "Content-Type": "application/json",
}
BLANK_USER_ID_MARKETING_OPS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_MARKETING_OPS,
    "Content-Type": "application/json",
}


class TestAuthenticationPrecedence:
    """Tier 1 of the refusal ladder runs before every other tier."""

    def test_absent_or_blank_user_id_outranks_the_role_check(self, api):
        """A missing identity is reported as 401 even when the role is forbidden too.

        PRD: "A request whose `X-User-ID` header is absent or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is inspected — including before the role is examined and before the URL is resolved."

        Design: Corner/errors/err_unauthenticated_blank_header_outranks_the_role_check
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = fixtures.create_partner(api)
        payload = factories.partner_status_change_payload(
            "ACTIVE", partner["version"], reason="No header at all."
        )

        # MarketingOps is not admitted on a partner status change, yet the
        # missing identity is what is reported.
        absent = api.change_partner_status(
            partner["id"], payload, NO_USER_ID_MARKETING_OPS
        )
        assert_refused(absent, ERR_UNAUTHENTICATED)
        assert_error_shape(absent)
        assert_request_meta(absent)

        blank = api.change_partner_status(
            partner["id"],
            factories.partner_status_change_payload(
                "ACTIVE", partner["version"], reason="Header present but empty string."
            ),
            BLANK_USER_ID_MARKETING_OPS,
        )
        assert_refused(blank, ERR_UNAUTHENTICATED)

        # Reads are authenticated too, and here the role would have been admitted.
        read = api.get_partner(partner["id"], EMPTY_USER_ID_HEADERS)
        assert_refused(read, ERR_UNAUTHENTICATED)

        # None of the three refused calls mutated the partner.
        after = validate_success(api.get_partner(partner["id"], PLATFORM_ADMIN))
        assert_fields(after, {"status": "ONBOARDING", "version": 1})


class TestRolePermissionPrecedence:
    """Tier 2 outranks the existence check of tier 5 and the bounds of tier 4."""

    def test_unauthorized_role_outranks_path_existence(self, api):
        """A forbidden role never learns whether the addressed row exists.

        PRD: "Which error the caller sees is not a matter of implementation convenience: validations are evaluated in a strict ascending precedence, the **first** violated rule produces the response, and no later rule is evaluated."

        Design: Corner/errors/err_unauthorized_role_outranks_path_existence
        """
        fixtures.set_clock(api, CLOCK_START)

        # A write whose role is wrong and whose path id does not exist.
        wrong_role_missing_claim = api.triage_claim(
            MISSING_UUID,
            factories.triage_approval_payload(coverage_note="Wrong role, unknown claim."),
            MARKETING_OPS,
        )
        assert_refused(wrong_role_missing_claim, ERR_UNAUTHORIZED)

        # The shared read scope of a CustomerServiceRep excludes the
        # regulator-complaint reads, so the missing row is never reported.
        out_of_read_scope = api.get_complaint(MISSING_UUID, CUSTOMER_SERVICE_REP)
        assert_refused(out_of_read_scope, ERR_UNAUTHORIZED)

        # Tier 2 also outranks the tier-4 pagination bound.
        out_of_range_limit = api.list_claims(MARKETING_OPS, params={"limit": 5000})
        assert_refused(out_of_range_limit, ERR_UNAUTHORIZED)


class TestSchemaPrecedence:
    """Tier 3 outranks both existence tiers, so a schema bug is never a 404."""

    def test_schema_violation_outranks_path_and_body_existence(self, api):
        """A malformed body is reported as 400 even when its identifiers are bogus.

        PRD: "On every operation that carries a body: a missing required field, a field of the wrong JSON type, an unknown enum member, or a violation of a declared length or range constraint yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/err_schema_violation_outranks_path_and_body_existence
        """
        fixtures.set_clock(api, CLOCK_START)

        # A required field is omitted while the body foreign key is unresolvable.
        missing_field = api.create_claim(
            factories.claim_payload(
                MISSING_UUID,
                urgency=None,
                incident_description="urgency omitted on purpose.",
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(missing_field, ERR_INVALID_REQUEST)

        # An enum member outside the declared set, same unresolvable foreign key.
        bad_enum = api.create_claim(
            factories.claim_payload(
                MISSING_UUID,
                line_type="WATER_MAIN",
                incident_description="line_type is not a member of the declared enum.",
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(bad_enum, ERR_INVALID_REQUEST)

        # A declared length/charset constraint: state_code is exactly two
        # uppercase letters, so the bogus partner_id is never reached.
        bad_state_code = api.create_premises(
            factories.premises_payload(
                MISSING_UUID, street_address="18 Alder Court", state_code="OREGON"
            ),
            MARKETING_OPS,
        )
        assert_refused(bad_state_code, ERR_INVALID_REQUEST)


class TestPathAndBodyExistence:
    """Tier 5 speaks each collection's own code, and tier 6 runs only after it."""

    def test_every_path_collection_returns_its_own_not_found_code(self, api):
        """The same unresolvable UUID yields nine distinct not-found identifiers.

        PRD: "On every endpoint with a path parameter, a well-formed UUID that matches no row of the addressed collection yields that collection's own not-found code (404): `ERR_PARTNER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`."

        Design: Corner/errors/err_every_path_collection_returns_its_own_not_found_code
        """
        fixtures.set_clock(api, CLOCK_START)

        # A PlatformAdmin is admitted on every read below, so the tier-2 role
        # check can never pre-empt the tier-5 existence check.
        reads = [
            (api.get_product(MISSING_UUID, PLATFORM_ADMIN), ERR_PRODUCT_NOT_FOUND),
            (api.get_premises(MISSING_UUID, PLATFORM_ADMIN), ERR_PREMISES_NOT_FOUND),
            (api.get_campaign(MISSING_UUID, PLATFORM_ADMIN), ERR_CAMPAIGN_NOT_FOUND),
            (api.get_enrollment(MISSING_UUID, PLATFORM_ADMIN), ERR_ENROLLMENT_NOT_FOUND),
            (api.get_claim(MISSING_UUID, PLATFORM_ADMIN), ERR_CLAIM_NOT_FOUND),
            (api.get_contractor(MISSING_UUID, PLATFORM_ADMIN), ERR_CONTRACTOR_NOT_FOUND),
            (api.get_dispatch(MISSING_UUID, PLATFORM_ADMIN), ERR_DISPATCH_NOT_FOUND),
            (api.get_ledger_entry(MISSING_UUID, PLATFORM_ADMIN), ERR_LEDGER_ENTRY_NOT_FOUND),
            (api.get_complaint(MISSING_UUID, PLATFORM_ADMIN), ERR_COMPLAINT_NOT_FOUND),
        ]

        seen = []
        for response, expected_error in reads:
            data = assert_refused(response, expected_error)
            seen.append(data["error_id"])

        assert len(set(seen)) == len(seen), (
            f"each collection must own its not-found code, got {seen}"
        )

    def test_body_foreign_keys_resolve_only_after_the_path_id(self, api):
        """The path identifier is reported first, then each body key's own 404.

        PRD: "Because this tier sits below tier 5, a request with both a bad path identifier and a bad body identifier reports the path failure."

        Design: Corner/errors/err_body_foreign_keys_resolve_only_after_the_path_id
        """
        world = fixtures.filed_claim(api)
        claim_id = world["claim_id"]
        claim_version = world["claim_version"]
        window_start = fixtures.DEFAULT_WINDOW_START

        # Both the path claim and the body contractor are unresolvable: the path
        # failure is the one reported.
        path_and_body_bad = api.create_dispatch(
            MISSING_UUID,
            factories.manual_dispatch_payload(claim_version, window_start, MISSING_UUID),
            OPERATIONS_ADMIN,
        )
        assert_refused(path_and_body_bad, ERR_CLAIM_NOT_FOUND)

        # With the path resolved, the body foreign key answers with its own code
        # — and does so even though the claim is still in TRIAGE, which is a
        # later tier.
        bad_contractor = api.create_dispatch(
            claim_id,
            factories.manual_dispatch_payload(claim_version, window_start, MISSING_UUID),
            OPERATIONS_ADMIN,
        )
        assert_refused(bad_contractor, ERR_CONTRACTOR_NOT_FOUND)

        bad_supersedes = api.create_dispatch(
            claim_id,
            factories.manual_dispatch_payload(
                claim_version,
                window_start,
                world["contractor_id"],
                supersedes_dispatch_id=MISSING_UUID,
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(bad_supersedes, ERR_DISPATCH_NOT_FOUND)

        # The same identifier raised from a body foreign key rather than a path.
        bad_partner_fk = api.create_premises(
            factories.premises_payload(MISSING_UUID, street_address="20 Alder Court"),
            MARKETING_OPS,
        )
        assert_refused(bad_partner_fk, ERR_PARTNER_NOT_FOUND)

        # Nothing was created and the claim never left TRIAGE.
        rows, _ = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim_id}),
            expected_total=0,
        )
        assert rows == [], f"no dispatch may exist for the claim, got {rows}"
        claim = validate_success(api.get_claim(claim_id, PLATFORM_ADMIN))
        assert_fields(claim, {"status": "TRIAGE", "version": claim_version})


class TestOwnershipAndStateGatePrecedence:
    """Tier 7 outranks tier 10, and tier 10 outranks tier 11."""

    def test_ownership_check_outranks_the_campaign_state_gate(self, api):
        """A foreign reviewer is refused as a non-owner, learning nothing of the state.

        PRD: "An entity-backed caller acting outside its own scope yields `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/errors/err_ownership_check_outranks_the_campaign_state_gate
        """
        world = fixtures.active_partner_with_product(api)
        partner_a = world["partner_id"]
        partner_b = fixtures.create_partner(
            api, name="Willamette Power", utility_type="ELECTRIC"
        )["id"]

        # Partner A's campaign is left in DRAFT, which no decision may act on.
        campaign = fixtures.create_campaign(api, partner_a, world["product_id"])

        foreign_reviewer = api.decide_campaign(
            campaign["id"],
            factories.campaign_approval_payload(
                decision_note="Reviewer of the wrong partner.", approved_quantity=None
            ),
            make_partner_brand_reviewer_headers(partner_b),
        )
        assert_refused(foreign_reviewer, ERR_NOT_RESOURCE_OWNER)

        # With ownership satisfied the state gate is finally reached.
        own_reviewer = api.decide_campaign(
            campaign["id"],
            factories.campaign_approval_payload(
                decision_note="Right reviewer, wrong campaign state.",
                approved_quantity=None,
            ),
            make_partner_brand_reviewer_headers(partner_a),
        )
        assert_refused(own_reviewer, ERR_INVALID_CAMPAIGN_STATE)

        after = validate_success(api.get_campaign(campaign["id"], PLATFORM_ADMIN))
        assert_fields(
            after,
            {"status": "DRAFT", "version": campaign["version"], "approved_quantity": None},
        )

    def test_campaign_state_gate_outranks_the_partner_active_gate(self, api):
        """A withdrawn campaign under a suspended partner reports the campaign state.

        PRD: "A campaign that is not in a state the requested transition leaves from yields `ERR_INVALID_CAMPAIGN_STATE` — submission requires `DRAFT` or `REJECTED`, a decision requires `PARTNER_REVIEW`, a mail drop requires `APPROVED`."

        Design: Corner/errors/err_campaign_state_gate_outranks_the_partner_active_gate
        """
        world = fixtures.approved_campaign(api, fixtures.active_partner_with_product(api))
        partner_id = world["partner_id"]
        campaign_id = world["campaign_id"]

        # Suspension withdraws the approved campaign as one cascade hop.
        suspended = fixtures.change_partner_status(
            api,
            partner_id,
            "SUSPENDED",
            world["partner_version"],
            reason="Regulatory pause on all marketing.",
        )
        assert_fields(
            suspended,
            {
                "status": "SUSPENDED",
                "version": 3,
                "suspension_reason": "Regulatory pause on all marketing.",
            },
        )

        resubmission = api.submit_campaign(
            campaign_id,
            factories.campaign_submission_payload(
                note="Try to resubmit the withdrawn campaign under a suspended partner."
            ),
            MARKETING_OPS,
        )
        assert_refused(resubmission, ERR_INVALID_CAMPAIGN_STATE)

        # create 1, submission 2, decision 3, suspension cascade 4.
        campaign = validate_success(api.get_campaign(campaign_id, PLATFORM_ADMIN))
        assert_fields(campaign, {"status": "WITHDRAWN", "version": 4})

        assert_list_envelope(
            api.list_campaigns(
                PLATFORM_ADMIN, params={"partner_id": partner_id, "status": "WITHDRAWN"}
            ),
            expected_total=1,
        )


class TestConditionalBodyRequirements:
    """One tier-3 rule whose shape depends on a sibling field, on two endpoints."""

    def test_conditional_amount_required_only_for_money_moving_events(self, api):
        """The identical payload shape is invalid for one event type and valid for another.

        PRD: "So does one **conditional** requirement whose shape depends on a sibling field: `amount_cents` must be present when a billing event's `event_type` is `PREMIUM_PAYMENT`, `INSERT_REMITTANCE` or `WRITE_OFF`, and `remedy_amount_cents` must be present when a complaint response's `remedy_type` is `BENEFIT_REVERSAL` or `PREMIUM_REFUND`."

        Design: Corner/errors/err_conditional_amount_required_only_for_money_moving_events
        """
        world = fixtures.enrolled_premises(api)
        world = fixtures.open_complaint(api, world)
        enrollment_id = world["enrollment_id"]
        before_rows = fixtures.ledger_entries(api, enrollment_id=enrollment_id)

        payment = api.create_billing_event(
            enrollment_id,
            factories.billing_event_payload("PREMIUM_PAYMENT", ENROLLMENT_TERM_START),
            BILLING_OPS,
        )
        assert_refused(payment, ERR_INVALID_REQUEST)

        write_off = api.create_billing_event(
            enrollment_id,
            factories.billing_event_payload("WRITE_OFF", ENROLLMENT_TERM_START),
            BILLING_OPS,
        )
        assert_refused(write_off, ERR_INVALID_REQUEST)

        # The same shape — no amount_cents at all — is accepted for the one event
        # type that moves no money.
        accepted = get_success_data(
            api.create_billing_event(
                enrollment_id,
                factories.billing_event_payload("MISSED_PAYMENT", ENROLLMENT_TERM_START),
                BILLING_OPS,
            )
        )
        assert_fields(
            accepted,
            {
                "billing_status": "PAST_DUE",
                "past_due_since": ENROLLMENT_TERM_START,
                "version": world["enrollment_version"] + 1,
            },
        )

        # A missed payment writes no ledger row at all.
        after_rows = fixtures.ledger_entries(api, enrollment_id=enrollment_id)
        assert [row["id"] for row in after_rows] == [row["id"] for row in before_rows], (
            "a missed payment moves no money and must append no ledger row"
        )

        # The same conditional rule on the complaint response pre-empts the much
        # later remedy-target check, even though this complaint cites no policy.
        response = api.respond_to_complaint(
            world["complaint_id"],
            factories.complaint_response_payload(
                "SUBSTANTIATED", "PREMIUM_REFUND", world["complaint_version"],
                response_summary="Premium will be refunded.",
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(response, ERR_INVALID_REQUEST)

        complaint = validate_success(
            api.get_complaint(world["complaint_id"], REGULATORY_AFFAIRS)
        )
        assert_fields(
            complaint, {"status": "OPEN", "version": world["complaint_version"]}
        )


class TestRequestShapeBusinessRules:
    """Two rules the PRD deliberately reports as ERR_INVALID_REQUEST (400)."""

    def test_approved_quantity_above_the_requested_quantity_is_invalid_request(self, api):
        """A reviewer may trim the quantity but never raise it; equality is admitted.

        PRD: "An approval moves the campaign `PARTNER_REVIEW → APPROVED` and sets `approved_quantity` to the supplied value, defaulting to the campaign's `requested_quantity` when the decision omits it; a supplied `approved_quantity` above `requested_quantity` is refused with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/err_approved_quantity_above_the_requested_quantity_is_invalid_request
        """
        world = fixtures.active_partner_with_product(api)
        campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"], requested_quantity=1000
        )
        submitted = fixtures.submit_campaign(api, campaign["id"])

        above = api.decide_campaign(
            campaign["id"],
            factories.campaign_approval_payload(
                decision_note="Reviewer tries to buy more mail than marketing asked for.",
                approved_quantity=1500,
            ),
            make_partner_brand_reviewer_headers(world["partner_id"]),
        )
        assert_refused(above, ERR_INVALID_REQUEST)

        still_in_review = validate_success(
            api.get_campaign(campaign["id"], PLATFORM_ADMIN)
        )
        assert_fields(
            still_in_review,
            {"status": "PARTNER_REVIEW", "version": submitted["version"]},
        )

        # The boundary approved_quantity == requested_quantity is permitted.
        approved = fixtures.approve_campaign(
            api,
            campaign["id"],
            world["partner_id"],
            decision_note="Approved at exactly the requested quantity.",
            approved_quantity=1000,
        )
        assert_fields(
            approved,
            {"status": "APPROVED", "approved_quantity": 1000, "version": 3},
        )

    def test_cancellation_date_outside_the_term_is_invalid_request(self, api):
        """Both ends of the closed term interval are enforced; term_start is legal.

        PRD: "The request carries a `reason` — recorded as `cancellation_reason`, one of `CUSTOMER_REQUEST`, `MOVED`, `NONPAYMENT` or `REGULATOR_REMEDY` — and a `requested_effective_date`, which must fall on or after `term_start` and on or before `term_end`; outside that range the request is refused with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/err_cancellation_date_outside_the_term_is_invalid_request
        """
        world = fixtures.enrolled_premises(api)
        enrollment_id = world["enrollment_id"]
        assert_fields(
            world["enrollment"],
            {"term_start": ENROLLMENT_TERM_START, "term_end": ENROLLMENT_TERM_END},
        )

        one_day_early = api.cancel_enrollment(
            enrollment_id, factories.cancellation_payload("2026-08-04"), CUSTOMER_SERVICE_REP
        )
        assert_refused(one_day_early, ERR_INVALID_REQUEST)

        one_day_late = api.cancel_enrollment(
            enrollment_id, factories.cancellation_payload("2027-08-06"), CUSTOMER_SERVICE_REP
        )
        assert_refused(one_day_late, ERR_INVALID_REQUEST)

        # term_start itself is a legal cancellation date, and earns nothing: the
        # earned span is the half-open interval [term_start, term_start).
        settled = fixtures.cancel_enrollment(api, enrollment_id, ENROLLMENT_TERM_START)
        assert_cents(settled["refund_cents"], "refund_cents")
        assert_cents(settled["credit_cents"], "credit_cents")
        assert_cents(settled["cancellation_fee_cents"], "cancellation_fee_cents")
        assert_fields(
            settled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "cancellation_effective_date": ENROLLMENT_TERM_START,
                "cancellation_fee_cents": 0,
                "refund_cents": 29988,
                "credit_cents": 0,
            },
        )
