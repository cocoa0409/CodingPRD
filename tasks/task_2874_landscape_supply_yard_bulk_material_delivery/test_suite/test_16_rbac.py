"""Six roles, six disjoint grants, and the three separate ways a caller can be turned away."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import CENTS, assert_claim_case
from test_helpers.factories import (
    create_credit_adjustment_payload,
    create_delivery_truck_payload,
    create_material_payload,
    create_will_call_order_payload,
    decide_claim_payload,
    stage_next_payload,
)
from test_helpers.fixtures import (
    read_account,
    read_claim,
    seed_account,
    seed_catalogue,
    seed_claim,
    seed_delivered_load,
    seed_delivery_order,
    seed_truck,
    seed_will_call_order,
    seed_will_call_ticket,
)
from test_helpers.test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_manager_headers,
    make_dispatch_planner_headers,
    make_headers_for_role,
    make_yard_admin_headers,
    make_yard_loader_headers,
)

DEAD_CLAIM = "00000000-0000-0000-0000-00000000beef"
FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}


def _stone(sku: str, name: str, **overrides):
    """One aggregate profile at reference moisture, cloned per test."""
    profile = {
        "sku": sku,
        "name": name,
        "offered_forms": ["BULK"],
        "seasonal_category": "AGGREGATE",
        "density_lb_per_cubic_yard": 1000,
        "shrinkage_factor": 0.10,
        "moisture_pct": 15.0,
        "unit_bag_cubic_yards": 0.037,
        "prebuy_eligible": False,
    }
    profile.update(overrides)
    return profile


def _role_landscapes(api):
    """One confirmed will-call order with a queued ticket and a submitted short-load claim."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-R1", "Role Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api,
        business_name="Role Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_will_call_order(
        api, account, catalogue["material"]["id"], lines=(("BULK", 4.0),), confirm=True
    )
    ticket = seed_will_call_ticket(
        api, seeded["order"]["id"], account["id"], "2026-07-31T07:00:00.000Z"
    )
    claim = seed_claim(
        api,
        seeded["order"]["id"],
        account["id"],
        "SHORT_LOAD",
        1000,
        will_call_ticket_id=ticket["id"],
        description="Bucket count looked light.",
    )
    return {
        "material": catalogue["material"],
        "account": account,
        "order": seeded["order"],
        "ticket": ticket,
        "claim": claim,
    }


