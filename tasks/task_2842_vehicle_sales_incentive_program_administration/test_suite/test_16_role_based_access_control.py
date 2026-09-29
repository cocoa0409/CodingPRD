"""Role-based access control: the five exclusive writes, the non-uniform read
scopes, the two segregation-of-duties sites and the entity-backed Dealer id."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ALL_ROLE_NAMES,
    USER_AUDITOR_1,
    USER_CONTROLLER,
    USER_DESIGNER,
    USER_FSM,
    make_headers,
    make_program_designer_headers,
)

# A single operator principal that legitimately holds several roles. Operator
# ids are opaque and are never compared to any entity id, so the same string may
# act as a designer, a controller and an auditor.
USER_DUAL = "u-dual-1"

# A syntactically valid identifier that belongs to no Dealer row.
GHOST_DEALER_ID = "00000000-0000-4000-8000-00000000f005"

_OPERATOR_IDS = {
    "ProgramDesigner": USER_DESIGNER,
    "IncentiveController": USER_CONTROLLER,
    "FieldSalesManager": USER_FSM,
    "ClaimsAuditor": USER_AUDITOR_1,
}

OCT_01 = "2026-10-01T00:00:00.000Z"
NOV_01 = "2026-11-01T00:00:00.000Z"


def _role_headers(role: str, dealer_id: str) -> dict:
    """Headers for one role. The Dealer role's X-User-ID is a real Dealer id."""
    if role == "Dealer":
        return make_dealer_headers(dealer_id)
    return make_headers(_OPERATOR_IDS[role], role)


# --- The exclusive-write matrix ----------------------------------------------

CREATE_DEALER = "POST /incentives/dealers"
CREATE_PROGRAM = "POST /incentives/programs"
REPORT_DELIVERY = "POST /incentives/deliveries"
VALIDATE_DELIVERY = "POST /incentives/deliveries/{id}/validate"
ASSIGN_OBJECTIVE = "POST /incentives/programs/{id}/objectives"

# One representative exclusive write per role, with the authorized-role list the
# endpoint table states for it.
EXCLUSIVE_WRITES = {
    CREATE_DEALER: ("IncentiveController",),
    CREATE_PROGRAM: ("ProgramDesigner",),
    REPORT_DELIVERY: ("Dealer",),
    VALIDATE_DELIVERY: ("ClaimsAuditor",),
    ASSIGN_OBJECTIVE: ("FieldSalesManager",),
}

WRONG_ROLE_CASES = [
    (endpoint, role)
    for endpoint, authorized in EXCLUSIVE_WRITES.items()
    for role in ALL_ROLE_NAMES
    if role not in authorized
]
WRONG_ROLE_IDS = [
    f"{endpoint.split()[1].rsplit('/', 1)[-1] or 'root'}-as-{role}"
    for endpoint, role in WRONG_ROLE_CASES
]


def _exclusive_write_world() -> dict:
    """One ACTIVE program, one ACTIVE dealer and one REPORTED delivery. Every
    call below then carries a payload that would be accepted if the acting role
    were the right one, so only the role gate can explain a refusal."""
    base = fx.setup_active_program_and_dealer()
    delivery = fx.report_delivery(base["dealer"]["id"])
    return {
        "program": base["program"],
        "dealer": base["dealer"],
        "delivery": delivery,
    }


def _call_exclusive_write(endpoint: str, headers: dict, world: dict):
    dealer_id = world["dealer"]["id"]
    if endpoint == CREATE_DEALER:
        return api_client.create_dealer(f.create_dealer_payload(), headers)
    if endpoint == CREATE_PROGRAM:
        return api_client.create_program(
            f.create_program_payload(effective_from=OCT_01, effective_to=NOV_01),
            headers,
        )
    if endpoint == REPORT_DELIVERY:
        return api_client.create_delivery(f.create_delivery_payload(dealer_id), headers)
    if endpoint == VALIDATE_DELIVERY:
        return api_client.validate_delivery(world["delivery"]["id"], headers)
    if endpoint == ASSIGN_OBJECTIVE:
        return api_client.create_objective(
            world["program"]["id"], f.create_objective_payload(dealer_id), headers
        )
    raise AssertionError(f"unknown endpoint {endpoint!r}")


