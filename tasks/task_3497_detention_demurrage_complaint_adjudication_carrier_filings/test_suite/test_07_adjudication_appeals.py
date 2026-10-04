"""Adjudication and appeals: the dual reparation variants, per-invoice
rounding, frozen-score-driven method selection, segregation of duties, the
appeal window, and reversal ledger compensation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_congestion_report_payload,
    file_complaint,
    file_tariff,
    issue_invoice,
    make_alj_headers,
    make_carrier,
    make_carrier_rep_headers,
    make_ombuds_officer_headers,
    make_shipper,
    make_shipper_rep_headers,
    mark_paid,
    publish_tariff,
    set_logical_clock,
    setup_adjudication_open,
    setup_carrier_shipper,
    setup_published_tariff,
    setup_standard_billing,
    setup_standard_complaint,
    validate_error,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _decide(complaint_id, judge_id="alj-1"):
    return validate_success(api_client.decide_complaint(
        complaint_id, make_alj_headers(judge_id)), 200)


# ---------------------------------------------------------------------------
# Dual-variant reparation award
# ---------------------------------------------------------------------------

def _oop_fluidity_env():
    """Carrier with PUBLISHED CALENDAR tariff (free 4, 15000/day); one PAID
    105000-cent invoice and one ISSUED 75000-cent invoice carrying holds;
    USLAX week 2026-08-31 at 572/672 occupancy; two complaints open under
    alj-1 with the clock at 2026-09-20."""
    env = setup_carrier_shipper(carrier_name="Delta Bay Carriers")
    cid = env["carrier"]["id"]
    sid = env["shipper"]["id"]
    tariff = file_tariff(cid, tariff_code="DD-STD-1", charge_scope="DEMURRAGE",
                         free_time_days=4, per_diem_rate_cents=15000)
    set_logical_clock("2026-09-03T00:00:00Z")
    publish_tariff(cid, tariff["id"])
    set_logical_clock("2026-09-15T00:00:00Z")
    inv_paid = issue_invoice(cid, sid, tariff_id=tariff["id"],
                             invoice_number="INV-OOP-1",
                             container_number="MSKU1000011", port_code="USLAX",
                             availability_date="2026-09-04T00:00:00Z",
                             return_date="2026-09-14T12:00:00Z",
                             last_accrual_date="2026-09-14T12:00:00Z")
    inv_unpaid = issue_invoice(cid, sid, tariff_id=tariff["id"],
                               invoice_number="INV-FLU-2",
                               container_number="MSKU1000012", port_code="USLAX",
                               availability_date="2026-09-04T00:00:00Z",
                               return_date="2026-09-12T12:00:00Z",
                               last_accrual_date="2026-09-12T12:00:00Z",
                               government_hold_days=2,
                               appointment_unavailable_days=1)
    mark_paid(inv_paid["id"], sid)
    for term, hours in (("TERM-A", 168), ("TERM-B", 168), ("TERM-C", 168),
                        ("TERM-D", 68)):
        validate_success(api_client.create_congestion_report(
            create_congestion_report_payload(
                port_code="USLAX", terminal_code=term,
                week_start="2026-08-31T00:00:00Z", berth_occupancy_hours=hours,
                gate_closures_hours=0, vessel_dwell_hours_avg=90.0),
            DOCKET), 201)
    set_logical_clock("2026-09-20T00:00:00Z")
    comp_clean = file_complaint(sid, cid, [inv_paid["id"]],
                                reparations_claimed_cents=200000)
    comp_burdened = file_complaint(sid, cid, [inv_paid["id"], inv_unpaid["id"]],
                                   reparations_claimed_cents=200000)
    for comp in (comp_clean, comp_burdened):
        validate_success(api_client.open_adjudication(
            comp["id"], make_alj_headers("alj-1")), 200)
    return env, comp_clean, comp_burdened


class TestReparationVariants:
    def test_out_of_pocket_excludes_unpaid_and_adds_interest(self):
        """PRD §3.7: "A score below 50 selects `FLUIDITY_WEIGHTED` — the charges
        presumptively failed to promote freight fluidity — while a score of 50
        or higher selects `OUT_OF_POCKET`. Under `OUT_OF_POCKET`, only subject
        invoices currently in `PAID` status contribute: each paid invoice
        contributes its current `amount_cents` plus interest of five percent of
        that amount, the interest rounded half up to a whole cent, while an
        invoice in any other status contributes nothing. Under
        `FLUIDITY_WEIGHTED`, every subject invoice contributes whether paid or
        not, each at 125 percent of its current `amount_cents`".
        PRD §3.7: "the award is the lesser of that sum and the complaint's
        `reparations_claimed_cents`".

        Design: Difficulty/dual_variant_calc/reparation_out_of_pocket_vs_fluidity_weighted_variants
        """
        _env, comp_clean, comp_burdened = _oop_fluidity_env()
        assert comp_clean["incentive_principle_score"] == 75, (
            "only the 572/672 >= 0.85 congestion deduction applies")
        assert comp_burdened["incentive_principle_score"] == 10, (
            "100 - 25 congestion x2 - 15x2 holds - 10x1 appointments")

        decided_clean = _decide(comp_clean["id"])
        assert decided_clean["reparation_method"] == "OUT_OF_POCKET"
        assert decided_clean["reparations_awarded_cents"] == 110250, (
            "105000 + round_half_up(105000 x 0.05) = 105000 + 5250")

        decided_burdened = _decide(comp_burdened["id"])
        assert decided_burdened["reparation_method"] == "FLUIDITY_WEIGHTED"
        assert decided_burdened["reparations_awarded_cents"] == 200000, (
            "131250 + 93750 = 225000 capped at reparations_claimed_cents")

    def test_reparation_decisions_accumulate_on_shipper_ledger(self):
        """PRD §3.7: "the shipper's `total_recovery_cents` grows by the award."
        PRD §3.1: "reparation awards add to it".

        Design: Difficulty/dual_variant_calc/reparation_out_of_pocket_vs_fluidity_weighted_variants
        """
        env, comp_clean, comp_burdened = _oop_fluidity_env()
        _decide(comp_clean["id"])
        _decide(comp_burdened["id"])
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 310250, (
            "110250 out-of-pocket + 200000 fluidity-weighted")


# ---------------------------------------------------------------------------
# Award/reversal ledger compensation
# ---------------------------------------------------------------------------

def _reversal_env():
    """One PAID 105000-cent invoice and a clean complaint (score 100,
    claimed 200000) in ADJUDICATION_OPEN under alj-1; clock 2026-09-20."""
    env = setup_published_tariff(
        tariff_overrides={"tariff_code": "DD-REV-1", "free_time_days": 4,
                          "per_diem_rate_cents": 15000},
        carrier_name="Reversal Carriers")
    cid = env["carrier"]["id"]
    sid = env["shipper"]["id"]
    set_logical_clock("2026-09-15T00:00:00Z")
    invoice = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                            invoice_number="INV-REV-1",
                            container_number="MSKU8000001",
                            availability_date="2026-09-04T00:00:00Z",
                            return_date="2026-09-14T12:00:00Z",
                            last_accrual_date="2026-09-14T12:00:00Z")
    mark_paid(invoice["id"], sid)
    set_logical_clock("2026-09-20T00:00:00Z")
    complaint = file_complaint(sid, cid, [invoice["id"]],
                               reparations_claimed_cents=200000)
    validate_success(api_client.open_adjudication(
        complaint["id"], make_alj_headers("alj-1")), 200)
    env["invoice"] = invoice
    env["complaint"] = complaint
    return env


class TestAwardReversalCompensation:
    def test_decision_credits_shipper_ledger(self):
        """PRD §3.7: "the shipper's `total_recovery_cents` grows by the award"
        and "`decided_at` is stamped from the logical clock, the
        `appeal_deadline` falls thirty days after the decision".

        Design: Difficulty/compensating_invariant/reparation_award_and_reversal_conserve_shipper_ledger
        """
        env = _reversal_env()
        before = api_client.get_shipper(
            env["shipper"]["id"], DOCKET).json()["data"]["total_recovery_cents"]
        assert before == 0
        decided = _decide(env["complaint"]["id"])
        assert decided["reparations_awarded_cents"] == 110250
        assert decided["decided_at"] == "2026-09-20T00:00:00Z"
        assert decided["appeal_deadline"] == "2026-10-20T00:00:00Z"
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 110250

    def test_appeal_reversal_claws_back_exact_award(self):
        """PRD §3.7: "Reversal lands it in `REVERSED`: the awarded amount is
        subtracted back out of the shipper's `total_recovery_cents`, and
        `reparations_awarded_cents` is reset to zero."

        Design: Difficulty/compensating_invariant/reparation_award_and_reversal_conserve_shipper_ledger
        """
        env = _reversal_env()
        _decide(env["complaint"]["id"])
        validate_success(api_client.appeal_complaint(
            env["complaint"]["id"],
            make_carrier_rep_headers(env["carrier"]["id"])), 200)
        reversed_ = validate_success(api_client.resolve_appeal(
            env["complaint"]["id"], {"decision": "REVERSE"}, ADMIN), 200)
        assert reversed_["complaint_status"] == "REVERSED"
        assert reversed_["reparations_awarded_cents"] == 0
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 0, (
            "the reversal debits exactly what the decision credited")


# ---------------------------------------------------------------------------
# Reparation precision, method boundary, input-set filtering
# ---------------------------------------------------------------------------

class TestReparationPrecision:
    def test_reparation_interest_rounds_per_invoice_half_up(self):
        """PRD §3.7: "each paid invoice contributes its current `amount_cents`
        plus interest of five percent of that amount, the interest rounded half
        up to a whole cent".
        PRD §2.6: "Where a calculation requires rounding, the method is always
        round half up".

        Design: Corner/calculations/reparation_interest_rounds_per_invoice_half_up
        """
        env = setup_carrier_shipper()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        tariff = file_tariff(cid, tariff_code="DD-ODD-1", charge_scope="DETENTION",
                             per_diem_rate_cents=10010)
        set_logical_clock("2026-09-03T00:00:00Z")
        publish_tariff(cid, tariff["id"])
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(cid, sid, tariff_id=tariff["id"],
                                invoice_number="INV-ODD-1",
                                container_number="MSKU9100004",
                                return_date="2026-09-07T00:00:00Z",
                                last_accrual_date="2026-09-07T00:00:00Z")
        assert invoice["amount_cents"] == 10010
        mark_paid(invoice["id"], sid)
        complaint = file_complaint(sid, cid, [invoice["id"]],
                                   reparations_claimed_cents=50000)
        validate_success(api_client.open_adjudication(
            complaint["id"], make_alj_headers("alj-1")), 200)
        decided = _decide(complaint["id"])
        assert decided["reparation_method"] == "OUT_OF_POCKET"
        # 10010 + round_half_up(10010 x 0.05 = 500.5) = 10010 + 501.
        assert decided["reparations_awarded_cents"] == 10511

    def test_incentive_score_ignores_congestion_reports_outside_the_accrual_window(self):
        """PRD §3.7: "the server gathers every weekly port congestion report
        whose `port_code` equals the invoice's `port_code` and whose reported
        week intersects the invoice's accrual footprint — concretely, reports
        whose `week_start` falls on or before the invoice's `last_accrual_date`
        while the seven-day week beginning at `week_start` extends past the
        invoice's `availability_date`."

        Design: Corner/calculations/incentive_score_ignores_congestion_reports_outside_the_accrual_window
        """
        env = setup_standard_billing()
        for term in ("TERM-W1", "TERM-W2", "TERM-W3", "TERM-W4"):
            validate_success(api_client.create_congestion_report(
                create_congestion_report_payload(
                    port_code="USNYC", terminal_code=term,
                    week_start="2026-10-12T00:00:00Z", berth_occupancy_hours=168,
                    vessel_dwell_hours_avg=200.0), DOCKET), 201)
        for term in ("TERM-X1", "TERM-X2", "TERM-X3", "TERM-X4"):
            validate_success(api_client.create_congestion_report(
                create_congestion_report_payload(
                    port_code="USSEA", terminal_code=term,
                    week_start="2026-09-07T00:00:00Z", berth_occupancy_hours=168,
                    vessel_dwell_hours_avg=200.0), DOCKET), 201)
        complaint = file_complaint(env["shipper"]["id"], env["carrier"]["id"],
                                   [env["invoice"]["id"]],
                                   reparations_claimed_cents=50000)
        assert complaint["incentive_principle_score"] == 100, (
            "the wrong-week USNYC set and the wrong-port USSEA set are both "
            "outside the input set even at ratio 1.0")

    def test_incentive_score_boundary_50_selects_out_of_pocket_45_selects_fluidity(self):
        """PRD §3.7: "A score below 50 selects `FLUIDITY_WEIGHTED` — the charges
        presumptively failed to promote freight fluidity — while a score of 50
        or higher selects `OUT_OF_POCKET`."
        PRD §3.7: "Days the container spent under government hold cost 15 points
        per day, counted up to a maximum of three days per invoice" and "Days on
        which no gate appointment was available cost 10 points per day, again
        capped at three days per invoice through `appointment_unavailable_days`."

        Design: Corner/calculations/incentive_score_boundary_50_selects_out_of_pocket_45_selects_fluidity
        """
        env = setup_published_tariff()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        set_logical_clock("2026-09-10T00:00:00Z")
        inv50 = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                              invoice_number="INV-S50",
                              container_number="MSKU9100005",
                              government_hold_days=2,
                              appointment_unavailable_days=2)
        inv45 = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                              invoice_number="INV-S45",
                              container_number="MSKU9100006",
                              government_hold_days=3,
                              appointment_unavailable_days=1)
        mark_paid(inv50["id"], sid)
        mark_paid(inv45["id"], sid)
        comp50 = file_complaint(sid, cid, [inv50["id"]],
                                reparations_claimed_cents=50000)
        comp45 = file_complaint(sid, cid, [inv45["id"]],
                                reparations_claimed_cents=50000)
        assert comp50["incentive_principle_score"] == 50
        assert comp45["incentive_principle_score"] == 45
        for comp in (comp50, comp45):
            validate_success(api_client.open_adjudication(
                comp["id"], make_alj_headers("alj-1")), 200)
        decided50 = _decide(comp50["id"])
        assert decided50["reparation_method"] == "OUT_OF_POCKET"
        assert decided50["reparations_awarded_cents"] == 10500
        decided45 = _decide(comp45["id"])
        assert decided45["reparation_method"] == "FLUIDITY_WEIGHTED"
        assert decided45["reparations_awarded_cents"] == 12500


# ---------------------------------------------------------------------------
# Adjudication gates, segregation, appeal window and branches
# ---------------------------------------------------------------------------

class TestAdjudicationGates:
    def test_decide_without_open_adjudication_returns_not_adjudicating(self):
        """PRD §3.7: "The decision belongs to the presiding judge alone — a
        different caller is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` — and
        only while the complaint stands in `ADJUDICATION_OPEN`, otherwise
        `ERR_COMPLAINT_NOT_ADJUDICATING` (HTTP 409)." PRD §2.7 orders the
        assigned-officer ownership check (rung 3) before the complaint
        from-state check (rung 8), first failure wins; on a DOCKETED
        complaint `presiding_judge_id` is unset, so any caller fails the
        officer check before the state gate is consulted.

        Design: Corner/state_machines/decide_without_open_adjudication_returns_not_adjudicating
        """
        env = setup_standard_complaint()
        resp = api_client.decide_complaint(env["complaint"]["id"],
                                           make_alj_headers("alj-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)
        after = api_client.get_complaint(env["complaint"]["id"], DOCKET).json()["data"]
        assert after["complaint_status"] == "DOCKETED"
        assert after["reparations_awarded_cents"] == 0

    def test_adjudicator_conflict_bars_former_ombuds_officer(self):
        """PRD §3.7: "the judge who opens adjudication must not be the officer
        who ran the complaint's most recent ombuds round, and a conflicting
        caller is rejected with `ERR_ADJUDICATOR_CONFLICT` (HTTP 403)."

        Design: Corner/rbac/adjudicator_conflict_bars_former_ombuds_officer
        """
        env = setup_standard_complaint()
        cid = env["complaint"]["id"]
        validate_success(api_client.refer_ombuds(
            cid, {"ombuds_officer_id": "om-7"}, DOCKET), 200)
        validate_success(api_client.close_ombuds(
            cid, {"outcome": "FAILED"}, make_ombuds_officer_headers("om-7")), 200)

        r1 = api_client.open_adjudication(cid, make_alj_headers("om-7"))
        validate_error(r1, ApiErrorId.ERR_ADJUDICATOR_CONFLICT)

        data = validate_success(api_client.open_adjudication(
            cid, make_alj_headers("alj-9")), 200)
        assert data["complaint_status"] == "ADJUDICATION_OPEN"
        assert data["presiding_judge_id"] == "alj-9"

    def test_appeal_and_resolve_appeal_from_wrong_states_rejected(self):
        """PRD §3.7: "Either party may appeal — the complainant shipper or the
        respondent carrier, and anyone else is rejected with
        `ERR_FORBIDDEN_RESOURCE_ACCESS` — while the complaint stands in
        `ADJUDICATION_DECIDED`, otherwise `ERR_APPEAL_NOT_ALLOWED` (HTTP 409)".
        PRD §3.7: "a complaint not standing in `APPEALED` is rejected with
        `ERR_APPEAL_NOT_ALLOWED`".

        Design: Corner/state_machines/appeal_and_resolve_appeal_from_wrong_states_rejected
        """
        env = setup_standard_billing()
        sid = env["shipper"]["id"]
        cid = env["carrier"]["id"]
        comp_a = file_complaint(sid, cid, [env["invoice"]["id"]],
                                reparations_claimed_cents=50000)
        comp_b = file_complaint(sid, cid, [env["invoice"]["id"]],
                                reparations_claimed_cents=40000)
        validate_success(api_client.open_adjudication(
            comp_a["id"], make_alj_headers("alj-1")), 200)
        validate_success(api_client.open_adjudication(
            comp_b["id"], make_alj_headers("alj-2")), 200)
        _decide(comp_b["id"], judge_id="alj-2")

        r1 = api_client.appeal_complaint(comp_a["id"],
                                         make_shipper_rep_headers(sid))
        validate_error(r1, ApiErrorId.ERR_APPEAL_NOT_ALLOWED)
        r2 = api_client.resolve_appeal(comp_b["id"], {"decision": "AFFIRM"}, ADMIN)
        validate_error(r2, ApiErrorId.ERR_APPEAL_NOT_ALLOWED)

        assert api_client.get_complaint(comp_a["id"], DOCKET).json()["data"][
            "complaint_status"] == "ADJUDICATION_OPEN"
        assert api_client.get_complaint(comp_b["id"], DOCKET).json()["data"][
            "complaint_status"] == "ADJUDICATION_DECIDED"

    def test_appeal_at_exact_deadline_accepted_one_second_late_rejected(self):
        """PRD §3.7: "while the logical clock remains on or before the
        `appeal_deadline`, otherwise `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422). A
        timely appeal moves the complaint to `APPEALED`."

        Design: Corner/validations/appeal_at_exact_deadline_accepted_one_second_late_rejected
        """
        env = setup_standard_billing()
        sid = env["shipper"]["id"]
        cid = env["carrier"]["id"]
        comp_x = file_complaint(sid, cid, [env["invoice"]["id"]],
                                reparations_claimed_cents=50000)
        comp_y = file_complaint(sid, cid, [env["invoice"]["id"]],
                                reparations_claimed_cents=40000)
        for comp in (comp_x, comp_y):
            validate_success(api_client.open_adjudication(
                comp["id"], make_alj_headers("alj-1")), 200)
        set_logical_clock("2026-10-05T12:00:00Z")
        _decide(comp_x["id"])
        _decide(comp_y["id"])

        set_logical_clock("2026-11-04T12:00:00Z")
        appealed = validate_success(api_client.appeal_complaint(
            comp_x["id"], make_shipper_rep_headers(sid)), 200)
        assert appealed["complaint_status"] == "APPEALED"

        set_logical_clock("2026-11-04T12:00:01Z")
        r2 = api_client.appeal_complaint(comp_y["id"], make_shipper_rep_headers(sid))
        validate_error(r2, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
        assert api_client.get_complaint(comp_y["id"], DOCKET).json()["data"][
            "complaint_status"] == "ADJUDICATION_DECIDED"

    def test_appeal_affirmed_reaches_final_and_award_stands(self):
        """PRD §3.7: "Affirmation lands the complaint in its terminal `FINAL`
        status with the award intact."
        PRD §3.7: appeal is allowed "while the complaint stands in
        `ADJUDICATION_DECIDED`, otherwise `ERR_APPEAL_NOT_ALLOWED` (HTTP 409)".

        Design: Corner/state_machines/appeal_affirmed_reaches_final_and_award_stands
        """
        env = setup_standard_complaint(mark_paid_first=True)
        validate_success(api_client.open_adjudication(
            env["complaint"]["id"], make_alj_headers("alj-1")), 200)
        decided = _decide(env["complaint"]["id"])
        assert decided["reparations_awarded_cents"] == 10500
        validate_success(api_client.appeal_complaint(
            env["complaint"]["id"],
            make_carrier_rep_headers(env["carrier"]["id"])), 200)
        final = validate_success(api_client.resolve_appeal(
            env["complaint"]["id"], {"decision": "AFFIRM"}, ADMIN), 200)
        assert final["complaint_status"] == "FINAL"
        assert final["reparations_awarded_cents"] == 10500
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 10500

        r = api_client.appeal_complaint(env["complaint"]["id"],
                                        make_carrier_rep_headers(env["carrier"]["id"]))
        validate_error(r, ApiErrorId.ERR_APPEAL_NOT_ALLOWED)


class TestOwnershipAndConsistency:
    def test_ownership_identity_mismatches_return_forbidden(self):
        """PRD §2.1: "when `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id`
        of the acting `CarrierOrganization`, and ownership checks on any resource
        that references a carrier compare the resource's carrier foreign-key
        field to `X-User-ID`".
        PRD §3.7: "Only the assigned officer may close the round: the caller's
        `X-User-ID` must equal the complaint's current `ombuds_officer_id`,
        otherwise the request is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS`
        (HTTP 403)."

        Design: Corner/rbac/ownership_identity_mismatches_return_forbidden
        """
        env = setup_published_tariff()
        carrier_b = make_carrier(org_type="VOCC", org_name="Interloper Lines")
        shipper2 = make_shipper(company_name="Stranger Shippers",
                                contact_email="ops@stranger.example")
        set_logical_clock("2026-09-10T00:00:00Z")
        invoice = issue_invoice(env["carrier"]["id"], env["shipper"]["id"],
                                tariff_id=env["tariff"]["id"])
        dispute = validate_success(api_client.create_dispute(
            invoice["id"], {"dispute_reason": "OTHER"},
            make_shipper_rep_headers(env["shipper"]["id"])), 201)
        complaint = file_complaint(env["shipper"]["id"], env["carrier"]["id"],
                                   [invoice["id"]], reparations_claimed_cents=50000)
        validate_success(api_client.refer_ombuds(
            complaint["id"], {"ombuds_officer_id": "om-1"}, DOCKET), 200)

        bad_carrier = make_carrier_rep_headers(carrier_b["id"])
        bad_shipper = make_shipper_rep_headers(shipper2["id"])
        base_invoice = {
            "invoice_number": "INV-STEAL-1", "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU9300001", "port_code": "USNYC",
            "availability_date": "2026-09-04T00:00:00Z",
            "return_date": "2026-09-08T00:00:00Z",
            "last_accrual_date": "2026-09-08T00:00:00Z",
        }
        validate_error(api_client.create_invoice(
            env["carrier"]["id"], base_invoice, bad_carrier),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)
        validate_error(api_client.respond_to_dispute(
            dispute["id"], {"resolution": "WAIVE"}, bad_carrier),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)
        validate_error(api_client.close_ombuds(
            complaint["id"], {"outcome": "FAILED"},
            make_ombuds_officer_headers("om-2")),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)
        validate_error(api_client.create_dispute(
            invoice["id"], {"dispute_reason": "OTHER"}, bad_shipper),
            ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)
        validate_error(api_client.mark_invoice_paid(invoice["id"], bad_shipper),
                       ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS)

        rows = api_client.list_disputes(invoice["id"], DOCKET).json()["data"]
        assert rows[0]["resolution"] == "PENDING"
        assert api_client.get_invoice(invoice["id"], DOCKET).json()["data"][
            "invoice_status"] == "DISPUTED"
        assert api_client.get_complaint(complaint["id"], DOCKET).json()["data"][
            "complaint_status"] == "OMBUDS"

    def test_mutations_are_visible_in_the_same_response(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.7: "The chosen method is recorded as `reparation_method`, the
        award as `reparations_awarded_cents`".

        Design: Corner/consistency_model/mutations_are_visible_in_the_same_response
        """
        env = setup_standard_complaint(mark_paid_first=True)
        validate_success(api_client.open_adjudication(
            env["complaint"]["id"], make_alj_headers("alj-1")), 200)
        decided = _decide(env["complaint"]["id"])
        assert decided["reparations_awarded_cents"] == 10500
        assert decided["complaint_status"] == "ADJUDICATION_DECIDED"
        shipper = api_client.get_shipper(env["shipper"]["id"], DOCKET).json()["data"]
        assert shipper["total_recovery_cents"] == 10500