class TestEveryRoleOwnsItsExclusiveOperation:
    """Six calls, one per role, each on an endpoint that names only that role."""

    def test_each_of_the_six_grants_is_live_on_the_operation_only_it_may_run(self, api):
        """The catalogue, the credit desk, the fleet, the yard queue, claim review and order
        creation each answer to exactly one role, and all six answer.

        PRD 2.1: "A **`YardAdmin`** runs yard operations -- the material catalogue, the price
        book, stockpile intake and moisture readings, opening trade accounts, activating
        pre-buy contracts, forfeiting abandoned containers, and driving the yard's logical
        clock."

        PRD 2.1: "A **`CreditManager`** works the credit desk: it resets credit lines, invoices
        fulfilled orders, records payment, and issues the credit memos that settle approved
        claims; it never touches fulfilment."

        PRD 2.1: "A **`DispatchPlanner`** commissions trucks and runs the road: booking
        windows, dispatching, delivering, refusing, replanning and cancelling loads."

        PRD 2.1: "A **`YardLoader`** works the loading yard: staging the will-call queue,
        running the equipment-safety briefing, loading and releasing contractor vehicles, and
        receiving containers back."

        PRD 2.1: "A **`ClaimsAdjuster`** reviews damage and shortage claims, requests further
        information, and approves or denies them."

        PRD 2.1: "A **`Contractor`** is the buying customer: it opens material orders, adds
        lines to them, confirms them, issues will-call tickets, files claims and supplies
        information the adjuster asks for."

        PRD 3.1: "Either change recomputes `effective_density_lb_per_cubic_yard` and advances
        the material's `version`."

        PRD 3.7: "A `ClaimsAdjuster` takes a submitted claim up, transitioning it `SUBMITTED ->
        UNDER_REVIEW` and incrementing `review_round` by 1."

        Design: Corner/rbac/each_role_can_run_one_of_its_exclusive_operations
        """
        context = _role_landscapes(api)
        account_id = context["account"]["id"]

        wetter = validate_success(
            api.patch_material(
                context["material"]["id"], {"moisture_pct": 16.0}, headers=make_yard_admin_headers()
            ),
            200,
        )
        assert wetter["moisture_pct"] == pytest.approx(16.00, abs=CENTS)
        # 1000 * (1 + (16.0 - 15.0) / 100)
        assert wetter["effective_density_lb_per_cubic_yard"] == pytest.approx(1010.00, abs=CENTS)
        assert wetter["version"] == context["material"]["version"] + 1

        before = read_account(api, account_id)
        adjusted = validate_success(
            api.create_credit_adjustment(
                account_id,
                create_credit_adjustment_payload(6000000, before["version"], memo="Seasonal increase."),
                headers=make_credit_manager_headers(),
            ),
            200,
        )
        assert adjusted["credit_limit_cents"] == 6000000
        assert adjusted["version"] == before["version"] + 1

        truck = validate_success(
            api.create_delivery_truck(
                create_delivery_truck_payload(
                    truck_code="TND-R1",
                    axle_class="TANDEM",
                    max_payload_lb=40000,
                    bed_capacity_cubic_yards=12.0,
                    min_driveway_access_class="CLASS_B",
                ),
                headers=make_dispatch_planner_headers(),
            ),
            201,
        )
        assert truck["status"] == "AVAILABLE"

        staged = validate_success(
            api.stage_next_will_call_ticket(
                stage_next_payload("2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z"),
                headers=make_yard_loader_headers("loader-r1"),
            ),
            200,
        )
        assert staged["id"] == context["ticket"]["id"]
        assert staged["status"] == "STAGED"
        assert staged["staged_by_user_id"] == "loader-r1"

        reviewed = validate_success(
            api.start_review_claim_case(
                context["claim"]["id"], headers=make_claims_adjuster_headers("adjuster-r1")
            ),
            200,
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        assert reviewed["review_round"] == 1

        opened = validate_success(
            api.create_material_order(
                create_will_call_order_payload(account_id), headers=make_contractor_headers(account_id)
            ),
            201,
        )
        assert opened["fulfillment_status"] == "DRAFT"
        assert opened["fulfillment_mode"] == "WILL_CALL"


class TestCrossRoleAttemptsAreForbidden:
    """Authorisation sits above path existence, so the wrong role learns nothing at all."""

    def test_six_wrong_role_attempts_are_refused_and_nothing_is_written(self, api):
        """Each call names a role the endpoint does not list, and the refusal arrives before
        the path, the body or the target row is ever consulted.

        PRD 2.1: "A request whose role is well-formed but is not listed among the authorized
        roles for the endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD 2.8: "The ladder below is evaluated top to bottom on every request, and the first
        rung that fails produces the response; no later rung is consulted."

        PRD 2.8: "**Role authorization** -- the acting role appears in the called endpoint's
        authorized-role list in section 4, on every endpoint, else `ERR_UNAUTHORIZED` (403)."

        PRD 2.8: "**Path-parameter existence** -- every path segment resolves, checked left to
        right, on every endpoint carrying path parameters, else the matching 404 from the
        catalogue in section 2.4."

        Design: Corner/rbac/other_roles_exclusive_operations_are_rejected_with_403
        """
        account = seed_account(
            api,
            business_name="Forbidden Landscapes",
            credit_limit_cents=500000,
            po_required=False,
            driveway_protection_required=False,
        )
        account_id = account["id"]

        validate_error(
            api.create_material(
                create_material_payload(sku="AGG-R2", name="Forbidden Stone"),
                headers=make_headers_for_role("Contractor", "contractor-r2"),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_delivery_truck(
                create_delivery_truck_payload(
                    truck_code="TND-R2",
                    axle_class="TANDEM",
                    max_payload_lb=40000,
                    bed_capacity_cubic_yards=12.0,
                    min_driveway_access_class="CLASS_B",
                ),
                headers=make_yard_loader_headers("loader-r2"),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        # the claim id does not exist, yet rung 2 answers before rung 6 ever looks
        validate_error(
            api.start_review_claim_case(
                DEAD_CLAIM, headers=make_dispatch_planner_headers("planner-r2")
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_credit_adjustment(
                account_id,
                create_credit_adjustment_payload(900000, account["version"], memo="Not my desk."),
                headers=make_claims_adjuster_headers("adjuster-r2"),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_material_order(
                create_will_call_order_payload(account_id),
                headers=make_yard_admin_headers("admin-r2"),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.stage_next_will_call_ticket(
                stage_next_payload("2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z"),
                headers=make_credit_manager_headers("credit-r2"),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        # the refused adjustment never reached the account row
        untouched = read_account(api, account_id)
        assert untouched["credit_limit_cents"] == 500000
        assert untouched["version"] == account["version"]

        for lister, params in (
            (api.list_materials, {"limit": 10, "offset": 0}),
            (api.list_delivery_trucks, {"limit": 10, "offset": 0}),
            (api.list_material_orders, {"limit": 10, "offset": 0}),
            (api.list_will_call_tickets, {"limit": 10, "offset": 0}),
        ):
            rows, meta = validate_paginated(lister(headers=make_yard_admin_headers(), params=params))
            assert meta["total_count"] == 0
            assert rows == []


LIST_PAGE = {"limit": 10, "offset": 0}
NO_ROLE_HEADERS = {"X-User-ID": "admin-r3", "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": "YardAdmin", "Content-Type": "application/json"}
EMPTY_USER_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": "YardAdmin",
    "Content-Type": "application/json",
}


class TestUnauthenticatedRequests:
    """Authentication is the first rung, so a bad identity never reaches a payload."""

    def test_a_missing_header_an_empty_identity_and_an_undeclared_role_all_fail_first(self, api):
        """The same list read succeeds with a well-formed identity and is refused three ways
        without one, and a role outside the six is 401 rather than 403.

        PRD 2.1: "Both must be present and non-empty, and `X-User-Role` must be one of exactly
        six declared roles -- `Contractor`, `YardAdmin`, `CreditManager`, `DispatchPlanner`,
        `YardLoader`, `ClaimsAdjuster`."

        PRD 2.1: "A request missing either header, sending either as an empty value, or naming
        a role outside those six is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD 2.8: "**Header validity** -- `X-User-Role` and `X-User-ID` present and non-empty
        and the role one of the six declared roles, on every endpoint, else
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/unauthenticated_and_unknown_role_requests_are_rejected_with_401
        """
        rows, meta = validate_paginated(
            api.list_materials(headers=make_yard_admin_headers(), params=dict(LIST_PAGE))
        )
        assert meta["total_count"] == 0
        assert rows == []

        # the role header is absent entirely
        validate_error(
            api.list_materials(headers=NO_ROLE_HEADERS, params=dict(LIST_PAGE)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        # the identity header is absent entirely
        validate_error(
            api.list_materials(headers=NO_USER_HEADERS, params=dict(LIST_PAGE)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        # the identity header is present but empty
        validate_error(
            api.list_materials(headers=EMPTY_USER_HEADERS, params=dict(LIST_PAGE)),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        # YardManager is not one of the six declared roles, so this is 401 and not 403
        validate_error(
            api.create_material(
                create_material_payload(sku="AGG-R3", name="Unknown Role Stone"),
                headers=make_headers_for_role("YardManager", "manager-r3"),
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        after, after_meta = validate_paginated(
            api.list_materials(headers=make_yard_admin_headers(), params=dict(LIST_PAGE))
        )
        assert after_meta["total_count"] == 0
        assert after == []


def _two_scoped_accounts(api):
    """Two unrelated trade accounts, only one of which owns an order."""
    account_a = seed_account(
        api,
        business_name="Scope A",
        credit_limit_cents=500000,
        po_required=False,
        driveway_protection_required=False,
    )
    account_b = seed_account(
        api,
        business_name="Scope B",
        credit_limit_cents=500000,
        po_required=False,
        driveway_protection_required=False,
    )
    order_b = validate_success(
        api.create_material_order(
            create_will_call_order_payload(account_b["id"]),
            headers=make_contractor_headers(account_b["id"]),
        ),
        201,
    )
    return {"account_a": account_a, "account_b": account_b, "order_b": order_b}


class TestContractorAccountScope:
    """Contractor is a legitimate role on both reads; the block comes from whose row it is."""

    def test_a_stranger_is_refused_the_rows_the_owner_and_the_staff_read_freely(self, api):
        """The scope rung compares the acting identity against the row's account, so the same
        endpoint answers the owner and refuses the neighbour.

        PRD 2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting
        `ContractorAccount`; ownership checks on any resource that references a
        `ContractorAccount` compare the resource's account reference to `X-User-ID`."

        PRD 2.1: "A cross-account attempt is rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (HTTP
        403)."

        PRD 2.1: "When `X-User-Role` is `YardAdmin`, `CreditManager`, `DispatchPlanner`,
        `YardLoader` or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied
        to any persisted entity, and the server never compares it to any entity's `id`."

        PRD 2.8: "**Account scope** -- for a `Contractor`, `X-User-ID` matches the
        `contractor_account_id` reachable from the target resource, whether that target is an
        order, a purchase order, a pre-buy contract, a will-call ticket, a claim or a container
        return; this applies to every `Contractor`-callable endpoint, else
        `ERR_ACCOUNT_SCOPE_VIOLATION` (403)."

        Design: Corner/rbac/contractor_reading_another_accounts_rows_is_rejected_with_403
        """
        context = _two_scoped_accounts(api)
        stranger = make_contractor_headers(context["account_a"]["id"])
        owner = make_contractor_headers(context["account_b"]["id"])
        order_id = context["order_b"]["id"]

        validate_error(
            api.get_material_order(order_id, headers=stranger),
            ApiErrorId.ACCOUNT_SCOPE_VIOLATION.value,
            403,
        )
        validate_error(
            api.get_contractor_account(context["account_b"]["id"], headers=stranger),
            ApiErrorId.ACCOUNT_SCOPE_VIOLATION.value,
            403,
        )

        owned = validate_success(api.get_material_order(order_id, headers=owner), 200)
        assert owned["id"] == order_id
        assert owned["fulfillment_status"] == "DRAFT"

        # staff identities are opaque, so no scope comparison applies to them
        staff = validate_success(
            api.get_material_order(order_id, headers=make_credit_manager_headers("credit-r4")), 200
        )
        assert staff["id"] == order_id
        assert staff["fulfillment_status"] == "DRAFT"


def _duties_landscapes(api):
    """A delivered CLASS_A load run by planner-shared, with its claim already under review."""
    catalogue = seed_catalogue(
        api, material=_stone("AGG-R5", "Duties Stone"), price=FLAT_PRICE, lot=STANDARD_LOT
    )
    account = seed_account(
        api,
        business_name="Duties Landscapes",
        credit_limit_cents=5000000,
        po_required=False,
        driveway_protection_required=False,
    )
    seeded = seed_delivery_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BULK", 6.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=2.0,
        delivery_address="5 Duties Rd",
        confirm=True,
    )
    truck = seed_truck(
        api,
        truck_code="TRI-R5",
        axle_class="TRI_AXLE",
        max_payload_lb=60000,
        bed_capacity_cubic_yards=20.0,
        min_driveway_access_class="CLASS_A",
    )
    load = seed_delivered_load(
        api,
        seeded["order"]["id"],
        truck["id"],
        6.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        driveway_protection_used=False,
        spillage_cubic_yards=0.0,
        dispatcher_user_id="planner-shared",
    )
    claim = seed_claim(
        api,
        seeded["order"]["id"],
        account["id"],
        "DRIVEWAY_DAMAGE",
        20000,
        delivery_load_id=load["id"],
        under_review=True,
        adjuster_user_id="adjuster-clean",
        description="Cracked apron after the tri-axle turned in.",
    )
    return {"account": account, "order": seeded["order"], "load": load, "claim": claim}


class TestSegregationOfDuties:
    """The block is keyed on the identity, not the role: one adjuster is refused, another is not."""

    def test_the_planner_who_ran_the_truck_cannot_judge_the_claim_another_adjuster_approves(self, api):
        """Holding the adjuster role is not enough when the acting identity dispatched the load
        under complaint, and the identical decision lands for a clean identity.

        PRD 2.1: "In particular, the yard enforces segregation of duties on claim decisions:
        when a `ClaimsAdjuster` decides a claim that names a `delivery_load_id`, and that
        load's `dispatched_by_user_id` equals the deciding adjuster's `X-User-ID`, the decision
        is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD 2.8: "**Segregation of duties** -- on `POST /claim-cases/{claimCaseId}/decide`,
        when the claim carries a `delivery_load_id`, that load's `dispatched_by_user_id`
        differs from the acting `X-User-ID`, else `ERR_SEGREGATION_OF_DUTIES` (403)."

        PRD 3.7: "Both branches write the deciding adjuster's `X-User-ID` to
        `decided_by_user_id`, and both are blocked by segregation of duties: when the claim
        names a `delivery_load_id` whose `dispatched_by_user_id` equals the acting adjuster's
        `X-User-ID`, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

        PRD 3.7: "For a `DRIVEWAY_DAMAGE` claim the yard applies a
        one-hundred-and-fifty-dollar deductible, except that the deductible is **waived
        entirely** -- treated as zero -- when the claim names a `delivery_load_id` whose
        `driveway_protection_used` is false, because a crew that skipped the mats does not get
        to bill the contractor for the first hundred and fifty dollars of the consequence;
        `payable_cents` is then the `approved_amount_cents` minus the applicable deductible,
        floored at zero so it never goes negative."

        Design: Corner/rbac/same_user_cannot_dispatch_a_load_and_decide_its_claim
        """
        context = _duties_landscapes(api)
        claim_id = context["claim"]["id"]

        assert context["load"]["dispatched_by_user_id"] == "planner-shared"

        validate_error(
            api.decide_claim_case(
                claim_id,
                decide_claim_payload("APPROVE", 20000),
                headers=make_claims_adjuster_headers("planner-shared"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        held = read_claim(api, claim_id)
        assert held["status"] == "UNDER_REVIEW"
        assert held["decided_by_user_id"] is None
        assert held["approved_amount_cents"] is None

        decided = validate_success(
            api.decide_claim_case(
                claim_id,
                decide_claim_payload("APPROVE", 20000),
                headers=make_claims_adjuster_headers("adjuster-clean"),
            ),
            200,
        )
        assert_claim_case(decided)
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == "adjuster-clean"
        assert decided["approved_amount_cents"] == 20000
        # the mats were skipped, so the 15000 deductible is waived entirely
        assert decided["payable_cents"] == 20000


class TestSharedReadIsNotRoleFiltered:
    """The one detail read every declared role shares, taken by all six on the same row."""

    def test_all_six_roles_receive_the_identical_order_projection(self, api):
        """Six identities read one order and every response is the same row, with the
        contractor arm still passing its scope check.

        PRD 2.8: "**Role authorization** -- the acting role appears in the called endpoint's
        authorized-role list in section 4, on every endpoint, else `ERR_UNAUTHORIZED` (403)."

        PRD 2.1: "The authoritative role list for each endpoint is the "Authorized Role(s)"
        column of the endpoint table in section 4."

        PRD 3.4: "A new order begins with `fulfillment_status` `DRAFT` and `settlement_status`
        `UNBILLED`, with every money field at 0, with `final_total_cents` and `quote_locked_at`
        null, and with `paid_amount_cents` and `credit_memo_cents` at 0."

        Design: Corner/rbac/shared_read_operations_work_for_every_declared_role
        """
        account = seed_account(
            api,
            business_name="Shared Landscapes",
            credit_limit_cents=500000,
            po_required=False,
            driveway_protection_required=False,
        )
        account_id = account["id"]
        order = validate_success(
            api.create_material_order(
                create_will_call_order_payload(account_id),
                headers=make_contractor_headers(account_id),
            ),
            201,
        )
        order_id = order["id"]

        readers = (
            make_yard_admin_headers(),
            make_credit_manager_headers(),
            make_dispatch_planner_headers(),
            make_yard_loader_headers(),
            make_claims_adjuster_headers(),
            make_contractor_headers(account_id),
        )
        projections = []
        for headers in readers:
            seen = validate_success(api.get_material_order(order_id, headers=headers), 200)
            assert seen["id"] == order_id
            assert seen["fulfillment_mode"] == "WILL_CALL"
            assert seen["fulfillment_status"] == "DRAFT"
            assert seen["settlement_status"] == "UNBILLED"
            projections.append(seen)

        # the read is not role-filtered: every caller sees the identical projection
        for projection in projections[1:]:
            assert projection == projections[0]
