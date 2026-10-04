"""
Composite setup helpers for multi-step test prerequisites.

Every helper drives the system exclusively through the declared API endpoints and
uses get_success_data() (the lenient validator) internally, so a broken
precondition surfaces as a clear "Setup step failed" error rather than as a
confusing assertion failure inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_account_device_link_payload,
    create_appeal_outcome_payload,
    create_decision_payload,
    create_device_cluster_payload,
    create_evidence_payload,
    create_incident_payload,
    create_platform_policy_payload,
    create_regulator_report_payload,
    create_trip_payload,
)
from .constants import (AGGRAVATOR_LEVELS, SEVERITY_BASE_LEVEL, TEST_DEFAULTS)
from .test_users import TEST_USERS, make_driver_headers, make_rider_headers

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]
LIAISON = TEST_USERS["liaison_headers"]
BACKGROUND_REVIEWER = TEST_USERS["background_reviewer_headers"]

REGION = TEST_DEFAULTS["REGION"]
CLOCK = TEST_DEFAULTS["CLOCK"]


def shift_iso(iso_timestamp: str, days: float) -> str:
    """Shift an ISO 8601 UTC instant by a number of days.

    Used by tests that must move the logical clock to a boundary the server
    stamped from a derivation the PRD does not pin (an anchored cadence date).
    """
    from datetime import datetime, timedelta, timezone

    parsed = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    shifted = parsed.astimezone(timezone.utc) + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _email(handle: str) -> str:
    return f"{handle}@example.com"


def _name(handle: str) -> str:
    return " ".join(part.capitalize() for part in handle.split("."))


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(current_utc, headers=None):
    """Set the logical clock; the server never falls back to wall-clock time."""
    res = api_client.set_current_utc(current_utc, headers or ADMIN)
    return get_success_data(res)


# ─── Tier 1: single-entity creation ──────────────────────────────────────────

def setup_policy(region_code=REGION, sd_floor_severity="S4", **overrides) -> dict:
    """Publish the region's threshold record."""
    payload = create_platform_policy_payload(
        region_code=region_code, sd_floor_severity=sd_floor_severity, **overrides
    )
    return get_success_data(api_client.create_platform_policy(payload, ADMIN))


def setup_account(account_type="RIDER", region_code=REGION, handle="test.account",
                  **overrides) -> dict:
    """Provision an account of the given type in the given region."""
    payload = create_account_payload(
        account_type=account_type,
        home_region_code=region_code,
        legal_name=overrides.pop("legal_name", _name(handle)),
        contact_email=overrides.pop("contact_email", _email(handle)),
        **overrides,
    )
    return get_success_data(api_client.create_account(payload, ADMIN))


def setup_cluster(region_code=REGION, cluster_key="dc-test", **overrides) -> dict:
    """Create a device cluster; any supplied aggregate is ignored."""
    payload = create_device_cluster_payload(
        cluster_key=cluster_key, region_code=region_code, **overrides
    )
    return get_success_data(api_client.create_device_cluster(payload, ADMIN))


def setup_link(account_id, cluster_id, fingerprint_hash="fp-test", headers=None) -> dict:
    """Attribute an account observation to a cluster."""
    payload = create_account_device_link_payload(
        account_id, cluster_id, fingerprint_hash=fingerprint_hash
    )
    return get_success_data(
        api_client.create_account_device_link(payload, headers or INVESTIGATOR)
    )


def setup_trip(rider_account_id, driver_account_id, region_code=REGION,
               requested_at=TEST_DEFAULTS["TRIP_REQUESTED_AT"], **overrides) -> dict:
    """Request a trip between a rider and a driver."""
    payload = create_trip_payload(
        rider_account_id,
        driver_account_id,
        region_code=region_code,
        requested_at=requested_at,
        **overrides,
    )
    return get_success_data(api_client.create_trip(payload, ADMIN))


def setup_incident(account_id, incident_category="PHYSICAL_ASSAULT",
                   reporter_type="RIDER", reporter_account_id=None,
                   headers=None, **overrides):
    """File an incident report. Returns the raw response.

    reporter_account_id is populated automatically for RIDER and DRIVER
    reporters and omitted entirely for THIRD_PARTY, matching the conditional
    pairing the platform enforces.
    """
    payload = create_incident_payload(account_id, incident_category=incident_category,
                                      reporter_type=reporter_type, **overrides)
    if reporter_type in ("RIDER", "DRIVER"):
        payload["reporter_account_id"] = reporter_account_id or account_id
    return api_client.create_incident(payload, headers or INVESTIGATOR)


