"""Cross-cutting complexity layers: optimistic concurrency on plan creation,
version increments on mutations, and the suspension cascade.

Queue B — corner design section ``cross_cutting_complexity_layers``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestPlanCreateOCC:
    def _setup_territory_with_entry(self, api):
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api)
        fx.add_target_entry(
            api,
            territory["id"],
            prescriber["id"],
            product["id"],
            manager,
            tier="C",
            planned_sample_units=10,
        )
        return territory, manager

    def test_stale_territory_version_rejected(self, api):
        """PRD section 2.7: "Creating a call plan for a territory requires the request
        body to carry expected_territory_version, the value of the Territory's
        version as last observed by the planner. ... if territory alignment has
        changed since the planner last observed it, the stale request is rejected
        with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_plan_create_with_stale_territory_version_rejected
        """
        territory, manager = self._setup_territory_with_entry(api)
        first = api.create_call_plan(
            f.create_call_plan_payload(territory["id"], territory["version"]),
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_success(first, expected_status=201)
        second = api.create_call_plan(
            f.create_call_plan_payload(
                territory["id"],
                territory["version"],  # stale: first create bumped it
                cycle_label="2026-Q4-B",
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)

    def test_current_territory_version_accepted_after_advance(self, api):
        """PRD section 3.3: "Plan creation increments the territory's version by
        one." — a planner who re-reads the territory can create again.

        Design: Corner/cross_cutting_complexity_layers/occ_plan_create_with_stale_territory_version_rejected
        """
        territory, manager = self._setup_territory_with_entry(api)
        first = fx.create_plan(
            api, territory["id"], territory["version"], manager
        )
        current = get_success_data(
            api.get_territory(
                territory["id"],
                headers=make_district_manager_headers(manager["id"]),
            )
        )
        assert current["version"] == territory["version"] + 1
        second = api.create_call_plan(
            f.create_call_plan_payload(
                territory["id"], current["version"], cycle_label="2026-Q4-B"
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_success(second, expected_status=201)


class TestLotVersionIncrements:
    def test_version_starts_at_one_on_receipt(self, api):
        """PRD section 2.4: "version is a system-managed integer beginning at 1 and
        incremented by exactly one on every mutation of the resource."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        product = fx.create_product(api)
        lot = fx.create_sample_lot(api, product["id"], quantity_received=50)
        assert lot["version"] == 1

    def test_issuance_and_transfer_request_each_increment(self, api):
        """PRD section 3.2: "Issuing units from a lot to a representative decrements
        quantity_available by the issued quantity and increments the lot's version by
        one" and PRD section 3.6: "On creation the transfer is REQUESTED ... and the
        lot's version increments by one."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
        """
        ctx = fx.setup_two_reps_with_lot(api, sender_issued=10, lot_quantity=50)
        after_issue = get_success_data(
            api.get_sample_lot(ctx["lot"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert after_issue["version"] == 2
        fx.request_transfer(api, ctx["sender"], ctx["receiver"], ctx["lot"], 2)
        after_transfer = get_success_data(
            api.get_sample_lot(ctx["lot"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert after_transfer["version"] == 3


class TestSuspensionCascade:
    def _setup_suspension_scenario(self, api):
        ctx = fx.setup_count_session_cast(
            api,
            custodian_issue_qty=100,
            lot_quantity=200,
            annual_max_units_per_prescriber=500,
        )
        # Give the custodian a published plan with one SCHEDULED future visit.
        prescriber = fx.create_eligible_prescriber(api)
        entry = fx.add_target_entry(
            api,
            ctx["t_custodian"]["id"],
            prescriber["id"],
            ctx["product"]["id"],
            ctx["manager"],
            tier="B",
            planned_sample_units=20,
        )
        territory = get_success_data(
            api.get_territory(
                ctx["t_custodian"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        plan = fx.create_plan(
            api, territory["id"], territory["version"], ctx["manager"]
        )
        fx.publish_plan(api, plan["id"], ctx["manager"])
        visit = fx.schedule_visit(
            api,
            plan["id"],
            entry["id"],
            ctx["custodian"],
            scheduled_start="2026-09-20T08:00:00Z",
            scheduled_end="2026-09-20T09:00:00Z",
        )
        session = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-10T00:00:00Z",
            window_end="2026-09-11T00:00:00Z",
        )
        # Counted 85 of expected 100 -> variance 15.00% -> SUSPENSION_REVIEW.
        fx.submit_full_count(
            api, session["id"], ctx["counter"], {ctx["lot"]["id"]: 85}
        )
        ctx["session"] = session
        ctx["visit"] = visit
        return ctx

    def test_reconcile_assigns_suspension_review_and_suspends(self, api):
        """PRD section 3.6: "at least 10.0 it is SUSPENSION_REVIEW" and "a tier of
        SUSPENSION_REVIEW sets it to SUSPENDED."

        Design: Corner/cross_cutting_complexity_layers/suspension_cascade_cancels_open_work_for_custodian
        """
        ctx = self._setup_suspension_scenario(api)
        session = fx.reconcile_session(api, ctx["session"]["id"], ctx["manager"])
        assert session["variance_pct"] == 15.00
        assert session["disciplinary_tier"] == "SUSPENSION_REVIEW"
        custodian = get_success_data(
            api.get_representative(
                ctx["custodian"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert custodian["compliance_standing"] == "SUSPENDED"

    def test_suspension_cancels_scheduled_visits(self, api):
        """PRD section 3.6: "at which point every still-SCHEDULED visit of the
        suspended custodian is automatically CANCELLED and every REQUESTED outbound
        transfer of theirs is automatically CANCELLED."

        Design: Corner/cross_cutting_complexity_layers/suspension_cascade_cancels_open_work_for_custodian
        """
        ctx = self._setup_suspension_scenario(api)
        fx.reconcile_session(api, ctx["session"]["id"], ctx["manager"])
        visit = get_success_data(
            api.get_call_visit(
                ctx["visit"]["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        assert visit["call_status"] == "CANCELLED"
