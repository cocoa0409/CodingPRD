"""Draft quality: audits, account suspension, wholesaler cascade, spacing."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_draft_audit,
    assert_instant_equals,
    create_retail_account_payload,
    get_assignment,
    get_success_data,
    make_account,
    make_event,
    post_audit,
    post_critical_audit,
    request_allocation,
    setup_awarded_territory,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestAccountCreation:
    def test_retail_account_create_missing_required_returns_invalid_request(
        self, api, admin_headers
    ):
        """PRD §3.6: "A `BrewerAdmin` registers an account with its `name`,
        the `state_code` that will select its point-of-sale value cap (§3.7),
        the `serving_wholesaler_id` of the wholesaler servicing it, and an
        optional `line_cleaning_frequency_days` — the required draft-line
        cleaning frequency in days, defaulting to 14."
        PRD §2.10: "required fields are present, types and enum members are
        valid, and unknown fields are rejected (`ERR_INVALID_REQUEST`, 400)"

        Design: Corner/entities/retail_account_create_missing_required_returns_invalid_request
        """
        resp = api.create_retail_account(
            {"name": "No Owner Bar", "state_code": "TX"}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuditComputation:
    def test_draft_audit_result_and_counts_computed(self, api):
        """PRD §3.6: "A keg aged at least 90 days is stale; a keg aged at least
        120 days is critical."
        PRD §3.6: "From these measurements the audit derives its `result`:
        `CRITICAL_FAIL` when a critical keg or a critically overdue cleaning is
        present; otherwise `FAIL` when at least one keg is stale or the
        cleaning is overdue; otherwise `PASS`."
        PRD §3.6: "audits that fail — a `FAIL` or `CRITICAL_FAIL` result — do
        not update it."

        Design: Corner/entities/draft_audit_result_and_counts_computed
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Computed Territory")
        account = make_account(wholesaler["id"], name="Computed Bar")
        # 95-day keg (stale, not critical); 4-day line gap (not overdue).
        resp = post_audit(
            account["id"],
            conducted_at="2026-09-01T00:00:00Z",
            line_cleaning_last_at="2026-08-28T00:00:00Z",
            kegs=[{"brand_code": "BUD", "filled_at": "2026-05-29T00:00:00Z",
                   "volume_bbl": 12}],
        )
        audit = validate_success(resp, 201)
        assert_draft_audit(audit)
        assert audit["stale_keg_count"] == 1, "95 days >= 90 but < 120"
        assert audit["critical_keg_flag"] is False
        assert audit["line_cleaning_overdue"] is False
        assert audit["result"] == "FAIL"

        acct = validate_success(api.get_retail_account(account["id"], ADMIN))
        assert acct["status"] == "ACTIVE", "FAIL does not suspend"
        assert acct.get("last_audit_at") is None, (
            "a FAIL audit is accepted but does not update last_audit_at"
        )
        whole = validate_success(api.get_wholesaler(wholesaler["id"], ADMIN))
        assert whole["suspended_account_count"] == 0

    def test_keg_age_exactly_90_counts_stale(self, api):
        """PRD §3.6: "Every keg's age is measured in whole days: the number of
        complete 86400-second days between `filled_at` and `conducted_at`,
        discarding any partial day. A keg aged at least 90 days is stale; a keg
        aged at least 120 days is critical."

        Design: Corner/calculations/keg_age_exactly_90_counts_stale
        """
        _, wholesaler, _ = setup_awarded_territory(territory_name="Keg Territory")
        acct90 = make_account(wholesaler["id"], name="Keg Bar 90")
        acct89 = make_account(wholesaler["id"], name="Keg Bar 89")

        r90 = post_audit(acct90["id"], conducted_at="2026-09-01T00:00:00Z",
                         line_cleaning_last_at="2026-08-28T00:00:00Z",
                         kegs=[{"brand_code": "BUD",
                                "filled_at": "2026-06-03T00:00:00Z",
                                "volume_bbl": 10}])
        a90 = validate_success(r90, 201)
        assert a90["result"] == "FAIL", "age exactly 90 days is stale (>= 90)"
        assert a90["stale_keg_count"] == 1

        r89 = post_audit(acct89["id"], conducted_at="2026-09-01T00:00:00Z",
                         line_cleaning_last_at="2026-08-28T00:00:00Z",
                         kegs=[{"brand_code": "BUD",
                                "filled_at": "2026-06-04T00:00:00Z",
                                "volume_bbl": 10}])
        a89 = validate_success(r89, 201)
        assert a89["result"] == "PASS", "age 89 days is fresh"
        assert a89["stale_keg_count"] == 0


