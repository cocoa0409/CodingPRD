"""Term-advance cascade into enrollments and aid disbursement release."""
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    setup_certified_package, setup_in_session_disbursing, set_clock,
    assert_aid_package,
)

REGISTRAR = TEST_USERS["registrar_headers"]
FAO1 = TEST_USERS["fao1_headers"]


class TestTermAdvanceCascadesEnrollmentAndDisbursement:
    def test_term_in_session_flips_enrollment_active(self):
        """PRD §3.1: "When a term moves `ENROLLMENT_OPEN` → `IN_SESSION`,
        every enrollment of that term still in `REGISTERED` transitions to
        `ACTIVE`, and for each enrollment that became active, a financial aid
        package in `CERTIFIED` transitions to `DISBURSING` while every
        schedule entry whose `release_date` is on or before the current
        logical date flips from `SCHEDULED` to `DISBURSED`, adding its amount
        into the package's `disbursed_cents`."

        Design: Difficulty/transitive_cascade/term_advance_cascades_enrollment_active_and_disbursement_release
        """
        ctx = setup_certified_package(intensity="FULL_TIME", efc_cents=0)
        assert ctx["package"]["certified_award_cents"] == 739500
        set_clock("2026-10-19T00:00:00Z")
        resp = api_client.advance_term(ctx["term"]["id"], "IN_SESSION",
                                       REGISTRAR)
        term = validate_success(resp, expected_status=200)
        assert term["status"] == "IN_SESSION"
        enrollment = get_success_data(
            api_client.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
        assert enrollment["status"] == "ACTIVE", (
            f"the term advance must cascade REGISTERED -> ACTIVE; got "
            f"{enrollment['status']}")

    def test_term_in_session_releases_due_schedule_entry(self):
        """PRD §3.1: "When a term moves `ENROLLMENT_OPEN` → `IN_SESSION`,
        every enrollment of that term still in `REGISTERED` transitions to
        `ACTIVE`, and for each enrollment that became active, a financial aid
        package in `CERTIFIED` transitions to `DISBURSING` while every
        schedule entry whose `release_date` is on or before the current
        logical date flips from `SCHEDULED` to `DISBURSED`, adding its amount
        into the package's `disbursed_cents`."

        Design: Difficulty/transitive_cascade/term_advance_cascades_enrollment_active_and_disbursement_release
        """
        ctx = setup_certified_package(intensity="FULL_TIME", efc_cents=0)
        set_clock("2026-10-19T00:00:00Z")  # census; entry 2 due 2026-11-09
        validate_success(api_client.advance_term(
            ctx["term"]["id"], "IN_SESSION", REGISTRAR), expected_status=200)
        package = get_success_data(api_client.list_aid_packages(
            ctx["enrollment"]["id"], FAO1))[0]
        assert_aid_package(package)
        assert package["status"] == "DISBURSING", (
            f"the CERTIFIED package must follow its enrollment into "
            f"DISBURSING; got {package['status']}")
        assert package["disbursed_cents"] == 369750, (
            f"only entry 1 (release 2026-10-19) is due at census; got "
            f"{package['disbursed_cents']}")
        first, second = package["disbursement_schedule"]
        assert first["entry_status"] == "DISBURSED"
        assert second["entry_status"] == "SCHEDULED", (
            f"entry 2 releases 2026-11-09, after the clock; got "
            f"{second['entry_status']}")


def test_lazy_second_disbursement_release():
    """PRD §3.8: "Release itself is lazy: whenever the package is read or
    mutated, entries still `SCHEDULED` whose `release_date` is on or before
    the current logical date transition to `DISBURSED` while the term is
    `IN_SESSION`, each adding its amount into `disbursed_cents`."

    Design: Corner/calculations/lazy_second_disbursement_release
    """
    ctx = setup_in_session_disbursing(intensity="FULL_TIME", efc_cents=0)
    assert ctx["package"]["disbursed_cents"] == 369750
    # Move past the midpoint release date (2026-11-09); no mutation call.
    set_clock("2026-11-10T00:00:00Z")
    package = get_success_data(api_client.list_aid_packages(
        ctx["enrollment"]["id"], FAO1))[0]
    assert package["disbursed_cents"] == 739500, (
        f"reading the package must lazily release entry 2; got "
        f"{package['disbursed_cents']}")
    statuses = [e["entry_status"] for e in package["disbursement_schedule"]]
    assert statuses == ["DISBURSED", "DISBURSED"], (
        f"both entries must be DISBURSED after lazy release; got {statuses}")
    assert package["status"] == "DISBURSING"
