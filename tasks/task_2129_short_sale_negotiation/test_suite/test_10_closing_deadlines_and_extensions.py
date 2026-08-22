"""Closing under the letter, lazy expiry, and the extension chain: the budget,
the successor letter, and the collateral cancellations."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_approval_letter,
    assert_extension_request,
    extension_decision_payload,
    file_extension,
    file_extension_request_payload,
    set_clock,
    setup_full_approval_chain,
    setup_letter_with_extension_request,
    validate_error,
    validate_paginated,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]
ANALYST2 = TEST_USERS["second_analyst_headers"]


def test_closing_under_the_letter_closes_the_case_and_the_window(api):
    """PRD §3.9: "Closing under the letter is the negotiator's move, and it is available
    only while the letter is `ACTIVE` and only on or before its `closing_deadline` — a
    close attempted at exactly the deadline instant still succeeds. The letter moves to
    the terminal `CLOSED`, the case's negotiation dimension moves from `APPROVAL_ACTIVE`
    to the terminal `CLOSED`, and the case's controlling listing is withdrawn: whether it
    stood at `ACTIVE` or at `UNDER_CONTRACT`, it moves to `WITHDRAWN` with its `ended_at`
    set to the current logical-clock instant."

    Design: Corner/state_machines/close_letter_moves_case_to_closed_and_withdraws_listing
    """
    scenario = setup_full_approval_chain()
    set_clock("2026-09-15T00:00:00Z")

    closed = validate_success(
        api.close_approval_letter(scenario["letter"]["id"], NEG), 200
    )

    assert closed["status"] == "CLOSED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "CLOSED"

    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "WITHDRAWN"
    assert listings[0]["ended_at"].startswith("2026-09-15T00:00:00")

    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "ACCEPTED"


def test_closing_past_the_deadline_expires_the_letter_then_refuses(api):
    """PRD §3.9: "Instead, whenever a write is addressed at a letter and the current
    instant has passed that letter's `closing_deadline`, the server first moves the letter
    from `ACTIVE` to the terminal `EXPIRED`, cancels every extension request against it
    that was still `REQUESTED`, and then refuses the observing write with
    `ERR_APPROVAL_EXPIRED`."

    Design: Corner/state_machines/close_letter_after_deadline_expires_letter_and_rejects_write
    """
    scenario = setup_full_approval_chain()
    assert scenario["letter"]["closing_deadline"].startswith("2026-10-08T00:00:00")
    set_clock("2026-10-09T00:00:00Z")

    validate_error(
        api.close_approval_letter(scenario["letter"]["id"], NEG),
        ApiErrorId.ERR_APPROVAL_EXPIRED.value,
    )

    letter_after = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert letter_after["status"] == "EXPIRED"
    assert letter_after["closing_deadline"].startswith("2026-10-08T00:00:00")
    assert_approval_letter(letter_after)

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "APPROVAL_ACTIVE"
    listings = validate_success(api.list_case_listings(scenario["case"]["id"], NEG), 200)
    assert listings[0]["marketing_status"] == "UNDER_CONTRACT"


def test_filing_an_extension_against_a_closed_letter_is_refused(api):
    """PRD §3.9: "Addressing any of those three at a letter that is not `ACTIVE` for some
    other reason — already closed, already voided, already superseded — yields
    `ERR_APPROVAL_NOT_ACTIVE` instead."

    Design: Corner/state_machines/file_extension_against_closed_letter_returns_approval_not_active
    """
    scenario = setup_full_approval_chain()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(api.close_approval_letter(scenario["letter"]["id"], NEG), 200)

    validate_error(
        api.file_extension_request(
            scenario["letter"]["id"],
            file_extension_request_payload(15, reason="Late title work"),
            NEG,
        ),
        ApiErrorId.ERR_APPROVAL_NOT_ACTIVE.value,
    )

    letter_after = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert letter_after["status"] == "CLOSED"

    requests = validate_success(
        api.list_letter_extension_requests(scenario["letter"]["id"], ANALYST), 200
    )
    assert len(requests) == 0

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "CLOSED"


def test_deciding_an_already_denied_extension_is_refused(api):
    """PRD §3.9: "A `ServicerAnalyst` — necessarily one other than the letter's
    `issued_by_user_id` — decides it with an `outcome` of `GRANT` or `DENY`; deciding a
    request that is not `REQUESTED` is refused with `ERR_EXTENSION_NOT_PENDING`."
    PRD §3.9: "A `DENY` is deliberately inert on the ledger. It sets `granted_days` to 0,
    stamps `decided_by_user_id`, moves the request to the terminal `DENIED`, and leaves
    the letter's `closing_deadline`, its `cumulative_extension_days_used` and its
    `ACTIVE` status entirely untouched."

    Design: Corner/state_machines/decide_denied_extension_returns_extension_not_pending
    """
    scenario = setup_letter_with_extension_request(requested_days=20)
    extension_id = scenario["extension"]["id"]
    denied = validate_success(
        api.decide_extension_request(
            extension_id, extension_decision_payload("DENY"), ANALYST2
        ),
        200,
    )
    assert denied["status"] == "DENIED"

    validate_error(
        api.decide_extension_request(
            extension_id, extension_decision_payload("GRANT"), ANALYST2
        ),
        ApiErrorId.ERR_EXTENSION_NOT_PENDING.value,
    )

    requests = validate_success(
        api.list_letter_extension_requests(scenario["letter"]["id"], ANALYST), 200
    )
    stored = requests[0]
    assert stored["status"] == "DENIED"
    assert stored["granted_days"] == 0
    assert stored["new_closing_deadline"] is None

    letter_after = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert letter_after["status"] == "ACTIVE"
    assert letter_after["closing_deadline"].startswith("2026-10-08T00:00:00")
    assert letter_after["cumulative_extension_days_used"] == 0


def test_the_issuing_analyst_may_not_decide_the_extension(api):
    """PRD §2.10: "The analyst who issued an approval letter — recorded as
    `issued_by_user_id` at issuance — is barred from deciding any extension request filed
    against that letter."
    PRD §2.10: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP
    403."

    Design: Corner/rbac/issuing_analyst_cannot_decide_extension_request
    """
    scenario = setup_letter_with_extension_request(requested_days=20)

    # The letter was issued by sa-100, so sa-100 is barred from deciding.
    validate_error(
        api.decide_extension_request(
            scenario["extension"]["id"], extension_decision_payload("GRANT"), ANALYST
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    requests = validate_success(
        api.list_letter_extension_requests(scenario["letter"]["id"], ANALYST), 200
    )
    assert requests[0]["status"] == "REQUESTED"
    assert requests[0]["decided_by_user_id"] is None
    assert_extension_request(requests[0])

    letter_after = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert letter_after["status"] == "ACTIVE"
    assert letter_after["closing_deadline"].startswith("2026-10-08T00:00:00")


def test_an_extension_landing_exactly_on_sixty_days_is_granted(api):
    """PRD §3.9: "A `GRANT` additionally requires that the chain's extension budget
    accommodate it: the letter's `cumulative_extension_days_used` plus the
    `requested_days` must be **no more than 60 days** in total, and a request that would
    push the chain past sixty days is refused with `ERR_EXTENSION_BUDGET_EXCEEDED`. A
    request landing exactly on 60 is granted."

    Design: Corner/calculations/extension_budget_exactly_sixty_days_is_granted
    """
    scenario = setup_letter_with_extension_request(requested_days=60)

    granted = validate_success(
        api.decide_extension_request(
            scenario["extension"]["id"], extension_decision_payload("GRANT"), ANALYST2
        ),
        200,
    )

    assert granted["status"] == "GRANTED"
    assert granted["granted_days"] == 60

    predecessor = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert predecessor["status"] == "SUPERSEDED"

    successors, meta = validate_paginated(
        api.list_approval_letters(
            ANALYST, params={"supersedes_approval_id": scenario["letter"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    successor = successors[0]
    assert successor["status"] == "ACTIVE"
    # 2026-10-08 advanced by 60 calendar days.
    assert successor["closing_deadline"].startswith("2026-12-07T00:00:00")
    assert successor["cumulative_extension_days_used"] == 60


def test_an_extension_past_sixty_days_is_refused(api):
    """PRD §3.9: "A `GRANT` additionally requires that the chain's extension budget
    accommodate it: the letter's `cumulative_extension_days_used` plus the
    `requested_days` must be **no more than 60 days** in total, and a request that would
    push the chain past sixty days is refused with `ERR_EXTENSION_BUDGET_EXCEEDED`. A
    request landing exactly on 60 is granted."

    Design: Corner/calculations/extension_budget_over_sixty_days_is_rejected
    """
    scenario = setup_letter_with_extension_request(requested_days=65)

    validate_error(
        api.decide_extension_request(
            scenario["extension"]["id"], extension_decision_payload("GRANT"), ANALYST2
        ),
        ApiErrorId.ERR_EXTENSION_BUDGET_EXCEEDED.value,
    )

    requests = validate_success(
        api.list_letter_extension_requests(scenario["letter"]["id"], ANALYST), 200
    )
    assert requests[0]["status"] == "REQUESTED"

    letter_after = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert letter_after["status"] == "ACTIVE"
    assert letter_after["closing_deadline"].startswith("2026-10-08T00:00:00")
    assert letter_after["cumulative_extension_days_used"] == 0

    _, meta = validate_paginated(
        api.list_approval_letters(
            ANALYST, params={"supersedes_approval_id": scenario["letter"]["id"]}
        )
    )
    assert meta["total_count"] == 0, "no successor letter is minted by a refused grant"


def test_a_grant_mints_a_successor_letter_carrying_the_extended_deadline(api):
    """PRD §3.9: "Hop one sets the request's `granted_days` equal to its `requested_days`
    and mints a **successor** approval letter: its `supersedes_approval_id` points at the
    predecessor, its `closing_deadline` is the predecessor's `closing_deadline` advanced
    by `granted_days` calendar days, its `cumulative_extension_days_used` is the
    predecessor's total plus those granted days, and every other field — the case, the
    approved offer, the approved net, the commission cap, the relocation incentive, the
    deficiency-waiver treatment, the conditions and the issuing analyst's identifier — is
    copied from the predecessor."
    PRD §3.9: "The granted request itself records `new_closing_deadline`, the successor's
    deadline, and moves to the terminal `GRANTED`."

    Design: Difficulty/transitive_cascade/extension_grant_mints_successor_and_cancels_sibling_request
    """
    scenario = setup_letter_with_extension_request(requested_days=20)
    file_extension(scenario["letter"]["id"], 10, reason="Title curative work")

    granted = validate_success(
        api.decide_extension_request(
            scenario["extension"]["id"], extension_decision_payload("GRANT"), ANALYST2
        ),
        200,
    )

    assert granted["status"] == "GRANTED"
    assert granted["granted_days"] == 20
    assert granted["new_closing_deadline"].startswith("2026-10-28T00:00:00")

    successors, meta = validate_paginated(
        api.list_approval_letters(
            ANALYST, params={"supersedes_approval_id": scenario["letter"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    successor = successors[0]
    assert successor["status"] == "ACTIVE"
    assert successor["supersedes_approval_id"] == scenario["letter"]["id"]
    assert successor["closing_deadline"].startswith("2026-10-28T00:00:00")
    assert successor["cumulative_extension_days_used"] == 20
    assert successor["approved_net_proceeds_cents"] == 22_122_539
    assert_approval_letter(successor)


def test_a_grant_supersedes_the_predecessor_and_cancels_its_siblings(api):
    """PRD §3.9: "Hop two, caused by hop one, moves the predecessor from `ACTIVE` to the
    terminal `SUPERSEDED`. Hop three, caused by hop two, cancels the collateral damage:
    every **other** extension request against the predecessor that was still `REQUESTED`
    moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/extension_grant_mints_successor_and_cancels_sibling_request
    """
    scenario = setup_letter_with_extension_request(requested_days=20)
    sibling = file_extension(scenario["letter"]["id"], 10, reason="Title curative work")

    validate_success(
        api.decide_extension_request(
            scenario["extension"]["id"], extension_decision_payload("GRANT"), ANALYST2
        ),
        200,
    )

    predecessor = validate_success(
        api.get_approval_letter(scenario["letter"]["id"], ANALYST), 200
    )
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["closing_deadline"].startswith("2026-10-08T00:00:00"), (
        "the predecessor's own deadline is left where it was"
    )

    requests = validate_success(
        api.list_letter_extension_requests(scenario["letter"]["id"], ANALYST), 200
    )
    by_id = {request["id"]: request for request in requests}
    assert by_id[sibling["id"]]["status"] == "CANCELLED"
    assert by_id[scenario["extension"]["id"]]["status"] == "GRANTED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], NEG), 200)
    assert case_after["negotiation_status"] == "APPROVAL_ACTIVE"
