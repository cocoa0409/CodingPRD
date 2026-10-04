"""Production-run scheduling gates: certification, producibility, label
pinning, isolate support, window semantics, dedication rules, and the
line-version OCC rule (PRD sections 2.7, 2.8, 3.5)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success, validate_paginated,
    create_production_run_payload,
    create_bare_product, create_draft_label, submit_label,
    transition_product, create_product_with_approved_label,
    create_pilot_product_with_label, create_active_product_with_label,
    create_owned_line, create_coman_line, certify_coman_line,
    post_certification_audit,
    create_lto_program, setup_lto_program,
    set_clock, setup_production_scenario, schedule_run,
    current_line_version, fetch_line,
)

_PLANT = TEST_USERS["plant_manager_headers"]
_CH = TEST_USERS["channel_manager_headers"]

_CE1_START = "2026-09-12T08:00:00Z"
_CE1_END = "2026-09-12T12:00:00Z"


def _run_payload(line_id, product_id, label_id, expected_version, **overrides):
    return create_production_run_payload(
        production_line_id=line_id, product_id=product_id,
        label_version_id=label_id, expected_line_version=expected_version,
        **overrides)


def test_run_create_rejected_while_line_certification_pending(api):
    """PRD section 3.5: "the line must be `CERTIFIED`
    (`ERR_LINE_NOT_CERTIFIED`)" — a CO_MAN line still PENDING cannot accept a
    run, and the gate reads the OTHER entity's state, not the run's.

    Design: Difficulty/cross_entity_state_dependency/cesd_run_create_requires_line_certified
    """
    set_clock()
    line = create_coman_line(line_code="LINE-CE-1",
                             monthly_reserved_capacity_kg=5000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    product, label = create_active_product_with_label(
        {"product_code": "PROD-CE-1"})
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"]),
                     planned_quantity_kg=100, scheduled_start=_CE1_START,
                     scheduled_end=_CE1_END),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_CERTIFIED)


def test_run_create_succeeds_after_passing_audit(api):
    """PRD section 3.5: "the line must be `CERTIFIED`
    (`ERR_LINE_NOT_CERTIFIED`)" — after a passing equivalence audit the
    identical create lands the run in SCHEDULED. PRD section 3.3: "From
    `PENDING` or `SUSPENDED` a passing audit certifies the line".

    Design: Difficulty/cross_entity_state_dependency/cesd_run_create_requires_line_certified
    """
    set_clock()
    line = create_coman_line(line_code="LINE-CE-1",
                             monthly_reserved_capacity_kg=5000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    product, label = create_active_product_with_label(
        {"product_code": "PROD-CE-1"})
    certify_coman_line(line["id"], texture_score=95, moisture_variance_pct=1.0)
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"]),
                     planned_quantity_kg=100, scheduled_start=_CE1_START,
                     scheduled_end=_CE1_END),
        _PLANT)
    run = validate_success(resp, 201)
    assert run["status"] == "SCHEDULED"
    assert fetch_line(line["id"])["certification_status"] == "CERTIFIED"


def _suspended_line_with_overlapping_run(api):
    """CO_MAN line certified, one run scheduled 09-10 08:00-10:00, then a
    failing audit suspends certification. Returns (line, product, label)."""
    line = create_coman_line(line_code="LINE-PV-2",
                             monthly_reserved_capacity_kg=5000,
                             hourly_capacity_kg=200,
                             supported_isolate_types=["PEA"])
    certify_coman_line(line["id"], texture_score=90, moisture_variance_pct=1.0)
    product, label = create_active_product_with_label(
        {"product_code": "PROD-PV-2"})
    schedule_run({"line": line, "product": product, "label": label},
                 planned_quantity_kg=100,
                 scheduled_start="2026-09-10T08:00:00Z",
                 scheduled_end="2026-09-10T10:00:00Z")
    post_certification_audit(line["id"], texture_score=70,
                             moisture_variance_pct=1.0)
    return line, product, label


def test_suspended_certification_reports_before_window_conflict(api):
    """PRD section 2.8: "Validations run in a fixed cascade and the first
    failing check determines the error response; later checks are not
    consulted." — "6. **Compliance gates.** ... line certification for run
    scheduling and run starting (`ERR_LINE_NOT_CERTIFIED`)" runs ahead of
    "7. **Temporal rules.** ... line window conflicts
    (`ERR_RUN_WINDOW_CONFLICT`)". A create that violates both (certification
    SUSPENDED, window 09:00-11:00 overlapping an existing 08:00-10:00 run)
    reports ERR_LINE_NOT_CERTIFIED.

    Design: Difficulty/priority_pair_validation_conflict/pvc_certification_beats_window_overlap
    """
    set_clock()
    line, product, label = _suspended_line_with_overlapping_run(api)
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"]),
                     planned_quantity_kg=50,
                     scheduled_start="2026-09-10T09:00:00Z",
                     scheduled_end="2026-09-10T11:00:00Z"),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_CERTIFIED)


def test_suspended_certification_alone_reports_line_not_certified(api):
    """PRD section 2.8 tier 6: "line certification for run scheduling and run
    starting (`ERR_LINE_NOT_CERTIFIED`)" fires even when no temporal rule is
    violated — the same create on a non-overlapping window (2026-09-11) fails
    identically, proving the error comes from the compliance gate.

    Design: Difficulty/priority_pair_validation_conflict/pvc_certification_beats_window_overlap
    """
    set_clock()
    line, product, label = _suspended_line_with_overlapping_run(api)
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"]),
                     planned_quantity_kg=50,
                     scheduled_start="2026-09-11T08:00:00Z",
                     scheduled_end="2026-09-11T12:00:00Z"),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_CERTIFIED)


def test_run_starting_when_another_ends_is_legal(api):
    """PRD section 3.5: "the window may not overlap any other `SCHEDULED` or
    `IN_PROGRESS` run on the same line — with half-open semantics, so a run
    beginning exactly when another ends is legal —
    (`ERR_RUN_WINDOW_CONFLICT`)". A 10:00-12:00 run follows an 08:00-10:00
    run without conflict.

    Design: Difficulty/resource_temporal_overlap/rto_line_run_windows_half_open
    """
    ctx = setup_production_scenario(
        line_overrides={"line_code": "LINE-OV-1"},
        product_overrides={"product_code": "PROD-OV-1"})
    schedule_run(ctx, planned_quantity_kg=100,
                 scheduled_start="2026-09-10T08:00:00Z",
                 scheduled_end="2026-09-10T10:00:00Z")
    run_b = schedule_run(ctx, planned_quantity_kg=100,
                         scheduled_start="2026-09-10T10:00:00Z",
                         scheduled_end="2026-09-10T12:00:00Z")
    assert run_b["status"] == "SCHEDULED"


def test_overlapping_run_window_conflicts(api):
    """PRD section 3.5: "the window may not overlap any other `SCHEDULED` or
    `IN_PROGRESS` run on the same line — with half-open semantics, so a run
    beginning exactly when another ends is legal —
    (`ERR_RUN_WINDOW_CONFLICT`)". A 09:59-11:00 run overlaps the existing
    08:00-10:00 run by one minute and is refused; only the two legal runs
    remain on the line.

    Design: Difficulty/resource_temporal_overlap/rto_line_run_windows_half_open
    """
    ctx = setup_production_scenario(
        line_overrides={"line_code": "LINE-OV-1"},
        product_overrides={"product_code": "PROD-OV-1"})
    schedule_run(ctx, planned_quantity_kg=100,
                 scheduled_start="2026-09-10T08:00:00Z",
                 scheduled_end="2026-09-10T10:00:00Z")
    schedule_run(ctx, planned_quantity_kg=100,
                 scheduled_start="2026-09-10T10:00:00Z",
                 scheduled_end="2026-09-10T12:00:00Z")
    resp = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"],
                     current_line_version(ctx["line"]["id"]),
                     planned_quantity_kg=100,
                     scheduled_start="2026-09-10T09:59:00Z",
                     scheduled_end="2026-09-10T11:00:00Z"),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_CONFLICT)
    _rows, meta = validate_paginated(api.list_production_runs(
        _PLANT, params={"production_line_id": ctx["line"]["id"]}))
    assert meta["total_count"] == 2


def test_run_product_isolate_must_be_supported_by_line(api):
    """PRD section 3.5: "the product's isolate type must appear in the line's
    `supported_isolate_types` (`ERR_ISOLATE_NOT_SUPPORTED`)" — a PEA product
    cannot run on a line supporting only SOY.

    Design: Corner/validations/cn_val_isolate_not_supported
    """
    line = create_owned_line(line_code="LINE-K-21",
                             supported_isolate_types=["SOY"])
    product, label = create_active_product_with_label(
        {"product_code": "PROD-K-21"})
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"])),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_ISOLATE_NOT_SUPPORTED)


def test_run_label_must_belong_to_run_product(api):
    """PRD section 3.5: "the pinned label must be `APPROVED`
    (`ERR_LABEL_NOT_APPROVED`) and must belong to the run's product
    (`ERR_LABEL_PRODUCT_MISMATCH`)". Product B is producible and label A is
    APPROVED, so the only failing gate is label-product ownership.

    Design: Corner/validations/cn_val_label_product_mismatch
    """
    line = create_owned_line(line_code="LINE-K-1")
    product_a, label_a = create_active_product_with_label(
        {"product_code": "PROD-K-23A"})
    product_b = create_bare_product(product_code="PROD-K-23B")
    transition_product(product_b["id"], "PILOT")
    resp = api.create_production_run(
        _run_payload(line["id"], product_b["id"], label_a["id"],
                     current_line_version(line["id"])),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_LABEL_PRODUCT_MISMATCH)
    _rows, meta = validate_paginated(api.list_production_runs(_PLANT))
    assert meta["total_count"] == 0


def test_run_cannot_pin_unapproved_label(api):
    """PRD section 3.5: "the pinned label must be `APPROVED`
    (`ERR_LABEL_NOT_APPROVED`)" — a merely SUBMITTED label keeps unapproved
    nutrition and claims off the line.

    Design: Corner/validations/cn_val_label_not_approved_on_run
    """
    line = create_owned_line(line_code="LINE-K-1")
    product = create_bare_product(product_code="PROD-K-24")
    label = create_draft_label(product["id"])
    submit_label(label["id"])
    transition_product(product["id"], "PILOT")
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"])),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED)


def test_dedicated_run_rejected_while_program_proposed(api):
    """PRD section 3.5: "The program must be accepting volume, meaning
    `ACTIVE` or `IN_WINDOW` (`ERR_PROGRAM_NOT_ACCEPTING_RUNS`)" — dedication
    to a PROPOSED program fails.

    Design: Corner/validations/cn_val_program_not_accepting_runs
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-25"})
    program = create_lto_program(ctx["product"]["id"],
                                 program_code="PROG-K-25",
                                 partner_code="CHAIN-K25")
    resp = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"],
                     current_line_version(ctx["line"]["id"]),
                     program_id=program["id"], channel="FOODSERVICE",
                     planned_quantity_kg=50),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTING_RUNS)


