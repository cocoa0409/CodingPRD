"""Endpoint surfaces: a registry, an action, a derived read and a guarded create.

Covers the crew registry and its two independent filters of PRD §3.1 and §2.3,
the customer's accept action of PRD §3.3, the clock-sensitive corridor read of
PRD §3.4 and the phase-move capability of PRD §3.5 with its stale-version guard
from PRD §2.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_INVALID_PHASE_MOVE,
    ERR_QUOTE_STATE,
    ERR_STALE_VERSION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_envelope_meta,
    assert_freshly_created,
    assert_integer,
    ids_of,
)


def _page(response, expected_status=200):
    """A list response's rows and its ``meta`` block (PRD §2.3)."""
    rows = validate_success(response, expected_status=expected_status)
    body = response.json()
    assert body["response_type"] == "array", body
    assert isinstance(rows, list), body
    assert_envelope_meta(body)
    return rows, body["meta"]


def test_the_crew_registry_creates_reads_and_filters_on_two_axes(api):
    """PRD §3.1: "An **install crew** is registered by `PlatformAdmin` or
    `DispatchCoordinator` with a `crew_code`, its home yard's `depot_code`, a
    strictly positive `daily_capacity_hours` ... and a
    `certified_for_solid_screen` flag that defaults to false." PRD §2.3 lists both
    of the registry's filters and makes `total_count` the filtered total.

    Design: Corner/endpoints/crew_registry_create_read_and_filtered_list
    """
    FX.set_clock(api, C.CLOCK_AUG_01)

    plain = validate_success(
        api.create_crew(F.crew_payload(crew_code=C.CREW_A), U.DISPATCH_COORDINATOR),
        expected_status=201,
    )
    certified = validate_success(
        api.create_crew(
            F.crew_payload(crew_code=C.CREW_B, certified_for_solid_screen=True),
            U.PLATFORM_ADMIN,
        ),
        expected_status=201,
    )
    other_depot = validate_success(
        api.create_crew(
            F.crew_payload(
                crew_code="CRW-C", depot_code="DEP-2", daily_capacity_hours=8.0
            ),
            U.DISPATCH_COORDINATOR,
        ),
        expected_status=201,
    )

    for crew in (plain, certified, other_depot):
        assert_integer(crew["version"], 1, "version")
        assert_freshly_created(crew)
    assert plain["certified_for_solid_screen"] is False
    assert certified["certified_for_solid_screen"] is True

    read_back = validate_success(api.get_crew(certified["id"], U.DISPATCH_COORDINATOR))
    assert read_back["crew_code"] == C.CREW_B
    assert read_back["depot_code"] == C.DEPOT
    assert read_back["daily_capacity_hours"] == 12.0

    by_depot, depot_meta = _page(
        api.list_crews(U.DISPATCH_COORDINATOR, params={"depot_code": C.DEPOT})
    )
    assert_integer(depot_meta["total_count"], 2, "total_count")
    assert depot_meta["has_more"] is False
    assert ids_of(by_depot) == [plain["id"], certified["id"]]

    by_certification, cert_meta = _page(
        api.list_crews(
            U.DISPATCH_COORDINATOR, params={"certified_for_solid_screen": "true"}
        )
    )
    assert_integer(cert_meta["total_count"], 1, "total_count")
    assert ids_of(by_certification) == [certified["id"]]

    first_page, page_meta = _page(
        api.list_crews(
            U.DISPATCH_COORDINATOR,
            params={"depot_code": C.DEPOT, "limit": 1, "offset": 0},
        )
    )
    assert len(first_page) == 1, first_page
    assert_integer(page_meta["limit"], 1, "limit")
    assert_integer(page_meta["offset"], 0, "offset")
    # The total is the filtered total, not the three crews on file.
    assert_integer(page_meta["total_count"], 2, "total_count")
    assert page_meta["has_more"] is True
    assert ids_of(first_page) == [plain["id"]]


def test_the_accept_action_is_gated_on_issuance_and_records_the_signer(api):
    """PRD §3.3: acceptance is the `CustomerContact`'s only write and it moves an
    `ISSUED` quote to `ACCEPTED`; "a quote in any other status is
    `ERR_QUOTE_STATE`" at rung 9 of PRD §2.7, which fires before the signer is
    recorded.

    Design: Corner/endpoints/accept_action_records_the_signer_and_refuses_a_draft_quote
    """
    world = FX.seed_world(api)
    quote = FX.seed_quote(api, world["jobsite"]["id"], linear_feet=500)
    customer = U.make_customer_contact_headers(world["account"]["id"])

    assert quote["status"] == C.QUOTE_DRAFT
    assert_integer(quote["version"], 1, "version")
    assert quote["accepted_by_name"] is None

    validate_error(
        api.accept_quote(
            quote["id"], F.accept_payload(C.ACCEPTOR_CONSTRUCTION), customer
        ),
        ERR_QUOTE_STATE,
        409,
    )

    refused = FX.read_quote(api, quote["id"])
    assert refused["accepted_by_name"] is None
    assert_integer(refused["version"], 1, "version")
    assert refused["status"] == C.QUOTE_DRAFT

    issued = validate_success(api.issue_quote(quote["id"], U.ACCOUNT_MANAGER))
    assert issued["status"] == C.QUOTE_ISSUED
    assert_integer(issued["version"], 2, "version")

    accepted = validate_success(
        api.accept_quote(
            quote["id"], F.accept_payload(C.ACCEPTOR_CONSTRUCTION), customer
        )
    )
    assert accepted["status"] == C.QUOTE_ACCEPTED
    assert_integer(accepted["version"], 3, "version")
    assert accepted["accepted_by_name"] == C.ACCEPTOR_CONSTRUCTION

    # Neither transition re-priced anything.
    for stage in (quote, issued, accepted):
        assert_cents(
            stage["monthly_recurring_cents"], 27000, "monthly_recurring_cents"
        )
        assert_cents(stage["one_time_cents"], 78500, "one_time_cents")


