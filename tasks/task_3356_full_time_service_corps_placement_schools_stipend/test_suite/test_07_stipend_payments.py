"""Stipend payments: provisional vs final amount variants, segregation of
duties, the duplicate-period fence, the fiscal gate and its ordering behind
the state check, and pay/clawback cash conservation."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
    STIPEND_ADMIN_2_HEADERS,
)


def _site_with_active_member(api):
    site = fixtures.create_active_site(api)
    member = fixtures.create_active_member(api, site["id"])
    return site, member


class TestScheduling:
    def test_stipend_create_records_creator_and_provisional_fields(self, api):
        """PRD §3.7: "At scheduling the system records `created_by` from the
        caller's `X-User-ID`, computes `period_days` as the count of calendar
        days from `period_start` through `period_end` inclusive, and sets the
        provisional amount: `base_amount_cents` is the site's
        `annual_stipend_cents` divided across the 26 stipend periods of a
        service year, rounded half up to a whole cent."

        Design: Corner/endpoints/stipend_create_records_creator_and_provisional_fields
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        resp = api.create_stipend_payment(
            member["id"], factories.stipend_payment_payload("2026-09-01", "2026-09-14"), STIPEND_ADMIN_1_HEADERS
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        payment = resp.json()["data"]

        assert payment["status"] == "SCHEDULED"
        assert payment["created_by"] == "sa-1"
        assert payment.get("approved_by") is None
        # Provisional variant: round_half_up(1300000 / 26), blind to period
        # length and deductions.
        assert payment["base_amount_cents"] == 50_000
        assert payment["period_days"] == 14
        assert payment.get("final_gross_cents") is None
        assert payment.get("net_amount_cents") is None

    def test_duplicate_payment_period_rejected(self, api):
        """PRD §3.7: "Scheduling requires the member's `stipend_status` to be
        `ACTIVE` (else `ERR_MEMBER_NOT_ACTIVE`), and the `period_start` must
        be unique across that member's payments — a second payment opening on
        the same day is rejected with `ERR_DUPLICATE_PAYMENT_PERIOD`."

        Design: Corner/validations/duplicate_payment_period_rejected
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        fixtures.schedule_payment(api, member["id"], "2026-09-01", "2026-09-14")

        # Same member, same period_start — a different period_end still collides.
        blocked = api.create_stipend_payment(
            member["id"], factories.stipend_payment_payload("2026-09-01", "2026-09-21"), STIPEND_ADMIN_1_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_DUPLICATE_PAYMENT_PERIOD.value)

        _payments, meta = validate_paginated(
            api.list_member_stipend_payments(member["id"], STIPEND_ADMIN_1_HEADERS)
        )
        assert meta["total_count"] == 1


class TestApprovalVariants:
    def test_stipend_approve_by_creator_rejected(self, api):
        """PRD §2.1: "the operator who approves a stipend payment must be a
        different individual than the one who created it, and any attempt to
        self-approve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/stipend_approve_by_creator_rejected
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"])
        assert payment["created_by"] == "sa-1"

        blocked = api.transition_stipend_payment(
            payment["id"], {"to_status": "APPROVED", "deduction_cents": 0}, STIPEND_ADMIN_1_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        approved = fixtures.approve_payment(api, payment["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "sa-2"

    def test_stipend_provisional_base_computed_at_creation(self, api):
        """PRD §3.7: "The provisional base deliberately ignores the period's
        actual length — it assumes a standard 14-day period — and
        `final_gross_cents` and `net_amount_cents` remain null."

        Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_deduction
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"], "2026-09-01", "2026-09-14")

        # The provisional variant: round_half_up(1300000 / 26) = 50000, known
        # at creation before any deduction exists.
        assert payment["base_amount_cents"] == 50_000
        assert payment["status"] == "SCHEDULED"
        assert payment.get("final_gross_cents") is None
        assert payment.get("net_amount_cents") is None

    def test_stipend_final_variant_nets_deduction(self, api):
        """PRD §3.7: "For a non-14-day period or a nonzero deduction, these
        final values differ from the provisional base computed on identical
        period data."
        PRD §3.7: "`net_amount_cents` is that gross minus the
        `deduction_cents` supplied at approval (a non-negative amount
        defaulting to 0), floored at zero so a payment never nets negative."

        Design: Difficulty/dual_variant_calc/stipend_provisional_vs_final_deduction
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"], "2026-09-01", "2026-09-14")
        assert payment["base_amount_cents"] == 50_000

        approved = fixtures.approve_payment(api, payment["id"], deduction_cents=12_000)
        # Final variant on identical period data: round_half_up(50000 x 14 /
        # 14) = 50000 gross, then the 12000 deduction nets 38000.
        assert approved["final_gross_cents"] == 50_000
        assert approved["net_amount_cents"] == 38_000
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == "sa-2"

    def test_stipend_final_prorated_short_period(self, api):
        """PRD §3.7: "At approval the final variant is computed:
        `final_gross_cents` prorates the provisional base by the period's
        actual length — `base_amount_cents` multiplied by `period_days`,
        divided by the 14 days of a standard period, rounded half up — and
        `net_amount_cents` is that gross minus the `deduction_cents` supplied
        at approval (a non-negative amount defaulting to 0), floored at zero
        so a payment never nets negative."

        Design: Corner/calculations/stipend_final_prorated_short_period"""
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"], "2026-09-01", "2026-09-10")
        assert payment["base_amount_cents"] == 50_000  # provisional ignores length
        assert payment["period_days"] == 10

        approved = fixtures.approve_payment(api, payment["id"], deduction_cents=0)
        # round_half_up(50000 x 10 / 14) = round_half_up(35714.2857...) = 35714.
        assert approved["final_gross_cents"] == 35_714
        assert approved["net_amount_cents"] == 35_714


class TestFiscalGate:
    def test_stipend_pay_deficit_rejected(self, api):
        """PRD §3.7: "Disbursement — `APPROVED` to `PAID` — passes through the
        fiscal gate: the site's `funding_headroom_cents` must cover the
        payment's `net_amount_cents`, else the payment is rejected with
        `ERR_SITE_FUNDING_DEFICIT`."

        Design: Corner/validations/stipend_pay_deficit_rejected
        """
        fixtures.set_clock(api)
        site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"])
        fixtures.approve_payment(api, payment["id"], deduction_cents=0)

        # No funding received: headroom is 0 - 0 - 1300000 = -1300000 < 50000.
        blocked = api.transition_stipend_payment(payment["id"], {"to_status": "PAID"}, STIPEND_ADMIN_2_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_SITE_FUNDING_DEFICIT.value)

        payments = get_success_data(api.list_member_stipend_payments(member["id"], STIPEND_ADMIN_1_HEADERS))
        assert payments[0]["status"] == "APPROVED"
        assert fixtures.get_member(api, member["id"])["net_stipend_received_cents"] == 0

    def test_state_beats_fiscal_on_stipend_pay(self, api):
        """PRD §2.8: "After existence, state-level checks run: the OCC
        staleness comparison (`ERR_STALE_VERSION`) precedes the question of
        whether the target resource's current state permits the requested
        transition (`ERR_INVALID_STATE`)."
        PRD §2.8: "Business rules follow, layered as temporal windows first
        (service-date validity, the 30-day verification window, the backfill
        deadline, the 45-day report window), then referential gates (agreement
        active, data sharing signed, member active, member placed, award
        earned), then constraint checks (daily hour cap, fundraising cap,
        caseload size, caseload conflict, assignment overlap, team capacity,
        backfill budget, deploy staffing, duplicate payment period, completion
        hours), and finally the fiscal gate on stipend payment
        (`ERR_SITE_FUNDING_DEFICIT`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_stipend_pay
        """
        fixtures.set_clock(api)
        site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"])

        site_read = fixtures.get_site(api, site["id"])
        assert site_read["funding_posture"] == "DEFICIT"  # the fiscal gate would fail too

        # The payment is SCHEDULED — not a state from which PAID is legal. The
        # state error is reported, not the fiscal one.
        blocked = api.transition_stipend_payment(payment["id"], {"to_status": "PAID"}, STIPEND_ADMIN_2_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        payments = get_success_data(api.list_member_stipend_payments(member["id"], STIPEND_ADMIN_1_HEADERS))
        assert payments[0]["status"] == "SCHEDULED", "a rejected transition mutates nothing"

    def test_fiscal_gate_reachable_once_state_passes(self, api):
        """PRD §2.8: "Business rules follow, layered as temporal windows first
        (service-date validity, the 30-day verification window, the backfill
        deadline, the 45-day report window), then referential gates (agreement
        active, data sharing signed, member active, member placed, award
        earned), then constraint checks (daily hour cap, fundraising cap,
        caseload size, caseload conflict, assignment overlap, team capacity,
        backfill budget, deploy staffing, duplicate payment period, completion
        hours), and finally the fiscal gate on stipend payment
        (`ERR_SITE_FUNDING_DEFICIT`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_stipend_pay
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"])
        fixtures.approve_payment(api, payment["id"], deduction_cents=0)

        # With the state obstacle removed (APPROVED), the same PAID request now
        # reaches the fiscal layer and reports it instead.
        blocked = api.transition_stipend_payment(payment["id"], {"to_status": "PAID"}, STIPEND_ADMIN_2_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_SITE_FUNDING_DEFICIT.value)

        payments = get_success_data(api.list_member_stipend_payments(member["id"], STIPEND_ADMIN_1_HEADERS))
        assert payments[0]["status"] == "APPROVED"


class TestPayClawbackConservation:
    def _funded_approved_payment(self, api):
        """Site with 2000000 philanthropy received: headroom 700000, FUNDED."""
        fixtures.set_clock(api)
        site, member = _site_with_active_member(api)
        funded = validate_success(
            api.receive_funding(
                site["id"], {"funding_type": "PHILANTHROPY", "amount_cents": 2_000_000}, SITE_DIRECTOR_HEADERS
            )
        )
        assert funded["funding_posture"] == "FUNDED"
        assert funded["funding_headroom_cents"] == 700_000
        payment = fixtures.schedule_payment(api, member["id"])
        fixtures.approve_payment(api, payment["id"], deduction_cents=0)
        return site, member, payment

    def test_stipend_pay_moves_cash_forward(self, api):
        """PRD §3.7: "On payment, the site's `stipend_outlay_cents` rises by
        the net amount, the member's `net_stipend_received_cents` rises by the
        same amount, and the site's headroom and posture are recomputed."

        Design: Difficulty/compensating_invariant/stipend_pay_clawback_cash_conservation
        """
        site, member, payment = self._funded_approved_payment(api)

        paid = fixtures.pay_payment(api, payment["id"])
        assert paid["status"] == "PAID"

        site_paid = fixtures.get_site(api, site["id"])
        member_paid = fixtures.get_member(api, member["id"])
        # The conserved quantity: site outlay == member net after paying.
        assert site_paid["stipend_outlay_cents"] == 50_000
        assert member_paid["net_stipend_received_cents"] == 50_000
        assert site_paid["funding_headroom_cents"] == 650_000  # 700000 - 50000

    def test_stipend_clawback_restores_cash_exactly(self, api):
        """PRD §3.7: "Clawback — `PAID` to `CLAWED_BACK`, with a `reason`
        required (else `ERR_INVALID_REQUEST`) — is the exact compensating
        action: outlay and the member's net received each fall by the
        payment's net amount, headroom and posture recompute, and the reason
        is preserved in `decision_reason`."
        PRD §3.7: "Cash is conserved across pay and clawback: the pair returns
        both ledgers to their prior values."

        Design: Difficulty/compensating_invariant/stipend_pay_clawback_cash_conservation
        """
        site, member, payment = self._funded_approved_payment(api)
        fixtures.pay_payment(api, payment["id"])

        clawed = validate_success(
            api.transition_stipend_payment(
                payment["id"], {"to_status": "CLAWED_BACK", "reason": "overpayment"}, STIPEND_ADMIN_1_HEADERS
            )
        )
        assert clawed["status"] == "CLAWED_BACK"
        assert clawed["decision_reason"] == "overpayment"

        site_after = fixtures.get_site(api, site["id"])
        member_after = fixtures.get_member(api, member["id"])
        assert site_after["stipend_outlay_cents"] == 0
        assert member_after["net_stipend_received_cents"] == 0
        assert site_after["funding_headroom_cents"] == 700_000
        assert site_after["funding_posture"] == "FUNDED"


class TestSegregationAcrossRoles:
    def test_pm_cannot_approve_stipend(self, api):
        """PRD §2.1: "A `StipendAdministrator` administers living stipends and
        education awards; deliberate segregation of duties keeps this role
        away from hour verification and keeps a `ProgramManager` away from
        stipend approval."
        PRD §2.1: "Each endpoint admits a specific list of roles (enumerated
        in §4); a caller whose role is not on that list is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/pm_cannot_approve_stipend
        """
        fixtures.set_clock(api)
        _site, member = _site_with_active_member(api)
        payment = fixtures.schedule_payment(api, member["id"])

        blocked = api.transition_stipend_payment(
            payment["id"], {"to_status": "APPROVED", "deduction_cents": 0}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