def make_incident(account_id, incident_category="PHYSICAL_ASSAULT",
                  reporter_type="RIDER", reporter_account_id=None, **overrides) -> dict:
    """File an incident and return its representation."""
    return get_success_data(
        setup_incident(account_id, incident_category=incident_category,
                       reporter_type=reporter_type,
                       reporter_account_id=reporter_account_id, **overrides)
    )


def setup_evidence(incident_id, evidence_type, evidence_weight,
                   source_entity_id=None, headers=None):
    """Gather one evidence item. Returns the raw response."""
    payload = create_evidence_payload(evidence_type=evidence_type,
                                      evidence_weight=evidence_weight)
    if source_entity_id is not None:
        payload["source_entity_id"] = source_entity_id
    return api_client.create_evidence(incident_id, payload, headers or INVESTIGATOR)


def make_evidence(incident_id, evidence_type, evidence_weight, source_entity_id=None) -> dict:
    return get_success_data(
        setup_evidence(incident_id, evidence_type, evidence_weight, source_entity_id)
    )


def _trip_sourced_type(evidence_type):
    return evidence_type in ("TRIP_DATA", "IN_APP_MESSAGE")


def _resolve_trip_source(incident, spec, index):
    """PRD §3.3: a `TRIP_DATA` / `IN_APP_MESSAGE` item must name a trip.

    The helper derives a PRD-legal trip rather than leaving the optional
    `source_entity_id` null, because a trip-sourced item without a trip is not a
    well-formed request against the endpoint. The trip must involve both the
    incident's subject account and its reported counterparty (§3.3); the setup
    helper files its incidents self-reported, so the account is both and a trip
    between the account and itself satisfies the guard.
    """
    if spec.get("source_entity_id"):
        return spec["source_entity_id"]
    if incident.get("referenced_trip_id"):
        return incident["referenced_trip_id"]
    subject_id = incident.get("account_id")
    counterparty_id = incident.get("reporter_account_id") or subject_id
    trip = setup_trip(subject_id, counterparty_id, in_app_message_count=1)
    return trip["id"]


def _hold_floor_aggravators(incident_category):
    """Codes that lift a category to the S3 hold floor of PRD §3.2.

    An incident may only be held while its `severity` is `S3` or `S4`, so a
    fixture that walks a low-base category through the investigation must supply
    the aggravator codes the intake derivation needs to reach that band. The
    category itself is left alone, so category-conditioned rules (the decision
    floor ladder, the reportable-category test) are unaffected.
    """
    base = SEVERITY_BASE_LEVEL.get(incident_category, 1)
    needed = max(0, 3 - base)
    return list(AGGRAVATOR_LEVELS)[:needed]


def gather_and_accept(incident_id, evidence_specs) -> list:
    """Gather each spec, accept it, and return the accepted evidence rows.

    Reaching PENDING_DECISION requires at least one INCLUDED row and no PENDING
    row left; this helper always accepts, so the last call advances the incident.
    """
    incident = get_incident(incident_id)
    rows = []
    for index, spec in enumerate(evidence_specs):
        source_entity_id = spec.get("source_entity_id")
        if _trip_sourced_type(spec["evidence_type"]) and source_entity_id is None:
            source_entity_id = _resolve_trip_source(incident, spec, index)
        row = make_evidence(
            incident_id,
            spec["evidence_type"],
            spec["evidence_weight"],
            source_entity_id,
        )
        rows.append(row)
    for row in rows:
        get_success_data(
            api_client.accept_evidence(incident_id, row["id"], True, INVESTIGATOR)
        )
    return rows


def make_prior_incidents(account_id, count, incident_category="HARASSMENT",
                         start="2026-09-01T00:00:00Z", step_days=1, **overrides) -> list:
    """File `count` incidents that are strictly older than the subject incident.

    PRD §3.1 freezes `prior_incident_count_at_intake` from the account's *other*
    `SafetyIncident` rows created **strictly before** this incident's
    `created_at`. The logical clock supplies that ordering key, so the helper
    steps it between filings; filing several reports at one frozen instant would
    leave the frozen prior count at zero however many rows exist.
    """
    rows = []
    for index in range(count):
        set_clock(shift_iso(start, index * step_days))
        rows.append(make_incident(account_id, incident_category=incident_category,
                                  **overrides))
    return rows


