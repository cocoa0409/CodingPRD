"""State-machine behaviour of the Utility Service Line Warranty Program API.

Every test here proves one declared transition, initial state, terminal
lockdown or cascade of the PRD: the campaign approval cycle of §3.2, the
partner lifecycle and its withdrawal cascade of §3.1 and §2.9, the initial
states of §3.3, §3.5, §3.6 and §3.8, the per-event dispatch guards of §3.6 and
§3.7, the nightly response-breach sweep of §3.9, and the reinstatement remedy
of §3.8.

The logical clock (PRD §2.5) is pinned by every setup chain, because "there is
no wall clock" and each of these rules reads a deadline or stamps an instant
from it.
"""

import pytest

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_DISPATCH_STATE,
    ERR_INVALID_PARTNER_STATE,
    ERR_REVISION_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_created_at_ascending,
    assert_created_resource,
    assert_drop_summary_shape,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_instant_format,
    assert_ledger_amounts,
    assert_list_envelope,
    assert_nightly_lists_empty,
    assert_nightly_report_shape,
    assert_nulls,
    assert_object_envelope,
    assert_refused,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_START,
    ENROLLMENT_TERM_END,
    ENROLLMENT_TERM_START,
)
from test_helpers.test_users import (
    CLAIMS_ADJUSTER,
    CLAIMS_ADJUSTER_USER_ID,
    MARKETING_OPS,
    MARKETING_OPS_USER_ID,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    make_network_contractor_headers,
    make_partner_brand_reviewer_headers,
)

# The contractor of PRD §3.6's worked comparison: sla_compliance_pct 92,
# hourly_rate_cents 18000 and five open slots.
ALDER_PLUMBING = {
    "name": "Alder Plumbing",
    "license_number": "OR-PL-4411",
    "license_expires_on": "2027-06-30",
    "hourly_rate_cents": 18000,
    "sla_compliance_pct": 92,
    "max_open_dispatches": 5,
}

DISPATCH_WINDOW_START = "2026-09-10T09:00:00.000Z"


