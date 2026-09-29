"""The logical clock, role-based access control, and optimistic concurrency at buyout.

Covers PRD §2.5 (the monotonic clock and its four-hop expiry cascade with a single stall
sweep), PRD §2.1 and §2.9 rungs 1–2 and 7 (header authentication, the peer-role authority
split, and segregation of duties inside the `BuyoutManager` role), and PRD §2.7 (version
pinning on the one guarded write, `POST /procurement/purchase-commitments`).
"""
from test_helpers import (
    ApiErrorId,
    BUYOUT_MANAGER_ID,
    TEST_USERS,
    api_client,
    assert_clock_state,
    assert_instant_equals,
    assert_material_package,
    assert_package_schedule_invariants,
    assert_project,
    assert_purchase_commitment,
    assert_substantiation_arithmetic,
    build_buyout_scenario,
    build_delivered_scenario,
    make_buyout_manager_headers,
    make_headers,
    make_supplier_rep_headers,
    open_project,
    read_clause,
    read_commitment,
    read_package,
    read_project,
    read_project_version,
    read_quote,
    register_package,
    register_supplier,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_change_order_request_payload,
    create_material_package_payload,
    create_purchase_commitment_payload,
    delivery_posture_payload,
    disposition_change_order_payload,
    set_clock_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
PROJECT_EXECUTIVE = TEST_USERS["project_executive_headers"]
DESIGN_ENGINEER = TEST_USERS["design_engineer_headers"]
OWNER_REP = TEST_USERS["owner_rep_headers"]

# Two distinct BuyoutManager operators — segregation of duties is keyed on X-User-ID.
PREPARER = make_buyout_manager_headers("buyer-anita")
SUBMITTER = make_buyout_manager_headers("buyer-diego")

EARLY_AUGUST = "2026-08-05T00:00:00.000Z"
JULY_ONLY_READING = (("2026-07", 310.00),)
JULY_AND_AUGUST_READINGS = (("2026-07", 310.00), ("2026-08", 322.00))

STEEL_FINAL_ESCALATION = 12909.90
STEEL_ADMIN_FEE = 451.85
STEEL_RUNNING_TOTAL = 13361.75

CLAIM_NARRATIVE = "Documented mill index escalation per executed clause"
UNKNOWN_CHANGE_ORDER_ID = "00000000-0000-4000-8000-000000000999"


def _setup_pending_buyout_on_a_proposed_clause() -> dict:
    """A PENDING PO attached to a never-executed clause on a quote expiring 2026-09-15.

    The clock is left at its 2026-08-01 startup default, so the whole four-hop cascade
    is still ahead of the sweep.
    """
    return build_buyout_scenario(
        readings=JULY_ONLY_READING, clause_stage="PROPOSED", countersign=False
    )


def _setup_delivered_steel_commitment() -> dict:
    """A steel buyout carried to DELIVERED with a FINAL escalation of 12909.90."""
    return build_delivered_scenario(release_at=EARLY_AUGUST, deliver_at=EARLY_AUGUST)


def _prepare_and_approve_claim(commitment_id: str, claimed_amount: float) -> dict:
    """Prepare, submit and owner-approve one change order, returning the approved row."""
    change_order = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=commitment_id,
                claimed_amount=claimed_amount,
                narrative=CLAIM_NARRATIVE,
            ),
            PREPARER,
        ),
        201,
    )
    validate_success(api_client.submit_change_order_request(change_order["id"], SUBMITTER))
    return validate_success(
        api_client.disposition_change_order_request(
            change_order["id"],
            disposition_change_order_payload(
                "APPROVED", owner_note="Escalation substantiated against published index"
            ),
            OWNER_REP,
        )
    )