def test_dedicated_run_channel_must_match_program_type(api):
    """PRD section 3.5: "the run's `channel` must match the program's type
    mapping — `FOODSERVICE_LTO` programs take `FOODSERVICE` runs and
    `SAMPLING_DEMO` programs take `SAMPLES` runs
    (`ERR_CHANNEL_PROGRAM_MISMATCH`)" — a SAMPLES run cannot serve an LTO
    program.

    Design: Corner/validations/cn_val_channel_program_mismatch
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-26"})
    program = setup_lto_program(ctx["product"]["id"],
                                program_code="PROG-K-26",
                                partner_code="CHAIN-K26")
    resp = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"],
                     current_line_version(ctx["line"]["id"]),
                     program_id=program["id"], channel="SAMPLES",
                     planned_quantity_kg=50),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_PROGRAM_MISMATCH)


def test_dedicated_run_window_must_fit_inside_program_window(api):
    """PRD section 3.5: "the run's window must sit entirely inside the
    program's window from `window_start` to `window_end`
    (`ERR_RUN_OUTSIDE_PROGRAM_WINDOW`)" — a run scheduled 2026-10-05 falls
    outside a program window ending 2026-09-30.

    Design: Corner/validations/cn_val_run_outside_program_window
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-27"})
    program = setup_lto_program(ctx["product"]["id"],
                                program_code="PROG-K-27",
                                partner_code="CHAIN-K27",
                                window_start="2026-09-01T00:00:00Z",
                                window_end="2026-09-30T23:59:59Z")
    resp = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"],
                     current_line_version(ctx["line"]["id"]),
                     program_id=program["id"], channel="FOODSERVICE",
                     planned_quantity_kg=50,
                     scheduled_start="2026-10-05T08:00:00Z",
                     scheduled_end="2026-10-05T12:00:00Z"),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_RUN_OUTSIDE_PROGRAM_WINDOW)


