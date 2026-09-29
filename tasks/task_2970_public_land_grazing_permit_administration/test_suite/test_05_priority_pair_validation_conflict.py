"""Requests that violate two checks at once: only the lower-numbered check may answer."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_pct,
    make_officer_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    allotment_with_pasture,
    create_closure_order,
    create_permit,
    get_allotment,
    get_permit,
    issue_permit,
    lift_closure_order,
    permittee_with_base_property,
)


def _masked_capacity_setup():
    """A 1200-AUM allotment and a PENDING_REVIEW 1200-AUM permit whose 1500-AUM base
    property qualifies it, so an instruction asking for 1500 AUMs breaks both the permit
    state gate and the capacity gate at once."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=1200,
                                  required_pasture_rotation_count=1, acres=30000)
    holder = permittee_with_base_property(carrying_capacity_aums=1500)
    permit = create_permit(land["allotment"]["id"], holder["permittee"]["id"],
                           holder["base_property"]["id"], requested_aums=1200)
    assert permit["permit_status"] == "PENDING_REVIEW"
    return {"allotment": land["allotment"], "permittee": holder["permittee"],
            "base_property": holder["base_property"], "permit": permit}


def _aoi_body(permit_id, authorized_aums):
    return f.aoi_payload(permit_id, grazing_year=2026, authorized_aums=authorized_aums,
                         season_start_date="2026-01-01", season_end_date="2026-12-31")


def test_permit_state_gate_masks_the_capacity_gate_on_instruction_creation():
    """One instruction-creation request asks for 1500 AUMs against 1200 open AUMs on a permit
    that is still PENDING_REVIEW; priority 8 answers with ERR_PERMIT_STATE_INVALID and the
    priority 30 capacity failure never surfaces, and nothing is written.

    PRD 2.6: "This priority also covers the cross-entity state preconditions that name the
    subject's own parent chain: drafting an operating instruction requires the named permit to be
    `ISSUED`, so a permit in `PENDING_REVIEW`, `SUSPENDED`, `CANCELLED`, `EXPIRED` or
    `TRANSFERRED` yields `ERR_PERMIT_STATE_INVALID`; scheduling a use record requires the owning
    instruction to be in `DRAFT`; reporting actual use requires it to be in `ISSUED`; and paying a
    bill requires the bill to be in `ISSUED` or `DELINQUENT`."
    PRD 2.6: "The checks below are evaluated in ascending order of the numbers given, the first
    violated check short-circuits the request, and its code is the code the client sees."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_aoi_creation
    """
    setup = _masked_capacity_setup()

    error = validate_error(
        api_client.create_aoi(_aoi_body(setup["permit"]["id"], 1500),
                              make_specialist_headers()),
        ApiErrorId.ERR_PERMIT_STATE_INVALID, 409)
    assert error["error_id"] != ApiErrorId.ERR_ALLOTMENT_CAPACITY_EXCEEDED, (
        "the priority 30 capacity failure must stay masked by priority 8")

    assert get_permit(setup["permit"]["id"])["permit_status"] == "PENDING_REVIEW"
    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 0
    assert allotment["open_aums"] == 1200


def test_capacity_gate_surfaces_once_the_permit_state_gate_is_satisfied():
    """Issuing the permit and replaying the identical body proves the fiscal violation was real
    all along: the answer becomes ERR_ALLOTMENT_CAPACITY_EXCEEDED with HTTP 422, and asking for
    1200 AUMs instead of 1500 is accepted.

    PRD 2.6: "This ordering is normative — a client that fixes the reported problem and retries
    will then see the next-highest violated check, and never the reverse."
    PRD 2.6: "At instruction creation the requested `authorized_aums` must not exceed the
    allotment's `open_aums` at that moment, and the same comparison is re-run at issuance against
    the then-current `open_aums`, so a capacity that shrank between draft and issue makes the
    issue fail even though the draft was accepted."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_aoi_creation
    """
    setup = _masked_capacity_setup()
    issued = issue_permit(setup["permit"]["id"])
    assert issued["permit_status"] == "ISSUED"

    validate_error(
        api_client.create_aoi(_aoi_body(setup["permit"]["id"], 1500), make_specialist_headers()),
        ApiErrorId.ERR_ALLOTMENT_CAPACITY_EXCEEDED, 422)

    accepted = validate_success(
        api_client.create_aoi(_aoi_body(setup["permit"]["id"], 1200), make_specialist_headers()),
        201)
    assert accepted["authorized_aums"] == 1200
    assert accepted["aoi_status"] == "DRAFT"

    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allocated_aums"] == 0, "a DRAFT instruction consumes nothing"
    assert allotment["open_aums"] == 1200


