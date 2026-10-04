"""Timeliness math: dual basis variants and threshold boundaries (PRD §3.4)."""
from test_helpers import (
    add_case,
    create_sample,
    create_scored_sample,
    fill_sample_with_cases,
    get_success_data,
    make_accreditation_officer_headers,
    score_sample,
    setup_evidence_review,
    submit_sample,
    validate_paginated,
)
from test_helpers.fixtures import (
    BASE_EXTRA_CASES,
    BASE_TIMELY_CASES,
    LATE_CASE,
    api_client,
)


def _officer():
    return make_accreditation_officer_headers()


def test_file_case_timeliness_basis_divergence_days_and_flags(api):
    """PRD §3.4: "The basis date is the case's `decision_date` when the sample's `timeliness_basis` is `DECISION_DATE`, or the case's `resolution_date` when the basis is `RESOLUTION_DATE`; `days_to_basis` is the whole calendar days between `service_date` and the basis date, taken as the floor of the elapsed time."
    PRD §3.4: "A case is timely when `days_to_basis` is less than or equal to the case's `required_turnaround_days`."

    Design: Difficulty/dual_variant_calc/file_case_timeliness_basis_divergence
    """
    ctx = setup_evidence_review()
    app_id = ctx["app"]["id"]
    plan_id = ctx["plan"]["id"]

    sample_dec = create_sample(app_id, timeliness_basis="DECISION_DATE")
    sample_res = create_sample(app_id, timeliness_basis="RESOLUTION_DATE")

    case_dates = dict(
        service_date="2025-03-01T00:00:00Z",
        decision_date="2025-03-20T00:00:00Z",
        resolution_date="2025-04-25T00:00:00Z",
        required_turnaround_days=30,
    )
    case_dec = add_case(sample_dec["id"], plan_id, case_reference="DN-100", **case_dates)
    case_res = add_case(sample_res["id"], plan_id, case_reference="DN-200", **case_dates)

    # Fill both samples to the required size with additional timely cases.
    filler = [{"service_date": "2025-05-01T00:00:00Z",
               "decision_date": "2025-05-10T00:00:00Z"}] * 4
    fill_sample_with_cases(sample_dec["id"], plan_id, filler, prefix="DF")
    fill_sample_with_cases(sample_res["id"], plan_id, filler, prefix="RF")
    submit_sample(sample_dec["id"], plan_id)
    submit_sample(sample_res["id"], plan_id)
    score_sample(sample_dec["id"])
    score_sample(sample_res["id"])

    got_dec = get_success_data(api_client.get_file_review_case(case_dec["id"], _officer()))
    got_res = get_success_data(api_client.get_file_review_case(case_res["id"], _officer()))
    assert got_dec["days_to_basis"] == 19, f"decision-basis days {got_dec['days_to_basis']}"
    assert got_res["days_to_basis"] == 55, f"resolution-basis days {got_res['days_to_basis']}"
    assert got_dec["is_timely"] is True, "19 days <= 30 must be timely"
    assert got_res["is_timely"] is False, "55 days > 30 must not be timely"


def test_file_case_timeliness_identical_inputs_diverge_by_basis(api):
    """PRD §3.4: "The same case can therefore be timely under the decision-date
    basis but not timely under the resolution-date basis, when the decision was
    prompt but final resolution lagged."

    Design: Difficulty/dual_variant_calc/file_case_timeliness_basis_divergence
    """
    ctx = setup_evidence_review()
    app_id = ctx["app"]["id"]
    plan_id = ctx["plan"]["id"]

    sample_dec = create_sample(app_id, timeliness_basis="DECISION_DATE")
    sample_res = create_sample(app_id, timeliness_basis="RESOLUTION_DATE")

    identical = dict(
        service_date="2025-03-01T00:00:00Z",
        decision_date="2025-03-20T00:00:00Z",
        resolution_date="2025-04-25T00:00:00Z",
        required_turnaround_days=30,
    )
    cases = [{"case_reference": "K", **identical}] + [
        {"case_reference": f"F{i}", "service_date": "2025-05-01T00:00:00Z",
         "decision_date": "2025-05-10T00:00:00Z", "resolution_date": "2025-05-10T00:00:00Z",
         "required_turnaround_days": 30}
        for i in range(4)
    ]
    for s in (sample_dec, sample_res):
        for c in cases:
            add_case(s["id"], plan_id, **c)
        submit_sample(s["id"], plan_id)
        score_sample(s["id"])

    dec_cases, _ = validate_paginated(
        api_client.list_file_review_cases(sample_dec["id"], _officer(), params={"limit": 100})
    )
    res_cases, _ = validate_paginated(
        api_client.list_file_review_cases(sample_res["id"], _officer(), params={"limit": 100})
    )
    k_dec = [c for c in dec_cases if c["case_reference"] == "K"][0]
    k_res = [c for c in res_cases if c["case_reference"] == "K"][0]
    assert k_dec["is_timely"] is True and k_res["is_timely"] is False, (
        "identical dates and turnaround must produce divergent is_timely purely from timeliness_basis"
    )


