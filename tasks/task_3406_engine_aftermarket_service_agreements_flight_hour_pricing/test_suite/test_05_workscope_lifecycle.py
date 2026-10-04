"""Workscope versioning: the rework loop, OCC on the visit version, creation
gates (visit inducted, prior version decided, life-restoration floor),
approval gates (state, fiscal cap), and the due-directive auto-append."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_enrolled_engine,
    setup_inducted_visit,
    setup_submitted_workscope,
    create_directive,
    create_visit,
    create_workscope_version,
    approve_workscope,
    reject_workscope,
    get_workscope,
    get_visit_version,
    workscope_item,
    create_workscope_payload,
    create_part_requisition_payload,
)


def test_workscope_version_rework_loop(api, shop_planner_headers):
    """PRD §3.6: "The **Workscope** is the negotiated content of a shop visit,
    versioned per visit: each version carries a `scope_version` counter that
    starts at 1 and increments with every new workscope created for the same
    visit."
    PRD §3.6: "Creating a newer workscope version for the visit moves the
    previous version — whether `REJECTED`, `REOPENED`, or `APPROVED` — to the
    terminal `SUPERSEDED` state, increments its `version`, and cancels every
    one of its requisitions in `REQUESTED`, `ESCALATED`, or `SOURCED` status."

    Design: Difficulty/non_linear_state_machine/workscope_version_rework_loop
    """
    fx = setup_enrolled_engine(
        esn="ESN-F601",
        base_severity_tier="MODERATE",
        agreement_overrides={
            "contract_ref": "LTSA-F06",
            "allowed_sourcing_classes": ["NEW", "REPAIRED"],
            "max_workscope_cost_usd": 2000000,
        },
    )
    fx = setup_inducted_visit(fx)
    w1 = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=100000,
                              restores_cycles=8000)],
    )
    assert w1["scope_version"] == 1
    reject_workscope(w1, fx["operator_headers"])

    w2 = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-2", estimated_cost_usd=120000,
                              restores_cycles=8000)],
    )
    assert w2["scope_version"] == 2

    w1_after = get_workscope(w1["id"])
    assert w1_after["status"] == "SUPERSEDED"


def test_approve_state_beats_fiscal(api):
    """PRD §2.8: "When several checks could fail on the same request, the
    system evaluates them in a fixed priority order and surfaces the
    **first** failing check's error; later checks are not evaluated." — the
    state preconditions (tier 6) run before the fiscal gates (tier 10).
    PRD §3.6: "Approval requires the workscope to be `SUBMITTED` (otherwise
    `ERR_WORKSCOPE_NOT_SUBMITTED`), the visit to be `INDUCTED` (otherwise
    `ERR_VISIT_NOT_INDUCTED`), and the fiscal cap: `total_cost_usd` must be at
    or below the agreement's `max_workscope_cost_usd`, else the approval is
    rejected with `ERR_WORKSCOPE_COST_CAP_EXCEEDED`."

    The 2500000.00 workscope is over the 2000000 cap AND already REJECTED;
    only the state error may surface.

    Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_fiscal
    """
    fx = setup_enrolled_engine(
        esn="ESN-J901",
        agreement_overrides={"contract_ref": "LTSA-J09",
                             "max_workscope_cost_usd": 2000000},
    )
    fx = setup_inducted_visit(fx)
    workscope = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-X", estimated_cost_usd=2500000,
                              restores_cycles=8000)],
    )
    reject_workscope(workscope, fx["operator_headers"])

    res = api.approve_workscope(workscope["id"], fx["operator_headers"])
    validate_error(res, ApiErrorId.ERR_WORKSCOPE_NOT_SUBMITTED.value)


def test_workscope_create_blocked_while_latest_submitted(api, shop_planner_headers):
    """PRD §3.6: "If the visit's latest workscope version is still `SUBMITTED`
    (drafted but undecided), a new version may not be layered on top: the
    attempt is rejected with `ERR_ACTIVE_WORKSCOPE_EXISTS`."

    The request carries the visit's current version, so the OCC gate is
    satisfied and only the undecided-version gate can fail.

    Design: Corner/state_machines/workscope_create_blocked_while_latest_submitted
    """
    fx = setup_enrolled_engine(
        esn="ESN-S401", agreement_overrides={"contract_ref": "LTSA-C701"}
    )
    fx = setup_inducted_visit(fx)
    create_workscope_version(fx["visit"]["id"])  # v1 left SUBMITTED
    fresh_version = get_visit_version(fx["visit"]["id"])

    res = api.create_workscope(
        fx["visit"]["id"],
        create_workscope_payload(
            fresh_version,
            items=[workscope_item(item_code="MO-2", estimated_cost_usd=110000,
                                  restores_cycles=8000)],
        ),
        shop_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_ACTIVE_WORKSCOPE_EXISTS.value)


def test_workscope_creation_appends_due_directive_items(api):
    """PRD §3.6 (step 1): "A directive is due for this visit when it is
    `mandatory`, its `applicability_model` matches the engine's
    `engine_model` exactly, and at least one of its bounds is triggered: its
    `compliance_cycles`, when non-null, is at most the engine's
    `llp_remaining_cycles` plus a buffer of 18 months' worth of assumed cycles
    (that is, 18 multiplied by `assumed_cycles_per_month`)".
    PRD §3.6 (step 2): "For every due directive, the server appends one
    `MANDATORY_DIRECTIVE` item to the proposer-supplied list: the `item_code`
    and `directive_ref` are set to the directive's `directive_ref`, the
    `estimated_cost_usd` is taken from the directive, and `restores_cycles`
    is 0."

    Arithmetic: due because 50 <= 8000 + 18*100 = 9800; total = 300000.00
    (proposed) + 150000.00 (appended) = 450000.00.

    Design: Corner/calculations/workscope_creation_appends_due_directive_items
    """
    fx = setup_enrolled_engine(
        esn="ESN-G301", agreement_overrides={"contract_ref": "LTSA-C1301"}
    )
    create_directive(directive_ref="AD-2026-0300", mandatory=True,
                     estimated_cost_usd=150000, compliance_cycles=50)
    fx = setup_inducted_visit(fx)
    workscope = create_workscope_version(
        fx["visit"]["id"],
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=300000,
                              restores_cycles=8000)],
    )
    assert workscope["total_cost_usd"] == pytest.approx(450000.00, abs=0.01)
    directive_items = [i for i in workscope["items"]
                       if i["item_type"] == "MANDATORY_DIRECTIVE"]
    assert len(directive_items) == 1
    assert directive_items[0]["directive_ref"] == "AD-2026-0300"
    assert directive_items[0]["estimated_cost_usd"] == pytest.approx(150000.00, abs=0.01)


def test_workscope_requires_inducted_visit(api, shop_planner_headers):
    """PRD §3.6: "A `ShopPlanner` drafts the next version for an `INDUCTED`
    visit — drafting against a visit in any other status is rejected with
    `ERR_VISIT_NOT_INDUCTED`".

    The visit is SCHEDULED and the OCC version carried is current, isolating
    the state gate.

    Design: Corner/validations/workscope_requires_inducted_visit
    """
    fx = setup_enrolled_engine(
        esn="ESN-O101", agreement_overrides={"contract_ref": "LTSA-V2601"}
    )
    visit = create_visit(fx["engine"], fx["operator_headers"])
    assert visit["status"] == "SCHEDULED"
    res = api.create_workscope(
        visit["id"],
        create_workscope_payload(visit["version"], items=[workscope_item()]),
        shop_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_VISIT_NOT_INDUCTED.value)


def test_requisition_requires_approved_workscope(api, shop_planner_headers):
    """PRD §3.7: "Demanding a part on a workscope that is not `APPROVED` is
    rejected with `ERR_WORKSCOPE_NOT_APPROVED`."

    Design: Corner/validations/requisition_requires_approved_workscope
    """
    fx = setup_enrolled_engine(
        esn="ESN-P101", agreement_overrides={"contract_ref": "LTSA-V2701"}
    )
    fx = setup_submitted_workscope(fx)
    res = api.create_part_requisition(
        fx["workscope"]["id"],
        create_part_requisition_payload(part_number="PN-P1", list_price_usd=5000,
                                        requested_class="NEW",
                                        required_by_date="2026-10-01T00:00:00Z"),
        shop_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_WORKSCOPE_NOT_APPROVED.value)


def test_insufficient_life_restoration_rejected(api, shop_planner_headers):
    """PRD §3.6 (step 3): "The post-visit life in cycles is the larger of that
    restored value and the engine's current `llp_remaining_cycles`; divided by
    `assumed_cycles_per_month`, it gives the post-visit interval in months. If
    that interval is strictly less than 18 months, the workscope creation is
    rejected with `ERR_INSUFFICIENT_LIFE_RESTORATION`".

    Arithmetic: no item restores anything, so post-visit life = max(0, 1000)
    = 1000 cycles; 1000 / 100 = 10 months < 18.

    Design: Corner/validations/insufficient_life_restoration_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-Q201",
        llp_remaining_cycles=1000,
        assumed_cycles_per_month=100,
        agreement_overrides={"contract_ref": "LTSA-V2801"},
    )
    fx = setup_inducted_visit(fx)
    res = api.create_workscope(
        fx["visit"]["id"],
        create_workscope_payload(
            get_visit_version(fx["visit"]["id"]),
            items=[workscope_item(item_code="INSP-1", item_type="INSPECTION",
                                  estimated_cost_usd=50000, restores_cycles=0)],
        ),
        shop_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_LIFE_RESTORATION.value)


