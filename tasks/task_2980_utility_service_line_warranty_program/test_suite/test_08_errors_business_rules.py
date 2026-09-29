"""Refusal-precedence, money and date-arithmetic corners of the error catalogue.

Each test below proves one ordered refusal ladder or one arithmetic boundary end
to end: the shallower rule is made to fire first, the payload is then repaired
one field at a time so the next rule down is exposed, and the finally-accepted
request is settled and reconciled against the ledger. Every identifier and HTTP
status pairing asserted here is the one PRD §5 catalogues, and every test that
reads a date window pins the logical clock inside that window before triggering.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_CANCELLATION_BLOCKED_APPEAL,
    ERR_CONTRACTOR_CAPACITY_EXCEEDED,
    ERR_DENIAL_REASON_UNSUPPORTED,
    ERR_INSUFFICIENT_RENEWAL_NOTICE,
    ERR_INVALID_RECURRENCE_LINK,
    ERR_NO_ELIGIBLE_CONTRACTOR,
    ERR_OWNERSHIP_NOT_ELIGIBLE,
    ERR_PERMIT_REQUIRED,
    ERR_PER_OCCURRENCE_CAP_EXHAUSTED,
    ERR_PRE_EXISTING_CONDITION,
    ERR_RATE_FILING_REQUIRED,
    ERR_REFUND_NOT_AVAILABLE,
    ERR_REMEDY_NOT_PERMITTED,
    ERR_REMEDY_TARGET_MISSING,
    ERR_RESTORATION_SCOPE_NOT_COVERED,
    ERR_REVERSAL_EXCEEDS_BENEFIT,
)
from test_helpers.assertions import (
    assert_instant,
    assert_list_envelope,
    assert_refused,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
    make_network_contractor_headers,
    make_policyholder_headers,
)

# The visit window the worked dispatch examples use, one hour after the clock
# reaches the day coverage is active on.
WINDOW_FIRST = "2026-09-10T09:00:00.000Z"
WINDOW_SECOND = "2026-09-11T09:00:00.000Z"


def _cash_rows_of_type(api, enrollment_id, entry_type):
    """Every CASH ledger row of one entry type for one policy, in append order."""
    rows, _meta = assert_list_envelope(
        api.list_ledger_entries(
            PLATFORM_ADMIN,
            params={"enrollment_id": enrollment_id, "ledger_kind": "CASH"},
        )
    )
    return [row for row in rows if row["entry_type"] == entry_type]


class TestDispatchEligibilityGates:
    """The manual override enforces the candidate filter field by field."""

    def test_manual_permit_and_capacity_gates_then_the_pool_empties(self, api):
        """A named contractor fails the permit rule, then the capacity rule, and
        the automatic pass over the same two contractors finds nobody.

        PRD: "When it was, `selection_mode` is `MANUAL`, the scoring pass is skipped entirely, and the named contractor is used — but every eligibility condition is still enforced individually, so that a bad manual choice fails with a precise reason rather than a generic one: a contractor whose `status` is not `ACTIVE` is refused with `ERR_CONTRACTOR_NOT_ACTIVE`, an expired licence with `ERR_CONTRACTOR_LICENSE_EXPIRED`, a missing certification with `ERR_CONTRACTOR_NOT_CERTIFIED`, a full book with `ERR_CONTRACTOR_CAPACITY_EXCEEDED`, and a contractor who cannot pull permits on a product whose `permit_covered` is true with `ERR_PERMIT_REQUIRED`."

        Design: Corner/errors/err_dispatch_eligibility_gates_permit_capacity_and_empty_pool
        """
        world = fixtures.active_coverage(api)

        # The only two contractors on file: one that may not pull permits, one
        # whose whole book is a single slot.
        nopermit = fixtures.create_contractor(
            api,
            name="No Permit Plumbing",
            license_number="OR-PL-8100",
            license_expires_on="2027-06-30",
            hourly_rate_cents=6000,
            sla_compliance_pct=76,
            max_open_dispatches=4,
            permit_pull_authorized=False,
        )
        solo = fixtures.create_contractor(
            api,
            name="Solo Trenchless",
            license_number="OR-PL-4471",
            license_expires_on="2027-06-30",
            max_open_dispatches=1,
        )

        claim_one = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="First failure at the curb stop.",
        )
        one_v2 = fixtures.approve_claim(api, claim_one["id"])["version"]
        claim_two = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="METER_TO_HOME",
            incident_description="Unrelated failure between meter and home.",
        )
        two_v2 = fixtures.approve_claim(api, claim_two["id"])["version"]

        # The product is permit_covered, so a contractor that cannot pull
        # permits is refused by name.
        refused_permit = api.create_dispatch(
            claim_one["id"],
            factories.manual_dispatch_payload(one_v2, WINDOW_FIRST, nopermit["id"]),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused_permit, ERR_PERMIT_REQUIRED, 422)

        # The permit-authorised contractor is admitted, and still carries the
        # score it would have received had the scoring pass run:
        # 0.45*92 + 0.35*100 + 0.20*10 under the standard urgency weights.
        assigned = validate_success(
            api.create_dispatch(
                claim_one["id"],
                factories.manual_dispatch_payload(one_v2, WINDOW_FIRST, solo["id"]),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert assigned["selection_mode"] == "MANUAL"
        assert assigned["selection_score"] == pytest.approx(78.40, abs=0.01)
        assert assigned["estimated_benefit_cents"] == 228000

        # That single slot is now taken, so the same contractor is over capacity.
        refused_capacity = api.create_dispatch(
            claim_two["id"],
            factories.manual_dispatch_payload(two_v2, WINDOW_SECOND, solo["id"]),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused_capacity, ERR_CONTRACTOR_CAPACITY_EXCEEDED, 422)

        # With the permit filter dropping one candidate and the capacity filter
        # the other, automatic selection refuses rather than relaxing a rule.
        refused_pool = api.create_dispatch(
            claim_two["id"],
            factories.dispatch_payload(two_v2, WINDOW_SECOND),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused_pool, ERR_NO_ELIGIBLE_CONTRACTOR, 422)

        assert fixtures.refresh_contractor(api, solo["id"])["open_dispatch_count"] == 1
        assert fixtures.refresh_contractor(api, nopermit["id"])["open_dispatch_count"] == 0

        rows, _meta = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"claim_id": claim_two["id"]}),
            expected_total=0,
        )
        assert rows == []
        assert fixtures.refresh_claim(api, claim_two["id"])["status"] == "APPROVED"


class TestTriageAssessmentGates:
    """The derived intake verdict decides which triage payloads are legal."""

    def test_denial_reason_ownership_and_pre_existing_gates_on_triage(self, api):
        """The identical DENY reason is refused on one assessment and correct on
        another, and APPROVE names a different error for each assessment.

        PRD: "An adjuster cannot approve a claim the system found uncovered, and the specific refusal names the specific defect: a claim assessed `COVERAGE_INACTIVE` is refused with `ERR_ENROLLMENT_NOT_ACTIVE`, one assessed `WAITING_PERIOD` with `ERR_WAITING_PERIOD_NOT_ELAPSED`, one assessed `OWNERSHIP_INELIGIBLE` with `ERR_OWNERSHIP_NOT_ELIGIBLE`, one assessed `PRE_EXISTING` with `ERR_PRE_EXISTING_CONDITION`, and one assessed `CAP_EXHAUSTED` with `ERR_ANNUAL_CAP_EXHAUSTED`."

        Design: Corner/errors/err_triage_gates_denial_reason_ownership_boundary_and_pre_existing
        """
        world = fixtures.active_partner_with_product(api)
        premises_a = fixtures.create_premises(
            api, world["partner_id"], street_address="18 Alder Court"
        )
        # Premises B was flagged with a defect before it was ever sold a policy.
        premises_b = fixtures.create_premises(
            api,
            world["partner_id"],
            street_address="22 Birch Lane",
            known_defect_reported_at="2026-07-01T00:00:00.000Z",
        )

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment_a = fixtures.create_enrollment(
            api, premises_a["id"], world["product_id"], premises_a["version"]
        )
        enrollment_b = fixtures.create_enrollment(
            api, premises_b["id"], world["product_id"], premises_b["version"]
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        # INSIDE_HOME is not one of the locations a CURB_STOP boundary covers.
        claim_a = fixtures.file_claim(
            api,
            enrollment_a["id"],
            defect_location="INSIDE_HOME",
            incident_description="Leak under the kitchen floor.",
        )
        assert claim_a["eligibility_assessment"] == "OWNERSHIP_INELIGIBLE"

        # A covered location, but the defect predates the enrollment date.
        claim_b = fixtures.file_claim(
            api,
            enrollment_b["id"],
            incident_description="The same seepage that was reported in July.",
        )
        assert claim_b["eligibility_assessment"] == "PRE_EXISTING"

        contradictory = api.triage_claim(
            claim_a["id"],
            factories.triage_denial_payload(
                "PRE_EXISTING", coverage_note="Wrong reason for this assessment."
            ),
            CLAIMS_ADJUSTER,
        )
        assert_refused(contradictory, ERR_DENIAL_REASON_UNSUPPORTED, 422)

        approve_a = api.triage_claim(
            claim_a["id"],
            factories.triage_approval_payload(
                coverage_note="Approving a defect inside the home."
            ),
            CLAIMS_ADJUSTER,
        )
        assert_refused(approve_a, ERR_OWNERSHIP_NOT_ELIGIBLE, 422)

        denied_a = fixtures.deny_claim(
            api,
            claim_a["id"],
            "OWNERSHIP_INELIGIBLE",
            coverage_note="Inside-home plumbing is outside the curb-stop boundary.",
        )
        assert denied_a["status"] == "DENIED"
        assert denied_a["denial_reason"] == "OWNERSHIP_INELIGIBLE"
        assert denied_a["version"] == 2

        approve_b = api.triage_claim(
            claim_b["id"],
            factories.triage_approval_payload(
                coverage_note="Approving a known pre-existing defect."
            ),
            CLAIMS_ADJUSTER,
        )
        assert_refused(approve_b, ERR_PRE_EXISTING_CONDITION, 422)

        # The very reason that was refused on claim A is the correct one here.
        denied_b = fixtures.deny_claim(
            api,
            claim_b["id"],
            "PRE_EXISTING",
            coverage_note="Defect was on file before the enrollment date.",
        )
        assert denied_b["status"] == "DENIED"
        assert denied_b["denial_reason"] == "PRE_EXISTING"
        assert denied_b["version"] == 2


class TestRecurrenceLinkValidation:
    """A recurrence link is validated on the policy, the line and the window."""

    def test_link_is_refused_across_policies_and_past_the_thirty_day_window(self, api):
        """A link to another policy's claim is refused, a link exactly 30 days
        old is accepted, one day later is refused, and the root is transitive.

        PRD: "A supplied link is only valid when the referenced claim belongs to the same `enrollment_id`, carries the same `line_type`, and was reported no more than 30 days before this claim's `reported_at`; otherwise the filing is refused with `ERR_INVALID_RECURRENCE_LINK`."

        Design: Corner/errors/err_invalid_recurrence_link_across_enrollment_and_window_arms
        """
        world = fixtures.active_partner_with_product(api)
        premises_a = fixtures.create_premises(
            api, world["partner_id"], street_address="18 Alder Court"
        )
        premises_b = fixtures.create_premises(
            api, world["partner_id"], street_address="22 Birch Lane"
        )

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment_a = fixtures.create_enrollment(
            api, premises_a["id"], world["product_id"], premises_a["version"]
        )
        enrollment_b = fixtures.create_enrollment(
            api, premises_b["id"], world["product_id"], premises_b["version"]
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        # The root of its own group, reported at the instant the clock holds.
        root = fixtures.file_claim(
            api,
            enrollment_a["id"],
            incident_description="Root failure at the curb stop.",
        )
        assert root["occurrence_root_claim_id"] == root["id"]
        assert_instant(root["reported_at"], "2026-09-10T08:00:00.000Z", "reported_at")

        # Arm 1: the referenced claim belongs to a different policy.
        wrong_policy = api.create_claim(
            factories.claim_payload(
                enrollment_b["id"],
                incident_description="Different house, linked to the wrong root.",
                recurrence_of_claim_id=root["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(wrong_policy, ERR_INVALID_RECURRENCE_LINK, 422)

        # Arm 2: exactly 30 days later is still "no more than 30 days before".
        fixtures.set_clock(api, "2026-10-10T08:00:00.000Z")
        linked = validate_success(
            api.create_claim(
                factories.claim_payload(
                    enrollment_a["id"],
                    incident_description="Same failure, exactly at the window edge.",
                    recurrence_of_claim_id=root["id"],
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert linked["recurrence_of_claim_id"] == root["id"]
        assert linked["occurrence_root_claim_id"] == root["id"]
        assert linked["eligibility_assessment"] == "ELIGIBLE"

        # Arm 3: one day past the edge, the same link is no longer valid.
        fixtures.set_clock(api, "2026-10-11T08:00:00.000Z")
        too_old = api.create_claim(
            factories.claim_payload(
                enrollment_a["id"],
                incident_description="One day too late to join the group.",
                recurrence_of_claim_id=root["id"],
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(too_old, ERR_INVALID_RECURRENCE_LINK, 422)

        # Arm 4: linking to the middle claim resolves to the transitive root,
        # not to the claim named in the link.
        grandchild = validate_success(
            api.create_claim(
                factories.claim_payload(
                    enrollment_a["id"],
                    incident_description="Third failure, linked to the second.",
                    recurrence_of_claim_id=linked["id"],
                ),
                CUSTOMER_SERVICE_REP,
            ),
            201,
        )
        assert grandchild["recurrence_of_claim_id"] == linked["id"]
        assert grandchild["occurrence_root_claim_id"] == root["id"]

        # None of the refused filings created anything on policy B.
        rows, _meta = assert_list_envelope(
            api.list_claims(
                CUSTOMER_SERVICE_REP, params={"enrollment_id": enrollment_b["id"]}
            ),
            expected_total=0,
        )
        assert rows == []


class TestPerOccurrenceCapScope:
    """The per-occurrence pool is drawn down per group, never per policy."""

    def test_exhausted_pool_blocks_the_group_but_not_a_fresh_occurrence(self, api):
        """A recurrence of a claim whose group has spent its allowance cannot be
        dispatched, while an unlinked claim on the same policy still can.

        PRD: "Before any of this, the occurrence pool is checked: a claim whose occurrence group has already consumed its entire per-occurrence allowance cannot be worked at all and is refused with `ERR_PER_OCCURRENCE_CAP_EXHAUSTED`."

        Design: Corner/errors/err_per_occurrence_cap_exhausted_only_inside_the_occurrence_group
        """
        world = fixtures.partner_product_premises(
            api,
            product_overrides={
                "name": "Water Line Basic",
                "per_occurrence_cap_cents": 100000,
                "annual_cap_cents": 5000000,
            },
        )
        world = fixtures.active_coverage(api, world)
        contractor = fixtures.create_contractor(
            api, name="Cascade Trenchless", license_expires_on="2027-06-30"
        )

        root = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Root failure at the curb stop.",
        )
        root_v2 = fixtures.approve_claim(api, root["id"])["version"]

        # The per-occurrence allowance, not the annual one, caps the estimate.
        first = fixtures.dispatch_claim_to(
            api, root["id"], root_v2, contractor["id"], WINDOW_FIRST
        )
        assert first["estimated_benefit_cents"] == 100000

        fixtures.accept_dispatch(api, first["id"], contractor["id"])
        fixtures.arrive_dispatch(api, first["id"], contractor["id"])
        settled = fixtures.complete_dispatch(
            api,
            first["id"],
            contractor["id"],
            260000,
            175000,
            permit_number="PRM-9001",
            permit_fee_cents=42000,
            restoration_cents=90000,
            restoration_scope="BASIC_BACKFILL",
        )
        # 260000 + 175000 + 42000 + 90000, of which only the pool is payable.
        assert settled["invoice_total_cents"] == 567000
        assert settled["benefit_paid_cents"] == 100000
        assert settled["customer_responsibility_cents"] == 467000

        # A linked recurrence joins the drained group.
        fixtures.set_clock(api, "2026-09-20T08:00:00.000Z")
        recurrence = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="The same failure has reopened.",
            recurrence_of_claim_id=root["id"],
        )
        assert recurrence["occurrence_root_claim_id"] == root["id"]
        assert recurrence["eligibility_assessment"] == "ELIGIBLE"
        recurrence_v2 = fixtures.approve_claim(api, recurrence["id"])["version"]

        # An unlinked claim opens a brand-new group with its own fresh pool.
        fresh = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="METER_TO_HOME",
            incident_description="A separate, unlinked failure past the meter.",
        )
        assert fresh["occurrence_root_claim_id"] == fresh["id"]
        fresh_v2 = fixtures.approve_claim(api, fresh["id"])["version"]

        refused = api.create_dispatch(
            recurrence["id"],
            factories.manual_dispatch_payload(
                recurrence_v2, "2026-09-20T09:00:00.000Z", contractor["id"]
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(refused, ERR_PER_OCCURRENCE_CAP_EXHAUSTED, 422)

        allowed = fixtures.dispatch_claim_to(
            api, fresh["id"], fresh_v2, contractor["id"], "2026-09-21T09:00:00.000Z"
        )
        assert allowed["estimated_benefit_cents"] == 100000

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_used_cents"] == 100000
        assert enrollment["cap_status"] == "WITHIN_CAP"

        rows, _meta = assert_list_envelope(
            api.list_ledger_entries(
                PLATFORM_ADMIN,
                params={"claim_id": root["id"], "ledger_kind": "BENEFIT"},
            ),
            expected_total=1,
        )
        assert rows[0]["entry_type"] == "BENEFIT_CHARGE"
        assert rows[0]["amount_cents"] == 100000


class TestCompletionInvoiceGates:
    """A completion is checked for safety evidence before coverage scope."""

    def test_permit_number_gate_precedes_the_restoration_scope_gate(self, api):
        """One payload violates both rules and reports the permit one; supplying
        only the permit number exposes the restoration one; both repaired settles.

        PRD: "A `permit_fee_cents` greater than zero with no `permit_number` supplied is refused with `ERR_PERMIT_REQUIRED`: the programme will not reimburse a permit fee that cannot be evidenced."

        Design: Corner/errors/err_permit_number_requirement_outranks_the_restoration_scope_check
        """
        world = fixtures.active_coverage(api)
        contractor = fixtures.create_contractor(
            api, name="Cascade Trenchless", license_expires_on="2027-06-30"
        )

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Collapsed service line at the curb.",
        )
        claim_v2 = fixtures.approve_claim(api, claim["id"])["version"]
        dispatch = fixtures.dispatch_claim_to(
            api, claim["id"], claim_v2, contractor["id"], WINDOW_FIRST
        )
        assert dispatch["estimated_benefit_cents"] == 228000

        fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
        on_site = fixtures.arrive_dispatch(api, dispatch["id"], contractor["id"])
        assert on_site["status"] == "ON_SITE"
        assert on_site["version"] == 3

        crew = make_network_contractor_headers(contractor["id"])

        # Both rules are violated at once: no permit number against a positive
        # permit fee, and a restoration scope richer than the product covers.
        both_wrong = api.create_dispatch_event(
            dispatch["id"],
            factories.complete_event_payload(
                260000,
                175000,
                permit_fee_cents=42000,
                restoration_cents=90000,
                restoration_scope="FULL_HARDSCAPE",
            ),
            crew,
        )
        assert_refused(both_wrong, ERR_PERMIT_REQUIRED, 422)

        # Repairing only the permit evidence exposes the scope rule beneath it.
        scope_wrong = api.create_dispatch_event(
            dispatch["id"],
            factories.complete_event_payload(
                260000,
                175000,
                permit_number="PRM-9001",
                permit_fee_cents=42000,
                restoration_cents=90000,
                restoration_scope="FULL_HARDSCAPE",
            ),
            crew,
        )
        assert_refused(scope_wrong, ERR_RESTORATION_SCOPE_NOT_COVERED, 422)

        # Neither refusal advanced the dispatch.
        still_on_site = fixtures.refresh_dispatch(api, dispatch["id"])
        assert still_on_site["status"] == "ON_SITE"
        assert still_on_site["version"] == 3

        # 90000 of restoration trimmed to the 50000 BASIC_BACKFILL allowance,
        # then labour, materials, permit and restoration filled from the pool.
        settled = fixtures.complete_dispatch(
            api,
            dispatch["id"],
            contractor["id"],
            260000,
            175000,
            permit_number="PRM-9001",
            permit_fee_cents=42000,
            restoration_cents=90000,
            restoration_scope="BASIC_BACKFILL",
        )
        assert settled["status"] == "COMPLETED"
        assert settled["invoice_total_cents"] == 567000
        assert settled["benefit_paid_cents"] == 527000
        assert settled["customer_responsibility_cents"] == 40000
        assert settled["version"] == 4

        paid = fixtures.refresh_claim(api, claim["id"])
        assert paid["status"] == "PAID"
        assert paid["benefit_paid_cents"] == 527000
        assert fixtures.refresh_contractor(api, contractor["id"])["open_dispatch_count"] == 0

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_used_cents"] == 527000
        assert enrollment["annual_benefit_reserved_cents"] == 0
        assert enrollment["cap_status"] == "WITHIN_CAP"


class TestAppealWindowAndRetentionHold:
    """The appeal window edge, and what an open appeal blocks while it is open."""

    def test_appeal_at_the_edge_holds_the_policy_and_one_hour_later_is_expired(self, api):
        """An appeal at exactly denied_at plus 30 days is admitted and blocks
        cancellation; one hour past the edge is refused on the sibling claim.

        PRD: "And the appeal must arrive within 30 days of `denied_at`; once the logical clock passes `denied_at` plus 30 days the request is refused with `ERR_APPEAL_WINDOW_EXPIRED`, the boundary being inclusive on the appellant's side — an appeal at exactly the 30-day instant is still accepted."

        Design: Corner/errors/err_appeal_window_boundary_and_the_retention_hold_on_cancellation
        """
        world = fixtures.active_coverage(api)

        # Two ELIGIBLE claims denied at the same instant; NOT_COVERED_SEGMENT is
        # the only reason the denial-reason rule admits on an ELIGIBLE claim.
        claim_a = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Weeping joint at the curb stop.",
        )
        denied_a = fixtures.deny_claim(
            api,
            claim_a["id"],
            "NOT_COVERED_SEGMENT",
            coverage_note="The failed fitting is outside the covered segment scope.",
        )
        assert_instant(denied_a["denied_at"], "2026-09-10T08:00:00.000Z", "denied_at")

        claim_b = fixtures.file_claim(
            api,
            world["enrollment_id"],
            defect_location="METER_TO_HOME",
            incident_description="Second weeping joint after the meter.",
        )
        denied_b = fixtures.deny_claim(
            api,
            claim_b["id"],
            "NOT_COVERED_SEGMENT",
            coverage_note="Also outside the covered segment scope.",
        )
        assert_instant(denied_b["denied_at"], "2026-09-10T08:00:00.000Z", "denied_at")
        assert denied_b["appeal_count"] == 0

        # Exactly denied_at + 30 days: the boundary is the appellant's.
        fixtures.set_clock(api, "2026-10-10T08:00:00.000Z")
        appealed = validate_success(
            api.create_appeal(
                claim_a["id"],
                factories.appeal_payload(
                    appeal_reason="The fitting is on the covered side of the curb stop."
                ),
                make_policyholder_headers(world["premises_id"]),
            ),
            200,
        )
        assert appealed["status"] == "APPEAL_OPEN"
        assert appealed["appeal_count"] == 1
        assert appealed["appeal_source"] == "POLICYHOLDER"

        assert fixtures.refresh_enrollment(api, world["enrollment_id"])["retention_hold"] is True
        premises = validate_success(api.get_premises(world["premises_id"], MARKETING_OPS))
        assert premises["suppression_reason"] == "OPEN_APPEAL"

        blocked = api.cancel_enrollment(
            world["enrollment_id"],
            factories.cancellation_payload("2026-10-11"),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(blocked, ERR_CANCELLATION_BLOCKED_APPEAL, 422)

        upheld = fixtures.decide_appeal(
            api,
            claim_a["id"],
            "UPHOLD",
            rationale="The fitting sits on the utility side of the curb stop.",
        )
        assert upheld["status"] == "APPEAL_UPHELD_DENIAL"
        assert fixtures.refresh_enrollment(api, world["enrollment_id"])["retention_hold"] is False

        # One hour past the edge on the sibling claim, which is still DENIED
        # with appeal_count 0, so neither the state gate nor the appeal limit
        # can be responsible for the refusal.
        fixtures.set_clock(api, "2026-10-10T09:00:00.000Z")
        late = api.create_appeal(
            claim_b["id"],
            factories.appeal_payload(appeal_reason="One hour too late."),
            make_policyholder_headers(world["premises_id"]),
        )
        assert_refused(late, ERR_APPEAL_WINDOW_EXPIRED, 422)

        # With the hold cleared the cancellation settles: 27 of August's 31 days
        # gives 2177, all of September 2499, 10 of October's 31 gives 806.
        fixtures.set_clock(api, "2026-10-11T00:00:00.000Z")
        cancelled = validate_success(
            api.cancel_enrollment(
                world["enrollment_id"],
                factories.cancellation_payload("2026-10-11"),
                CUSTOMER_SERVICE_REP,
            ),
            200,
        )
        assert cancelled["coverage_status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 2500
        assert cancelled["refund_cents"] == 22006
        assert cancelled["credit_cents"] == 0

        refunds = _cash_rows_of_type(api, world["enrollment_id"], "PRORATION_REFUND")
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == -22006


class TestRenewalNoticeGates:
    """The lead-time tier is evaluated before the rate-filing gate, always."""

    def test_notice_tier_is_checked_before_the_rate_filing_gate(self, api):
        """The same 40.02 percent increase reports the filing error with 60 days'
        lead and the tier error with 30, and a 4.00 percent change passes both.

        PRD: "A second, independent gate follows the tier check, and the order between them is fixed: the tier is evaluated first, then the filing gate."

        Design: Corner/errors/err_renewal_notice_tier_is_evaluated_before_the_rate_filing_gate
        """
        world = fixtures.partner_product_premises(
            api, partner_overrides={"rate_filing_required": True}
        )
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"]
        )
        assert enrollment["monthly_price_cents"] == 2499
        assert enrollment["term_start"] == "2026-08-05"
        assert enrollment["term_end"] == "2027-08-05"
        assert enrollment["renewal_notice_status"] == "NONE"

        fixtures.set_clock(api, "2026-09-10T00:00:00.000Z")
        fixtures.run_nightly(api)
        active = fixtures.refresh_enrollment(api, enrollment["id"])
        assert active["coverage_status"] == "ACTIVE"
        assert active["version"] == 2
        guard = active["version"]

        # 100 * 1000 / 2499 rounds to 40.02 percent, which demands 60 days of
        # lead time. 2027-06-06 is exactly 60 days before the renewal date, so
        # the tier is satisfied and only the filing gate is left to fire.
        fixtures.set_clock(api, "2027-06-06T00:00:00.000Z")
        filing = api.create_renewal_notice(
            enrollment["id"],
            factories.renewal_notice_payload(3499, "2027-08-05", guard),
            BILLING_OPS,
        )
        assert_refused(filing, ERR_RATE_FILING_REQUIRED, 422)

        # The identical increase with only 30 days of lead fails the tier first,
        # so the filing gate is never reached and the errors are not swapped.
        fixtures.set_clock(api, "2027-07-06T00:00:00.000Z")
        short_notice = api.create_renewal_notice(
            enrollment["id"],
            factories.renewal_notice_payload(3499, "2027-08-05", guard),
            BILLING_OPS,
        )
        assert_refused(short_notice, ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)

        # 100 * 100 / 2499 rounds to 4.00 percent: the 30-day tier, met exactly,
        # and far under the filing threshold. The refusals left the version at 2.
        sent = validate_success(
            api.create_renewal_notice(
                enrollment["id"],
                factories.renewal_notice_payload(2599, "2027-08-05", guard),
                BILLING_OPS,
            ),
            200,
        )
        assert sent["renewal_notice_status"] == "SENT"
        assert sent["renewal_price_cents"] == 2599
        assert sent["renewal_effective_date"] == "2027-08-05"
        assert_instant(
            sent["renewal_notice_sent_at"],
            "2027-07-06T00:00:00.000Z",
            "renewal_notice_sent_at",
        )
        # A notice announces a price; it does not put it in force.
        assert sent["monthly_price_cents"] == 2499
        assert sent["version"] == 3


class TestRefundAvailability:
    """A DIRECT_BILL settlement that would owe money refuses instead."""

    def test_refund_is_refused_when_earned_premium_and_fee_exceed_the_prepayment(self, api):
        """Two policies cancelled on identical dates with identical earned
        premium diverge purely on how much was prepaid.

        PRD: "If that arithmetic comes out negative — earned premium plus fee exceeding what was prepaid — nothing is refunded and the request is refused with `ERR_REFUND_NOT_AVAILABLE`."

        Design: Corner/errors/err_refund_not_available_when_earned_premium_exceeds_the_prepayment
        """
        world = fixtures.active_partner_with_product(api)
        premises_a = fixtures.create_premises(
            api, world["partner_id"], street_address="18 Alder Court"
        )
        premises_b = fixtures.create_premises(
            api, world["partner_id"], street_address="22 Birch Lane"
        )

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment_a = fixtures.create_enrollment(
            api,
            premises_a["id"],
            world["product_id"],
            premises_a["version"],
            prepaid_amount_cents=3000,
        )
        assert enrollment_a["prepaid_amount_cents"] == 3000
        enrollment_b = fixtures.create_enrollment(
            api, premises_b["id"], world["product_id"], premises_b["version"]
        )
        assert enrollment_b["prepaid_amount_cents"] == 29988

        # Both policies reach ACTIVE at version 2 before either is cancelled.
        fixtures.set_clock(api, "2026-11-18T00:00:00.000Z")
        fixtures.run_nightly(api)

        # Earned premium 8591 plus the 2500 fee exceeds the 3000 prepayment, so
        # the refund would be negative.
        refused = api.cancel_enrollment(
            enrollment_a["id"],
            factories.cancellation_payload("2026-11-18"),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused, ERR_REFUND_NOT_AVAILABLE, 422)

        untouched = fixtures.refresh_enrollment(api, enrollment_a["id"])
        assert untouched["coverage_status"] == "ACTIVE"
        assert untouched["version"] == 2
        assert _cash_rows_of_type(api, enrollment_a["id"], "PRORATION_REFUND") == []

        # 27 of August's 31 days gives 2177, September 2499, October 2499, and
        # 17 of November's 30 days gives 1416: 8591 earned, 29988 - 8591 - 2500.
        settled = validate_success(
            api.cancel_enrollment(
                enrollment_b["id"],
                factories.cancellation_payload("2026-11-18"),
                CUSTOMER_SERVICE_REP,
            ),
            200,
        )
        assert settled["coverage_status"] == "CANCELLED"
        assert settled["cancellation_reason"] == "CUSTOMER_REQUEST"
        assert settled["cancellation_fee_cents"] == 2500
        assert settled["refund_cents"] == 18897
        assert settled["credit_cents"] == 0

        refunds = _cash_rows_of_type(api, enrollment_b["id"], "PRORATION_REFUND")
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == -18897


class TestComplaintRemedyGates:
    """The three remedy gates fire in their declared order.

    Each payload below differs from the next in exactly one field, so the error
    that comes back identifies which gate was reached.
    """

    def test_missing_target_then_forbidden_remedy_then_excessive_reversal(self, api):
        """An uncited complaint reports the missing target even though its
        disposition is also illegal, and only then does the reversal cap bite.

        PRD: "The remedy must have something to act on: `BENEFIT_REVERSAL` with no cited claim, or `PREMIUM_REFUND` or `REINSTATEMENT` with no cited policy, is refused with `ERR_REMEDY_TARGET_MISSING`."

        Design: Corner/errors/err_remedy_gates_target_then_disposition_then_posted_benefit
        """
        world = fixtures.active_coverage(api)
        contractor = fixtures.create_contractor(
            api, name="Cascade Trenchless", license_expires_on="2027-06-30"
        )

        claim = fixtures.file_claim(
            api,
            world["enrollment_id"],
            incident_description="Collapsed service line at the curb.",
        )
        claim_v2 = fixtures.approve_claim(api, claim["id"])["version"]
        dispatch = fixtures.dispatch_claim_to(
            api, claim["id"], claim_v2, contractor["id"], WINDOW_FIRST
        )
        fixtures.accept_dispatch(api, dispatch["id"], contractor["id"])
        fixtures.arrive_dispatch(api, dispatch["id"], contractor["id"])
        settled = fixtures.complete_dispatch(
            api,
            dispatch["id"],
            contractor["id"],
            260000,
            175000,
            permit_number="PRM-9001",
            permit_fee_cents=42000,
            restoration_cents=90000,
            restoration_scope="BASIC_BACKFILL",
        )
        assert settled["benefit_paid_cents"] == 527000

        # Complaint X cites nothing at all; complaint Y cites both the claim and
        # the policy the claim belongs to.
        complaint_x = fixtures.create_complaint(
            api,
            world["partner_id"],
            regulator="BBB",
            allegation="Generic advertising complaint with no policy attached.",
        )
        assert complaint_x["claim_id"] is None
        assert complaint_x["enrollment_id"] is None
        complaint_y = fixtures.create_complaint(
            api,
            world["partner_id"],
            regulator="PUC",
            allegation="Homeowner says the restoration was billed twice.",
            claim_id=claim["id"],
            enrollment_id=world["enrollment_id"],
        )

        # Two rules are violated: no cited claim to reverse against, and a money
        # remedy on an UNSUBSTANTIATED finding. The missing target wins.
        no_target = api.respond_to_complaint(
            complaint_x["id"],
            factories.complaint_response_payload(
                "UNSUBSTANTIATED",
                "BENEFIT_REVERSAL",
                complaint_x["version"],
                response_summary="Reversing a benefit that was never cited.",
                remedy_amount_cents=100000,
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(no_target, ERR_REMEDY_TARGET_MISSING, 422)

        # With the target present only the disposition rule can fire.
        not_permitted = api.respond_to_complaint(
            complaint_y["id"],
            factories.complaint_response_payload(
                "UNSUBSTANTIATED",
                "PREMIUM_REFUND",
                complaint_y["version"],
                response_summary="Nothing wrong was found, but here is a refund.",
                remedy_amount_cents=5000,
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(not_permitted, ERR_REMEDY_NOT_PERMITTED, 422)

        # Substantiated and targeted, but reversing more than was ever paid.
        too_much = api.respond_to_complaint(
            complaint_y["id"],
            factories.complaint_response_payload(
                "SUBSTANTIATED",
                "BENEFIT_REVERSAL",
                complaint_y["version"],
                response_summary="Reversing more than was ever paid.",
                remedy_amount_cents=600000,
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(too_much, ERR_REVERSAL_EXCEEDS_BENEFIT, 422)

        # The three refusals left the complaint at version 1, so the guard the
        # accepted response carries is the same one they all carried.
        closed = validate_success(
            api.respond_to_complaint(
                complaint_y["id"],
                factories.complaint_response_payload(
                    "SUBSTANTIATED",
                    "BENEFIT_REVERSAL",
                    complaint_y["version"],
                    response_summary="Full reversal of the posted benefit.",
                    remedy_amount_cents=527000,
                ),
                REGULATORY_AFFAIRS,
            ),
            200,
        )
        assert closed["status"] == "CLOSED_SUBSTANTIATED"
        assert closed["remedy_type"] == "BENEFIT_REVERSAL"
        assert closed["remedy_amount_cents"] == 527000
        assert closed["version"] == 2

        rows, _meta = assert_list_envelope(
            api.list_ledger_entries(
                PLATFORM_ADMIN,
                params={"claim_id": claim["id"], "ledger_kind": "BENEFIT"},
            ),
            expected_total=2,
        )
        assert [row["entry_type"] for row in rows] == ["BENEFIT_CHARGE", "BENEFIT_REVERSAL"]
        assert [row["amount_cents"] for row in rows] == [527000, -527000]

        enrollment = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert enrollment["annual_benefit_used_cents"] == 0
        assert enrollment["cap_status"] == "WITHIN_CAP"

        uncited = fixtures.refresh_complaint(api, complaint_x["id"])
        assert uncited["status"] == "OPEN"
        assert uncited["version"] == 1
