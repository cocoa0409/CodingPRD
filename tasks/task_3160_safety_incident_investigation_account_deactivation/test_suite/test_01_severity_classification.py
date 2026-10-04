"""Intake severity classification: the category base level, the aggravator codes
and the floor band that a second report earns."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_incident,
    get_incident,
    get_success_data,
    make_incident,
    make_prior_incidents,
    set_clock,
    setup_account,
    setup_policy,
)


def test_severity_from_category_plus_aggravator_codes(api):
    """PRD §2.7: "The derivation composes a category base level — 4 for `PHYSICAL_ASSAULT`
    and `SEXUAL_MISCONDUCT`, 2 for `HARASSMENT`, `SAFETY_VIOLATION`, `FRAUD_IDENTITY` and
    `DISCRIMINATION`, and 1 for `PROPERTY_DAMAGE` — with at most one escalation level from
    each distinct code in `aggravator_codes`, where `S3_INJURY` and
    `S3_LAW_ENFORCEMENT_SEVERITY` each add one level and each code is counted at most once."
    PRD §3.1: "`prior_incident_count_at_intake` counts the account's *other* `SafetyIncident`
    rows created strictly before this incident's `created_at`."

    Design: Difficulty/dual_variant_calc/dual_variant_severity_aggravator_vs_floor_band
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="bo.tran")

    # Two prior incidents establish a frozen prior count of exactly 2. The
    # frozen count reads rows created strictly before this incident's
    # created_at, so the clock is stepped between the filings.
    make_prior_incidents(account["id"], 2, incident_category="HARASSMENT",
                         reporter_type="RIDER")
    set_clock("2026-10-01T00:00:00Z")

    incident = make_incident(
        account["id"],
        incident_category="PROPERTY_DAMAGE",
        aggravator_codes=["S3_INJURY", "S3_LAW_ENFORCEMENT_SEVERITY"],
    )

    assert incident["severity"] == "S3", (
        "PROPERTY_DAMAGE (base 1) plus two aggravator levels must band to S3, "
        f"got {incident['severity']}"
    )
    assert incident["derivative_severity_flagged"] is False, (
        "the raw level is 3, so the saturated branch (raw level 4 with an applied "
        "aggravator) was never reached"
    )
    assert incident["prior_incident_count_at_intake"] == 2, (
        "exactly two other incidents were created strictly before this one"
    )
    assert incident["incident_status"] == "OPEN"
    assert incident["decision_category"] == "PENDING"
    assert_incident(incident)


def test_severity_floor_band_applies_once_aggravators_are_cleared(api):
    """PRD §2.7: "When the request supplies **no** aggravator codes at all, the band instead
    floors at `S2` whenever `prior_incident_count_at_intake` is at least 2 and the category
    base level is 1, so a second-report `PROPERTY_DAMAGE` incident lands on `S2` rather than
    the `S1` the base level alone would give."
    PRD §3.1: "Before any interim hold exists, a `SafetyInvestigator` may revise the intake
    codes by patching the incident's `aggravator_codes`, and the same derivation re-runs."

    Design: Difficulty/dual_variant_calc/dual_variant_severity_aggravator_vs_floor_band
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="bo.tran.floor")

    make_prior_incidents(account["id"], 2, incident_category="HARASSMENT",
                         reporter_type="RIDER")
    set_clock("2026-10-01T00:00:00Z")

    incident = make_incident(
        account["id"],
        incident_category="PROPERTY_DAMAGE",
        aggravator_codes=["S3_INJURY", "S3_LAW_ENFORCEMENT_SEVERITY"],
    )
    assert incident["severity"] == "S3"

    cleared = get_success_data(
        api_client.patch_incident_severity(
            incident["id"], [], TEST_USERS["investigator_headers"]
        )
    )

    assert cleared["severity"] == "S2", (
        "with no aggravators and a prior count of 2, PROPERTY_DAMAGE must floor at S2 "
        f"rather than the S1 the base level alone gives, got {cleared['severity']}"
    )
    assert cleared["derivative_severity_flagged"] is False
    assert get_incident(incident["id"])["severity"] == "S2"


def test_aggravator_saturation_sets_the_derivative_flag(api):
    """PRD §2.7: "The `derivative_severity_flagged` flag is set true exactly on the saturated
    branch: the raw level reached 4 and at least one aggravator level was applied, meaning at
    least one escalation was consumed by the clamp."

    Design: Corner/calculations/severity_saturating_aggravators_set_the_derivative_flag
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="owen.pike")

    set_clock("2026-09-01T00:00:00Z")
    exact = make_incident(
        account["id"],
        incident_category="SAFETY_VIOLATION",
        aggravator_codes=["S3_INJURY", "S3_LAW_ENFORCEMENT_SEVERITY"],
    )
    set_clock("2026-09-05T00:00:00Z")
    saturated = make_incident(
        account["id"],
        incident_category="SEXUAL_MISCONDUCT",
        aggravator_codes=["S3_INJURY"],
    )

    assert exact["severity"] == "S4", (
        "SAFETY_VIOLATION (base 2) plus two aggravator levels reaches exactly the "
        "band ceiling of 4"
    )
    assert exact["derivative_severity_flagged"] is True, (
        "the raw level reached 4 and an aggravator level was applied, which is the "
        "branch the flag marks"
    )
    assert saturated["severity"] == "S4"
    assert saturated["derivative_severity_flagged"] is True, (
        "SEXUAL_MISCONDUCT already sits at the ceiling, so the applied aggravator "
        "level was consumed by the clamp"
    )
    assert_incident(exact)
    assert_incident(saturated)


def test_supplied_severity_is_ignored_on_intake(api):
    """PRD §2.7: "A severity band is never supplied by a client. `severity` is always derived
    and any `severity` sent on intake is ignored."

    Design: Corner/entities/incident_severity_is_derived_and_supplied_input_is_ignored
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="dana.ille")

    low = make_incident(account["id"], incident_category="PROPERTY_DAMAGE",
                        reporter_type="RIDER", severity="S4")
    set_clock("2026-09-05T00:00:00Z")
    high = make_incident(account["id"], incident_category="PHYSICAL_ASSAULT",
                         reporter_type="RIDER", severity="S1")

    assert low["severity"] == "S1", (
        f"a PROPERTY_DAMAGE category derives S1 regardless of the supplied band, "
        f"got {low['severity']}"
    )
    assert low["derivative_severity_flagged"] is False
    assert high["severity"] == "S4", (
        f"a PHYSICAL_ASSAULT category derives S4 regardless of the supplied band, "
        f"got {high['severity']}"
    )
    assert high["derivative_severity_flagged"] is False
    assert high["prior_incident_count_at_intake"] == 1, (
        "only the incident created strictly before this one is counted"
    )
    assert low["incident_status"] == "OPEN" and high["incident_status"] == "OPEN"
    assert low["decision_category"] == "PENDING" and high["decision_category"] == "PENDING"