@pytest.fixture
def seven_day_gap(api):
    """Account with a PASS audit at 2026-09-01T00:00:00Z, then a rejected
    604799-second-gap attempt and an accepted 604800-second-gap audit."""
    _, wholesaler, _ = setup_awarded_territory(territory_name="Gap Territory")
    account = make_account(wholesaler["id"], name="Gap Bar")
    first = post_audit(account["id"], conducted_at="2026-09-01T00:00:00Z",
                       line_cleaning_last_at="2026-08-28T00:00:00Z",
                       kegs=[{"brand_code": "BUD",
                              "filled_at": "2026-08-25T00:00:00Z",
                              "volume_bbl": 10}])
    if first.status_code != 201:
        raise AssertionError(f"Setup failed at first audit: {first.text[:300]}")
    too_soon = post_audit(account["id"], conducted_at="2026-09-07T23:59:59Z",
                          line_cleaning_last_at="2026-09-05T00:00:00Z",
                          kegs=[{"brand_code": "BUD",
                                 "filled_at": "2026-09-01T00:00:00Z",
                                 "volume_bbl": 10}])
    on_boundary = post_audit(account["id"], conducted_at="2026-09-08T00:00:00Z",
                             line_cleaning_last_at="2026-09-05T00:00:00Z",
                             kegs=[{"brand_code": "BUD",
                                    "filled_at": "2026-09-01T00:00:00Z",
                                    "volume_bbl": 10}])
    return {"account": account, "first": get_success_data(first),
            "too_soon": too_soon, "on_boundary": on_boundary}


class TestAuditSevenDayBoundary:
    def test_gap_604799_seconds_rejected(self, api, seven_day_gap):
        """PRD §3.6: "A new audit is rejected with `ERR_AUDIT_TOO_SOON` (HTTP
        409) when its `conducted_at` falls less than seven days — 604800
        seconds — after the account's previous accepted audit; a gap of exactly
        604800 seconds is allowed, while a gap of 604799 seconds is rejected."

        Design: Difficulty/boundary_precision_check/audit_min_gap_exact_seven_day_boundary
        """
        env = seven_day_gap
        assert env["first"]["result"] == "PASS"
        validate_error(env["too_soon"], ApiErrorId.ERR_AUDIT_TOO_SOON)

    def test_gap_exactly_604800_seconds_accepted(self, api, seven_day_gap):
        """PRD §3.6: "a gap of exactly 604800 seconds is allowed, while a gap
        of 604799 seconds is rejected. The anchor for this spacing is the
        account's `last_audit_at`, which is null until the account's first
        accepted audit and thereafter carries the `conducted_at` of the most
        recent accepted audit; audits that fail — a `FAIL` or `CRITICAL_FAIL`
        result — do not update it."

        Design: Difficulty/boundary_precision_check/audit_min_gap_exact_seven_day_boundary
        """
        env = seven_day_gap
        third = validate_success(env["on_boundary"], 201)
        assert third["result"] == "PASS"
        acct = validate_success(
            api.get_retail_account(env["account"]["id"], ADMIN))
        assert_instant_equals(acct["last_audit_at"], "2026-09-08T00:00:00Z",
                              label="last_audit_at")


@pytest.fixture
def buffer_semantics(api):
    """Two accounts on one wholesaler; AB1 audited 2026-09-01, AB2 audited
    2026-09-02, then an AB1 re-audit attempt 3 days later."""
    _, wholesaler, _ = setup_awarded_territory(territory_name="Buffer Territory")
    ab1 = make_account(wholesaler["id"], name="Buffer Bar 1")
    ab2 = make_account(wholesaler["id"], name="Buffer Bar 2")
    first = post_audit(ab1["id"], conducted_at="2026-09-01T00:00:00Z",
                       line_cleaning_last_at="2026-08-28T00:00:00Z",
                       kegs=[{"brand_code": "BUD",
                              "filled_at": "2026-08-25T00:00:00Z",
                              "volume_bbl": 10}])
    if first.status_code != 201:
        raise AssertionError(f"Setup failed at AB1 audit: {first.text[:300]}")
    sibling = post_audit(ab2["id"], conducted_at="2026-09-02T00:00:00Z",
                         line_cleaning_last_at="2026-08-30T00:00:00Z",
                         kegs=[{"brand_code": "BUD",
                                "filled_at": "2026-08-28T00:00:00Z",
                                "volume_bbl": 10}])
    reaudit = post_audit(ab1["id"], conducted_at="2026-09-04T00:00:00Z",
                         line_cleaning_last_at="2026-09-02T00:00:00Z",
                         kegs=[{"brand_code": "BUD",
                                "filled_at": "2026-09-01T00:00:00Z",
                                "volume_bbl": 10}])
    return {"ab1": ab1, "ab2": ab2, "sibling": sibling, "reaudit": reaudit}


