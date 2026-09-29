"""Creating a route and keeping its money straight.

A route is the root of everything else in this system, so its birth defaults and
its budget ledger are worth pinning down on their own. The ledger has exactly one
invariant — authorized equals committed plus available — and every operation that
touches money has to leave it standing.
"""

from test_helpers import fixtures as fx, validate_error, validate_success
from test_helpers.assertions import assert_budget_invariant
from test_helpers.factories import (
    budget_adjustment_payload,
    create_route_payload,
    make_ready_item,
)

_HARBOR_LOOP = {
    "name": "Harbor Loop",
    "topology_objective": "RING_CLOSURE",
    "target_in_service_date": "2027-03-01",
    "budget_authorized_cents": 250000000,
}


def test_route_create_returns_every_declared_field_at_its_birth_default(
    api, engineer_headers
):
    """The four inputs are echoed and the eleven derived fields are all seeded.

    PRD: "The route is born in `PLANNING` with `segment_count` and
    `design_total_length_feet` at zero, `total_preliminary_cost_cents` and
    `total_bid_ready_cost_cents` at zero, `budget_committed_cents` at zero and
    `budget_available_cents` equal to the authorized figure, `scope_locked_at`
    null, and both complexity indices — `planned_complexity_index` and
    `live_complexity_index` — null."

    Design: Corner/entities/route_creation_returns_all_declared_fields_with_defaults
    """
    fx.set_clock("2026-08-10T00:00:00Z")

    route = validate_success(
        api.create_route(create_route_payload(**_HARBOR_LOOP), headers=engineer_headers), 201
    )
    assert route["name"] == "Harbor Loop"
    assert route["topology_objective"] == "RING_CLOSURE"
    assert route["target_in_service_date"] == "2027-03-01"
    assert route["status"] == "PLANNING"
    assert route["scope_locked_at"] is None
    assert route["budget_authorized_cents"] == 250000000
    assert route["budget_committed_cents"] == 0
    assert route["budget_available_cents"] == 250000000
    assert route["segment_count"] == 0
    assert route["design_total_length_feet"] == 0
    assert route["total_preliminary_cost_cents"] == 0
    assert route["total_bid_ready_cost_cents"] == 0
    assert route["planned_complexity_index"] is None
    assert route["live_complexity_index"] is None
    assert route["id"]
    assert route["created_at"] == "2026-08-10T00:00:00Z"
    assert route["updated_at"] == "2026-08-10T00:00:00Z"
    assert route["version"] == 1
    assert_budget_invariant(route)


