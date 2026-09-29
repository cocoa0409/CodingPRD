"""Role admission: what each role may do, and what its authority does not buy it.

The role model here is segregation of duties rather than hierarchy, so the tests
below deliberately probe the `ProgramAdmin` against operational endpoints it does
not hold, and probe the operational roles against each other. Every refusal is
checked to have left the row it addressed exactly where it was.
"""

from test_helpers import (
    ADMIN,
    AUTH1,
    GRADE_POLICY_OUTERWEAR_B,
    GRADE_POLICY_OUTERWEAR_C,
    INTAKE,
    MERCH,
    TECH1,
    TEST_USERS,
    api_client,
    assert_channel,
    assert_credit_policy,
    assert_customer,
    assert_grade_policy,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_refurb_order,
    assert_unit_dimensions,
    authenticate_trade_in_payload,
    appeal_trade_in_payload,
    create_channel_payload,
    create_credit_policy_payload,
    create_customer,
    create_customer_payload,
    create_grade_policy_payload,
    create_refurb_order_payload,
    create_trade_in,
    create_trade_in_payload,
    disposition_payload,
    create_refurb_task_payload,
    fetch_customer,
    fetch_trade_in,
    fetch_unit,
    list_unit_payload,
    make_customer_headers,
    patch_customer,
    qc_decision_payload,
    receive_trade_in,
    return_request_payload,
    authenticate_trade_in,
    setup_accepted_trade_in,
    setup_fulfilled_order,
    setup_estate,
    validate_error,
    validate_paginated,
    validate_success,
)

CUSTOMER_ROLE = TEST_USERS["customer_headers"]


