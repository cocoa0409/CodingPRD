"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints; the
server is re-launched before every test, so nothing may be assumed seeded.
Ownership-gated calls use per-instance role headers built from the actual entity
id created by the same helper.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import DEFAULTS
from .factories import (
    accrual_payload,
    authorization_payload,
    batch_payload,
    dispute_payload,
    employer_payload,
    layout_payload,
    product_payload,
    record_payload,
    request_payload,
    review_payload,
    settlement_payload,
    verifier_payload,
    worker_payload,
)
from .test_users import (
    TEST_USERS,
    make_employer_headers,
    make_verifier_headers,
    make_worker_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _ok(response):
    data = get_success_data(response)
    return data


# --------------------------------------------------------------------------
# Primitive entity creation
# --------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


def onboard_employer(
    fein=DEFAULTS["FEIN"],
    frequency=DEFAULTS["PAYROLL_FREQUENCY"],
    legal_name=DEFAULTS["LEGAL_NAME"],
    employer_type=DEFAULTS["EMPLOYER_TYPE"],
):
    return _ok(api.create_employer(
        employer_payload(
            fein=fein,
            payroll_frequency=frequency,
            legal_name=legal_name,
            employer_type=employer_type,
        ),
        ADMIN,
    ))


def register_worker(
    full_name=DEFAULTS["WORKER_NAME"],
    ssn_last4=DEFAULTS["WORKER_SSN_LAST4"],
    date_of_birth=DEFAULTS["WORKER_DOB"],
):
    return _ok(api.create_worker(
        worker_payload(full_name=full_name, ssn_last4=ssn_last4, date_of_birth=date_of_birth),
        ADMIN,
    ))


def register_product(**overrides):
    return _ok(api.create_product(product_payload(**overrides), ADMIN))


def register_verifier(**overrides):
    return _ok(api.create_verifier(verifier_payload(**overrides), ADMIN))


def authorize_verifier(verifier_id):
    """Move a freshly registered requesting party to AUTHORIZED / NORMAL posture."""
    headers = make_verifier_headers(verifier_id)
    _ok(api.accredit_verifier(verifier_id, headers))
    return _ok(api.authorize_verifier(verifier_id, headers))


def fund_escrow(verifier_id, amount_cents):
    return _ok(api.escrow_adjustment(verifier_id, amount_cents, ADMIN))


def register_authorized_verifier(**overrides):
    verifier = register_verifier(**overrides)
    return authorize_verifier(verifier["id"])


def create_layout(employer_id, layout_version=1, column_map=None, fiscal_year_start_month=1):
    headers = make_employer_headers(employer_id)
    payload = layout_payload(
        employer_id,
        layout_version=layout_version,
        fiscal_year_start_month=fiscal_year_start_month,
    )
    if column_map is not None:
        payload["column_map"] = column_map
    return _ok(api.create_layout(payload, headers))


def verify_layout(employer_id, layout_id):
    return _ok(api.verify_layout(layout_id, make_employer_headers(employer_id)))


def create_verified_layout(employer_id, layout_version=1, column_map=None):
    """Register a layout and promote it to VERIFIED (complete map assumed)."""
    layout = create_layout(employer_id, layout_version=layout_version, column_map=column_map)
    return verify_layout(employer_id, layout["id"])


def create_batch(
    employer_id,
    layout_id,
    batch_sequence=1,
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
    record_count=DEFAULTS["BATCH_RECORD_COUNT"],
):
    return _ok(api.create_batch(
        batch_payload(
            employer_id,
            layout_id,
            batch_sequence=batch_sequence,
            pay_period_end_date=pay_period_end_date,
            record_count=record_count,
        ),
        make_employer_headers(employer_id),
    ))


def attach_record(employer_id, worker_id, batch_id, **overrides):
    return _ok(api.create_record(
        record_payload(employer_id, worker_id, batch_id, **overrides),
        make_employer_headers(employer_id),
    ))


def validate_batch(employer_id, batch_id):
    return _ok(api.validate_batch(batch_id, make_employer_headers(employer_id)))


def reject_batch(employer_id, batch_id):
    return _ok(api.reject_batch(batch_id, make_employer_headers(employer_id)))


def get_record(record_id):
    return _ok(api.get_record(record_id, ADMIN))


def get_employer(employer_id):
    return _ok(api.get_employer(employer_id, ADMIN))


def get_worker(worker_id, headers=None):
    return _ok(api.get_worker(worker_id, headers or ADMIN))


def get_verifier(verifier_id, headers=None):
    return _ok(api.get_verifier(verifier_id, headers or ADMIN))


def get_request(request_id, headers=None):
    return _ok(api.get_request(request_id, headers or ADMIN))


def _scoped_headers(second, third, builder):
    """Getters accept either an owner id (headers are then built from it) or an
    already-built headers dict as the second positional argument."""
    if isinstance(second, dict):
        return second
    if isinstance(third, dict):
        return third
    if second:
        return builder(second)
    return ADMIN


def get_batch(batch_id, employer_id=None, headers=None):
    headers = _scoped_headers(employer_id, headers, make_employer_headers)
    return _ok(api.get_batch(batch_id, headers))


def record_version(record_id):
    """Re-read the live version of an employment span before a version-guarded write."""
    return get_record(record_id)["version"]


# --------------------------------------------------------------------------
# Verification chain
# --------------------------------------------------------------------------

def capture_authorization(worker, verifier, purpose=DEFAULTS["VERIFIER_PURPOSE"], worker_version=None):
    headers = make_worker_headers(worker["id"])
    if worker_version is None:
        worker_version = get_worker(worker["id"])["version"]
    return _ok(api.create_authorization(
        authorization_payload(worker["id"], verifier["id"], worker_version, permitted_purpose=purpose),
        headers,
    ))


def submit_request(verifier, worker, product, purpose=DEFAULTS["VERIFIER_PURPOSE"]):
    return _ok(api.create_request(
        request_payload(verifier["id"], worker["id"], product["id"], permissible_purpose_asserted=purpose),
        make_verifier_headers(verifier["id"]),
    ))


def permit_request(worker_id, request_id, authorization_id):
    return _ok(api.permit_request(
        request_id, authorization_id, make_worker_headers(worker_id)
    ))


def validate_currency(verifier_id, request_id):
    return _ok(api.validate_currency(request_id, make_verifier_headers(verifier_id)))


def reconsent_request(worker_id, request_id):
    return _ok(api.reconsent_request(request_id, make_worker_headers(worker_id)))


def get_layout(layout_id, employer_id=None, headers=None):
    headers = _scoped_headers(employer_id, headers, make_employer_headers)
    return _ok(api.get_layout(layout_id, headers))


def get_review(review_id, employer_id=None, headers=None):
    headers = _scoped_headers(employer_id, headers, make_employer_headers)
    return _ok(api.get_review(review_id, headers))


def materialize_response(verifier_id, request_id):
    return _ok(api.create_response(request_id, make_verifier_headers(verifier_id)))


def sign_attestation(verifier_id, request_id, purpose=DEFAULTS["VERIFIER_PURPOSE"]):
    return _ok(api.create_attestation(
        {
            "verification_request_id": request_id,
            "verifier_id": verifier_id,
            "attested_purpose": purpose,
        },
        make_verifier_headers(verifier_id),
    ))


# --------------------------------------------------------------------------
# Tier 2/3: composite scenario builders
# --------------------------------------------------------------------------

def setup_employer_worker_record(
    fein=DEFAULTS["FEIN"],
    frequency=DEFAULTS["PAYROLL_FREQUENCY"],
    legal_name=DEFAULTS["LEGAL_NAME"],
    employer_type=DEFAULTS["EMPLOYER_TYPE"],
    worker_name=DEFAULTS["WORKER_NAME"],
    worker_ssn_last4=DEFAULTS["WORKER_SSN_LAST4"],
    worker_dob=DEFAULTS["WORKER_DOB"],
    record_overrides=None,
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
    record_count=DEFAULTS["BATCH_RECORD_COUNT"],
    batch_sequence=1,
    layout_version=1,
    validate=True,
):
    """Employer + worker + VERIFIED layout + one record on a validated batch."""
    employer = onboard_employer(
        fein=fein, frequency=frequency, legal_name=legal_name, employer_type=employer_type
    )
    worker = register_worker(full_name=worker_name, ssn_last4=worker_ssn_last4, date_of_birth=worker_dob)
    layout = create_verified_layout(employer["id"], layout_version=layout_version)
    batch = create_batch(
        employer["id"],
        layout["id"],
        batch_sequence=batch_sequence,
        pay_period_end_date=pay_period_end_date,
        record_count=record_count,
    )
    record = attach_record(
        employer["id"], worker["id"], batch["id"], **(record_overrides or {})
    )
    if validate:
        batch = validate_batch(employer["id"], batch["id"])
    return {
        "employer": employer,
        "worker": worker,
        "layout": layout,
        "batch": batch,
        "record": record,
    }


def setup_verification_stack(
    clock=None,
    record_overrides=None,
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
    record_count=DEFAULTS["BATCH_RECORD_COUNT"],
    product_overrides=None,
    verifier_overrides=None,
    purpose=DEFAULTS["VERIFIER_PURPOSE"],
    permit=True,
    validate=False,
    respond=False,
):
    """Full verification preamble: employer, worker, verified span, product,
    authorized requesting party, captured authorization and one request."""
    if clock is not None:
        set_clock(clock)
    base = setup_employer_worker_record(
        record_overrides=record_overrides,
        pay_period_end_date=pay_period_end_date,
        record_count=record_count,
    )
    product = register_product(**(product_overrides or {}))
    verifier = register_authorized_verifier(**(verifier_overrides or {}))
    authorization = capture_authorization(base["worker"], verifier, purpose=purpose)
    request = submit_request(verifier, base["worker"], product, purpose=purpose)
    if permit:
        request = permit_request(base["worker"]["id"], request["id"], authorization["id"])
    response_row = None
    if validate or respond:
        request = validate_currency(verifier["id"], request["id"])
    if respond:
        response_row = materialize_response(verifier["id"], request["id"])
        request = get_request(request["id"], make_verifier_headers(verifier["id"]))
    base.update({
        "product": product,
        "verifier": verifier,
        "authorization": authorization,
        "request": request,
    })
    if response_row is not None:
        base["response"] = response_row
    return base


def setup_request_with_signed_attestation(clock=None, **overrides):
    """A PERMITTED request plus a standalone SIGNED attestation against it."""
    stack = setup_verification_stack(clock=clock, **overrides)
    attestation = sign_attestation(stack["verifier"]["id"], stack["request"]["id"])
    stack["attestation"] = attestation
    return stack


def setup_responded_request(clock=None, **overrides):
    overrides.pop("respond", None)
    return setup_verification_stack(clock=clock, respond=True, **overrides)


def setup_validated_request(clock=None, **overrides):
    overrides.pop("validate", None)
    return setup_verification_stack(clock=clock, validate=True, **overrides)


def setup_verified_span_stack(
    clock=None,
    fein=DEFAULTS["FEIN"],
    frequency=DEFAULTS["PAYROLL_FREQUENCY"],
    legal_name=DEFAULTS["LEGAL_NAME"],
    employer_type=DEFAULTS["EMPLOYER_TYPE"],
    worker_name=DEFAULTS["WORKER_NAME"],
    worker_ssn_last4=DEFAULTS["WORKER_SSN_LAST4"],
    worker_dob=DEFAULTS["WORKER_DOB"],
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
    record_count=DEFAULTS["BATCH_RECORD_COUNT"],
    record_overrides=None,
    batch_sequence=1,
    layout_id=None,
    batch_id=None,
):
    """A VERIFIED span (record_state VERIFIED, currency CURRENT) with no verifier
    machinery. Used by tests that only need a disputable span."""
    if clock is not None:
        set_clock(clock)
    employer = onboard_employer(
        fein=fein, frequency=frequency, legal_name=legal_name, employer_type=employer_type
    )
    worker = register_worker(full_name=worker_name, ssn_last4=worker_ssn_last4, date_of_birth=worker_dob)
    layout = create_verified_layout(employer["id"]) if layout_id is None else {"id": layout_id}
    batch = (
        create_batch(
            employer["id"],
            layout["id"],
            batch_sequence=batch_sequence,
            pay_period_end_date=pay_period_end_date,
            record_count=record_count,
        )
        if batch_id is None
        else {"id": batch_id}
    )
    record = attach_record(
        employer["id"], worker["id"], batch["id"], **(record_overrides or {})
    )
    batch = validate_batch(employer["id"], batch["id"])
    return {
        "employer": employer,
        "worker": worker,
        "layout": layout,
        "batch": batch,
        "record": record,
    }


# --------------------------------------------------------------------------
# Tier 1: freeze progression
# --------------------------------------------------------------------------

def freeze_employer_to_active(employer_id, reason_code="EMPLOYER_DIRECTIVE"):
    """File twice so the freeze reaches ACTIVE and the cascade fires."""
    headers = make_employer_headers(employer_id)
    first = _ok(api.freeze_employer(employer_id, reason_code, headers))
    second = _ok(api.freeze_employer(employer_id, reason_code, headers))
    return first, second


def release_freeze(employer_id):
    return _ok(api.unfreeze_employer(employer_id, "RELEASE", make_employer_headers(employer_id)))


def lapse_freeze(employer_id):
    return _ok(api.unfreeze_employer(employer_id, "LAPSE", make_employer_headers(employer_id)))


# --------------------------------------------------------------------------
# Tier 4: dispute lifecycle targeting
# --------------------------------------------------------------------------

def file_dispute(worker_id, record_id, claimed_field="EMPLOYMENT_STATUS",
                 claimed_correct_value="TERMINATED", record_version=None):
    headers = make_worker_headers(worker_id)
    if record_version is None:
        record_version = record_version_of(record_id)
    return _ok(api.create_dispute(
        dispute_payload(
            record_id,
            worker_id,
            record_version,
            claimed_field=claimed_field,
            claimed_correct_value=claimed_correct_value,
        ),
        headers,
    ))


def record_version_of(record_id):
    return get_record(record_id)["version"]


def notice_dispute(employer_id, dispute_id):
    return _ok(api.notice_dispute(dispute_id, make_employer_headers(employer_id)))


def respond_dispute(employer_id, dispute_id, resolution):
    return _ok(api.respond_dispute(dispute_id, resolution, make_employer_headers(employer_id)))


def reopen_dispute(worker_id, dispute_id, resolution="REOPEN"):
    return _ok(api.reopen_dispute(dispute_id, resolution, make_worker_headers(worker_id)))


def setup_dispute_in_notice_sent(
    clock=None,
    claimed_field="EMPLOYMENT_STATUS",
    claimed_correct_value="TERMINATED",
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
):
    """A VERIFIED span with one dispute already moved to NOTICE_SENT."""
    base = setup_employer_worker_record(pay_period_end_date=pay_period_end_date)
    if clock is not None:
        set_clock(clock)
    dispute = file_dispute(
        base["worker"]["id"],
        base["record"]["id"],
        claimed_field=claimed_field,
        claimed_correct_value=claimed_correct_value,
    )
    dispute = notice_dispute(base["employer"]["id"], dispute["id"])
    base["dispute"] = dispute
    return base


def setup_dispute_acknowledged(
    clock=None,
    claimed_field="PAY_RATE",
    claimed_correct_value="480000",
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
):
    """A VERIFIED span with one dispute acknowledged by the employer."""
    base = setup_dispute_in_notice_sent(
        clock=clock,
        claimed_field=claimed_field,
        claimed_correct_value=claimed_correct_value,
        pay_period_end_date=pay_period_end_date,
    )
    dispute = respond_dispute(base["employer"]["id"], base["dispute"]["id"], "ACKNOWLEDGED")
    base["dispute"] = dispute
    return base


# --------------------------------------------------------------------------
# Tier 5: compensation settlement targeting
# --------------------------------------------------------------------------

def create_validated_batch_accrual(
    fein="123456789",
    record_count=1200,
    pay_period_end_date=DEFAULTS["DEFAULT_FEED_PERIOD_END"],
    frequency=DEFAULTS["PAYROLL_FREQUENCY"],
):
    """Employer + verified layout + one VALIDATED batch, so an accrual exists."""
    employer = onboard_employer(fein=fein, frequency=frequency)
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"],
        layout["id"],
        pay_period_end_date=pay_period_end_date,
        record_count=record_count,
    )
    batch = validate_batch(employer["id"], batch["id"])
    accruals = _ok(api.list_accruals(ADMIN, params={"employer_id": employer["id"]}))
    return {
        "employer": employer,
        "layout": layout,
        "batch": batch,
        "accrual": accruals[0],
    }


