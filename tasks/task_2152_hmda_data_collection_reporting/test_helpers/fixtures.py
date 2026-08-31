"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test starts against an empty database. Setup calls use
the lenient validator so a broken precondition reports as a setup failure rather
than as a confusing assertion failure inside the test body.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ANALYST_NOVA,
    EXAMINER_RHO,
    OFFICER_ALPHA,
    TEST_DEFAULTS,
    TRACT_A,
    TRACT_B,
    TRACT_TX,
)
from .factories import (
    action_taken_payload,
    certify_payload,
    close_sample_payload,
    create_application_payload,
    create_audit_finding_payload,
    create_audit_sample_payload,
    create_census_tract_payload,
    create_demographic_entry_payload,
    create_edit_run_payload,
    create_fair_lending_payload,
    create_geocode_assignment_payload,
    create_institution_payload,
    create_submission_payload,
    manual_override_payload,
    reopen_payload,
    resubmit_payload,
    review_payload,
    verify_exception_payload,
)
from .test_users import (
    make_compliance_analyst_headers,
    make_compliance_officer_headers,
    make_examiner_headers,
    make_institution_admin_headers,
    make_loan_officer_headers,
    make_system_admin_headers,
    TEST_USERS,
)

# ─── Tier 0: single-call primitives ───────────────────────────────────────────


def set_clock(to_iso8601: str) -> None:
    """Move the server's logical clock. Before any such call it reads
    2026-08-01T00:00:00Z."""
    get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_system_admin_headers())
    )


def create_institution(**overrides) -> dict:
    return get_success_data(
        api_client.create_institution(
            create_institution_payload(**overrides), make_system_admin_headers()
        )
    )


def create_second_institution(**overrides) -> dict:
    defaults = {
        "lei": TEST_DEFAULTS["SECONDARY_LEI"],
        "name": TEST_DEFAULTS["SECONDARY_NAME"],
        "asset_size_usd_cents": 180000000000,
        "prior_year_closed_end_originations": 610,
        "prior_year_open_end_originations": 20,
    }
    defaults.update(overrides)
    return create_institution(**defaults)


def read_institution(institution_id: str) -> dict:
    return get_success_data(
        api_client.get_institution(institution_id, TEST_USERS["examiner_headers"])
    )


def patch_institution(institution_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.patch_institution(
            institution_id, payload, make_institution_admin_headers(institution_id)
        )
    )


def create_census_tract(**overrides) -> dict:
    return get_success_data(
        api_client.create_census_tract(
            create_census_tract_payload(**overrides), make_system_admin_headers()
        )
    )


def create_tract_a() -> dict:
    return create_census_tract(**TRACT_A)


def create_tract_b() -> dict:
    return create_census_tract(**TRACT_B)


def create_tract_tx() -> dict:
    return create_census_tract(**TRACT_TX)


def create_application(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_application(
            create_application_payload(institution_id, **overrides),
            make_loan_officer_headers(),
        )
    )


def read_application(application_id: str) -> dict:
    return get_success_data(
        api_client.get_application(application_id, TEST_USERS["examiner_headers"])
    )


def patch_application(application_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.patch_application(application_id, payload, make_loan_officer_headers())
    )


def record_demographics(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_demographic_entry(
            create_demographic_entry_payload(application_id, **overrides),
            make_loan_officer_headers(),
        )
    )


def geocode_application(application_id: str,
                        expected_application_version: Optional[int] = None,
                        **overrides) -> dict:
    """Create a geocode assignment, reading the record's current version when the
    caller does not supply one."""
    if expected_application_version is None:
        expected_application_version = read_application(application_id)["version"]
    return get_success_data(
        api_client.create_geocode_assignment(
            create_geocode_assignment_payload(
                application_id, expected_application_version, **overrides
            ),
            make_loan_officer_headers(),
        )
    )


def override_geocode(assignment_id: str, census_tract_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.manual_override_geocode(
            assignment_id,
            manual_override_payload(census_tract_id, **overrides),
            make_compliance_analyst_headers(),
        )
    )


def advance_application(application_id: str, to_stage: str) -> dict:
    return get_success_data(
        api_client.advance_application(
            application_id, {"to_stage": to_stage}, make_loan_officer_headers()
        )
    )


def record_action(application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_action_taken(
            application_id, action_taken_payload(**overrides), make_loan_officer_headers()
        )
    )


