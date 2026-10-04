"""Corner queue B, section=rbac (3 instances)."""
from test_helpers import (
    RIGHTS,
    create_active_agreement,
    create_agreement_payload,
    create_audit_case_payload,
    create_eligible_athlete,
    create_finalized_statement,
    create_roster_batch_payload,
    create_roster_entry_payload,
    create_season_payload,
    get_success_data,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    TEST_USERS,
    make_league_auditor_headers,
    make_roster_operator_headers,
)

ADMIN = TEST_USERS["licensing_admin_headers"]
LIVEOPS = TEST_USERS["liveops_manager_headers"]


def test_roster_operator_cannot_publish(api):
    """PRD §4: the publish endpoint row authorizes only "RosterReviewer".
    PRD §2.1: "An authenticated caller whose role is not permitted to invoke
    the requested endpoint is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/roster_operator_cannot_publish
    """
    agreement = create_active_agreement()
    athlete, _ = create_eligible_athlete(agreement["id"])
    season = get_success_data(
        api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
    )
    op = make_roster_operator_headers("op-1")
    batch = get_success_data(
        api_client.create_roster_batch(
            create_roster_batch_payload(season["id"], batch_label="RBAC"), op
        )
    )
    get_success_data(
        api_client.add_roster_entry(
            batch["id"], create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                                     overall_rating=80), op
        )
    )
    get_success_data(api_client.validate_roster_batch(batch["id"], op))
    season_now = get_success_data(api_client.get_season(season["id"], LIVEOPS))

    resp = api_client.publish_roster_batch(
        batch["id"], {"expected_season_version": season_now["version"]},
        make_roster_operator_headers("op-2"),  # role denied even for a different id
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_league_auditor_cannot_settle_own_audit(api):
    """PRD §4: the audit-case settle endpoint row authorizes only
    "FinanceController". PRD §3.8: "Settlement belongs to a FinanceController
    who is not the auditor who opened the case."

    Design: Corner/rbac/league_auditor_cannot_settle_own_audit
    """
    agreement = create_active_agreement(audit_window_days=90)
    statement = create_finalized_statement(
        agreement["id"], gross_sales_cents=100000, returns_cents=0,
        pending_sales_cents=0, finalize_clock="2026-09-10T00:00:00Z",
    )
    case = get_success_data(
        api_client.create_audit_case(
            create_audit_case_payload(agreement["id"], statement["id"],
                                      opened_by_role="LEAGUE_AUDITOR"),
            make_league_auditor_headers("league-aud-1"),
        )
    )
    get_success_data(
        api_client.file_audit_findings(
            case["id"], {"finding_delta_cents": 5000},
            make_league_auditor_headers("league-aud-1"),
        )
    )
    resp = api_client.settle_audit_case(
        case["id"], make_league_auditor_headers("league-aud-1")
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    case_after = get_success_data(api_client.get_audit_case(case["id"], ADMIN))
    assert case_after["audit_status"] == "FINDINGS_FILED"


def test_liveops_cannot_create_agreements(api):
    """PRD §4: the create-agreement endpoint row authorizes only
    "LicensingAdmin". PRD §2.1: "An authenticated caller whose role is not
    permitted to invoke the requested endpoint is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/liveops_cannot_create_agreements
    """
    resp = api_client.create_agreement(
        create_agreement_payload(licensor_name="X"), LIVEOPS
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