def post_settlement(employer_id, settlement_period_end="2026-06-30T00:00:00Z",
                    settlement_budget_cents=12000, waiver_budget_cents=0,
                    apply_blended_rate=None):
    payload = settlement_payload(
        employer_id,
        settlement_period_end=settlement_period_end,
        settlement_budget_cents=settlement_budget_cents,
        waiver_budget_cents=waiver_budget_cents,
    )
    if apply_blended_rate is not None:
        payload["apply_blended_rate"] = apply_blended_rate
    return _ok(api.create_settlement(payload, ADMIN))


def void_settlement(settlement_id):
    return _ok(api.void_settlement(settlement_id, ADMIN))


def list_accruals(employer_id):
    return _ok(api.list_accruals(ADMIN, params={"employer_id": employer_id}))


# --------------------------------------------------------------------------
# Currency review helpers
# --------------------------------------------------------------------------

def open_review(employer_id, **overrides):
    return _ok(api.create_review(review_payload(employer_id, **overrides), ADMIN))


# --------------------------------------------------------------------------
# Disclosure helpers
# --------------------------------------------------------------------------

def request_disclosure(worker_id):
    return _ok(api.create_disclosure(worker_id, make_worker_headers(worker_id)))


def generate_disclosure(worker_id, disclosure_id):
    return _ok(api.generate_disclosure(disclosure_id, make_worker_headers(worker_id)))