def test_run_window_with_empty_span_is_invalid(api):
    """PRD section 3.5: "the window's end must sit after its start
    (`ERR_INVALID_WINDOW`)" — a zero-length window is refused before any
    overlap or capacity analysis.

    Design: Corner/validations/cn_val_invalid_window
    """
    line = create_owned_line(line_code="LINE-K-1")
    product, label = create_active_product_with_label(
        {"product_code": "PROD-K-38"})
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"]),
                     planned_quantity_kg=100,
                     scheduled_start="2026-09-05T08:00:00Z",
                     scheduled_end="2026-09-05T08:00:00Z"),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_run_for_development_product_is_not_producible(api):
    """PRD section 3.5: "the product must be in `PILOT` or `ACTIVE`
    (`ERR_PRODUCT_NOT_PRODUCIBLE`)" — a DEVELOPMENT product cannot be
    extruded even with an APPROVED label.

    Design: Corner/validations/cn_val_product_not_producible
    """
    line = create_owned_line(line_code="LINE-K-1")
    product, label = create_product_with_approved_label(
        {"product_code": "PROD-K-41"})
    resp = api.create_production_run(
        _run_payload(line["id"], product["id"], label["id"],
                     current_line_version(line["id"])),
        _PLANT)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_PRODUCIBLE)


