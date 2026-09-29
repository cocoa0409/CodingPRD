"""Cross-cutting behaviour of the Utility Service Line Warranty Program API.

These tests exercise the rules that are not owned by any single resource: the
five optimistic-concurrency guards of PRD §2.6, the cascade catalogue of §2.9,
the two settlement variants and the tiered notice ladder of §3.4, the pagination
contract of §2.3, the absence of any declared replay key, and the derived-field
definitions of §2.10 and §3.1.

Every test pins the logical clock explicitly, because most of the quantities
below are windowed and a clock parked outside the window is indistinguishable
from a missing implementation.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_DUPLICATE_ACTIVE_ENROLLMENT,
    ERR_INSUFFICIENT_RENEWAL_NOTICE,
    ERR_INVALID_CAMPAIGN_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_PAGINATION,
    ERR_PARTNER_NOT_ACTIVE,
    ERR_STALE_CLAIM_VERSION,
    ERR_STALE_COMPLAINT_VERSION,
    ERR_STALE_ENROLLMENT_VERSION,
    ERR_STALE_PARTNER_VERSION,
    ERR_STALE_PREMISES_VERSION,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_created_resource,
    assert_date_only,
    assert_drop_counts_agree,
    assert_drop_summary_shape,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_ledger_amounts,
    assert_list_envelope,
    assert_nightly_lists_empty,
    assert_nightly_names,
    assert_nightly_report_shape,
    assert_nulls,
    assert_object_envelope,
    assert_refused,
    assert_version_bumped,
)
from test_helpers.constants import (
    CANCELLATION_FEE_CENTS,
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    DEFAULT_LIMIT,
    MAX_LIMIT,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
    REGULATORY_AFFAIRS,
)

# A visit window one hour after the clock used to activate coverage, and a
# second window two days later for the redispatch.
WINDOW_ONE = "2026-09-10T09:00:00.000Z"
WINDOW_TWO = "2026-09-12T09:00:00.000Z"

# ROUTINE urgency is 72 hours from the claim's reported_at (PRD §3.6).
ROUTINE_SLA_DEADLINE = "2026-09-13T08:00:00.000Z"


class TestOptimisticConcurrencyGuards:
    """The five version-guarded writes of PRD §2.6, one test each."""

    def test_stale_partner_version_refuses_the_status_change(self, api):
        """A reinstatement carrying the pre-suspension snapshot is refused 412.

        PRD: "**Changing a partner's lifecycle status** requires `expected_partner_version` carrying the caller's last observed `version` of the target `UtilityPartner`."

        PRD: "A mismatch is refused with `ERR_STALE_PARTNER_VERSION` (HTTP 412) even when the requested transition is itself legal."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_stale_partner_version_refuses_the_status_change
        """
        fixtures.set_clock(api, CLOCK_START)
        partner = fixtures.create_partner(api)
        assert_created_resource(partner)
        assert_fields(partner, {"status": "ONBOARDING", "enrolled_premises_count": 0})
        assert_nulls(partner, ["suspension_reason"])

        fixtures.file_product(api, partner["id"])
        # A product filing advances UtilityPartner.version, so the activation
        # must carry the version observed after the filing (PRD §2.6).
        version_before_activation = fixtures.refresh_partner_version(api, partner["id"])
        activated = fixtures.activate_partner(api, partner["id"], version_before_activation)
        assert_fields(activated, {"status": "ACTIVE"})

        suspended = fixtures.change_partner_status(
            api, partner["id"], "SUSPENDED",
            activated["version"],
            reason="Marketing paused pending a disclosure review.",
        )
        assert_fields(suspended, {"status": "SUSPENDED"})
        assert_version_bumped(suspended, activated)
        assert suspended["suspension_reason"] == "Marketing paused pending a disclosure review."

        # SUSPENDED -> ACTIVE is a legal transition, but the snapshot is stale.
        refused = api.change_partner_status(
            partner["id"],
            factories.partner_status_change_payload(
                "ACTIVE", activated["version"],
                reason="Reinstated from the pre-suspension snapshot.",
            ),
            PLATFORM_ADMIN,
        )
        assert_refused(refused, ERR_STALE_PARTNER_VERSION, 412)

        # The refused write is a no-op on the partner it addressed.
        after_refusal = assert_object_envelope(api.get_partner(partner["id"], PLATFORM_ADMIN))
        assert_fields(after_refusal, {"status": "SUSPENDED", "version": suspended["version"]})

        # The identical body with the current version is accepted, and the
        # reinstatement clears suspension_reason back to null (PRD §2.9).
        reinstated = fixtures.change_partner_status(
            api, partner["id"], "ACTIVE", suspended["version"],
            reason="Reinstated from the current snapshot.",
        )
        assert_fields(reinstated, {"status": "ACTIVE", "version": suspended["version"] + 1})
        assert_nulls(reinstated, ["suspension_reason"])

    def test_stale_premises_version_refuses_the_enrollment(self, api):
        """The mail drop bumps Premises.version, so the pre-drop draft is refused.

        PRD: "Admission is decided from that premises snapshot — its `owned_segments`, its suppression state, its `last_mail_decision` — and a mail drop, an appeal-driven suppression recompute, or an earlier enrollment on the same address all advance `Premises.version` and invalidate it. A mismatch is refused with `ERR_STALE_PREMISES_VERSION` (HTTP 412)."

        PRD: "A drop touches every premises on the partner's file, mailed or suppressed alike, and each touched premises has its `version` incremented by 1."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_stale_premises_version_refuses_the_enrollment
        """
        world = fixtures.partner_product_premises(api)
        pre_drop_version = world["premises_version"]
        assert_fields(world["premises"], {
            "version": 1,
            "last_mail_decision": "NOT_EVALUATED",
            "mail_count_current_year": 0,
        })

        # The drop date must be on or before the clock's calendar date.
        world = fixtures.mailed_campaign(api, world, drop_date="2026-08-01")
        summary = world["drop_summary"]
        assert_drop_summary_shape(summary)
        assert_drop_counts_agree(summary)
        assert_fields(summary, {"status": "MAILED", "mailed_count": 1, "suppressed_count": 0})

        post_drop = assert_object_envelope(api.get_premises(world["premises_id"], MARKETING_OPS))
        assert_fields(post_drop, {
            "version": pre_drop_version + 1,
            "last_mail_decision": "MAILED",
            "mail_count_current_year": 1,
        })

        # The enrollment drafted from the pre-drop snapshot.
        refused = api.create_enrollment(
            factories.enrollment_payload(
                world["premises_id"], world["product_id"], pre_drop_version,
                source_campaign_id=world["campaign_id"],
                prepaid_amount_cents=None,
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(refused, ERR_STALE_PREMISES_VERSION, 412)

        # The refusal created no row and bumped nothing.
        assert_list_envelope(api.list_enrollments(CUSTOMER_SERVICE_REP), expected_total=0)
        after_refusal = assert_object_envelope(api.get_premises(world["premises_id"], MARKETING_OPS))
        assert_fields(after_refusal, {"version": pre_drop_version + 1})

        # The identical body with the post-drop version is accepted, and the
        # accepted enrollment bumps Premises.version once more (PRD §3.3).
        enrollment = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], post_drop["version"],
            source_campaign_id=world["campaign_id"], prepaid_amount_cents=None,
        )
        assert_created_resource(enrollment)
        assert_fields(enrollment, {
            "coverage_status": "PENDING_WAITING_PERIOD",
            "billing_mode": "DIRECT_BILL",
            "prepaid_amount_cents": 29988,
        })
        after_enrollment = assert_object_envelope(
            api.get_premises(world["premises_id"], MARKETING_OPS)
        )
        assert_fields(after_enrollment, {"version": post_drop["version"] + 1})

    def test_stale_claim_version_refuses_the_dispatch_and_the_supersede(self, api):
        """Claim.version moves at triage and again at dispatch, so one snapshot goes stale twice.

        PRD: "Any earlier accepted write on that claim — a triage decision, a previous dispatch, a supersede — has already advanced `Claim.version`, so a caller holding the pre-write snapshot is refused with `ERR_STALE_CLAIM_VERSION` (HTTP 412) even when the claim is still perfectly dispatchable and the identical body with the current version would have been accepted."

        PRD: "Every later dispatch on the claim, **including one created through `supersedes_dispatch_id`, inherits that instant unchanged**: re-dispatching a stalled job never buys the network more time."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_stale_claim_version_refuses_the_dispatch_and_the_supersede
        """
        world = fixtures.active_coverage(api)
        contractor_a = fixtures.create_contractor(api)
        contractor_b = fixtures.create_cheap_contractor(api)

        claim = fixtures.file_claim(api, world["enrollment_id"])
        assert_created_resource(claim)
        assert_fields(claim, {"status": "TRIAGE", "eligibility_assessment": "ELIGIBLE"})

        # The version is current here, so it is the state gate that refuses a
        # dispatch against a claim still in TRIAGE.
        before_triage = api.create_dispatch(
            claim["id"],
            factories.manual_dispatch_payload(claim["version"], WINDOW_ONE, contractor_a["id"]),
            OPERATIONS_ADMIN,
        )
        assert_refused(before_triage, ERR_INVALID_CLAIM_STATE, 409)

        approved = fixtures.approve_claim(api, claim["id"])
        assert_fields(approved, {"status": "APPROVED"})
        assert_version_bumped(approved, claim)

        # The same body, now genuinely stale because triage moved the claim.
        stale_dispatch = api.create_dispatch(
            claim["id"],
            factories.manual_dispatch_payload(claim["version"], WINDOW_ONE, contractor_a["id"]),
            OPERATIONS_ADMIN,
        )
        assert_refused(stale_dispatch, ERR_STALE_CLAIM_VERSION, 412)

        first = fixtures.dispatch_claim_to(
            api, claim["id"], approved["version"], contractor_a["id"], window_start=WINDOW_ONE,
        )
        assert_created_resource(first)
        assert_fields(first, {"status": "ASSIGNED", "contractor_id": contractor_a["id"]})
        assert_instant(first["sla_deadline_at"], ROUTINE_SLA_DEADLINE, "sla_deadline_at")

        dispatched = fixtures.refresh_claim(api, claim["id"])
        assert_fields(dispatched, {"status": "DISPATCHED", "version": approved["version"] + 1})

        # The supersede drafted before the first dispatch is stale in turn.
        stale_supersede = api.create_dispatch(
            claim["id"],
            factories.manual_dispatch_payload(
                approved["version"], WINDOW_TWO, contractor_b["id"],
                supersedes_dispatch_id=first["id"],
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(stale_supersede, ERR_STALE_CLAIM_VERSION, 412)

        untouched = fixtures.refresh_dispatch(api, first["id"])
        assert_fields(untouched, {"status": "ASSIGNED", "version": 1})

        second = fixtures.dispatch_claim_to(
            api, claim["id"], dispatched["version"], contractor_b["id"],
            window_start=WINDOW_TWO, supersedes_dispatch_id=first["id"],
        )
        assert_fields(second, {
            "status": "ASSIGNED",
            "contractor_id": contractor_b["id"],
            "supersedes_dispatch_id": first["id"],
        })
        # The response deadline is inherited, not restarted.
        assert_instant(second["sla_deadline_at"], ROUTINE_SLA_DEADLINE, "sla_deadline_at")

        superseded = fixtures.refresh_dispatch(api, first["id"])
        assert_fields(superseded, {"status": "SUPERSEDED"})

    def test_stale_enrollment_version_refuses_the_renewal_notice(self, api):
        """A cash write on the policy invalidates the pricing snapshot the notice was drafted from.

        PRD: "Renewal pricing is computed from the in-force price on that snapshot, and any billing event, cancellation, cap movement or earlier notice advances `Enrollment.version`. A mismatch is refused with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_stale_enrollment_version_refuses_the_renewal_notice
        """
        world = fixtures.active_coverage(api)
        active = world["enrollment"]
        assert_fields(active, {
            "coverage_status": "ACTIVE",
            "billing_status": "CURRENT",
            "monthly_price_cents": 2499,
            "renewal_notice_status": "NONE",
        })
        assert_nulls(active, ["renewal_price_cents", "renewal_effective_date"])

        paid = fixtures.billing_event(
            api, world["enrollment_id"], "PREMIUM_PAYMENT", "2026-09-10", amount_cents=2499,
        )
        assert_fields(paid, {
            "version": active["version"] + 1,
            "premium_collected_cents": 2499,
            "billing_status": "CURRENT",
        })

        refused = api.create_renewal_notice(
            world["enrollment_id"],
            factories.renewal_notice_payload(2599, "2027-08-05", active["version"]),
            BILLING_OPS,
        )
        assert_refused(refused, ERR_STALE_ENROLLMENT_VERSION, 412)

        after_refusal = fixtures.refresh_enrollment(api, world["enrollment_id"])
        assert_fields(after_refusal, {
            "version": paid["version"],
            "renewal_notice_status": "NONE",
        })
        assert_nulls(after_refusal, ["renewal_price_cents", "renewal_effective_date"])

        notice = fixtures.issue_renewal_notice(
            api, world["enrollment_id"], 2599, "2027-08-05", paid["version"],
        )
        assert_fields(notice, {
            "renewal_notice_status": "SENT",
            "renewal_price_cents": 2599,
            "renewal_effective_date": "2027-08-05",
            "version": paid["version"] + 1,
            # The in-force price is untouched until the renewal run applies it.
            "monthly_price_cents": 2499,
        })
        assert_date_only(notice["renewal_effective_date"], "renewal_effective_date")

    def test_stale_complaint_version_refuses_the_response(self, api):
        """The overnight overdue sweep, not a human, is what makes the response snapshot stale.

        PRD: "A response moves money, and the overnight overdue-and-escalation sweep or a prior escalation advances `RegulatorComplaint.version`, so a response drafted against the pre-sweep snapshot is refused with `ERR_STALE_COMPLAINT_VERSION` (HTTP 412)."

        PRD: "`days_overdue` is the floored whole days from `response_due_at` to the logical clock, floored at zero, and is zero once a response is filed."

        Design: Corner/cross_cutting_complexity_layers/cc_occ_stale_complaint_version_refuses_the_response
        """
        world = fixtures.active_partner_with_product(api)
        complaint = fixtures.create_complaint(
            api, world["partner_id"],
            allegation="The regulator asks for the disclosure trail on the curb-stop boundary.",
        )
        assert_created_resource(complaint)
        assert_fields(complaint, {"status": "OPEN", "escalation_count": 0})
        # RESPONSE_DAYS[PUC] is 10 days with no cited claim.
        assert_instant(complaint["response_due_at"], "2026-08-11T00:00:00.000Z", "response_due_at")

        fixtures.set_clock(api, "2026-08-12T00:00:00.000Z")
        report = fixtures.run_nightly(api)
        assert_nightly_report_shape(report)
        assert_nightly_names(report, "overdue_complaint_ids", [complaint["id"]])
        assert_nightly_lists_empty(report, except_for=("overdue_complaint_ids",))

        swept = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(swept, {
            "status": "OVERDUE",
            "version": complaint["version"] + 1,
            "days_overdue": 1,
            # days_overdue 1 has not reached the 5-day escalation grace.
            "escalation_count": 0,
        })

        # Responding from OVERDUE is legal; the pre-sweep version is not.
        refused = api.respond_to_complaint(
            complaint["id"],
            factories.complaint_response_payload(
                "UNSUBSTANTIATED", "NONE", complaint["version"],
                response_summary="Drafted from the pre-sweep snapshot.",
            ),
            REGULATORY_AFFAIRS,
        )
        assert_refused(refused, ERR_STALE_COMPLAINT_VERSION, 412)

        after_refusal = fixtures.refresh_complaint(api, complaint["id"])
        assert_fields(after_refusal, {"status": "OVERDUE", "version": swept["version"]})
        assert_nulls(after_refusal, ["responded_at", "disposition", "remedy_type"])

        closed = fixtures.respond_to_complaint(
            api, complaint["id"], "UNSUBSTANTIATED", "NONE", swept["version"],
            response_summary="The disclosure pack and the point-of-sale script are attached.",
        )
        assert_fields(closed, {
            "status": "CLOSED_UNSUBSTANTIATED",
            "version": swept["version"] + 1,
            "days_overdue": 0,
        })
        assert_instant(closed["responded_at"], "2026-08-12T00:00:00.000Z", "responded_at")


class TestCascadingSideEffects:
    """One accepted request fanning out across records the caller never named."""

    def test_partner_termination_withdraws_products_and_in_flight_campaigns(self, api):
        """Termination withdraws every product and only the non-terminal campaigns.

        PRD: "Terminating a partner performs the same campaign withdrawal cascade and, in addition, transitions every product of that partner to `WITHDRAWN` in `created_at` ascending order."

        PRD: "Suspending a partner sets its `suspension_reason` from the request and then, as one cascade hop, transitions every campaign of that partner whose status is `DRAFT`, `PARTNER_REVIEW` or `APPROVED` to `WITHDRAWN` in `created_at` ascending order, incrementing each campaign's `version`."

        PRD: "In-force coverage is deliberately untouched: suspension stops marketing and new enrollments, and no enrollment or claim changes state."

        Design: Corner/cross_cutting_complexity_layers/cc_cascading_side_effects_partner_termination_withdraws_products_and_in_flight_campaigns
        """
        fixtures.set_clock(api, CLOCK_START)
        # Four drops 21 days apart need a contact-frequency cap above the default.
        partner = fixtures.create_partner(api, max_mailings_per_year=4)
        product_one = fixtures.file_product(api, partner["id"])
        product_two = fixtures.file_product(
            api, partner["id"], name="Water Line Protect Plus", monthly_price_cents=3499,
        )
        assert_fields(product_one, {"status": "AVAILABLE"})
        assert_fields(product_two, {"status": "AVAILABLE"})
        activated = fixtures.activate_partner(
            api, partner["id"], fixtures.refresh_partner_version(api, partner["id"]),
        )
        premises = fixtures.create_premises(api, partner["id"])

        # A MAILED campaign: outside the withdrawal filter because MAILED is terminal.
        mailed = fixtures.create_campaign(
            api, partner["id"], product_one["id"], name="August drop",
            drop_date="2026-08-01", requested_quantity=1000,
        )
        fixtures.submit_campaign(api, mailed["id"])
        fixtures.approve_campaign(api, mailed["id"], partner["id"])
        summary = fixtures.mail_drop(api, mailed["id"])
        assert_fields(summary, {"status": "MAILED", "mailed_count": 1})

        # An APPROVED campaign, a PARTNER_REVIEW campaign and a DRAFT campaign.
        approved = fixtures.create_campaign(
            api, partner["id"], product_one["id"], name="Late August drop",
            piece_type="DIRECT_MAIL_LETTER", drop_date="2026-08-22", requested_quantity=800,
        )
        fixtures.submit_campaign(api, approved["id"])
        fixtures.approve_campaign(api, approved["id"], partner["id"])
        in_review = fixtures.create_campaign(
            api, partner["id"], product_two["id"], name="September drop",
            drop_date="2026-09-12", requested_quantity=600,
        )
        fixtures.submit_campaign(api, in_review["id"])
        draft = fixtures.create_campaign(
            api, partner["id"], product_two["id"], name="October drop",
            piece_type="DIRECT_MAIL_LETTER", drop_date="2026-10-03", requested_quantity=400,
        )

        enrollment = fixtures.create_enrollment(
            api, premises["id"], product_one["id"],
            fixtures.refresh_premises_version(api, premises["id"]),
        )
        assert_fields(enrollment, {"coverage_status": "PENDING_WAITING_PERIOD", "version": 1})

        # Snapshots taken immediately before the cascade, so each version claim
        # below is a claim about the cascade itself.
        before = {
            "product_one": assert_object_envelope(api.get_product(product_one["id"], PLATFORM_ADMIN)),
            "product_two": assert_object_envelope(api.get_product(product_two["id"], PLATFORM_ADMIN)),
            "mailed": assert_object_envelope(api.get_campaign(mailed["id"], MARKETING_OPS)),
            "approved": assert_object_envelope(api.get_campaign(approved["id"], MARKETING_OPS)),
            "in_review": assert_object_envelope(api.get_campaign(in_review["id"], MARKETING_OPS)),
            "draft": assert_object_envelope(api.get_campaign(draft["id"], MARKETING_OPS)),
        }
        assert_fields(before["mailed"], {"status": "MAILED"})
        assert_fields(before["approved"], {"status": "APPROVED"})
        assert_fields(before["in_review"], {"status": "PARTNER_REVIEW"})
        assert_fields(before["draft"], {"status": "DRAFT", "version": 1})

        terminated = fixtures.change_partner_status(
            api, partner["id"], "TERMINATED", activated["version"],
            reason="The utility exited the warranty programme.",
        )
        assert_fields(terminated, {
            "status": "TERMINATED",
            "version": activated["version"] + 1,
            # One premises holds live coverage, so the counter still reads 1.
            "enrolled_premises_count": 1,
        })

        # Hop 1: every product of the partner is withdrawn, none deleted.
        rows, _ = assert_list_envelope(
            api.list_products(PLATFORM_ADMIN, params={"partner_id": partner["id"]}),
            expected_total=2,
        )
        assert_created_at_ascending(rows)
        for key in ("product_one", "product_two"):
            after = assert_object_envelope(
                api.get_product(before[key]["id"], PLATFORM_ADMIN)
            )
            assert_fields(after, {"status": "WITHDRAWN"})
            assert_version_bumped(after, before[key])

        # Hop 2: DRAFT, PARTNER_REVIEW and APPROVED are withdrawn, MAILED is not.
        for key in ("approved", "in_review", "draft"):
            after = assert_object_envelope(api.get_campaign(before[key]["id"], MARKETING_OPS))
            assert_fields(after, {"status": "WITHDRAWN"})
            assert_version_bumped(after, before[key])
        mailed_after = assert_object_envelope(api.get_campaign(mailed["id"], MARKETING_OPS))
        assert_fields(mailed_after, {"status": "MAILED", "version": before["mailed"]["version"]})

        withdrawn_rows, _ = assert_list_envelope(
            api.list_campaigns(MARKETING_OPS, params={
                "partner_id": partner["id"], "status": "WITHDRAWN",
            }),
            expected_total=3,
        )
        assert sorted(row["id"] for row in withdrawn_rows) == sorted(
            [approved["id"], in_review["id"], draft["id"]]
        )

        # In-force coverage is deliberately untouched by the partner cascade.
        enrollment_after = fixtures.refresh_enrollment(api, enrollment["id"])
        assert_fields(enrollment_after, {"coverage_status": "PENDING_WAITING_PERIOD", "version": 1})

        # But every new marketing write is now refused.
        refused = api.create_campaign(
            factories.campaign_payload(
                partner["id"], product_one["id"], name="November drop",
                drop_date="2026-11-07", requested_quantity=200,
            ),
            MARKETING_OPS,
        )
        assert_refused(refused, ERR_PARTNER_NOT_ACTIVE, 409)


class TestDualVariantSettlement:
    """Two cancellations identical but for billing_mode, and genuinely different sums."""

    def test_cancellation_cash_refund_versus_bill_insert_credit(self, api):
        """DIRECT_BILL refunds 18897 in cash while BILL_INSERT credits 1083.

        PRD: "Under `DIRECT_BILL` the homeowner already paid the year up front, so unearned premium comes back as cash: `refund_cents` is `prepaid_amount_cents` less the earned premium less the cancellation fee, `credit_cents` is 0, and a proration-refund cash ledger row is appended for the negative of `refund_cents`."

        PRD: "Under `BILL_INSERT` the homeowner has been paying month by month, so `prepaid_amount_cents` is irrelevant and only the unused remainder of the final billed month is given back: the remaining days are the number of days in the month containing `cancellation_effective_date`, minus that date's day of the month, plus 1, and `credit_cents` is `monthly_price_cents` multiplied by those remaining days, divided by the number of days in that month, rounded half up."

        PRD: "The billing dimension goes `CURRENT → REFUND_ISSUED` under `DIRECT_BILL` and `CURRENT → CREDIT_ISSUED` under `BILL_INSERT`."

        Design: Corner/cross_cutting_complexity_layers/cc_dual_variant_cancellation_cash_refund_versus_bill_insert_credit
        """
        world = fixtures.partner_product_premises(api)
        premises_cash = world["premises"]
        premises_insert = fixtures.create_unique_premises(api, world["partner_id"])

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        cash = fixtures.create_enrollment(
            api, premises_cash["id"], world["product_id"], premises_cash["version"],
            prepaid_amount_cents=None,
        )
        insert = fixtures.create_bill_insert_enrollment(
            api, premises_insert["id"], world["product_id"], premises_insert["version"],
        )
        # Identical in product and term; the prepayment default is the only divergence.
        assert_fields(cash, {
            "term_start": "2026-08-05", "billing_mode": "DIRECT_BILL",
            "monthly_price_cents": 2499, "prepaid_amount_cents": 29988,
        })
        assert_fields(insert, {
            "term_start": "2026-08-05", "billing_mode": "BILL_INSERT",
            "monthly_price_cents": 2499, "prepaid_amount_cents": 0,
        })

        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        report = fixtures.run_nightly(api)
        assert_nightly_names(report, "activated_enrollment_ids", [cash["id"], insert["id"]])

        # A cancellation date 105 days after term_start: outside the free-look
        # window, so both variants record the 2500-cent fee.
        fixtures.set_clock(api, "2026-11-18T00:00:00.000Z")
        cash_settled = fixtures.cancel_enrollment(api, cash["id"], "2026-11-18")
        # earned premium 8591 = 2177 + 2499 + 2499 + 1416, each month rounded
        # before the sum; 29988 - 8591 - 2500 = 18897.
        assert_fields(cash_settled, {
            "coverage_status": "CANCELLED",
            "billing_status": "REFUND_ISSUED",
            "cancellation_effective_date": "2026-11-18",
            "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
            "refund_cents": 18897,
            "credit_cents": 0,
        })

        insert_settled = fixtures.cancel_enrollment(api, insert["id"], "2026-11-18")
        # days_remaining = 30 - 18 + 1 = 13; round_half_up(2499 * 13 / 30) = 1083.
        assert_fields(insert_settled, {
            "coverage_status": "CANCELLED",
            "billing_status": "CREDIT_ISSUED",
            "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
            "refund_cents": 0,
            "credit_cents": 1083,
        })

        cash_rows, _ = assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={
                "enrollment_id": cash["id"], "entry_type": "PRORATION_REFUND",
            }),
            expected_total=1,
        )
        assert_ledger_amounts(cash_rows, [-18897])
        assert_fields(cash_rows[0], {"ledger_kind": "CASH"})

        insert_rows, _ = assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={
                "enrollment_id": insert["id"], "entry_type": "PRORATION_CREDIT",
            }),
            expected_total=1,
        )
        assert_ledger_amounts(insert_rows, [-1083])
        assert_fields(insert_rows[0], {"ledger_kind": "CASH"})

        # The bill-insert variant never writes a proration-refund row.
        assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={
                "enrollment_id": insert["id"], "entry_type": "PRORATION_REFUND",
            }),
            expected_total=0,
        )

        # The same inputs diverge by 17814 cents purely on billing_mode.
        assert cash_settled["refund_cents"] - insert_settled["credit_cents"] == 17814


class TestRateThresholds:
    """Every rung of the renewal notice ladder, probed on both sides."""

    def test_renewal_notice_tier_ladder_at_every_boundary(self, api):
        """All four tiers accept at exactly their lead time and refuse one day short.

        PRD: "Four notice tiers are then consulted **in order**, and the first one that accepts the percentage supplies the requirement: a change of at most 0 percent requires 15 days' notice; a change of at most 10 percent requires 30 days; a change of at most 25 percent requires 45 days; and anything larger requires 60 days."

        PRD: "Because the tiers are consulted in that order, each boundary belongs to the lower tier — a change of exactly 10.00 percent falls in the 30-day tier, not the 45-day tier."

        PRD: "The lead time actually offered is the number of whole days from the logical clock's calendar date to `renewal_effective_date`, and the notice is compliant when that lead time is greater than or equal to the required days; a lead time exactly equal to the requirement is compliant."

        Design: Corner/cross_cutting_complexity_layers/cc_rate_threshold_renewal_notice_tier_ladder_at_every_boundary
        """
        # A round 2000-cent price makes each percentage exact, and the partner
        # files no rates, so the filing gate behind the tier never fires.
        world = fixtures.partner_product_premises(
            api, product_overrides={"monthly_price_cents": 2000},
        )
        world = fixtures.active_coverage(api, world, prepaid_amount_cents=24000)
        enrollment = world["enrollment"]
        assert_fields(enrollment, {
            "coverage_status": "ACTIVE",
            "monthly_price_cents": 2000,
            "prepaid_amount_cents": 24000,
            "term_start": "2026-08-05",
            "term_end": "2027-08-05",
            "renewal_notice_status": "NONE",
        })
        assert_nulls(enrollment, ["renewal_price_cents", "renewal_notice_sent_at"])

        renewal_date = "2027-08-05"
        version = enrollment["version"]

        def send(clock, new_price_cents, expected_version):
            fixtures.set_clock(api, clock)
            return api.create_renewal_notice(
                enrollment["id"],
                factories.renewal_notice_payload(
                    new_price_cents, renewal_date, expected_version,
                ),
                BILLING_OPS,
            )

        # Rung 4 — 25.05 percent is above every ceiling, so 60 days are owed.
        # 2027-06-05 offers 61 days.
        over = assert_object_envelope(send("2027-06-05T00:00:00.000Z", 2501, version))
        assert_fields(over, {"renewal_notice_status": "SENT", "renewal_price_cents": 2501})
        assert over["version"] == version + 1
        version = over["version"]

        # Exactly 60 days is compliant.
        exact_60 = assert_object_envelope(send("2027-06-06T00:00:00.000Z", 2501, version))
        assert_fields(exact_60, {"renewal_notice_status": "SENT", "renewal_price_cents": 2501})
        assert_instant(exact_60["renewal_notice_sent_at"], "2027-06-06T00:00:00.000Z",
                       "renewal_notice_sent_at")
        assert exact_60["version"] == version + 1
        version = exact_60["version"]

        # 59 days is one day short of the same tier.
        assert_refused(send("2027-06-07T00:00:00.000Z", 2501, version),
                       ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)
        after_refusal = fixtures.refresh_enrollment(api, enrollment["id"])
        # A refused notice bumps nothing, which is why the next accepted notice
        # reuses the same expected_enrollment_version.
        assert_fields(after_refusal, {
            "version": version,
            "renewal_notice_status": "SENT",
            "renewal_price_cents": 2501,
        })

        # Rung 3 — exactly 25.00 percent belongs to the 45-day tier, and
        # 2027-06-21 offers exactly 45 days.
        exact_45 = assert_object_envelope(send("2027-06-21T00:00:00.000Z", 2500, version))
        assert_fields(exact_45, {"renewal_notice_status": "SENT", "renewal_price_cents": 2500})
        assert exact_45["version"] == version + 1
        version = exact_45["version"]
        assert_refused(send("2027-06-22T00:00:00.000Z", 2500, version),
                       ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)

        # Rung 2 — exactly 10.00 percent belongs to the 30-day tier, not the
        # 45-day tier, and 2027-07-06 offers exactly 30 days.
        exact_30 = assert_object_envelope(send("2027-07-06T00:00:00.000Z", 2200, version))
        assert_fields(exact_30, {"renewal_notice_status": "SENT", "renewal_price_cents": 2200})
        assert exact_30["version"] == version + 1
        version = exact_30["version"]
        assert_refused(send("2027-07-07T00:00:00.000Z", 2200, version),
                       ERR_INSUFFICIENT_RENEWAL_NOTICE, 422)

        # Rung 1 — an unchanged price is 0.00 percent and needs 15 days, which
        # 2027-07-21 offers exactly.
        exact_15 = assert_object_envelope(send("2027-07-21T00:00:00.000Z", 2000, version))
        assert_fields(exact_15, {
            "renewal_notice_status": "SENT",
            "renewal_price_cents": 2000,
            # Every notice leaves the in-force price alone until the renewal run.
            "monthly_price_cents": 2000,
        })
        assert exact_15["version"] == version + 1


class TestPaginationWithFiltering:
    """limit, offset, total_count and has_more computed over the filtered set."""

    def test_premises_list_pagination_with_filtering_and_created_at_ordering(self, api):
        """The window is cut from the filtered, created_at-ordered set.

        PRD: "The `meta` object of a list response carries all four pagination fields: `limit` and `offset` echo the effective values used for the page, `total_count` reports the number of rows matching the filter before the page window is applied, and `has_more` is true exactly when rows remain beyond the current window."

        PRD: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."

        PRD: "A `limit` below 1, a `limit` above 100, an `offset` below 0, or a non-integer value for either is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."

        PRD: "Every list endpoint returns its rows sorted by `created_at` ascending, so the oldest record appears first and a freshly created record appears last."

        Design: Corner/cross_cutting_complexity_layers/cc_pagination_with_filtering_and_created_at_ordering_on_the_premises_list
        """
        fixtures.set_clock(api, CLOCK_START)
        partner_a = fixtures.create_partner(api)
        partner_b = fixtures.create_partner(api, name="Willamette Power", utility_type="ELECTRIC")

        # The clock is advanced an hour between creations so created_at is
        # strictly increasing and the ordering claims below are unambiguous.
        def at(hour, partner_id, street, **overrides):
            fixtures.set_clock(api, "2026-08-01T%02d:00:00.000Z" % hour)
            return fixtures.create_premises(
                api, partner_id, street_address=street, **overrides
            )

        p1 = at(1, partner_a["id"], "18 Alder Court")
        p2 = at(2, partner_a["id"], "22 Birch Lane", do_not_mail=True)
        p3 = at(3, partner_a["id"], "31 Cedar Way")
        p4 = at(4, partner_a["id"], "44 Douglas Fir Road", do_not_mail=True)
        p5 = at(5, partner_a["id"], "57 Elm Street")
        p6 = at(6, partner_b["id"], "9 Fern Hollow",
                owned_segments=["EXTERIOR_ELECTRIC_MAST"])
        # do_not_mail is the highest-precedence standing reason, so these two
        # are the suppressed subset of partner A's file.
        assert_fields(p2, {"suppression_reason": "DNM_REQUEST", "suppressed": True})
        assert_fields(p4, {"suppression_reason": "DNM_REQUEST", "suppressed": True})
        assert_fields(p1, {"suppression_reason": "NONE", "suppressed": False})

        # Unfiltered and unwindowed: the declared defaults, and both partners.
        rows, meta = assert_list_envelope(api.list_premises(MARKETING_OPS), expected_total=6)
        assert_fields(meta, {"limit": DEFAULT_LIMIT, "offset": 0, "has_more": False})
        assert_created_at_ascending(rows)
        assert_ids_in_order(rows, [p1["id"], p2["id"], p3["id"], p4["id"], p5["id"], p6["id"]])

        # The partner filter narrows the set before anything is counted.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={"partner_id": partner_a["id"]}),
            expected_total=5,
        )
        assert_fields(meta, {"has_more": False})
        assert_ids_in_order(rows, [p1["id"], p2["id"], p3["id"], p4["id"], p5["id"]])

        # First window of the filtered set: total_count still reports 5.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "limit": 2, "offset": 0,
            }),
            expected_total=5,
        )
        assert_fields(meta, {"limit": 2, "offset": 0, "has_more": True})
        assert_ids_in_order(rows, [p1["id"], p2["id"]])

        # Last window: a single row and nothing beyond it.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "limit": 2, "offset": 4,
            }),
            expected_total=5,
        )
        assert_fields(meta, {"offset": 4, "has_more": False})
        assert_ids_in_order(rows, [p5["id"]])

        # Filter first, then order: the suppressed subset keeps created_at ASC.
        rows, _ = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "suppressed": "true",
            }),
            expected_total=2,
        )
        assert_ids_in_order(rows, [p2["id"], p4["id"]])

        # Filter and window compose: offset 1 of the two-row filtered set.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "suppressed": "true",
                "limit": 1, "offset": 1,
            }),
            expected_total=2,
        )
        assert_fields(meta, {"has_more": False})
        assert_ids_in_order(rows, [p4["id"]])

        # An offset past the end is an empty page, not a refusal.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "limit": 2, "offset": 10,
            }),
            expected_total=5,
        )
        assert rows == []
        assert_fields(meta, {"has_more": False})

        # The three out-of-range probes share one identifier.
        assert_refused(api.list_premises(MARKETING_OPS, params={"limit": 0}),
                       ERR_INVALID_PAGINATION, 400)
        assert_refused(api.list_premises(MARKETING_OPS, params={"limit": 101}),
                       ERR_INVALID_PAGINATION, 400)
        assert_refused(api.list_premises(MARKETING_OPS, params={"offset": -1}),
                       ERR_INVALID_PAGINATION, 400)

        # 100 is the inclusive maximum.
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={"limit": MAX_LIMIT}),
            expected_total=6,
        )
        assert_fields(meta, {"limit": MAX_LIMIT})

        # A row created after the first read appends to the tail, so the earlier
        # window is unchanged and the offset stays stable.
        p7 = at(7, partner_a["id"], "63 Hemlock Court")
        rows, meta = assert_list_envelope(
            api.list_premises(MARKETING_OPS, params={
                "partner_id": partner_a["id"], "limit": 2, "offset": 4,
            }),
            expected_total=6,
        )
        assert_fields(meta, {"has_more": False})
        assert_ids_in_order(rows, [p5["id"], p7["id"]])
        assert p3["id"] not in [row["id"] for row in rows]


class TestIdempotency:
    """No replay key is declared, so a replay is a new row or a business refusal."""

    def test_replays_are_new_rows_or_business_refusals(self, api):
        """An identical create duplicates; an identical transition is state-gated.

        PRD: "The campaign opens in `DRAFT` with `version` 1, `revision_count` 0, `mailed_count` 0 and `suppressed_count` 0, and its `approved_quantity` is null."

        PRD: "A campaign that is not in a state the requested transition leaves from yields `ERR_INVALID_CAMPAIGN_STATE` — submission requires `DRAFT` or `REJECTED`, a decision requires `PARTNER_REVIEW`, a mail drop requires `APPROVED`."

        PRD: "And an address may not hold two live policies on the same product — if an existing enrollment on that `product_id` is `PENDING_WAITING_PERIOD`, `ACTIVE` or `SUSPENDED_NONPAY`, the second is refused with `ERR_DUPLICATE_ACTIVE_ENROLLMENT`."

        PRD: "A claim in the wrong state yields `ERR_INVALID_CLAIM_STATE` — a triage decision requires `TRIAGE`; dispatching requires `APPROVED`, or `DISPATCHED` when the request names an open dispatch of the same claim to supersede; opening an appeal requires `DENIED`; an appeal decision requires `APPEAL_OPEN`."

        PRD: "Because the run is idempotent with respect to a fixed clock — every phase is guarded by a condition that its own action falsifies — invoking it twice without moving the clock produces the same state as invoking it once, and the second invocation returns eleven empty lists."

        Design: Corner/cross_cutting_complexity_layers/cc_idempotency_is_undeclared_so_replays_are_new_rows_or_business_refusals
        """
        world = fixtures.partner_product_premises(api)
        draft_payload = dict(
            name="August water drop", drop_date="2026-08-01", requested_quantity=1000,
        )
        campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"], **draft_payload
        )

        # A byte-identical create a minute later. Nothing in the request carries
        # a replay key, and a campaign name is not declared unique, so this is
        # simply a second independent row.
        fixtures.set_clock(api, "2026-08-01T00:01:00.000Z")
        twin = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"], **draft_payload
        )
        assert twin["id"] != campaign["id"]
        assert_created_resource(twin)
        assert_fields(twin, {"status": "DRAFT", "name": "August water drop"})
        assert_list_envelope(
            api.list_campaigns(MARKETING_OPS, params={"partner_id": world["partner_id"]}),
            expected_total=2,
        )

        # A replayed state transition is refused by its own state gate.
        submitted = fixtures.submit_campaign(api, campaign["id"], note="First submission.")
        assert_fields(submitted, {"status": "PARTNER_REVIEW"})
        assert_version_bumped(submitted, campaign)
        replayed_submission = api.submit_campaign(
            campaign["id"], factories.campaign_submission_payload(note="First submission."),
            MARKETING_OPS,
        )
        assert_refused(replayed_submission, ERR_INVALID_CAMPAIGN_STATE, 409)
        assert_fields(
            assert_object_envelope(api.get_campaign(campaign["id"], MARKETING_OPS)),
            {"status": "PARTNER_REVIEW", "version": submitted["version"]},
        )

        # A replayed enrollment is refused by the duplicate-policy rule. The
        # accepted enrollment bumped the premises, so the replay must carry the
        # refreshed version — otherwise the stale-version guard would mask it.
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, world["premises_id"], world["product_id"], world["premises_version"],
        )
        premises_version = fixtures.refresh_premises_version(api, world["premises_id"])
        assert premises_version == world["premises_version"] + 1
        replayed_enrollment = api.create_enrollment(
            factories.enrollment_payload(
                world["premises_id"], world["product_id"], premises_version,
            ),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(replayed_enrollment, ERR_DUPLICATE_ACTIVE_ENROLLMENT, 422)

        # The batch is idempotent by construction: the second run at the same
        # clock finds no PENDING_WAITING_PERIOD enrollment left.
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        first_run = fixtures.run_nightly(api)
        assert_nightly_report_shape(first_run)
        assert_nightly_names(first_run, "activated_enrollment_ids", [enrollment["id"]])
        assert_nightly_lists_empty(first_run, except_for=("activated_enrollment_ids",))
        assert_instant(first_run["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")

        second_run = fixtures.run_nightly(api)
        assert_nightly_report_shape(second_run)
        assert_nightly_lists_empty(second_run)
        assert_instant(second_run["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")

        after_two_runs = fixtures.refresh_enrollment(api, enrollment["id"])
        assert_fields(after_two_runs, {"coverage_status": "ACTIVE"})
        assert_version_bumped(after_two_runs, enrollment)

        # And a replayed triage decision is refused by the claim's state gate.
        claim = fixtures.file_claim(api, enrollment["id"])
        denied = fixtures.deny_claim(api, claim["id"])
        assert_fields(denied, {"status": "DENIED"})
        assert_version_bumped(denied, claim)
        replayed_triage = api.triage_claim(
            claim["id"], factories.triage_denial_payload("NOT_COVERED_SEGMENT"),
            CLAIMS_ADJUSTER,
        )
        assert_refused(replayed_triage, ERR_INVALID_CLAIM_STATE, 409)
        assert_fields(
            fixtures.refresh_claim(api, claim["id"]),
            {"status": "DENIED", "version": denied["version"]},
        )


class TestDerivedFieldReconciliation:
    """Each derived field reconciles against its own declared source set."""

    def test_cash_ledger_and_partner_counter_reconcile_to_their_own_sources(self, api):
        """A write-off raises only the refunded side; the counter tracks live coverage.

        PRD: "On the cash side, `premium_collected_cents` is the sum of `amount_cents` over this enrollment's `CASH` rows whose `entry_type` is `PREMIUM_PAYMENT`, `INSERT_REMITTANCE`, `CANCELLATION_FEE` or `REFUND_CLAWBACK`, and `premium_refunded_cents` is the absolute value of the sum over its `CASH` rows whose `entry_type` is `PRORATION_REFUND`, `PRORATION_CREDIT` or `WRITE_OFF`."

        PRD: "A **missed payment** moves the billing dimension `CURRENT → PAST_DUE` and stamps `past_due_since` with the event's own `effective_date`; it writes no ledger row at all, because a missed payment moves no money."

        PRD: "A **write-off** moves `PAST_DUE → WRITTEN_OFF` and appends one cash row with a negative `amount_cents`."

        PRD: "That last figure is a live cross-entity count rather than a stored tally: it is the number of distinct premises on this partner's file that hold at least one enrollment whose coverage is `PENDING_WAITING_PERIOD`, `ACTIVE` or `SUSPENDED_NONPAY`."

        PRD: "`suppression_reason` is the highest-precedence **standing** suppression reason for the address, drawn from `NONE`, `DNM_REQUEST`, `BAD_ADDRESS`, `REGULATOR_COMPLAINT_OPEN`, `OPEN_APPEAL` and `CONTACT_FREQUENCY_CAP`; it is evaluated in the same precedence order the mail drop uses, but with the two campaign-scoped reasons deliberately skipped, because whether an address is already enrolled or ownership-ineligible cannot be answered without knowing which product a campaign is marketing."

        Design: Corner/cross_cutting_complexity_layers/cc_derived_field_reconciliation_across_the_cash_ledger_and_the_partner_counter
        """
        world = fixtures.partner_product_premises(api)
        premises_one = world["premises"]
        premises_two = fixtures.create_unique_premises(api, world["partner_id"])
        assert_fields(world["partner"], {"enrolled_premises_count": 0})

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        one = fixtures.create_enrollment(
            api, premises_one["id"], world["product_id"], premises_one["version"],
        )
        # prepaid_amount_cents is a term input, not a ledger row, so neither cash
        # aggregate has anything to sum yet.
        assert_fields(one, {
            "prepaid_amount_cents": 29988,
            "premium_collected_cents": 0,
            "premium_refunded_cents": 0,
        })
        assert_fields(
            assert_object_envelope(api.get_partner(world["partner_id"], PLATFORM_ADMIN)),
            {"enrolled_premises_count": 1},
        )

        # The enrollment re-derived the address's suppression, but being enrolled
        # is one of the two campaign-scoped reasons the standing field skips.
        assert_fields(
            assert_object_envelope(api.get_premises(premises_one["id"], MARKETING_OPS)),
            {"suppression_reason": "NONE", "suppressed": False},
        )

        two = fixtures.create_bill_insert_enrollment(
            api, premises_two["id"], world["product_id"], premises_two["version"],
        )
        # The counter counts premises, not enrollments.
        assert_fields(
            assert_object_envelope(api.get_partner(world["partner_id"], PLATFORM_ADMIN)),
            {"enrolled_premises_count": 2},
        )

        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)

        paid_once = fixtures.billing_event(
            api, one["id"], "PREMIUM_PAYMENT", "2026-09-10", amount_cents=2499,
        )
        assert_fields(paid_once, {"premium_collected_cents": 2499, "billing_status": "CURRENT"})
        paid_twice = fixtures.billing_event(
            api, one["id"], "PREMIUM_PAYMENT", "2026-09-10", amount_cents=2499,
        )
        assert_fields(paid_twice, {"premium_collected_cents": 4998})

        fixtures.set_clock(api, "2026-10-05T00:00:00.000Z")
        missed = fixtures.billing_event(api, one["id"], "MISSED_PAYMENT", "2026-10-05")
        assert_fields(missed, {
            "billing_status": "PAST_DUE",
            "past_due_since": "2026-10-05",
            "premium_collected_cents": 4998,
        })
        assert_date_only(missed["past_due_since"], "past_due_since")
        # The missed payment moved the billing dimension without writing a row.
        assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={"enrollment_id": one["id"]}),
            expected_total=2,
        )

        fixtures.set_clock(api, "2026-10-20T00:00:00.000Z")
        written_off = fixtures.billing_event(
            api, one["id"], "WRITE_OFF", "2026-10-20", amount_cents=2499,
        )
        # WRITE_OFF is outside the collected entry-type set and inside the
        # refunded one, so only the second aggregate moves.
        assert_fields(written_off, {
            "billing_status": "WRITTEN_OFF",
            "premium_collected_cents": 4998,
            "premium_refunded_cents": 2499,
        })
        rows, _ = assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS, params={
                "enrollment_id": one["id"], "entry_type": "WRITE_OFF",
            }),
            expected_total=1,
        )
        assert_ledger_amounts(rows, [-2499])
        assert_fields(rows[0], {"ledger_kind": "CASH"})

        # The bill-insert policy's own settlement: days_remaining = 31 - 20 + 1
        # = 12, and round_half_up(2499 * 12 / 31) is 967.
        settled = fixtures.cancel_enrollment(api, two["id"], "2026-10-20", reason="MOVED")
        assert_fields(settled, {
            "coverage_status": "CANCELLED",
            "cancellation_reason": "MOVED",
            "credit_cents": 967,
            "refund_cents": 0,
            "cancellation_fee_cents": CANCELLATION_FEE_CENTS,
            # The -967 proration-credit row lands in the refunded aggregate, and
            # the positive cancellation-fee row in the collected one.
            "premium_refunded_cents": 967,
            "premium_collected_cents": CANCELLATION_FEE_CENTS,
        })

        # CANCELLED is outside the live set, so the second premises leaves the
        # counter while the first, merely written off, stays.
        assert_fields(
            assert_object_envelope(api.get_partner(world["partner_id"], PLATFORM_ADMIN)),
            {"enrolled_premises_count": 1},
        )
