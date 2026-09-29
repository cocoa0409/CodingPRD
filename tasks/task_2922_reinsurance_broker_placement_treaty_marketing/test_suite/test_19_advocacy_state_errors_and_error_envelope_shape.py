"""Advocacy status gates, the running collectible ceiling and the error envelope.

Queue B — section ``errors``: five advocacy endpoints share
``ERR_ADVOCACY_STATE_INVALID`` at priority 30 while each admits a different set
of source states, the collectible ceiling is enforced on the running total
rather than on the individual call, and every HTTP status class answers with one
identical error envelope (PRD §2.2, §2.3, §3.1, §3.9).
"""
from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    CLOCK,
    LEAD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    advocacy_route_payload,
    api_client,
    assert_envelope_meta,
    assert_money_equals,
    assert_status,
    collect,
    create_cedent,
    create_cedent_payload,
    create_cession_dispute_payload,
    create_collection_payload,
    create_program_payload,
    make_cedent_underwriter_headers,
    make_reinsurer_underwriter_headers,
    read_advocacy,
    read_layer,
    review_claim,
    set_advocacy_route,
    set_clock,
    setup_disputed_claim,
    setup_notified_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical CAT layer is 1,000,000,000 excess of 2,000,000,000, so the
# default 2,600,000,000 ground-up loss cedes 600,000,000 to the treaty.
CEDED_CLAIM_MINOR = 600_000_000
COLLECTIBLE_MINOR = 600_000_000
ONE_UNIT_OVER_COLLECTIBLE_MINOR = 600_000_001
ONE_UNIT_SHORT_MINOR = 599_999_999
TWO_UNITS_MINOR = 2
LAST_UNIT_MINOR = 1

# One dispute of 100,000,000 leaves 500,000,000 collectible.
DISPUTED_MINOR = 100_000_000
COLLECTIBLE_AFTER_DISPUTE_MINOR = 500_000_000
FURTHER_DISPUTE_MINOR = 1_000

# Envelope shape (PRD §2.2).
ERROR_DATA_KEYS = {"error_id", "message"}
ERROR_META_KEYS = {"api_request_id", "api_request_timestamp"}
BACKWARDS_PROGRAM_NAME = "Backwards Period 2026"


def _assert_error_envelope(response, expected_error_id: str, expected_status: int):
    """One error envelope for every status class: meta, response_type, data."""
    validate_error(response, expected_error_id, expected_status)
    body = response.json()
    assert body["response_type"] == "error", (
        f"every failure carries response_type error, got {body['response_type']!r}"
    )
    assert set(body["data"].keys()) == ERROR_DATA_KEYS, (
        "an error body carries exactly error_id and message and never leaks a "
        f"partial entity, got keys {sorted(body['data'].keys())}"
    )
    assert body["data"]["message"].strip(), "the message must be non-empty"
    assert set(body["meta"].keys()) == ERROR_META_KEYS, (
        "the meta block of an error carries only api_request_id and "
        f"api_request_timestamp, got keys {sorted(body['meta'].keys())}"
    )
    assert_envelope_meta(body)
    return body