class TestCampaignLifecycleTransitions:
    """The DRAFT → PARTNER_REVIEW → APPROVED / REJECTED cycle of PRD §3.2."""

    def test_campaign_submission_moves_draft_to_partner_review(self, api):
        """A first submission advances the state and the version but not revision_count.

        PRD: "Submitting the draft for brand review moves it `DRAFT → PARTNER_REVIEW` and stamps `submitted_by_user_id` with the submitting operator's `X-User-ID`."

        Design: Corner/state_machines/campaign_submission_moves_draft_to_partner_review
        """
        world = fixtures.active_partner_with_product(api)
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="Curb Stop Fall Mailer",
            piece_type="POSTCARD",
            drop_date="2026-08-26",
            requested_quantity=100,
        )
        # "The campaign opens in `DRAFT` with `version` 1, `revision_count` 0"
        assert_created_resource(campaign)
        assert_fields(campaign, {"status": "DRAFT", "revision_count": 0})

        response = api.submit_campaign(
            campaign["id"],
            factories.campaign_submission_payload(
                note="Creative approved internally; sending for brand review."
            ),
            MARKETING_OPS,
        )
        submitted = assert_object_envelope(response)
        assert_fields(
            submitted,
            {
                "status": "PARTNER_REVIEW",
                "version": 2,
                "submitted_by_user_id": MARKETING_OPS_USER_ID,
                # Only a resubmission "increments `revision_count` by 1".
                "revision_count": 0,
            },
        )
        # "its `approved_quantity` is null" until a decision is taken, and
        # `decided_at` is "the logical clock at the moment of the decision".
        assert_nulls(submitted, ["approved_quantity", "decided_at"])

        rows, _meta = assert_list_envelope(
            api.list_campaigns(
                MARKETING_OPS,
                params={"partner_id": world["partner_id"], "status": "PARTNER_REVIEW"},
            ),
            expected_total=1,
        )
        assert_ids_in_order(rows, [campaign["id"]])

    def test_campaign_approval_applies_every_declared_side_effect(self, api):
        """One approval writes the trimmed quantity, the decider, the note and the instant.

        PRD: "An approval moves the campaign `PARTNER_REVIEW → APPROVED` and sets `approved_quantity` to the supplied value, defaulting to the campaign's `requested_quantity` when the decision omits it; a supplied `approved_quantity` above `requested_quantity` is refused with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/campaign_approval_applies_every_declared_side_effect
        """
        world = fixtures.active_partner_with_product(api)
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="Curb Stop Fall Mailer",
            piece_type="DIRECT_MAIL_LETTER",
            drop_date="2026-08-26",
            requested_quantity=500,
        )
        submitted = fixtures.submit_campaign(
            api, campaign["id"], note="Sending for brand review."
        )
        assert_fields(submitted, {"status": "PARTNER_REVIEW", "version": 2})

        decision_note = "Approved at a reduced volume for this quarter."
        response = api.decide_campaign(
            campaign["id"],
            factories.campaign_approval_payload(
                decision_note=decision_note, approved_quantity=300
            ),
            make_partner_brand_reviewer_headers(world["partner_id"]),
        )
        decided = assert_object_envelope(response)
        assert_fields(
            decided,
            {
                "status": "APPROVED",
                "version": 3,
                "approved_quantity": 300,
                # "When `X-User-Role` is `PartnerBrandReviewer`, `X-User-ID` is
                # the `id` of the acting `UtilityPartner`".
                "decision_by_user_id": world["partner_id"],
                "decision_note": decision_note,
                "revision_count": 0,
                "mailed_count": 0,
            },
        )
        assert_instant_format(decided["decided_at"], "decided_at")
        assert_instant(decided["decided_at"], CLOCK_START, "decided_at")

        fetched = assert_object_envelope(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(fetched, {"requested_quantity": 500, "approved_quantity": 300})

    def test_campaign_revision_cycle_terminates_at_the_revision_limit(self, api):
        """The REJECTED → PARTNER_REVIEW loop admits two revisions and refuses the third.

        PRD: "The cycle is bounded: a campaign whose `revision_count` has already reached 2 may not be resubmitted again, and the third attempt is refused with `ERR_REVISION_LIMIT_REACHED`."

        Design: Corner/state_machines/campaign_revision_cycle_terminates_at_the_revision_limit
        """
        world = fixtures.active_partner_with_product(api)
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="Curb Stop Fall Mailer",
            piece_type="POSTCARD",
            drop_date="2026-08-26",
            requested_quantity=100,
        )
        partner_id = world["partner_id"]

        first = fixtures.submit_campaign(api, campaign["id"], note="Initial submission.")
        assert_fields(first, {"status": "PARTNER_REVIEW", "revision_count": 0, "version": 2})

        rejected_once = fixtures.reject_campaign(
            api, campaign["id"], partner_id,
            decision_note="Headline overstates the coverage.",
        )
        assert_fields(rejected_once, {"status": "REJECTED", "version": 3})

        second = fixtures.submit_campaign(api, campaign["id"], note="Headline reworded.")
        assert_fields(second, {"status": "PARTNER_REVIEW", "revision_count": 1, "version": 4})

        rejected_twice = fixtures.reject_campaign(
            api, campaign["id"], partner_id,
            decision_note="Logo placement still wrong.",
        )
        assert_fields(rejected_twice, {"status": "REJECTED", "version": 5})

        third = fixtures.submit_campaign(api, campaign["id"], note="Logo moved to the reverse.")
        assert_fields(third, {"status": "PARTNER_REVIEW", "revision_count": 2, "version": 6})

        rejected_thrice = fixtures.reject_campaign(
            api, campaign["id"], partner_id,
            decision_note="Legal has withdrawn support.",
        )
        assert_fields(rejected_thrice, {"status": "REJECTED", "revision_count": 2, "version": 7})

        response = api.submit_campaign(
            campaign["id"],
            factories.campaign_submission_payload(note="Fourth attempt."),
            MARKETING_OPS,
        )
        assert_refused(response, ERR_REVISION_LIMIT_REACHED)

        after = assert_object_envelope(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(after, {"status": "REJECTED", "revision_count": 2, "version": 7})

    def test_mail_drop_on_a_campaign_in_partner_review_returns_invalid_campaign_state(self, api):
        """A drop attempted from PARTNER_REVIEW is refused and touches no premises.

        PRD: "A campaign that is not in a state the requested transition leaves from yields `ERR_INVALID_CAMPAIGN_STATE` — submission requires `DRAFT` or `REJECTED`, a decision requires `PARTNER_REVIEW`, a mail drop requires `APPROVED`."

        Design: Corner/state_machines/mail_drop_on_a_campaign_in_partner_review_returns_invalid_campaign_state
        """
        world = fixtures.partner_product_premises(api)
        campaign = fixtures.create_campaign(
            api,
            world["partner_id"],
            world["product_id"],
            name="Curb Stop Summer Mailer",
            piece_type="POSTCARD",
            drop_date="2026-08-05",
            requested_quantity=50,
        )
        # The partner stays ACTIVE and the drop date is already behind the
        # clock, so neither ERR_PARTNER_NOT_ACTIVE nor ERR_DROP_DATE_IN_FUTURE
        # can answer instead.
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")
        submitted = fixtures.submit_campaign(
            api, campaign["id"], note="Sending for brand review."
        )
        assert_fields(submitted, {"status": "PARTNER_REVIEW", "version": 2})

        response = api.mail_drop(campaign["id"], MARKETING_OPS)
        assert_refused(response, ERR_INVALID_CAMPAIGN_STATE)

        after = assert_object_envelope(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert_fields(
            after,
            {
                "status": "PARTNER_REVIEW",
                "version": 2,
                "mailed_count": 0,
                "suppressed_count": 0,
            },
        )
        assert_nulls(after, ["mail_dropped_at"])

        # "A drop touches every premises on the partner's file" — a refused
        # drop performs no part of that walk.
        premises = assert_object_envelope(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert_fields(
            premises,
            {
                "last_mail_decision": "NOT_EVALUATED",
                "mail_count_current_year": 0,
                "version": 1,
            },
        )


class TestPartnerLifecycleAndWithdrawalCascade:
    """The partner state machine of PRD §3.1 and its cascade of PRD §2.9."""

    def test_terminated_partner_refuses_every_further_status_change(self, api):
        """No target_status is reachable from TERMINATED, not even a repeat of it.

        PRD: "`TERMINATED` is terminal in the strongest sense: no `target_status` whatsoever is reachable from it, and any attempt is refused with `ERR_INVALID_PARTNER_STATE`."

        Design: Corner/state_machines/terminated_partner_refuses_every_further_status_change
        """
        world = fixtures.active_partner_with_product(api)
        partner_id = world["partner_id"]

        terminated = fixtures.change_partner_status(
            api,
            partner_id,
            "TERMINATED",
            world["partner_version"],
            reason="Programme wound down by the utility.",
        )
        assert_fields(
            terminated,
            {
                "status": "TERMINATED",
                "version": 3,
                "suspension_reason": "Programme wound down by the utility.",
            },
        )
        # "Terminating a partner ... transitions every product of that partner
        # to `WITHDRAWN`".
        withdrawn_product = assert_object_envelope(
            api.get_product(world["product_id"], PLATFORM_ADMIN)
        )
        assert_fields(withdrawn_product, {"status": "WITHDRAWN", "version": 2})

        # Each attempt declares the partner's current version, so the
        # optimistic-concurrency guard cannot answer in place of the state guard.
        for target_status in ("ACTIVE", "SUSPENDED", "TERMINATED"):
            response = api.change_partner_status(
                partner_id,
                factories.partner_status_change_payload(
                    target_status, 3, reason="Utility asks for the file to be reopened."
                ),
                PLATFORM_ADMIN,
            )
            assert_refused(response, ERR_INVALID_PARTNER_STATE)

        after = assert_object_envelope(api.get_partner(partner_id, PLATFORM_ADMIN))
        assert_fields(
            after,
            {
                "status": "TERMINATED",
                "version": 3,
                "suspension_reason": "Programme wound down by the utility.",
            },
        )

    def test_partner_suspension_withdraws_only_the_campaigns_that_have_not_mailed(self, api):
        """MAILED is terminal, so the cascade takes the other three campaigns in creation order.

        PRD: "Suspending a partner sets its `suspension_reason` from the request and then, as one cascade hop, transitions every campaign of that partner whose status is `DRAFT`, `PARTNER_REVIEW` or `APPROVED` to `WITHDRAWN` in `created_at` ascending order, incrementing each campaign's `version`."

        Design: Corner/state_machines/partner_suspension_withdraws_only_the_campaigns_that_have_not_mailed
        """
        # A one-day spacing requirement lets four dated campaigns coexist on the
        # same partner file without any of them crowding another's window.
        world = fixtures.partner_product_premises(
            api, partner_overrides={"min_days_between_drops": 1, "max_mailings_per_year": 4}
        )
        partner_id = world["partner_id"]
        product_id = world["product_id"]

        mailed = fixtures.create_campaign(
            api, partner_id, product_id,
            name="M - Early August Drop", drop_date="2026-08-02", requested_quantity=1,
        )
        fixtures.submit_campaign(api, mailed["id"], note="First of the four.")
        fixtures.approve_campaign(
            api, mailed["id"], partner_id,
            approved_quantity=1, decision_note="Approved as requested.",
        )
        fixtures.set_clock(api, "2026-08-03T00:00:00.000Z")
        drop_summary = fixtures.mail_drop(api, mailed["id"])
        assert_drop_summary_shape(drop_summary)
        assert_fields(drop_summary, {"status": "MAILED", "mailed_count": 1})

        draft = fixtures.create_campaign(
            api, partner_id, product_id,
            name="D - Draft Never Submitted", drop_date="2026-08-10", requested_quantity=1,
        )
        in_review = fixtures.create_campaign(
            api, partner_id, product_id,
            name="R - Awaiting Review", drop_date="2026-08-20", requested_quantity=1,
        )
        fixtures.submit_campaign(api, in_review["id"], note="Third of the four.")
        approved = fixtures.create_campaign(
            api, partner_id, product_id,
            name="A - Approved Not Dropped", drop_date="2026-08-30", requested_quantity=1,
        )
        fixtures.submit_campaign(api, approved["id"], note="Fourth of the four.")
        approved_record = fixtures.approve_campaign(
            api, approved["id"], partner_id,
            approved_quantity=1, decision_note="Approved as requested.",
        )
        assert_fields(approved_record, {"status": "APPROVED", "approved_quantity": 1})

        suspended = fixtures.change_partner_status(
            api,
            partner_id,
            "SUSPENDED",
            world["partner_version"],
            reason="Regulatory review of marketing practices.",
        )
        assert_fields(
            suspended,
            {
                "status": "SUSPENDED",
                "version": 3,
                "suspension_reason": "Regulatory review of marketing practices.",
            },
        )

        # "`WITHDRAWN` and `MAILED` are the two terminal campaign states."
        after_mailed = assert_object_envelope(api.get_campaign(mailed["id"], MARKETING_OPS))
        assert_fields(after_mailed, {"status": "MAILED", "version": 4, "mailed_count": 1})
        assert_instant(
            after_mailed["mail_dropped_at"], "2026-08-03T00:00:00.000Z", "mail_dropped_at"
        )

        after_draft = assert_object_envelope(api.get_campaign(draft["id"], MARKETING_OPS))
        assert_fields(after_draft, {"status": "WITHDRAWN", "version": 2})
        assert_nulls(after_draft, ["approved_quantity"])

        after_review = assert_object_envelope(api.get_campaign(in_review["id"], MARKETING_OPS))
        assert_fields(after_review, {"status": "WITHDRAWN", "version": 3})

        # "an `APPROVED` campaign that is withdrawn keeps its
        # `approved_quantity` intact for audit rather than having it cleared."
        after_approved = assert_object_envelope(api.get_campaign(approved["id"], MARKETING_OPS))
        assert_fields(after_approved, {"status": "WITHDRAWN", "version": 4, "approved_quantity": 1})

        rows, _meta = assert_list_envelope(
            api.list_campaigns(
                MARKETING_OPS, params={"partner_id": partner_id, "status": "WITHDRAWN"}
            ),
            expected_total=3,
        )
        assert_created_at_ascending(rows)
        assert_ids_in_order(rows, [draft["id"], in_review["id"], approved["id"]])

        # "In-force coverage is deliberately untouched" — and so is the marketing
        # file, whose only version bump came from the one drop that ran.
        premises = assert_object_envelope(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert_fields(
            premises,
            {
                "last_mail_decision": "MAILED",
                "last_mailed_campaign_id": mailed["id"],
                "mail_count_current_year": 1,
                "version": 2,
            },
        )


class TestDeclaredInitialStates:
    """Every entity of PRD §3.3, §3.5, §3.6 and §3.8 opens where it says it does."""

    def test_claim_dispatch_and_complaint_begin_in_their_declared_initial_states(self, api):
        """Four freshly created records each land on their opening state with version 1.

        PRD: "An accepted claim opens in `TRIAGE` with `version` 1, `appeal_count` 0, and `reported_at` stamped from the logical clock."

        Design: Corner/state_machines/claim_dispatch_and_complaint_begin_in_their_declared_initial_states
        """
        # The enrollment is inspected before the nightly run, because activation
        # would overwrite the very dimensions being proved.
        world = fixtures.enrolled_premises(api, prepaid_amount_cents=None)
        enrollment = world["enrollment"]
        assert_created_resource(enrollment)
        # "three status dimensions that thereafter advance independently:
        # `coverage_status` at `PENDING_WAITING_PERIOD`, `billing_status` at
        # `CURRENT`, and `cap_status` at `WITHIN_CAP`."
        assert_fields(
            enrollment,
            {
                "coverage_status": "PENDING_WAITING_PERIOD",
                "billing_status": "CURRENT",
                "cap_status": "WITHIN_CAP",
                # "`NONE` before any notice exists"
                "renewal_notice_status": "NONE",
                "renewal_count": 0,
            },
        )

        world = fixtures.activate_coverage(api, world)
        assert_fields(world["enrollment"], {"coverage_status": "ACTIVE"})
        contractor = fixtures.create_contractor(api, **ALDER_PLUMBING)

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="URGENT",
            incident_description="Water surfacing at the curb box.",
        )
        assert_created_resource(claim)
        assert_fields(
            claim,
            {"status": "TRIAGE", "appeal_count": 0, "benefit_paid_cents": 0},
        )
        assert_nulls(claim, ["denied_at"])
        assert_instant(claim["reported_at"], CLOCK_COVERAGE_ACTIVE, "reported_at")

        approved = fixtures.approve_claim(
            api,
            claim["id"],
            coverage_note="Curb-stop failure inside the covered boundary.",
        )
        assert_fields(approved, {"status": "APPROVED", "version": 2})

        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            approved["version"],
            contractor["id"],
            window_start=DISPATCH_WINDOW_START,
        )
        # "The dispatch itself opens `ASSIGNED` with `version` 1 and
        # `assigned_at` from the logical clock."
        assert_created_resource(dispatch)
        assert_fields(dispatch, {"status": "ASSIGNED"})
        assert_nulls(dispatch, ["responded_at"])
        assert_instant(dispatch["assigned_at"], CLOCK_COVERAGE_ACTIVE, "assigned_at")

        complaint = fixtures.create_complaint(
            api,
            world["partner_id"],
            allegation="Homeowner reports slow handling of a curb-stop repair.",
        )
        # "It opens `OPEN` with `version` 1, `escalation_count` 0, and
        # `received_at` from the logical clock."
        assert_created_resource(complaint)
        assert_fields(
            complaint,
            {"status": "OPEN", "escalation_count": 0, "days_overdue": 0},
        )
        assert_instant(complaint["received_at"], CLOCK_COVERAGE_ACTIVE, "received_at")

        rows, _meta = assert_list_envelope(
            api.list_dispatches(
                OPERATIONS_ADMIN, params={"claim_id": claim["id"], "status": "ASSIGNED"}
            ),
            expected_total=1,
        )
        assert_ids_in_order(rows, [dispatch["id"]])


class TestClaimAndDispatchStateGuards:
    """The per-event state preconditions of PRD §3.5 and §3.6."""

    def test_dispatch_arrive_and_complete_before_accept_are_both_refused(self, api):
        """ARRIVE and COMPLETE from ASSIGNED are refused, and the later ACCEPT still works.

        PRD: "An event whose state precondition is unmet — accepting a dispatch that is not `ASSIGNED`, arriving at one that is not `ACCEPTED` — is refused with `ERR_INVALID_DISPATCH_STATE`."

        Design: Corner/state_machines/dispatch_arrive_and_complete_before_accept_are_both_refused
        """
        world = fixtures.active_coverage_with_contractor(
            api, contractor_overrides=ALDER_PLUMBING
        )
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="URGENT",
            incident_description="Water surfacing at the curb box.",
        )
        approved = fixtures.approve_claim(
            api,
            claim["id"],
            coverage_note="Curb-stop failure inside the covered boundary.",
        )
        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            approved["version"],
            world["contractor_id"],
            window_start=DISPATCH_WINDOW_START,
        )
        assert_fields(dispatch, {"status": "ASSIGNED"})

        crew = make_network_contractor_headers(world["contractor_id"])
        fixtures.set_clock(api, "2026-09-10T09:30:00.000Z")

        # "Arrival moves `ACCEPTED → ON_SITE`" — there is no path into ON_SITE
        # from ASSIGNED.
        arrive_response = api.create_dispatch_event(
            dispatch["id"], factories.arrive_event_payload(), crew
        )
        assert_refused(arrive_response, ERR_INVALID_DISPATCH_STATE)

        # "Completion is admissible from `ACCEPTED` or `ON_SITE` ... and from
        # anywhere else it is refused with `ERR_INVALID_DISPATCH_STATE`." The
        # dispatch-state tier outranks the permit tier, so a complete carrying no
        # permit number still answers with the state code.
        complete_response = api.create_dispatch_event(
            dispatch["id"],
            factories.complete_event_payload(260000, 175000),
            crew,
        )
        assert_refused(complete_response, ERR_INVALID_DISPATCH_STATE)

        untouched = fixtures.refresh_dispatch(api, dispatch["id"])
        assert_fields(untouched, {"status": "ASSIGNED", "version": 1})
        assert_nulls(untouched, ["responded_at"])

        # The refusals left the machine exactly where it was, so the legitimate
        # first event still lands.
        accept_response = api.create_dispatch_event(
            dispatch["id"], factories.accept_event_payload(), crew
        )
        accepted = assert_object_envelope(accept_response)
        assert_fields(
            accepted, {"status": "ACCEPTED", "version": 2, "response_minutes": 90}
        )
        assert_instant(accepted["responded_at"], "2026-09-10T09:30:00.000Z", "responded_at")

        claim_after = fixtures.refresh_claim(api, claim["id"])
        assert_fields(claim_after, {"status": "DISPATCHED"})

    def test_triaging_an_already_approved_claim_a_second_time_is_refused(self, api):
        """A triage decision is admissible from TRIAGE only, so the second one is refused.

        PRD: "A claim in the wrong state yields `ERR_INVALID_CLAIM_STATE` — a triage decision requires `TRIAGE`; dispatching requires `APPROVED`, or `DISPATCHED` when the request names an open dispatch of the same claim to supersede; opening an appeal requires `DENIED`; an appeal decision requires `APPEAL_OPEN`."

        Design: Corner/state_machines/triaging_an_already_approved_claim_a_second_time_is_refused
        """
        world = fixtures.active_coverage(api)
        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="ROUTINE",
            incident_description="Slow leak weeping at the curb box.",
        )
        assert_fields(claim, {"status": "TRIAGE", "version": 1})

        first = fixtures.approve_claim(
            api, claim["id"], coverage_note="Covered curb-stop segment."
        )
        assert_fields(
            first,
            {
                "status": "APPROVED",
                "version": 2,
                "triage_decided_by_user_id": CLAIMS_ADJUSTER_USER_ID,
            },
        )
        assert_instant(
            first["triage_decided_at"], CLOCK_COVERAGE_ACTIVE, "triage_decided_at"
        )

        response = api.triage_claim(
            claim["id"],
            factories.triage_approval_payload(
                coverage_note="Second look reaches the same conclusion."
            ),
            CLAIMS_ADJUSTER,
        )
        assert_refused(response, ERR_INVALID_CLAIM_STATE)

        after = fixtures.refresh_claim(api, claim["id"])
        assert_fields(
            after,
            {
                "status": "APPROVED",
                "version": 2,
                "triage_decided_by_user_id": CLAIMS_ADJUSTER_USER_ID,
            },
        )
        assert_instant(
            after["triage_decided_at"], CLOCK_COVERAGE_ACTIVE, "triage_decided_at"
        )
        assert_nulls(after, ["denial_reason", "denied_at"])


