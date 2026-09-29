"""Precondition builders for the ESA administration API.

Every helper builds its preconditions from scratch against an empty database using
only the endpoints the requirements document declares, and reads results through
the lenient success reader so that a broken precondition surfaces as a setup
failure naming the error identifier rather than as a confusing assertion inside
the test body.

The composite helpers return an :class:`Env`, a dictionary whose keys are also
readable as attributes, so a test body reads ``env.account_id`` rather than
indexing strings.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_status_action_payload,
    create_adjudication_payload,
    create_appeal_decision_payload,
    create_application_payload,
    create_application_denial_appeal_payload,
    create_approve_provider_payload,
    create_claim_payload,
    create_clawback_appeal_payload,
    create_curriculum_provider_payload,
    create_decision_payload,
    create_determination_payload,
    create_field_trips_category_payload,
    create_materials_category_payload,
    create_misuse_case_payload,
    create_next_program_year_payload,
    create_program_year_payload,
    create_provider_delisting_appeal_payload,
    create_provider_payload,
    create_purchase_request_payload,
    create_renewal_decision_payload,
    create_renewal_review_payload,
    create_sanction_payload,
    create_school_provider_payload,
    create_screening_payload,
    create_student_payload,
    create_tuition_category_payload,
    create_tutoring_category_payload,
)
from .test_users import (
    AO,
    CO,
    EO,
    ER1,
    ER2,
    PA,
    VS,
    make_guardian_headers,
    make_provider_headers,
)

CANONICAL_CLOCK = "2026-09-01T00:00:00Z"


class Env(dict):
    """A precondition bundle whose keys are also readable as attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as missing:
            raise AttributeError(name) from missing


# --- Tier 0: the logical clock and thin readers ----------------------------------


def set_clock(to_iso8601, headers=PA):
    """Move the server's logical UTC clock and return the new setting."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def read_program_year(program_year_id, headers=PA):
    return get_success_data(api_client.get_program_year(program_year_id, headers))


def read_student(student_id, headers=PA):
    return get_success_data(api_client.get_student(student_id, headers))


def read_application(application_id, headers=PA):
    return get_success_data(api_client.get_application(application_id, headers))


def read_account(account_id, headers=PA):
    return get_success_data(api_client.get_account(account_id, headers))


def read_provider(provider_id, headers=PA):
    return get_success_data(api_client.get_provider(provider_id, headers))


def read_expense_category(expense_category_id, headers=PA):
    return get_success_data(
        api_client.get_expense_category(expense_category_id, headers)
    )


def read_purchase_request(purchase_request_id, headers=PA):
    return get_success_data(
        api_client.get_purchase_request(purchase_request_id, headers)
    )


def read_misuse_case(misuse_case_id, headers=PA):
    return get_success_data(api_client.get_misuse_case(misuse_case_id, headers))


def read_renewal_review(renewal_review_id, headers=PA):
    return get_success_data(api_client.get_renewal_review(renewal_review_id, headers))


def read_appeal(appeal_id, headers=PA):
    return get_success_data(api_client.get_appeal(appeal_id, headers))


def account_version(account_id, headers=PA):
    """The account's current ``version``, for the purchase-request version guard."""
    return read_account(account_id, headers)["version"]


def application_version(application_id, headers=PA):
    """The application's current ``version``, for the renewal-review version guard."""
    return read_application(application_id, headers)["version"]


# --- Tier 1: single-step creators ------------------------------------------------


def create_program_year(**overrides):
    """Create a programme year in DRAFT."""
    return get_success_data(
        api_client.create_program_year(create_program_year_payload(**overrides), PA)
    )


def create_next_program_year(**overrides):
    """Create the successor year a renewal would fund."""
    return get_success_data(
        api_client.create_program_year(create_next_program_year_payload(**overrides), PA)
    )


def open_window(program_year_id):
    """Advance a programme year DRAFT to WINDOW_OPEN and publish its seat pool."""
    return get_success_data(api_client.open_window(program_year_id, PA))


def create_open_program_year(**overrides):
    """Create a programme year and publish its submission window."""
    year = create_program_year(**overrides)
    open_window(year["id"])
    return read_program_year(year["id"])


def create_tutoring_category(**overrides):
    return get_success_data(
        api_client.create_expense_category(
            create_tutoring_category_payload(**overrides), PA
        )
    )