def setup_incident_in_state(account_id, incident_category="PHYSICAL_ASSAULT",
                            evidence_specs=None, hold=True, reporter_type="RIDER",
                            **overrides):
    """Active account + incident walked to PENDING_DECISION.

    Returns (incident, evidence_rows). With hold=False the incident stays OPEN
    and no evidence is gathered.

    The incident is filed self-reported by default: PRD §3.3 requires a
    `TRIP_DATA` / `IN_APP_MESSAGE` item to involve both the incident's subject
    account and its *reported counterparty account*, and a self-report makes the
    subject account its own counterparty, so trip data the helper draws for that
    account is admissible without inventing a second identity.

    The hold edge exists only for an `S3`/`S4` incident (§3.2), so when the
    caller has not supplied aggravator codes the helper lifts a low-base
    category to the hold floor with the intake aggravator codes. The category
    itself is untouched.
    """
    if hold and not overrides.get("aggravator_codes"):
        overrides["aggravator_codes"] = _hold_floor_aggravators(incident_category)
    incident = make_incident(account_id, incident_category=incident_category,
                             reporter_type=reporter_type, **overrides)
    rows = []
    if hold:
        get_success_data(api_client.hold_incident(incident["id"], INVESTIGATOR))
        specs = evidence_specs if evidence_specs is not None else [
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "LAW_ENFORCEMENT_CONTACT", "evidence_weight": "DISPOSITIVE"},
        ]
        rows = gather_and_accept(incident["id"], specs)
        incident = get_success_data(api_client.get_incident(incident["id"], INVESTIGATOR))
    return incident, rows


def decide(incident_id, decision_category, expected_incident_version, basis=None):
    """Commit a graduated decision."""
    payload = create_decision_payload(decision_category, expected_incident_version)
    if basis:
        payload["decision_basis"] = basis
    return api_client.commit_decision(incident_id, payload, INVESTIGATOR)


def decide_now(incident_id, decision_category, expected_incident_version, basis=None) -> dict:
    return get_success_data(
        decide(incident_id, decision_category, expected_incident_version, basis)
    )


def file_appeal(incident_id, headers=None):
    return api_client.file_appeal(incident_id, headers or APPEAL_REVIEWER)


def commit_appeal_outcome(incident_id, adjudication, expected_incident_version,
                          commit_early=False, headers=None):
    payload = create_appeal_outcome_payload(
        adjudication, expected_incident_version, commit_early=commit_early
    )
    return api_client.commit_appeal_outcome(incident_id, payload,
                                            headers or APPEAL_REVIEWER)


# ─── Tier 2: reads ───────────────────────────────────────────────────────────

def get_account(account_id) -> dict:
    return get_success_data(api_client.get_account(account_id, ADMIN))


def get_cluster(cluster_id) -> dict:
    return get_success_data(api_client.get_device_cluster(cluster_id, OPERATIONS_LEAD))


def get_incident(incident_id) -> dict:
    return get_success_data(api_client.get_incident(incident_id, INVESTIGATOR))


def get_link(link_id) -> dict:
    return get_success_data(
        api_client.get_account_device_link(link_id, OPERATIONS_LEAD)
    )


def list_account_actions(account_id) -> list:
    return get_success_data(
        api_client.list_account_enforcement_actions(account_id, OPERATIONS_LEAD)
    )


def list_incident_actions(incident_id) -> list:
    return get_success_data(
        api_client.list_enforcement_actions(INVESTIGATOR, params={"incident_id": incident_id})
    )


def first_action_for_incident(incident_id) -> dict:
    actions = list_incident_actions(incident_id)
    assert actions, f"Setup failed: no EnforcementAction for incident {incident_id}"
    return actions[0]


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────

def setup_decided_case(account_handle="case.subject", account_type="DRIVER",
                       region_code=REGION, incident_category="PHYSICAL_ASSAULT",
                       decision_category="DEACTIVATED", evidence_specs=None,
                       policy_overrides=None, **incident_overrides):
    """Policy + account + incident walked to a committed decision.

    Returns (account, incident, enforcement_action).
    """
    setup_policy(region_code=region_code, **(policy_overrides or {}))
    account = setup_account(account_type=account_type, region_code=region_code,
                            handle=account_handle)
    incident, _ = setup_incident_in_state(
        account["id"], incident_category=incident_category,
        evidence_specs=evidence_specs, **incident_overrides
    )
    decided = decide_now(incident["id"], decision_category, incident["version"])
    return get_account(account["id"]), decided, first_action_for_incident(incident["id"])


