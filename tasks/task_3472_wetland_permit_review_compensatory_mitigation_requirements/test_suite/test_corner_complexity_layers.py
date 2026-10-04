"""Corner queue — complexity layers (PRD §2.4, §2.5, §2.7, §3.7).

Optimistic concurrency on application and plan edits, the pinned clock
default and monotonicity rule, and the withdraw cascade releasing reserved
credits.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_DEFAULT,
    assert_bank_inventory_conserved,
    assert_iso_instants_equal,
    create_application,
    create_plan,
    iso_add_days,
    make_applicant_headers,
    patch_application,
    patch_application_payload,
    patch_mitigation_plan_payload,
    patch_plan,
    reserve_credits,
    review_plan,
    set_clock,
    setup_aa_accepted,
    setup_application_decision_pending,
    setup_applicant_and_site,
    setup_site_with_issued_jd,
    create_jd,
    issue_jd,
    setup_operational_bank,
    submit_plan,
    validate_error,
    validate_success,
    withdraw_application,
)


def test_corner_occ_application_patch_stale_version(api):
    """PRD §2.7: "Editing a permit application requires the request to carry
    `expected_application_version`, holding the application `version` the
    client last observed; if that value no longer equals the application's
    current `version` — because a prior edit has already advanced it since
    the client's last read, so the client's edits are based on a stale record
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "The same holds for application edits, which are permitted
    while the application is in `DRAFT` or `RETURNED_TO_APPLICANT` and do not
    change status."
    PRD §2.4: "The `version` starts as a small integer at creation and is
    incremented by exactly 1 on every mutation of the resource".

    A PATCH with the version observed at creation succeeds and advances the
    version by exactly 1; replaying the same stale version is rejected even
    though DRAFT is still a patchable state; supplying the current version
    succeeds again.

    Design: Corner/complexity_layers/corner_occ_application_patch_stale_version
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(site, jd, applicant)
    observed = app["version"]

    app_v2 = patch_application(
        app, applicant, observed, project_purpose="Stormwater facility, phase 1"
    )
    assert app_v2["version"] == observed + 1, "fresh version accepted, +1"
    assert app_v2["status"] == "DRAFT", "PATCH does not move the state machine"

    resp = api.patch_application(
        app["id"],
        patch_application_payload(
            observed, project_purpose="Stormwater facility, revised again"
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    app_v3 = patch_application(
        app_v2, applicant, app_v2["version"],
        project_purpose="Stormwater facility, revised again",
    )
    assert app_v3["version"] == app_v2["version"] + 1


def test_corner_occ_plan_patch_stale_version(api):
    """PRD §2.7: "Editing a mitigation plan likewise requires
    `expected_plan_version` equal to the plan's current `version`, with the
    same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. This second
    guard matters even though a successful edit on a draft plan leaves the
    plan in `DRAFT`: no state precondition catches a second edit carrying an
    earlier observed version, so only the version check rejects it."

    The DRAFT plan's first PATCH succeeds and stays DRAFT; the replayed
    creation-time version is rejected by the version check alone.

    Design: Corner/complexity_layers/corner_occ_plan_patch_stale_version
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(
        ctx["app"], applicant, mechanism="PERMITTEE_RESPONSIBLE",
        financial_assurance_dollars=60000.0,
        stewardship_entity_name="Piney Branch Stewardship LLC",
        long_term_stewardship_secured=False,
    )
    observed = plan["version"]

    plan_v2 = patch_plan(
        plan, applicant, observed, long_term_stewardship_secured=True
    )
    assert plan_v2["version"] == observed + 1
    assert plan_v2["status"] == "DRAFT", "PATCH in DRAFT does not move the state machine"

    resp = api.patch_mitigation_plan(
        plan["id"],
        patch_mitigation_plan_payload(observed, financial_assurance_dollars=65000.0),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_corner_clock_default_is_fixed(api, district_engineer_headers):
    """PRD §2.5: "Before any operator sets it, the logical clock's startup
    default is exactly `2026-09-01T00:00:00Z`, and it never falls back to
    wall-clock time thereafter."
    PRD §3.1: "On issuance the determination moves `DRAFT` to `ISSUED`,
    `issued_date` is set to the current logical clock, and `expiration_date`
    is fixed at the issuance instant plus 1825 days — five years of
    validity."

    No clock call is ever made: the determination issued first thing stamps
    2026-09-01T00:00:00Z, and its expiration lands 1825 days later at
    2031-08-31T00:00:00Z.

    Design: Corner/complexity_layers/corner_clock_default_is_fixed
    """
    applicant, site = setup_applicant_and_site(
        resource_types_present=["FORESTED_WETLAND"]
    )
    jd = create_jd(site)
    jd = issue_jd(jd)
    assert_iso_instants_equal(
        jd["issued_date"], CLOCK_STARTUP_DEFAULT,
        label="issued_date equals the pinned startup clock",
    )
    assert_iso_instants_equal(
        jd["expiration_date"], "2031-08-31T00:00:00Z",
        label="expiration_date = issued_date + 1825 days",
    )


def test_corner_clock_regression_rejected(api, system_admin_headers):
    """PRD §2.5: "The new instant must be strictly greater than the current
    logical clock value — a request to move the clock backward, or to the
    identical instant, is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422)."

    After advancing to 2026-10-01, both 2026-09-15 (backward) and 2026-10-01
    (identical) are rejected.

    Design: Corner/complexity_layers/corner_clock_regression_rejected
    """
    set_clock("2026-10-01T00:00:00Z")

    resp = api.set_clock("2026-09-15T00:00:00Z", system_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)

    resp = api.set_clock("2026-10-01T00:00:00Z", system_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)


def test_corner_withdraw_releases_reserved(api, reviewer_headers):
    """PRD §3.3: "Withdrawal runs the same credit compensation cascade and
    plan cancellation as a denial, specified in §3.7".
    PRD §3.7: "Every credit transaction of the application's plans still in
    `RESERVED` transitions to `RELEASED`, and every one in `PURCHASED`
    transitions to `REFUNDED`, restoring the banks' inventory and revenue;
    and every mitigation plan of the application not yet terminal — anything
    in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, or
    `CREDITS_SECURED` — transitions to `CANCELLED`."

    A 7.0-credit reservation (never purchased) flips to RELEASED on withdraw,
    the bank's availability returns to capacity 20, and the APPROVED plan is
    CANCELLED.

    Design: Corner/complexity_layers/corner_withdraw_releases_reserved
    """
    ctx = setup_application_decision_pending()
    app, applicant = ctx["app"], ctx["applicant"]
    plan = create_plan(app, applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()
    txn = reserve_credits(bank, plan, applicant, credits=7.0)
    assert txn["status"] == "RESERVED"

    app = withdraw_application(app, applicant)
    assert app["status"] == "WITHDRAWN"

    txn_after = validate_success(api.get_credit_transaction(txn["id"], reviewer_headers))
    assert txn_after["status"] == "RELEASED"

    bank_after = validate_success(api.get_mitigation_bank(bank["id"], reviewer_headers))
    assert bank_after["available_credits_by_type"]["FORESTED_WETLAND"] == pytest.approx(
        20.0, abs=1e-6
    ), "the reservation is fully released"
    assert_bank_inventory_conserved(bank_after)

    plan_after = validate_success(api.get_mitigation_plan(plan["id"], reviewer_headers))
    assert plan_after["status"] == "CANCELLED"