def get_disclosure(disclosure_id, worker_id=None):
    headers = make_worker_headers(worker_id) if worker_id else ADMIN
    return _ok(api.get_disclosure(disclosure_id, headers))


def list_disputes(worker_id=None, record_id=None, employer_id=None):
    params = {}
    if worker_id:
        params["covered_worker_id"] = worker_id
    if record_id:
        params["employment_record_id"] = record_id
    headers = make_worker_headers(worker_id) if worker_id else (
        make_employer_headers(employer_id) if employer_id else ADMIN
    )
    return _ok(api.list_disputes(headers, params=params))


def list_responses(request_id, verifier_id=None):
    headers = make_verifier_headers(verifier_id) if verifier_id else ADMIN
    return _ok(api.list_responses(headers, params={"verification_request_id": request_id}))


def list_authorizations(worker_id=None, verifier_id=None):
    params = {}
    if worker_id:
        params["covered_worker_id"] = worker_id
    if verifier_id:
        params["verifier_id"] = verifier_id
    headers = make_worker_headers(worker_id) if worker_id else ADMIN
    return _ok(api.list_authorizations(headers, params=params))


def get_dispute(dispute_id, employer_id=None, worker_id=None, headers=None):
    if isinstance(employer_id, dict):
        headers = employer_id
    elif isinstance(worker_id, dict):
        headers = worker_id
    elif headers is not None:
        pass
    elif employer_id:
        headers = make_employer_headers(employer_id)
    elif worker_id:
        headers = make_worker_headers(worker_id)
    else:
        headers = ADMIN
    return _ok(api.get_dispute(dispute_id, headers))


def get_attestation(attestation_id, verifier_id=None, headers=None):
    headers = _scoped_headers(verifier_id, headers, make_verifier_headers)
    return _ok(api.get_attestation(attestation_id, headers))