def setup_deactivated_account(account_handle="deact.subject", region_code=REGION,
                              incident_category="PHYSICAL_ASSAULT",
                              policy_overrides=None, evidence_specs=None):
    """A deactivated driver account with one DEACTIVATED enforcement action."""
    return setup_decided_case(
        account_handle=account_handle, region_code=region_code,
        incident_category=incident_category, decision_category="DEACTIVATED",
        evidence_specs=evidence_specs, policy_overrides=policy_overrides,
    )


def setup_restricted_account(account_handle="restrict.subject", region_code=REGION,
                             incident_category="PHYSICAL_ASSAULT",
                             policy_overrides=None, evidence_specs=None):
    """A restricted driver account with one ACTIVE RESTRICTED action."""
    return setup_decided_case(
        account_handle=account_handle, region_code=region_code,
        incident_category=incident_category, decision_category="RESTRICTED",
        evidence_specs=evidence_specs or [
            {"evidence_type": "TRIP_DATA", "evidence_weight": "DISPOSITIVE"},
            {"evidence_type": "EXTERNAL_RECORD", "evidence_weight": "DISPOSITIVE"},
        ],
        policy_overrides=policy_overrides,
    )


def setup_appeal_pending(account_handle="appeal.subject", region_code=REGION,
                         incident_category="PHYSICAL_ASSAULT", policy_overrides=None,
                         evidence_specs=None):
    """A deactivated account whose single appeal has been filed.

    Returns (account, incident, enforcement_action).
    """
    account, incident, action = setup_deactivated_account(
        account_handle=account_handle, region_code=region_code,
        incident_category=incident_category, policy_overrides=policy_overrides,
        evidence_specs=evidence_specs,
    )
    get_success_data(file_appeal(incident["id"]))
    incident = get_incident(incident["id"])
    return get_account(account["id"]), incident, first_action_for_incident(incident["id"])


def register_completed_trip(account_id, region_code=REGION,
                            requested_at=TEST_DEFAULTS["TRIP_REQUESTED_AT"],
                            handle=None):
    """Request, start and complete a trip credited to `account_id`.

    PRD §2.6 credits a trip to both member accounts, and §3.9 permits the
    completion signal only for a driver whose account is `ACTIVE` or
    `RESTRICTED`. A deactivated account therefore earns the credit as the
    *rider*, with a fresh `ACTIVE` counterparty driving.
    """
    counterparty = setup_account(account_type="DRIVER", region_code=region_code,
                                 handle=handle or ("trip.driver." + str(abs(hash(account_id)) % 100000)))
    trip = setup_trip(account_id, counterparty["id"], region_code=region_code,
                      requested_at=requested_at)
    driver_headers = make_driver_headers(counterparty["id"])
    get_success_data(api_client.complete_start_trip(trip["id"], driver_headers))
    return get_success_data(api_client.complete_trip(trip["id"], driver_headers))


# ─── Tier 4: accumulation / threshold targeting ──────────────────────────────

def setup_cluster_with_members(cluster_key="dc-members", region_code=REGION,
                               member_handles=("m1", "m2"), policy_overrides=None):
    """Policy + cluster + N driver members each linked to the cluster.

    Returns (cluster, [account, ...], [link, ...]).
    """
    setup_policy(region_code=region_code, **(policy_overrides or {}))
    cluster = setup_cluster(region_code=region_code, cluster_key=cluster_key)
    accounts, links = [], []
    for index, handle in enumerate(member_handles):
        account = setup_account(account_type="DRIVER", region_code=region_code, handle=handle)
        link = setup_link(account["id"], cluster["id"], fingerprint_hash=f"{cluster_key}-fp-{index}")
        accounts.append(account)
        links.append(link)
    return get_cluster(cluster["id"]), accounts, links


def drive_cluster_to_watchlist(cluster_id, account, incident_category="PHYSICAL_ASSAULT",
                               decision_category="RESTRICTED"):
    """Commit one deactivating decision for a cluster member.

    The mandatory-report cascade escalates the cluster OPEN -> WATCHLIST once
    the threshold is crossed. Returns the decided incident.
    """
    incident, _ = setup_incident_in_state(account["id"], incident_category=incident_category)
    return decide_now(incident["id"], decision_category, incident["version"])


