"""The sample ledger: reservation boundary (equality is inclusive), half-open
bench-window overlap scoped by lab_name, and mass conservation across
reserve / settle / cancel."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_sample_ledger_conservation,
    cancel_lab_analysis,
    create_lab_analysis,
    create_lab_analysis_payload,
    get_evidence_item,
    list_rows,
    record_result,
    setup_case_in_testing,
    ship_sample,
    validate_created,
    validate_error,
)

ATTORNEY = TEST_USERS["staff_attorney_headers"]
ANALYST = TEST_USERS["evidence_analyst_headers"]

WINDOW_A1 = ("2026-10-01T09:00:00Z", "2026-10-10T17:00:00Z")
WINDOW_A2 = ("2026-10-10T17:00:00Z", "2026-10-15T17:00:00Z")


def _testing_ctx(initial_sample_ng=25, state_code="CO", name="Colorado"):
    return setup_case_in_testing(
        jurisdiction_overrides={"state_code": state_code, "name": name},
        item_overrides={"initial_sample_ng": initial_sample_ng},
    )


def _analyses_of(api, item_id):
    rows, _ = list_rows(api.list_evidence_item_lab_analyses(item_id, ANALYST))
    return rows


def test_reserve_equal_to_remaining_succeeds_and_more_fails(api):
    """PRD section 3.5: "The item's `remaining_sample_ng` must cover the
    request and stay testable — both at least `required_sample_ng` and at
    least 5 nanograms, the minimum testable mass — else
    `ERR_INSUFFICIENT_SAMPLE` (HTTP 422)."
    PRD section 3.5: "A successful creation debits the sample ledger: the
    item's `remaining_sample_ng` drops by `required_sample_ng`".

    Design: Difficulty/boundary_precision_check/lab_reserve_exact_remaining_equality_allowed
    """
    ctx = _testing_ctx()
    create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"],
        required_sample_ng=15,
        scheduled_start=WINDOW_A1[0], scheduled_end=WINDOW_A1[1],
    )
    assert get_evidence_item(ctx["item"]["id"])["remaining_sample_ng"] == 10

    # One nanogram more than the remaining mass: rejected.
    resp = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            required_sample_ng=11,
            scheduled_start=WINDOW_A2[0], scheduled_end=WINDOW_A2[1],
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SAMPLE)
    assert get_evidence_item(ctx["item"]["id"])["remaining_sample_ng"] == 10, (
        "a failed reservation leaves the ledger untouched"
    )

    # Exact equality: the >= bound is inclusive.
    ok = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            test_type="DNA_YSTR",
            required_sample_ng=10,
            scheduled_start=WINDOW_A2[0], scheduled_end=WINDOW_A2[1],
        ),
        ATTORNEY,
    )
    validate_created(ok)
    assert get_evidence_item(ctx["item"]["id"])["remaining_sample_ng"] == 0


def test_reserve_to_zero_flips_testing_status_to_exhausted(api):
    """PRD section 3.5: "below 5 nanograms remaining, `SAMPLE_EXHAUSTED`".
    PRD section 3.5: "The item's `remaining_sample_ng` must cover the request
    and stay testable — both at least `required_sample_ng` and at least 5
    nanograms, the minimum testable mass — else `ERR_INSUFFICIENT_SAMPLE`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/lab_reserve_exact_remaining_equality_allowed
    """
    ctx = _testing_ctx()
    create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"],
        required_sample_ng=15,
        scheduled_start=WINDOW_A1[0], scheduled_end=WINDOW_A1[1],
    )
    resp = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            test_type="DNA_YSTR",
            required_sample_ng=10,
            scheduled_start=WINDOW_A2[0], scheduled_end=WINDOW_A2[1],
        ),
        ATTORNEY,
    )
    validate_created(resp)

    item = get_evidence_item(ctx["item"]["id"])
    assert item["remaining_sample_ng"] == 0
    assert item["testing_status"] == "SAMPLE_EXHAUSTED", "0 < 5ng minimum testable mass"
    analyses = _analyses_of(api, ctx["item"]["id"])
    assert_sample_ledger_conservation(item, analyses)


def test_lab_window_adjacent_endpoints_do_not_overlap(api):
    """PRD section 3.5: "if another analysis for the same `lab_name` in any
    status other than `CANCELLED` has a strictly overlapping half-open window —
    the existing window starts before the new window ends and ends after the
    new window starts; an endpoint touching an endpoint does not overlap —
    creation is rejected with `ERR_LAB_SCHEDULE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lab_windows_half_open_adjacency_vs_overlap
    """
    ctx = _testing_ctx(initial_sample_ng=100, state_code="OR", name="Oregon")
    create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"],
        required_sample_ng=10,
        scheduled_start="2027-02-01T09:00:00Z", scheduled_end="2027-02-10T17:00:00Z",
    )

    # A2 starts exactly at A1's end: half-open adjacency is not overlap.
    ok = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            test_type="DNA_YSTR", required_sample_ng=10,
            scheduled_start="2027-02-10T17:00:00Z", scheduled_end="2027-02-15T17:00:00Z",
        ),
        ATTORNEY,
    )
    validate_created(ok)

    # A3 [02-10T16:00, 02-20T09:00) overlaps A1 by one hour and A2 from its start.
    resp = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            test_type="MITOCHONDRIAL_DNA", required_sample_ng=10,
            scheduled_start="2027-02-10T16:00:00Z", scheduled_end="2027-02-20T09:00:00Z",
        ),
        ATTORNEY,
    )
    validate_error(resp, ApiErrorId.ERR_LAB_SCHEDULE_OVERLAP)


def test_lab_window_overlap_is_scoped_by_lab_name(api):
    """PRD section 3.5: "And the laboratory's bench cannot be double-booked:
    if another analysis for the same `lab_name` in any status other than
    `CANCELLED` has a strictly overlapping half-open window — the existing
    window starts before the new window ends and ends after the new window
    starts; an endpoint touching an endpoint does not overlap — creation is
    rejected with `ERR_LAB_SCHEDULE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lab_windows_half_open_adjacency_vs_overlap
    """
    ctx = _testing_ctx(initial_sample_ng=100, state_code="OR", name="Oregon")
    create_lab_analysis(
        ctx["item"]["id"], ctx["authorization"]["id"],
        required_sample_ng=10,
        scheduled_start="2027-02-01T09:00:00Z", scheduled_end="2027-02-10T17:00:00Z",
    )

    # Fully overlapping in time but a different lab_name: the resource is the
    # laboratory bench, not the calendar.
    ok = api.create_lab_analysis(
        create_lab_analysis_payload(
            ctx["item"]["id"], ctx["authorization"]["id"],
            lab_name="LabOther", test_type="MITOCHONDRIAL_DNA", required_sample_ng=10,
            scheduled_start="2027-02-05T00:00:00Z", scheduled_end="2027-02-12T00:00:00Z",
        ),
        ATTORNEY,
    )
    validate_created(ok)


def test_sample_mass_conserved_across_settle_and_cancel(api):
    """PRD section 3.5: "The ledger obeys a strict conservation invariant over
    each evidence item: `initial_sample_ng` always equals `remaining_sample_ng`
    plus the reservations of that item's analyses in `SCHEDULED` or
    `SAMPLE_SHIPPED`, plus the consumed masses of its analyses in
    `RESULT_RECORDED` or `INTERPRETED`."
    PRD section 3.5: "any unconsumed portion of the reservation — the
    difference between `reserved_sample_ng` and `actual_consumed_ng` — is
    refunded to the item's `remaining_sample_ng`".

    Design: Difficulty/compensating_invariant/sample_mass_conserved_across_reserve_settle_cancel
    """
    ctx = _testing_ctx(state_code="TN", name="Tennessee")
    item_id = ctx["item"]["id"]

    a1 = create_lab_analysis(
        item_id, ctx["authorization"]["id"],
        required_sample_ng=15,
        scheduled_start=WINDOW_A1[0], scheduled_end=WINDOW_A1[1],
    )
    assert get_evidence_item(item_id)["remaining_sample_ng"] == 10  # 25 - 15

    ship_sample(a1["id"])
    record_result(a1["id"], outcome="EXCLUSIONARY", actual_consumed_ng=12)
    # Under-consumption refund of 3 applied on settlement.
    assert get_evidence_item(item_id)["remaining_sample_ng"] == 13

    a2 = create_lab_analysis(
        item_id, ctx["authorization"]["id"],
        test_type="DNA_YSTR", required_sample_ng=5,
        scheduled_start=WINDOW_A2[0], scheduled_end=WINDOW_A2[1],
    )
    assert get_evidence_item(item_id)["remaining_sample_ng"] == 8  # 13 - 5

    cancel_lab_analysis(a2["id"])
    # The compensating cancel restores the ledger to exactly its pre-reserve state.
    assert get_evidence_item(item_id)["remaining_sample_ng"] == 13


def test_sample_conservation_invariant_and_final_status(api):
    """PRD section 3.5: "The ledger obeys a strict conservation invariant over
    each evidence item: `initial_sample_ng` always equals `remaining_sample_ng`
    plus the reservations of that item's analyses in `SCHEDULED` or
    `SAMPLE_SHIPPED`, plus the consumed masses of its analyses in
    `RESULT_RECORDED` or `INTERPRETED`."
    PRD section 3.5: "Cancelling is possible only from `SCHEDULED` — once the
    sample has shipped, the reservation is committed — and refunds the entire
    `reserved_sample_ng`, again re-deriving the status".

    Design: Difficulty/compensating_invariant/sample_mass_conserved_across_reserve_settle_cancel
    """
    ctx = _testing_ctx(state_code="TN", name="Tennessee")
    item_id = ctx["item"]["id"]

    a1 = create_lab_analysis(
        item_id, ctx["authorization"]["id"],
        required_sample_ng=15,
        scheduled_start=WINDOW_A1[0], scheduled_end=WINDOW_A1[1],
    )
    assert_sample_ledger_conservation(
        get_evidence_item(item_id), _analyses_of(api, item_id)
    )
    ship_sample(a1["id"])
    record_result(a1["id"], outcome="EXCLUSIONARY", actual_consumed_ng=12)
    assert_sample_ledger_conservation(
        get_evidence_item(item_id), _analyses_of(api, item_id)
    )

    a2 = create_lab_analysis(
        item_id, ctx["authorization"]["id"],
        test_type="DNA_YSTR", required_sample_ng=5,
        scheduled_start=WINDOW_A2[0], scheduled_end=WINDOW_A2[1],
    )
    assert_sample_ledger_conservation(
        get_evidence_item(item_id), _analyses_of(api, item_id)
    )
    cancel_lab_analysis(a2["id"])

    item = get_evidence_item(item_id)
    assert_sample_ledger_conservation(item, _analyses_of(api, item_id))
    assert item["testing_status"] == "TESTED", (
        "a RESULT_RECORDED analysis exists, no active reservations, remaining >= 5"
    )
