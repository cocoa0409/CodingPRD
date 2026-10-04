"""Corner queue: entity creation, defaults, constraints, retrieval, listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, is_valid_uuid,
    TEST_USERS,
    reset_clock, setup_region, setup_dealer, setup_department,
    setup_customer, setup_dealer_env, create_tx,
    create_region_payload, create_dealer_payload, create_department_payload,
    create_advisor_payload, create_customer_payload,
    create_question_set_payload, create_transaction_payload,
    assert_region, assert_dealer, assert_transaction,
)

ADMIN = TEST_USERS["admin_headers"]


def test_region_create_returns_declared_fields(api):
    """PRD §2.4: "id: a unique, server-generated UUID with no type prefix."
    and "version: an integer starting at 1 on creation and incremented on
    every mutation, including mutations driven by cascading side effects."
    PRD §4: "Operations that create new, stand-alone resources (a region, a
    dealer, a question set, a wave, a transaction, an appeal, a flag, a
    statement, a plan, a response) return 201 Created."

    Design: Corner/entities/region_create_returns_declared_fields
    """
    reset_clock()
    resp = api.create_region(
        create_region_payload(code="NE", name="Northeast"), ADMIN
    )
    region = validate_success(resp, expected_status=201)
    assert_region(region)
    assert region["code"] == "NE"
    assert region["name"] == "Northeast"
    assert region["version"] == 1


def test_dealer_create_returns_default_posture_and_counters(api):
    """PRD §3.1: "At creation, a dealer's posture is GOOD_STANDING, its
    confirmed_flag_count is 0, and both current_score_adjusted and
    current_response_rate are null until the first wave close writes them."

    Design: Corner/entities/dealer_create_returns_default_posture_and_counters
    """
    reset_clock()
    region = setup_region()
    dealer = validate_success(api.create_dealer(
        create_dealer_payload(region["id"], name="Acme", dealer_code="ACME"),
        ADMIN,
    ), 201)
    assert_dealer(dealer)
    assert dealer["posture"] == "GOOD_STANDING"
    assert dealer["confirmed_flag_count"] == 0
    assert dealer["current_score_adjusted"] is None
    assert dealer["current_response_rate"] is None


def test_dealer_create_duplicate_dealer_code_rejected(api):
    """PRD §3.1: "A Dealer is created against a region by supplying
    region_id, a display name, and a factory-issued dealer_code that must be
    unique across all dealers — duplicates are rejected with ERR_VALIDATION."

    Design: Corner/entities/dealer_create_duplicate_dealer_code_rejected
    """
    reset_clock()
    region = setup_region()
    validate_success(api.create_dealer(
        create_dealer_payload(region["id"], name="A", dealer_code="DUP"),
        ADMIN,
    ), 201)
    err = api.create_dealer(
        create_dealer_payload(region["id"], name="B", dealer_code="DUP"),
        ADMIN,
    )
    validate_error(err, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_question_set_comparability_factor_lower_bound_exclusive(api):
    """PRD §3.2: "The comparability_factor is a multiplier strictly greater
    than 0.5 and at most 1.5; it maps this set's scores onto its
    predecessor's scale so that year-over-year score history remains
    meaningful when the instrument changes." and "Violations are rejected
    with ERR_VALIDATION."

    Design: Corner/entities/question_set_create_invalid_comparability_factor_rejected
    """
    reset_clock()
    err = api.create_question_set(
        create_question_set_payload(code="QS-X", comparability_factor=0.5),
        ADMIN,
    )
    validate_error(err, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_dealer_get_round_trips_stored_fields(api):
    """PRD §3.1: "A Dealer is created against a region by supplying
    region_id, a display name, and a factory-issued dealer_code that must be
    unique across all dealers — duplicates are rejected with ERR_VALIDATION."
    PRD §4: "All list and single-resource reads return 200 OK."

    Design: Corner/entities/dealer_get_returns_stored_fields
    """
    reset_clock()
    region = setup_region()
    dealer = validate_success(api.create_dealer(
        create_dealer_payload(region["id"], name="Acme", dealer_code="ACME"),
        ADMIN,
    ), 201)
    fetched = validate_success(api.get_dealer(dealer["id"], ADMIN), 200)
    assert fetched["name"] == "Acme"
    assert fetched["dealer_code"] == "ACME"
    assert fetched["region_id"] == region["id"]


def test_dealer_get_unknown_id_returns_not_found(api):
    """PRD §2.6: "Endpoints whose paths contain multiple resource identifiers
    validate them left to right. The system confirms each path segment
    against existence in order; the first segment that does not resolve
    yields ERR_NOT_FOUND (HTTP 404) for that segment, and no further
    validation runs."

    Design: Corner/entities/dealer_get_not_found_returns_404
    """
    reset_clock()
    err = api.get_dealer(NON_EXISTENT_UUID, ADMIN)
    validate_error(err, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_dealers_list_pagination_envelope(api):
    """PRD §2.3: "The limit parameter specifies the maximum number of items
    returned; it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at 100. The offset parameter specifies the number of items to skip
    and defaults to 0." and "The meta block of a paginated response carries
    limit, offset, total_count, and has_more, where has_more is true when the
    requested window does not exhaust the underlying collection."

    Design: Corner/entities/dealers_list_pagination_envelope
    """
    reset_clock()
    region = setup_region()
    for code in ("A", "B", "C"):
        setup_dealer(region["id"], code=code, name=code)
    data, meta = validate_paginated(
        api.list_dealers(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    data2, meta2 = validate_paginated(
        api.list_dealers(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_transaction_create_missing_margin_rejected(api):
    """PRD §3.3: "A PlatformAdmin records the visit with dealer_id,
    department_id, an optional advisor_id, the visiting customer_id, the
    visit kind (one of SALE or SERVICE_VISIT), the completed_at timestamp,
    and the margin_cents attributable to the visit — an integer at or above
    zero."
    PRD §2.9: "19. Request shape — required fields present, well-typed,
    enums valid (ERR_INVALID_REQUEST)."

    Design: Corner/entities/transaction_create_required_margin_missing
    """
    env = setup_dealer_env(dealer_code="A", customers=1)
    cust = env["customers"][0]
    payload = create_transaction_payload(
        env["dealer"]["id"], env["dept"]["id"], cust["id"],
    )
    del payload["margin_cents"]
    err = api.create_transaction(payload, ADMIN)
    validate_error(err, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_transaction_is_immutable_record_without_version(api):
    """PRD §2.4: "The exception is the Transaction entity, which is immutable
    after recording and therefore carries only id and created_at — both
    updated_at and version are absent. This asymmetry matters for optimistic
    concurrency: transactions cannot be the parent of an OCC contract because
    there is nothing to version against."

    Design: Corner/entities/transaction_common_fields_false_immutability
    """
    env = setup_dealer_env(dealer_code="A", customers=1)
    cust = env["customers"][0]
    tx = validate_success(api.create_transaction(
        create_transaction_payload(
            env["dealer"]["id"], env["dept"]["id"], cust["id"],
            margin_cents=100,
        ),
        ADMIN,
    ), 201)
    assert_transaction(tx)
    assert is_valid_uuid(tx["id"])
    assert "updated_at" not in tx
    assert "version" not in tx


def test_customer_create_do_not_contact_defaults_false(api):
    """PRD §3.1: "Customers are registered independently of any dealer, with
    full_name, email, phone, and an optional do_not_contact boolean
    defaulting to false."

    Design: Corner/entities/customer_create_do_not_contact_default_false
    """
    reset_clock()
    cust = validate_success(api.create_customer(
        create_customer_payload(full_name="C", email="c@x.com",
                                phone="5551234567"),
        ADMIN,
    ), 201)
    assert cust["do_not_contact"] is False


def test_advisor_employee_ref_unique_within_department(api):
    """PRD §3.1: "Within a department, an Advisor is registered with
    department_id, a full name, and an employee_ref unique within that
    department."
    PRD §2.9: "11. Structural constraints — uniqueness, schema shape,
    weights positive (ERR_VALIDATION)."

    Design: Corner/entities/advisor_create_employee_ref_unique_per_department
    """
    reset_clock()
    region = setup_region()
    dealer = setup_dealer(region["id"], code="A")
    dept_s = setup_department(dealer["id"], kind="SALES", name="Sales")
    dept_v = setup_department(dealer["id"], kind="SERVICE", name="Service")
    validate_success(api.create_advisor(
        create_advisor_payload(dept_s["id"], name="Joe", employee_ref="E1"),
        ADMIN,
    ), 201)
    err = api.create_advisor(
        create_advisor_payload(dept_s["id"], name="Jane", employee_ref="E1"),
        ADMIN,
    )
    validate_error(err, ApiErrorId.ERR_VALIDATION, expected_status=400)
    # the same employee_ref in a different department is allowed
    ok = validate_success(api.create_advisor(
        create_advisor_payload(dept_v["id"], name="Jane", employee_ref="E1"),
        ADMIN,
    ), 201)
    assert ok["department_id"] == dept_v["id"]