def test_the_configuration_surface_belongs_to_the_program_admin_alone():
    """Four creates, a PATCH and the sweep are refused, then all six land for the admin.

    PRD §2.1: "A caller who is authenticated but whose `X-User-Role` is not among the
    roles that the target endpoint admits is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."
    PRD §3.1: "Nothing can be traded in until a `ProgramAdmin` has enrolled the
    participant."
    PRD §3.1: "A `loyalty_tier` may be supplied and is one of `STANDARD` or `PLUS`; when
    it is omitted the customer is enrolled as `STANDARD`."
    PRD §3.1: "A `ProgramAdmin` may later revise a customer's `status`, their
    `loyalty_tier`, or both, and each such edit is a mutation of the customer row."
    PRD §3.9: "`EXHAUSTED` grants are skipped because their `remaining_minor` is already
    zero, and grants already `EXPIRED` are skipped too, which makes a repeated sweep
    idempotent — it expires nothing and reports zeros."
    PRD §2.6: "Most resources — customers, condition-tier policies, brand-currency
    policies, store locations, refurbishment bays, channels, trade-ins, brand-currency
    grants, resale units, refurbishment orders, markdown campaigns, resale orders and
    diversion reports — additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation of the row, and `version`, an integer that is
    initialized to 1 when the row is created and incremented by exactly one on every
    mutation."

    Design: Corner/rbac/program_admin_configuration_surface_is_exclusive
    """
    # Each create is attempted by a different role that the endpoint does not admit.
    validate_error(
        api_client.create_customer(create_customer_payload(), CUSTOMER_ROLE),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_grade_policy(create_grade_policy_payload(), MERCH),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_credit_policy(create_credit_policy_payload(), INTAKE),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_channel(create_channel_payload(), TECH1),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.run_credit_grant_expiry(MERCH),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    # The refused create left no row behind: the same unique email is still free.
    customer = validate_success(
        api_client.create_customer(create_customer_payload(), ADMIN), 201
    )
    assert_customer(customer)
    assert customer["loyalty_tier"] == "STANDARD"
    assert customer["status"] == "ACTIVE"
    assert customer["version"] == 1

    validate_error(
        api_client.patch_customer(customer["id"], {"loyalty_tier": "PLUS"}, MERCH),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    assert fetch_customer(customer["id"])["loyalty_tier"] == "STANDARD"

    amended = patch_customer(customer["id"], {"loyalty_tier": "PLUS"})
    assert amended["loyalty_tier"] == "PLUS"
    assert amended["version"] == 2

    # The other three creates land on the same payloads that were just refused.
    grade_policy = validate_success(
        api_client.create_grade_policy(create_grade_policy_payload(), ADMIN), 201
    )
    assert_grade_policy(grade_policy)
    credit_policy = validate_success(
        api_client.create_credit_policy(create_credit_policy_payload(), ADMIN), 201
    )
    assert_credit_policy(credit_policy)
    channel = validate_success(
        api_client.create_channel(create_channel_payload(), ADMIN), 201
    )
    assert_channel(channel)

    # And the sweep runs for the admin, finding nothing on a grant-free programme.
    sweep = validate_success(api_client.run_credit_grant_expiry(ADMIN))
    assert sweep["expired_grant_count"] == 0
    assert sweep["expired_amount_minor"] == 0
    assert sweep["affected_customer_count"] == 0


def test_receipt_and_grading_admit_only_their_own_operator():
    """The admin's configuration authority buys no shortcut through intake.

    PRD §3.2: "Taking physical custody is the `IntakeAgent`'s exclusive act, and it
    advances the trade-in from `SUBMITTED` to `RECEIVED`."
    PRD §3.2: "Receipt writes `received_at` from the logical clock and increments the
    trade-in's version."
    PRD §3.3: "Authentication is the `Authenticator`'s exclusive act and it is the same
    operation whether it is happening for the first time or as the resolution of an
    appeal — which is why it appears twice in the trade-in's state machine, once as the
    leg from `RECEIVED` to `AUTHENTICATED` and once as the leg from `APPEALED` to
    `AUTHENTICATED`."
    PRD §3.3: "A successful grading writes `authenticity_result` and `assessed_grade`
    from the request, stamps the acting operator's identifier into `graded_by_user_id`,
    and increments the trade-in's version."
    PRD §2.1: "A caller who is authenticated but whose `X-User-Role` is not among the
    roles that the target endpoint admits is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/rbac/intake_and_authentication_steps_admit_only_their_own_role
    """
    setup_estate()
    customer = create_customer()
    trade_in = create_trade_in(customer, channel="MAIL_IN")
    assert trade_in["status"] == "SUBMITTED"
    assert_null(trade_in["received_at"], "received_at")

    # Neither the grader nor the admin may take custody.
    validate_error(
        api_client.receive_trade_in(trade_in["id"], AUTH1),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.receive_trade_in(trade_in["id"], ADMIN),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    untouched = fetch_trade_in(trade_in["id"])
    assert untouched["status"] == "SUBMITTED"
    assert_null(untouched["received_at"], "received_at")
    assert untouched["version"] == trade_in["version"]

    received = receive_trade_in(trade_in["id"])
    assert received["status"] == "RECEIVED"
    assert_instant(received["received_at"], "2026-08-01T00:00:00Z", "received_at")

    # And neither the intake agent nor the admin may rule on the grade.
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"], authenticate_trade_in_payload("GENUINE", "B"), INTAKE
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"], authenticate_trade_in_payload("GENUINE", "B"), ADMIN
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    still_received = fetch_trade_in(trade_in["id"])
    assert still_received["status"] == "RECEIVED"
    assert_null(still_received["assessed_grade"], "assessed_grade")

    graded = authenticate_trade_in(trade_in["id"])
    assert graded["status"] == "AUTHENTICATED"
    assert graded["assessed_grade"] == "B"
    assert graded["graded_by_user_id"] == "auth-001"


def test_the_refurb_and_listing_exclusives_are_split_per_operation():
    """The admin may book and sign a job it may not start, log or submit.

    PRD §3.5: "Scheduling refurbishment is open to a `RefurbTechnician` or a
    `ProgramAdmin`."
    PRD §3.5: "Starting work is exclusive to a `RefurbTechnician` and serves two legs of
    the refurbishment cycle."
    PRD §3.5: "Effort is captured as **immutable task lines**, appended only by a
    `RefurbTechnician` and only while the order is `IN_PROGRESS`; logging against an
    order in any other status is `ERR_REFURB_ORDER_NOT_LOGGABLE`."
    PRD §3.5: "Submitting for quality control is again exclusive to a
    `RefurbTechnician` and moves the order from `IN_PROGRESS` to `QC_PENDING`; any other
    starting status is `ERR_REFURB_ORDER_NOT_QC_SUBMITTABLE`."
    PRD §3.5: "The **quality-control decision** may be signed by a `RefurbTechnician` or
    a `ProgramAdmin`, carries a `decision` of `PASS`, `FAIL` or `SALVAGE`, and optionally
    carries a `viability_override_reason`."
    PRD §3.6: "Listing is the `MerchandisingManager`'s exclusive act, and it is the
    point at which the anti-cannibalization policy of §3.1 becomes an enforced
    constraint rather than a stated intention."

    Design: Corner/rbac/refurb_execution_and_listing_exclusives_are_not_interchangeable
    """
    estate = setup_estate()
    scenario = setup_accepted_trade_in(estate)
    unit = scenario["unit"]

    # The shared write: the admin may book the bay.
    order = validate_success(
        api_client.create_refurb_order(
            create_refurb_order_payload(
                unit["id"],
                estate["bay"]["id"],
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
                unit["version"],
            ),
            ADMIN,
        ),
        201,
    )
    assert_refurb_order(order)
    assert order["status"] == "SCHEDULED"
    assert_null(order["performed_by_user_id"], "performed_by_user_id")

    # Starting is not shared, not even with the role that booked it.
    validate_error(
        api_client.start_refurb_order(order["id"], ADMIN),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.start_refurb_order(order["id"], MERCH),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    started = validate_success(api_client.start_refurb_order(order["id"], TECH1))
    assert started["status"] == "IN_PROGRESS"
    assert started["performed_by_user_id"] == "tech-001"

    # Logging effort and submitting for QC are the technician's alone.
    validate_error(
        api_client.create_refurb_task(
            order["id"], create_refurb_task_payload("REPAIR", 10, 0), ADMIN
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.submit_refurb_order_qc(order["id"], ADMIN),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    tasks, task_meta = validate_paginated(
        api_client.list_refurb_tasks(order["id"], ADMIN)
    )
    # The refused log wrote no line.
    assert_pagination_meta(task_meta, 0)
    assert tasks == []

    submitted = validate_success(api_client.submit_refurb_order_qc(order["id"], TECH1))
    assert submitted["status"] == "QC_PENDING"
    assert submitted["logged_cost_minor"] == 0
    assert submitted["viability_ratio_bp"] == 0

    # The signature is shared, and admin-001 is not the tech-001 who did the work.
    decided = validate_success(
        api_client.decide_refurb_order_qc(
            order["id"], qc_decision_payload("PASS"), ADMIN
        )
    )
    assert decided["status"] == "COMPLETED"
    assert decided["qc_by_user_id"] == "admin-001"
    assert_unit_dimensions(fetch_unit(unit["id"]), "READY", "CAPITALIZED")

    # Listing belongs to the manager and to nobody else.
    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(estate["channel"]["id"]), TECH1
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(estate["channel"]["id"]), ADMIN
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    listed = validate_success(
        api_client.list_resale_unit(
            unit["id"], list_unit_payload(estate["channel"]["id"]), MERCH
        )
    )
    assert listed["lifecycle_state"] == "LISTED"
    # floor(50000 * 3900 / 10000).
    assert listed["list_price_minor"] == 19500


def test_the_customer_role_shares_every_operation_it_holds():
    """Submitting and appealing succeed; the staff writes on the same row do not.

    PRD §2.1: "**`Customer`** — the consumer participating in the programme:
    surrendering items, appealing grades, redeeming brand currency against resale
    purchases, and opening returns."
    PRD §3.2: "A trade-in is opened either by the `Customer` themself or by an
    `IntakeAgent` acting at the counter."
    PRD §3.3: "Grading is contestable exactly once."
    PRD §3.3: "An appeal takes the trade-in from `AUTHENTICATED` to `APPEALED` and may be
    raised by the `Customer` who owns it or, on their behalf, by a `ProgramAdmin`."
    PRD §3.3: "A successful appeal increments `appeal_count` by one and bumps the
    version."
    PRD §3.4: "Disposition is where the fork in the trade-in's lifecycle happens, and
    either the `Authenticator` or a `ProgramAdmin` may pull the lever."

    Design: Corner/rbac/customer_shared_operations_work_while_staff_writes_are_refused
    """
    # The grade this trade-in is later assessed at needs its own ACTIVE tier
    # policy, because PRD §3.3 refuses to record a grade it cannot price.
    setup_estate(
        grade_policies=(GRADE_POLICY_OUTERWEAR_B, GRADE_POLICY_OUTERWEAR_C)
    )
    customer = create_customer()
    own_headers = make_customer_headers(customer["id"])

    # The shared write and the shared reads all work for the participant.
    trade_in = validate_success(
        api_client.create_trade_in(
            create_trade_in_payload(customer["id"], channel="MAIL_IN"), own_headers
        ),
        201,
    )
    assert trade_in["status"] == "SUBMITTED"
    assert validate_success(api_client.get_trade_in(trade_in["id"], own_headers))[
        "id"
    ] == trade_in["id"]
    assert validate_success(api_client.get_customer(customer["id"], own_headers))[
        "email"
    ] == "ava@example.com"

    # Every staff-only step of the same workflow is refused for the participant.
    validate_error(
        api_client.receive_trade_in(trade_in["id"], own_headers),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.authenticate_trade_in(
            trade_in["id"], authenticate_trade_in_payload("GENUINE", "B"), own_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    validate_error(
        api_client.create_grade_policy(
            create_grade_policy_payload(condition_grade="C"), own_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )

    receive_trade_in(trade_in["id"])
    graded = authenticate_trade_in(trade_in["id"], "GENUINE", "C")
    assert graded["assessed_grade"] == "C"

    # Disposition sits on the very trade-in the participant may appeal, and it is
    # still refused.
    validate_error(
        api_client.disposition_trade_in(
            trade_in["id"], disposition_payload("ACCEPT"), own_headers
        ),
        "ERR_ROLE_NOT_PERMITTED",
        403,
    )
    assert fetch_trade_in(trade_in["id"])["status"] == "AUTHENTICATED"

    appealed = validate_success(
        api_client.appeal_trade_in(
            trade_in["id"], appeal_trade_in_payload(), own_headers
        )
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1
    assert appealed["version"] == graded["version"] + 1


def test_a_customers_reads_and_after_sale_writes_are_scoped_to_their_own_rows():
    """Ben holds the role and is still refused Ava's rows — 403, but never the role code.

    PRD §2.10: "A caller acting as `Customer` may only read or act on rows whose
    customer reference equals the `Customer` row bound to their `X-User-ID`; that applies
    to trade-ins, brand-currency grants, resale units, resale orders, ledger-entry reads
    and list filters alike, on every endpoint whose permitted roles include `Customer`."
    PRD §2.10: "Attempting to reach another customer's data is `ERR_NOT_RESOURCE_OWNER`
    (HTTP 403)."
    PRD §2.10: "Operator roles are not ownership-scoped and see the whole programme."
    PRD §2.11: "**Ownership.** The `Customer` scoping rule of §2.10 must hold, otherwise
    `ERR_NOT_RESOURCE_OWNER` (403)."
    PRD §3.8: "A `Customer` caller must be the order's own buyer, otherwise
    `ERR_NOT_RESOURCE_OWNER`."
    PRD §3.2: "A `Customer` reading either way sees only their own rows, per §2.10."

    Design: Corner/rbac/customer_reads_and_after_sale_writes_are_scoped_to_the_calling_owner
    """
    estate = setup_estate()
    scenario = setup_fulfilled_order(
        estate, seller_kwargs={"loyalty_tier": "PLUS"}
    )
    ava = scenario["customer"]
    order = scenario["order"]
    # The claim would clear the status gate, so only ownership can refuse it.
    assert order["status"] == "FULFILLED"

    ben = create_customer(email="ben@example.com", full_name="Ben Ortiz")
    ben_headers = make_customer_headers(ben["id"])

    validate_error(
        api_client.get_trade_in(scenario["trade_in"]["id"], ben_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api_client.list_trade_ins(ben_headers, {"customer_id": ava["id"]}),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api_client.get_credit_grant(scenario["grant"]["id"], ben_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api_client.list_credit_grant_ledger_entries(
            scenario["grant"]["id"], ben_headers
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api_client.get_resale_order(order["id"], ben_headers),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )
    validate_error(
        api_client.request_resale_order_return(
            order["id"], return_request_payload("BUYER_REMORSE"), ben_headers
        ),
        "ERR_NOT_RESOURCE_OWNER",
        403,
    )

    # An unfiltered Customer list is scoped to the caller rather than refused.
    rows, meta = validate_paginated(api_client.list_trade_ins(ben_headers))
    assert_pagination_meta(meta, 0)
    assert rows == []

    # The owner reads exactly the rows Ben could not.
    ava_headers = make_customer_headers(ava["id"])
    assert validate_success(
        api_client.get_trade_in(scenario["trade_in"]["id"], ava_headers)
    )["id"] == scenario["trade_in"]["id"]
    assert validate_success(api_client.get_resale_order(order["id"], ava_headers))[
        "status"
    ] == "FULFILLED"

    # And an operator role is not scoped at all, so the read path itself is sound.
    assert validate_success(api_client.get_resale_order(order["id"], MERCH))[
        "status"
    ] == "FULFILLED"
    assert fetch_trade_in(scenario["trade_in"]["id"])["status"] == "ACCEPTED"