def _setup_two_packages_one_bought_out() -> dict:
    """One project, two packages, two OPEN quotes, and the misc-metals PO already issued.

    The client's version token is read *before* that PO is issued, so it is stale by the
    time the steel buyout is attempted with it.
    """
    project = open_project()
    package = register_package(project["id"], estimated_cost=1200000.00)
    second_payload = create_material_package_payload(
        project_id=project["id"],
        scope_code="STRUCT-STEEL-02",
        description="Miscellaneous metals package",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=900000.00,
        fabrication_duration_days=60,
        delivery_transit_days=29,
    )
    # submittal_review_days is omitted deliberately so the server's default of 21 applies.
    second_payload.pop("submittal_review_days")
    package_2 = validate_success(
        api_client.create_material_package(second_payload, BUYOUT_MANAGER), 201
    )
    supplier = register_supplier()
    quote = submit_quote(package["id"], supplier["id"], base_price=1150000.00)
    quote_2 = submit_quote(package_2["id"], supplier["id"], base_price=880000.00)

    stale_version = read_project_version(project["id"])
    validate_success(
        api_client.create_purchase_commitment(
            create_purchase_commitment_payload(
                quote_id=quote_2["id"],
                expected_project_version=stale_version,
                po_number="PO-2996-0002",
                is_early_buyout=False,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    return {
        "project": project,
        "package": package,
        "package_2": package_2,
        "quote": quote,
        "quote_2": quote_2,
        "stale_version": stale_version,
    }


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade /
#   clock_sweep_expires_quote_lapses_clause_voids_po_stalls_package
# ---------------------------------------------------------------------------

def test_clock_sweep_reports_all_four_hops_in_its_audit_lists():
    """Advancing to the quote's expiry names the quote, clause, PO and package.

    PRD §2.5: "Hop one expires price holds: every quote still `OPEN` whose `expires_at`
    is at or before the supplied instant becomes `EXPIRED`"; "Hop two lapses
    negotiations"; "Hop three voids un-countersigned buyouts"; "Hop four returns scope to
    the market".
    PRD §2.5: "The clock response reports the resulting instant in `current_utc` and
    returns four audit lists — `expired_quote_ids`, `lapsed_agreement_ids`,
    `voided_commitment_ids` and `stalled_package_ids`".

    Design: Difficulty/transitive_cascade/clock_sweep_expires_quote_lapses_clause_voids_po_stalls_package
    """
    scenario = _setup_pending_buyout_on_a_proposed_clause()

    response = api_client.set_clock(
        set_clock_payload("2026-09-15T00:00:00.000Z"), BUYOUT_MANAGER
    )
    clock = validate_success(response)

    assert_clock_state(clock)
    assert_instant_equals(clock["current_utc"], "2026-09-15T00:00:00.000Z", "current_utc")
    assert scenario["quote"]["id"] in clock["expired_quote_ids"]
    assert scenario["agreement"]["id"] in clock["lapsed_agreement_ids"]
    assert scenario["commitment"]["id"] in clock["voided_commitment_ids"]
    assert scenario["package"]["id"] in clock["stalled_package_ids"]


def test_clock_sweep_expires_quote_lapses_clause_voids_po_and_stalls_package():
    """The four hops land on the rows themselves, and the buyout log falls back to zero.

    PRD §2.5: "every quote still `OPEN` whose `expires_at` is at or before the supplied
    instant becomes `EXPIRED`"; "every escalation agreement attached to a quote that just
    expired, and whose own status is `DRAFT`, `PROPOSED` or `COUNTERED`, becomes
    `LAPSED`"; "every purchase commitment whose `commitment_status` is `PENDING` and
    whose attached escalation agreement just lapsed becomes `VOIDED`".
    PRD §2.5: "Only after all four hops have run does a single stall sweep pass over the
    affected packages and mark every one that has no `OPEN` quote left as
    `SOURCING_STALLED`".
    PRD §3.5: "A voided commitment retains its `escalation_agreement_id` for audit even
    though the clause behind it is dead".
    PRD §3.1: "commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute
    nothing."

    Design: Difficulty/transitive_cascade/clock_sweep_expires_quote_lapses_clause_voids_po_stalls_package
    """
    scenario = _setup_pending_buyout_on_a_proposed_clause()
    validate_success(
        api_client.set_clock(
            set_clock_payload("2026-09-15T00:00:00.000Z"), BUYOUT_MANAGER
        )
    )

    assert read_quote(scenario["quote"]["id"])["status"] == "EXPIRED"
    assert read_clause(scenario["agreement"]["id"])["status"] == "LAPSED"

    commitment = read_commitment(scenario["commitment"]["id"])
    assert commitment["commitment_status"] == "VOIDED"
    assert commitment["escalation_agreement_id"] == scenario["agreement"]["id"]

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "SOURCING_STALLED"
    assert package["open_quote_count"] == 0

    project = read_project(scenario["project"]["id"])
    assert project["committed_total_cost"] == 0.00
    assert project["escalation_contingency_committed"] == 0.00


# ---------------------------------------------------------------------------
# Queue B: validations / temporal_validation_a_clock_rewind_is_rejected_and_the_clock_holds
# ---------------------------------------------------------------------------

def test_clock_rewind_is_rejected_and_the_clock_holds():
    """One millisecond earlier is a rewind; the identical instant is accepted.

    PRD §2.5: "The clock is monotonic: a target earlier than the current logical clock is
    refused with `ERR_CLOCK_REWIND` (HTTP 422). Setting the clock to precisely its current
    value is not a rewind and is accepted."
    PRD §3.1: "`float_days` ... is the number of whole days from the current logical clock
    forward to `release_for_fabrication_date`"; "`rff_risk_band` reads ... `ON_TRACK` when
    it is 15 or more."
    PRD §3.1: "`release_for_fabrication_date` is the `required_onsite_date` moved
    backwards by `lead_time_days` calendar days."

    Design: Corner/validations/temporal_validation_a_clock_rewind_is_rejected_and_the_clock_holds
    """
    project = open_project()
    package = register_package(project["id"])
    set_clock("2026-09-05T00:00:00.000Z")

    rewind = api_client.set_clock(
        set_clock_payload("2026-09-04T23:59:59.999Z"), BUYOUT_MANAGER
    )
    validate_error(rewind, ApiErrorId.ERR_CLOCK_REWIND.value, 422)

    held = validate_success(
        api_client.set_clock(set_clock_payload("2026-09-05T00:00:00.000Z"), BUYOUT_MANAGER)
    )
    assert_clock_state(held)
    assert_instant_equals(held["current_utc"], "2026-09-05T00:00:00.000Z", "current_utc")
    assert held["expired_quote_ids"] == []
    assert held["lapsed_agreement_ids"] == []
    assert held["voided_commitment_ids"] == []
    assert held["stalled_package_ids"] == []

    read_back = read_package(package["id"])
    assert_material_package(read_back)
    assert_package_schedule_invariants(read_back)
    assert read_back["float_days"] == 66
    assert read_back["rff_risk_band"] == "ON_TRACK"
    assert_instant_equals(
        read_back["release_for_fabrication_date"],
        "2026-11-10T00:00:00.000Z",
        "release_for_fabrication_date",
    )


# ---------------------------------------------------------------------------
# Queue B: rbac / role_exclusive_operation_a_buyout_manager_cannot_execute_a_clause
# ---------------------------------------------------------------------------

def test_a_buyout_manager_cannot_execute_a_clause():
    """Signing authority is exclusive to the ProjectExecutive, even on its own clause.

    PRD §2.1: "The `ProjectExecutive` is the contractor officer with signing authority: it
    executes escalation clauses, countersigns and cancels purchase orders, and suspends
    suppliers."
    PRD §2.1: "If the headers are well-formed but the declared role is not authorized for
    the endpoint being called, the request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /procurement/escalation-agreements/{id}/execute` — authorized roles
    "ProjectExecutive".

    Design: Corner/rbac/role_exclusive_operation_a_buyout_manager_cannot_execute_a_clause
    """
    scenario = build_buyout_scenario(
        readings=JULY_ONLY_READING, clause_stage="PROPOSED", issue=False
    )
    agreement_id = scenario["agreement"]["id"]

    refused = api_client.execute_escalation_agreement(agreement_id, BUYOUT_MANAGER)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    executed = validate_success(
        api_client.execute_escalation_agreement(agreement_id, PROJECT_EXECUTIVE)
    )
    assert executed["status"] == "EXECUTED"

    clause = read_clause(agreement_id)
    assert clause["status"] == "EXECUTED"
    # The refused call changed nothing: no negotiation round was consumed.
    assert clause["round_number"] == 0
    assert clause["cap_pct"] == 8.0
    assert clause["contractor_share_pct"] == 40.0
    assert read_quote(scenario["quote"]["id"])["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B: rbac / peer_roles_a_project_executive_can_neither_move_the_posture_nor_the_clock
# ---------------------------------------------------------------------------

def test_a_project_executive_can_neither_move_the_posture_nor_the_clock():
    """The officer who countersigned the PO holds no superset of the buyer's authority.

    PRD §2.1: "This is **not** a hierarchical override — a `ProjectExecutive` cannot
    register a package, issue a purchase order, move a delivery posture, or advance the
    clock. These are peer roles with disjoint authority over the same rows."
    PRD §3.6: "It stamps `released_for_fab_at` with the current logical clock".
    PRD §2.5: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`".

    Design: Corner/rbac/peer_roles_a_project_executive_can_neither_move_the_posture_nor_the_clock
    """
    scenario = build_buyout_scenario(readings=JULY_ONLY_READING)
    commitment_id = scenario["commitment"]["id"]

    refused_posture = api_client.set_delivery_posture(
        commitment_id, delivery_posture_payload("RELEASED_FOR_FAB"), PROJECT_EXECUTIVE
    )
    validate_error(refused_posture, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    refused_clock = api_client.set_clock(set_clock_payload(EARLY_AUGUST), PROJECT_EXECUTIVE)
    validate_error(refused_clock, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    released = validate_success(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("RELEASED_FOR_FAB"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(released)
    assert released["delivery_posture"] == "RELEASED_FOR_FAB"
    assert released["commitment_status"] == "COMMITTED"
    # The refused clock request left the clock at its startup default.
    assert_instant_equals(
        released["released_for_fab_at"], "2026-08-01T00:00:00.000Z", "released_for_fab_at"
    )


# ---------------------------------------------------------------------------
# Queue B: rbac /
#   role_denied_operation_supplier_and_engineer_reads_stop_at_the_project_and_the_change_order
# ---------------------------------------------------------------------------

def test_supplier_and_engineer_reads_stop_at_the_project_and_the_change_order():
    """"All GET endpoints" is not universal, and the role check outranks path existence.

    PRD §2.1: "The `OwnerRep` is the owner's representative: it has full read access,
    including the project buyout log and the change-order records".
    PRD §3.1: "The owner's representative sees this log alongside the procurement group
    and the signing officer; a supplier's representative and the engineer of record do
    not."
    PRD §3.9: "they are visible to the procurement group, the signing officer and the
    owner's representative — the supplier's representative and the engineer of record have
    no access to them at all."
    PRD §2.9: rung 2 "**Role authorization.** The declared role appears in the called
    endpoint's authorized list — otherwise `ERR_UNAUTHORIZED` (403)" precedes rung 4
    "**Path existence.** Every identifier in the path resolves, left to right".
    PRD §4: `GET /procurement/material-packages/{id}` — authorized roles "BuyoutManager,
    SupplierRep, ProjectExecutive, DesignEngineer, OwnerRep".

    Design: Corner/rbac/role_denied_operation_supplier_and_engineer_reads_stop_at_the_project_and_the_change_order
    """
    scenario = _setup_delivered_steel_commitment()
    supplier_headers = make_supplier_rep_headers(scenario["supplier"]["id"])
    approved = _prepare_and_approve_claim(scenario["commitment"]["id"], 20000.00)
    assert approved["substantiated_amount"] == STEEL_RUNNING_TOTAL

    validate_error(
        api_client.get_project(scenario["project"]["id"], supplier_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.get_change_order_request(approved["id"], DESIGN_ENGINEER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    # An unknown change-order id is still 403 for the engineer, never 404.
    validate_error(
        api_client.get_change_order_request(UNKNOWN_CHANGE_ORDER_ID, DESIGN_ENGINEER),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    # The package read is open to every role, including the supplier's representative.
    package = validate_success(
        api_client.get_material_package(scenario["package"]["id"], supplier_headers)
    )
    assert_material_package(package)
    # PRD §3.6: accepting delivery closes the scope package from BOUGHT_OUT to CLOSED.
    assert package["status"] == "CLOSED"

    owner_view = validate_success(
        api_client.get_change_order_request(approved["id"], OWNER_REP)
    )
    assert owner_view["substantiated_amount"] == STEEL_RUNNING_TOTAL


# ---------------------------------------------------------------------------
# Queue B: rbac / segregation_of_duties_the_preparer_of_a_change_order_may_not_submit_it
# ---------------------------------------------------------------------------

def test_the_preparer_of_a_change_order_may_not_submit_it():
    """The split is inside one role and keyed on X-User-ID, not on X-User-Role.

    PRD §2.1: "the operator who prepares an owner change order may not be the operator
    who submits it to the owner. Both are `BuyoutManager` users, and a self-submission is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "A `BuyoutManager` submits the change order to the owner, moving it from
    `PREPARED` to `SUBMITTED` and recording that caller's `X-User-ID` in
    `submitted_by_user_id` — but the submitting operator's `X-User-ID` **must differ** from
    the recorded `prepared_by_user_id`, and a self-submission is
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "The caller's `X-User-ID` is recorded in `prepared_by_user_id`,
    `submitted_by_user_id` and `owner_note` start null, and the request opens in
    `PREPARED`."
    PRD §3.9: "`substantiated_amount` is the lesser of that running total and the
    `claimed_amount`" — a claim of 12909.90 against a running total of 13361.75 caps at
    12909.90.

    Design: Corner/rbac/segregation_of_duties_the_preparer_of_a_change_order_may_not_submit_it
    """
    scenario = _setup_delivered_steel_commitment()
    change_order = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=scenario["commitment"]["id"],
                claimed_amount=STEEL_FINAL_ESCALATION,
                narrative=CLAIM_NARRATIVE,
            ),
            PREPARER,
        ),
        201,
    )
    assert change_order["prepared_by_user_id"] == "buyer-anita"

    self_submit = api_client.submit_change_order_request(change_order["id"], PREPARER)
    validate_error(self_submit, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    # The refused self-submission left the row in PREPARED with no submitter recorded.
    after_refusal = validate_success(
        api_client.get_change_order_request(change_order["id"], BUYOUT_MANAGER)
    )
    assert after_refusal["status"] == "PREPARED"
    assert after_refusal["submitted_by_user_id"] is None

    submitted = validate_success(
        api_client.submit_change_order_request(change_order["id"], SUBMITTER)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["prepared_by_user_id"] == "buyer-anita"
    assert submitted["submitted_by_user_id"] == "buyer-diego"

    read_back = validate_success(
        api_client.get_change_order_request(change_order["id"], BUYOUT_MANAGER)
    )
    assert_substantiation_arithmetic(read_back)
    assert read_back["status"] == "SUBMITTED"
    assert read_back["gross_documented_amount"] == STEEL_FINAL_ESCALATION
    assert read_back["admin_fee_pct"] == 3.5
    assert read_back["admin_fee_amount"] == STEEL_ADMIN_FEE
    assert read_back["substantiated_amount"] == STEEL_FINAL_ESCALATION


# ---------------------------------------------------------------------------
# Queue B: rbac /
#   role_unauthenticated_blank_role_blank_user_and_an_undeclared_role_are_all_401
# ---------------------------------------------------------------------------

def test_blank_role_blank_user_and_an_undeclared_role_are_all_401():
    """Three distinct header defects collapse into one 401 ahead of any role check.

    PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not one of the
    five declared roles, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: rung 1 "**Header authentication.** Both `X-User-ID` and `X-User-Role`
    present, non-empty, with `X-User-Role` naming one of the five declared roles —
    otherwise `ERR_UNAUTHENTICATED` (401). This applies to every endpoint."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/rbac/role_unauthenticated_blank_role_blank_user_and_an_undeclared_role_are_all_401
    """
    project = open_project()
    package = register_package(project["id"])

    blank_role = api_client.get_material_package(
        package["id"], make_headers(BUYOUT_MANAGER_ID, "")
    )
    blank_user = api_client.get_material_package(
        package["id"], make_headers("", "BuyoutManager")
    )
    undeclared_role = api_client.get_material_package(
        package["id"], make_headers(BUYOUT_MANAGER_ID, "Foreman")
    )

    for response in (blank_role, blank_user, undeclared_role):
        # "Foreman" is a plausible construction role but is not one of the five declared
        # roles, so rung 1 fires and the answer is 401, never 403.
        error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert error["message"].strip()
        meta = response.json()["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].strip()

    permitted = validate_success(
        api_client.get_material_package(package["id"], BUYOUT_MANAGER)
    )
    assert permitted["scope_code"] == "STRUCT-STEEL-01"


# ---------------------------------------------------------------------------
# Queue B: rbac /
#   role_denied_operation_the_owner_rep_reads_the_buyout_log_but_cannot_prepare_the_claim
# ---------------------------------------------------------------------------

def test_the_owner_rep_reads_the_buyout_log_but_cannot_prepare_the_claim():
    """Full read access is not write access: the owner disposes, it never prepares.

    PRD §2.1: "The `OwnerRep` is the owner's representative: it has full read access,
    including the project buyout log and the change-order records, and it is the only role
    that may dispose of a submitted change order."
    PRD §3.9: "A **ChangeOrderRequest** is prepared by a `BuyoutManager` against a
    `purchase_commitment_id`"; "Disposition belongs to the `OwnerRep`, who supplies a
    `disposition` of `APPROVED` or `REJECTED` and may attach an `owner_note`."
    PRD §4: `POST /procurement/change-order-requests` — authorized roles "BuyoutManager".
    PRD §3.9: "`substantiated_amount` is the lesser of that running total and the
    `claimed_amount`, rounded half up to 2 decimal places".
    PRD §3.9: "An approval feeds the project's `change_order_recovered_amount` on the next
    project read"; "an approved change order does **not** reduce the project's
    `escalation_contingency_committed`."

    Design: Corner/rbac/role_denied_operation_the_owner_rep_reads_the_buyout_log_but_cannot_prepare_the_claim
    """
    scenario = _setup_delivered_steel_commitment()

    listed, meta = validate_paginated(
        api_client.list_purchase_commitments(
            OWNER_REP, params={"material_package_id": scenario["package"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert listed[0]["id"] == scenario["commitment"]["id"]

    owner_attempt = api_client.create_change_order_request(
        create_change_order_request_payload(
            purchase_commitment_id=scenario["commitment"]["id"],
            claimed_amount=STEEL_FINAL_ESCALATION,
            narrative=CLAIM_NARRATIVE,
        ),
        OWNER_REP,
    )
    validate_error(owner_attempt, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    change_order = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=scenario["commitment"]["id"],
                claimed_amount=STEEL_FINAL_ESCALATION,
                narrative=CLAIM_NARRATIVE,
            ),
            PREPARER,
        ),
        201,
    )
    validate_success(api_client.submit_change_order_request(change_order["id"], SUBMITTER))

    disposed = validate_success(
        api_client.disposition_change_order_request(
            change_order["id"],
            disposition_change_order_payload(
                "APPROVED", owner_note="Escalation substantiated against published index"
            ),
            OWNER_REP,
        )
    )
    assert_substantiation_arithmetic(disposed)
    assert disposed["status"] == "OWNER_APPROVED"
    assert disposed["gross_documented_amount"] == STEEL_FINAL_ESCALATION
    assert disposed["admin_fee_pct"] == 3.5
    assert disposed["admin_fee_amount"] == STEEL_ADMIN_FEE
    # The claim caps the running total of 13361.75 back down to what was claimed.
    assert disposed["substantiated_amount"] == STEEL_FINAL_ESCALATION

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["change_order_recovered_amount"] == STEEL_FINAL_ESCALATION
    assert project["escalation_contingency_committed"] == STEEL_FINAL_ESCALATION
    assert project["escalation_contingency_remaining"] == 487090.10


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers /
#   optimistic_concurrency_a_stale_project_token_is_412_and_frees_its_po_number
# ---------------------------------------------------------------------------

def test_a_stale_project_token_is_412_and_frees_its_po_number():
    """A refused buyout reserves nothing — the same PO number succeeds on the retry.

    PRD §2.7: "If that value does not equal the project's current `version`, the request is
    rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) and nothing is created."
    PRD §2.4: "A project's `version` increments by exactly 1 only on the five events that
    genuinely enlarge or unwind a commitment: issuing a purchase commitment,
    countersigning it, cancelling it, releasing its material for fabrication, and accepting
    its delivery."
    PRD §3.5: "a `po_number` of 1 to 40 characters that must be globally unique compared
    case-sensitively (`ERR_DUPLICATE_PO_NUMBER` otherwise)".
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope
    package belonging to the project — every package, with no status filter at all".
    PRD §3.1: "commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute nothing."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_a_stale_project_token_is_412_and_frees_its_po_number
    """
    scenario = _setup_two_packages_one_bought_out()
    assert scenario["stale_version"] == 1

    refused = api_client.create_purchase_commitment(
        create_purchase_commitment_payload(
            quote_id=scenario["quote"]["id"],
            expected_project_version=scenario["stale_version"],
            po_number="PO-2996-0001",
            is_early_buyout=False,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)

    # "nothing changes": the sibling buyout's version bump is the only one on the row.
    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["version"] == 2

    fresh_version = read_project_version(scenario["project"]["id"])
    assert fresh_version == 2

    issued = validate_success(
        api_client.create_purchase_commitment(
            create_purchase_commitment_payload(
                quote_id=scenario["quote"]["id"],
                expected_project_version=fresh_version,
                po_number="PO-2996-0001",
                is_early_buyout=False,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_purchase_commitment(issued)
    # The refused attempt did not consume PO-2996-0001, so this is not a duplicate.
    assert issued["po_number"] == "PO-2996-0001"
    assert issued["committed_base_cost"] == 1150000.00
    assert issued["commitment_status"] == "PENDING"

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "BOUGHT_OUT"

    project = read_project(scenario["project"]["id"])
    assert project["version"] == 3
    assert project["estimated_total_cost"] == 2100000.00
    assert project["committed_total_cost"] == 0.00


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_complexity_layers /
#   optimistic_concurrency_the_version_counts_ledger_writes_not_every_write
# ---------------------------------------------------------------------------

def test_the_project_version_counts_ledger_writes_not_every_write():
    """Five ledger events move the version; reads and the fabrication step do not.

    PRD §2.4: "A project's `version` increments by exactly 1 only on the five events that
    genuinely enlarge or unwind a commitment: issuing a purchase commitment,
    countersigning it, cancelling it, releasing its material for fabrication, and accepting
    its delivery. Reading a project a hundred times leaves its `version` where it was."
    PRD §2.10: "Nothing about a derivation counts as a mutation: it never refreshes
    `updated_at` and never increments `version`."
    PRD §3.6: "**Starting fabrication** moves the posture from `RELEASED_FOR_FAB` to
    `FABRICATING` and does nothing else at all — it refreshes `updated_at` and touches no
    money, no project version, and no other row."
    PRD §3.6: "At **release**, the reading used is the one for the clause's `index_code`
    with the **greatest period at or before** the current clock month"; "At **delivery**,
    the reading used is the one whose `period` equals the current clock month exactly."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`".

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_the_version_counts_ledger_writes_not_every_write
    """
    scenario = build_buyout_scenario(readings=JULY_AND_AUGUST_READINGS, issue=False)
    project_id = scenario["project"]["id"]
    set_clock("2026-08-20T00:00:00.000Z")
    assert read_project_version(project_id) == 1

    commitment = validate_success(
        api_client.create_purchase_commitment(
            create_purchase_commitment_payload(
                quote_id=scenario["quote"]["id"],
                expected_project_version=1,
                escalation_agreement_id=scenario["agreement"]["id"],
                is_early_buyout=False,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    commitment_id = commitment["id"]
    assert commitment["po_number"] == "PO-2996-0001"
    assert commitment["escalation_variant"] == "NONE"
    assert read_project_version(project_id) == 2

    # Derivation on read is not a mutation, on any of the reachable rows.
    read_commitment(commitment_id)
    read_package(scenario["package"]["id"])
    read_clause(scenario["agreement"]["id"])
    read_quote(scenario["quote"]["id"])
    assert read_project_version(project_id) == 2

    countersigned = validate_success(
        api_client.commit_purchase_commitment(commitment_id, PROJECT_EXECUTIVE)
    )
    assert countersigned["commitment_status"] == "COMMITTED"
    assert read_project_version(project_id) == 3

    released = validate_success(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("RELEASED_FOR_FAB"), BUYOUT_MANAGER
        )
    )
    assert released["delivery_posture"] == "RELEASED_FOR_FAB"
    assert released["escalation_variant"] == "PROVISIONAL"
    assert released["escalation_accrued"] == STEEL_FINAL_ESCALATION
    assert released["escalation_index_period"] == "2026-08"
    assert read_project_version(project_id) == 4

    fabricating = validate_success(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("FABRICATING"), BUYOUT_MANAGER
        )
    )
    assert fabricating["delivery_posture"] == "FABRICATING"
    # Starting fabrication touches no money and no project version.
    assert fabricating["escalation_accrued"] == STEEL_FINAL_ESCALATION
    assert read_project_version(project_id) == 4

    delivered = validate_success(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(delivered)
    assert delivered["delivery_posture"] == "DELIVERED"
    assert delivered["commitment_status"] == "CLOSED"
    assert delivered["escalation_variant"] == "FINAL"
    assert delivered["escalation_accrued"] == STEEL_FINAL_ESCALATION
    assert delivered["escalation_index_period"] == "2026-08"
    assert_instant_equals(delivered["delivered_at"], "2026-08-20T00:00:00.000Z", "delivered_at")
    assert read_project_version(project_id) == 5

    package = read_package(scenario["package"]["id"])
    assert_package_schedule_invariants(package)
    assert package["status"] == "CLOSED"

    project = read_project(project_id)
    assert_project(project)
    assert project["version"] == 5
    assert project["escalation_contingency_committed"] == STEEL_FINAL_ESCALATION
    assert project["escalation_contingency_remaining"] == 487090.10
    assert project["committed_total_cost"] == 1162909.90
    assert project["buyout_variance"] == 37090.10
