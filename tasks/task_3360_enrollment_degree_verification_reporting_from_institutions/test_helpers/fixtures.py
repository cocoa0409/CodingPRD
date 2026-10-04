"""Composite setup helpers for the clearinghouse test suite.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before each test, so every test
starts against an empty database). Setup calls use get_success_data() so
failures surface as clear setup errors.

Recurring preambles:
  setup_period_scenario   institution + agreement + reporting period (+clock)
  setup_uploaded_file     ... + one uploaded enrollment file
  setup_certified_file    ... + certification by the institution's certifier
  setup_vetted_requester  requester account vetted to VETTED
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_institution_payload, create_agreement_payload, create_period_payload,
    enrollment_row, create_enrollment_file_payload, create_correction_payload,
    create_degree_payload, create_requester_payload,
    create_verification_request_payload, create_directive_payload,
    create_dataset_payload,
)
from .test_users import (
    TEST_USERS, make_submitter_headers, make_certifier_headers,
    make_requester_headers, make_learner_headers, make_servicer_headers,
    make_analyst_headers,
)

OPS = TEST_USERS["ops_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-endpoint helpers
# ---------------------------------------------------------------------------

def create_institution(payload=None) -> dict:
    """Create an institution with its registrar users inline."""
    resp = api_client.create_institution(payload or create_institution_payload(), OPS)
    return get_success_data(resp)


def create_institution_with_registrars(name="State University", ope_id="00123400") -> dict:
    """Institution with one SUBMITTER and one CERTIFIER user.

    Returns {"inst": ..., "inst_id": ..., "sub_uid": ..., "cert_uid": ...}.
    """
    inst = create_institution(create_institution_payload(name=name, ope_id=ope_id))
    return {
        "inst": inst,
        "inst_id": inst["id"],
        "sub_uid": inst["users"][0]["id"],
        "cert_uid": inst["users"][1]["id"],
    }


def add_agreement(inst_id, effective_from="2026-01-01", effective_to="2027-06-30") -> dict:
    resp = api_client.create_agreement(
        inst_id,
        create_agreement_payload(effective_from=effective_from, effective_to=effective_to),
        OPS,
    )
    return get_success_data(resp)


def add_period(inst_id, **overrides) -> dict:
    resp = api_client.create_reporting_period(inst_id, create_period_payload(**overrides), OPS)
    return get_success_data(resp)


def advance_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, OPS)
    return get_success_data(resp)


def get_period_version(inst_id, index=0) -> int:
    resp = api_client.list_reporting_periods(inst_id, OPS)
    data, _meta = validate_paginated(resp)
    return data[index]["version"]


def get_student_version(student_id) -> int:
    resp = api_client.get_student(student_id, OPS)
    return get_success_data(resp)["version"]


def list_file_entries(file_id) -> list:
    # PRD §2.3 default limit is 10; fixture files carry up to 12 rows, so the
    # helper pages wide (limit 100 is the PRD maximum) to return every row.
    resp = api_client.list_enrollment_entries(
        OPS, params={"file_id": file_id, "limit": 100},
    )
    data, _meta = validate_paginated(resp)
    return data


def list_student_notifications(student_id) -> list:
    resp = api_client.list_servicer_notifications(OPS, params={"student_id": student_id})
    data, _meta = validate_paginated(resp)
    return data


def list_entry_notifications(entry_id) -> list:
    resp = api_client.list_servicer_notifications(OPS, params={"enrollment_entry_id": entry_id})
    data, _meta = validate_paginated(resp)
    return data


def get_requester_balance(requester_id) -> int:
    resp = api_client.get_requester(requester_id, OPS)
    return get_success_data(resp)["credit_balance_cents"]


# ---------------------------------------------------------------------------
# Tier 1: institution + agreement + period scenario
# ---------------------------------------------------------------------------

def setup_period_scenario(advance_to="2026-11-15T00:00:00Z", with_agreement=True,
                          **period_overrides) -> dict:
    """Institution (submitter + certifier) + agreement + one reporting period.

    advance_to: ISO instant to move the logical clock to after creation
    (None keeps the pinned default clock). Returns a context dict with
    inst_id, sub_uid, cert_uid, period_id.
    """
    ctx = create_institution_with_registrars()
    if with_agreement:
        ctx["agreement"] = add_agreement(ctx["inst_id"])
    ctx["period"] = add_period(ctx["inst_id"], **period_overrides)
    ctx["period_id"] = ctx["period"]["id"]
    if advance_to is not None:
        advance_clock(advance_to)
    return ctx


def upload_file(ctx, rows, expected_version=None) -> dict:
    """Upload an enrollment file as the scenario's submitter.

    When expected_version is None the period's current version is re-read
    first (the common path); callers exercising OCC pass it explicitly.
    """
    if expected_version is None:
        expected_version = get_period_version(ctx["inst_id"])
    payload = create_enrollment_file_payload(
        ctx["inst_id"], ctx["period_id"], expected_version, rows,
    )
    resp = api_client.create_enrollment_file(payload, make_submitter_headers(ctx["sub_uid"]))
    return get_success_data(resp)


def certify_file(ctx, file_id) -> dict:
    resp = api_client.certify_enrollment_file(file_id, make_certifier_headers(ctx["cert_uid"]))
    return get_success_data(resp)


def setup_uploaded_file(rows=None, **scenario_kw) -> dict:
    """Period scenario + one uploaded (uncertified) file.

    Returns the scenario context plus file and entries.
    """
    ctx = setup_period_scenario(**scenario_kw)
    ctx["file"] = upload_file(ctx, rows if rows is not None else [enrollment_row()])
    ctx["file_id"] = ctx["file"]["id"]
    ctx["entries"] = list_file_entries(ctx["file_id"])
    return ctx


def setup_certified_file(rows=None, **scenario_kw) -> dict:
    """Period scenario + one uploaded file, certified by the certifier."""
    ctx = setup_uploaded_file(rows=rows, **scenario_kw)
    ctx["file"] = certify_file(ctx, ctx["file_id"])
    ctx["entries"] = list_file_entries(ctx["file_id"])
    return ctx


def setup_student_with_file(rows=None, **scenario_kw) -> dict:
    """Certified file exposing student_id of the first entry as student_id."""
    ctx = setup_certified_file(rows=rows, **scenario_kw)
    ctx["student_id"] = ctx["entries"][0]["student_id"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: degrees
# ---------------------------------------------------------------------------

def report_degree(ctx, student_id, **overrides) -> dict:
    payload = create_degree_payload(ctx["inst_id"], student_id, **overrides)
    resp = api_client.create_degree_record(payload, make_submitter_headers(ctx["sub_uid"]))
    return get_success_data(resp)


def seal_degree(ctx, degree_id) -> dict:
    resp = api_client.seal_degree_record(degree_id, make_certifier_headers(ctx["cert_uid"]))
    return get_success_data(resp)


def setup_sealed_degree(ctx, student_id, **overrides) -> dict:
    degree = report_degree(ctx, student_id, **overrides)
    return seal_degree(ctx, degree["id"])


# ---------------------------------------------------------------------------
# Tier 3: requesters and verification requests
# ---------------------------------------------------------------------------

def create_requester(credit=None, kind="EMPLOYER", org="Acme Hiring") -> dict:
    payload = create_requester_payload(org_name=org, requester_kind=kind)
    if credit is not None:
        payload["initial_credit_cents"] = credit
    resp = api_client.create_requester(payload, OPS)
    return get_success_data(resp)


def vet_requester(requester_id, outcome="VET") -> dict:
    resp = api_client.vet_requester(requester_id, {"outcome": outcome}, OPS)
    return get_success_data(resp)


def setup_vetted_requester(credit=100000, kind="EMPLOYER", org="Acme Hiring") -> dict:
    rq = create_requester(credit=credit, kind=kind, org=org)
    return vet_requester(rq["id"], "VET")


def create_request(payload, as_requester_id=None, as_student_id=None):
    """Create a verification request with correctly-threaded identity."""
    if as_requester_id is not None:
        headers = make_requester_headers(as_requester_id)
    elif as_student_id is not None:
        headers = make_learner_headers(as_student_id)
    else:
        raise ValueError("create_request needs a requester or learner identity")
    resp = api_client.create_verification_request(payload, headers)
    return resp


def create_degree_request(inst_id, student_id, requester_id,
                          purpose="EMPLOYMENT", rush=None) -> dict:
    payload = create_verification_request_payload(
        student_id, inst_id, requester_id=requester_id, purpose=purpose,
    )
    if rush is not None:
        payload["rush"] = rush
    resp = create_request(payload, as_requester_id=requester_id)
    return get_success_data(resp)


def pay_request(request_id, payer_id, learner=False) -> dict:
    headers = (make_learner_headers(payer_id) if learner
               else make_requester_headers(payer_id))
    resp = api_client.pay_verification_request(request_id, headers)
    return get_success_data(resp)


def fulfill_request(request_id) -> dict:
    resp = api_client.fulfill_verification_request(request_id, OPS)
    return get_success_data(resp)


def release_degree_request(inst_id, student_id, requester_id, purpose="EMPLOYMENT") -> dict:
    """Create -> pay -> fulfill a DEGREE request. Returns the RELEASED request."""
    req = create_degree_request(inst_id, student_id, requester_id, purpose=purpose)
    pay_request(req["id"], requester_id)
    return fulfill_request(req["id"])


def release_n_degree_requests(ctx, requester_id, n, base_iso="2026-11-15T00:00:00Z") -> list:
    """Release n identical DEGREE requests, advancing the clock one hour
    between releases so each release lands strictly before the next quote."""
    released = []
    for i in range(n):
        released.append(
            release_degree_request(ctx["inst_id"], ctx["student_id"], requester_id)
        )
        if i < n - 1:
            hour = f"{i + 1:02d}"
            advance_clock(f"2026-11-15T{hour}:00:00Z")
    return released


# ---------------------------------------------------------------------------
# Tier 4: privacy directives (OCC-threaded)
# ---------------------------------------------------------------------------

def place_directive(student_id, directive_type="FULL_BLOCK",
                    effective_from="2026-01-01", effective_to=None,
                    headers=None) -> dict:
    """Place a privacy directive, re-reading the student version for OCC."""
    version = get_student_version(student_id)
    payload = create_directive_payload(
        version, directive_type=directive_type, effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    resp = api_client.create_privacy_directive(
        student_id, payload, headers if headers is not None else OPS,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: research cohorts
# ---------------------------------------------------------------------------

def make_rows(n, prefix="S", first_name="Student", dob_month=1,
              credit_hours=12.0, career_level="UNDERGRAD",
              term_start="2026-09-01", term_end="2026-12-15",
              servicer_ref=None) -> list:
    """Build n distinct rows: unique student_ref, full_name and dob."""
    rows = []
    ordinals = [
        "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
        "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
    ]
    for i in range(n):
        row = enrollment_row(
            student_ref=f"{prefix}{i + 1:02d}",
            full_name=f"{first_name} {ordinals[i]}",
            date_of_birth=f"2004-{dob_month:02d}-{i + 1:02d}",
            career_level=career_level,
            credit_hours=credit_hours,
            term_start=term_start,
            term_end=term_end,
        )
        if servicer_ref is not None:
            row["servicer_ref"] = servicer_ref
        rows.append(row)
    return rows


def setup_research_dataset(ctx, analyst_id="analyst-a",
                           cohort_term_start="2026-09-01",
                           cohort_term_end="2026-12-15") -> dict:
    payload = create_dataset_payload(
        ctx["inst_id"],
        cohort_term_start=cohort_term_start,
        cohort_term_end=cohort_term_end,
    )
    resp = api_client.create_research_dataset(payload, make_analyst_headers(analyst_id))
    return get_success_data(resp)
