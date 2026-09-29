"""Missed service: the pinned credit calculation, its cascade, its waive and the re-run."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_charge_event,
    assert_route_density,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]


class TestMissedServiceCreditAmount:
    """The credit reads the planned density as it stood before the transition."""

    def test_01_the_credit_uses_the_pre_transition_planned_density_tier(self):
        """A route at 65 percent planned density credits 62413, not the thin-route 65946.

        PRD 3.6: "**First**, take a snapshot of the route's `density_planned_pct`
        *before* the visit's state is written — the planned figure, not the realized one,
        and its pre-transition value."
        PRD 3.6: "**Second**, look up the surcharge tier by walking three declared tiers
        in order and taking the first whose ceiling is greater than or equal to the
        snapshot: a snapshot at or below 40 percent draws a 12 percent surcharge, a
        snapshot above 40 but at or below 75 percent draws 6 percent, and a snapshot
        above 75 but at or below 100 percent draws no surcharge."
        PRD 3.6: "Only after the credit has been persisted does the service recompute the
        route's `density_realized_pct`."

        Design: Difficulty/combinatorial_formula/missed_credit_pinned_pre_transition_density_resolves_circularity
        """
        env = fx.setup_scheduled_contract(
            shape=fx.THIRTEEN_UNIT,
            route_code="RT-MON-20",
            truck_capacity_units=20,
            waste_capacity_gallons=1800,
            legal_name="Summit Sitework",
            site_label="Summit Pad 4",
            authority_ref="PL-4001",
            authority_decision_ref="AD-4001",
            site_overrides={
                "jurisdiction_code": "CA-SD-CITY",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        assert env["contract"]["quoted_cents"] == 181500
        assert_route_density(
            env["route"], committed_units=13, density_planned_pct=65
        )

        visit = fx.plan_visit(env["schedule"]["id"], "2026-08-10", 480, 540)
        missed = fx.mark_visit_missed(visit["id"], "truck breakdown")
        assert missed["state"] == "MISSED"

        credit = fx.missed_service_credit_for_contract(env["contract"]["id"])
        assert_charge_event(credit)
        assert credit["charge_kind"] == "MISSED_SERVICE_CREDIT"
        assert credit["state"] == "ASSESSED"
        assert credit["amount_cents"] == 62413
        assert credit["amount_cents"] != 65946
        assert credit["assessed_by_user_id"] == "SYSTEM"
        assert credit["source_visit_id"] == visit["id"]

        contract = fx.read_contract(env["contract"]["id"])
        assert contract["credit_accrued_cents"] == 62413

        route = fx.read_route(env["route"]["id"])
        assert_route_density(
            route, committed_units=13, density_planned_pct=65, density_realized_pct=0
        )
        assert route["last_run_date"] is None

    def test_02_a_thin_route_draws_the_twelve_percent_tier_on_the_same_unit_mix(self):
        """The identical 13-unit contract on a 40-unit truck credits 65946 instead.

        PRD 3.6: "**Second**, look up the surcharge tier by walking three declared tiers
        in order and taking the first whose ceiling is greater than or equal to the
        snapshot: a snapshot at or below 40 percent draws a 12 percent surcharge, a
        snapshot above 40 but at or below 75 percent draws 6 percent, and a snapshot
        above 75 but at or below 100 percent draws no surcharge."
        PRD 3.6: "**Fourth**, apply the density surcharge to that base by multiplying it
        by one hundred plus the surcharge percentage, dividing by 100, and rounding half
        up to whole cents."
        PRD 3.6: "**Fifth**, take 115 percent of that rounded per-visit charge — we
        credit a missed stop at more than its own cost, because a missed pump-out costs
        the customer more than it saves us — by multiplying by 115, dividing by 100 and
        rounding half up again."

        Design: Difficulty/combinatorial_formula/missed_credit_pinned_pre_transition_density_resolves_circularity
        """
        env = fx.setup_scheduled_contract(
            shape=fx.THIRTEEN_UNIT,
            route_code="RT-MON-41",
            truck_capacity_units=40,
            legal_name="Summit Sitework",
            site_label="Summit Pad 4",
            authority_ref="PL-4001",
            authority_decision_ref="AD-4001",
            site_overrides={
                "jurisdiction_code": "CA-SD-CITY",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        assert_route_density(
            env["route"], committed_units=13, density_planned_pct=32
        )

        visit = fx.plan_visit(env["schedule"]["id"], "2026-08-10", 480, 540)
        fx.mark_visit_missed(visit["id"], "truck breakdown")

        credit = fx.missed_service_credit_for_contract(env["contract"]["id"])
        assert credit["amount_cents"] == 65946
        assert credit["amount_cents"] != 62413
        assert fx.read_contract(env["contract"]["id"])["credit_accrued_cents"] == 65946


def _invoiced_contract_with_a_missed_visit():
    """A 13-unit contract invoiced to 199197, then one planned stop declared missed."""
    return fx.setup_missed_visit_credit(
        invoice_first=True,
        shape=fx.THIRTEEN_UNIT,
        truck_capacity_units=20,
        legal_name="Cedarbrook Structures",
        site_label="Cedarbrook Deck",
        authority_ref="PL-4101",
        authority_decision_ref="AD-4101",
        site_overrides={
            "jurisdiction_code": "CA-SD-CITY",
            "gate_open_minute": 360,
            "gate_close_minute": 1080,
            "max_truck_length_ft": 40,
        },
    )


class TestMissedServiceCascade:
    """Four hops: charge row, contract figures, account balance, then the hold."""

    def test_03_the_credit_walks_charge_then_contract_then_account_then_hold(self):
        """One missed stop rewrites the charge, the contract, the balance and the hold.

        PRD 3.6: "A charge event is created with `charge_kind` `MISSED_SERVICE_CREDIT`
        and `state` `ASSESSED`, bound to the schedule's contract through `contract_id`,
        pointing back at the missed visit through `source_visit_id`, with
        `assessed_by_user_id` set to the literal string `SYSTEM` and `assessed_at` set to
        the logical clock's current instant."
        PRD 3.6: "The contract's `credit_accrued_cents` and `net_billable_cents` are
        recomputed, and if that contract's `billing_state` is `INVOICED` it transitions
        `INVOICED → REBILL_REQUIRED`."
        PRD 3.6: "The owning account's `open_credit_balance_cents` is recomputed as the
        sum of `amount_cents` over every missed-service-credit charge in `state`
        `ASSESSED` or `UPHELD` across every contract of that account."
        PRD 3.6: "The account's `billing_hold` is set to true when
        `open_credit_balance_cents` is greater than or equal to 60000 cents — six hundred
        dollars of unapplied credit is where our credit team wants the brakes applied —
        and to false otherwise."

        Design: Difficulty/transitive_cascade/missed_visit_credit_cascades_charge_contract_account_then_blocks_rebill
        """
        env = _invoiced_contract_with_a_missed_visit()

        before = env["contract_at_invoice"]
        assert before["invoice_subtotal_cents"] == 199197
        assert before["billing_state"] == "INVOICED"
        assert before["net_billable_cents"] == 199197

        assert env["visit"]["state"] == "MISSED"

        credit = env["credit"]
        assert credit["amount_cents"] == 62413
        assert credit["state"] == "ASSESSED"
        assert credit["assessed_by_user_id"] == "SYSTEM"
        assert credit["source_visit_id"] == env["visit"]["id"]

        contract = env["contract"]
        assert contract["credit_accrued_cents"] == 62413
        assert contract["billing_state"] == "REBILL_REQUIRED"
        assert contract["charge_debits_cents"] == 0
        assert contract["net_billable_cents"] == 136784
        assert contract["net_billable_cents"] == 199197 + 0 - 62413

        assert env["account"]["open_credit_balance_cents"] == 62413
        assert env["account"]["billing_hold"] is True

        assert_route_density(
            env["route"], committed_units=13, density_planned_pct=65,
            density_realized_pct=0,
        )

    def test_04_the_hold_from_the_last_hop_refuses_the_rebill(self):
        """The contract wants re-invoicing but the account's hold makes it payment-required.

        PRD 3.9: "From `REBILL_REQUIRED → INVOICED`, which is how a contract recovers
        after a credit or charge landed on an already-issued invoice, the only additional
        requirement is that at least one non-superseded quote line still exists."
        PRD 3.9: "Either way the owning account's `billing_hold` must be false, or the
        attempt is refused with `ERR_ACCOUNT_BILLING_HOLD`: an account sitting on six
        hundred dollars of unapplied credit does not get another invoice until the credit
        is cleared."

        Design: Difficulty/transitive_cascade/missed_visit_credit_cascades_charge_contract_account_then_blocks_rebill
        """
        env = _invoiced_contract_with_a_missed_visit()
        assert env["contract"]["billing_state"] == "REBILL_REQUIRED"
        assert env["account"]["billing_hold"] is True

        validate_error(
            api_client.invoice_rental_contract(env["contract"]["id"], SALES),
            "ERR_ACCOUNT_BILLING_HOLD",
            402,
        )

        after = fx.read_contract(env["contract"]["id"])
        assert after["billing_state"] == "REBILL_REQUIRED"
        assert after["net_billable_cents"] == 136784
        assert fx.read_account(env["account"]["id"])["billing_hold"] is True


class TestWaivingTheCredit:
    """Waiving the credit returns the money exactly and leaves the audit trace behind."""

    def test_05_the_waive_restores_the_balance_and_the_hold_to_the_cent(self):
        """Balance, hold, credit_accrued and net_billable all come back to their pre-values.

        PRD 3.8: "From `ASSESSED → WAIVED`, three compensations run in order: the
        contract's `charge_debits_cents`, `credit_accrued_cents` and
        `net_billable_cents` are recomputed with this charge excluded; then, caused by
        that contract change, the account's `open_credit_balance_cents` is recomputed and
        its `billing_hold` re-evaluated against the sixty-thousand-cent threshold"
        PRD 3.6: "Credits in `DISPUTED` or `WAIVED` are excluded, and damage, tip-over
        and relocation charges never enter this balance at all."

        Design: Difficulty/compensating_invariant/waiving_the_missed_service_credit_restores_the_account_credit_balance_exactly
        """
        env = _invoiced_contract_with_a_missed_visit()
        before = env["contract_at_invoice"]
        assert before["credit_accrued_cents"] == 0
        assert before["net_billable_cents"] == 199197
        assert env["account"]["open_credit_balance_cents"] == 62413
        assert env["account"]["billing_hold"] is True

        waived = fx.waive_charge(env["credit"]["id"])
        assert waived["state"] == "WAIVED"
        assert waived["amount_cents"] == 62413
        assert waived["resolved_by_user_id"] == "officer-2"

        account = fx.read_account(env["account"]["id"])
        assert account["open_credit_balance_cents"] == 0
        assert account["billing_hold"] is False

        contract = fx.read_contract(env["contract"]["id"])
        assert contract["credit_accrued_cents"] == before["credit_accrued_cents"] == 0
        assert contract["net_billable_cents"] == before["net_billable_cents"] == 199197

    def test_06_the_waive_leaves_the_billing_flag_and_the_missed_visit_where_they_are(self):
        """billing_state stays REBILL_REQUIRED and the visit stays MISSED; the rebill now passes.

        PRD 3.8: "An `INVOICED` contract flips to `REBILL_REQUIRED`."
        PRD 3.9: "From `REBILL_REQUIRED → INVOICED`, which is how a contract recovers
        after a credit or charge landed on an already-issued invoice, the only additional
        requirement is that at least one non-superseded quote line still exists."
        PRD 3.6: "Both paths write the supplied `missed_reason` onto the visit, both
        leave `units_serviced` at 0, and both run the identical four-hop credit cascade
        described below."

        Design: Difficulty/compensating_invariant/waiving_the_missed_service_credit_restores_the_account_credit_balance_exactly
        """
        env = _invoiced_contract_with_a_missed_visit()
        fx.waive_charge(env["credit"]["id"])

        contract = fx.read_contract(env["contract"]["id"])
        assert contract["billing_state"] == "REBILL_REQUIRED"

        visit = fx.read_visit(env["visit"]["id"])
        assert visit["state"] == "MISSED"
        assert visit["units_serviced"] == 0
        assert visit["missed_reason"] is not None

        assert_route_density(
            fx.read_route(env["route"]["id"]),
            committed_units=13, density_planned_pct=65, density_realized_pct=0,
        )

        rebilled = validate_success(
            api_client.invoice_rental_contract(env["contract"]["id"], SALES)
        )
        assert rebilled["billing_state"] == "INVOICED"
        assert rebilled["invoice_subtotal_cents"] == 199197
        assert rebilled["net_billable_cents"] == 199197


class TestRerunBooking:
    """The make-good visit points back at the stop it replaces."""

    def test_07_the_rerun_is_reachable_through_the_reverse_lookup(self):
        """A booked re-run is a RERUN child of the missed visit and keeps the credit intact.

        PRD 3.6: "Success creates a brand-new visit with `visit_kind` `RERUN` in `state`
        `PLANNED`, carrying the same `schedule_id` and `route_id` as the original, with
        `rerun_of_visit_id` pointing at the missed visit it replaces, `scheduled_date`
        set to the supplied `rerun_date`, and the supplied window."
        PRD 3.6: "Booking the make-good advances the original visit `MISSED →
        RERUN_SCHEDULED`, which is terminal for that row."
        PRD 3.6: "Crucially, booking a re-run neither creates a second credit nor
        reverses the first: the customer keeps the credit for the stop we missed, and the
        re-run is our own cost of recovery."

        Design: Corner/entities/service_visit_rerun_of_visit_id_reverse_lookup_returns_the_linked_rerun
        """
        env = fx.setup_missed_visit_credit(
            shape=fx.THIRTEEN_UNIT,
            truck_capacity_units=20,
            legal_name="Marrowfield Builders",
            site_label="Marrowfield Pad",
            authority_ref="PL-4201",
            authority_decision_ref="AD-4201",
            site_overrides={
                "jurisdiction_code": "CA-SD-CITY",
                "gate_open_minute": 360,
                "gate_close_minute": 1080,
                "max_truck_length_ft": 40,
            },
        )
        original = env["visit"]
        assert original["state"] == "MISSED"
        assert original["rerun_of_visit_id"] is None
        assert env["credit"]["amount_cents"] == 62413

        rerun = fx.book_rerun(original["id"], "2026-08-17", 480, 540)
        assert rerun["visit_kind"] == "RERUN"
        assert rerun["state"] == "PLANNED"
        assert rerun["rerun_of_visit_id"] == original["id"]
        assert rerun["schedule_id"] == env["schedule"]["id"]
        assert rerun["route_id"] == env["route"]["id"]
        assert rerun["scheduled_date"] == "2026-08-17"

        children, meta = validate_paginated(
            api_client.list_service_visits(
                PLANNER, {"rerun_of_visit_id": original["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(children) == 1
        assert children[0]["id"] == rerun["id"]

        assert fx.read_visit(original["id"])["state"] == "RERUN_SCHEDULED"
        assert (
            fx.read_contract(env["contract"]["id"])["credit_accrued_cents"] == 62413
        )
        assert len(fx.charges_for_contract(env["contract"]["id"])) == 1