def test_reading_a_route_returns_the_stored_row_without_bumping_its_version(
    api, engineer_headers, coordinator_headers
):
    """A GET is not a mutation, so the version counter must stand still.

    PRD: "`version` is an integer that begins at 1 on creation and increments by
    exactly 1 on every mutation of that record — again including mutations confined
    to computed rollups, and including mutations applied by a cascade rather than
    by a direct request against that record."

    Design: Corner/entities/route_detail_get_returns_the_stored_row_unchanged
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    created = validate_success(
        api.create_route(create_route_payload(**_HARBOR_LOOP), headers=engineer_headers), 201
    )

    read = validate_success(api.get_route(created["id"], headers=coordinator_headers))
    assert read["id"] == created["id"]
    assert read["name"] == "Harbor Loop"
    assert read["budget_available_cents"] == 250000000
    assert read["created_at"] == "2026-08-10T00:00:00Z"
    assert read["version"] == created["version"]

    again = validate_success(api.get_route(created["id"], headers=coordinator_headers))
    assert again["version"] == created["version"]
    assert again["updated_at"] == created["updated_at"]


def test_a_client_supplied_status_is_an_unknown_field_and_the_route_is_not_created(
    api, engineer_headers
):
    """Status is system-owned, so naming it in the body is a shape fault.

    PRD: "**Body shape** — every required field present; no unknown field; every
    enum value inside its declared set; every integer inside its declared
    constraint; dates parseable as `YYYY-MM-DD`; instants parseable as ISO 8601
    UTC"

    Design: Corner/entities/route_system_fields_are_server_minted_and_a_status_input_is_rejected
    """
    fx.set_clock("2026-08-10T00:00:00Z")

    rejected = api.create_route(
        create_route_payload(status="CONSTRUCTION_READY", **_HARBOR_LOOP),
        headers=engineer_headers,
    )
    validate_error(rejected, "ERR_INVALID_REQUEST", 400)
    assert "api_request_id" in rejected.json()["meta"]
    assert "api_request_timestamp" in rejected.json()["meta"]

    clean = api.create_route(create_route_payload(**_HARBOR_LOOP), headers=engineer_headers)
    route = validate_success(clean, 201)
    assert route["status"] == "PLANNING"
    assert route["created_at"] == "2026-08-10T00:00:00Z"
    assert route["updated_at"] == "2026-08-10T00:00:00Z"
    assert route["version"] == 1
    assert isinstance(route["id"], str) and route["id"] != ""
    assert "api_request_id" in clean.json()["meta"]
    assert "api_request_timestamp" in clean.json()["meta"]


# ---------------------------------------------------------------------------
# The budget ledger
# ---------------------------------------------------------------------------

_HARBOR_LOOP_SMALL_PURSE = dict(_HARBOR_LOOP, budget_authorized_cents=1000000)

_TIGHT_BUDGET_SPUR = {
    "name": "Tight Budget Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 165984,
}

_DOCK_STREET = {
    "sequence_index": 1,
    "street_name": "Dock Street",
    "municipality_code": "MUN-014",
    "length_feet": 400,
    "terrain_class": "URBAN_PAVED",
    "planned_work_start_on": "2026-09-15",
    "planned_work_end_on": "2026-09-20",
    "existing_conduit_available": False,
}

_MUNICIPAL_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "MUNICIPAL_LIGHT",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}

_TELCO_POLE = {
    "pole_tag": "P-001",
    "pole_owner": "TELCO",
    "condition_grade": "B",
    "available_vertical_clearance_in": 45,
    "existing_attachment_count": 2,
}


def _estimate_on_a_fresh_route(route_spec, pole, pole_owner, items, owner_note, owner):
    """One walked Dock Street segment carrying a single MAKE_READY_ESTIMATED application."""

    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(**route_spec)
    segment = fx.create_segment(route["id"], **_DOCK_STREET)
    fx.accepted_walkout(
        segment["id"],
        [pole],
        walked_on="2026-08-11",
        obstruction_count=0,
        conduit_available_confirmed=False,
        surveyor_note="pole serviceable, guying needed",
    )
    application = fx.create_pole_application(
        segment["id"], pole_owner=pole_owner, pole_count=4
    )
    fx.submit_pole_application(application["id"])
    estimated = fx.owner_respond(
        application["id"], "ESTIMATED", list(items), headers=owner, owner_note=owner_note
    )
    return {
        "route_id": route["id"],
        "segment_id": segment["id"],
        "application_id": application["id"],
        "application": estimated,
    }


def _guying_estimate_that_exactly_fills_the_purse(owner):
    """Two down guys on a municipal-light pole, priced to the last cent of the purse."""

    return _estimate_on_a_fresh_route(
        _TIGHT_BUDGET_SPUR,
        _MUNICIPAL_POLE,
        "MUNICIPAL_LIGHT",
        [make_ready_item("P-001", "GUYING", 2)],
        "two down guys",
        owner,
    )


def test_raising_the_authorization_flows_straight_into_the_available_balance(
    api, admin_headers, engineer_headers
):
    """A signed positive delta lands on authorized and available, not on committed.

    PRD: "The delta is added to `budget_authorized_cents`, the committed and
    available figures are re-derived so the invariant continues to hold, and the
    route's `version` increments."

    Design: Corner/endpoints/budget_adjustment_raises_the_authorization_and_recomputes_available
    """
    fx.set_clock("2026-08-10T00:00:00Z")
    route = fx.create_route(headers=engineer_headers, **_HARBOR_LOOP_SMALL_PURSE)
    assert route["budget_authorized_cents"] == 1000000
    assert route["budget_available_cents"] == 1000000

    raised = validate_success(
        api.adjust_route_budget(
            route["id"],
            budget_adjustment_payload(250000, reason="supplemental make-ready allowance"),
            headers=admin_headers,
        )
    )
    assert raised["budget_authorized_cents"] == 1250000
    assert raised["budget_available_cents"] == 1250000
    assert raised["budget_committed_cents"] == 0
    assert raised["version"] == route["version"] + 1
    assert_budget_invariant(raised)

    returned = validate_success(
        api.adjust_route_budget(
            route["id"],
            budget_adjustment_payload(-250000, reason="allowance returned to the program"),
            headers=admin_headers,
        )
    )
    assert returned["budget_authorized_cents"] == 1000000
    assert returned["budget_available_cents"] == 1000000
    assert returned["budget_committed_cents"] == 0
    assert returned["version"] == raised["version"] + 1
    assert_budget_invariant(returned)


def test_a_grant_that_exactly_consumes_the_authorization_is_allowed(
    api, coordinator_headers, owner_municipal_headers
):
    """An exact fit drives the available balance to zero and is still accepted.

    PRD: "The rejection is strict — a cost strictly greater than the available
    balance is refused with `ERR_BUDGET_EXCEEDED`, and an exact fit that drives
    `budget_available_cents` to precisely zero is allowed."

    Design: Corner/calculations/budget_ledger_accepts_a_make_ready_grant_that_exactly_consumes_the_authorization
    """
    built = _guying_estimate_that_exactly_fills_the_purse(owner_municipal_headers)
    estimated = built["application"]
    assert estimated["make_ready_items_subtotal_cents"] == 148200, (
        "156,000 cents of guying at the municipal-light multiplier of 9,500 basis points"
    )
    assert estimated["make_ready_admin_fee_bp"] == 1200
    assert estimated["make_ready_admin_fee_cents"] == 17784
    assert estimated["make_ready_cost_cents"] == 165984
    assert estimated["make_ready_days"] == 53

    granted = validate_success(
        api.accept_make_ready(built["application_id"], headers=coordinator_headers)
    )
    assert granted["status"] == "GRANTED"
    assert granted["committed"] is True

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 165984
    assert route["budget_available_cents"] == 0
    assert route["budget_authorized_cents"] == 165984
    assert_budget_invariant(route)

    rows = validate_success(
        api.list_make_ready_items(built["application_id"], headers=coordinator_headers)
    )
    assert len(rows) == 1
    assert rows[0]["work_class"] == "GUYING"
    assert rows[0]["quantity"] == 2
    assert rows[0]["unit_cost_cents"] == 78000
    assert rows[0]["extended_cost_cents"] == 148200
    assert rows[0]["lead_days"] == 45

    segment = fx.read_segment(built["segment_id"])
    assert segment["bid_ready_cost_cents"] is None, (
        "no construction method has been selected on this segment yet"
    )


def test_accepting_an_estimate_answers_with_the_ledger_already_recomputed(
    api, coordinator_headers, owner_headers
):
    """The acceptance response carries the commitment, and the next read agrees.

    PRD: "Except where a specific narrative in section 3 says otherwise, a write
    returns the created or modified resource in the envelope's `data` field; the
    clock-setting capability instead returns an object carrying `current_utc`."

    Design: Corner/consistency_model/budget_ledger_is_visible_in_the_accept_make_ready_response
    """
    built = _estimate_on_a_fresh_route(
        _HARBOR_LOOP_SMALL_PURSE,
        _TELCO_POLE,
        "TELCO",
        [make_ready_item("P-001", "TRANSFER", 1)],
        "one transfer",
        owner_headers,
    )
    estimated = built["application"]
    assert estimated["make_ready_items_subtotal_cents"] == 42500, (
        "the telco multiplier of 10,000 basis points leaves the schedule price alone"
    )
    assert estimated["make_ready_admin_fee_cents"] == 5100
    assert estimated["make_ready_cost_cents"] == 47600

    granted = validate_success(
        api.accept_make_ready(built["application_id"], headers=coordinator_headers)
    )
    assert granted["status"] == "GRANTED"
    assert granted["committed"] is True
    assert granted["make_ready_cost_cents"] == 47600

    route = fx.read_route(built["route_id"])
    assert route["budget_committed_cents"] == 47600
    assert route["budget_available_cents"] == 952400
    assert route["budget_authorized_cents"] == 1000000
    assert_budget_invariant(route)


def test_deauthorizing_money_already_committed_to_a_grant_is_refused(
    api, admin_headers, coordinator_headers, owner_municipal_headers
):
    """A single cent below the committed total is already too far.

    PRD: "A reduction that would drive `budget_authorized_cents` below the route's
    current `budget_committed_cents` is refused with `ERR_BUDGET_EXCEEDED` — money
    already committed to granted attachments cannot be de-authorized underneath
    them."

    Design: Corner/validations/budget_adjustment_below_the_committed_total_returns_budget_exceeded
    """
    built = _guying_estimate_that_exactly_fills_the_purse(owner_municipal_headers)
    fx.accept_make_ready(built["application_id"], headers=coordinator_headers)
    before = fx.read_route(built["route_id"])
    assert before["budget_committed_cents"] == 165984
    assert before["budget_available_cents"] == 0

    refusal = api.adjust_route_budget(
        built["route_id"],
        budget_adjustment_payload(-1, reason="trim one cent"),
        headers=admin_headers,
    )
    validate_error(refusal, "ERR_BUDGET_EXCEEDED", 402)

    unchanged = fx.read_route(built["route_id"])
    assert unchanged["budget_authorized_cents"] == 165984
    assert unchanged["budget_committed_cents"] == 165984
    assert unchanged["budget_available_cents"] == 0
    assert unchanged["version"] == before["version"]
    assert_budget_invariant(unchanged)

    raised = validate_success(
        api.adjust_route_budget(
            built["route_id"],
            budget_adjustment_payload(100000, reason="supplemental authorization"),
            headers=admin_headers,
        )
    )
    assert raised["budget_authorized_cents"] == 265984
    assert raised["budget_committed_cents"] == 165984
    assert raised["budget_available_cents"] == 100000
    assert_budget_invariant(raised)