def create_materials_category(**overrides):
    return get_success_data(
        api_client.create_expense_category(
            create_materials_category_payload(**overrides), PA
        )
    )


def create_tuition_category(**overrides):
    return get_success_data(
        api_client.create_expense_category(
            create_tuition_category_payload(**overrides), PA
        )
    )


def create_field_trips_category(**overrides):
    return get_success_data(
        api_client.create_expense_category(
            create_field_trips_category_payload(**overrides), PA
        )
    )


def create_student(**overrides):
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), PA)
    )


def create_application(program_year_id, student_id, **overrides):
    """File a DRAFT application as the guardian behind ``student_id``."""
    return get_success_data(
        api_client.create_application(
            create_application_payload(program_year_id, student_id, **overrides),
            make_guardian_headers(student_id),
        )
    )


def submit_application(application_id, student_id):
    return get_success_data(
        api_client.submit_application(application_id, make_guardian_headers(student_id))
    )


def record_determination(application_id, headers=EO, **overrides):
    """Record an eligibility determination on a submitted application."""
    return get_success_data(
        api_client.create_eligibility_determination(
            application_id, create_determination_payload(**overrides), headers
        )
    )


def run_awarding(program_year_id):
    return get_success_data(api_client.run_awarding(program_year_id, PA))


def accept_award(application_id, student_id):
    return get_success_data(
        api_client.accept_award(application_id, make_guardian_headers(student_id))
    )


def withdraw_application(application_id, student_id):
    return get_success_data(
        api_client.withdraw_application(
            application_id, make_guardian_headers(student_id)
        )
    )


def run_disbursement(program_year_id, quarter):
    return get_success_data(api_client.run_disbursement(program_year_id, quarter, PA))


def close_year(program_year_id):
    return get_success_data(api_client.close_year(program_year_id, PA))


def create_provider(payload_builder=create_provider_payload, **overrides):
    """Register a candidate provider in DRAFT."""
    return get_success_data(api_client.create_provider(payload_builder(**overrides), PA))


def screen_provider(provider_id, flags=None):
    """Run the integrity check and record the resulting score."""
    return get_success_data(
        api_client.create_fraud_screening(
            provider_id, create_screening_payload(flags), VS
        )
    )


def approve_provider(provider_id, codes=None):
    """Admit a screened provider and pin the categories it may serve."""
    return get_success_data(
        api_client.approve_provider(
            provider_id, create_approve_provider_payload(codes), VS
        )
    )


def sanction_provider(provider_id, action, reason, headers=CO):
    return get_success_data(
        api_client.sanction_provider(
            provider_id, create_sanction_payload(action, reason), headers
        )
    )


def suspend_account(account_id, reason="Documentation audit in progress.", headers=CO):
    return get_success_data(
        api_client.account_status_action(
            account_id, create_account_status_action_payload("SUSPEND", reason), headers
        )
    )


def reinstate_account(account_id, reason="Audit closed with no findings.", headers=CO):
    return get_success_data(
        api_client.account_status_action(
            account_id, create_account_status_action_payload("REINSTATE", reason), headers
        )
    )


def file_purchase_request(
    account_id,
    student_id,
    provider_id,
    expense_category_id,
    expected_account_version=None,
    **overrides,
):
    """File a purchase request, reading the account version afresh when not given."""
    if expected_account_version is None:
        expected_account_version = account_version(account_id)
    payload = create_purchase_request_payload(
        provider_id, expense_category_id, expected_account_version, **overrides
    )
    return get_success_data(
        api_client.create_purchase_request(
            account_id, payload, make_guardian_headers(student_id)
        )
    )


def decide_purchase_request(purchase_request_id, decision, headers=ER1, **overrides):
    return get_success_data(
        api_client.decide_purchase_request(
            purchase_request_id, create_decision_payload(decision, **overrides), headers
        )
    )


def claim_purchase_request(
    purchase_request_id, provider_id, claimed_amount_cents, invoice_reference
):
    return get_success_data(
        api_client.claim_purchase_request(
            purchase_request_id,
            create_claim_payload(claimed_amount_cents, invoice_reference),
            make_provider_headers(provider_id),
        )
    )


def settle_purchase_request(purchase_request_id, headers=ER2):
    return get_success_data(
        api_client.settle_purchase_request(purchase_request_id, headers)
    )


