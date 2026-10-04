"""Pigment batches: quarantine, certification, segregation of duties, recall."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_pigment_batch, assert_recall_case, assert_same_instant,
    make_qa_headers, make_licensor_headers,
)

ADMIN = fx.ADMIN
QA = fx.QA
QA2 = fx.QA2


def test_batch_created_in_quarantine_initial_state(api):
    """PRD section 3.2: "A new batch starts in `QUARANTINE`, and the registrar's
    `X-User-ID` is recorded as `created_by_user_id`, which becomes the
    segregation-of-duties anchor."

    Design: Corner/state_machines/batch_created_in_quarantine_initial_state
    """
    fx.reset_clock()
    resp = api_client.create_pigment_batch(
        {"pigment_name": "Phthalo Blue", "supplier_name": "PigmentCo",
         "hazard_class": "STANDARD", "received_quantity_kg": 500,
         "certification_mark": "ACMI_AP"},
        fx.make_sourcing_headers("sm-1"))
    data = validate_success(resp, 201)
    assert_pigment_batch(data)
    assert data["status"] == "QUARANTINE"
    assert data["created_by_user_id"] == "sm-1"
    assert data["certified_by_user_id"] is None


def test_batch_create_client_supplied_status_is_ignored_input(api):
    """PRD section 2.8 stage 3: "Undeclared extra fields are ignored: never
    echoed, never stored." PRD section 3.2: "A new batch starts in `QUARANTINE`"
    and PRD section 2.5: "`version` (integer): starts at 1 when the resource is
    created".

    Design: Corner/entities/batch_create_client_supplied_status_is_ignored_input
    """
    fx.reset_clock()
    resp = api_client.create_pigment_batch(
        {"pigment_name": "Phthalo Blue", "supplier_name": "PigmentCo",
         "hazard_class": "STANDARD", "received_quantity_kg": 500,
         "certification_mark": "ACMI_AP", "status": "CERTIFIED", "version": 99,
         "created_by_user_id": "spoofed"},
        fx.make_sourcing_headers("sm-1"))
    data = validate_success(resp, 201)
    assert data["status"] == "QUARANTINE"
    assert data["version"] == 1
    assert data["created_by_user_id"] == "sm-1"


def test_certification_mark_required_for_sensitive_batch(api):
    """PRD section 3.2: "when the batch's `hazard_class` is `SENSITIVE` or
    `RESTRICTED`, certification additionally requires the `certification_mark`
    to be `ACMI_AP`, else the decision is rejected with
    `ERR_CERTIFICATION_MARK_REQUIRED` (HTTP 409)."

    Design: Corner/errors/certification_mark_required_for_sensitive_batch
    """
    fx.reset_clock()
    b1 = fx.create_batch(pigment_name="Cobalt Blue", hazard_class="SENSITIVE",
                         received_quantity_kg=120, certification_mark="ACMI_CL")
    b2 = fx.create_batch(pigment_name="Phthalo Blue", hazard_class="STANDARD",
                         received_quantity_kg=500, certification_mark="ACMI_CL")
    resp1 = api_client.certification_decision(b1["id"], {"decision": "CERTIFY"}, QA)
    validate_error(resp1, ApiErrorId.ERR_CERTIFICATION_MARK_REQUIRED)
    assert get_success_data(api_client.get_pigment_batch(b1["id"], ADMIN))["status"] == "QUARANTINE"
    resp2 = api_client.certification_decision(b2["id"], {"decision": "CERTIFY"}, QA)
    data2 = validate_success(resp2, 200)
    assert data2["status"] == "CERTIFIED"


def test_batch_rejected_is_terminal_state_lockdown(api):
    """PRD section 3.2: "A decision attempted on a `REJECTED` batch is refused
    with `ERR_BATCH_TERMINAL` (HTTP 409), because `REJECTED` is terminal." and
    "A `REJECT` decision on a `QUARANTINE` batch moves it to `REJECTED` and
    stores the payload `reason` as `rejection_reason`."

    Design: Corner/state_machines/batch_rejected_is_terminal_state_lockdown
    """
    fx.reset_clock()
    batch = fx.create_batch()
    fx.reject_batch(batch["id"], by="qa-1", reason="off-spec color")
    resp = api_client.certification_decision(batch["id"], {"decision": "CERTIFY"}, QA2)
    validate_error(resp, ApiErrorId.ERR_BATCH_TERMINAL)
    frozen = get_success_data(api_client.get_pigment_batch(batch["id"], ADMIN))
    assert frozen["status"] == "REJECTED"
    assert frozen["rejection_reason"] == "off-spec color"
    assert frozen["certified_by_user_id"] is None


def test_qa_who_created_batch_cannot_certify_it(api):
    """PRD section 2.9: "A `QualityAssurance` officer deciding a pigment batch's
    certification must not be the `X-User-ID` recorded as the batch's
    `created_by_user_id`." — violations are `ERR_SOD_VIOLATION` (HTTP 403).

    Design: Corner/rbac/qa_who_created_batch_cannot_certify_it
    """
    fx.reset_clock()
    resp = api_client.create_pigment_batch(
        {"pigment_name": "Phthalo Blue", "supplier_name": "PigmentCo",
         "hazard_class": "STANDARD", "received_quantity_kg": 500,
         "certification_mark": "ACMI_AP"},
        make_qa_headers("qa-1"))
    batch = get_success_data(resp)
    self_decide = api_client.certification_decision(
        batch["id"], {"decision": "CERTIFY"}, make_qa_headers("qa-1"))
    validate_error(self_decide, ApiErrorId.ERR_SOD_VIOLATION)
    assert self_decide.status_code == 403
    other = api_client.certification_decision(
        batch["id"], {"decision": "CERTIFY"}, make_qa_headers("qa-2"))
    data = validate_success(other, 200)
    assert data["status"] == "CERTIFIED"
    assert data["certified_by_user_id"] == "qa-2"


def test_recall_severity_bumps_restricted_hazard(api):
    """PRD section 3.2: "fewer than the `CLASS_II_FLOOR` of 1000 units is
    `CLASS_III`" and "`RESTRICTED` raises it one class (`CLASS_III` to
    `CLASS_II`, `CLASS_II` to `CLASS_I`, while `CLASS_I` stays `CLASS_I`)"
    and "`CLASS_II` for the `COOLING_II_DAYS` window of 14 days, and
    `CLASS_I` for the `COOLING_I_DAYS` window of 30 days, and
    `cooling_until` is the case's `created_at` plus its severity's cooling
    days."

    Design: Corner/calculations/recall_severity_bumps_restricted_hazard
    """
    fx.reset_clock()
    env = fx.production_setup()
    batch = fx.create_batch(pigment_name="Cobalt Blue", hazard_class="RESTRICTED",
                            received_quantity_kg=120, certification_mark="ACMI_AP")
    fx.certify_batch(batch["id"])
    run = fx.create_run(env["spec"]["id"], batch["id"], planned_boxes=5)
    fx.advance_run_to_packing(run["id"])
    fx.complete_run(run["id"], [{"color_id": env["color"]["id"], "count": 40}])
    fx.set_clock("2026-11-02T00:00:00Z")
    resp = api_client.certification_decision(
        batch["id"], {"decision": "REJECT", "reason": "cobalt impurity"}, QA2)
    validate_success(resp, 200)
    cases = get_success_data(api_client.list_recall_cases(batch["id"], ADMIN))
    assert len(cases) == 1
    case = cases[0]
    assert_recall_case(case)
    assert case["status"] == "OPEN"
    assert case["severity"] == "CLASS_II"  # bumped from CLASS_III by RESTRICTED
    assert case["affected_units"] == 40
    assert case["affected_run_count"] == 1
    assert_same_instant(case["cooling_until"], "2026-11-16T00:00:00Z", "cooling_until")


def test_run_create_with_recalled_batch_returns_recall_active(api):
    """PRD section 3.2: "While any case against a batch is `OPEN` or
    `CONTAINED`, that batch gates production: a new run referencing it is
    rejected with `ERR_RECALL_ACTIVE` (HTTP 409), and per §2.8 this
    recall gate fires at the business-safety stage, ahead of the linked-entity
    checks."

    Design: Corner/errors/run_create_with_recalled_batch_returns_recall_active
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    api_client.certification_decision(
        env["batch"]["id"], {"decision": "REJECT", "reason": "trace cadmium"}, QA2)
    resp = api_client.create_production_run(
        {"assortment_spec_id": env["spec"]["id"],
         "pigment_batch_id": env["batch"]["id"], "planned_boxes": 10,
         "planned_start_date": "2027-04-15T00:00:00Z",
         "planned_end_date": "2027-05-20T00:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RECALL_ACTIVE)
    assert resp.status_code == 409
    assert resp.json()["data"]["error_id"] != "ERR_BATCH_NOT_CERTIFIED"


def test_reinstate_happy_path_after_recall_closes(api):
    """PRD section 3.6: "`REINSTATE` moves `SUSPENDED` back to `APPROVED` only
    when no `OPEN` or `CONTAINED` recall case touches the line's formula color,
    the line's formula is currently `APPROVED`, and `pinned_formula_version`
    still equals the formula's current `version`". PRD section 3.2: "A
    `CONTAINED` case moves to `CLOSED` once the logical clock is at or after
    `cooling_until`; closure makes the `SUSPENDED` licensed lines whose
    suspension traces to this case eligible for reinstatement."

    Design: Corner/complexity_layers/reinstate_happy_path_after_recall_closes
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    line = fx.create_approved_licensed_line(env["formula"]["id"])
    assert line["pinned_formula_version"] == 4  # approve bumped formula 3 -> 4
    fx.set_clock("2026-11-02T00:00:00Z")
    api_client.certification_decision(
        env["batch"]["id"], {"decision": "REJECT", "reason": "trace cadmium"}, QA2)
    fx.run_epoch()  # contains the recall (OPEN -> CONTAINED)
    fx.set_clock("2026-11-17T00:00:00Z")
    second = fx.run_epoch()
    assert second["recalls_closed"] == 1
    suspended = fx.get_line(line["id"])
    assert suspended["status"] == "SUSPENDED"
    frm_v = fx.get_formula(env["formula"]["id"])["version"]
    assert frm_v == 4
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "REINSTATE", "expected_formula_version": frm_v}, fx.BRAND)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    assert data["pinned_formula_version"] == 4


def test_batch_decision_terminal_state_beats_sod_certify(api):
    """PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins" — state gates (stage 6, `ERR_BATCH_TERMINAL`) precede
    business-safety segregation of duties (stage 7, `ERR_SOD_VIOLATION`). PRD
    section 3.2: "A decision attempted on a `REJECTED` batch is refused with
    `ERR_BATCH_TERMINAL` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/batch_decision_terminal_state_beats_sod
    """
    fx.reset_clock()
    resp = api_client.create_pigment_batch(
        {"pigment_name": "Cadmium Red", "supplier_name": "PigmentCo",
         "hazard_class": "RESTRICTED", "received_quantity_kg": 120,
         "certification_mark": "ACMI_AP"},
        make_qa_headers("qa-1"))
    batch = get_success_data(resp)
    fx.reject_batch(batch["id"], by="qa-2", reason="cadmium above limit")
    # qa-1 is both the creator (SoD violation) AND the batch is terminal.
    attempt = api_client.certification_decision(
        batch["id"], {"decision": "CERTIFY"}, make_qa_headers("qa-1"))
    validate_error(attempt, ApiErrorId.ERR_BATCH_TERMINAL)
    assert attempt.status_code == 409
    assert attempt.json()["data"]["error_id"] != "ERR_SOD_VIOLATION"


def test_batch_decision_terminal_state_beats_sod_reject(api):
    """PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins" — a REJECT against the already-REJECTED batch by its own
    registrar is likewise answered at the state gate (stage 6) before the SoD
    check (stage 7).

    Design: Difficulty/priority_pair_validation_conflict/batch_decision_terminal_state_beats_sod
    """
    fx.reset_clock()
    resp = api_client.create_pigment_batch(
        {"pigment_name": "Cadmium Red", "supplier_name": "PigmentCo",
         "hazard_class": "RESTRICTED", "received_quantity_kg": 120,
         "certification_mark": "ACMI_AP"},
        make_qa_headers("qa-1"))
    batch = get_success_data(resp)
    fx.reject_batch(batch["id"], by="qa-2", reason="cadmium above limit")
    attempt = api_client.certification_decision(
        batch["id"], {"decision": "REJECT", "reason": "again"}, make_qa_headers("qa-1"))
    validate_error(attempt, ApiErrorId.ERR_BATCH_TERMINAL)
    assert attempt.status_code == 409
    frozen = get_success_data(api_client.get_pigment_batch(batch["id"], ADMIN))
    assert frozen["status"] == "REJECTED"
    assert frozen["rejection_reason"] == "cadmium above limit"


def test_recall_cascade_creates_case_with_class_ii_severity(api):
    """PRD section 3.2: "A `REJECT` decision on an already `CERTIFIED` batch is
    the platform's recall trigger: the batch is retro-rejected to `REJECTED`,
    and if any production run references the batch, a **recall case** is created
    in `OPEN`" and "from 1000 units up to but not including the `CLASS_I_FLOOR`
    of 10000 is `CLASS_II` — the boundary value 1000 belongs to class II".

    Design: Difficulty/transitive_cascade/batch_retro_rejection_cascades_recall_runs_lots_allocations_lines
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(alloc["id"], "COMMIT")
    line = fx.create_approved_licensed_line(env["formula"]["id"])
    fx.set_clock("2026-11-02T00:00:00Z")
    resp = api_client.certification_decision(
        env["batch"]["id"],
        {"decision": "REJECT", "reason": "trace cadmium above child-safety limit"}, QA2)
    data = validate_success(resp, 200)
    assert data["status"] == "REJECTED"
    cases = get_success_data(api_client.list_recall_cases(env["batch"]["id"], ADMIN))
    assert len(cases) == 1
    case = cases[0]
    assert case["status"] == "OPEN"
    assert case["affected_run_count"] == 1
    assert case["affected_units"] == 1000  # 125 boxes x 8-count box
    assert case["severity"] == "CLASS_II"  # 1000 is the inclusive floor of class II
    assert_same_instant(case["cooling_until"], "2026-11-16T00:00:00Z", "cooling_until")


def test_recall_cascade_quarantines_run_lot_shortens_allocation_suspends_line(api):
    """PRD section 3.2: "A `COMPLETED` run becomes `QUARANTINED` as well —
    completion is not a safe harbor — and its inventory lots become
    `QUARANTINED` with their `boxes_committed` frozen inside the quarantined
    lot" and "`COMMITTED` allocations of the affected specs become `SHORTED`"
    and "any `APPROVED` licensed line is `SUSPENDED` when the recall quarantines
    a run whose spec contains the color of the line's formula".

    Design: Difficulty/transitive_cascade/batch_retro_rejection_cascades_recall_runs_lots_allocations_lines
    """
    fx.reset_clock()
    env = fx.production_setup_with_completed_run()
    alloc = fx.create_allocation(env["spec"]["id"], requested_boxes=100)
    fx.allocation_decision(alloc["id"], "COMMIT")
    line = fx.create_approved_licensed_line(env["formula"]["id"])
    fx.set_clock("2026-11-02T00:00:00Z")
    api_client.certification_decision(
        env["batch"]["id"],
        {"decision": "REJECT", "reason": "trace cadmium above child-safety limit"}, QA2)
    run = fx.get_run(env["run"]["id"])
    assert run["stage"] == "QUARANTINED"
    lots = fx.list_lots(env["run"]["id"])
    assert len(lots) == 1
    assert lots[0]["status"] == "QUARANTINED"
    assert lots[0]["boxes_committed"] == 100  # frozen in place
    alloc_now = fx.get_allocation(alloc["id"])
    assert alloc_now["status"] == "SHORTED"
    line_now = fx.get_line(line["id"])
    assert line_now["status"] == "SUSPENDED"
