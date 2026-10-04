"""Corner coverage: validation ordering and evidence/model-match rules."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, claim_with_verified_docs, get_claim,
    m95_completed_run, make_claim, make_component, make_lot, make_model,
    make_verified_document, standard_kit, validate_error,
)
from test_helpers import TEST_USERS, api_client

api = api_client
PLANNER = TEST_USERS["planner"]
COMPLIANCE = TEST_USERS["compliance"]


def test_list_factories_missing_header_returns_missing_user_context():
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in
    which they act. If either header is missing, or if `X-User-Role` does not
    name one of the declared roles, the request is rejected with
    `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/validations/list_factories_missing_header_returns_missing_user_context
    """
    resp = api.list_factories(headers={})
    error = validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)
    assert resp.json()["response_type"] == "error"


def test_unknown_run_id_on_complete_returns_not_found():
    """PRD §2.8: "The twelve families below are evaluated in ascending priority
    order, and within each family the checks run as described. A failure in an
    earlier family masks every later family"
    PRD §2.8 (family 4): "Path identifiers are resolved left to right, and
    every body-supplied reference — `model_id`, `factory_id`, `component_id`,
    `report_id`, `production_run_id`, `worker_id`, `claim_id`,
    `material_lot_id`, and every `component_id` inside a `bom_lines` entry —
    must resolve to an existing resource."

    Design: Corner/validations/unknown_run_id_on_complete_returns_not_found
    """
    # Empty payload would fail schema (family 5); existence (family 4) wins.
    resp = api.complete_run(NON_EXISTENT_UUID, {}, PLANNER)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND)


def test_complete_without_minutes_returns_invalid_request():
    """PRD §2.8 (family 5): "Required fields must be present, enum values must
    be valid, and numeric and date ranges must be honored: `planned_units` at
    least 1, `quantity_units` between 1 and 12 inclusive, `score` between 0 and
    100 inclusive, `units` at least 1, `target_level` between 1 and 3
    inclusive, `end_day` strictly after `start_day`, `valid_until` strictly
    after `valid_from`, and `fulfillment_end` strictly after
    `fulfillment_start`. Violations are `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.8 (family 6): "the generic `ERR_INVALID_STATE` (HTTP 409) covers
    wrong-state targets"

    Design: Corner/validations/complete_without_minutes_returns_invalid_request
    """
    kit = standard_kit()  # run PLANNED
    resp = api.complete_run(kit["run"]["id"], {}, PLANNER)
    # Schema (family 5) precedes the wrong-state error (family 6).
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_substantiate_without_any_evidence_returns_required_evidence_missing():
    """PRD §3.8: "and finally the evidence folder must contain at least one
    `VERIFIED` unexpired `SUPPLIER_ORIGIN_CERT` and at least one `VERIFIED`
    unexpired `ASSEMBLY_LABOR_RECORD` attached to this claim via `claim_id`
    (otherwise `ERR_REQUIRED_EVIDENCE_MISSING`, HTTP 422)."

    Design: Corner/validations/substantiate_without_any_evidence_returns_required_evidence_missing
    """
    kit = m95_completed_run()  # 95.00 report: the threshold passes
    claim = make_claim(kit["model"]["id"], "MADE_IN_USA")

    zero = api.substantiate_claim(claim["id"], {"report_id": kit["report"]["id"]},
                                  COMPLIANCE)
    validate_error(zero, ApiErrorId.ERR_REQUIRED_EVIDENCE_MISSING)

    # Only the origin cert on file: the labor record is still missing.
    make_verified_document("SUPPLIER_ORIGIN_CERT", "claim_id", claim["id"])
    one = api.substantiate_claim(claim["id"], {"report_id": kit["report"]["id"]},
                                 COMPLIANCE)
    validate_error(one, ApiErrorId.ERR_REQUIRED_EVIDENCE_MISSING)
    assert get_claim(claim["id"])["status"] == "DRAFT"


def test_report_of_other_model_returns_report_model_mismatch():
    """PRD §3.8: "the report must belong to the claim's own model — the
    report's run's `model_id` must equal the claim's `model_id`, otherwise
    `ERR_REPORT_MODEL_MISMATCH` (HTTP 422)"
    PRD §2.8 (family 7): "first the report-to-claim model match
    (`ERR_REPORT_MODEL_MISMATCH`, HTTP 422 — a claim may not be substantiated
    by another model's report); then the claim content-threshold check
    (`ERR_CONTENT_THRESHOLD_NOT_MET`, HTTP 422)"

    Design: Corner/validations/report_of_other_model_returns_report_model_mismatch
    """
    kit = m95_completed_run()  # CERTIFIED report belongs to M95
    c_t = make_component()
    make_lot(c_t["id"])
    mstd = make_model(c_t["id"], style_code="MSTD")
    # The MSTD claim carries both required VERIFIED documents, so only the
    # mismatch rule can fail.
    docs = claim_with_verified_docs(mstd["id"], "MADE_IN_USA")

    resp = api.substantiate_claim(docs["claim"]["id"],
                                  {"report_id": kit["report"]["id"]}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_REPORT_MODEL_MISMATCH)
    assert get_claim(docs["claim"]["id"])["status"] == "DRAFT"