def open_misuse_case(account_id, headers=CO, **overrides):
    return get_success_data(
        api_client.create_misuse_case(
            create_misuse_case_payload(account_id, **overrides), headers
        )
    )


def review_misuse_case(misuse_case_id, headers=CO):
    return get_success_data(api_client.review_misuse_case(misuse_case_id, headers))


def adjudicate_misuse_case(
    misuse_case_id, outcome, rationale="Attendance logs contradict the billed hours.",
    headers=CO,
):
    return get_success_data(
        api_client.adjudicate_misuse_case(
            misuse_case_id, create_adjudication_payload(outcome, rationale), headers
        )
    )


def issue_clawback(misuse_case_id, headers=CO):
    return get_success_data(api_client.issue_clawback(misuse_case_id, headers))


def file_renewal_review(
    account_id,
    next_program_year_id,
    student_id,
    expected_application_version,
    **overrides,
):
    payload = create_renewal_review_payload(
        account_id, next_program_year_id, expected_application_version, **overrides
    )
    return get_success_data(
        api_client.create_renewal_review(payload, make_guardian_headers(student_id))
    )


def decide_renewal_review(renewal_review_id, decision, headers=EO, **overrides):
    return get_success_data(
        api_client.decide_renewal_review(
            renewal_review_id,
            create_renewal_decision_payload(decision, **overrides),
            headers,
        )
    )


def file_application_denial_appeal(application_id, student_id, **overrides):
    return get_success_data(
        api_client.create_appeal(
            create_application_denial_appeal_payload(application_id, **overrides),
            make_guardian_headers(student_id),
        )
    )


def file_clawback_appeal(misuse_case_id, student_id, **overrides):
    return get_success_data(
        api_client.create_appeal(
            create_clawback_appeal_payload(misuse_case_id, **overrides),
            make_guardian_headers(student_id),
        )
    )


def file_provider_delisting_appeal(provider_id, **overrides):
    return get_success_data(
        api_client.create_appeal(
            create_provider_delisting_appeal_payload(provider_id, **overrides),
            make_provider_headers(provider_id),
        )
    )


def decide_appeal(appeal_id, decision, rationale, headers=AO):
    return get_success_data(
        api_client.decide_appeal(
            appeal_id, create_appeal_decision_payload(decision, rationale), headers
        )
    )


# --- Tier 2: composite preconditions ---------------------------------------------


def setup_catalog():
    """Publish the three catalogue lines the purchase workflows lean on.

    TUTORING is pre-approval only and switches on the service-interval rule,
    MATERIALS accepts the reimbursement route and is exempt from that rule, and
    TUITION is pre-approval only but also exempt.
    """
    return Env(
        tutoring=create_tutoring_category(),
        materials=create_materials_category(),
        tuition=create_tuition_category(),
    )


def setup_open_year_and_student(
    *, year_overrides=None, student_overrides=None, clock=CANONICAL_CLOCK
):
    """A programme year with its window published, a student, and the clock inside it."""
    year = create_program_year(**(year_overrides or {}))
    open_window(year["id"])
    student = create_student(**(student_overrides or {}))
    if clock is not None:
        set_clock(clock)
    return Env(
        program_year_id=year["id"],
        program_year=read_program_year(year["id"]),
        student_id=student["id"],
        student=student,
        guardian=make_guardian_headers(student["id"]),
    )


def setup_draft_application(
    *,
    year_overrides=None,
    student_overrides=None,
    application_overrides=None,
    clock=CANONICAL_CLOCK,
):
    """A DRAFT application inside an open window."""
    env = setup_open_year_and_student(
        year_overrides=year_overrides, student_overrides=student_overrides, clock=clock
    )
    application = create_application(
        env.program_year_id, env.student_id, **(application_overrides or {})
    )
    env["application_id"] = application["id"]
    env["application"] = application
    return env


def setup_submitted_application(**kwargs):
    """An application advanced to SUBMITTED with its provisional award stamped."""
    env = setup_draft_application(**kwargs)
    submit_application(env.application_id, env.student_id)
    env["application"] = read_application(env.application_id)
    return env


def setup_eligible_application(*, determination_overrides=None, **kwargs):
    """A submitted application carried to ELIGIBLE by a clean determination."""
    env = setup_submitted_application(**kwargs)
    env["determination"] = record_determination(
        env.application_id, **(determination_overrides or {})
    )
    env["application"] = read_application(env.application_id)
    return env