def test_timeliness_rate_exactly_at_threshold_passes(api):
    """PRD §3.4: "The sample's `must_pass_threshold_breached` becomes true when the
    `timeliness_rate` is strictly less than the edition's `timeliness_threshold`
    and the edition contains at least one element in the sample's category whose
    `is_must_pass` is true; a rate equal to or above the threshold does not breach."

    Design: Difficulty/boundary_precision_check/timeliness_rate_exactly_at_threshold_passes
    """
    ctx = setup_evidence_review()
    app_id = ctx["app"]["id"]
    plan_id = ctx["plan"]["id"]

    # 10 cases, 9 timely -> rate exactly 0.9000 == threshold 0.90
    sample_pass = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES + BASE_EXTRA_CASES, prefix="P"
    )
    assert sample_pass["timely_case_count"] == 9
    assert sample_pass["timeliness_rate"] == 0.9, (
        f"9/10 must round to 0.9000, got {sample_pass['timeliness_rate']}"
    )
    assert sample_pass["must_pass_threshold_breached"] is False, (
        "0.9000 >= 0.90 — the boundary is inclusive"
    )

    # 5 cases, 4 timely -> rate 0.8000 < 0.90, and UM has must-pass element UM-1
    sample_fail = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES[:4] + [LATE_CASE],
        sample_type="APPEAL", prefix="F",
    )
    assert sample_fail["timeliness_rate"] == 0.8
    assert sample_fail["must_pass_threshold_breached"] is True, (
        "0.8000 < 0.90 with a must-pass UM element must breach"
    )


def test_timeliness_rate_one_case_below_threshold_breaches(api):
    """PRD §3.4: "a rate equal to or above the threshold does not breach."
    Boundary pair: 0.9000 does not breach while 0.8000 (one timely case apart)
    does, so the comparison against the edition's threshold is `>=`.

    Design: Difficulty/boundary_precision_check/timeliness_rate_exactly_at_threshold_passes
    """
    ctx = setup_evidence_review()
    app_id = ctx["app"]["id"]
    plan_id = ctx["plan"]["id"]

    sample_pass = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES + BASE_EXTRA_CASES, prefix="P"
    )
    sample_fail = create_scored_sample(
        app_id, plan_id, BASE_TIMELY_CASES[:4] + [LATE_CASE],
        sample_type="APPEAL", prefix="F",
    )
    assert sample_pass["timeliness_rate"] == 0.9
    assert sample_fail["timeliness_rate"] == 0.8
    assert (sample_pass["must_pass_threshold_breached"],
            sample_fail["must_pass_threshold_breached"]) == (False, True)


def test_sample_timeliness_exact_turnaround_boundary_is_timely(api):
    """PRD §3.4: "A case is timely when `days_to_basis` is less than or equal to
    the case's `required_turnaround_days` — the boundary case where `days_to_basis`
    equals `required_turnaround_days` exactly counts as timely."

    Design: Corner/calculations/sample_timeliness_exact_turnaround_boundary_is_timely
    """
    ctx = setup_evidence_review()
    app_id = ctx["app"]["id"]
    plan_id = ctx["plan"]["id"]

    sample = create_sample(app_id)
    case_b = add_case(sample["id"], plan_id, case_reference="B1",
                      service_date="2025-03-01T00:00:00Z",
                      decision_date="2025-03-31T00:00:00Z",
                      resolution_date="2025-03-31T00:00:00Z")
    case_b2 = add_case(sample["id"], plan_id, case_reference="B2",
                       service_date="2025-03-01T00:00:00Z",
                       decision_date="2025-04-01T00:00:00Z",
                       resolution_date="2025-04-01T00:00:00Z")
    for i, d in enumerate(("2025-05-01", "2025-06-01", "2025-07-01"), 3):
        add_case(sample["id"], plan_id, case_reference=f"B{i}",
                 service_date=f"{d}T00:00:00Z", decision_date=f"{d[:8]}10T00:00:00Z",
                 resolution_date=f"{d[:8]}10T00:00:00Z")
    submit_sample(sample["id"], plan_id)
    scored = score_sample(sample["id"])

    got_b = get_success_data(api_client.get_file_review_case(case_b["id"], _officer()))
    got_b2 = get_success_data(api_client.get_file_review_case(case_b2["id"], _officer()))
    assert got_b["days_to_basis"] == 30 and got_b["is_timely"] is True, "30 <= 30 is timely"
    assert got_b2["days_to_basis"] == 31 and got_b2["is_timely"] is False, "31 > 30 is not timely"
    assert scored["timeliness_rate"] == 0.8, f"4/5 must round to 0.8000, got {scored['timeliness_rate']}"
