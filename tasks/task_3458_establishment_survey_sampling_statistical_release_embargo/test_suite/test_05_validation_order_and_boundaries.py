"""Depth tests: validation-stage ordering and boundary precision.

The fixed validation pipeline makes the state-category error win over the
disclosure-safety error, and the temporal error win over the fiscal one;
the certification rate floor and the embargo-open instant are inclusive
boundaries.
"""
from test_helpers import (
    ANALYST_USER_ID,
    ApiErrorId,
    TEST_USERS,
    accept_report,
    api_client,
    approve_disclosure,
    assert_same_instant,
    certify_cycle,
    close_collection,
    collect_cycle,
    create_cycle,
    create_program,
    create_release,
    create_stratum,
    find_case,
    get_enrollment,
    get_grant,
    make_accredited_media_headers,
    open_collection,
    record_contact,
    release_advance_payload,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    submit_report,
    validate_error,
    validate_success,
)

COLLECTOR = TEST_USERS["collection_officer_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]


def test_open_embargo_state_error_precedes_disclosure_safety(api):
    """PRD §2.8: "Every request passes through a fixed pipeline of validation stages, evaluated in the order below. The first failing stage determines the response: its error is returned and no later stage is consulted."
    PRD §2.8 (stage 8): "embargo opening requires a `CERTIFIED` cycle, disclosure review requires `CERTIFIED` or `PUBLISHED`, and benchmark application requires the benchmark-month cycle in `CERTIFIED` or `PUBLISHED` (`ERR_CYCLE_NOT_CERTIFIED`, HTTP 409)"
    PRD §2.8 (stage 9): "Embargo opening and publication require an approved disclosure (`ERR_DISCLOSURE_NOT_APPROVED`, HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/open_embargo_state_error_precedes_disclosure_safety
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-09")  # stays SCHEDULED: never certified
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")
    set_clock("2026-10-01T13:00:00Z")  # inside the embargo window

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload("OPEN_EMBARGO",
                                expected_release_version=release["version"]),
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CERTIFIED)
    # 409; NOT ERR_DISCLOSURE_NOT_APPROVED — the state-category stage runs
    # before the disclosure-safety stage although both conditions hold.


def test_contact_timing_precedes_burden_fiscal(api):
    """PRD §2.8: "Every request passes through a fixed pipeline of validation stages, evaluated in the order below. The first failing stage determines the response: its error is returned and no later stage is consulted."
    PRD §2.8 (stage 10): "follow-up contact spacing (`ERR_CONTACT_TOO_SOON`, HTTP 422)"
    PRD §2.8 (stage 12): "the per-establishment annual burden budget (`ERR_BURDEN_BUDGET_EXCEEDED`, HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/contact_timing_precedes_burden_fiscal
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=22)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]

    # E1/E2 report (accepted), E3 silent -> follow-up case opened at close.
    cycle = create_cycle("CES", "2026-09")
    open_collection(cycle)
    accept_report(submit_report(en1, cycle["id"], 9)["id"])
    accept_report(submit_report(en2, cycle["id"], 11)["id"])
    close_collection(cycle)
    case = find_case(en3["id"], cycle["id"])

    # First contact of 20 minutes at 09-22T09:00: burden now 20 of 22.
    record_contact(case["id"], 20, at="2026-09-22T09:00:00Z")

    # Second contact one hour later AND 20 + 5 = 25 > 22: both rules fail.
    set_clock("2026-09-22T10:00:00Z")
    resp = api_client.advance_follow_up_case(
        case["id"],
        {"action": "RECORD_CONTACT", "contact_minutes": 5, "channel": "PHONE"},
        COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_CONTACT_TOO_SOON)
    # 422; business_temporal (earlier stage) wins over business_fiscal.

    assert get_enrollment(en3["id"])["burden_minutes_ytd"] == 20, (
        "rejected contact added nothing")


