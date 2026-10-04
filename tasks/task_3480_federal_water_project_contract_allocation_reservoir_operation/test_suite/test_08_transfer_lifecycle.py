"""Transfer proposals, the bounded revision loop, and execution.

Covers the three-round revision cycle with the cap rejection, the
OPEN-year gate, the objection-window execution gate, ledger conservation
across execution, the price_cents default, the terminal REJECTED lockdown,
the from-line fiscal gate, and the from-equals-to shape rejection - PRD
§2.9, §3.6 and §3.8.
"""

from test_helpers import (
    ApiErrorId,
    REGIONAL_DIRECTOR_HEADERS,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

DIRECTOR = REGIONAL_DIRECTOR_HEADERS


def test_transfer_revision_cycle_bounded(api):
    """The UNDER_REVIEW -> REVISION_REQUESTED -> UNDER_REVIEW loop runs
    exactly three times (revision_count 1, 2, 3); the fourth REQUEST_REVISION
    fails 409 ERR_REVISION_LIMIT_EXCEEDED while REJECT still succeeds.

    PRD §3.8: "A revision request requires `revision_count` below three — at
    the cap it fails with `ERR_REVISION_LIMIT_EXCEEDED` — increments
    `revision_count`, and moves the request to `REVISION_REQUESTED`."
    PRD §3.8: "This review loop — `UNDER_REVIEW` to `REVISION_REQUESTED` and
    back — is bounded by the three-round cap."

    Design: Difficulty/non_linear_state_machine/transfer_revision_cycle_bounded
    """
    world, transfer = fixtures.setup_transfer_under_review(api, quantity_af=1_000, price_cents=50_000)

    # Three rounds: amend to 900, then 800, then resubmit without changes.
    transfer = fixtures.loop_transfer_revisions(api, world, transfer["id"])
    assert transfer["revision_count"] == 3
    assert transfer["status"] == "UNDER_REVIEW"
    assert transfer["quantity_af"] == 800, "the second amendment survives the empty third resubmit"

    validate_error(
        api.decide_transfer_request(transfer["id"], {"decision": "REQUEST_REVISION"}, DIRECTOR),
        ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED,
    )
    still_open = fixtures.get_transfer(api, transfer["id"])
    assert still_open["status"] == "UNDER_REVIEW"
    assert still_open["revision_count"] == 3

    rejected = fixtures.decide_transfer(api, transfer["id"], "REJECT", rationale="rounds exhausted")
    assert rejected["status"] == "REJECTED"


def test_transfer_gated_by_water_year_status(api):
    """Transfer creation in an OPEN year fails 409 ERR_YEAR_NOT_ANNOUNCED;
    the identical payload succeeds once the year is ANNOUNCED.

    PRD §3.8: "The year must be `ANNOUNCED` — `OPEN` fails with
    `ERR_YEAR_NOT_ANNOUNCED`, `CLOSED` with `ERR_YEAR_CLOSED` — and the
    `quantity_af` must not exceed the seller line's `remaining_af` on the
    year's current published announcement, else `ERR_ALLOCATION_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_gated_by_water_year_status
    """
    world = fixtures.setup_open_year(api)  # observations posted, no announcement
    year_id = world["year"]["id"]

    validate_error(
        api.create_transfer_request(
            factories.transfer_payload(
                world["contract_sr"]["id"], world["contract_jr"]["id"], year_id, 100
            ),
            world["mgr_sr_headers"],
        ),
        ApiErrorId.ERR_YEAR_NOT_ANNOUNCED,
    )

    fixtures.publish_new_announcement(api, world)

    transfer = fixtures.create_transfer_request(api, world, 100)
    assert transfer["status"] == "UNDER_REVIEW"

    transfers, meta = validate_paginated(
        api.list_transfer_requests(fixtures.READ_HEADERS, {"water_year_id": year_id})
    )
    assert meta["total_count"] == 1 and len(transfers) == 1


def test_transfer_conserves_year_allocation(api):
    """Executing a 1,000 af transfer debits the seller line and credits the
    buyer line; the pair's remaining balances still sum to the year's 7,500
    total, and the allocations themselves are untouched. Execution exactly at
    the objection window's end is allowed.

    PRD §3.8: "A `ReclamationOperator` executes a transfer in `APPROVED` —
    from any other status, `ERR_INVALID_STATE` — once the logical clock has
    reached `objection_window_end`; earlier execution fails with
    `ERR_OBJECTION_WINDOW_OPEN`, and execution exactly at the window's end is
    allowed."
    PRD §3.8: "Execution moves water on the year's currently `PUBLISHED`
    announcement's lines: the seller line's `transfer_out_af` increases by
    `quantity_af`, the buyer line's `transfer_in_af` increases by
    `quantity_af`, both lines' `remaining_af` are recomputed, and the
    transfer's `executed_at`, likewise null until execution, is stamped with
    the logical clock."

    Design: Difficulty/compensating_invariant/transfer_conserves_year_allocation
    """
    world, transfer = fixtures.setup_transfer_executed(api, quantity_af=1_000, price_cents=50_000)

    assert transfer["status"] == "EXECUTED", "execution at exactly the window end is allowed"

    line_sr = world["line_sr"]
    line_jr = world["line_jr"]
    assert line_sr["transfer_out_af"] == 1_000
    assert line_sr["remaining_af"] == 5_000, "6,000 - 1,000 out"
    assert line_jr["transfer_in_af"] == 1_000
    assert line_jr["remaining_af"] == 2_500, "1,500 + 1,000 in"
    assert line_sr["remaining_af"] + line_jr["remaining_af"] == 7_500, (
        "the year's total remaining is conserved by the forward action"
    )
    assert line_sr["allocated_af"] == 6_000
    assert line_jr["allocated_af"] == 1_500, "allocations are untouched; only ledgers moved"


def test_transfer_create_omitting_price_cents_defaults_zero(api):
    """price_cents declares a default of 0: a transfer created without it
    stores 0 rather than null.

    PRD §3.8: "a `quantity_af` greater than zero (else
    `ERR_INVALID_QUANTITY`), and an optional `price_cents` of zero or more
    that defaults to 0 when omitted."

    Design: Corner/entities/transfer_create_omitting_price_cents_defaults_zero
    """
    world = fixtures.setup_announced_year(api)

    transfer = fixtures.create_transfer_request(api, world, 100)  # price_cents omitted

    assert transfer["price_cents"] == 0
    assert transfer["status"] == "UNDER_REVIEW"
    assert transfer["revision_count"] == 0


def test_decide_on_rejected_transfer_returns_invalid_state(api):
    """REJECTED is terminal: a subsequent decide on the same transfer fails
    409 ERR_INVALID_STATE and changes nothing.

    PRD §3.8: "Decision rests with a `RegionalDirector`, who acts on a
    request in `UNDER_REVIEW` — deciding from any other status fails with
    `ERR_INVALID_STATE`"
    PRD §3.8: "Rejection moves it to `REJECTED`, a terminal state."

    Design: Corner/state_machines/decide_on_rejected_transfer_returns_invalid_state
    """
    world, transfer = fixtures.setup_transfer_under_review(api)
    fixtures.decide_transfer(api, transfer["id"], "REJECT")

    validate_error(
        api.decide_transfer_request(transfer["id"], {"decision": "APPROVE"}, DIRECTOR),
        ApiErrorId.ERR_INVALID_STATE,
    )

    after = fixtures.get_transfer(api, transfer["id"])
    assert after["status"] == "REJECTED"


def test_transfer_over_from_line_returns_allocation_exceeded(api):
    """The fiscal rule guards transfers from the seller side: 6,001 af
    against a 6,000 af remaining balance fails 422 ERR_ALLOCATION_EXCEEDED.

    PRD §3.8: "the `quantity_af` must not exceed the seller line's
    `remaining_af` on the year's current published announcement, else
    `ERR_ALLOCATION_EXCEEDED`."

    Design: Corner/validations/transfer_over_from_line_returns_allocation_exceeded
    """
    world = fixtures.setup_announced_year(api)  # senior line remaining 6,000

    validate_error(
        api.create_transfer_request(
            factories.transfer_payload(
                world["contract_sr"]["id"], world["contract_jr"]["id"],
                world["year"]["id"], 6_001,
            ),
            world["mgr_sr_headers"],
        ),
        ApiErrorId.ERR_ALLOCATION_EXCEEDED,
    )

    transfers, meta = validate_paginated(
        api.list_transfer_requests(fixtures.READ_HEADERS, {"water_year_id": world["year"]["id"]})
    )
    assert meta["total_count"] == 0 and transfers == []


def test_transfer_from_equals_to_returns_invalid_request(api):
    """from_contract_id == to_contract_id is a shape error: 400
    ERR_INVALID_REQUEST before any state or fiscal evaluation.

    PRD §3.8: "A `DistrictManager` proposes a transfer as seller, supplying
    `from_contract_id` and `to_contract_id` — which must differ, else
    `ERR_INVALID_REQUEST` — the `water_year_id` whose allocation lines will
    move"

    Design: Corner/validations/transfer_from_equals_to_returns_invalid_request
    """
    world = fixtures.setup_announced_year(api)

    response = api.create_transfer_request(
        factories.transfer_payload(
            world["contract_sr"]["id"], world["contract_sr"]["id"], world["year"]["id"], 10
        ),
        world["mgr_sr_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400
    assert error["error_id"] == "ERR_INVALID_REQUEST"


def test_transfer_execute_before_window_end_rejected(api):
    """An APPROVED transfer cannot execute while its objection window is
    open: at 71 hours after approval the execute fails 409
    ERR_OBJECTION_WINDOW_OPEN and no ledger movement occurs.

    PRD §3.8: "A `ReclamationOperator` executes a transfer in `APPROVED` —
    from any other status, `ERR_INVALID_STATE` — once the logical clock has
    reached `objection_window_end`; earlier execution fails with
    `ERR_OBJECTION_WINDOW_OPEN`, and execution exactly at the window's end is
    allowed."

    Design: Corner/validations/transfer_execute_before_window_end_rejected
    """
    # Approved at the January publish instant; the window ends 72h later at
    # 2027-01-18T00:00:00Z.
    world, transfer = fixtures.setup_transfer_approved(api, quantity_af=1_000)
    fixtures.set_clock(api, "2027-01-17T23:00:00Z")

    validate_error(
        api.execute_transfer_request(transfer["id"], fixtures.RECLAMATION_OPERATOR_HEADERS),
        ApiErrorId.ERR_OBJECTION_WINDOW_OPEN,
    )

    after = fixtures.get_transfer(api, transfer["id"])
    assert after["status"] == "APPROVED"

    line_sr = fixtures.find_line(api, world["announcement"]["id"], world["contract_sr"]["id"])
    assert line_sr["transfer_out_af"] == 0, "a rejected execute moves no water"
