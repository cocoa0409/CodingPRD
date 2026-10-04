"""Corner queue — RBAC claims (2 of 2): the three segregation-of-duties pairs
and the ExternalResearcher's release-scoped visibility."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_irb_protocol_payload,
    create_restricted_use_file,
    create_study_payload,
    irb_decision_payload,
    make_agency_officer_headers,
    make_data_manager_headers,
    make_external_researcher_headers,
    make_irb_reviewer_headers,
    make_peer_reviewer_headers,
    make_principal_investigator_headers,
    setup_contract,
    setup_published_report,
    setup_released_ruf,
    setup_study_with_draft_report,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
DM = TEST_USERS["data_manager_headers"]


def test_sod_irb_decider_equals_submitter_rejected(api):
    """PRD §3.3: "The reviewer must not be the operator who submitted the
    protocol: if the deciding `X-User-ID` equals the recorded
    `submitted_by_id`, the decision is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_irb_decider_equals_submitter_rejected
    """
    pi_shared = make_principal_investigator_headers("shared-7")
    contract = setup_contract()
    study = validate_success(
        api.create_study(
            contract["id"], create_study_payload(title="S", research_question="Q"),
            pi_shared,
        ),
        201,
    )
    irb = validate_success(
        api.create_irb_protocol(study["id"], create_irb_protocol_payload(), pi_shared),
        201,
    )
    validate_success(api.submit_irb_protocol(irb["id"], pi_shared), 200)

    resp = api.irb_decision(
        irb["id"],
        irb_decision_payload(
            "APPROVED",
            approval_start="2026-09-01T00:00:00Z",
            approval_end="2027-09-01T00:00:00Z",
        ),
        make_irb_reviewer_headers("shared-7"),  # same operator id, other hat
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    protocols, _ = validate_paginated(api.list_irb_protocols(study["id"], PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "SUBMITTED"


def test_sod_report_reviewer_equals_submitter_rejected(api):
    """PRD §3.7: "the reviewer's `X-User-ID` must differ from the recorded
    `submitted_by_id`; a self-review is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_report_reviewer_equals_submitter_rejected
    """
    ctx = setup_study_with_draft_report()
    report = validate_success(
        api.submit_report(
            ctx["report"]["id"], make_principal_investigator_headers("pi-9")
        ),
        200,
    )
    assert report["submitted_by_id"] == "pi-9"

    resp = api.review_report(report["id"], make_peer_reviewer_headers("pi-9"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    reports, _ = validate_paginated(api.list_reports(ctx["study"]["id"], PI))
    assert next(r for r in reports if r["id"] == report["id"])["status"] == "SUBMITTED"


def test_sod_ruf_decider_equals_preparer_rejected(api):
    """PRD §3.9: "the decider's `X-User-ID` must differ from `prepared_by_id`,
    else `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_ruf_decider_equals_preparer_rejected
    """
    ctx = setup_published_report()
    dm_shared = make_data_manager_headers("shared-8")
    ruf = validate_success(
        api.create_restricted_use_file(
            ctx["study"]["id"],
            {"title": "RUF sod", "cell_counts": [10, 20],
             "sensitivity_weights": [0.5, 0.5]},
            dm_shared,
        ),
        201,
    )
    assert ruf["prepared_by_id"] == "shared-8"
    validate_success(api.submit_ruf_review(ruf["id"], dm_shared), 200)

    resp = api.ruf_review_decision(
        ruf["id"], {"decision": "APPROVE"}, make_agency_officer_headers("shared-8")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    files, _ = validate_paginated(api.list_restricted_use_files(ctx["study"]["id"], DM))
    assert next(f for f in files if f["id"] == ruf["id"])["status"] == "DISCLOSURE_REVIEW"


def test_external_researcher_sees_only_released_files(api):
    """PRD §3.9: "Visibility follows release: staff roles list all of a study's
    restricted-use files, while an `ExternalResearcher` listing the same
    collection sees only `RELEASED` files."
    PRD §3.9: "each surviving cell's risk is its `sensitivity_weights` entry
    divided by its `cell_counts` entry, and `max_risk` is the largest such
    per-cell risk." (0.5/10 = 0.05 here, within the gate.)

    Design: Corner/rbac/external_researcher_sees_only_released_files
    """
    ctx = setup_released_ruf(
        ruf_overrides={"title": "RUF-A", "cell_counts": [10, 20],
                       "sensitivity_weights": [0.5, 0.5]}
    )
    ruf_a = ctx["ruf"]
    assert ruf_a["status"] == "RELEASED"
    assert ruf_a["max_risk"] == pytest.approx(0.05)

    ruf_b = create_restricted_use_file(
        ctx["study"]["id"], title="RUF-B", cell_counts=[8, 9],
        sensitivity_weights=[0.5, 0.5],
    )  # stays DRAFT

    xr_files, _ = validate_paginated(
        api.list_restricted_use_files(
            ctx["study"]["id"], make_external_researcher_headers("xr-1")
        )
    )
    assert len(xr_files) == 1, "ExternalResearcher sees released files only"
    assert xr_files[0]["id"] == ruf_a["id"]
    assert xr_files[0]["status"] == "RELEASED"

    staff_files, _ = validate_paginated(
        api.list_restricted_use_files(ctx["study"]["id"], DM)
    )
    assert len(staff_files) == 2, "staff see every file of the study"