def test_run_create_with_stale_line_version_rejected(api):
    """PRD section 2.7: "Because scheduling a run increments the line's
    `version` by one, a client holding a previously observed version finds its
    next create rejected as stale until it re-reads the line" — the stale
    retry fails with `ERR_STALE_LINE_VERSION` (HTTP 412), and the retry armed
    with the freshly read version succeeds.

    Design: Corner/cross_cutting_layers/cn_occ_run_create_stale_line_version
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-60"})
    stale_version = ctx["line"]["version"]
    schedule_run(ctx)
    resp_stale = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"], stale_version,
                     planned_quantity_kg=50,
                     scheduled_start="2026-09-08T08:00:00Z",
                     scheduled_end="2026-09-08T12:00:00Z"),
        _PLANT)
    validate_error(resp_stale, ApiErrorId.ERR_STALE_LINE_VERSION)
    resp_retry = api.create_production_run(
        _run_payload(ctx["line"]["id"], ctx["product"]["id"],
                     ctx["label"]["id"],
                     current_line_version(ctx["line"]["id"]),
                     planned_quantity_kg=50,
                     scheduled_start="2026-09-08T08:00:00Z",
                     scheduled_end="2026-09-08T12:00:00Z"),
        _PLANT)
    run_b = validate_success(resp_retry, 201)
    assert run_b["status"] == "SCHEDULED"


def test_runs_reverse_lookup_by_program(api):
    """PRD section 4 (GET /protein-ops/production-runs): "List runs;
    filterable by `production_line_id`, `product_id`, `label_version_id`,
    `program_id`, `status`". Filtering by `program_id` returns exactly the
    two dedicated runs and excludes the non-dedicated run on the same line.

    Design: Corner/endpoints/cn_ep_runs_reverse_lookup_by_program
    """
    ctx = setup_production_scenario(
        product_overrides={"product_code": "PROD-K-50"})
    program = setup_lto_program(ctx["product"]["id"],
                                program_code="PROG-K-50",
                                partner_code="CHAIN-K50")
    run1 = schedule_run(ctx, channel="FOODSERVICE", planned_quantity_kg=50,
                        scheduled_start="2026-09-05T08:00:00Z",
                        scheduled_end="2026-09-05T12:00:00Z",
                        program_id=program["id"])
    run2 = schedule_run(ctx, channel="FOODSERVICE", planned_quantity_kg=50,
                        scheduled_start="2026-09-06T08:00:00Z",
                        scheduled_end="2026-09-06T12:00:00Z",
                        program_id=program["id"])
    run3 = schedule_run(ctx, channel="RETAIL_FROZEN", planned_quantity_kg=50,
                        scheduled_start="2026-09-07T08:00:00Z",
                        scheduled_end="2026-09-07T12:00:00Z")
    data, meta = validate_paginated(api.list_production_runs(
        _CH, params={"program_id": program["id"]}))
    assert meta["total_count"] == 2
    ids = {row["id"] for row in data}
    assert ids == {run1["id"], run2["id"]}
    assert run3["id"] not in ids