def _total_count(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


@pytest.mark.parametrize("endpoint,role", WRONG_ROLE_CASES, ids=WRONG_ROLE_IDS)
def test_every_wrong_role_is_refused_at_every_exclusive_write(endpoint, role):
    """Each of the twenty wrong-role calls at the five exclusive writes is
    refused with ERR_UNAUTHORIZED and persists nothing.

    PRD: "If both headers are present and well-formed but the named role does not
    appear in the authorized-role list of the endpoint being called (§4), the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/every_role_is_refused_at_every_other_roles_exclusive_write
    """
    world = _exclusive_write_world()
    controller = fx.CONTROLLER

    response = _call_exclusive_write(
        endpoint, _role_headers(role, world["dealer"]["id"]), world
    )
    # 403 with a well-formed error envelope: not 401 (the headers were valid) and
    # not 404/409/422 (the paths and payloads were valid).
    validate_error(response, "ERR_UNAUTHORIZED", 403)

    # The refusal wrote nothing: the world still holds exactly what setup built.
    assert _total_count(api_client.list_programs(controller, {"limit": 100})) == 1
    assert _total_count(api_client.list_deliveries(controller, {"limit": 100})) == 1
    delivery = fx.read_delivery(world["delivery"]["id"])
    a.assert_status(delivery, "REPORTED")
    a.assert_null_fields(delivery, ["validated_by_user_id"])
    assert (
        _total_count(
            api_client.list_program_objectives(
                world["program"]["id"], controller, {"limit": 100}
            )
        )
        == 0
    )


def test_each_exclusive_write_succeeds_for_the_one_role_that_owns_it():
    """The five right-role calls all succeed, so the twenty refusals above were
    about the role and not about the payloads.

    PRD: "A `ProgramDesigner` composes incentive programs, appends their
    eligibility footprint rows and stackability edges, submits programs for
    approval, revises rejected submissions and applies mid-month repricings."

    Design: Corner/rbac/every_role_is_refused_at_every_other_roles_exclusive_write
    """
    world = _exclusive_write_world()
    dealer_id = world["dealer"]["id"]
    controller = fx.CONTROLLER

    created_dealer = validate_success(
        _call_exclusive_write(CREATE_DEALER, _role_headers("IncentiveController", dealer_id), world),
        201,
    )
    a.assert_dealer_shape(created_dealer)

    created_program = validate_success(
        _call_exclusive_write(CREATE_PROGRAM, _role_headers("ProgramDesigner", dealer_id), world),
        201,
    )
    a.assert_status(created_program, "DRAFT")

    reported = validate_success(
        _call_exclusive_write(REPORT_DELIVERY, _role_headers("Dealer", dealer_id), world),
        201,
    )
    a.assert_status(reported, "REPORTED")

    validated = validate_success(
        _call_exclusive_write(VALIDATE_DELIVERY, _role_headers("ClaimsAuditor", dealer_id), world)
    )
    a.assert_status(validated, "VALIDATED")
    assert validated["validated_by_user_id"] == USER_AUDITOR_1

    objective = validate_success(
        _call_exclusive_write(ASSIGN_OBJECTIVE, _role_headers("FieldSalesManager", dealer_id), world),
        201,
    )
    a.assert_status(objective, "PROPOSED")

    # Exactly the setup rows plus the one accepted call per collection.
    assert _total_count(api_client.list_deliveries(controller, {"limit": 100})) == 2
    assert _total_count(api_client.list_programs(controller, {"limit": 100})) == 2


# --- The shared-read matrix ---------------------------------------------------

SPEND_SUMMARY = "GET /incentives/programs/{id}/spend-summary"
LIST_PROGRAMS = "GET /incentives/programs"
LIST_DELIVERIES = "GET /incentives/deliveries"
LIST_PROTESTS = "GET /incentives/objectives/{id}/protests"
ELIGIBLE_PROGRAMS = "GET /incentives/deliveries/{id}/eligible-programs"
GET_DEALER = "GET /incentives/dealers/{id}"

# Four shared projections with four different authorized-role lists, plus the one
# read every role shares.
SHARED_READS = {
    SPEND_SUMMARY: ("ProgramDesigner", "IncentiveController", "ClaimsAuditor"),
    LIST_PROGRAMS: (
        "ProgramDesigner",
        "IncentiveController",
        "FieldSalesManager",
        "ClaimsAuditor",
    ),
    LIST_DELIVERIES: (
        "ClaimsAuditor",
        "IncentiveController",
        "FieldSalesManager",
        "Dealer",
    ),
    LIST_PROTESTS: ("FieldSalesManager", "IncentiveController", "Dealer"),
    ELIGIBLE_PROGRAMS: ("ClaimsAuditor", "IncentiveController", "Dealer"),
    GET_DEALER: tuple(ALL_ROLE_NAMES),
}

EXCLUDED_READ_CASES = [
    (endpoint, role)
    for endpoint, authorized in SHARED_READS.items()
    for role in ALL_ROLE_NAMES
    if role not in authorized
]
EXCLUDED_READ_IDS = [
    f"{endpoint.split()[1].rsplit('/', 1)[-1] or 'root'}-as-{role}"
    for endpoint, role in EXCLUDED_READ_CASES
]


def _read_scope_world() -> dict:
    """One ACTIVE stair-step program with one dealer, one objective carrying one
    OPEN protest, and one REPORTED delivery."""
    setup = fx.setup_stair_step_objective(
        historical_volume_units=6,
        market_opportunity_bps=0,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 25000}
        ],
        tier_bonus_mode="MARGINAL",
        program_overrides={"budget_cents": 800000},
    )
    protest = fx.file_protest(setup["objective"]["id"], setup["dealer"]["id"], 4)
    delivery = fx.report_delivery(setup["dealer"]["id"])
    setup["protest"] = protest
    setup["delivery"] = delivery
    return setup