class TestAuditBufferIsPerAccount:
    def test_sibling_account_audit_untouched_by_buffer(self, api, buffer_semantics):
        """PRD §3.6: "Audits on one account are spaced apart. A new audit is
        rejected with `ERR_AUDIT_TOO_SOON` (HTTP 409) when its `conducted_at`
        falls less than seven days — 604800 seconds — after the account's
        previous accepted audit"

        Design: Difficulty/resource_temporal_overlap/audit_min_gap_buffer_not_overlap_semantics
        """
        env = buffer_semantics
        sibling = validate_success(env["sibling"], 201)
        assert sibling["result"] == "PASS", (
            "the 7-day buffer is scoped per account, not per wholesaler"
        )

    def test_reaudit_three_days_later_rejected(self, api, buffer_semantics):
        """PRD §3.6: "A new audit is rejected with `ERR_AUDIT_TOO_SOON` (HTTP
        409) when its `conducted_at` falls less than seven days — 604800
        seconds — after the account's previous accepted audit; a gap of exactly
        604800 seconds is allowed, while a gap of 604799 seconds is rejected."

        Design: Difficulty/resource_temporal_overlap/audit_min_gap_buffer_not_overlap_semantics
        """
        env = buffer_semantics
        validate_error(env["reaudit"], ApiErrorId.ERR_AUDIT_TOO_SOON)
        acct = validate_success(api.get_retail_account(env["ab1"]["id"], ADMIN))
        assert_instant_equals(acct["last_audit_at"], "2026-09-01T00:00:00Z",
                              label="last_audit_at")


class TestSuspensionAndReinstatement:
    def test_suspension_threshold_trips_at_exactly_three_accounts(self, api):
        """PRD §3.6: "When that increment takes the wholesaler's count from 2
        to 3, the cascade continues up one level: the wholesaler moves
        `APPOINTED` → `SUSPENDED`, every `PENDING` allocation assignment naming
        it is released per §3.5"

        Design: Corner/complexity_layers/suspension_threshold_trips_at_exactly_three_accounts
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Threshold Territory")
        accounts = [make_account(wholesaler["id"], name=f"Threshold Bar {i}")
                    for i in range(1, 4)]
        post_critical_audit(accounts[0]["id"])
        post_critical_audit(accounts[1]["id"])

        mid = validate_success(api.get_wholesaler(wholesaler["id"], ADMIN))
        assert mid["status"] == "APPOINTED"
        assert mid["suspended_account_count"] == 2, "threshold not yet reached"

        post_critical_audit(accounts[2]["id"])
        final = validate_success(api.get_wholesaler(wholesaler["id"], ADMIN))
        assert final["status"] == "SUSPENDED"
        assert final["suspended_account_count"] == 3

    def test_account_reinstates_via_pass_audit_and_count_decrements(self, api):
        """PRD §3.6: "A later `PASS` on a `SERVICE_SUSPENDED` account restores
        it `SERVICE_SUSPENDED` → `ACTIVE` and subtracts one from the count —
        but the wholesaler's own status is not restored by field evidence
        alone."

        Design: Corner/state_machines/account_reinstates_via_pass_audit_and_count_decrements
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Reinstate Territory")
        account = make_account(wholesaler["id"], name="Reinstate Bar")
        post_critical_audit(account["id"], conducted_at="2026-09-01T00:00:00Z")

        suspended = validate_success(api.get_retail_account(account["id"], ADMIN))
        assert suspended["status"] == "SERVICE_SUSPENDED"

        resp = post_audit(
            account["id"], conducted_at="2026-09-09T00:00:00Z",
            line_cleaning_last_at="2026-09-07T00:00:00Z",
            kegs=[{"brand_code": "BUD", "filled_at": "2026-09-02T00:00:00Z",
                   "volume_bbl": 15}])
        audit = validate_success(resp, 201)
        assert audit["result"] == "PASS"

        acct = validate_success(api.get_retail_account(account["id"], ADMIN))
        assert acct["status"] == "ACTIVE"
        assert_instant_equals(acct["last_audit_at"], "2026-09-09T00:00:00Z",
                              label="last_audit_at")

        whole = validate_success(api.get_wholesaler(wholesaler["id"], ADMIN))
        assert whole["suspended_account_count"] == 0
        assert whole["status"] == "APPOINTED", (
            "threshold 3 was never reached; no plan needed"
        )