def reopen_application(application_id: str, analyst_id: str = ANALYST_NOVA,
                       **overrides) -> dict:
    return get_success_data(
        api_client.reopen_application(
            application_id,
            reopen_payload(**overrides),
            make_compliance_analyst_headers(analyst_id),
        )
    )


def create_edit_run(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_edit_run(
            create_edit_run_payload(institution_id, **overrides),
            make_compliance_analyst_headers(),
        )
    )


def read_edit_run(run_id: str) -> dict:
    return get_success_data(
        api_client.get_edit_run(run_id, TEST_USERS["examiner_headers"])
    )


def list_run_exceptions(run_id: str, params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_edit_run_exceptions(
            run_id, TEST_USERS["examiner_headers"], params=params
        )
    )


def verify_exception(exception_id: str, analyst_id: str = ANALYST_NOVA,
                     **overrides) -> dict:
    return get_success_data(
        api_client.verify_edit_exception(
            exception_id,
            verify_exception_payload(**overrides),
            make_compliance_analyst_headers(analyst_id),
        )
    )


def open_submission(institution_id: str, officer_id: str = OFFICER_ALPHA) -> dict:
    """Read the institution's current version, then open a filing submission
    against it."""
    current = read_institution(institution_id)
    return get_success_data(
        api_client.create_submission(
            create_submission_payload(institution_id, current["version"]),
            make_compliance_officer_headers(officer_id),
        )
    )


def read_submission(submission_id: str) -> dict:
    return get_success_data(
        api_client.get_submission(submission_id, TEST_USERS["examiner_headers"])
    )


def attach_run(submission_id: str, run_id: str, officer_id: str = OFFICER_ALPHA) -> dict:
    return get_success_data(
        api_client.attach_edit_run(
            submission_id, {"edit_run_id": run_id},
            make_compliance_officer_headers(officer_id),
        )
    )


def certify_submission(submission_id: str, officer_id: str = OFFICER_ALPHA,
                       **overrides) -> dict:
    return get_success_data(
        api_client.certify_submission(
            submission_id, certify_payload(**overrides),
            make_compliance_officer_headers(officer_id),
        )
    )


def file_submission(submission_id: str, officer_id: str = OFFICER_ALPHA) -> dict:
    return get_success_data(
        api_client.file_submission(
            submission_id, make_compliance_officer_headers(officer_id)
        )
    )


def review_submission(submission_id: str, decision: str = "ACCEPT",
                      examiner_id: str = EXAMINER_RHO, **overrides) -> dict:
    return get_success_data(
        api_client.review_submission(
            submission_id, review_payload(decision, **overrides),
            make_examiner_headers(examiner_id),
        )
    )


def resubmit_submission(submission_id: str, officer_id: str = OFFICER_ALPHA,
                        **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_submission(
            submission_id, resubmit_payload(**overrides),
            make_compliance_officer_headers(officer_id),
        )
    )


def list_disclosure_statements(submission_id: str,
                               params: Optional[dict] = None) -> List[dict]:
    return get_success_data(
        api_client.list_submission_disclosure_statements(
            submission_id, TEST_USERS["examiner_headers"], params=params
        )
    )


def create_audit_sample(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_sample(
            create_audit_sample_payload(institution_id, **overrides),
            make_compliance_analyst_headers(),
        )
    )


def read_audit_sample(sample_id: str) -> dict:
    return get_success_data(
        api_client.get_audit_sample(sample_id, TEST_USERS["examiner_headers"])
    )


def create_audit_finding(sample_id: str, application_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_finding(
            create_audit_finding_payload(sample_id, application_id, **overrides),
            make_compliance_analyst_headers(),
        )
    )


def close_audit_sample(sample_id: str, defect_rate_basis: str = "FIELD_WEIGHTED") -> dict:
    return get_success_data(
        api_client.close_audit_sample(
            sample_id, close_sample_payload(defect_rate_basis),
            make_compliance_analyst_headers(),
        )
    )


def create_fair_lending_analysis(institution_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fair_lending_analysis(
            create_fair_lending_payload(institution_id, **overrides),
            make_compliance_analyst_headers(),
        )
    )


# ─── Tier 1: institution + reference data ─────────────────────────────────────


