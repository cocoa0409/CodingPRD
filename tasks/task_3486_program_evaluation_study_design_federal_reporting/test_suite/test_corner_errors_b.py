"""Corner queue — error catalogue claims (2 of 2): selective-reporting guard,
fiscal gate, publication prerequisites, and the disclosure-review cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_report,
    create_restricted_use_file,
    get_contract,
    ruf_review_decision_payload,
    setup_accepted_report,
    setup_contract_with_study,
    setup_published_report,
    setup_ruf_in_review,
    setup_study_in_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
DM = TEST_USERS["data_manager_headers"]


def test_report_submit_missing_primary_outcome_rejected(api):
    """PRD §3.7: "the report's `addressed_primary_outcomes` must include every
    code in that plan's frozen `primary_outcomes` — a report that silently
    drops a preregistered primary outcome is rejected with
    `ERR_UNREPORTED_PRIMARY_OUTCOME` (HTTP 422)."

    Design: Corner/errors/report_submit_missing_primary_outcome_rejected
    """
    ctx = setup_study_in_analysis()  # plan PREREGISTERED with both outcomes
    report = create_report(
        ctx["study"]["id"], addressed_primary_outcomes=["employment_q4"]
    )

    resp = api.submit_report(report["id"], PI)
    validate_error(resp, ApiErrorId.ERR_UNREPORTED_PRIMARY_OUTCOME)
    reports, _ = validate_paginated(api.list_reports(ctx["study"]["id"], PI))
    assert next(r for r in reports if r["id"] == report["id"])["status"] == "DRAFT"


def test_publish_overdrawn_milestone_rejected(api):
    """PRD §3.8: "The fiscal gate requires the report's
    `payment_milestone_cents` to fit within the owning contract's current
    `remaining_cents`; an overdraw is rejected with
    `ERR_INSUFFICIENT_CONTRACT_FUNDS` (HTTP 402)."

    Design: Corner/errors/publish_overdrawn_milestone_rejected
    """
    ctx = setup_accepted_report(
        report_overrides={"payment_milestone_cents": 90000001}
    )  # remaining_cents 90000000
    resp = api.publish_report(ctx["report"]["id"], AO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CONTRACT_FUNDS)

    reports, _ = validate_paginated(api.list_reports(ctx["study"]["id"], PI))
    assert next(r for r in reports if r["id"] == ctx["report"]["id"])["status"] == "ACCEPTED"
    contract = get_contract(ctx["contract"]["id"])
    assert contract["disbursed_cents"] == 0
    assert contract["remaining_cents"] == 90000000


def test_ruf_create_before_any_publication_rejected(api):
    """PRD §3.9: "A `DataManager` prepares a file for a study — permitted only
    once the study has at least one `PUBLISHED` report, otherwise
    `ERR_NO_PUBLISHED_REPORT`."

    Design: Corner/errors/ruf_create_before_any_publication_rejected
    """
    ctx = setup_contract_with_study()  # study DESIGN, no reports at all
    resp = api.create_restricted_use_file(
        ctx["study"]["id"],
        {"title": "RUF v1", "cell_counts": [10, 20],
         "sensitivity_weights": [0.5, 0.5]},
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_REPORT)
    files, _ = validate_paginated(
        api.list_restricted_use_files(ctx["study"]["id"], DM)
    )
    assert len(files) == 0, "no file persisted"


def test_closeout_with_incomplete_studies_rejected(api):
    """PRD §3.1: "An `AgencyOfficer` closes out a contract only while it is
    `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`) and only when every study of
    the contract has reached `COMPLETED`; if any study is short of `COMPLETED`,
    the closeout is rejected with `ERR_STUDIES_NOT_COMPLETED`."

    Design: Corner/errors/closeout_with_incomplete_studies_rejected
    """
    ctx = setup_contract_with_study()  # one DESIGN study
    resp = api.closeout_contract(ctx["contract"]["id"], AO)
    validate_error(resp, ApiErrorId.ERR_STUDIES_NOT_COMPLETED)
    contract = get_contract(ctx["contract"]["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["remaining_cents"] == 90000000


def test_ruf_all_cells_suppressed_risk_rejected_cycle(api):
    """PRD §3.9: "Both risk scores are expressed to 4 decimal places with
    round-half-up rounding, and if no cells survive suppression, both fall back
    to 1.0."
    PRD §3.9: "A `decision` of `REJECT` moves the file to `RISK_REJECTED`, from
    which the `DataManager` may revise the cell structure and submit it for
    review again."

    Design: Corner/errors/ruf_all_cells_suppressed_risk_rejected_cycle
    """
    ctx = setup_ruf_in_review(
        ruf_overrides={"title": "RUF risky", "cell_counts": [4, 3],
                       "sensitivity_weights": [1.0, 0.5]}
    )
    ruf = ctx["ruf"]
    assert ruf["status"] == "DISCLOSURE_REVIEW"
    assert ruf["suppressed_cell_count"] == 2, "all cells below the k-anonymity floor 5"
    assert ruf["max_risk"] == pytest.approx(1.0)
    assert ruf["mean_risk"] == pytest.approx(1.0)

    resp = api.ruf_review_decision(ruf["id"], ruf_review_decision_payload("APPROVE"), AO)
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_RISK_TOO_HIGH)  # 1.0 > 0.20
    files, _ = validate_paginated(api.list_restricted_use_files(ctx["study"]["id"], DM))
    assert next(f for f in files if f["id"] == ruf["id"])["status"] == "DISCLOSURE_REVIEW"

    ruf = validate_success(
        api.ruf_review_decision(ruf["id"], ruf_review_decision_payload("REJECT"), AO), 200
    )
    assert ruf["status"] == "RISK_REJECTED"

    ruf = validate_success(api.submit_ruf_review(ruf["id"], DM), 200)
    assert ruf["status"] == "DISCLOSURE_REVIEW", "rejection cycle re-enters review"


def test_ruf_decision_on_draft_rejected(api):
    """PRD §3.9: "An `AgencyOfficer` records a `decision` on a file in
    `DISCLOSURE_REVIEW` — any other state is rejected with
    `ERR_RUF_INVALID_STATE`."

    Design: Corner/errors/ruf_decision_on_draft_rejected
    """
    ctx = setup_published_report()
    ruf = create_restricted_use_file(ctx["study"]["id"])  # stays DRAFT

    resp = api.ruf_review_decision(ruf["id"], ruf_review_decision_payload("APPROVE"), AO)
    validate_error(resp, ApiErrorId.ERR_RUF_INVALID_STATE)
    files, _ = validate_paginated(api.list_restricted_use_files(ctx["study"]["id"], DM))
    assert next(f for f in files if f["id"] == ruf["id"])["status"] == "DRAFT"
