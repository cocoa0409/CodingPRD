"""Research data services: cohorts, k-anonymity, rates, scoping."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    advance_clock, create_institution_with_registrars, add_agreement,
    add_period, get_period_version, upload_file, certify_file,
    setup_period_scenario, setup_certified_file, setup_sealed_degree,
    place_directive, make_rows, setup_research_dataset, list_file_entries,
    make_analyst_headers,
)

OPS = TEST_USERS["ops_headers"]


def _cohort_scene(api):
    """The shared cohort fixture: 12 certified students (S01 withdrawn before
    census), degrees sealed for S03..S06, opt-outs on S11 and S12, and a
    dataset over the Fall window. Clock ends at 2028-06-01."""
    ctx = setup_period_scenario()
    rows = make_rows(12)
    rows[0]["withdrawal_date"] = "2026-09-10"
    ctx["file"] = upload_file(ctx, rows)
    ctx["file_id"] = ctx["file"]["id"]
    ctx["file"] = certify_file(ctx, ctx["file_id"])
    ctx["entries"] = list_file_entries(ctx["file_id"])
    for index in (2, 3, 4, 5):
        setup_sealed_degree(
            ctx, ctx["entries"][index]["student_id"],
            conferred_on="2027-05-15",
        )
    for index in (10, 11):
        place_directive(
            ctx["entries"][index]["student_id"],
            directive_type="RESEARCH_OPT_OUT", effective_from="2026-01-01",
        )
    ctx["dataset"] = setup_research_dataset(ctx)
    advance_clock("2028-06-01T00:00:00Z")
    return ctx


def _generate(api, dataset_id):
    return api_client.generate_research_dataset(dataset_id, OPS)


def test_research_cohort_sizes_with_opt_out_and_census_withdrawal(api):
    """PRD section 3.9: "First, the cohort: distinct students who hold an
    `ACCEPTED`, non-`SUPERSEDED` EnrollmentEntry at the scope institution
    whose entry `term_start` falls within the cohort window, minus any
    student with a `RESEARCH_OPT_OUT` directive in effect at generation time
    under §3.8's gating rule; the count is `cohort_size`."
    PRD section 3.9: "Fourth, the adjusted denominator:
    `adjusted_cohort_size` is `cohort_size` minus the members whose latest
    entry's `census_status_code` is `WITHDRAWN`."

    Design: Difficulty/dual_variant_calc/research_cohort_census_vs_adjusted_denominator
    """
    ctx = _cohort_scene(api)
    data = validate_success(_generate(api, ctx["dataset"]["id"]), 200)
    assert data["cohort_size"] == 10, "12 enrolled minus 2 opted out"
    assert data["completer_count"] == 4, (
        "S03..S06 hold SEALED degrees conferred inside the lag window"
    )
    assert data["adjusted_cohort_size"] == 9, (
        "S01 withdrew on 2026-09-10, on or before census 2026-09-15, so the "
        "census variant reads WITHDRAWN and excludes them"
    )


def test_research_completion_rates_diverge_by_denominator(api):
    """PRD section 3.9: "Fifth, the two rates, each computed to exactly four
    decimal places rounded half-up: `completion_rate_census` divides
    `completer_count` by `cohort_size`, and `completion_rate_adjusted`
    divides the same `completer_count` — the numerator is identical in both
    variants — by `adjusted_cohort_size`, so the two rates diverge exactly
    when census-withdrawn members exist."

    Design: Difficulty/dual_variant_calc/research_cohort_census_vs_adjusted_denominator
    """
    ctx = _cohort_scene(api)
    data = validate_success(_generate(api, ctx["dataset"]["id"]), 200)
    assert data["completion_rate_census"] == 0.4, "4/10 to four decimals"
    assert data["completion_rate_adjusted"] == 0.4444, (
        "4/9 rounded half-up to four decimals"
    )


def _two_window_scene(api):
    """Two certified files in disjoint term windows: F1 has 12 students with
    2 opted out; F2 has 11 students with 2 opted out."""
    ctx = create_institution_with_registrars()
    add_agreement(ctx["inst_id"])
    p1 = add_period(ctx["inst_id"])
    p2 = add_period(
        ctx["inst_id"], term_label="Spring 2027", term_start="2026-12-21",
        term_end="2027-05-01", submission_opens_at="2027-03-01",
        submission_due_at="2027-05-15",
    )
    advance_clock("2026-11-15T00:00:00Z")

    scope1 = {"inst_id": ctx["inst_id"], "sub_uid": ctx["sub_uid"],
              "cert_uid": ctx["cert_uid"], "period_id": p1["id"]}
    f1 = upload_file(scope1, make_rows(12, prefix="A", first_name="Alpha"),
                     expected_version=get_period_version(ctx["inst_id"], 0))
    certify_file(scope1, f1["id"])
    entries1 = list_file_entries(f1["id"])
    for index in (10, 11):
        place_directive(entries1[index]["student_id"],
                        directive_type="RESEARCH_OPT_OUT",
                        effective_from="2026-01-01")

    advance_clock("2027-03-10T00:00:00Z")
    scope2 = {"inst_id": ctx["inst_id"], "sub_uid": ctx["sub_uid"],
              "cert_uid": ctx["cert_uid"], "period_id": p2["id"]}
    f2 = upload_file(
        scope2,
        make_rows(11, prefix="B", first_name="Beta",
                  term_start="2026-12-21", term_end="2027-05-01",
                  dob_month=2),
        expected_version=get_period_version(ctx["inst_id"], 1),
    )
    certify_file(scope2, f2["id"])
    entries2 = list_file_entries(f2["id"])
    for index in (9, 10):
        place_directive(entries2[index]["student_id"],
                        directive_type="RESEARCH_OPT_OUT",
                        effective_from="2026-01-01")
    ctx["ds_a"] = setup_research_dataset(ctx)  # Fall window
    ctx["ds_b"] = setup_research_dataset(
        ctx, cohort_term_start="2026-12-21", cohort_term_end="2027-05-01",
    )
    return ctx


def test_cohort_of_exactly_ten_generates(api):
    """PRD section 3.9: "Second, the k-anonymity gate: a `cohort_size` below
    ten rejects the generation with `ERR_COHORT_TOO_SMALL` (HTTP 422)."
    PRD section 3.9: "Generation stamps `generated_at` and moves the dataset
    `REQUESTED` → `GENERATED`".

    Design: Difficulty/boundary_precision_check/k_anonymity_boundary_10_vs_9
    """
    ctx = _two_window_scene(api)
    data = validate_success(_generate(api, ctx["ds_a"]["id"]), 200)
    assert data["status"] == "GENERATED"
    assert data["cohort_size"] == 10, (
        "12 minus 2 opted out; exactly ten satisfies the >= gate"
    )


def test_cohort_of_nine_rejected(api):
    """PRD section 3.9: "Second, the k-anonymity gate: a `cohort_size` below
    ten rejects the generation with `ERR_COHORT_TOO_SMALL` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/k_anonymity_boundary_10_vs_9
    """
    ctx = _two_window_scene(api)
    resp = _generate(api, ctx["ds_b"]["id"])
    validate_error(resp, ApiErrorId.ERR_COHORT_TOO_SMALL)


def test_generate_generated_dataset_rejected(api):
    """PRD section 3.9: "Generation is an operations act on a dataset still
    `REQUESTED` — anything else fails with `ERR_INVALID_STATE`".
    PRD section 3.9: "Generation stamps `generated_at` and moves the dataset
    `REQUESTED` → `GENERATED`, a stable end state with no further
    transitions."

    Design: Corner/state_machines/generate_generated_dataset_rejected
    """
    ctx = setup_certified_file(rows=make_rows(10, prefix="B",
                                              first_name="Beta",
                                              dob_month=2))
    dataset = setup_research_dataset(ctx)
    first = validate_success(_generate(api, dataset["id"]), 200)
    assert first["status"] == "GENERATED"
    assert first["cohort_size"] == 10
    again = _generate(api, dataset["id"])
    validate_error(again, ApiErrorId.ERR_INVALID_STATE)
    data, _m = validate_paginated(
        api_client.list_institution_research_datasets(ctx["inst_id"], OPS),
    )
    assert data[0]["status"] == "GENERATED"


def test_rbac_analyst_cannot_generate(api):
    """PRD section 2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint, or that fails an ownership check, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD section 3.9: "Generation is an operations act on a dataset still
    `REQUESTED`".

    Design: Corner/rbac/rbac_analyst_cannot_generate
    """
    ctx = create_institution_with_registrars()
    dataset = setup_research_dataset(ctx, analyst_id="analyst-a")
    resp = api_client.generate_research_dataset(
        dataset["id"], make_analyst_headers("analyst-a"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    data, _m = validate_paginated(
        api_client.list_institution_research_datasets(ctx["inst_id"], OPS),
    )
    assert data[0]["status"] == "REQUESTED"


def test_rbac_analyst_list_scoped_to_own_datasets(api):
    """PRD section 3.9: "The institution-scoped dataset list shows
    `ClearinghouseOps` and registrar callers the institution's datasets; a
    `ResearchAnalyst` caller sees only the datasets they created."

    Design: Corner/rbac/rbac_analyst_list_scoped_to_own_datasets
    """
    ctx = create_institution_with_registrars()
    ds_a = setup_research_dataset(ctx, analyst_id="analyst-a")
    setup_research_dataset(ctx, analyst_id="analyst-b")
    own, meta_own = validate_paginated(
        api_client.list_institution_research_datasets(
            ctx["inst_id"], make_analyst_headers("analyst-a"),
        ),
    )
    assert meta_own["total_count"] == 1
    assert own[0]["id"] == ds_a["id"]
    _all, meta_all = validate_paginated(
        api_client.list_institution_research_datasets(ctx["inst_id"], OPS),
    )
    assert meta_all["total_count"] == 2


def test_err_dataset_not_found(api):
    """PRD section 3.9: "Generation is an operations act on a dataset still
    `REQUESTED` — anything else fails with `ERR_INVALID_STATE`, and an
    unknown dataset reports `ERR_DATASET_NOT_FOUND`".

    Design: Corner/errors/err_dataset_not_found
    """
    create_institution_with_registrars()
    resp = api_client.generate_research_dataset(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_DATASET_NOT_FOUND)
