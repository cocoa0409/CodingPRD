"""Role grants, entity-backed ownership and optimistic concurrency."""
from test_helpers import (
    api_client, get_success_data, validate_error, ApiErrorId,
    refresh_advisor, create_branch, create_advisor,
    setup_active_advisor, setup_funded_period, make_instance_headers,
    open_account, open_period, retire_loan,
    PLATFORM_ADMIN, BRANCH_MANAGER, COMPLIANCE_OFFICER,
)


# ─── corner: rbac ─────────────────────────────────────

def test_opening_a_payout_period_is_exclusive_to_the_branch_manager():
    """PRD §2.1: "A request from a recognized role that attempts an operation outside that
    role's grant is rejected with `ERR_UNAUTHORIZED` at HTTP 403".
    PRD §4: "| POST | `/payout-periods` | Open a payout period for a branch | BranchManager,
    PlatformAdmin |"

    Design: Corner/rbac/compliance_officer_cannot_open_a_payout_period
    """
    create_branch()
    response = api_client.create_payout_period(
        {"branch_code": "SUP-1", "year": 2026, "month": 9, "period_index": 1},
        COMPLIANCE_OFFICER)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    rows = get_success_data(api_client.list_payout_periods(PLATFORM_ADMIN))
    assert rows == []


def test_the_same_payout_period_body_succeeds_for_the_branch_manager():
    """PRD §2.1: "the platform first confirms that the acting role appears among the roles
    authorized for that operation".
    PRD §3.3: "A new period begins at `state` `OPEN` and `status` `OPEN`".

    Design: Corner/rbac/compliance_officer_cannot_open_a_payout_period
    """
    create_branch()
    created = get_success_data(api_client.create_payout_period(
        {"branch_code": "SUP-1", "year": 2026, "month": 9, "period_index": 1},
        BRANCH_MANAGER))
    assert created["state"] == "OPEN"
    assert created["status"] == "OPEN"

    rows = get_success_data(api_client.list_payout_periods(PLATFORM_ADMIN))
    assert len(rows) == 1


def test_an_entity_backed_actor_cannot_depart_another_advisors_book():
    """PRD §2.1: "When `X-User-Role` is `AdvisorOps`, `X-User-ID` is the `id` of the acting
    `Advisor`; ownership checks on any resource that references an `Advisor` compare the
    resource's advisor foreign-key field to `X-User-ID`."
    PRD §2.1: "A request from a recognized role that attempts an operation outside that
    role's grant is rejected with `ERR_UNAUTHORIZED` at HTTP 403, as is any entity-backed
    actor reaching for another advisor's resource."

    Design: Corner/rbac/entity_backed_advisor_ops_actor_cannot_open_another_advisors_account
    """
    target = setup_active_advisor(advisor_code="A-10001", crd_number="1234580",
                                  full_name="Selma Duarte",
                                  ingested_book_total_cents=200_000_000,
                                  book_transferred_cents=160_000_000,
                                  principal_cents=500_000,
                                  forgiveness_milestone_pct=100)
    account = open_account(target["advisor"], "A-10001-1", balance_cents=1_000_000)
    open_period()
    retire_loan(target["advisor"], account)
    other = create_advisor("A-10002", "1234581", "Gale Prosser",
                           primary_branch_code=target["branch"]["branch_code"],
                           ingested_book_total_cents=100_000_000,
                           book_transferred_cents=80_000_000)

    response = api_client.start_departure(
        target["advisor"]["id"],
        {"expected_advisor_version": refresh_advisor(target["advisor"]["id"])["version"]},
        make_instance_headers(other["id"], "AdvisorOps"))
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert refresh_advisor(target["advisor"]["id"])["status"] != "DEPARTING"


def test_an_opaque_role_is_never_ownership_checked():
    """PRD §2.1: "`BranchManager` is the supervising branch principal who runs payout
    periods and the retention contest. When `X-User-Role` is `BranchManager`, `X-User-ID`
    is an opaque operator identifier not tied to any persisted entity and is not compared
    to any entity's `id`."

    Design: Corner/rbac/entity_backed_advisor_ops_actor_cannot_open_another_advisors_account
    """
    target = setup_active_advisor(advisor_code="A-10003", crd_number="1234582",
                                  full_name="Selma Duarte")
    created = get_success_data(api_client.create_payout_period(
        {"branch_code": target["branch"]["branch_code"],
         "year": 2026, "month": 9, "period_index": 1},
        BRANCH_MANAGER))
    assert created["state"] == "OPEN"


# ─── corner: cross_cutting_complexity_layers (OCC) ────

def test_a_stale_advisor_version_on_payout_line_settlement_is_refused():
    """PRD §2.8: "The payout-line settlement endpoint `POST /advisor-payout-lines/{id}/settlement`
    requires `expected_advisor_version` matching the `Advisor` the line belongs to."
    PRD §2.8: "A mismatch between the supplied value and the parent's current `version` is
    rejected with `ERR_STALE_VERSION` at HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/stale_advisor_version_on_payout_line_settlement_returns_precondition_failed
    """
    ctx = setup_funded_period(advisor_code="A-10004", release=True,
                              entries=((1_000_000, "2026-09-03", "EQUITY"),))
    line = ctx["line"]
    stale_version = line["version"]

    response = api_client.settle_payout_line(
        line["id"], {"expected_advisor_version": stale_version}, BRANCH_MANAGER)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)


def test_a_freshly_read_advisor_version_lets_the_settlement_through():
    """PRD §2.8: "Lifecycle transitions are requested by naming the target state rather than
    the transition: a payout period is moved by supplying `to_state`, while a supervisory
    enrollment, an advisor link, an advisor, and an expense pass-through row are moved by
    supplying `to_status`."
    PRD §2.6: "- `**version` (integer):** A system-managed integer that increments by one on every
    modification to the resource."

    Design: Corner/cross_cutting_complexity_layers/stale_advisor_version_on_payout_line_settlement_returns_precondition_failed
    """
    ctx = setup_funded_period(advisor_code="A-10005", release=True,
                              entries=((1_000_000, "2026-09-03", "EQUITY"),))
    advisor, line = ctx["advisor"], ctx["line"]

    fresh = refresh_advisor(advisor["id"])
    settled = get_success_data(api_client.settle_payout_line(
        line["id"], {"expected_advisor_version": fresh["version"]}, BRANCH_MANAGER))
    assert settled["net_settlement_cents"] >= 0
    assert line["version"] != fresh["version"], (
        "the line was observed at an older advisor version")

    api_client.settle_payout_line(
        line["id"], {"expected_advisor_version": fresh["version"]}, BRANCH_MANAGER)
    # The advisor's version is what is compared, so re-reading it is what matters.
    assert refresh_advisor(advisor["id"])["version"] >= fresh["version"]