def test_approve_over_cap_rejected(api):
    """PRD §3.6: "the fiscal cap: `total_cost_usd` must be at or below the
    agreement's `max_workscope_cost_usd`, else the approval is rejected with
    `ERR_WORKSCOPE_COST_CAP_EXCEEDED`."

    The 2500000.00 workscope is SUBMITTED (state precondition holds) against
    the default 1000000 cap, isolating the fiscal gate.

    Design: Corner/validations/approve_over_cap_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-R201", agreement_overrides={"contract_ref": "LTSA-V2901"}
    )
    fx = setup_submitted_workscope(
        fx,
        items=[workscope_item(item_code="MO-X", estimated_cost_usd=2500000,
                              restores_cycles=8000)],
    )
    assert fx["workscope"]["status"] == "SUBMITTED"
    res = api.approve_workscope(fx["workscope"]["id"], fx["operator_headers"])
    validate_error(res, ApiErrorId.ERR_WORKSCOPE_COST_CAP_EXCEEDED.value)


def test_occ_stale_workscope_create_version(api, shop_planner_headers):
    """PRD §2.7: "**Creating a new workscope version** for a shop visit
    requires the request to carry `expected_shop_visit_version`, the caller's
    last observed `version` of the visit. A prior workscope creation
    legitimately supersedes the previous version and bumps the visit's
    `version`, so if the visit's current `version` does not match
    `expected_shop_visit_version` the creation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    The first version's creation bumped the visit's version, so the version
    captured right after induction is stale; the latest workscope is REJECTED,
    so the state gate would otherwise permit creation.

    Design: Corner/cross_cutting_layers/occ_stale_workscope_create_version
    """
    fx = setup_enrolled_engine(
        esn="ESN-Z201", agreement_overrides={"contract_ref": "LTSA-R4001"}
    )
    fx = setup_inducted_visit(fx)
    stale_version = fx["visit"]["version"]
    w1 = create_workscope_version(fx["visit"]["id"])  # bumps the visit version
    reject_workscope(w1, fx["operator_headers"])

    res = api.create_workscope(
        fx["visit"]["id"],
        create_workscope_payload(
            stale_version,
            items=[workscope_item(item_code="MO-2", estimated_cost_usd=110000,
                                  restores_cycles=8000)],
        ),
        shop_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


def test_immediate_consistency_on_approve_and_get(api, finance_controller_headers):
    """PRD §3.6: "Approval stamps `decided_at` with the logical clock, moves
    the workscope to `APPROVED`, and increments its `version`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    The mutation is visible both in the approving response and in an
    immediate re-read.

    Design: Corner/consistency_model/immediate_consistency_on_approve_and_get
    """
    fx = setup_enrolled_engine(
        esn="ESN-B201",
        operator_overrides={"name": "Birch Air", "iata_code": "BB"},
        agreement_overrides={"contract_ref": "LTSA-R4101"},
    )
    fx = setup_submitted_workscope(fx)
    approved = approve_workscope(fx["workscope"], fx["operator_headers"])
    assert approved["status"] == "APPROVED"
    assert approved["decided_at"] is not None

    reread = validate_success(
        api.get_workscope(fx["workscope"]["id"], finance_controller_headers), 200
    )
    assert reread["status"] == "APPROVED"
    assert reread["decided_at"] is not None
