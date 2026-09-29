"""Grading, contesting a grade, and the independent re-grade."""

from test_helpers import (
    ADMIN,
    AUTH1,
    AUTH2,
    AUTHENTICATOR_ID,
    CREDIT_POLICY_CORE,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_FOOTWEAR_B,
    GRADE_POLICY_OUTERWEAR_B,
    INTAKE,
    SECOND_AUTHENTICATOR_ID,
    api_client,
    appeal_trade_in,
    appeal_trade_in_payload,
    authenticate_trade_in,
    authenticate_trade_in_payload,
    create_credit_policy,
    create_customer,
    create_grade_policy,
    create_store_location,
    create_trade_in,
    disposition_payload,
    disposition_trade_in,
    fetch_trade_in,
    make_customer_headers,
    receive_trade_in,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_submitted_trade_in_refuses_grading_appeal_and_disposition():
    """Each refused action names its own per-transition state error.

    PRD §3.3: "Attempting to grade a trade-in whose status is neither
    `RECEIVED` nor `APPEALED` is `ERR_TRADE_IN_NOT_AUTHENTICATABLE`."
    PRD §3.3: "The trade-in must be in `AUTHENTICATED` — an appeal against a
    `RECEIVED`, `ACCEPTED` or `REJECTED` trade-in is
    `ERR_TRADE_IN_NOT_APPEALABLE`."
    PRD §3.4: "In both branches the trade-in must currently be `AUTHENTICATED`;
    any other status is `ERR_TRADE_IN_NOT_DISPOSITIONABLE`."
    PRD §2.11: "**State.** The target entity must be in a state from which the
    requested transition is declared."
    PRD §2.11: "**Counted limits** — `ERR_REWORK_LIMIT_EXCEEDED` (409) on a
    quality-control decision, then `ERR_APPEAL_LIMIT_EXCEEDED` (409) on an
    appeal."

    Design: Corner/state_machines/submitted_trade_in_refuses_authenticate_appeal_and_disposition
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    assert trade_in["status"] == "SUBMITTED"
    version_at_submission = trade_in["version"]

    # The only trigger declared out of SUBMITTED is receipt, so grading is
    # refused with the grading-specific state code.
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"],
            authenticate_trade_in_payload("GENUINE", "A"),
            AUTH1,
        ),
        "ERR_TRADE_IN_NOT_AUTHENTICATABLE",
        409,
    )

    # The state check precedes the appeal-limit check, so an un-graded row
    # answers the appeal state code rather than anything about the allowance.
    validate_error(
        api_client.appeal_trade_in(
            trade_in["id"],
            appeal_trade_in_payload(appeal_reason="grade seems low"),
            make_customer_headers(customer["id"]),
        ),
        "ERR_TRADE_IN_NOT_APPEALABLE",
        409,
    )

    validate_error(
        api_client.disposition_trade_in(
            trade_in["id"],
            disposition_payload("ACCEPT", "OWNED_INVENTORY"),
            AUTH1,
        ),
        "ERR_TRADE_IN_NOT_DISPOSITIONABLE",
        409,
    )

    after = fetch_trade_in(trade_in["id"])
    assert after["status"] == "SUBMITTED"
    assert after["version"] == version_at_submission
    assert after["appeal_count"] == 0
    assert after["authenticity_result"] == "PENDING"
    assert after["assessed_grade"] is None
    assert after["graded_by_user_id"] is None


def test_a_rejected_trade_in_is_terminal_for_every_action_endpoint():
    """Rejection locks the row and a second ACCEPT cannot resurrect it.

    PRD §3.4: "`ACCEPTED` and `REJECTED` are both terminal for a trade-in."
    PRD §3.4: "**Rejecting** is the disjoint branch. The trade-in moves to
    `REJECTED`, `reject_reason` is written from the request body,
    `appraised_credit_minor` is zeroed out — the provisional quote is explicitly
    withdrawn rather than left standing — and the version is bumped."
    PRD §3.4: "Nothing else happens at all: no brand-currency grant is created,
    no ledger entry is appended, no resale unit is created, and the
    participant's `credit_balance_minor`, `diverted_grams_total` and `version`
    are all left exactly as they were."
    PRD §3.2: "The trade-in must actually be in `SUBMITTED` — anything else is
    `ERR_TRADE_IN_NOT_RECEIVABLE`."

    Design: Corner/state_machines/rejected_trade_in_is_terminal_for_every_trigger
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", "A")
    rejected = disposition_trade_in(
        trade_in["id"],
        decision="REJECT",
        ownership_treatment=None,
        reject_reason="item does not match the declared model",
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["appraised_credit_minor"] == 0
    rejected_version = rejected["version"]

    validate_error(
        api_client.receive_trade_in(trade_in["id"], INTAKE),
        "ERR_TRADE_IN_NOT_RECEIVABLE",
        409,
    )
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"],
            authenticate_trade_in_payload("GENUINE", "A"),
            AUTH1,
        ),
        "ERR_TRADE_IN_NOT_AUTHENTICATABLE",
        409,
    )
    validate_error(
        api_client.appeal_trade_in(
            trade_in["id"],
            appeal_trade_in_payload(appeal_reason="please reconsider"),
            make_customer_headers(customer["id"]),
        ),
        "ERR_TRADE_IN_NOT_APPEALABLE",
        409,
    )
    validate_error(
        api_client.disposition_trade_in(
            trade_in["id"],
            disposition_payload("ACCEPT", "OWNED_INVENTORY"),
            AUTH1,
        ),
        "ERR_TRADE_IN_NOT_DISPOSITIONABLE",
        409,
    )

    after = fetch_trade_in(trade_in["id"])
    assert after["status"] == "REJECTED"
    assert after["version"] == rejected_version
    assert after["appraised_credit_minor"] == 0

    # The refused ACCEPT minted nothing on either cascade branch.
    _, grant_meta = validate_paginated(
        api_client.list_credit_grants(ADMIN, {"trade_in_id": trade_in["id"]})
    )
    assert grant_meta["total_count"] == 0
    _, unit_meta = validate_paginated(
        api_client.list_resale_units(ADMIN, {"trade_in_id": trade_in["id"]})
    )
    assert unit_meta["total_count"] == 0