class TestSweepAndRemedyTransitions:
    """The overnight sweep of PRD §3.9 and the reinstatement remedy of PRD §3.8."""

    def test_sla_breach_sweep_marks_the_dispatch_and_bumps_only_the_breach_counter(self, api):
        """One breach on a threshold of two breaches the dispatch without probating anyone.

        PRD: "Every dispatch still `ASSIGNED` whose `sla_deadline_at` is on or before the logical clock moves `ASSIGNED → SLA_BREACHED`, and its contractor's `sla_breach_count` is incremented."

        Design: Corner/state_machines/sla_breach_sweep_marks_the_dispatch_and_bumps_only_the_breach_counter
        """
        world = fixtures.active_coverage(api)
        # "coverage_effective_at" had arrived, so the setup run activated it.
        assert world["nightly_report"]["activated_enrollment_ids"] == [world["enrollment_id"]]
        contractor = fixtures.create_contractor(api, **ALDER_PLUMBING)

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            urgency="EMERGENCY",
            incident_description="Curb stop sheared; water flooding the sidewalk.",
        )
        approved = fixtures.approve_claim(
            api, claim["id"], coverage_note="Emergency curb-stop failure."
        )
        dispatch = fixtures.dispatch_claim_to(
            api,
            claim["id"],
            approved["version"],
            contractor["id"],
            window_start=DISPATCH_WINDOW_START,
        )
        # "An `EMERGENCY` claim reported at `2026-09-10T08:00:00.000Z` carries a
        # deadline of `2026-09-10T12:00:00.000Z`".
        assert_instant(dispatch["sla_deadline_at"], "2026-09-10T12:00:00.000Z", "sla_deadline_at")
        # "the same water-service job estimated at 6 hours times 18000 cents plus
        # 120000, or 228000".
        assert_cents(dispatch["estimated_benefit_cents"], "estimated_benefit_cents")
        assert_fields(
            dispatch, {"status": "ASSIGNED", "selection_mode": "MANUAL", "estimated_benefit_cents": 228000}
        )
        # "`selection_score` is recorded on manual dispatches too" — 89.9 under
        # the emergency weights for this contractor.
        assert dispatch["selection_score"] == pytest.approx(89.90, abs=0.01), (
            f"selection_score expected 89.90, got {dispatch['selection_score']!r}"
        )

        # The sweep is inclusive at the deadline itself.
        fixtures.set_clock(api, "2026-09-10T12:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_report_shape(report)
        assert report["sla_breached_dispatch_ids"] == [dispatch["id"]], (
            f"sla_breached_dispatch_ids expected [{dispatch['id']}], "
            f"got {report['sla_breached_dispatch_ids']!r}"
        )
        # One breach is short of the probation threshold of two, so nothing else
        # fired anywhere in the run.
        assert_nightly_lists_empty(report, except_for=("sla_breached_dispatch_ids",))

        breached = fixtures.refresh_dispatch(api, dispatch["id"])
        assert_fields(breached, {"status": "SLA_BREACHED", "version": 2})
        # A breach is not a cancellation.
        assert_nulls(breached, ["cancellation_reason"])

        # "Every contractor whose `sla_breach_count` has reached 2 moves
        # `ACTIVE → PROBATION`" — one breach leaves it active.
        contractor_after = fixtures.refresh_contractor(api, contractor["id"])
        assert_fields(
            contractor_after,
            {"sla_breach_count": 1, "status": "ACTIVE", "open_dispatch_count": 0},
        )

        # "released the moment the dispatch leaves the open set" — SLA_BREACHED is
        # outside `ASSIGNED`, `ACCEPTED`, `ON_SITE`.
        enrollment_after = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(enrollment_after, {"annual_benefit_reserved_cents": 0})

        # Phase 1 touches the dispatch and the contractor, never the claim.
        claim_after = fixtures.refresh_claim(api, claim["id"])
        assert_fields(claim_after, {"status": "DISPATCHED", "version": 3})

    def test_reinstatement_remedy_reverses_the_cancellation_payout(self, api):
        """The clawback equals what was actually paid out, and the retained fee is not reversed.

        PRD: "`REINSTATEMENT` is the fullest reversal: the coverage dimension returns `CANCELLED → ACTIVE`, the billing dimension returns to `CURRENT`, a positive refund-clawback cash row is appended for the absolute value of whatever was paid out at cancellation — `refund_cents` or `credit_cents`, whichever applied — `cancellation_effective_date`, `cancellation_reason`, `refund_cents`, `credit_cents` and `cancellation_fee_cents` are all cleared to null, and `term_end` is restored to the value it held before cancellation, namely twelve calendar months after `term_start` plus a further twelve months for each completed renewal."

        Design: Corner/state_machines/reinstatement_remedy_reverses_the_cancellation_payout
        """
        # prepaid_amount_cents is deliberately omitted so the DIRECT_BILL default
        # of twelve times the pinned monthly price is the figure under test.
        world = fixtures.enrolled_premises(api, prepaid_amount_cents=None)
        enrollment = world["enrollment"]
        assert_fields(
            enrollment,
            {
                "prepaid_amount_cents": 29988,
                "term_start": ENROLLMENT_TERM_START,
                "term_end": ENROLLMENT_TERM_END,
            },
        )
        world = fixtures.activate_coverage(api, world)
        assert_fields(world["enrollment"], {"coverage_status": "ACTIVE"})

        fixtures.set_clock(api, "2026-11-18T00:00:00.000Z")
        cancelled = fixtures.cancel_enrollment(
            api, world["enrollment_id"], "2026-11-18", reason="CUSTOMER_REQUEST"
        )
        # "8591 cents earned ... the fee is 2500 ... `refund_cents` is 29988 less
        # 8591 less 2500, or 18897."
        assert_fields(
            cancelled,
            {
                "coverage_status": "CANCELLED",
                "billing_status": "REFUND_ISSUED",
                "cancellation_effective_date": "2026-11-18",
                "cancellation_reason": "CUSTOMER_REQUEST",
                "refund_cents": 18897,
                "cancellation_fee_cents": 2500,
                # "`credit_cents` is 0" under DIRECT_BILL.
                "credit_cents": 0,
            },
        )

        fixtures.set_clock(api, "2026-11-20T00:00:00.000Z")
        complaint = fixtures.create_complaint(
            api,
            world["partner_id"],
            allegation="Coverage was cancelled without the homeowner's consent.",
            enrollment_id=world["enrollment_id"],
        )
        # "The base window is 10 days for `PUC`" and no denied claim is cited.
        assert_instant(complaint["response_due_at"], "2026-11-30T00:00:00.000Z", "response_due_at")
        assert_fields(complaint, {"status": "OPEN", "version": 1})
        # "when an `enrollment_id` is cited, that policy's address has
        # `regulator_hold` set to true".
        held_premises = assert_object_envelope(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert_fields(held_premises, {"regulator_hold": True})

        fixtures.set_clock(api, "2026-11-25T00:00:00.000Z")
        responded = fixtures.respond_to_complaint(
            api,
            complaint["id"],
            "SUBSTANTIATED",
            "REINSTATEMENT",
            complaint["version"],
            response_summary="Cancellation was made in error; coverage reinstated.",
        )
        assert_fields(
            responded,
            {"status": "CLOSED_SUBSTANTIATED", "version": 2, "remedy_type": "REINSTATEMENT"},
        )
        assert_instant(responded["responded_at"], "2026-11-25T00:00:00.000Z", "responded_at")

        reinstated = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(
            reinstated,
            {
                "coverage_status": "ACTIVE",
                "billing_status": "CURRENT",
                # Restored, not extended: no renewal has completed.
                "term_end": ENROLLMENT_TERM_END,
                # 2500 retained fee plus the 18897 clawed back.
                "premium_collected_cents": 21397,
                "premium_refunded_cents": 18897,
            },
        )
        assert_nulls(
            reinstated,
            [
                "cancellation_effective_date",
                "cancellation_reason",
                "refund_cents",
                "credit_cents",
                "cancellation_fee_cents",
            ],
        )

        rows, _meta = assert_list_envelope(
            api.list_ledger_entries(
                PLATFORM_ADMIN,
                params={"enrollment_id": world["enrollment_id"], "ledger_kind": "CASH"},
            ),
            expected_total=3,
        )
        assert_created_at_ascending(rows)
        assert [row["entry_type"] for row in rows] == [
            "PRORATION_REFUND",
            "CANCELLATION_FEE",
            "REFUND_CLAWBACK",
        ], f"cash ledger entry types out of order: {[row['entry_type'] for row in rows]!r}"
        # "The net cash position must land back exactly where it was before the
        # cancellation" — the retained fee is deliberately not reversed.
        assert_ledger_amounts(rows, [-18897, 2500, 18897])

        # "Every response also re-derives the address's `regulator_hold` — false
        # only when no other complaint on that address is still open — and its
        # `suppression_reason`".
        premises_after = assert_object_envelope(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert_fields(
            premises_after,
            {"regulator_hold": False, "suppression_reason": "NONE", "suppressed": False},
        )
