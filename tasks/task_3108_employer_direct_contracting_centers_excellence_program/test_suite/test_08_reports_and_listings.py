"""Employer monthly reports and listing pagination/filtering."""
from test_helpers import (
    ApiErrorId,
    close_episode,
    drive_episode_to_post_op,
    drive_episode_to_sor_pending,
    get_success_data,
    get_episode,
    make_employer,
    make_employer_rep_headers,
    make_patient,
    open_episode,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = {"X-User-ID": "test-program-admin-1", "X-User-Role": "ProgramAdmin"}
COORD = {"X-User-ID": "test-care-coordinator-1", "X-User-Role": "CareCoordinator"}
REVIEWER = {"X-User-ID": "test-physician-reviewer-1", "X-User-Role": "PhysicianReviewer"}
CLAIMS = {"X-User-ID": "test-claims-admin-1", "X-User-Role": "ClaimsAdmin"}


def _drive_closed_with_optional_readmission(
    api, employer, contract, in_window_readmission_cents=None
):
    """Intake -> approve -> schedule -> PRE_OP -> surgery -> discharge ->
    optional related readmission -> advance to CLOSED. Returns episode."""
    patient = make_patient(employer)
    episode = drive_episode_to_sor_pending(open_episode(patient, contract))
    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_INDICATED",
             "expected_episode_version": episode["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    episode = drive_episode_to_post_op(get_episode(episode["id"]))
    if in_window_readmission_cents is not None:
        validate_success(
            api.record_readmission(
                episode["id"],
                {"related": True,
                 "provider_billed_cents": in_window_readmission_cents},
                COORD,
            ),
            expected_status=201,
        )
        episode = get_episode(episode["id"])
    return close_episode(episode)


def test_readmission_rate_pct_rounds_half_up_at_two_decimals(api):
    """PRD §3.9: "`readmission_rate_pct`, the count of in-month closed
    episodes with surgery that saw at least one in-window readmission over the
    count of in-month closed episodes with surgery, expressed as a percentage
    at 2 decimal places round-half-up, and exactly 0.00 when no such episodes
    exist; `warranty_absorbed_total_cents`, the sum of `absorbed_cents` over
    readmissions of in-month closed episodes"

    Design: Corner/calculations/readmission_rate_pct_rounds_half_up_at_two_decimals
    """
    prog = setup_program(
        rates={"ORTHO_JOINT": 2500000},
        template_overrides={"warranty_days": 3},
    )
    e1 = _drive_closed_with_optional_readmission(
        api, prog["employer"], prog["contract"], in_window_readmission_cents=150000
    )
    e2 = _drive_closed_with_optional_readmission(api, prog["employer"], prog["contract"])
    e3 = _drive_closed_with_optional_readmission(api, prog["employer"], prog["contract"])
    assert e1["closed_outcome"] == "READMITTED"
    assert e2["closed_outcome"] == "CLEAN"
    assert e3["closed_outcome"] == "CLEAN"

    resp = api.generate_employer_report(
        prog["employer"]["id"], {"period_month": "2026-09"},
        make_employer_rep_headers(prog["employer"]["id"]),
    )
    report = validate_success(resp, expected_status=201)
    assert report["status"] == "GENERATED"
    assert abs(report["readmission_rate_pct"] - 33.33) < 0.001, (
        "1 of 3 in-month closed surgical episodes, round-half-up at 2dp"
    )
    assert report["warranty_absorbed_total_cents"] == 150000
    assert report["avoided_procedures_count"] == 0
    assert report["avoided_cost_estimate_cents"] == 0


def test_readmission_rate_exactly_zero_when_no_surgical_closures(api):
    """PRD §3.9: "`readmission_rate_pct`, the count of in-month closed
    episodes with surgery that saw at least one in-window readmission over the
    count of in-month closed episodes with surgery, expressed as a percentage
    at 2 decimal places round-half-up, and exactly 0.00 when no such episodes
    exist"

    Design: Corner/calculations/readmission_rate_pct_rounds_half_up_at_two_decimals
    """
    prog = setup_program(rates={"ORTHO_JOINT": 2500000})
    patient = make_patient(prog["employer"])
    episode = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))
    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_UNNECESSARY",
             "expected_episode_version": episode["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )
    assert get_episode(episode["id"])["status"] == "AVOIDED"

    resp = api.generate_employer_report(
        prog["employer"]["id"], {"period_month": "2026-09"},
        make_employer_rep_headers(prog["employer"]["id"]),
    )
    report = validate_success(resp, expected_status=201)
    assert report["readmission_rate_pct"] == 0.00
    assert report["avoided_procedures_count"] == 1
    assert report["avoided_cost_estimate_cents"] == 2500000


def test_report_generate_upserts_same_month_snapshot(api):
    """PRD §3.9: "Generation upserts a snapshot per employer and month:
    regenerating the same month refreshes the computed fields in place and
    re-stamps `computed_seq` with the maximum episode sequence observed at
    computation time, so readers can reason about snapshot staleness. The
    report's `status` is always `GENERATED`."
    PRD §3.9: "`avoided_cost_estimate_cents`, the sum over those episodes of
    the employer baseline rate for each episode's family"

    Design: Corner/endpoints/report_generate_upserts_same_month_snapshot
    """
    prog = setup_program(rates={"ORTHO_JOINT": 2500000})
    patient = make_patient(prog["employer"])
    episode = drive_episode_to_sor_pending(open_episode(patient, prog["contract"]))
    validate_success(
        api.record_review(
            episode["id"],
            {"conclusion": "SURGERY_UNNECESSARY",
             "expected_episode_version": episode["version"]},
            REVIEWER,
        ),
        expected_status=201,
    )

    rep1 = validate_success(
        api.generate_employer_report(
            prog["employer"]["id"], {"period_month": "2026-09"},
            make_employer_rep_headers(prog["employer"]["id"]),
        ),
        expected_status=201,
    )
    rep2 = validate_success(
        api.generate_employer_report(
            prog["employer"]["id"], {"period_month": "2026-09"}, ADMIN
        ),
        expected_status=201,
    )
    assert rep1["id"] == rep2["id"], "the same (employer, month) upserts in place"
    assert rep1["avoided_procedures_count"] == 1
    assert rep1["avoided_cost_estimate_cents"] == 2500000
    assert rep2["computed_seq"] >= rep1["computed_seq"]


def test_report_generation_bad_month_format_rejected(api):
    """PRD §3.9: "Monthly employer reports are generated on demand for a
    `period_month` in YYYY-MM form — anything else fails with
    `ERR_MONTH_FORMAT_INVALID`"

    Design: Corner/endpoints/report_generate_upserts_same_month_snapshot
    """
    employer = make_employer()
    resp = api.generate_employer_report(
        employer["id"], {"period_month": "2026-9"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_MONTH_FORMAT_INVALID)


def test_employer_rep_cannot_read_other_employers_report(api):
    """PRD §2.1: "acting on a resource chain owned by a different employer —
    including generating a report for another employer — is rejected with
    `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

    Design: Corner/rbac/employer_rep_cannot_read_other_employers_report
    """
    emp_a = make_employer()
    emp_b = make_employer()
    report = validate_success(
        api.generate_employer_report(
            emp_b["id"], {"period_month": "2026-09"}, ADMIN
        ),
        expected_status=201,
    )

    gen = api.generate_employer_report(
        emp_b["id"], {"period_month": "2026-09"},
        make_employer_rep_headers(emp_a["id"]),
    )
    validate_error(gen, ApiErrorId.ERR_FORBIDDEN_SCOPE)

    read = api.get_report(report["id"], make_employer_rep_headers(emp_a["id"]))
    validate_error(read, ApiErrorId.ERR_FORBIDDEN_SCOPE)

    own = api.generate_employer_report(
        emp_b["id"], {"period_month": "2026-10"},
        make_employer_rep_headers(emp_b["id"]),
    )
    validate_success(own, expected_status=201)


def test_care_coordinator_cannot_adjudicate_claims(api, care_coordinator_headers):
    """PRD §2.1: "A caller whose role is not permitted to invoke the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /coe/claims/{id}/adjudicate — "Adjudicate a PENDING claim" —
    authorized role: ClaimsAdmin.

    Design: Corner/rbac/care_coordinator_cannot_adjudicate_claims
    """
    from test_helpers import setup_episode_in_post_op, submit_claim

    ctx = setup_episode_in_post_op()
    claim = submit_claim(
        ctx["episode"], "BUNDLE_CASE", ctx["episode"]["surgery_done_seq"], 3000000
    )

    resp = api.adjudicate_claim(claim["id"], care_coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    after = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert after["status"] == "PENDING"


def test_episodes_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` envelope of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §3.9: "Episodes can be listed with optional `contract_id`,
    `patient_id`, and `status` filters."

    Design: Corner/entities/episodes_list_paginates_with_total_count_and_has_more
    """
    prog = setup_program()
    for _ in range(3):
        patient = make_patient(prog["employer"])
        open_episode(patient, prog["contract"])

    page1, meta1 = validate_paginated(
        api.list_episodes(ADMIN, params={"contract_id": prog["contract"]["id"],
                                         "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_episodes(ADMIN, params={"contract_id": prog["contract"]["id"],
                                         "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_pagination_filter_sort_interaction_on_episode_list(api):
    """PRD §3.9: "Episodes can be listed with optional `contract_id`,
    `patient_id`, and `status` filters."
    PRD §3.4: "a `NOT_A_CANDIDATE` result moves it `SCREENING → CANCELLED`
    immediately"
    PRD §2.3: "Unless otherwise specified, every list endpoint returns
    resources sorted by `created_at` in ascending order."

    Design: Corner/cross_cutting_complexity_layers/pagination_filter_sort_interaction_on_episode_list
    """
    prog = setup_program()
    episodes = []
    for _ in range(3):
        patient = make_patient(prog["employer"])
        episodes.append(open_episode(patient, prog["contract"]))

    validate_success(
        api.submit_screening(
            episodes[2]["id"], {"doc_type": "LAB", "result": "NOT_A_CANDIDATE"}, COORD
        ),
        expected_status=201,
    )

    cancelled, meta = validate_paginated(
        api.list_episodes(ADMIN, params={"contract_id": prog["contract"]["id"],
                                         "status": "CANCELLED",
                                         "limit": 10, "offset": 0})
    )
    assert len(cancelled) == 1
    assert cancelled[0]["id"] == episodes[2]["id"]
    assert meta["total_count"] == 1, "the filter narrows total_count"
    assert meta["has_more"] is False

    _, meta_all = validate_paginated(
        api.list_episodes(ADMIN, params={"contract_id": prog["contract"]["id"]})
    )
    assert meta_all["total_count"] == 3