def setup_denied_application(*, denial_findings=None, **kwargs):
    """A submitted application carried to DENIED by a failing determination."""
    findings = denial_findings or {"residency_check": "FAIL"}
    return setup_eligible_application(determination_overrides=findings, **kwargs)


def setup_accepted_award(*, determination_overrides=None, **kwargs):
    """An accepted offer with the ESA account the acceptance opened."""
    env = setup_eligible_application(
        determination_overrides=determination_overrides, **kwargs
    )
    env["awarding_run"] = run_awarding(env.program_year_id)
    env["accept"] = accept_award(env.application_id, env.student_id)
    env["account_id"] = env["accept"]["account_id"]
    env["account"] = read_account(env.account_id)
    env["application"] = read_application(env.application_id)
    return env


def setup_funded_account(*, quarters=1, **kwargs):
    """An accepted award whose account has been credited for ``quarters`` quarters."""
    env = setup_accepted_award(**kwargs)
    runs = []
    for quarter in range(1, quarters + 1):
        runs.append(run_disbursement(env.program_year_id, quarter))
    env["disbursement_runs"] = runs
    env["account"] = read_account(env.account_id)
    return env


def setup_approved_provider(
    *,
    payload_builder=create_provider_payload,
    flags=None,
    codes=None,
    provider_overrides=None,
):
    """A registered provider screened and admitted with pinned categories."""
    provider = create_provider(payload_builder, **(provider_overrides or {}))
    screening = screen_provider(provider["id"], flags)
    admission = approve_provider(provider["id"], codes)
    return Env(
        provider_id=provider["id"],
        provider=read_provider(provider["id"]),
        screening=screening,
        admission=admission,
    )


def setup_purchase_environment(
    *, quarters=1, provider_flags=None, provider_codes=("TUTORING",), **kwargs
):
    """A funded account, the three-line catalogue, and one admitted provider."""
    env = setup_funded_account(quarters=quarters, **kwargs)
    env.update(setup_catalog())
    provider = setup_approved_provider(
        flags=provider_flags, codes=list(provider_codes)
    )
    env.update(provider)
    return env


def setup_pending_purchase_request(
    env=None, *, category_key="tutoring", amount_cents=150000, **pr_overrides
):
    """A filed purchase request sitting at PENDING_REVIEW and UNSETTLED."""
    if env is None:
        env = setup_purchase_environment()
    request = file_purchase_request(
        env.account_id,
        env.student_id,
        env.provider_id,
        env[category_key]["id"],
        amount_cents=amount_cents,
        **pr_overrides,
    )
    env["purchase_request_id"] = request["id"]
    env["purchase_request"] = request
    return env


def setup_approved_purchase_request(
    env=None, *, approver=ER1, category_key="tutoring", amount_cents=150000, **pr_overrides
):
    """A purchase request approved so that its amount sits in ``encumbered_cents``."""
    env = setup_pending_purchase_request(
        env, category_key=category_key, amount_cents=amount_cents, **pr_overrides
    )
    env["approval"] = decide_purchase_request(
        env.purchase_request_id, "APPROVED", headers=approver
    )
    env["purchase_request"] = read_purchase_request(env.purchase_request_id)
    env["account"] = read_account(env.account_id)
    return env


def setup_claimed_purchase_request(env=None, *, claimed_amount_cents=150000, invoice_reference="INV-9002", **kwargs):
    """An approved purchase request the provider has invoiced."""
    env = setup_approved_purchase_request(env, **kwargs)
    env["claim"] = claim_purchase_request(
        env.purchase_request_id, env.provider_id, claimed_amount_cents, invoice_reference
    )
    env["purchase_request"] = read_purchase_request(env.purchase_request_id)
    return env


def setup_settled_purchase_request(env=None, *, settler=ER2, **kwargs):
    """A claimed purchase request settled by a second reviewer."""
    env = setup_claimed_purchase_request(env, **kwargs)
    env["settlement"] = settle_purchase_request(env.purchase_request_id, headers=settler)
    env["purchase_request"] = read_purchase_request(env.purchase_request_id)
    env["account"] = read_account(env.account_id)
    return env


def setup_misuse_case_under_review(env=None, *, case_overrides=None, **kwargs):
    """A misuse case taken UNDER_REVIEW against a funded account."""
    if env is None:
        env = setup_purchase_environment(**kwargs)
    case = open_misuse_case(env.account_id, **(case_overrides or {}))
    review_misuse_case(case["id"])
    env["misuse_case_id"] = case["id"]
    env["misuse_case"] = read_misuse_case(case["id"])
    return env