def setup_institution_and_tract(**inst_overrides):
    """A non partially exempt reporting bank plus one census tract in
    county 06075 / CA, so a geocode naming that tract resolves to exactly one
    candidate. Returns (institution, tract)."""
    institution = create_institution(**inst_overrides)
    tract = create_tract_a()
    return institution, tract


def setup_institution_with_two_tracts(**inst_overrides):
    """Two census tracts in the same county, so a county-only geocode is
    ambiguous. Returns (institution, tract_a, tract_b)."""
    institution = create_institution(**inst_overrides)
    tract_a = create_tract_a()
    tract_b = create_tract_b()
    return institution, tract_a, tract_b


# ─── Tier 2: register records walked along the capture workflow ───────────────


def setup_decisioned_application(institution_id: str, *,
                                 geocode: bool = False,
                                 submitted_tract_code: Optional[str] = None,
                                 demographic_overrides: Optional[dict] = None,
                                 geocode_overrides: Optional[dict] = None,
                                 **app_overrides) -> dict:
    """Open a register record, optionally geocode it, record an APPLICANT
    demographic row and walk INTAKE -> UNDERWRITING -> DECISIONED."""
    application = create_application(institution_id, **app_overrides)
    if geocode:
        overrides = dict(geocode_overrides or {})
        if submitted_tract_code is not None:
            overrides.setdefault("submitted_tract_code", submitted_tract_code)
        geocode_application(application["id"], application["version"], **overrides)
    record_demographics(application["id"], **(demographic_overrides or {}))
    advance_application(application["id"], "UNDERWRITING")
    advance_application(application["id"], "DECISIONED")
    return read_application(application["id"])


def setup_originated_application(institution_id: str, *,
                                 action_overrides: Optional[dict] = None,
                                 **kwargs) -> dict:
    """A DECISIONED record whose action taken has been recorded."""
    application = setup_decisioned_application(institution_id, **kwargs)
    record_action(application["id"], **(action_overrides or {}))
    return read_application(application["id"])


def setup_locked_application(institution_id: str, **kwargs) -> dict:
    """A record carried all the way to REGISTER_LOCKED. Requires a resolved
    geocode assignment, so geocode defaults to true here."""
    kwargs.setdefault("geocode", True)
    kwargs.setdefault("submitted_tract_code", TRACT_A["tract_code"])
    application = setup_originated_application(institution_id, **kwargs)
    advance_application(application["id"], "REGISTER_LOCKED")
    return read_application(application["id"])


# ─── Tier 3: the edit battery ─────────────────────────────────────────────────

# A decision lag of 196 days between application_date and action_taken_date
# exceeds the 180-day quality threshold, so exactly one Q615 quality exception
# is raised on an otherwise clean record.
LAGGED_APPLICATION_DATE = "2026-01-05T00:00:00Z"
LAGGED_ACTION_DATE = "2026-07-20T00:00:00Z"


def setup_register_with_quality_exception(**inst_overrides) -> dict:
    """One locked record carrying a 196-day decision lag, walked through an edit
    run that raises exactly one quality exception.

    Returns {institution, tract, application, run, exception}.
    """
    institution, tract = setup_institution_and_tract(**inst_overrides)
    application = setup_locked_application(
        institution["id"],
        application_date=LAGGED_APPLICATION_DATE,
        action_overrides={"action_taken_date": LAGGED_ACTION_DATE},
    )
    run = create_edit_run(institution["id"])
    exceptions = list_run_exceptions(run["id"])
    return {
        "institution": read_institution(institution["id"]),
        "tract": tract,
        "application": read_application(application["id"]),
        "run": read_edit_run(run["id"]),
        "exception": exceptions[0] if exceptions else None,
        "exceptions": exceptions,
    }


def setup_verified_quality_exception(analyst_id: str = ANALYST_NOVA,
                                     **inst_overrides) -> dict:
    """The quality-exception register with that exception verified, so the record
    is CLEARED and the run is CLEARED_ALL."""
    scenario = setup_register_with_quality_exception(**inst_overrides)
    verify_exception(scenario["exception"]["id"], analyst_id)
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    scenario["application"] = read_application(scenario["application"]["id"])
    scenario["run"] = read_edit_run(scenario["run"]["id"])
    scenario["exception"] = get_success_data(
        api_client.list_edit_run_exceptions(
            scenario["run"]["id"], TEST_USERS["examiner_headers"]
        )
    )[0]
    return scenario