def _call_shared_read(endpoint: str, headers: dict, world: dict):
    if endpoint == SPEND_SUMMARY:
        return api_client.get_spend_summary(world["program"]["id"], headers)
    if endpoint == LIST_PROGRAMS:
        return api_client.list_programs(headers, {"limit": 10})
    if endpoint == LIST_DELIVERIES:
        return api_client.list_deliveries(headers, {"limit": 10})
    if endpoint == LIST_PROTESTS:
        return api_client.list_protests(world["objective"]["id"], headers, {"limit": 10})
    if endpoint == ELIGIBLE_PROGRAMS:
        return api_client.get_eligible_programs(world["delivery"]["id"], headers)
    if endpoint == GET_DEALER:
        return api_client.get_dealer(world["dealer"]["id"], headers)
    raise AssertionError(f"unknown endpoint {endpoint!r}")


@pytest.mark.parametrize("endpoint,role", EXCLUDED_READ_CASES, ids=EXCLUDED_READ_IDS)
def test_a_shared_read_refuses_the_roles_its_authorization_list_omits(endpoint, role):
    """Read access is not uniform: each shared projection refuses exactly the
    roles its own authorized-role list leaves out, with an error envelope rather
    than an empty page.

    PRD: "If both headers are present and well-formed but the named role does not
    appear in the authorized-role list of the endpoint being called (§4), the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/read_access_is_not_uniform_so_four_shared_projections_each_exclude_a_different_role
    """
    world = _read_scope_world()
    response = _call_shared_read(
        endpoint, _role_headers(role, world["dealer"]["id"]), world
    )
    error = validate_error(response, "ERR_UNAUTHORIZED", 403)
    assert "message" in error and error["message"], (
        "a refused read must carry a human-readable message, never an empty page"
    )