def _appealed_grade_a_footwear_trade_in():
    """Ava's mail-in grade-A trade-in, graded A by auth-001 and then appealed.

    Both FOOTWEAR grade policies are live so the re-grade to B is priceable.
    """
    create_grade_policy(GRADE_POLICY_FOOTWEAR_A)
    create_grade_policy(GRADE_POLICY_FOOTWEAR_B)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="FOOTWEAR",
        declared_grade="A",
        msrp_minor=120000,
        item_mass_grams=900,
    )
    receive_trade_in(trade_in["id"])
    authenticate_trade_in(trade_in["id"], "GENUINE", "A", headers=AUTH1)
    appealed = appeal_trade_in(
        trade_in["id"], customer, appeal_reason="the sole wear is cosmetic only"
    )
    return customer, appealed


def test_the_contested_grader_may_not_resolve_the_appeal_they_caused():
    """A second Authenticator re-grades and the quote survives untouched.

    PRD §3.3: "It is the same grading operation with one additional guard: the
    acting `X-User-ID` must differ from the `graded_by_user_id` currently
    recorded on the trade-in, so the grader whose verdict was contested cannot
    review their own work."
    PRD §3.3: "A self-review is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.3: "The re-grade overwrites `authenticity_result`, overwrites
    `assessed_grade`, and replaces `graded_by_user_id` with the second grader's
    identifier, then bumps the version."
    PRD §3.3: "It deliberately leaves `appraised_credit_minor` alone: even
    though the assessed grade may differ sharply from the declared one, the
    trade-in continues to display the provisional quote right up until
    disposition."

    Design: Corner/state_machines/appeal_regrade_needs_a_second_authenticator_then_exhausts_the_appeal_limit
    """
    customer, appealed = _appealed_grade_a_footwear_trade_in()
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1
    assert appealed["graded_by_user_id"] == AUTHENTICATOR_ID
    # Base 120000 * 3500bp = 42000, plus a 1000bp mail-in bonus of 4200.
    assert appealed["appraised_credit_minor"] == 46200
    version_when_appealed = appealed["version"]

    validate_error(
        api_client.authenticate_trade_in(
            appealed["id"],
            authenticate_trade_in_payload("GENUINE", "B"),
            AUTH1,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )

    regraded = authenticate_trade_in(appealed["id"], "GENUINE", "B", headers=AUTH2)
    assert regraded["status"] == "AUTHENTICATED"
    assert regraded["authenticity_result"] == "GENUINE"
    assert regraded["assessed_grade"] == "B"
    assert regraded["graded_by_user_id"] == SECOND_AUTHENTICATOR_ID
    # The re-grade to B does not re-run the appraisal, so the grade-A quote
    # computed at submission is still what the row displays.
    assert regraded["appraised_credit_minor"] == 46200
    assert regraded["version"] > version_when_appealed
    assert regraded["appeal_count"] == 1


def test_the_single_appeal_allowance_is_exhausted_by_the_first_appeal():
    """A second appeal after the re-grade is refused on the counted limit.

    PRD §3.3: "And `appeal_count`, which starts at 0 and may never exceed 1,
    must still be below the programme's single-appeal allowance; a second appeal
    is refused with `ERR_APPEAL_LIMIT_EXCEEDED`."
    PRD §3.3: "Because the appeal allowance is one, a trade-in can pass through
    `APPEALED` at most once, and the cycle therefore cannot spin."
    PRD §3.3: "A successful appeal increments `appeal_count` by one and bumps
    the version."

    Design: Corner/state_machines/appeal_regrade_needs_a_second_authenticator_then_exhausts_the_appeal_limit
    """
    customer, appealed = _appealed_grade_a_footwear_trade_in()
    regraded = authenticate_trade_in(appealed["id"], "GENUINE", "B", headers=AUTH2)
    assert regraded["status"] == "AUTHENTICATED"
    assert regraded["appeal_count"] == 1

    validate_error(
        api_client.appeal_trade_in(
            appealed["id"],
            appeal_trade_in_payload(appeal_reason="still unhappy"),
            make_customer_headers(customer["id"]),
        ),
        "ERR_APPEAL_LIMIT_EXCEEDED",
        409,
    )

    after = fetch_trade_in(appealed["id"])
    assert after["status"] == "AUTHENTICATED"
    assert after["appeal_count"] == 1
    assert after["version"] == regraded["version"]


def test_an_illegal_authenticity_enum_is_refused_before_the_state_check():
    """Body shape outranks state, and state outranks a successful grading.

    PRD §2.11: "**Body shape.** On every creating and modifying request, all
    required fields must be present, every enumerated value must be inside its
    declared set, every money, mass and basis-point field must be a non-negative
    integer, and every timestamp must be a valid ISO 8601 UTC instant, otherwise
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.3: "The request carries `authenticity_result`, which the grader sets
    to `GENUINE`, `COUNTERFEIT` or `INCONCLUSIVE` (`PENDING` being the
    pre-authentication value the field starts at), and optionally
    `assessed_grade`, the condition tier the grader assigns from `A`, `B`, `C`
    or `SALVAGE`."
    PRD §3.3: "Attempting to grade a trade-in whose status is neither
    `RECEIVED` nor `APPEALED` is `ERR_TRADE_IN_NOT_AUTHENTICATABLE`."
    PRD §3.3: "A successful grading writes `authenticity_result` and
    `assessed_grade` from the request, stamps the acting operator's identifier
    into `graded_by_user_id`, and increments the trade-in's version."

    Design: Corner/validations/invalid_enum_outranks_the_trade_in_state_error
    """
    create_grade_policy(GRADE_POLICY_OUTERWEAR_B)
    create_credit_policy(CREDIT_POLICY_CORE)
    create_store_location()
    customer = create_customer(email="ava@example.com", full_name="Ava Reyes",
                              loyalty_tier="PLUS")
    trade_in = create_trade_in(
        customer,
        channel="MAIL_IN",
        product_category="OUTERWEAR",
        declared_grade="B",
        msrp_minor=50000,
        item_mass_grams=1400,
    )
    assert trade_in["status"] == "SUBMITTED"
    # Base 50000 * 2000bp = 10000 plus a 1000bp mail-in bonus of 1000; the
    # provisional variant contributes no loyalty term.
    assert trade_in["appraised_credit_minor"] == 11000

    # The row's own state would justify a 409, but the illegal enum is caught
    # first at admission step 3.
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"],
            {"authenticity_result": "BOGUS"},
            AUTH1,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    # With a legal enum the same un-received row does answer the state error.
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"],
            authenticate_trade_in_payload("GENUINE", "B"),
            AUTH1,
        ),
        "ERR_TRADE_IN_NOT_AUTHENTICATABLE",
        409,
    )

    received = receive_trade_in(trade_in["id"])
    assert received["status"] == "RECEIVED"

    graded = validate_success(
        api_client.authenticate_trade_in(
            trade_in["id"],
            authenticate_trade_in_payload("GENUINE", "B"),
            AUTH1,
        )
    )
    assert graded["status"] == "AUTHENTICATED"
    assert graded["graded_by_user_id"] == AUTHENTICATOR_ID
    assert graded["assessed_grade"] == "B"
    # Grading leaves the provisional quote alone.
    assert graded["appraised_credit_minor"] == 11000