def setup_register_with_validity_exception(**inst_overrides) -> dict:
    """One DECISIONED record with an action taken but no geocode attempt at all,
    so the run raises exactly one validity exception and lands COMPLETED.

    Returns {institution, application, run, exception}.
    """
    institution = create_institution(**inst_overrides)
    application = setup_originated_application(institution["id"], geocode=False)
    run = create_edit_run(institution["id"])
    exceptions = list_run_exceptions(run["id"])
    return {
        "institution": read_institution(institution["id"]),
        "application": read_application(application["id"]),
        "run": read_edit_run(run["id"]),
        "exception": exceptions[0] if exceptions else None,
        "exceptions": exceptions,
    }


def setup_register_with_macro_exception(**inst_overrides) -> dict:
    """One withdrawn record with a resolved geocode, so the whole snapshot is
    withdrawn and only the macro edit fires.

    Returns {institution, tract, application, run, exception}.
    """
    institution, tract = setup_institution_and_tract(**inst_overrides)
    application = setup_originated_application(
        institution["id"],
        geocode=True,
        submitted_tract_code=TRACT_A["tract_code"],
        action_overrides={
            "action_taken": "WITHDRAWN",
            "action_taken_date": "2026-03-15T00:00:00Z",
            "rate_spread": None,
            "purchaser_type": None,
        },
    )
    run = create_edit_run(institution["id"])
    exceptions = list_run_exceptions(run["id"])
    return {
        "institution": read_institution(institution["id"]),
        "tract": tract,
        "application": read_application(application["id"]),
        "run": read_edit_run(run["id"]),
        "exception": exceptions[0] if exceptions else None,
        "exceptions": exceptions,
    }


def setup_exception_free_run(**inst_overrides):
    """An institution holding no register records at all, plus one edit run over
    that empty snapshot, which therefore raises nothing and lands CLEARED_ALL.
    Returns (institution, run)."""
    institution = create_institution(**inst_overrides)
    run = create_edit_run(institution["id"])
    return read_institution(institution["id"]), read_edit_run(run["id"])


# ─── Tier 4: the annual filing chain ──────────────────────────────────────────


def setup_draft_submission_on_empty_register(officer_id: str = OFFICER_ALPHA):
    """Institution with no register records, one exception-free run and one DRAFT
    submission. Returns (institution, run, submission)."""
    institution, run = setup_exception_free_run()
    submission = open_submission(institution["id"], officer_id)
    return institution, run, submission


def setup_attached_submission_on_empty_register(officer_id: str = OFFICER_ALPHA):
    """As above, with the run attached so the submission is EDITS_ATTACHED.
    Returns (institution, run, submission)."""
    institution, run, submission = setup_draft_submission_on_empty_register(officer_id)
    attach_run(submission["id"], run["id"], officer_id)
    return institution, run, read_submission(submission["id"])


def setup_certified_submission_on_empty_register(officer_id: str = OFFICER_ALPHA,
                                                 attestation_text: Optional[str] = None):
    """An empty register certified for filing, so the institution sits at
    LOCKED_FOR_FILING. Returns (institution, run, submission)."""
    institution, run, submission = setup_attached_submission_on_empty_register(officer_id)
    kwargs = {"attestation_text": attestation_text} if attestation_text else {}
    certify_submission(submission["id"], officer_id, **kwargs)
    return (
        read_institution(institution["id"]),
        read_edit_run(run["id"]),
        read_submission(submission["id"]),
    )


def setup_filed_submission_on_empty_register(officer_id: str = OFFICER_ALPHA,
                                             filed_at: str = "2027-02-01T00:00:00Z"):
    """An empty register filed with the regulator at the given clock instant.
    Returns (institution, run, submission)."""
    institution, run, submission = setup_certified_submission_on_empty_register(officer_id)
    set_clock(filed_at)
    file_submission(submission["id"], officer_id)
    return (
        read_institution(institution["id"]),
        read_edit_run(run["id"]),
        read_submission(submission["id"]),
    )


def setup_certified_submission_over_locked_record(officer_id: str = OFFICER_ALPHA) -> dict:
    """One locked, clean register record cleared by an exception-free run, with a
    submission attached and certified so the institution reads LOCKED_FOR_FILING.

    Returns {institution, tract, application, run, submission}.
    """
    institution, tract = setup_institution_and_tract()
    application = setup_locked_application(institution["id"])
    run = create_edit_run(institution["id"])
    submission = open_submission(institution["id"], officer_id)
    attach_run(submission["id"], run["id"], officer_id)
    certify_submission(submission["id"], officer_id)
    return {
        "institution": read_institution(institution["id"]),
        "tract": tract,
        "application": read_application(application["id"]),
        "run": read_edit_run(run["id"]),
        "submission": read_submission(submission["id"]),
    }