def test_the_committed_corridor_footage_is_read_against_the_clock(api):
    """PRD §3.4: the corridor aggregate covers windows that intersect on the
    half-open rule of PRD §2.6, where "each of the two instants must be at or after
    `closure_start_utc` and strictly before `closure_end_utc`". The same approved
    application therefore reads 300 at the inclusive start and 0 at the exclusive
    end, and no read mutates anything (PRD §2.4).

    Design: Corner/endpoints/committed_closure_footage_is_read_against_the_clock
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Dock Street North",
            "address_line": "8 Dock Street",
            "site_condition": C.CONDITION_ASPHALT,
            "requires_sidewalk_closure": True,
        },
    )
    municipality_id = world["municipality"]["id"]
    permit = FX.seed_approved_permit(api, world["jobsite"]["id"], closure_linear_feet=300)
    assert permit["status"] == C.PERMIT_APPROVED

    readings = []
    for instant, expected in (
        (C.CLOCK_AUG_01, 0),
        ("2026-08-10T00:00:00Z", 300),
        ("2026-08-19T23:59:59Z", 300),
        ("2026-08-20T00:00:00Z", 0),
    ):
        FX.set_clock(api, instant)
        reading = FX.read_municipality(api, municipality_id)
        assert_integer(
            reading["committed_closure_linear_feet"],
            expected,
            f"committed_closure_linear_feet at {instant}",
        )
        readings.append(reading)
        held = FX.read_permit(api, permit["id"])
        assert held["status"] == C.PERMIT_APPROVED
        assert_integer(held["version"], permit["version"], "permit version")

    # The aggregate is derived, so reading it never advanced the jurisdiction's row.
    assert {reading["version"] for reading in readings} == {readings[0]["version"]}


def test_a_phase_move_checks_the_version_before_the_phase_and_leaves_the_phase_alone(api):
    """PRD §2.8: a stale `expected_contract_version` "is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and nothing is written" at rung 8, below
    rung 22 where "`phase_to` must lie between 1 and the jobsite's `phase_count`
    inclusive, and must differ from the contract's `current_phase`". PRD §3.6 moves
    `current_phase` only when the `RESET` visit is reported complete.

    Design: Corner/endpoints/reset_order_phase_gate_and_stale_contract_version
    """
    world = FX.seed_world(api, jobsite={"phase_count": 4})
    state = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]
    stale_version = state["contract"]["version"]

    mobilized = FX.read_contract(api, contract_id)
    fresh_version = mobilized["version"]
    assert fresh_version != stale_version, mobilized
    assert mobilized["lifecycle_status"] == C.LIFECYCLE_ACTIVE
    assert_integer(mobilized["current_phase"], 1, "current_phase")

    # Rung 8 answers even though phase 2 would have been a legal destination.
    validate_error(
        api.create_reset_order(
            contract_id,
            F.reset_order_payload(
                stale_version, 500, 2, scheduled_start_utc="2026-08-06T08:00:00Z"
            ),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_STALE_VERSION,
        412,
    )

    # Re-setting to the phase the fence already occupies.
    validate_error(
        api.create_reset_order(
            contract_id,
            F.reset_order_payload(
                fresh_version, 500, 1, scheduled_start_utc="2026-08-06T08:00:00Z"
            ),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_INVALID_PHASE_MOVE,
        409,
    )

    # A phase the jobsite does not have.
    validate_error(
        api.create_reset_order(
            contract_id,
            F.reset_order_payload(
                fresh_version, 500, 5, scheduled_start_utc="2026-08-06T08:00:00Z"
            ),
            U.DISPATCH_COORDINATOR,
        ),
        ERR_INVALID_PHASE_MOVE,
        409,
    )

    # None of the three refusals wrote anything, so the token is still current.
    assert_integer(
        FX.read_contract(api, contract_id)["version"], fresh_version, "version"
    )

    reset = validate_success(
        api.create_reset_order(
            contract_id,
            F.reset_order_payload(
                fresh_version, 500, 2, scheduled_start_utc="2026-08-06T08:00:00Z"
            ),
            U.DISPATCH_COORDINATOR,
        ),
        expected_status=201,
    )

    assert reset["work_order_type"] == C.WO_RESET
    assert reset["status"] == C.WO_PLANNED
    assert_integer(reset["ordered_linear_feet"], 500, "ordered_linear_feet")
    assert_integer(reset["phase_from"], 1, "phase_from")
    assert_integer(reset["phase_to"], 2, "phase_to")

    after = FX.read_contract(api, contract_id)
    assert_integer(after["current_phase"], 1, "current_phase")
    assert_integer(after["deployed_linear_feet"], 500, "deployed_linear_feet")