def setup_background_check_in_review(account_id):
    """Move the driver account's synthesized review into the review state.

    The acknowledgement precondition is date-based: the clock must have reached
    the review's due date minus the region's acknowledgement deadline. The
    synthesized review's due date is not pinned by the PRD, so it is read off
    the row the server stamped and the clock is shifted just inside the window.

    Returns the acknowledged review row.
    """
    checks = get_success_data(
        api_client.list_account_background_checks(account_id, BACKGROUND_REVIEWER)
    )
    assert checks, f"Setup failed: no BackgroundCheck synthesized for account {account_id}"
    check = checks[0]

    # The acknowledgement precondition is a date: the window opens at the
    # review's due instant minus the region's acknowledgement deadline, so the
    # probes walk *into* that window rather than far outside it.
    for probe_days in (5, 2, 1):
        set_clock(shift_iso(check["scheduled_due_at"], -probe_days))
        candidate = api_client.acknowledge_background_check(check["id"], BACKGROUND_REVIEWER)
        if 200 <= candidate.status_code < 300:
            return get_success_data(candidate), candidate
    raise AssertionError(
        f"Setup failed: the synthesized review {check['id']} could not be moved into review"
    )


def setup_banned_cluster(region_code=REGION, cluster_key="dc-banned",
                         account_handle="banned.member", policy_overrides=None):
    """Drive a cluster all the way to BANNED through the escalation cascade.

    Returns (cluster, member_account, member_link).
    """
    overrides = {"cluster_watchlist_threshold": 1, "cluster_purge_threshold": 1,
                 "escalation_enabled": True}
    overrides.update(policy_overrides or {})
    cluster, accounts, links = setup_cluster_with_members(
        cluster_key=cluster_key, region_code=region_code,
        member_handles=(account_handle, account_handle + ".second"),
        policy_overrides=overrides,
    )
    # The first deactivating decision carries the cluster OPEN -> WATCHLIST; the
    # purge edge reads a cluster that is *already* WATCHLIST, so a second
    # clustered decision is what takes it to BANNED.
    drive_cluster_to_watchlist(cluster["id"], accounts[0])
    drive_cluster_to_watchlist(cluster["id"], accounts[1])
    return get_cluster(cluster["id"]), accounts[0], links[0]


# ─── Tier 5: finalization / terminal state ───────────────────────────────────

def setup_overturned_case(account_handle="overturn.subject", region_code=REGION,
                          commit_clock="2026-11-15T00:00:00Z",
                          reviewer_user_id="ar-rowan"):
    """Deactivated account + one completed rehabilitation trip + a committed overturn.

    Returns (account_before, account_after, incident, action).
    """
    setup_policy(region_code=region_code, appeal_window_days=30)
    account = setup_account(account_type="DRIVER", region_code=region_code, handle=account_handle)
    baseline = get_account(account["id"])

    incident, _ = setup_incident_in_state(account["id"])
    decided = decide_now(incident["id"], "DEACTIVATED", incident["version"])
    after_decision = get_account(account["id"])

    register_completed_trip(account["id"], region_code=region_code,
                            requested_at="2026-10-02T00:00:00Z")

    get_success_data(file_appeal(decided["id"]))
    appealed = get_incident(decided["id"])

    set_clock(commit_clock)
    outcome = get_success_data(
        commit_appeal_outcome(appealed["id"], "OVERTURNED", appealed["version"],
                              headers=build_reviewer_headers(reviewer_user_id))
    )
    return baseline, after_decision, outcome, first_action_for_incident(decided["id"])


def build_reviewer_headers(user_id):
    from .test_users import make_appeal_reviewer_headers
    return make_appeal_reviewer_headers(user_id)


def build_rider_headers(account_id):
    return make_rider_headers(account_id)


def build_driver_headers(account_id):
    return make_driver_headers(account_id)


def setup_regulator_report_backlog(incident_id, region_code=REGION, **overrides) -> dict:
    """Queue a RegulatorReport directly through the liaison surface."""
    payload = create_regulator_report_payload(incident_id, **overrides)
    return get_success_data(api_client.create_regulator_report(payload, LIAISON))