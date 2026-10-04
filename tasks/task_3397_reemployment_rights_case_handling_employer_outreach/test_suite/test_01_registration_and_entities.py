"""Registration and single-entity read corners: members, employers, service
periods, statements of support, and the employer's derived case counters."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_employer,
    assert_instant,
    assert_service_member,
    assert_service_period,
    assert_statement_of_support,
    create_case,
    create_employer,
    create_member,
    create_service_period,
    create_statement,
    member_payload,
    make_employer_headers,
    make_service_member_headers,
    read_employer,
    set_clock,
    sign_statement,
    transition_case,
    validate_success,
)


def test_member_create_returns_every_declared_field(api: ApiClient, anonymous_headers: dict):
    """PRD §3.1: "An `Anonymous` caller registers a service member by supplying a `full_name`, a contact `email`, a uniformed `branch` — one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINES`, `COAST_GUARD`, or `SPACE_FORCE` — and a reserve `component`, one of `ARMY_RESERVE`, `NAVY_RESERVE`, `MARINE_RESERVE`, `ARMY_GUARD`, or `AIR_GUARD`."
    PRD §2.4: "Before any coordinator has set it, the logical clock reads exactly `2026-09-01T00:00:00Z`."
    PRD §2.5: "`version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency rules of §2.6."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/member_create_returns_every_declared_field
    """
    set_clock(api)
    response = api.create_member(member_payload(), anonymous_headers)
    assert response.status_code == 201, f"member registration must return 201, got {response.status_code}: {response.text}"
    body = response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    member = validate_success(response, 201)
    assert_service_member(member)
    assert member["full_name"] == "Rae Torres"
    assert member["email"] == "rae@example.com"
    assert member["branch"] == "ARMY"
    assert member["component"] == "ARMY_RESERVE"
    assert_instant(member["created_at"], "2026-09-01T00:00:00Z", "ServiceMember.created_at")
    assert member["version"] == 1, f"a freshly created member carries version 1, got {member['version']}"


def test_employer_get_round_trips_all_fields(api: ApiClient, coordinator_headers: dict):
    """PRD §3.1: "Employers, by contrast, are onboarded only by a `ProgramCoordinator`, who records the employer's `legal_name`, its industry `sector` — `MANUFACTURING`, `RETAIL`, `HEALTHCARE`, `LOGISTICS`, `GOVERNMENT`, `CONSTRUCTION`, `HOSPITALITY`, or `TECHNOLOGY`, the attribute trend reporting groups by — and its headcount `size_tier` of `SMALL`, `MEDIUM`, or `LARGE`."
    PRD §3.1: "A freshly onboarded employer starts with `resolved_case_count` and `open_case_count` at zero and `recognition_tier` at `NONE`; all three are derived values maintained by the system thereafter."

    Design: Corner/entities/employer_get_round_trips_all_fields
    """
    set_clock(api)
    employer = create_employer(api, legal_name="Cascade Outfitters Inc", sector="RETAIL", size_tier="MEDIUM")

    response = api.get_employer(employer["id"], coordinator_headers)
    fetched = validate_success(response)
    assert_employer(fetched)
    assert fetched["legal_name"] == "Cascade Outfitters Inc"
    assert fetched["sector"] == "RETAIL"
    assert fetched["size_tier"] == "MEDIUM"
    assert fetched["resolved_case_count"] == 0
    assert fetched["open_case_count"] == 0
    assert fetched["recognition_tier"] == "NONE"


def test_service_period_is_immutable_without_version_or_update(
    api: ApiClient, coordinator_headers: dict
):
    """PRD §2.5: "Audit-grade records — `ServicePeriod`, `CaseNote`, `EligibilityAnalysis`, `BenefitAssessment`, and `TrainingRecord` — carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because these records are append-only statements of fact."
    PRD §3.2: "From these the system derives `duration_days`, the whole-day count from start to end, which stays null while the period is ongoing, and `chargeable`, which is true for every orders category except `NATIONAL_EMERGENCY` and `PRESIDENTIAL_CALLUP`"

    Design: Corner/entities/service_period_is_immutable_without_version_or_update
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)

    response = api.create_service_period(
        {
            "member_id": member["id"],
            "employer_id": employer["id"],
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-02-01T00:00:00Z",
            "orders_type": "DRILL",
        },
        make_service_member_headers(member["id"]),
    )
    period = validate_success(response, 201)
    assert_service_period(period)
    assert period["duration_days"] == 31, f"2026-01-01 to 2026-02-01 spans 31 whole days, got {period['duration_days']}"
    assert period["chargeable"] is True
    assert "version" not in period and "updated_at" not in period

    listing = validate_success(api.list_member_service_periods(member["id"], coordinator_headers))
    assert isinstance(listing, list) and len(listing) == 1
    assert_service_period(listing[0])
    assert listing[0]["id"] == period["id"]


def test_statement_create_defaults_term_months_to_24(api: ApiClient):
    """PRD §3.9: "An employer — acting for itself, so the payload's `employer_id` must equal its `X-User-ID` — or a coordinator pledges a statement of support, naming the `signer_name` and `signer_title` and optionally a `term_months` pledge term that defaults to 24 months."
    PRD §3.9: "The pledge rests in `PLEDGED` until the employer or a coordinator signs it, `PLEDGED → SIGNED`, which stamps `signed_on` with the logical clock and computes `expires_on` as the term length after signing."

    Design: Corner/entities/statement_create_defaults_term_months_to_24
    """
    set_clock(api)
    employer = create_employer(api)
    statement = create_statement(api, employer["id"])
    assert_statement_of_support(statement)
    assert statement["term_months"] == 24, f"omitted term_months defaults to 24, got {statement['term_months']}"
    assert statement["status"] == "PLEDGED"

    signed = sign_statement(api, statement["id"], employer["id"])
    assert signed["status"] == "SIGNED"
    assert_instant(signed["signed_on"], "2026-09-01T00:00:00Z", "StatementOfSupport.signed_on")
    assert_instant(signed["expires_on"], "2028-09-01T00:00:00Z", "StatementOfSupport.expires_on")


def test_employer_open_case_count_is_computed_not_stored(api: ApiClient):
    """PRD §3.1: "A freshly onboarded employer starts with `resolved_case_count` and `open_case_count` at zero and `recognition_tier` at `NONE`; all three are derived values maintained by the system thereafter."
    PRD §3.7: "Withdrawal moves the case from `INTAKE`, `TRIAGE`, `ASSIGNED`, `IN_MEDIATION`, `AWAITING_RESPONSE`, or `ESCALATION_PENDING` into `CLOSED_WITHDRAWN` and always stamps `closed_at`."

    Design: Corner/entities/employer_open_case_count_is_computed_not_stored
    """
    set_clock(api)
    employer = create_employer(api)
    member = create_member(api)
    assert read_employer(api, employer["id"])["open_case_count"] == 0

    case = create_case(api, member["id"], employer["id"], issue_type="DISCRIMINATION",
                       description="Passed over for drill weekends")
    after_filing = read_employer(api, employer["id"])
    assert after_filing["open_case_count"] == 1, f"one filed case must count as open, got {after_filing['open_case_count']}"

    transition_case(api, case["id"], "CLOSED_WITHDRAWN", make_service_member_headers(member["id"]))
    after_withdrawal = read_employer(api, employer["id"])
    assert after_withdrawal["open_case_count"] == 0, f"a withdrawn case no longer counts as open, got {after_withdrawal['open_case_count']}"
    assert after_withdrawal["resolved_case_count"] == 0