def setup_substantiated_case(env=None, *, case_overrides=None, adjudicator=CO, **kwargs):
    """A substantiated misuse case, which suspends the account it names."""
    env = setup_misuse_case_under_review(env, case_overrides=case_overrides, **kwargs)
    env["adjudication"] = adjudicate_misuse_case(
        env.misuse_case_id, "SUBSTANTIATED", headers=adjudicator
    )
    env["misuse_case"] = read_misuse_case(env.misuse_case_id)
    env["account"] = read_account(env.account_id)
    return env


def setup_clawback_issued_case(env=None, **kwargs):
    """A substantiated case whose clawback has been issued against the account."""
    env = setup_substantiated_case(env, **kwargs)
    env["clawback"] = issue_clawback(env.misuse_case_id)
    env["misuse_case"] = read_misuse_case(env.misuse_case_id)
    env["account"] = read_account(env.account_id)
    return env


def setup_delisted_provider(env=None, *, reason="Falsified attendance logs.", **kwargs):
    """An admitted provider that a compliance officer has delisted."""
    if env is None:
        env = setup_approved_provider(**kwargs)
    env["delisting"] = sanction_provider(env.provider_id, "DELIST", reason)
    env["provider"] = read_provider(env.provider_id)
    return env


def setup_next_program_year(*, open_it=True, **overrides):
    """The successor year a renewal review would fund."""
    year = create_next_program_year(**overrides)
    if open_it:
        open_window(year["id"])
    return Env(
        next_program_year_id=year["id"],
        next_program_year=read_program_year(year["id"]),
    )


def setup_renewal_review(env=None, *, review_overrides=None, next_year_overrides=None, **kwargs):
    """A funded account with a SUBMITTED renewal review against a successor year."""
    if env is None:
        env = setup_funded_account(**kwargs)
    if "next_program_year_id" not in env:
        env.update(setup_next_program_year(**(next_year_overrides or {})))
    review = file_renewal_review(
        env.account_id,
        env.next_program_year_id,
        env.student_id,
        application_version(env.application_id),
        **(review_overrides or {}),
    )
    env["renewal_review_id"] = review["id"]
    env["renewal_review"] = review
    return env


__all__ = [
    "CANONICAL_CLOCK",
    "Env",
    "set_clock",
    "read_program_year",
    "read_student",
    "read_application",
    "read_account",
    "read_provider",
    "read_expense_category",
    "read_purchase_request",
    "read_misuse_case",
    "read_renewal_review",
    "read_appeal",
    "account_version",
    "application_version",
    "create_program_year",
    "create_next_program_year",
    "open_window",
    "create_open_program_year",
    "create_tutoring_category",
    "create_materials_category",
    "create_tuition_category",
    "create_field_trips_category",
    "create_student",
    "create_application",
    "submit_application",
    "record_determination",
    "run_awarding",
    "accept_award",
    "withdraw_application",
    "run_disbursement",
    "close_year",
    "create_provider",
    "screen_provider",
    "approve_provider",
    "sanction_provider",
    "suspend_account",
    "reinstate_account",
    "file_purchase_request",
    "decide_purchase_request",
    "claim_purchase_request",
    "settle_purchase_request",
    "open_misuse_case",
    "review_misuse_case",
    "adjudicate_misuse_case",
    "issue_clawback",
    "file_renewal_review",
    "decide_renewal_review",
    "file_application_denial_appeal",
    "file_clawback_appeal",
    "file_provider_delisting_appeal",
    "decide_appeal",
    "setup_catalog",
    "setup_open_year_and_student",
    "setup_draft_application",
    "setup_submitted_application",
    "setup_eligible_application",
    "setup_denied_application",
    "setup_accepted_award",
    "setup_funded_account",
    "setup_approved_provider",
    "setup_purchase_environment",
    "setup_pending_purchase_request",
    "setup_approved_purchase_request",
    "setup_claimed_purchase_request",
    "setup_settled_purchase_request",
    "setup_misuse_case_under_review",
    "setup_substantiated_case",
    "setup_clawback_issued_case",
    "setup_delisted_provider",
    "setup_next_program_year",
    "setup_renewal_review",
]
