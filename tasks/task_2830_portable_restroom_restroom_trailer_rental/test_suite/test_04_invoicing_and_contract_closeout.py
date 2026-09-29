"""Line-by-line escalation, the two contract state dimensions and demobilization."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_contract_ledger,
    assert_quote_line_set,
    assert_route_density,
    fixtures as fx,
    lines_by_unit_class,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]


def _active_thirteen_unit_contract():
    """A SHOULDER / VERTICAL contract mobilized and ready to invoice."""
    env = fx.setup_quoted_contract(
        shape=fx.THIRTEEN_UNIT,
        legal_name="Ridgeline Concrete",
        site_label="Ridgeline Tower",
        authority_ref="PL-3001",
        authority_decision_ref="AD-3001",
    )
    assert env["contract"]["quoted_cents"] == 181500
    env["contract"] = fx.mobilize_contract(env["contract"]["id"])
    return env


class TestInvoiceEscalation:
    """Seasonal, phase and fuel percentages applied per line and rounded per line."""

    def test_01_each_line_is_escalated_and_rounded_on_its_own(self):
        """9.75 percent per line: 130500 -> 143224, 22500 -> 24694, 28500 -> 31279.

        PRD 3.9: "Add together three percentages: the seasonal escalation for the
        contract's `season_code` — 8.5 percent for `PEAK`, 3.25 percent for `SHOULDER`
        and nothing at all for `OFF` — the construction-phase escalation for the
        contract's `construction_phase` — nothing for `SITEWORK`, 4.75 percent for
        `VERTICAL`, 2.5 percent for `FINISHES` and nothing for `EVENT_NA`, which is
        what every event contract carries — and a flat fuel surcharge of 1.75 percent
        that applies to every contract regardless of season or phase."
        PRD 3.9: "for each line in that order compute `escalated_cents` as the line's
        `extended_cents` multiplied by one hundred plus the combined percentage,
        divided by 100, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/escalation_rounds_each_line_then_sums_not_sum_then_round
        """
        env = _active_thirteen_unit_contract()

        invoiced = fx.invoice_contract(env["contract"]["id"])
        assert invoiced["billing_state"] == "INVOICED"

        lines = lines_by_unit_class(fx.live_quote_lines(env["contract"]["id"]))
        assert lines["STANDARD_PORTABLE"]["extended_cents"] == 130500
        assert lines["STANDARD_PORTABLE"]["escalated_cents"] == 143224
        assert lines["ADA_PORTABLE"]["extended_cents"] == 22500
        assert lines["ADA_PORTABLE"]["escalated_cents"] == 24694
        assert lines["HANDWASH_STATION"]["extended_cents"] == 28500
        assert lines["HANDWASH_STATION"]["escalated_cents"] == 31279

    def test_02_the_subtotal_sums_the_rounded_lines_not_the_rounded_sum(self):
        """143224 + 24694 + 31279 is 199197; the collapsed order would report 199196.

        PRD 2.6: "Conversely, the invoice escalation rounds each line individually and
        only then sums the rounded lines; summing the unescalated lines, escalating
        once and rounding once is a different and incorrect total, because it can
        differ by up to one cent per line."
        PRD 3.9: "The contract's `invoice_subtotal_cents` is the sum of those
        already-rounded `escalated_cents` values."
        PRD 3.9: "Finally `net_billable_cents` is recomputed as
        `invoice_subtotal_cents` plus `charge_debits_cents` minus
        `credit_accrued_cents`."

        Design: Difficulty/combinatorial_formula/escalation_rounds_each_line_then_sums_not_sum_then_round
        """
        env = _active_thirteen_unit_contract()

        invoiced = validate_success(
            api_client.invoice_rental_contract(env["contract"]["id"], SALES)
        )
        assert invoiced["invoice_subtotal_cents"] == 199197
        assert invoiced["invoice_subtotal_cents"] != 199196
        assert invoiced["billing_state"] == "INVOICED"
        assert invoiced["fulfillment_state"] == "ACTIVE"
        assert_contract_ledger(
            invoiced,
            invoice_subtotal_cents=199197,
            charge_debits_cents=0,
            credit_accrued_cents=0,
            net_billable_cents=199197,
        )

        escalated = [
            line["escalated_cents"]
            for line in fx.live_quote_lines(env["contract"]["id"])
        ]
        assert sum(escalated) == 199197
        assert invoiced["quoted_cents"] == 181500


def _active_seven_unit_contract_with_one_unit_in_the_field():
    """An OFF / SITEWORK contract, one standard portable deployed, fulfillment ACTIVE."""
    env = fx.setup_active_contract_with_deployment(
        shape=fx.SEVEN_UNIT,
        asset_tag="SP-101",
        yard_code="YD-2",
        legal_name="Cascade Grading",
        site_label="Cascade Cut A",
        authority_ref="PL-5001",
        authority_decision_ref="AD-5001",
        account_overrides={"credit_terms_days": 15},
        site_overrides={"jurisdiction_code": "WA-KC-CITY"},
    )
    assert env["contract"]["quoted_cents"] == 91500
    return env


class TestParallelStateDimensions:
    """The billing dimension walks alone until the join condition fires."""

    def test_03_billing_walks_to_settled_while_fulfillment_stays_active(self):
        """Two billing hops, no fulfillment movement, subtotal 93102 at 1.75 percent.

        PRD 3.9: "A rental contract carries two independent state dimensions on the
        same row, and neither constrains the other's ordering."
        PRD 3.9: "The fulfillment dimension is `fulfillment_state` and it runs `DRAFT →
        QUOTED → ACTIVE → DEMOBILIZED`; the billing dimension is `billing_state` and it
        runs `UNBILLED → INVOICED → SETTLED`, with a rebilling loop `INVOICED →
        REBILL_REQUIRED → INVOICED` driven by the credit and charge cascades of §3.6
        and §3.8."
        PRD 3.9: "A contract may be invoiced while still mobilized in the field, or
        demobilized long before anyone pays."

        Design: Difficulty/non_linear_state_machine/contract_billing_and_fulfillment_dimensions_advance_independently
        """
        env = _active_seven_unit_contract_with_one_unit_in_the_field()
        contract_id = env["contract"]["id"]
        assert env["contract"]["fulfillment_state"] == "ACTIVE"
        assert env["contract"]["billing_state"] == "UNBILLED"

        invoiced = validate_success(
            api_client.invoice_rental_contract(contract_id, SALES)
        )
        assert invoiced["fulfillment_state"] == "ACTIVE"
        assert invoiced["billing_state"] == "INVOICED"
        assert invoiced["invoice_subtotal_cents"] == 93102
        assert invoiced["net_billable_cents"] == 93102

        settled = validate_success(
            api_client.settle_rental_contract_invoice(
                contract_id, ADMIN, {"payment_reference": "WIRE-7741"}
            )
        )
        assert settled["fulfillment_state"] == "ACTIVE"
        assert settled["billing_state"] == "SETTLED"
        assert settled["reconciled_cents"] == 0

    def test_04_demobilizing_an_already_settled_contract_writes_closed(self):
        """The join condition: fulfillment lands on CLOSED, not DEMOBILIZED.

        PRD 3.9: "`CLOSED` is the join of the two dimensions and the contract's only
        terminal state: it is written onto `fulfillment_state` the moment the
        fulfillment dimension has finished **and** `billing_state` has reached
        `SETTLED`, whichever of the two arrives second."
        PRD 3.9: "And if the contract's `billing_state` is already `SETTLED` at that
        moment, `fulfillment_state` is written `CLOSED` instead of `DEMOBILIZED` in the
        very same request."
        PRD 3.9: "Every deployment of the contract in `DEPLOYED` transitions `DEPLOYED
        → RETURNED` in `created_at` ascending order, each dragging its asset unit from
        `DEPLOYED` back to `IN_YARD` and recomputing the affected site's
        `deployed_unit_count`."

        Design: Difficulty/non_linear_state_machine/contract_billing_and_fulfillment_dimensions_advance_independently
        """
        env = _active_seven_unit_contract_with_one_unit_in_the_field()
        contract_id = env["contract"]["id"]

        fx.invoice_contract(contract_id)
        fx.settle_contract(contract_id, payment_reference="WIRE-7741")

        closed = validate_success(
            api_client.demobilize_rental_contract(
                contract_id, PLANNER, {"demobilization_note": "sitework finished"}
            )
        )
        assert closed["fulfillment_state"] == "CLOSED"
        assert closed["billing_state"] == "SETTLED"
        assert closed["reconciled_cents"] == 14500

        assert fx.read_deployment(env["deployment"]["id"])["state"] == "RETURNED"
        assert fx.read_asset_unit(env["asset"]["id"])["status"] == "IN_YARD"
        assert fx.read_site(env["site"]["id"])["deployed_unit_count"] == 0


class TestRefusedContractActions:
    """Every contract action probed from a state that declares no such transition."""

    def test_05_contract_actions_from_the_wrong_from_state_are_all_refused(self):
        """Activate, invoice, settle from DRAFT and demobilize from QUOTED all 409.

        PRD 2.11: "State-machine legality: the target row is in a state from which the
        requested transition is declared, and every same-entity or guard-entity state
        precondition of that transition holds — `ERR_INVALID_STATE_TRANSITION`."
        PRD 3.4: "Mobilization is the `SalesRep`'s act and it advances the contract's
        fulfillment dimension `QUOTED → ACTIVE`."
        PRD 3.9: "From `UNBILLED → INVOICED` the contract's `fulfillment_state` must be
        either `ACTIVE` or `DEMOBILIZED` — a `DRAFT` or merely `QUOTED` contract cannot
        be invoiced, and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`"
        PRD 3.9: "Demobilization is the `DispatchPlanner`'s closeout of the field work,
        advances `ACTIVE → DEMOBILIZED`, and accepts an optional
        `demobilization_note`."

        Design: Corner/state_machines/contract_actions_from_the_wrong_from_state_are_all_rejected
        """
        env = fx.setup_placeable_site(
            legal_name="Ashgrove Contracting",
            site_label="Ashgrove Lot",
            authority_ref="PL-10101",
            authority_decision_ref="AD-10101",
            site_overrides={"jurisdiction_code": "OK-OK-CITY"},
        )
        contract = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        assert contract["fulfillment_state"] == "DRAFT"
        assert contract["billing_state"] == "UNBILLED"
        assert contract["version"] == 1
        assert env["site"]["site_posture"] == "OPEN"
        assert env["account"]["billing_hold"] is False

        validate_error(
            api_client.activate_rental_contract(contract["id"], SALES),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        validate_error(
            api_client.invoice_rental_contract(contract["id"], SALES),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        validate_error(
            api_client.settle_rental_contract_invoice(
                contract["id"], ADMIN, {"payment_reference": "CHK-1"}
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        mid = fx.read_contract(contract["id"])
        assert mid["fulfillment_state"] == "DRAFT"
        assert mid["billing_state"] == "UNBILLED"
        assert mid["version"] == 1

        quoted = fx.quote_contract(contract)
        assert quoted["fulfillment_state"] == "QUOTED"
        assert quoted["version"] == 2

        validate_error(
            api_client.demobilize_rental_contract(contract["id"], PLANNER),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        end = fx.read_contract(contract["id"])
        assert end["fulfillment_state"] == "QUOTED"
        assert end["billing_state"] == "UNBILLED"
        assert end["version"] == 2

    def test_06_demobilizing_with_no_field_deployments_is_refused(self):
        """An empty reconciliation input set is 422; the twin with one deployment closes out.

        PRD 3.9: "It is refused unless the contract has at least one deployment in
        `DEPLOYED` or `RETURNED`: a contract whose iron never reached the site has
        nothing to reconcile, and the attempt is rejected with
        `ERR_RECONCILIATION_NO_DEPLOYMENTS` (HTTP 422)."
        PRD 2.11: "Reconciliation input-set non-emptiness —
        `ERR_RECONCILIATION_NO_DEPLOYMENTS`."

        Design: Corner/validations/demobilizing_a_contract_with_no_field_deployments_is_refused
        """
        env = fx.setup_placeable_site(
            legal_name="Gravelly Run Partners",
            site_label="Gravelly Run Pad",
            authority_ref="PL-11201",
            authority_decision_ref="AD-11201",
            site_overrides={"jurisdiction_code": "VA-HE-CITY"},
        )
        asset = fx.add_asset_unit("SP-1301", yard_code="YD-13")

        empty = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        fx.quote_contract(empty)
        activated = fx.mobilize_contract(empty["id"])
        assert activated["fulfillment_state"] == "ACTIVE"

        stocked = fx.raise_contract(env["account"]["id"], env["site"]["id"])
        fx.quote_contract(stocked)
        fx.commit_deployment(stocked["id"], asset["id"])
        fx.mobilize_contract(stocked["id"])

        validate_error(
            api_client.demobilize_rental_contract(
                empty["id"], PLANNER, {"demobilization_note": "nothing ever shipped"}
            ),
            "ERR_RECONCILIATION_NO_DEPLOYMENTS",
            422,
        )

        refused = fx.read_contract(empty["id"])
        assert refused["fulfillment_state"] == "ACTIVE"
        assert refused["reconciled_cents"] == 0
        assert refused["quoted_cents"] == 91500
        assert len(fx.live_quote_lines(empty["id"])) == 2

        closed_out = fx.demobilize_contract(stocked["id"])
        assert closed_out["fulfillment_state"] == "DEMOBILIZED"
        assert closed_out["reconciled_cents"] == 14500


class TestDemobilizationCascade:
    """One closeout call moves four child entities and the route roll-up."""

    def test_07_demobilize_returns_the_iron_terminates_schedules_and_cancels_visits(self):
        """Deployment, asset, schedule, visit and route all move; no credit is minted.

        PRD 3.9: "Every service schedule of the contract in `ACTIVE` or `SUSPENDED`
        transitions to `TERMINATED`, with the route-figure asymmetry described in §3.5."
        PRD 3.5: "A schedule terminated out of `ACTIVE` recomputes the route's
        `committed_units` and `density_planned_pct`, because its units are only now
        leaving the sum, and cancels its remaining `PLANNED` visits."
        PRD 3.5: "The word *frozen* is exact — a later re-quote that supersedes those
        lines, or a demobilization that replaces them, does not retroactively change an
        existing schedule's `units_on_route`."
        PRD 3.6: "Cancellation, by contrast, is never a missed service. A visit that
        leaves `PLANNED` for `CANCELLED` does so only as a consequence of its schedule
        leaving `ACTIVE` — through a hand suspension, a site-posture block, or a
        contract demobilization — and no credit is generated."

        Design: Corner/state_machines/demobilize_cascades_down_to_deployments_schedules_and_planned_visits
        """
        env = fx.setup_active_contract_with_deployment(
            shape=fx.SEVEN_UNIT,
            asset_tag="SP-401",
            yard_code="YD-4",
            legal_name="Harrow Vale Builders",
            site_label="Harrow Vale Phase 1",
            authority_ref="PL-9701",
            authority_decision_ref="AD-9701",
            site_overrides={"jurisdiction_code": "TN-DA-CITY"},
        )
        assert env["contract"]["quoted_cents"] == 91500

        route = fx.create_route(
            "RT-MON-41", truck_capacity_units=20, waste_capacity_gallons=3000
        )
        schedule = fx.attach_schedule(env["contract"]["id"], route["id"])
        assert schedule["units_on_route"] == 7
        visit = fx.plan_visit(schedule["id"], "2026-08-10", 480, 540)
        assert_route_density(
            fx.read_route(route["id"]), committed_units=7, density_planned_pct=35
        )

        demobilized = validate_success(
            api_client.demobilize_rental_contract(
                env["contract"]["id"],
                PLANNER,
                {"demobilization_note": "site handover complete"},
            )
        )
        assert demobilized["fulfillment_state"] == "DEMOBILIZED"
        assert demobilized["billing_state"] == "UNBILLED"
        assert demobilized["reconciled_cents"] == 14500

        assert fx.read_deployment(env["deployment"]["id"])["state"] == "RETURNED"
        assert fx.read_asset_unit(env["asset"]["id"])["status"] == "IN_YARD"
        assert fx.read_site(env["site"]["id"])["deployed_unit_count"] == 0

        terminated = fx.read_schedule(schedule["id"])
        assert terminated["state"] == "TERMINATED"
        assert terminated["units_on_route"] == 7

        cancelled = fx.read_visit(visit["id"])
        assert cancelled["state"] == "CANCELLED"
        assert cancelled["units_serviced"] == 0

        assert_route_density(
            fx.read_route(route["id"]), committed_units=0, density_planned_pct=0
        )
        assert fx.charges_for_contract(env["contract"]["id"]) == []

    def test_08_reconciled_lines_replace_the_provisional_set_at_closeout(self):
        """Demobilization supersedes the seven provisional units and emits one actual line.

        PRD 3.9: "What demobilization runs is the **reconciled** variant of the
        unit-mix calculation, and it differs from the provisional projection of §3.3 in
        both its inputs and its overlays."
        PRD 3.9: "First, every quote line of the contract that has not been superseded
        — provisional lines included — has `is_superseded` set to true."
        PRD 3.9: "Each line's `unit_rate_cents` is the same per-class term rate used by
        the projection — 14500, 22500, 9500, 78000 and 265000 cents respectively — and
        each `extended_cents` is again the exact product of `quantity` and
        `unit_rate_cents`."

        Design: Corner/state_machines/demobilize_cascades_down_to_deployments_schedules_and_planned_visits
        """
        env = fx.setup_active_contract_with_deployment(
            shape=fx.SEVEN_UNIT,
            asset_tag="SP-402",
            yard_code="YD-4",
            legal_name="Harrow Vale Civil",
            site_label="Harrow Vale Phase 2",
            authority_ref="PL-9702",
            authority_decision_ref="AD-9702",
            site_overrides={"jurisdiction_code": "TN-DA-CITY"},
        )

        before = fx.live_quote_lines(env["contract"]["id"])
        assert len(before) == 2

        fx.demobilize_contract(env["contract"]["id"])

        superseded = fx.superseded_quote_lines(env["contract"]["id"])
        assert len(superseded) == 2
        assert all(
            line["quote_variant"] == "PROVISIONAL" for line in superseded
        )

        assert_quote_line_set(
            fx.live_quote_lines(env["contract"]["id"]),
            [("STANDARD_PORTABLE", 1, 14500, 14500)],
            variant="RECONCILED",
        )


class TestContractListing:
    """Filtering narrows the population before the pagination window is applied."""

    def test_09_contract_list_filters_by_state_then_paginates(self):
        """Three contracts in three fulfillment states; filters drive total_count and has_more.

        PRD 3.3: "Contracts are listable and can be narrowed by `account_id`, by
        `site_id`, by `fulfillment_state` or by `billing_state`; the quote lines of one
        contract can be listed by reverse lookup and narrowed by `quote_variant` or by
        `is_superseded`."
        PRD 2.3: "`total_count` reports the number of rows matching the request's
        filters before the pagination window is applied, and `has_more` reports whether
        any matching row falls beyond that window."
        PRD 3.3: "A newly raised contract sits at `fulfillment_state` `DRAFT` and
        `billing_state` `UNBILLED`, with `quoted_cents`, `reconciled_cents`,
        `invoice_subtotal_cents`, `charge_debits_cents`, `credit_accrued_cents` and
        `net_billable_cents` all 0."

        Design: Corner/endpoints/contract_list_filters_by_fulfillment_state_and_paginates_independently
        """
        env = fx.setup_placeable_site(
            legal_name="Quillon Event Services",
            site_label="Quillon Fairgrounds",
            authority_ref="PL-11601",
            authority_decision_ref="AD-11601",
            account_overrides={"account_type": "EVENT", "credit_terms_days": 15},
            site_overrides={"jurisdiction_code": "IA-PO-CITY"},
        )
        account_id = env["account"]["id"]
        site_id = env["site"]["id"]

        def raise_event_row():
            return fx.raise_event_contract(
                account_id,
                site_id,
                headcount=40,
                event_duration_hours=6,
                service_frequency_per_week=3,
                season_code="OFF",
                ada_required=False,
                term_start="2026-08-03",
                term_end="2026-08-20",
            )

        draft = raise_event_row()
        assert draft["fulfillment_state"] == "DRAFT"
        assert draft["billing_state"] == "UNBILLED"

        quoted_only = raise_event_row()
        fx.quote_contract(quoted_only)

        activated = raise_event_row()
        fx.quote_contract(activated)
        fx.mobilize_contract(activated["id"])

        rows, meta = validate_paginated(
            api_client.list_rental_contracts(SALES, {"account_id": account_id})
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        quoted_rows, quoted_meta = validate_paginated(
            api_client.list_rental_contracts(
                SALES, {"account_id": account_id, "fulfillment_state": "QUOTED"}
            )
        )
        assert len(quoted_rows) == 1
        assert quoted_meta["total_count"] == 1
        assert quoted_rows[0]["id"] == quoted_only["id"]

        page_one, page_one_meta = validate_paginated(
            api_client.list_rental_contracts(
                SALES,
                {
                    "account_id": account_id,
                    "billing_state": "UNBILLED",
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(page_one) == 2
        assert page_one_meta["total_count"] == 3
        assert page_one_meta["has_more"] is True

        page_two, page_two_meta = validate_paginated(
            api_client.list_rental_contracts(
                SALES,
                {
                    "account_id": account_id,
                    "billing_state": "UNBILLED",
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(page_two) == 1
        assert page_two_meta["total_count"] == 3
        assert page_two_meta["has_more"] is False

        first_ids = {row["id"] for row in page_one}
        assert first_ids.isdisjoint({row["id"] for row in page_two})
        assert fx.read_contract(draft["id"])["fulfillment_state"] == "DRAFT"