def test_review_is_not_repeatable_and_a_reviewed_file_is_past_the_cedents_withdrawal():
    """Both NOTIFIED-only operations refuse the file once it reaches UNDER_REVIEW.

    PRD: "Any other file state on either operation is
    `ERR_ADVOCACY_STATE_INVALID`."

    Design: Corner/errors/advocacy_calls_made_from_the_wrong_status_all_return_the_advocacy_state_error
    """
    ctx = setup_notified_claim()
    advocacy = ctx["advocacy"]
    assert_status(advocacy, "status", "NOTIFIED")
    assert_money_equals(advocacy["ceded_claim_minor"], CEDED_CLAIM_MINOR, "ceded_claim_minor")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], COLLECTIBLE_MINOR, "collectible_minor")

    reviewed = review_claim(advocacy["id"])
    assert_status(reviewed, "status", "UNDER_REVIEW")

    second_review = api_client.review_claim_advocacy(advocacy["id"], LEAD)
    validate_error(second_review, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    late_withdrawal = api_client.withdraw_claim_advocacy(
        advocacy["id"], make_cedent_underwriter_headers(ctx["cedent"]["id"])
    )
    validate_error(late_withdrawal, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    after = read_advocacy(advocacy["id"])
    assert_status(after, "status", "UNDER_REVIEW")
    assert_money_equals(after["collected_minor"], 0, "collected_minor")
    assert after["advocacy_route"] is None, (
        "no route has been chosen, so advocacy_route stays null"
    )


def test_a_route_cannot_be_chosen_before_a_dispute_has_moved_the_file_to_disputed():
    """NOTIFIED and UNDER_REVIEW both refuse the fork that only DISPUTED admits.

    PRD: "From `DISPUTED` the broker chooses a `route`, and the two branches
    diverge in their side effects, not merely in their labels."

    Design: Corner/errors/advocacy_calls_made_from_the_wrong_status_all_return_the_advocacy_state_error
    """
    ctx = setup_notified_claim()
    advocacy = ctx["advocacy"]

    from_notified = api_client.set_advocacy_route(
        advocacy["id"], advocacy_route_payload("NEGOTIATION"), LEAD
    )
    validate_error(from_notified, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    review_claim(advocacy["id"])
    from_under_review = api_client.set_advocacy_route(
        advocacy["id"], advocacy_route_payload("NEGOTIATION"), LEAD
    )
    validate_error(from_under_review, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    after = read_advocacy(advocacy["id"])
    assert_status(after, "status", "UNDER_REVIEW")
    assert after["advocacy_route"] is None, (
        "a refused fork leaves advocacy_route null"
    )
    assert_money_equals(after["arbitration_cost_minor"], 0, "arbitration_cost_minor")


def test_the_first_dispute_carries_the_file_into_disputed_which_then_refuses_a_review():
    """The status that admits a dispute is exactly the status that refuses a review.

    PRD: "Creating the **first** dispute on a file cascades the file from
    `UNDER_REVIEW` to `DISPUTED` and recomputes `disputed_minor` and
    `collectible_minor`; a second and subsequent dispute recomputes those figures
    without moving the file, which is already `DISPUTED`."

    Design: Corner/errors/advocacy_calls_made_from_the_wrong_status_all_return_the_advocacy_state_error
    """
    ctx = setup_disputed_claim(disputed_minor=DISPUTED_MINOR)
    advocacy = ctx["advocacy"]
    assert_status(advocacy, "status", "DISPUTED")
    assert_money_equals(advocacy["disputed_minor"], DISPUTED_MINOR, "disputed_minor")
    assert_money_equals(
        advocacy["collectible_minor"],
        COLLECTIBLE_AFTER_DISPUTE_MINOR,
        "collectible_minor",
    )
    assert_status(ctx["dispute"], "status", "RAISED")

    review_from_disputed = api_client.review_claim_advocacy(advocacy["id"], LEAD)
    validate_error(review_from_disputed, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    after = read_advocacy(advocacy["id"])
    assert_status(after, "status", "DISPUTED")
    assert_money_equals(after["ceded_claim_minor"], CEDED_CLAIM_MINOR, "ceded_claim_minor")


def test_negotiation_is_chosen_once_and_then_refuses_a_second_route_and_a_further_dispute():
    """ADVOCACY_NEGOTIATION is not a fork that can be re-taken or re-disputed.

    PRD: "`NEGOTIATION` sets `advocacy_route` to `NEGOTIATION`, leaves
    `arbitration_cost_minor` at 0, moves the file to `ADVOCACY_NEGOTIATION`, and
    leaves collections open throughout."

    Design: Corner/errors/advocacy_calls_made_from_the_wrong_status_all_return_the_advocacy_state_error
    """
    ctx = setup_disputed_claim(disputed_minor=DISPUTED_MINOR)
    advocacy = ctx["advocacy"]

    negotiating = set_advocacy_route(advocacy["id"], "NEGOTIATION")
    assert_status(negotiating, "status", "ADVOCACY_NEGOTIATION")
    assert_status(negotiating, "advocacy_route", "NEGOTIATION")
    assert_money_equals(
        negotiating["arbitration_cost_minor"], 0, "arbitration_cost_minor"
    )

    switch_route = api_client.set_advocacy_route(
        advocacy["id"], advocacy_route_payload("ARBITRATION"), LEAD
    )
    validate_error(switch_route, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    further_dispute = api_client.create_cession_dispute(
        advocacy["id"],
        create_cession_dispute_payload(
            ctx["signing_lines"][0]["id"],
            FURTHER_DISPUTE_MINOR,
            dispute_reason="WORDING_AMBIGUITY",
        ),
        make_reinsurer_underwriter_headers(ctx["reinsurers"][0]["id"]),
    )
    validate_error(further_dispute, ApiErrorId.ERR_ADVOCACY_STATE_INVALID.value)

    after = read_advocacy(advocacy["id"])
    assert_status(after, "status", "ADVOCACY_NEGOTIATION")
    assert_status(after, "advocacy_route", "NEGOTIATION")
    assert_money_equals(after["arbitration_cost_minor"], 0, "arbitration_cost_minor")
    assert_money_equals(after["disputed_minor"], DISPUTED_MINOR, "disputed_minor")
    assert_money_equals(
        after["collectible_minor"], COLLECTIBLE_AFTER_DISPUTE_MINOR, "collectible_minor"
    )


def test_one_minor_unit_above_the_collectible_is_refused_and_books_no_movement():
    """600,000,001 against a 600,000,000 collectible is refused outright.

    PRD: "And the file's `collected_minor` plus this amount must be no greater
    than its `collectible_minor`, else `ERR_COLLECTION_EXCEEDS_COLLECTIBLE`;
    exact equality is what closes the file."

    Design: Corner/errors/collecting_one_minor_unit_above_the_collectible_is_refused_on_the_running_total
    """
    ctx = setup_notified_claim()
    advocacy = review_claim(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "UNDER_REVIEW")
    assert_money_equals(advocacy["ceded_claim_minor"], CEDED_CLAIM_MINOR, "ceded_claim_minor")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], COLLECTIBLE_MINOR, "collectible_minor")
    assert_money_equals(advocacy["collected_minor"], 0, "collected_minor")

    over = api_client.create_collection(
        advocacy["id"],
        create_collection_payload(
            ctx["signing_lines"][0]["id"], ONE_UNIT_OVER_COLLECTIBLE_MINOR
        ),
        ACCOUNTANT,
    )
    validate_error(over, ApiErrorId.ERR_COLLECTION_EXCEEDS_COLLECTIBLE.value)

    after = read_advocacy(advocacy["id"])
    assert_status(after, "status", "UNDER_REVIEW")
    assert_money_equals(after["collected_minor"], 0, "collected_minor")

    rows, meta = validate_paginated(
        api_client.list_fiduciary_transactions(
            ACCOUNTANT, params={"program_id": ctx["program"]["id"]}
        )
    )
    assert rows == [], (
        f"a refused collection materialises no movement, got {len(rows)} rows"
    )
    assert meta["total_count"] == 0, (
        f"the program's ledger is still empty, got total_count {meta['total_count']}"
    )


def test_a_two_unit_collection_is_refused_because_the_ceiling_is_on_the_running_total():
    """599,999,999 is admitted and books a PENDING movement, then 2 is refused.

    PRD: "The file's `collected_minor` is then recomputed as the sum of
    `amount_minor` over the `CLAIM_COLLECTION` movements linked to the file's
    signing lines whose status is `PENDING`, `APPROVED` or `SETTLED` — note that a
    collection counts toward the file the moment it is booked, even though it
    counts toward the fiduciary balance only once it settles."

    Design: Corner/errors/collecting_one_minor_unit_above_the_collectible_is_refused_on_the_running_total
    """
    ctx = setup_notified_claim()
    advocacy = review_claim(ctx["advocacy"]["id"])
    line = ctx["signing_lines"][0]

    movement = collect(advocacy["id"], line["id"], ONE_UNIT_SHORT_MINOR)
    assert_status(movement, "txn_type", "CLAIM_COLLECTION")
    assert_status(movement, "status", "PENDING")
    assert_money_equals(movement["amount_minor"], ONE_UNIT_SHORT_MINOR, "amount_minor")
    assert movement["program_id"] == ctx["program"]["id"], (
        "the movement is booked on the advocacy's program"
    )
    assert movement["signing_line_id"] == line["id"], (
        "the movement is linked to the same signing line"
    )

    short_by_one = read_advocacy(advocacy["id"])
    assert_money_equals(
        short_by_one["collected_minor"], ONE_UNIT_SHORT_MINOR, "collected_minor"
    )
    assert_status(short_by_one, "status", "UNDER_REVIEW")

    over_running_total = api_client.create_collection(
        advocacy["id"],
        create_collection_payload(line["id"], TWO_UNITS_MINOR),
        ACCOUNTANT,
    )
    validate_error(
        over_running_total, ApiErrorId.ERR_COLLECTION_EXCEEDS_COLLECTIBLE.value
    )

    after = read_advocacy(advocacy["id"])
    assert_money_equals(after["collected_minor"], ONE_UNIT_SHORT_MINOR, "collected_minor")
    assert_status(after, "status", "UNDER_REVIEW")


def test_the_exact_last_minor_unit_closes_the_file_without_consuming_a_reinstatement():
    """The 600,000,000th minor unit lands on the ceiling and closes the file.

    PRD: "When the recomputed `collected_minor` reaches or exceeds
    `collectible_minor`, the file becomes `COLLECTED`, which is terminal, and this
    is reachable both from `RESOLVED` and directly from `UNDER_REVIEW` when no
    dispute was ever raised on the file."

    Design: Corner/errors/collecting_one_minor_unit_above_the_collectible_is_refused_on_the_running_total
    """
    ctx = setup_notified_claim()
    advocacy = review_claim(ctx["advocacy"]["id"])
    line = ctx["signing_lines"][0]

    first = collect(advocacy["id"], line["id"], ONE_UNIT_SHORT_MINOR)
    last = collect(advocacy["id"], line["id"], LAST_UNIT_MINOR)
    assert_status(last, "txn_type", "CLAIM_COLLECTION")
    assert_status(last, "status", "PENDING")

    closed = read_advocacy(advocacy["id"])
    assert_status(closed, "status", "COLLECTED")
    assert_money_equals(closed["collected_minor"], COLLECTIBLE_MINOR, "collected_minor")
    assert closed["reinstatement_triggered"] is False, (
        "600,000,000 of a 1,000,000,000 limit consumes no reinstatement"
    )

    layer = read_layer(ctx["layer"]["id"])
    assert_money_equals(layer["limit_eroded_minor"], CEDED_CLAIM_MINOR, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 0, (
        "ceil(600,000,000 / 1,000,000,000) - 1 is 0, so no reinstatement was used, "
        f"got {layer['reinstatements_used']}"
    )
    assert_money_equals(
        layer["incurred_ceded_minor"], CEDED_CLAIM_MINOR, "incurred_ceded_minor"
    )

    by_program, program_meta = validate_paginated(
        api_client.list_fiduciary_transactions(
            ACCOUNTANT, params={"program_id": ctx["program"]["id"]}
        )
    )
    assert program_meta["total_count"] == 2, (
        f"exactly the two collections were booked, got {program_meta['total_count']}"
    )
    assert {row["id"] for row in by_program} == {first["id"], last["id"]}, (
        "the program's ledger holds exactly the two collection movements"
    )
    assert [row["txn_type"] for row in by_program] == ["CLAIM_COLLECTION"] * 2, (
        "no REINSTATEMENT_PREMIUM movement is appended when no reinstatement was "
        f"consumed, got {[row['txn_type'] for row in by_program]}"
    )

    by_line, line_meta = validate_paginated(
        api_client.list_fiduciary_transactions(
            ACCOUNTANT, params={"signing_line_id": line["id"]}
        )
    )
    assert line_meta["total_count"] == 2, (
        f"both movements are linked to the writing line, got {line_meta['total_count']}"
    )
    assert {row["id"] for row in by_line} == {first["id"], last["id"]}, (
        "the signing-line view answers with the same two movements"
    )


def test_a_successful_read_carries_the_meta_block_the_object_type_and_no_error_id():
    """The 200 a client parses first: meta, response_type object, data, no error_id.

    PRD: "All successful API responses (those with 2xx status codes) follow this
    standard envelope format in their JSON body:"

    Design: Corner/errors/every_error_status_class_returns_the_same_envelope_shape
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()

    response = api_client.get_cedent(cedent["id"], ADMIN)
    assert response.status_code == 200, (
        f"a read of an existing cedent is a 200, got {response.status_code}"
    )
    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource answers response_type object, got {body['response_type']!r}"
    )
    assert_envelope_meta(body)
    assert "error_id" not in body, "a success envelope carries no error_id"
    assert "error_id" not in body["data"], "a success envelope carries no error_id in data"
    assert "error_id" not in body["meta"], "a success envelope carries no error_id in meta"

    data = validate_success(response)
    assert data["name"] == cedent["name"], (
        f"the read answers the registered cedent, got {data['name']!r}"
    )
    assert data["id"] == cedent["id"], "the read answers the same row that was registered"


def test_both_four_hundred_classes_answer_with_the_same_two_key_error_body():
    """A missing required field and a pagination limit of 0 share one envelope.

    PRD: "A `limit` that is not an integer, is below 1 or is above 100, and an
    `offset` that is not an integer or is negative, are rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/errors/every_error_status_class_returns_the_same_envelope_shape
    """
    set_clock(CLOCK["PLACEMENT_START"])

    missing_name = api_client.create_cedent(
        {"domicile_code": "GBLON", "financial_rating": "A"}, ADMIN
    )
    shape_body = _assert_error_envelope(missing_name, ApiErrorId.ERR_VALIDATION.value, 400)

    below_minimum = api_client.list_cedents(ADMIN, params={"limit": 0, "offset": 0})
    limit_body = _assert_error_envelope(
        below_minimum, ApiErrorId.ERR_VALIDATION.value, 400
    )

    assert set(shape_body.keys()) == set(limit_body.keys()), (
        "the request-shape failure and the pagination failure carry the same "
        f"envelope keys, got {sorted(shape_body)} and {sorted(limit_body)}"
    )
    assert shape_body["data"]["error_id"] == limit_body["data"]["error_id"], (
        "both 400s report ERR_VALIDATION"
    )
    assert "limit" not in limit_body["meta"], (
        "a rejected pagination request returns no pagination meta"
    )


def test_the_not_found_conflict_and_unprocessable_classes_share_one_error_envelope():
    """404, 409 and 422 differ only in status and error_id, never in shape.

    PRD: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/every_error_status_class_returns_the_same_envelope_shape
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()

    missing = api_client.get_program(NON_EXISTENT_UUID, LEAD)
    not_found = _assert_error_envelope(missing, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value, 404)

    duplicate = api_client.create_cedent(
        create_cedent_payload(domicile_code="GBLON", financial_rating="B"), ADMIN
    )
    conflict = _assert_error_envelope(duplicate, ApiErrorId.ERR_DUPLICATE_NAME.value, 409)

    backwards = api_client.create_program(
        create_program_payload(
            cedent["id"],
            program_name=BACKWARDS_PROGRAM_NAME,
            inception_date=CLOCK["EXPIRY"],
            expiry_date=CLOCK["INCEPTION"],
        ),
        LEAD,
    )
    unprocessable = _assert_error_envelope(
        backwards, ApiErrorId.ERR_TREATY_PERIOD_INVALID.value, 422
    )

    shapes = [set(body.keys()) for body in (not_found, conflict, unprocessable)]
    assert shapes[0] == shapes[1] == shapes[2], (
        f"all three status classes carry the same envelope keys, got {shapes}"
    )
    assert "name" not in conflict["data"] and "id" not in conflict["data"], (
        "a refused registration echoes no partial entity"
    )

    rows, meta = validate_paginated(api_client.list_cedents(ADMIN))
    assert meta["total_count"] == 1, (
        f"neither refused POST registered a cedent, got total_count {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [cedent["id"]], (
        "the register still holds exactly the one cedent that was accepted"
    )