def test_each_shared_read_admits_exactly_its_own_role_list():
    """The same four projections answer every role their list names, including a
    dealer reading a program by id while the program collection stays closed to it.

    PRD: "Finally, the whole financial picture of a program is available as a
    single computed read for a `ProgramDesigner`, an `IncentiveController` or a
    `ClaimsAuditor`."

    Design: Corner/rbac/read_access_is_not_uniform_so_four_shared_projections_each_exclude_a_different_role
    """
    world = _read_scope_world()
    dealer_id = world["dealer"]["id"]
    program_id = world["program"]["id"]

    for role in SHARED_READS[SPEND_SUMMARY]:
        summary = validate_success(
            _call_shared_read(SPEND_SUMMARY, _role_headers(role, dealer_id), world)
        )
        assert summary["program_id"] == program_id
        a.assert_int_field(summary, "claimed_units", 0)
        a.assert_money(summary, "per_unit_spend_cents", 0)

    for role in SHARED_READS[LIST_PROGRAMS]:
        rows, meta = validate_paginated(
            _call_shared_read(LIST_PROGRAMS, _role_headers(role, dealer_id), world)
        )
        assert meta["total_count"] == 1
        a.assert_ids_equal(rows, [program_id], "programs")

    for role in SHARED_READS[LIST_DELIVERIES]:
        rows, meta = validate_paginated(
            _call_shared_read(LIST_DELIVERIES, _role_headers(role, dealer_id), world)
        )
        assert meta["total_count"] == 1
        a.assert_ids_equal(rows, [world["delivery"]["id"]], "deliveries")

    for role in SHARED_READS[LIST_PROTESTS]:
        rows, meta = validate_paginated(
            _call_shared_read(LIST_PROTESTS, _role_headers(role, dealer_id), world)
        )
        assert meta["total_count"] == 1
        a.assert_id_order(rows, [world["protest"]["id"]], "protests")

    for role in SHARED_READS[ELIGIBLE_PROGRAMS]:
        projection = validate_success(
            _call_shared_read(ELIGIBLE_PROGRAMS, _role_headers(role, dealer_id), world)
        )
        assert projection["delivery_id"] == world["delivery"]["id"]

    for role in SHARED_READS[GET_DEALER]:
        dealer = validate_success(
            _call_shared_read(GET_DEALER, _role_headers(role, dealer_id), world)
        )
        assert dealer["dealer_code"] == world["dealer"]["dealer_code"]

    # The dealer that may not enumerate the catalogue may still read one program.
    program = validate_success(
        api_client.get_program(program_id, make_dealer_headers(dealer_id))
    )
    assert program["program_code"] == world["program"]["program_code"]


# --- Segregation of duties ----------------------------------------------------