def setup_filed_submission_over_locked_record(officer_id: str = OFFICER_ALPHA,
                                              filed_at: str = "2027-02-01T00:00:00Z") -> dict:
    """The locked-record filing chain carried through to FILED, which archives the
    record and publishes the two disclosure statements.

    Returns {institution, tract, application, run, submission}.
    """
    scenario = setup_certified_submission_over_locked_record(officer_id)
    set_clock(filed_at)
    file_submission(scenario["submission"]["id"], officer_id)
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    scenario["application"] = read_application(scenario["application"]["id"])
    scenario["submission"] = read_submission(scenario["submission"]["id"])
    return scenario


def setup_certified_submission_over_verified_exception(
    analyst_id: str = ANALYST_NOVA, officer_id: str = OFFICER_ALPHA
) -> dict:
    """The quality-exception register, verified by `analyst_id`, with a submission
    attached and certified by `officer_id`.

    Returns {institution, tract, application, run, exception, submission}.
    """
    scenario = setup_verified_quality_exception(analyst_id)
    submission = open_submission(scenario["institution"]["id"], officer_id)
    attach_run(submission["id"], scenario["run"]["id"], officer_id)
    certify_submission(submission["id"], officer_id)
    scenario["institution"] = read_institution(scenario["institution"]["id"])
    scenario["run"] = read_edit_run(scenario["run"]["id"])
    scenario["submission"] = read_submission(submission["id"])
    return scenario


# ─── Tier 5: the audit scrub ──────────────────────────────────────────────────


def setup_two_originated_records(institution_id: str):
    """Two clean register records whose actions were taken on 2026-03-15 and
    2026-04-20, i.e. inside a 2026-01-01..2026-06-30 sampling period.
    Returns (application_a, application_b)."""
    application_a = setup_originated_application(
        institution_id,
        application_date="2026-02-10T00:00:00Z",
        loan_amount_cents=35000000,
        income_thousands=120,
        action_overrides={"action_taken_date": "2026-03-15T00:00:00Z",
                          "rate_spread": 1.75},
    )
    application_b = setup_originated_application(
        institution_id,
        application_date="2026-02-12T00:00:00Z",
        loan_purpose="REFINANCING",
        loan_amount_cents=41000000,
        income_thousands=150,
        demographic_overrides={"race_codes": ["ASIAN"], "sex_code": "FEMALE"},
        action_overrides={"action_taken_date": "2026-04-20T00:00:00Z",
                          "rate_spread": 2.10},
    )
    return application_a, application_b


def setup_sample_over_two_records(fields_reviewed_per_record: int = 4) -> dict:
    """One institution, two sampled records and one DRAFT audit sample drawn over
    2026-01-01..2026-06-30.

    Returns {institution, application_a, application_b, sample}.
    """
    institution = create_institution()
    application_a, application_b = setup_two_originated_records(institution["id"])
    sample = create_audit_sample(
        institution["id"], fields_reviewed_per_record=fields_reviewed_per_record
    )
    return {
        "institution": read_institution(institution["id"]),
        "application_a": application_a,
        "application_b": application_b,
        "sample": sample,
    }


def add_three_defect_findings(sample_id: str, application_a_id: str,
                              application_b_id: str) -> List[dict]:
    """Two defective fields on record A and one on record B, each occupying a
    distinct closed remediation window."""
    findings = [
        create_audit_finding(
            sample_id, application_a_id,
            field_name="income_thousands", recorded_value="120",
            source_document_value="112", severity="MATERIAL",
            remediation_start="2026-09-01T00:00:00Z",
            remediation_end="2026-09-05T00:00:00Z",
        ),
        create_audit_finding(
            sample_id, application_a_id,
            field_name="rate_spread", recorded_value="1.75",
            source_document_value="1.85", severity="NON_MATERIAL",
            remediation_start="2026-09-06T00:00:00Z",
            remediation_end="2026-09-10T00:00:00Z",
        ),
        create_audit_finding(
            sample_id, application_b_id,
            field_name="loan_amount_cents", recorded_value="41000000",
            source_document_value="40900000", severity="MATERIAL",
            remediation_start="2026-09-01T00:00:00Z",
            remediation_end="2026-09-05T00:00:00Z",
        ),
    ]
    return findings


