"""Corner queue — validation-layer claims: auth headers, wave-window boundary,
conditional site_id, and the IRB maximum window length."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_irb_protocol,
    create_contract_payload,
    create_irb_protocol_payload,
    create_wave,
    create_wave_payload,
    get_study,
    get_wave,
    irb_decision_payload,
    set_clock,
    setup_contract_with_study,
    setup_study_with_locked_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

PI = TEST_USERS["principal_investigator_headers"]
DM = TEST_USERS["data_manager_headers"]
IRB = TEST_USERS["irb_reviewer_headers"]


def test_missing_auth_headers_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying an
    `X-User-Role` value that is not one of these nine declared role names, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_returns_400
    """
    resp = api.create_contract(
        create_contract_payload(
            agency_code="ACF-OPRE", title="T", award_amount_cents=1000
        ),
        {},  # no X-User-ID / X-User-Role headers at all
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_wave_open_window_boundary(api):
    """PRD §3.6: "A `DataManager` opens a wave from `PLANNED` or `SUSPENDED` —
    from any other state the rejection is `ERR_WAVE_INVALID_STATE` — and only
    while the current logical time lies within the wave's window: at exactly
    `open_at` opening is allowed, at exactly `close_at` it is not, and any
    attempt outside the window is rejected with `ERR_WAVE_WINDOW_NOT_STARTED`."

    Design: Corner/validations/wave_open_window_boundary
    """
    ctx = setup_study_with_locked_plan()
    study_id = ctx["study"]["id"]
    approve_irb_protocol(study_id)
    wave = create_wave(
        study_id, wave_type="SURVEY",
        open_at="2026-10-01T00:00:00Z", close_at="2026-11-01T00:00:00Z",
    )

    # Before open_at: rejected.
    set_clock("2026-09-15T00:00:00Z")
    resp = api.open_wave(wave["id"], DM)
    validate_error(resp, ApiErrorId.ERR_WAVE_WINDOW_NOT_STARTED)
    assert get_wave(wave["id"])["status"] == "PLANNED"

    # At exactly open_at (inclusive window start): allowed.
    set_clock("2026-10-01T00:00:00Z")
    wave = validate_success(api.open_wave(wave["id"], DM), 200)
    assert wave["status"] == "OPEN"
    assert get_study(study_id)["status"] == "DATA_COLLECTION"


def test_site_visit_site_id_conditional_requirement(api):
    """PRD §3.6: "A `SITE_VISIT` wave must name its host through `site_id`,
    while `site_id` is forbidden — present only as null — on the other two wave
    types; violating either rule is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/site_visit_site_id_conditional_requirement
    """
    ctx = setup_study_with_locked_plan()
    study_id = ctx["study"]["id"]
    site_a = ctx["site"]

    resp = api.create_wave(
        study_id,
        create_wave_payload(
            wave_type="SITE_VISIT",
            open_at="2026-10-01T00:00:00Z", close_at="2026-10-03T00:00:00Z",
        ),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)  # SITE_VISIT without site_id

    resp = api.create_wave(
        study_id,
        create_wave_payload(
            wave_type="SURVEY", site_id=site_a["id"],
            open_at="2026-10-01T00:00:00Z", close_at="2026-11-01T00:00:00Z",
        ),
        DM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)  # site_id forbidden on SURVEY


def test_irb_window_longer_than_max_invalid(api):
    """PRD §3.3: "the payload must carry `approval_start` and `approval_end`,
    the end must be after the start, and the window's length must not exceed
    `IRB_MAX_APPROVAL_DAYS` of 365 days — violations of any of these are
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/irb_window_longer_than_max_invalid
    """
    ctx = setup_contract_with_study()
    study_id = ctx["study"]["id"]
    irb = validate_success(
        api.create_irb_protocol(study_id, create_irb_protocol_payload(), PI), 201
    )
    validate_success(api.submit_irb_protocol(irb["id"], PI), 200)

    # [2026-09-01, 2027-09-02) spans 366 days > 365.
    resp = api.irb_decision(
        irb["id"],
        irb_decision_payload(
            "APPROVED",
            approval_start="2026-09-01T00:00:00Z",
            approval_end="2027-09-02T00:00:00Z",
        ),
        IRB,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    protocols, _ = validate_paginated(api.list_irb_protocols(study_id, PI))
    assert next(p for p in protocols if p["id"] == irb["id"])["status"] == "SUBMITTED"