@pytest.fixture
def critical_cascade(api):
    """GOLD wholesaler with a locked 300-case event (assigned 120) and three
    accounts; three CRITICAL_FAIL audits fire the depth-3 cascade."""
    _, wholesaler, _ = setup_awarded_territory(
        territory_name="Cascade Territory",
        wholesaler_overrides={"tier": "GOLD"},
        agreement_overrides={"brand_scope": ["BUD-LTD"]})
    accounts = [make_account(wholesaler["id"], name=f"Cascade Bar {i}")
                for i in range(1, 4)]
    event = make_event(brand_code="BUD-LTD", total_qty_cases=300)
    resp = request_allocation(event["id"], wholesaler["id"], 200)
    if resp.status_code != 201:
        raise AssertionError(f"Setup failed at request: {resp.text[:300]}")
    locked = api.lock_event(event["id"], ADMIN)
    if locked.status_code != 200:
        raise AssertionError(f"Setup failed at lock: {locked.text[:300]}")
    audits = [post_critical_audit(a["id"]) for a in accounts]
    return {"wholesaler": wholesaler, "accounts": accounts,
            "event_id": event["id"], "locked": get_success_data(locked),
            "audits": audits}


class TestCriticalAuditCascade:
    def test_critical_audits_suspend_accounts_and_wholesaler(
        self, api, critical_cascade
    ):
        """PRD §3.6: "A `CRITICAL_FAIL` on an `ACTIVE` account moves it
        `ACTIVE` → `SERVICE_SUSPENDED` and adds one to the serving wholesaler's
        `suspended_account_count`"
        PRD §3.6: "When that increment takes the wholesaler's count from 2 to
        3, the cascade continues up one level: the wholesaler moves `APPOINTED`
        → `SUSPENDED`, every `PENDING` allocation assignment naming it is
        released per §3.5"

        Design: Difficulty/transitive_cascade/critical_audit_cascade_releases_allocations
        """
        env = critical_cascade
        # post_critical_audit already validated 201 and returns the data dict
        for audit in env["audits"]:
            assert audit["result"] == "CRITICAL_FAIL"
            assert audit["critical_keg_flag"] is True, "121-day keg >= 120"

        for account in env["accounts"]:
            acct = validate_success(api.get_retail_account(account["id"], ADMIN))
            assert acct["status"] == "SERVICE_SUSPENDED"

        wholesaler = validate_success(
            api.get_wholesaler(env["wholesaler"]["id"], ADMIN))
        assert wholesaler["suspended_account_count"] == 3
        assert wholesaler["status"] == "SUSPENDED"

    def test_suspension_releases_pending_assignments(self, api, critical_cascade):
        """PRD §3.5: "When a wholesaler is suspended under the draft-quality
        cascade of §3.6, or terminated as the seller at consummation under
        §3.4, every `PENDING` assignment naming that wholesaler becomes
        `RELEASED`: `released_qty` increases by each released assignment's
        `assigned_qty`, and `pending_qty` decreases by the same amounts."

        Design: Difficulty/transitive_cascade/critical_audit_cascade_releases_allocations
        """
        env = critical_cascade
        locked = env["locked"]
        assert get_assignment(locked, env["wholesaler"]["id"])["assigned_qty"] == 120
        assert locked["pending_qty"] == 120
        assert locked["unassigned_remainder"] == 180

        event = validate_success(api.get_allocation_event(env["event_id"], ADMIN))
        assignment = get_assignment(event, env["wholesaler"]["id"])
        assert assignment["status"] == "RELEASED"
        assert event["released_qty"] == 120
        assert event["pending_qty"] == 0
        assert event["committed_qty"] == 0
        assert event["unassigned_remainder"] == 180
