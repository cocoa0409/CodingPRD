"""Sample triage and test-result recording.

Covers the terminal REJECTED state of samples, the unknown-protocol rejection,
triage inadmissibility on an already-accepted sample, and the deterministic
outcome computation: the CONDITIONAL band, the DAMAGED cap, and the
safety-critical override.
"""

from test_helpers import (
    ApiErrorId,
    DEFAULT_ENGINEER_ID,
    record_result,
    refresh_project,
    reject_sample,
    result_payload,
    setup_open_project,
    setup_project_in_testing,
    submit_and_accept_sample,
    submit_sample,
    triage_payload,
    validate_error,
    validate_paginated,
)


def test_sample_rejected_is_terminal_results_rejected(api, officer_headers, engineer_headers):
    """PRD §3.2: "Accepting moves the sample to `ACCEPTED`; rejecting moves it
    to `REJECTED`, which is terminal."
    PRD §3.2: "the sample must be `ACCEPTED` or `TESTED` — recording against a
    `SUBMITTED` or `REJECTED` sample is rejected with `ERR_SAMPLE_NOT_ACCEPTED`."
    PRD §3.2: "When a project's first sample is accepted, the project moves
    automatically from `STANDARD_SELECTED` to `TESTING` and becomes eligible to
    accumulate protocol results."

    Design: Corner/state_machines/sample_rejected_is_terminal_results_rejected
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    sample = submit_sample(api, ctx["project"]["id"], mfr_id, serial_no="S-1")
    rejected = reject_sample(api, sample["id"], note="Cracked enclosure")
    assert rejected["status"] == "REJECTED"

    response = api.record_result(
        sample["id"], result_payload("P-SAFE", 60), engineer_headers
    )
    validate_error(response, ApiErrorId.ERR_SAMPLE_NOT_ACCEPTED)

    samples, _meta = validate_paginated(
        api.list_samples(ctx["project"]["id"], officer_headers)
    )
    view = next(s for s in samples if s["id"] == sample["id"])
    assert view["status"] == "REJECTED"
    assert view["results"] == [], "a rejected result must not be appended"

    project = refresh_project(api, ctx["project"]["id"])
    assert project["status"] == "STANDARD_SELECTED", (
        "a REJECTED sample never starts TESTING"
    )


def test_unknown_protocol_code_in_results_returns_422(api, officer_headers, engineer_headers):
    """PRD §3.2: "The protocol code must be declared among the pinned standard's
    `test_protocols` (`ERR_UNKNOWN_PROTOCOL_CODE`)"
    PRD §3.2: "The first result recorded on a sample moves it automatically from
    `ACCEPTED` to `TESTED`."

    Design: Corner/validations/unknown_protocol_code_in_results_returns_422
    """
    ctx = setup_project_in_testing(api)
    sample = ctx["sample"]
    response = api.record_result(
        sample["id"], result_payload("P-NOPE", 10), engineer_headers
    )
    validate_error(response, ApiErrorId.ERR_UNKNOWN_PROTOCOL_CODE)
    samples, _meta = validate_paginated(
        api.list_samples(ctx["project"]["id"], officer_headers)
    )
    view = next(s for s in samples if s["id"] == sample["id"])
    assert view["results"] == [], "a rejected result must not be appended"
    assert view["status"] == "ACCEPTED", (
        "the first-result flip to TESTED must not happen for a rejected result"
    )


def test_triage_on_accepted_sample_returns_invalid_state(api, officer_headers, engineer_headers):
    """PRD §3.2: "A `TestEngineer` triages each submitted sample with a
    `decision` and an optional `note`."
    PRD §2.8: "and any other inadmissible state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/triage_on_accepted_sample_returns_invalid_state
    """
    ctx = setup_project_in_testing(api)
    sample = ctx["sample"]
    assert sample["status"] == "ACCEPTED"
    response = api.triage_sample(
        sample["id"], triage_payload("REJECT"), engineer_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    samples, _meta = validate_paginated(
        api.list_samples(ctx["project"]["id"], officer_headers)
    )
    view = next(s for s in samples if s["id"] == sample["id"])
    assert view["status"] == "ACCEPTED", "a rejected triage must not mutate the sample"
    assert view["triaged_by"] == DEFAULT_ENGINEER_ID


def test_conditional_band_and_damaged_cap_on_temperature_protocol(api):
    """PRD §3.2: "a conditional band floor is computed as the `pass_threshold`
    multiplied by 0.95, rounded half-up to two decimal places. The raw outcome
    is `PASS` when the `measured_value` is at least the threshold, `CONDITIONAL`
    when it falls below the threshold but is at least the band floor, and `FAIL`
    when it falls below the band floor."
    PRD §3.2: "if the raw outcome is `PASS` and the sample is `DAMAGED`, the
    outcome is `CONDITIONAL`, because a damaged sample can never pass outright"
    PRD §3.2: "The result's `margin` is the `measured_value` minus the
    `pass_threshold`, rounded half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/test_outcome_conditional_band_and_damage_cap
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    intact = submit_and_accept_sample(
        api, ctx["project"]["id"], mfr_id, serial_no="SI-1", condition="INTACT"
    )
    damaged = submit_and_accept_sample(
        api, ctx["project"]["id"], mfr_id, serial_no="SD-1", condition="DAMAGED"
    )
    # P-TEMP: threshold 100, band floor 95. 97 is inside the band.
    intact = record_result(api, intact["id"], "P-TEMP", 97)
    band = next(r for r in intact["results"] if r["protocol_code"] == "P-TEMP")
    assert band["outcome"] == "CONDITIONAL"
    assert band["margin"] == -3
    # 105 clears the threshold, but a DAMAGED sample is capped at CONDITIONAL.
    damaged = record_result(api, damaged["id"], "P-TEMP", 105)
    capped = next(r for r in damaged["results"] if r["protocol_code"] == "P-TEMP")
    assert capped["outcome"] == "CONDITIONAL"
    assert capped["margin"] == 5
    assert intact["status"] == "TESTED"
    assert damaged["status"] == "TESTED"


def test_safety_critical_band_result_becomes_fail(api):
    """PRD §3.2: "otherwise, if the raw outcome is `CONDITIONAL` and the
    protocol is both `mandatory` and `safety_critical`, the outcome is `FAIL`,
    because safety-critical protocols never yield `CONDITIONAL`."

    Design: Difficulty/combinatorial_formula/test_outcome_conditional_band_and_damage_cap
    """
    ctx = setup_open_project(api)
    mfr_id = ctx["manufacturer"]["id"]
    intact = submit_and_accept_sample(
        api, ctx["project"]["id"], mfr_id, serial_no="SI-1", condition="INTACT"
    )
    damaged = submit_and_accept_sample(
        api, ctx["project"]["id"], mfr_id, serial_no="SD-1", condition="DAMAGED"
    )
    intact = record_result(api, intact["id"], "P-TEMP", 97)
    damaged = record_result(api, damaged["id"], "P-TEMP", 105)
    # P-SAFE: threshold 50, band floor 47.5; 48 is in-band but the protocol is
    # mandatory and safety-critical, so CONDITIONAL converts to FAIL.
    intact = record_result(api, intact["id"], "P-SAFE", 48)
    safety = next(r for r in intact["results"] if r["protocol_code"] == "P-SAFE")
    assert safety["outcome"] == "FAIL"
    assert safety["margin"] == -2
    assert intact["status"] == "TESTED"
    assert damaged["status"] == "TESTED"
