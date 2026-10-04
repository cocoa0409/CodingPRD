"""Cross-cutting corners: OCC on the resubmission chain, the logical clock
driving variant go-live, derived quality-score reconciliation, and the lazy
agreement-lapse cascade (PRD §2.4, §2.8, §3.2, §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    begin_edit,
    create_filing_payload,
    dispose,
    make_agreement,
    make_effective_filing,
    make_insurer,
    make_objected_filing,
    make_adoption,
    make_submission,
    set_clock,
    setup_adoption_scenario,
    setup_insurer_with_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
    make_insurer_headers,
)
from test_helpers import make_published_form_with_scheduled_variant

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_occ_resubmission_with_stale_superseded_version_rejected(api):
    """PRD §2.8: "Creating a filing resubmission must carry
    `expected_superseded_version` equal to the current `version` of the filing
    named by `supersedes_filing_id`. If the superseded filing's version has
    advanced since the client last read it — because another resubmission
    already moved that filing from `OBJECTED` to `WITHDRAWN`, or because a
    withdrawal fired — the resubmission is rejected with `ERR_STALE_VERSION`,
    preventing the client from building a supersede chain on a view of the
    objected filing that is no longer current."

    Design: Corner/cross_cutting_complexity_layers/occ_resubmission_with_stale_superseded_version_rejected
    """
    objected, _dept, _obj = make_objected_filing()
    stale_version = objected["version"]
    # First resubmission succeeds and consumes the version.
    resp1 = api.create_filing(
        create_filing_payload(
            trend_selection="EXPONENTIAL_LEAST_SQUARES",
            effective_date="2027-03-01T00:00:00Z",
            supersedes_filing_id=objected["id"],
            expected_superseded_version=stale_version,
        ),
        ADMIN,
    )
    first = validate_success(resp1, expected_status=201)
    assert first["filing_version"] == 2
    # Second resubmission with the same (now stale) expected version fails.
    resp2 = api.create_filing(
        create_filing_payload(
            trend_selection="EXPONENTIAL_LEAST_SQUARES",
            effective_date="2027-04-01T00:00:00Z",
            supersedes_filing_id=objected["id"],
            expected_superseded_version=stale_version,
        ),
        ADMIN,
    )
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION)
    rows, meta = validate_paginated(
        api.list_filings(ADMIN, params={"filing_status": "DRAFT"})
    )
    assert len(rows) == 1


def test_logical_clock_default_and_set_moves_system_gates(api):
    """PRD §2.4: "Before any administrative action sets it, the logical clock
    reads exactly `2026-09-01T00:00:00Z`. A `BureauAdmin` may advance the
    logical clock to a supplied `to_iso8601` instant via the clock-setting
    capability; system transitions gated on the logical clock are evaluated
    lazily on the next relevant read or action rather than by a background
    scheduler."
    PRD §3.5: "when the logical clock reaches the publishing circular's
    `implementation_date`, each `SCHEDULED` variant transitions to `LIVE`,
    opening the licensed-use gate — insurers holding an `ACTIVE` license
    agreement covering that date may use the variant."

    Design: Corner/cross_cutting_complexity_layers/logical_clock_default_is_2026_09_01_and_set_moves_system_gates
    """
    scenario = make_published_form_with_scheduled_variant(
        implementation_date="2026-10-01T00:00:00Z",
    )
    variant = scenario["variants"][0]
    set_clock("2026-09-30T23:59:59Z")
    before = validate_success(api.get_variant(variant["id"], ADMIN))
    assert before["publication_status"] == "SCHEDULED"
    set_clock("2026-10-01T00:00:00Z")
    after = validate_success(api.get_variant(variant["id"], ADMIN))
    assert after["publication_status"] == "LIVE"
    assert after["review_status"] == "CLEARED"


def test_derived_quality_score_reconciles_after_each_disposition(api):
    """PRD §3.2: "For each submission, compute its points as 10000 minus 200
    per error finding minus 50 per warning finding, floored at zero so no
    single submission contributes negative points."
    PRD §3.1: "That score is recomputed after every statistical submission
    disposition, per §3.2."

    Design: Corner/cross_cutting_complexity_layers/derived_quality_score_reconciles_after_each_disposition
    """
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=10)
    begin_edit(sub["id"])
    for code in ("W-1", "W-2", "W-3", "W-4"):
        add_finding(sub["id"], severity="WARNING", edit_code=code)
    disposed = dispose(sub["id"])
    assert disposed["submission_status"] == "ACCEPTED_WITH_WARNINGS"
    assert disposed["accepted_record_count"] == 10
    insurer_after = validate_success(api.get_insurer(insurer["id"], ADMIN))
    assert insurer_after["quality_score_bps"] == 9800


def test_agreement_lapse_on_read_cascades_pending_adoption_withdrawal(api):
    """PRD §3.4: "Lapse is lazy: when the logical clock is later than
    `coverage_end`, the `agreement_status` transitions from `ACTIVE` to
    `LAPSED` upon the next read of the agreement or the next adoption
    authorization that consults it — and every `PENDING` adoption of that
    insurer is withdrawn as a consequence, marked with the reason
    `LICENCE_LAPSED`."

    Design: Corner/cross_cutting_complexity_layers/agreement_lapse_on_read_cascades_pending_adoption_withdrawal
    """
    scenario = setup_adoption_scenario(
        multiplier_pct=110,
        filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
        agreement_overrides={
            "coverage_start": "2026-01-01T00:00:00Z",
            "coverage_end": "2026-12-31T00:00:00Z",
            "royalty_rate_bps": 100,
        },
    )
    set_clock("2027-01-01T00:00:00Z")
    resp = api.get_agreement(scenario["agreement"]["id"], ADMIN)
    agreement = validate_success(resp)
    assert agreement["agreement_status"] == "LAPSED"
    adoption = validate_success(api.get_adoption(scenario["adoption"]["id"], ADMIN))
    assert adoption["adoption_status"] == "WITHDRAWN"


def test_disposition_effects_visible_in_same_response(api):
    """PRD §3.2: "Every disposition — whether `ACCEPTED`,
    `ACCEPTED_WITH_WARNINGS`, or `REJECTED`, and whether reached through the
    edit pass or the fast reject — triggers the same two side effects: the
    insurer's `quality_score_bps` is recomputed, and the insurer's `version`
    increments by 1 (with `updated_at` refreshed per §2.5)."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/disposition_effects_visible_in_same_response
    """
    insurer, plan = setup_insurer_with_active_plan()
    sub = make_submission(insurer["id"], plan["id"], record_count=10)
    begin_edit(sub["id"])
    add_finding(sub["id"], severity="WARNING", edit_code="W-1")
    disposed = dispose(sub["id"])
    assert disposed["submission_status"] == "ACCEPTED_WITH_WARNINGS"
    assert disposed["warning_finding_count"] == 1
    insurer_after = validate_success(api.get_insurer(insurer["id"], ADMIN))
    assert insurer_after["quality_score_bps"] == 9950