def _sod_world() -> dict:
    """Two submitted CUSTOMER_CASH programs with disjoint footprints — P1
    submitted by u-dual-1, P2 by u-designer-1 — plus one dealer whose delivery
    was validated by u-auditor-1 inside P1's footprint."""
    fx.set_clock("2026-08-12T00:00:00.000Z")
    dealer = fx.register_dealer(
        dealer_code="CRN-D-SOD",
        name="Duty Split Motors",
        region_code="ZZSOD",
        historical_volume_units=3,
        market_opportunity_bps=0,
    )
    p1 = fx.create_draft_program_with_rules(
        f.create_program_payload(
            program_code="CRN-X-SD1",
            name="Duty Split One",
            per_unit_amount_cents=25000,
            budget_cents=700000,
            stack_group="CRNSD1",
            priority_rank=446,
        ),
        rules=[
            {
                "model_code": "MX5",
                "region_code": "ZZSOD",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    p1_submitted = get_success_data(
        api_client.submit_program(p1["id"], make_program_designer_headers(USER_DUAL))
    )
    p2 = fx.create_draft_program_with_rules(
        f.create_program_payload(
            program_code="CRN-X-SD2",
            name="Duty Split Two",
            effective_from=OCT_01,
            effective_to=NOV_01,
            per_unit_amount_cents=15000,
            budget_cents=400000,
            stack_group="CRNSD2",
            priority_rank=447,
        ),
        rules=[
            {
                "model_code": "SDN3",
                "region_code": "ZZSOD2",
                "build_date_from": "2026-08-01T00:00:00.000Z",
                "build_date_to": "2026-09-30T00:00:00.000Z",
                "allowed_deal_types": ["FINANCE"],
            }
        ],
    )
    p2_submitted = fx.submit_program(p2["id"])
    delivery = fx.report_delivery(
        dealer["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=2700000,
        sale_date="2026-08-09T00:00:00.000Z",
        customer_region_code="ZZSOD",
        deal_type="CASH",
    )
    validated = fx.validate_delivery(delivery["id"])
    return {
        "dealer": dealer,
        "p1": p1_submitted,
        "p2": p2_submitted,
        "delivery": validated,
    }


def test_a_submitter_is_blocked_on_its_own_program_yet_approves_another():
    """The approval guard compares the caller against that program's own
    submitted_by_user_id, so u-dual-1 is refused on the program it submitted and
    admitted on the program someone else submitted.

    PRD: "The approving `X-User-ID` must differ from the program's recorded
    `submitted_by_user_id`, and an approver who is the submitter is stopped with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_is_scoped_to_the_resource_pair_not_to_the_person
    """
    world = _sod_world()
    a.assert_status(world["p1"], "PENDING_APPROVAL")
    assert world["p1"]["submitted_by_user_id"] == USER_DUAL
    assert world["p2"]["submitted_by_user_id"] == USER_DESIGNER

    dual_controller = make_headers(USER_DUAL, "IncentiveController")
    validate_error(
        api_client.approve_program(world["p1"]["id"], dual_controller),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    # The refused approval had no side effect at all.
    refused = fx.read_program(world["p1"]["id"])
    a.assert_status(refused, "PENDING_APPROVAL")
    a.assert_null_fields(refused, ["approved_by_user_id"])
    a.assert_version(refused, world["p1"]["version"])

    p1_active = validate_success(
        api_client.approve_program(world["p1"]["id"], fx.CONTROLLER)
    )
    a.assert_status(p1_active, "ACTIVE")
    assert p1_active["approved_by_user_id"] == USER_CONTROLLER

    p2_active = validate_success(
        api_client.approve_program(world["p2"]["id"], dual_controller)
    )
    a.assert_status(p2_active, "ACTIVE")
    assert p2_active["approved_by_user_id"] == USER_DUAL


def test_the_claim_site_reads_only_the_deliverys_validating_auditor():
    """The auditor who validated the delivery may not adjudicate its claim, while
    the principal that submitted the very program may.

    PRD: "The adjudicating `X-User-ID` must differ from the `validated_by_user_id`
    recorded on that delivery; the auditor who vouched for the delivery may not
    also approve money against it, and an attempt is stopped with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_is_scoped_to_the_resource_pair_not_to_the_person
    """
    world = _sod_world()
    assert world["delivery"]["validated_by_user_id"] == USER_AUDITOR_1
    fx.approve_program(world["p1"]["id"])

    claim = fx.submit_claim(
        world["dealer"]["id"], world["delivery"]["id"], world["p1"]["id"], 25000
    )
    validate_error(
        api_client.adjudicate_claim(
            claim["id"], f.adjudicate_payload("APPROVE"), fx.VALIDATOR
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    refused = fx.read_claim(claim["id"])
    a.assert_claim_dimensions(refused, "SUBMITTED", "UNPAID")
    a.assert_null_fields(refused, ["adjudicated_by_user_id"])

    approved = validate_success(
        api_client.adjudicate_claim(
            claim["id"],
            f.adjudicate_payload("APPROVE"),
            make_headers(USER_DUAL, "ClaimsAuditor"),
        )
    )
    a.assert_claim_dimensions(approved, "VALIDATED", "UNPAID")
    a.assert_money(approved, "approved_amount_cents", 25000)
    assert approved["adjudicated_by_user_id"] == USER_DUAL


# --- The Dealer role is entity-backed ----------------------------------------


def _ownership_world() -> dict:
    """Two dealers in one region, each with an objective under a stair-step
    program, plus a cash program and one validated delivery owned by dealer A."""
    fx.set_clock("2026-08-14T00:00:00.000Z")
    dealer_a = fx.register_dealer(
        dealer_code="CRN-D-OWA",
        name="Owner A Motors",
        region_code="ZZOWN",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    dealer_b = fx.register_dealer(
        dealer_code="CRN-D-OWB",
        name="Owner B Motors",
        region_code="ZZOWN",
        historical_volume_units=5,
        market_opportunity_bps=0,
    )
    footprint = [
        {
            "model_code": "MX5",
            "region_code": "ZZOWN",
            "build_date_from": "2026-05-01T00:00:00.000Z",
            "build_date_to": "2026-07-31T00:00:00.000Z",
            "allowed_deal_types": ["CASH"],
        }
    ]
    stair = fx.create_active_program(
        payload=f.create_stair_step_program_payload(
            program_code="CRN-X-OWN",
            name="Owner Scope Stair",
            budget_cents=900000,
            stack_group="CRNOWN",
            priority_rank=448,
            tier_schedule=[
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 20000}
            ],
        ),
        rules=footprint,
    )
    cash = fx.create_active_program(
        payload=f.create_program_payload(
            program_code="CRN-X-OWC",
            name="Owner Scope Cash",
            per_unit_amount_cents=22000,
            budget_cents=700000,
            stack_group="CRNOWC",
            priority_rank=449,
        ),
        rules=footprint,
    )
    objective_a = fx.assign_objective(stair["id"], dealer_a["id"])
    objective_b = fx.assign_objective(stair["id"], dealer_b["id"])
    delivery_a = fx.report_delivery(
        dealer_a["id"],
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=2600000,
        sale_date="2026-08-13T00:00:00.000Z",
        customer_region_code="ZZOWN",
        deal_type="CASH",
    )
    fx.validate_delivery(delivery_a["id"])
    return {
        "dealer_a": dealer_a,
        "dealer_b": dealer_b,
        "stair": stair,
        "cash": cash,
        "objective_a": objective_a,
        "objective_b": objective_b,
        "delivery_a": delivery_a,
    }


def _delivery_payload_for(dealer_id: str) -> dict:
    return f.create_delivery_payload(
        dealer_id,
        model_code="MX5",
        trim_code="BASE",
        build_date="2026-06-01T00:00:00.000Z",
        msrp_cents=2600000,
        sale_date="2026-08-13T00:00:00.000Z",
        customer_region_code="ZZOWN",
        deal_type="CASH",
    )


OWNER_MISMATCH_CASES = [
    "report-a-delivery-for-another-dealer",
    "file-a-protest-on-another-dealers-objective",
    "claim-another-dealers-validated-delivery",
    "report-a-delivery-under-an-id-that-is-no-dealer",
]


def _call_owner_mismatch(case: str, world: dict):
    dealer_a_headers = make_dealer_headers(world["dealer_a"]["id"])
    if case == "report-a-delivery-for-another-dealer":
        return api_client.create_delivery(
            _delivery_payload_for(world["dealer_b"]["id"]), dealer_a_headers
        )
    if case == "file-a-protest-on-another-dealers-objective":
        return api_client.create_protest(
            world["objective_b"]["id"], f.create_protest_payload(2), dealer_a_headers
        )
    if case == "claim-another-dealers-validated-delivery":
        return api_client.create_claim(
            f.create_claim_payload(
                world["delivery_a"]["id"],
                world["cash"]["id"],
                22000,
                fx.program_version(world["cash"]["id"]),
            ),
            make_dealer_headers(world["dealer_b"]["id"]),
        )
    return api_client.create_delivery(
        _delivery_payload_for(world["dealer_a"]["id"]),
        make_dealer_headers(GHOST_DEALER_ID),
    )


@pytest.mark.parametrize("case", OWNER_MISMATCH_CASES, ids=OWNER_MISMATCH_CASES)
def test_a_dealer_write_that_names_another_dealers_resource_is_refused(case):
    """All three dealer-facing writes compare the acting X-User-ID against the
    dealer key of the resource, so naming another dealer's row is refused.

    PRD: "A `Dealer` caller acting on a resource belonging to another dealer is
    rejected with `ERR_DEALER_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/the_dealer_role_is_entity_backed_so_writes_are_owner_scoped_while_reads_are_not
    """
    world = _ownership_world()
    validate_error(_call_owner_mismatch(case, world), "ERR_DEALER_MISMATCH", 403)

    # Nothing was created: only dealer A's original delivery exists, no claim
    # exists at all, and dealer B's objective was never protested.
    assert _total_count(api_client.list_deliveries(fx.CONTROLLER)) == 1
    assert _total_count(api_client.list_claims(fx.CONTROLLER)) == 0
    untouched = fx.read_objective(world["objective_b"]["id"])
    a.assert_int_field(untouched, "protest_round", 0)
    a.assert_status(untouched, "PROPOSED")
    a.assert_version(untouched, world["objective_b"]["version"])


def test_a_dealer_writes_freely_on_its_own_rows_and_reads_shared_programs():
    """The same principal that was refused another dealer's rows is admitted on
    its own delivery, its own objective and its own claim, and a program carries
    no dealer key to scope its read by.

    PRD: "Ownership checks on any resource that references a `Dealer` compare the
    resource's dealer foreign-key field to `X-User-ID`: reporting a retail
    delivery requires the payload's `dealer_id` to equal `X-User-ID`, submitting a
    claim requires the referenced delivery's `dealer_id` to equal `X-User-ID`, and
    filing a protest requires the target objective's `dealer_id` to equal
    `X-User-ID`."

    Design: Corner/rbac/the_dealer_role_is_entity_backed_so_writes_are_owner_scoped_while_reads_are_not
    """
    world = _ownership_world()
    dealer_a_id = world["dealer_a"]["id"]
    headers = make_dealer_headers(dealer_a_id)

    own_delivery = validate_success(
        api_client.create_delivery(_delivery_payload_for(dealer_a_id), headers), 201
    )
    a.assert_delivery_shape(own_delivery)
    assert own_delivery["dealer_id"] == dealer_a_id
    a.assert_status(own_delivery, "REPORTED")

    own_protest = validate_success(
        api_client.create_protest(
            world["objective_a"]["id"], f.create_protest_payload(3), headers
        ),
        201,
    )
    a.assert_protest_shape(own_protest)
    a.assert_status(own_protest, "OPEN")
    a.assert_int_field(own_protest, "round_index", 1)
    assert own_protest["objective_id"] == world["objective_a"]["id"]

    own_claim = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                world["delivery_a"]["id"],
                world["cash"]["id"],
                22000,
                fx.program_version(world["cash"]["id"]),
            ),
            headers,
        ),
        201,
    )
    a.assert_claim_shape(own_claim)
    assert own_claim["dealer_id"] == dealer_a_id
    # PRD names the claim's creation-time nulls exhaustively (payment_batch_id,
    # rejection_error_id, adjudicated_by_user_id, paid_at) and never states what
    # approved_amount_cents holds before adjudication, so only the two fields it
    # does pin down are asserted here.
    a.assert_money(own_claim, "claimed_amount_cents", 22000)
    a.assert_money(own_claim, "snapshot_per_unit_cents", 22000)

    # The dealer's own record and the shared program projection both read back.
    own_record = validate_success(api_client.get_dealer(dealer_a_id, headers))
    assert own_record["dealer_code"] == "CRN-D-OWA"
    shared_program = validate_success(
        api_client.get_program(world["cash"]["id"], headers)
    )
    assert shared_program["program_code"] == "CRN-X-OWC"