# ─── Tier 6: fair lending populations ─────────────────────────────────────────


def setup_analysed_application(institution_id: str, race_code: str, action_taken: str,
                               action_taken_date: str, **app_overrides) -> dict:
    """A DECISIONED record carrying an APPLICANT demographic row with the given
    race code and the given action taken."""
    if action_taken in ("DENIED", "PREAPPROVAL_DENIED"):
        action_overrides = {
            "action_taken": action_taken,
            "action_taken_date": action_taken_date,
            "denial_reason_codes": ["CREDIT_HISTORY"],
            "rate_spread": None,
            "purchaser_type": None,
        }
    else:
        action_overrides = {
            "action_taken": action_taken,
            "action_taken_date": action_taken_date,
        }
    defaults = {
        "application_date": "2026-02-01T00:00:00Z",
        "loan_amount_cents": 30000000,
        "income_thousands": 110,
    }
    defaults.update(app_overrides)
    return setup_originated_application(
        institution_id,
        demographic_overrides={"race_codes": [race_code]},
        action_overrides=action_overrides,
        **defaults,
    )


# ─── Tier 7: a superseded original alongside its correction ───────────────────


def setup_superseded_pair_with_attached_submission(officer_id: str = OFFICER_ALPHA) -> dict:
    """A register holding one original record and the correction that supersedes
    it, both locked and cleared by their own edit run, with a submission attached
    to the newer run and ready to certify.

    Returns {institution, tract, original, correction, run_one, run_two,
    submission}.
    """
    institution, tract = setup_institution_and_tract()

    original = setup_locked_application(
        institution["id"],
        action_overrides={"action_taken_date": "2026-03-15T00:00:00Z"},
    )
    run_one = create_edit_run(
        institution["id"], window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )

    correction = setup_locked_application(
        institution["id"],
        supersedes_application_id=original["id"],
        action_overrides={"action_taken_date": "2026-04-20T00:00:00Z"},
    )
    run_two = create_edit_run(
        institution["id"], window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )

    submission = open_submission(institution["id"], officer_id)
    attach_run(submission["id"], run_two["id"], officer_id)

    return {
        "institution": read_institution(institution["id"]),
        "tract": tract,
        "original": read_application(original["id"]),
        "correction": read_application(correction["id"]),
        "run_one": read_edit_run(run_one["id"]),
        "run_two": read_edit_run(run_two["id"]),
        "submission": read_submission(submission["id"]),
    }


def setup_invalidated_run_with_draft_submission(officer_id: str = OFFICER_ALPHA) -> dict:
    """An empty register whose first edit run has been superseded by a second,
    adjacent run, leaving the first INVALIDATED, plus a DRAFT submission.

    Returns {institution, run_one, run_two, submission}.
    """
    institution = create_institution()
    run_one = create_edit_run(
        institution["id"], window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-02T00:00:00Z",
    )
    run_two = create_edit_run(
        institution["id"], window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    submission = open_submission(institution["id"], officer_id)
    return {
        "institution": read_institution(institution["id"]),
        "run_one": read_edit_run(run_one["id"]),
        "run_two": read_edit_run(run_two["id"]),
        "submission": read_submission(submission["id"]),
    }


def setup_two_banks_with_runs_and_one_attached_submission(
    officer_id: str = OFFICER_ALPHA,
) -> dict:
    """Two banks, each with one exception-free run over an empty register, and one
    submission on the first bank already moved to EDITS_ATTACHED by its own run.

    Returns {institution_one, institution_two, run_one, run_two, submission}.
    """
    institution_one = create_institution()
    institution_two = create_second_institution()
    run_one = create_edit_run(institution_one["id"])
    run_two = create_edit_run(institution_two["id"])
    submission = open_submission(institution_one["id"], officer_id)
    attach_run(submission["id"], run_one["id"], officer_id)
    return {
        "institution_one": read_institution(institution_one["id"]),
        "institution_two": read_institution(institution_two["id"]),
        "run_one": read_edit_run(run_one["id"]),
        "run_two": read_edit_run(run_two["id"]),
        "submission": read_submission(submission["id"]),
    }