def test_certify_weighted_rate_exactly_at_threshold_passes(api):
    """PRD §3.5: "It demands that estimates have been computed since the last close or reopen — otherwise the advance is rejected with `ERR_ESTIMATES_NOT_COMPUTED` — and that the `weighted_response_rate` reaches at least 0.600000, with a null rate treated as 0, otherwise the advance is rejected with `ERR_RESPONSE_RATE_BELOW_MINIMUM`."
    PRD §3.5: "Success records the certifying analyst's `X-User-ID` in `certified_by_user_id`, the value the segregation-of-duties check later enforces."

    Design: Difficulty/boundary_precision_check/certify_weighted_rate_exactly_at_threshold_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=12,
        strata=[create_stratum("RETAIL", "SMALL", 30),
                create_stratum("RETAIL", "MEDIUM", 60)],
        annual_burden_budget_minutes=500)
    # allocations 2 and 10 -> weights 15.0 and 6.0
    panel = setup_enrolled_panel(
        "CES", specs=[("RETAIL", "SMALL", 2), ("RETAIL", "MEDIUM", 5)])
    en_rs1, en_rs2, en_rm1 = (panel["enrollments"][0],
                              panel["enrollments"][1],
                              panel["enrollments"][2])

    # RS1, RS2, RM1 respond; RM2..RM5 silent.
    cycle = collect_cycle("CES", "2026-09", panel["enrollments"],
                          {en_rs1["id"]: 4, en_rs2["id"]: 6, en_rm1["id"]: 8})
    assert cycle["weighted_response_rate"] == 0.600000, (
        "exactly at the threshold: (2x15.000000 + 1x6.000000) / "
        f"(2x15.000000 + 5x6.000000) = 36/60, got "
        f"{cycle['weighted_response_rate']}")

    certified = certify_cycle(cycle["id"], ANALYST_USER_ID)
    assert certified["cycle_status"] == "CERTIFIED", (
        "the >= boundary is inclusive; the gate passes")
    assert certified["certified_by_user_id"] == ANALYST_USER_ID, (
        "certifier identity recorded for segregation-of-duties checks")


def test_embargo_bulletin_at_exact_open_instant_succeeds(api):
    """PRD §3.9: "the logical clock must have reached the release's `embargo_open_at`, otherwise the read is rejected with `ERR_EMBARGO_NOT_OPEN`."
    PRD §3.9: "The first successful read moves the grant from `ISSUED` to `ACCESSED` and stamps `first_accessed_at`; subsequent reads keep the grant `ACCESSED` and leave the stamp untouched."
    PRD §2.9: "The window is half-open: it includes its opening instant and excludes the release instant itself."

    Design: Difficulty/boundary_precision_check/embargo_bulletin_at_exact_open_instant_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]
    cycle = setup_certified_cycle(
        "CES", "2026-09", panel["enrollments"],
        {en1["id"]: 9, en2["id"]: 11, en3["id"]: 8})

    staged = setup_embargoed_release(cycle["id"], "2026-10-01T13:30:00Z")
    release = staged["release"]
    assert_same_instant(release["embargo_open_at"], "2026-10-01T13:00:00Z"), (
        "embargo_open_at = release_at - 30 minutes")
    grant = staged["grants"][0]
    outlet = staged["outlets"][0]
    # The embargo was opened with the clock pinned at exactly embargo_open_at.

    bulletin = validate_success(api_client.get_bulletin(
        grant["id"], make_accredited_media_headers(outlet["id"])))
    assert bulletin["release_status"] == "EMBARGO_OPEN"
    assert bulletin["embargoed"] is True, "pre-publication embargoed read"

    grant_after = get_grant(grant["id"])
    assert grant_after["grant_status"] == "ACCESSED"
    assert_same_instant(grant_after["first_accessed_at"],
                        "2026-10-01T13:00:00Z"), (
        ">= boundary is inclusive; one second earlier would be "
        "ERR_EMBARGO_NOT_OPEN")