def _closed_gate_setup():
    """An ISSUED 300-AUM permit on an allotment driven CLOSED by a FULL_CLOSURE order, plus a
    transferee who owns their own 400-AUM base property."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=1200,
                                  required_pasture_rotation_count=1, acres=30000)
    transferor = permittee_with_base_property(carrying_capacity_aums=400)
    transferee = permittee_with_base_property(carrying_capacity_aums=400)
    permit = issue_permit(create_permit(
        land["allotment"]["id"], transferor["permittee"]["id"],
        transferor["base_property"]["id"], requested_aums=300)["id"])
    order = create_closure_order(
        land["allotment"]["id"], order_type="FULL_CLOSURE", reduction_pct=1.0,
        effective_start_date="2026-08-15", effective_end_date="2026-12-31",
        justification="Rangeland fire rehabilitation requires complete rest of the allotment.")
    return {"allotment": land["allotment"], "transferor": transferor,
            "transferee": transferee, "permit": permit, "order": order}


def _transfer_body(setup, base_property_id):
    return f.transfer_payload(setup["transferee"]["permittee"]["id"], base_property_id,
                              requested_aums=300, term_start_date="2026-01-01",
                              term_end_date="2030-12-31")


def _successor_count(permit_id):
    items, _meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), {"predecessor_permit_id": permit_id, "limit": 100}))
    return len(items)


def test_closed_allotment_gate_masks_the_base_property_ownership_gate_on_transfer():
    """A transfer onto a CLOSED allotment that also reuses the transferor's base property is
    answered by priority 9 with ERR_ALLOTMENT_CLOSED and HTTP 409; the priority 13 ownership
    failure stays hidden, the permit is still ISSUED and no successor is minted.

    PRD 2.6: "When the governing allotment's `allotment_status` is `CLOSED`, no permit may be
    issued, renewed or transferred onto it, no operating instruction may be created or issued for
    any of its permits, and no use record may be scheduled on such an instruction."
    PRD 3.10: "The `allotment_status` becomes `CLOSED` when `stocking_adjustment_pct` is exactly
    1.0, `RESTRICTED` when it is strictly between 0 and 1, and `OPEN` when it is exactly 0."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_permit_transfer
    """
    setup = _closed_gate_setup()
    assert_pct(setup["order"]["reduction_pct"], 1.0)
    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 1.0)
    assert allotment["allotment_status"] == "CLOSED"

    error = validate_error(
        api_client.transfer_permit(
            setup["permit"]["id"],
            _transfer_body(setup, setup["transferor"]["base_property"]["id"]),
            make_officer_headers()),
        ApiErrorId.ERR_ALLOTMENT_CLOSED, 409)
    assert error["error_id"] != ApiErrorId.ERR_BASE_PROPERTY_NOT_OWNED, (
        "the priority 13 ownership failure must stay masked by priority 9")

    assert get_permit(setup["permit"]["id"])["permit_status"] == "ISSUED"
    assert _successor_count(setup["permit"]["id"]) == 0


def test_ownership_gate_surfaces_after_the_closure_is_lifted():
    """Lifting the order returns the allotment to OPEN and the same transfer body then reports
    the ownership violation with HTTP 422; supplying the transferee's own base property finally
    transfers the permit.

    PRD 2.6: "The `base_property_id` carried by the request must belong to the permittee who will
    hold the resulting permit."
    PRD 2.6: "On a transfer the transferee's own base property is required, and reusing the
    transferor's base property is precisely this violation."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_permit_transfer
    """
    setup = _closed_gate_setup()
    lift_closure_order(setup["order"]["id"])
    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allotment_status"] == "OPEN"
    assert allotment["open_aums"] == 1200

    validate_error(
        api_client.transfer_permit(
            setup["permit"]["id"],
            _transfer_body(setup, setup["transferor"]["base_property"]["id"]),
            make_officer_headers()),
        ApiErrorId.ERR_BASE_PROPERTY_NOT_OWNED, 422)
    assert get_permit(setup["permit"]["id"])["permit_status"] == "ISSUED"

    get_success_data(api_client.transfer_permit(
        setup["permit"]["id"],
        _transfer_body(setup, setup["transferee"]["base_property"]["id"]),
        make_officer_headers()))

    assert get_permit(setup["permit"]["id"])["permit_status"] == "TRANSFERRED"
    assert _successor_count(setup["permit"]["id"]) == 1
