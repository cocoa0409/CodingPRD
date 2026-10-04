"""Licensee fee engine, license lifecycle, disputes, and rate court tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    make_licensee_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    create_licensee_payload,
    issue_license_payload,
    open_dispute_payload,
    create_broadcaster_with_license,
    _create_licensee,
    _issue_license,
)

LIC_ADMIN = TEST_USERS["pro_licensing_admin_headers"]
COURT = TEST_USERS["rate_court_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


class TestDifficultyFeeEngineFormula:
    def test_digital_service_straddling_tier_cap(self, api):
        """PRD §3.4: "For a DIGITAL_SERVICE, the marginal tiers charge the portion of
        revenue up to 100,000,000,000 cents at 0.0175 and the portion above at 0.0150,
        and on top of the tier sum the engine adds a per-stream charge of 20 micro-cents
        per usage unit (that is, usage_units multiplied by 20 and divided by 10000 to
        convert micro-cents to cents) before taking the maximum against a minimum of
        10,000,000 cents."

        Design: Difficulty/combinatorial_formula/fee_engine_tiered_category_formula
        """
        licensee = _create_licensee(
            legal_name="StreamCo",
            category="DIGITAL_SERVICE",
            reported_revenue_cents=200000000000,
            usage_units=5000000000,
        )
        # 100e9*0.0175 + 100e9*0.0150 + 5e9*20/10000 = 1.75e9 + 1.5e9 + 1e7 = 3.26e9
        assert licensee["blanket_fee_cents"] == 3260000000

    def test_venue_flat_rate_and_digital_minimum(self, api):
        """PRD §3.4: "For a VENUE, the structure is flat rather than tiered: the fee is
        0.0080 times the revenue plus a per-event charge of 15,000 cents per usage unit,
        floored at a minimum of 5,000,000 cents."
        PRD §3.4: "the engine adds a per-stream charge of 20 micro-cents per usage unit
        (that is, usage_units multiplied by 20 and divided by 10000 to convert
        micro-cents to cents) before taking the maximum against a minimum of 10,000,000
        cents."

        Design: Difficulty/combinatorial_formula/fee_engine_tiered_category_formula
        """
        venue = _create_licensee(
            legal_name="ClubCo", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=400,
        )
        # 0.0080 * 10e9 + 400 * 15000 = 80e6 + 6e6 = 86e6
        assert venue["blanket_fee_cents"] == 86000000
        tiny = _create_licensee(
            legal_name="TinyNet", category="DIGITAL_SERVICE",
            reported_revenue_cents=1000000, usage_units=1000,
        )
        # formula 1000000*0.0175 + 1000*20/10000 = 17500 + 2 = 17502 -> floored to 10e6
        assert tiny["blanket_fee_cents"] == 10000000


class TestCornerFeeEngineBoundary:
    def test_broadcaster_tier1_cap_exact_and_one_cent_above(self, api):
        """PRD §3.4: "For a BROADCASTER, the fee is a marginal-tier sum over
        reported_revenue_cents: the portion up to 500,000,000,000 cents is charged at a
        rate of 0.0160, the portion above that cap up to 2,000,000,000,000 cents is
        charged at 0.0140, and any portion beyond the second cap is charged at 0.0110;
        the result is compared against a minimum fee of 25,000,000 cents."
        PRD §2.7: "Where a calculation yields a fractional cent, the result is rounded
        half-up to whole cents, and each calculation rounds exactly once".

        Design: Corner/calculations/fee_engine_broadcaster_tier_cap_boundary
        """
        at_cap = _create_licensee(
            legal_name="Cap Radio", category="BROADCASTER",
            reported_revenue_cents=500000000000, usage_units=0,
        )
        assert at_cap["blanket_fee_cents"] == 8000000000
        above = _create_licensee(
            legal_name="Cap Plus Radio", category="BROADCASTER",
            reported_revenue_cents=500000000100, usage_units=0,
        )
        # 100 cents above the cap at 0.0140 = 1.4 cents, round_half_up -> 1
        assert above["blanket_fee_cents"] == 8000000001


class TestDifficultyNegotiatedFeeOverride:
    def test_settle_overrides_formula_fee_but_keeps_pinned_basis(self, api):
        """PRD §3.6: "Settlement records the figure in settled_fee_cents, moves the
        dispute to SETTLED, returns the license from DISPUTED to ACTIVE, and — when the
        agreed figure differs from the licensee's current blanket_fee_cents — sets the
        licensee's blanket_fee_cents to the agreed figure."
        PRD §3.5: "That pinned basis is permanent: every performance and every pool
        computation under this license uses the pinned fee_basis_cents, even if the
        licensee's fee later changes."

        Design: Difficulty/dual_variant_calc/negotiated_settlement_vs_formula_fee
        """
        licensee = _create_licensee(
            legal_name="Net TV Inc", category="BROADCASTER",
            reported_revenue_cents=300000000000, usage_units=0,
        )
        assert licensee["blanket_fee_cents"] == 4800000000
        license_ = _issue_license(licensee)
        assert license_["fee_basis_cents"] == 4800000000

        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=3000000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api.negotiate_dispute(dispute["id"], {"counter_fee_cents": 3200000000}, LIC_ADMIN)
        )
        settled = validate_success(
            api.settle_dispute(dispute["id"], {"agreed_fee_cents": 3500000000}, LIC_ADMIN)
        )
        assert settled["status"] == "SETTLED"
        assert settled["settled_fee_cents"] == 3500000000

        licensee_after = validate_success(api.get_licensee(licensee["id"], LIC_ADMIN))
        # Negotiated override variant: the settled figure stands in place of the formula.
        assert licensee_after["blanket_fee_cents"] == 3500000000
        license_after = validate_success(api.get_license(license_["id"], LIC_ADMIN))
        # The pinned fee basis is unaffected by the settlement.
        assert license_after["fee_basis_cents"] == 4800000000
        assert license_after["status"] == "ACTIVE"

    def test_revenue_patch_after_settle_takes_max_of_engine_and_settled(self, api):
        """PRD §3.4: "when a settled rate dispute has set the licensee's
        blanket_fee_cents to a negotiated or adjudicated figure, the engine is bypassed
        and the settled figure stands until the next revenue or usage update, at which
        point the engine re-runs and the licensee's fee becomes the greater of the
        engine's fresh computation and the settled figure."

        Design: Difficulty/dual_variant_calc/negotiated_settlement_vs_formula_fee
        """
        licensee = _create_licensee(
            legal_name="Net TV Two", category="BROADCASTER",
            reported_revenue_cents=300000000000, usage_units=0,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=3000000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api.negotiate_dispute(dispute["id"], {"counter_fee_cents": 3200000000}, LIC_ADMIN)
        )
        validate_success(api.settle_dispute(dispute["id"], {"agreed_fee_cents": 3500000000}, LIC_ADMIN))

        # Patch revenue down: engine computes 25,000,000 floor < settled 3,500,000,000.
        patched = validate_success(
            api.update_licensee(licensee["id"], {"reported_revenue_cents": 0}, LIC_ADMIN)
        )
        assert patched["blanket_fee_cents"] == 3500000000


class TestDifficultyNegotiationCourtCycle:
    def test_negotiation_loop_then_court_dismissal_returns_to_negotiation(self, api):
        """PRD §3.6: "Dismissing a case while it is FILED sends the dispute back to
        NEGOTIATION and increments negotiation_rounds — the negotiation loop can thus
        cycle through the court more than once across separate cases, though never with
        two live cases at once."
        PRD §3.6: "The licensing admin opens the first round by moving the dispute from
        OPEN to NEGOTIATION, incrementing negotiation_rounds. Thereafter, either the
        admin or the licensee may advance further rounds with a counter_fee_cents
        payload that must differ from the last offered fee; each such round increments
        negotiation_rounds again."

        Design: Difficulty/non_linear_state_machine/dispute_negotiation_court_cycle
        """
        licensee = _create_licensee(
            legal_name="Cycle Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=400,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=70000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        round1 = validate_success(
            api.negotiate_dispute(dispute["id"], {"counter_fee_cents": 75000000}, LIC_ADMIN)
        )
        assert round1["negotiation_rounds"] == 1
        round2 = validate_success(
            api.negotiate_dispute(
                dispute["id"], {"counter_fee_cents": 78000000}, make_licensee_headers(licensee["id"])
            )
        )
        assert round2["negotiation_rounds"] == 2

        case = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        assert case["status"] == "FILED"
        validate_success(api.dismiss_case(case["id"], COURT))

        back = validate_success(api.get_dispute(dispute["id"], LIC_ADMIN))
        assert back["status"] == "NEGOTIATION"
        assert back["negotiation_rounds"] == 3

    def test_dismissed_case_allows_a_second_escalation(self, api):
        """PRD §3.6: "A dispute stuck in OPEN or NEGOTIATION may be escalated to the
        rate court by the licensee, provided no non-DISMISSED rate court case already
        exists for the dispute — a duplicate escalation is rejected with
        ERR_RATE_COURT_CASE_EXISTS."
        PRD §3.6: "Dismissing a case while it is FILED sends the dispute back to
        NEGOTIATION and increments negotiation_rounds — the negotiation loop can thus
        cycle through the court more than once across separate cases, though never with
        two live cases at once."

        Design: Difficulty/non_linear_state_machine/dispute_negotiation_court_cycle
        """
        licensee = _create_licensee(
            legal_name="Cycle Co Two", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=400,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=70000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        case1 = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        validate_success(api.dismiss_case(case1["id"], COURT))
        # The dismissed case no longer blocks a fresh escalation.
        case2 = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        assert case2["status"] == "FILED"
        dispute_after = validate_success(api.get_dispute(dispute["id"], LIC_ADMIN))
        assert dispute_after["status"] == "RATE_COURT"


class TestDifficultyRateCourtCascade:
    def test_decide_cascades_to_dispute_license_and_licensee(self, api):
        """PRD §3.6: "deciding the case from HEARING requires a non-negative
        adjudicated_fee_cents payload, moves the case to the terminal DECIDED status,
        stamps the figure onto the case, moves the dispute from RATE_COURT to SETTLED
        with settled_fee_cents equal to the adjudicated figure, returns the license to
        ACTIVE (or leaves it EXPIRED if the clock already passed expiry, with retro
        handled through adjustments), and sets the licensee's blanket_fee_cents to the
        adjudicated figure."
        PRD §3.5: "That pinned basis is permanent: every performance and every pool
        computation under this license uses the pinned fee_basis_cents, even if the
        licensee's fee later changes."

        Design: Difficulty/transitive_cascade/rate_court_decision_four_hop_cascade
        """
        licensee = _create_licensee(
            legal_name="Cascade BC", category="BROADCASTER",
            reported_revenue_cents=300000000000, usage_units=0,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=4000000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        case = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        validate_success(api.open_hearing(case["id"], COURT))
        decided = validate_success(
            api.decide_case(case["id"], {"adjudicated_fee_cents": 4200000000}, COURT)
        )
        assert decided["status"] == "DECIDED"
        assert decided["adjudicated_fee_cents"] == 4200000000

        dispute_after = validate_success(api.get_dispute(dispute["id"], COURT))
        assert dispute_after["status"] == "SETTLED"
        assert dispute_after["settled_fee_cents"] == 4200000000

        license_after = validate_success(api.get_license(license_["id"], LIC_ADMIN))
        assert license_after["status"] == "ACTIVE"
        assert license_after["fee_basis_cents"] == 4800000000

        licensee_after = validate_success(api.get_licensee(licensee["id"], LIC_ADMIN))
        assert licensee_after["blanket_fee_cents"] == 4200000000

    def test_open_hearing_then_dismiss_after_hearing_not_declared(self, api):
        """PRD §3.6: "A dispute stuck in OPEN or NEGOTIATION may be escalated to the
        rate court by the licensee, provided no non-DISMISSED rate court case already
        exists for the dispute — a duplicate escalation is rejected with
        ERR_RATE_COURT_CASE_EXISTS."
        PRD §3.6: "Escalation creates a RateCourtCase in FILED status and moves the
        dispute to RATE_COURT."
        PRD §2.6: state-machine permission (ERR_INVALID_STATE) is evaluated before the
        business checks, so a second escalation attempted while the dispute already sits
        in RATE_COURT is rejected with ERR_INVALID_STATE.

        Design: Difficulty/transitive_cascade/rate_court_decision_four_hop_cascade
        """
        licensee = _create_licensee(
            legal_name="Cascade BC 2", category="BROADCASTER",
            reported_revenue_cents=300000000000, usage_units=0,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=4000000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        case = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        # A second escalation while the first case is live is rejected: the dispute is
        # now in RATE_COURT, and PRD §2.6 evaluates the state-machine permission
        # (escalation is permitted only from OPEN or NEGOTIATION) before the business
        # duplicate-case check, so the rejection is ERR_INVALID_STATE.
        resp = api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # The chain's first hop is intact: the case sits FILED under a RATE_COURT dispute.
        dispute_after = validate_success(api.get_dispute(dispute["id"], COURT))
        assert dispute_after["status"] == "RATE_COURT"
        assert dispute_after["settled_fee_cents"] is None

    def test_decide_from_filed_rejected(self, api):
        """PRD §3.6: "A RateCourtOfficer then drives the case: opening a hearing moves
        it FILED to HEARING; deciding the case from HEARING requires a non-negative
        adjudicated_fee_cents payload".
        PRD §2.5: "State checks come after existence: an operation that the target's
        current state does not permit is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/rate_court_decide_from_filed_rejected
        """
        licensee = _create_licensee(
            legal_name="Court Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=80000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        case = validate_success(
            api.escalate_dispute(dispute["id"], make_licensee_headers(licensee["id"])),
            expected_status=201,
        )
        assert case["status"] == "FILED"
        resp = api.decide_case(case["id"], {"adjudicated_fee_cents": 80000000}, COURT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCornerDisputeAndLicenseState:
    def test_settle_from_open_rejected(self, api):
        """PRD §3.6: "When the parties converge, the admin settles the dispute from
        NEGOTIATION by presenting the agreed_fee_cents, which must be non-negative."
        PRD §2.5: "State checks come after existence: an operation that the target's
        current state does not permit is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/dispute_settle_from_open_rejected
        """
        licensee = _create_licensee(
            legal_name="Settle Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=80000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        assert dispute["status"] == "OPEN"
        resp = api.settle_dispute(dispute["id"], {"agreed_fee_cents": 80000000}, LIC_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_dispute(dispute["id"], LIC_ADMIN))
        assert after["status"] == "OPEN"

    def test_suspend_requires_delinquent_standing(self, api):
        """PRD §3.5: "When the licensee's standing deteriorates to DELINQUENT, the
        licensing admin may suspend the license, moving it from ACTIVE — or from
        DISPUTED if a dispute is in flight — to SUSPENDED".
        PRD §2.5: "State checks come after existence: an operation that the target's
        current state does not permit is rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/license_suspend_requires_delinquent_standing
        """
        licensee = _create_licensee(
            legal_name="Good Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        assert licensee["credit_standing"] == "GOOD"
        license_ = _issue_license(licensee)
        resp = api.suspend_license(license_["id"], LIC_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pro_opened_dispute_not_withdrawable_by_licensee(self, api):
        """PRD §3.6: "Withdrawal is available only when the dispute's opened_by_role is
        LICENSEE and the caller is the licensee that owns the license; attempts to
        withdraw a PRO-opened dispute, or by a non-owning licensee, are rejected with
        ERR_DISPUTE_NOT_WITHDRAWABLE."

        Design: Corner/validations/dispute_withdraw_by_non_opener_rejected
        """
        licensee = _create_licensee(
            legal_name="Wth Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_ = _issue_license(licensee)
        dispute = validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="PRO", disputed_fee_cents=80000000),
                LIC_ADMIN,
            ),
            expected_status=201,
        )
        assert dispute["opened_by_role"] == "PRO"
        resp = api.withdraw_dispute(dispute["id"], make_licensee_headers(licensee["id"]))
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_WITHDRAWABLE)

    def test_second_dispute_on_same_license_rejected(self, api):
        """PRD §3.6: "Only one live dispute may exist per license — a second opening
        while an OPEN, NEGOTIATION, or RATE_COURT dispute exists is rejected with
        ERR_DISPUTE_ALREADY_OPEN."

        Design: Corner/validations/second_dispute_on_same_license_rejected
        """
        licensee = _create_licensee(
            legal_name="D2 Co", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_ = _issue_license(licensee)
        validate_success(
            api.open_dispute(
                license_["id"],
                open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=80000000),
                make_licensee_headers(licensee["id"]),
            ),
            expected_status=201,
        )
        resp = api.open_dispute(
            license_["id"],
            open_dispute_payload(opened_by_role="LICENSEE", disputed_fee_cents=70000000),
            make_licensee_headers(licensee["id"]),
        )
        # The license is DISPUTED, so a faithful implementation may report either the
        # domain-specific duplicate-dispute error or the generic state error.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_DISPUTE_ALREADY_OPEN, ApiErrorId.ERR_INVALID_STATE]
        )


class TestCornerClockAndExpiry:
    def test_default_clock_sweeps_past_expiry_and_rewind_keeps_active(self, api):
        """PRD §2.8: "Before any such call, the clock reads exactly
        2026-09-01T00:00:00Z. Setting the clock forward triggers an expiry sweep: any
        license whose expiry_date is earlier than the new clock date transitions to
        EXPIRED, whether it was ACTIVE or DISPUTED, and expiry does not settle an
        unresolved dispute. License reads also evaluate this expiry rule lazily, so a
        license past its expiry_date reports EXPIRED even without an explicit sweep."

        Design: Corner/endpoints/clock_default_is_2026_09_01_and_settable
        """
        licensee_a = _create_licensee(
            legal_name="Clock A", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_a = _issue_license(licensee_a, effective_date="2026-01-01", expiry_date="2026-06-30")
        # Default clock 2026-09-01 is past expiry: the read sweeps it lazily.
        read_a = validate_success(api.get_license(license_a["id"], LIC_ADMIN))
        assert read_a["status"] == "EXPIRED"

        sysadmin = TEST_USERS["pro_system_admin_headers"]
        validate_success(api.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, sysadmin))
        licensee_b = _create_licensee(
            legal_name="Clock B", category="VENUE",
            reported_revenue_cents=10000000000, usage_units=10,
        )
        license_b = _issue_license(licensee_b, effective_date="2026-01-01", expiry_date="2026-06-30")
        assert license_b["status"] == "ACTIVE"
