"""Composite setup helpers.

Every helper drives the system from an empty database (the harness restarts the
server before each test) into a named precondition using only endpoints the PRD
declares, and returns the created resources so a test can assert on them.

Identity threading: for the entity-backed ``Moderator`` role the ``X-User-ID``
header is the acting Moderator *row* id, so helpers resolve the row and pass it
through :func:`make_moderator_headers`. The ``Account`` role is entity-backed on
the account id itself, so account ids are carried through directly.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_BASE,
    PROTEST_MORATORIUM_DAYS,
    SITEWIDE_FLOOR_BAND,
)
from .test_users import (
    make_account_headers,
    make_anonymous_headers,
    make_content_reviewer_headers,
    make_moderator_headers,
    make_platform_admin_headers,
    make_succession_auditor_headers,
)

ADMIN = make_platform_admin_headers()
ANONYMOUS = make_anonymous_headers()


# =============================================================================
# Clock
# =============================================================================

def set_clock(current_utc):
    """Advance the logical clock. Returns the payload the server echoes."""
    response = api_client.set_clock(current_utc, ADMIN)
    return get_success_data(response)


def clock_base():
    return set_clock(CLOCK_BASE)


# =============================================================================
# Communities
# =============================================================================

def create_community(name, founder_account_id="mod-alpha", description=None,
                     is_over_18=None, role="Account"):
    """Create a community and return its representation.

    The creating account becomes the first ACTIVE top moderator.
    """
    payload = {
        "name": name,
        "description": description if description is not None else f"{name} community",
    }
    if is_over_18 is not None:
        payload["is_over_18"] = is_over_18
    if role == "PlatformAdmin":
        headers = ADMIN
    else:
        headers = make_account_headers(founder_account_id)
    response = api_client.create_community(payload, headers)
    return get_success_data(response)


def get_community(community_id, role="PlatformAdmin", user_id=None):
    if role == "PlatformAdmin":
        headers = ADMIN
    elif role == "Moderator":
        headers = make_moderator_headers(user_id)
    else:
        headers = ANONYMOUS
    return get_success_data(api_client.get_community(community_id, headers))


def list_communities(params=None, role="PlatformAdmin"):
    headers = ADMIN if role == "PlatformAdmin" else ANONYMOUS
    return api_client.list_communities(headers, params=params)


def community_version(community_id):
    return get_community(community_id)["version"]


# =============================================================================
# Community rules
# =============================================================================

def author_rule(community_id, rule_code="R-1", rule_text="Be civil", rule_band=1,
                is_sitewide_floor=False, actor_account_id="mod-alpha",
                actor_moderator_id=None, expected_community_version=None):
    if expected_community_version is None:
        expected_community_version = community_version(community_id)
    payload = {
        "rule_code": rule_code,
        "rule_text": rule_text,
        "rule_band": rule_band,
        "is_sitewide_floor": is_sitewide_floor,
        "expected_community_version": expected_community_version,
    }
    headers = make_moderator_headers(actor_moderator_id or actor_account_id)
    return get_success_data(api_client.create_rule(community_id, payload, headers))


def list_rules(community_id, params=None):
    return api_client.list_rules(community_id, ADMIN, params=params)


def rule_rows(community_id, params=None):
    data, _meta = _paginated_pair(list_rules(community_id, params=params))
    return data


def escalate_rule(community_id, rule_id, escalation_note="Conflicts with the sitewide floor",
                  actor_moderator_id=None):
    payload = {"rule_id": rule_id, "escalation_note": escalation_note}
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.escalate_rule(community_id, payload, headers))


# =============================================================================
# Moderator team
# =============================================================================

def list_moderators(community_id, params=None, role="PlatformAdmin", user_id=None):
    if role == "PlatformAdmin":
        headers = ADMIN
    elif role == "Moderator":
        headers = make_moderator_headers(user_id)
    elif role == "ContentReviewer":
        headers = make_content_reviewer_headers()
    else:
        headers = make_succession_auditor_headers()
    return api_client.list_moderators(community_id, headers, params=params)


def moderator_rows(community_id, params=None):
    response = list_moderators(community_id, params=params)
    data, _meta = _paginated_pair(response)
    return data


def _first_top_moderator_id(community_id):
    rows = moderator_rows(community_id, params={"status": "ACTIVE"})
    for row in rows:
        if row.get("moderator_role") == "TOP_MODERATOR":
            return row["id"]
    return rows[0]["id"]


def founding_moderator(community_id):
    """The synthesized top moderator row of the founding account."""
    rows = moderator_rows(community_id)
    for row in rows:
        if row.get("top_rank") == 1:
            return row
    return rows[0]


def find_moderator(community_id, account_id):
    for row in moderator_rows(community_id):
        if row.get("moderator_account_id") == account_id:
            return row
    raise AssertionError(f"Setup failed: no moderator row for account {account_id!r}")


def appoint_moderator(community_id, account_id, moderator_role="REGULAR_MODERATOR",
                      display_name=None, actor_moderator_id=None,
                      expected_community_version=None):
    """Appoint a moderator. Returns the new row."""
    if expected_community_version is None:
        expected_community_version = community_version(community_id)
    payload = {
        "moderator_account_id": account_id,
        "display_name": display_name or account_id,
        "moderator_role": moderator_role,
        "expected_community_version": expected_community_version,
    }
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_moderator(community_id, payload, headers))


def setup_community_with_team(moderator_accounts, name="r/Alpha",
                              founder_account_id=None, is_over_18=None,
                              description=None, roles=None):
    """Create a community and appoint each account in ``moderator_accounts``.

    ``moderator_accounts`` names the *extra* moderators; the founding account is
    always the first ACTIVE top moderator. Returns ``(community, [rows])`` where
    rows are ordered founder-first.
    """
    founder = founder_account_id or (moderator_accounts[0] if moderator_accounts
                                     and roles and roles[0] == "TOP" else "mod-alpha")
    if founder_account_id is None and moderator_accounts and founder == moderator_accounts[0]:
        # The founder is the first listed account and does not need appointment.
        remaining = moderator_accounts[1:]
    else:
        remaining = moderator_accounts
    community = create_community(name, founder_account_id=founder,
                                 description=description, is_over_18=is_over_18)
    rows = [founding_moderator(community["id"])]
    for index, account_id in enumerate(remaining):
        role = "REGULAR_MODERATOR"
        if roles and index + 1 < len(roles) and roles[index + 1] == "TOP":
            role = "TOP_MODERATOR"
        row = appoint_moderator(community["id"], account_id, moderator_role=role,
                                actor_moderator_id=rows[0]["id"])
        rows.append(row)
    return community, rows


def resign(community_id, moderator_id, moderator_version=None, actor_moderator_id=None):
    if moderator_version is None:
        moderator_version = _moderator_version(community_id, moderator_id)
    payload = {"expected_moderator_version": moderator_version}
    headers = make_moderator_headers(actor_moderator_id or moderator_id)
    return get_success_data(api_client.resign_moderator(community_id, moderator_id, payload, headers))


def demote(community_id, moderator_id, moderator_version=None, actor_moderator_id=None):
    if moderator_version is None:
        moderator_version = _moderator_version(community_id, moderator_id)
    payload = {"expected_moderator_version": moderator_version}
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.demote_moderator(community_id, moderator_id, payload, headers))


def remove_moderator(community_id, moderator_id, moderator_version=None, actor_moderator_id=None):
    if moderator_version is None:
        moderator_version = _moderator_version(community_id, moderator_id)
    payload = {"expected_moderator_version": moderator_version}
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.remove_moderator(community_id, moderator_id, payload, headers))


def _moderator_version(community_id, moderator_id):
    response = api_client.get_moderator(community_id, moderator_id, ADMIN)
    return get_success_data(response)["moderator_version"]


# =============================================================================
# Posts, reports and detection
# =============================================================================

def publish_post(community_id, author_account_id="user-ap", title="Test post",
                 body="Test body", post_type="TEXT", is_over_18=None):
    payload = {
        "author_account_id": author_account_id,
        "title": title,
        "body": body,
        "post_type": post_type,
    }
    if is_over_18 is not None:
        payload["is_over_18"] = is_over_18
    response = api_client.create_post(community_id, payload, make_account_headers(author_account_id))
    return get_success_data(response)


def file_report(community_id, content_source_type="POST", content_source_id="src-1",
                reporter_account_id="rep-1", report_reason_code="SPAM",
                resolution_tier=1):
    payload = {
        "content_source_type": content_source_type,
        "content_source_id": content_source_id,
        "reporter_account_id": reporter_account_id,
        "report_reason_code": report_reason_code,
        "resolution_tier": resolution_tier,
    }
    headers = make_account_headers(reporter_account_id)
    return get_success_data(api_client.create_content_report(community_id, payload, headers))


def list_reports(community_id, params=None):
    return api_client.list_content_reports(community_id, ADMIN, params=params)


def report_rows(community_id, params=None):
    data, _meta = _paginated_pair(list_reports(community_id, params=params))
    return data


def record_detection(community_id, source_type="POST", source_id="src-1",
                     subject_account_id="u-target", signal_severity_band=5,
                     detection_confidence=0.90, overlap_ratio=0.20,
                     published_at_utc="2026-09-12T00:00:00Z",
                     actor_moderator_id=None):
    payload = {
        "source_type": source_type,
        "source_id": source_id,
        "subject_account_id": subject_account_id,
        "signal_severity_band": signal_severity_band,
        "detection_confidence": detection_confidence,
        "overlap_ratio": overlap_ratio,
        "published_at_utc": published_at_utc,
    }
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_detection_item(community_id, payload, headers))


def list_detections(community_id, params=None):
    return api_client.list_detection_items(community_id, ADMIN, params=params)


def detection_rows(community_id, params=None):
    data, _meta = _paginated_pair(list_detections(community_id, params=params))
    return data


# =============================================================================
# Content decisions
# =============================================================================

def record_decision(community_id, item_id, decision_outcome="REMOVE",
                    decision_confidence=0.90, dissection_band=0,
                    precedent_approval_count=0,
                    community_health_index_override_present=None,
                    actor_moderator_id=None):
    payload = {
        "auto_detection_backlog_item_id": item_id,
        "decision_outcome": decision_outcome,
        "decision_confidence": decision_confidence,
        "dissection_band": dissection_band,
        "precedent_approval_count": precedent_approval_count,
    }
    if community_health_index_override_present is not None:
        payload["community_health_index_override_present"] = community_health_index_override_present
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_content_decision(community_id, payload, headers))


def detect_and_decide(community_id, source_id="src-1", subject_account_id="u-target",
                      decision_outcome="REMOVE", dissection_band=0,
                      precedent_approval_count=0, signal_severity_band=5,
                      overlap_ratio=0.20, detection_confidence=0.90,
                      published_at_utc="2026-09-12T00:00:00Z",
                      actor_moderator_id=None):
    """Record a detection and consume it with a decision. Returns (item, decision)."""
    item = record_detection(
        community_id, source_id=source_id, subject_account_id=subject_account_id,
        signal_severity_band=signal_severity_band, overlap_ratio=overlap_ratio,
        detection_confidence=detection_confidence, published_at_utc=published_at_utc,
        actor_moderator_id=actor_moderator_id,
    )
    decision = record_decision(
        community_id, item["id"], decision_outcome=decision_outcome,
        dissection_band=dissection_band, precedent_approval_count=precedent_approval_count,
        decision_confidence=detection_confidence, actor_moderator_id=actor_moderator_id,
    )
    return item, decision


def list_decisions(community_id, params=None):
    return api_client.list_content_decisions(community_id, ADMIN, params=params)


def decision_rows(community_id, params=None):
    data, _meta = _paginated_pair(list_decisions(community_id, params=params))
    return data


def audit_decision(decision_id):
    return get_success_data(api_client.audit_decision({"decision_id": decision_id}, ADMIN))


def revise_decision(decision_id):
    return get_success_data(api_client.revise_decision({"decision_id": decision_id}, ADMIN))


def reaudit_decision(decision_id):
    return get_success_data(api_client.reaudit_decision({"decision_id": decision_id}, ADMIN))


# =============================================================================
# Sanctions and accounts
# =============================================================================

def apply_account_wide_sanction(account_id, community_id, decision_outcome="BAN_ISSUED"):
    payload = {
        "account_id": account_id,
        "community_id": community_id,
        "decision_outcome": decision_outcome,
    }
    return get_success_data(api_client.apply_account_wide_sanction(payload, ADMIN))


def get_account(account_id, role="PlatformAdmin", user_id=None):
    if role == "PlatformAdmin":
        headers = ADMIN
    elif role == "Moderator":
        headers = make_moderator_headers(user_id)
    elif role == "ContentReviewer":
        headers = make_content_reviewer_headers()
    else:
        headers = make_account_headers(user_id or account_id)
    return get_success_data(api_client.get_account(account_id, headers))


def list_account_sanctions(account_id, params=None):
    return api_client.list_account_sanctions(account_id, ADMIN, params=params)


def sanction_rows(account_id, params=None):
    data, _meta = _paginated_pair(list_account_sanctions(account_id, params=params))
    return data


def find_sanction(account_id, community_id=None, status=None):
    params = {}
    if community_id is not None:
        params["community_id"] = community_id
    if status is not None:
        params["status"] = status
    rows = sanction_rows(account_id, params=params or None)
    assert rows, f"Setup failed: no sanction for account {account_id!r}"
    return rows[0]


# =============================================================================
# Appeals
# =============================================================================

def file_appeal(account_id, sanction_id, ground_code="ANALYSIS_ERROR",
                new_evidence_url=None, sanction_misapplication_present=None):
    payload = {"sanction_id": sanction_id, "ground_code": ground_code}
    if new_evidence_url is not None:
        payload["new_evidence_url"] = new_evidence_url
    if sanction_misapplication_present is not None:
        payload["sanction_misapplication_present"] = sanction_misapplication_present
    return get_success_data(api_client.file_appeal(account_id, payload, ADMIN))


def submit_appeal(account_id, appeal_id):
    return get_success_data(api_client.submit_appeal(account_id, appeal_id, ADMIN))


def file_and_submit_appeal(account_id, sanction_id, ground_code="ANALYSIS_ERROR",
                           new_evidence_url=None, sanction_misapplication_present=None):
    appeal = file_appeal(account_id, sanction_id, ground_code=ground_code,
                         new_evidence_url=new_evidence_url,
                         sanction_misapplication_present=sanction_misapplication_present)
    return submit_appeal(account_id, appeal["id"])


def decide_appeal(account_id, appeal_id, decision="GRANT"):
    return get_success_data(api_client.decide_appeal(account_id, appeal_id, {"decision": decision}, ADMIN))


def refer_appeal(appeal_id, note=None):
    return get_success_data(api_client.refer_appeal(appeal_id, ADMIN, note=note))


def get_appeal(account_id, appeal_id):
    return get_success_data(api_client.get_appeal(account_id, appeal_id, ADMIN))


def reinstate_sanction(sanction_id):
    return get_success_data(api_client.reinstate_sanction({"sanction_id": sanction_id}, ADMIN))


# =============================================================================
# Brigading
# =============================================================================

def record_cluster(community_id, internal_link_count=10, external_link_count=10,
                   participant_count=10, legitimate_participant_count=0,
                   actor_moderator_id=None):
    payload = {
        "internal_link_count": internal_link_count,
        "external_link_count": external_link_count,
        "participant_count": participant_count,
        "legitimate_participant_count": legitimate_participant_count,
    }
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_brigade_cluster(community_id, payload, headers))


def list_clusters(community_id, params=None):
    return api_client.list_brigade_clusters(community_id, ADMIN, params=params)


def cluster_rows(community_id, params=None):
    data, _meta = _paginated_pair(list_clusters(community_id, params=params))
    return data


def escalate_cluster(cluster_id, sanction_ladder="BAN"):
    return get_success_data(api_client.escalate_brigade_cluster(
        {"cluster_id": cluster_id, "sanction_ladder": sanction_ladder}, ADMIN))


def revive_cluster(cluster_id):
    return get_success_data(api_client.revive_brigade_cluster({"cluster_id": cluster_id}, ADMIN))


def dismiss_cluster(community_id, cluster_id, actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.dismiss_brigade_cluster(community_id, cluster_id, headers))


# =============================================================================
# Protests
# =============================================================================

def request_protest(community_id, requested_access_mode="READ_ONLY",
                    conflicting_cross_power_account_ids=None,
                    actor_moderator_id=None, expected_community_version=None):
    if expected_community_version is None:
        expected_community_version = community_version(community_id)
    payload = {
        "requested_access_mode": requested_access_mode,
        "conflicting_cross_power_account_ids": conflicting_cross_power_account_ids or [],
        "expected_community_version": expected_community_version,
    }
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_protest(community_id, payload, headers))


def approve_protest(community_id, protest_id, moderator_id, approving_account_id,
                    actor_moderator_id=None):
    payload = {"moderator_id": moderator_id, "approving_account_id": approving_account_id}
    headers = make_moderator_headers(actor_moderator_id or moderator_id)
    return get_success_data(api_client.approve_protest(community_id, protest_id, payload, headers))


def coordinate_protest(community_id, protest_id, actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.coordinate_protest(community_id, protest_id, headers))


def end_protest(community_id, protest_id, actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.end_protest(community_id, protest_id, headers))


def get_protest(community_id, protest_id):
    return get_success_data(api_client.get_protest(community_id, protest_id, ADMIN))


def protest_approval_rows(protest_id):
    data, _meta = _paginated_pair(api_client.list_protest_approvals(protest_id, ADMIN))
    return data


def issue_policy_advisory(community_id):
    return get_success_data(api_client.issue_policy_advisory({"community_id": community_id}, ADMIN))


def record_regulation_cadence(community_id):
    return get_success_data(api_client.record_regulation_cadence({"community_id": community_id}, ADMIN))


def start_institution_negotiation(community_id):
    return get_success_data(api_client.start_institution_negotiation({"community_id": community_id}, ADMIN))


# =============================================================================
# Successions
# =============================================================================

def open_succession(community_id, actor_moderator_id=None, expected_community_version=None):
    if expected_community_version is None:
        expected_community_version = community_version(community_id)
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.create_succession(
        community_id, {"expected_community_version": expected_community_version}, headers))


def record_discussion(community_id, succession_id, round_note="Round", actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.record_succession_discussion(
        community_id, succession_id, {"round_note": round_note}, headers))


def dispute_succession(community_id, succession_id, dispute_note="Dispute", actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return get_success_data(api_client.dispute_succession(
        community_id, succession_id, {"dispute_note": dispute_note}, headers))


def prevent_succession(community_id, succession_id):
    return get_success_data(api_client.prevent_succession(community_id, succession_id, {}, ADMIN))


def get_succession(community_id, succession_id):
    return get_success_data(api_client.get_succession(community_id, succession_id, ADMIN))


def succession_rows(community_id, params=None):
    data, _meta = _paginated_pair(api_client.list_successions(community_id, ADMIN, params=params))
    return data


# =============================================================================
# Posture
# =============================================================================

def restrict_community_via_sanctions(community_id, account_id="u-restrict", count=1,
                                     outcomes=None):
    """Apply account-wide sanctions until the community leaves ACTIVE.

    A single account-wide sanction on a fresh account gives a sanction index of
    1.00, which clears both the restriction gate and the negotiation gate, so the
    community lands in INSTITUTION_NEGOTIATION in the same request.
    """
    outcomes = outcomes or ["BAN_ISSUED"] * count
    sanctions = []
    for outcome in outcomes:
        sanctions.append(apply_account_wide_sanction(account_id, community_id, outcome))
    return sanctions


def quarantine_community(community_id, account_id="u-quarantine"):
    """Drive a community into QUARANTINED through the restriction path.

    One account-wide sanction on a fresh account gives an index of 1.00, so the
    community passes through RESTRICTED into INSTITUTION_NEGOTIATION; the caller
    then advances the clock past the negotiation window and records no cadence.
    The clock move is left to the caller so a test can pin the exact instant.
    """
    apply_account_wide_sanction(account_id, community_id, "BAN_ISSUED")
    return get_community(community_id)


def quarantine_and_archive(community_id, sanctions=("u-arch-1", "u-arch-2")):
    """Take a community to ARCHIVED: sanctions -> INSTITUTION_NEGOTIATION ->
    archive. Returns the archived community."""
    for account_id in sanctions:
        apply_account_wide_sanction(account_id, community_id, "BAN_ISSUED")
    start_institution_negotiation(community_id)
    return get_success_data(api_client.archive_community({"community_id": community_id}, ADMIN))


def request_reinstatement(community_id, actor_moderator_id=None):
    headers = make_moderator_headers(actor_moderator_id or _first_top_moderator_id(community_id))
    return api_client.request_reinstatement(community_id, headers)


# =============================================================================
# Composite scenario builders used by more than one test
# =============================================================================

def setup_community_with_reports(report_specs, name="r/Alpha", founder_account_id="mod-alpha",
                                 source_type="POST", source_id=None, post_id=None,
                                 with_post=False, author_account_id="user-ap"):
    """Create a community holding one OPEN report per entry of ``report_specs``.

    Each entry is ``(resolution_tier, reason_code)``; reports share one source id
    so a single detection can consume them all.
    """
    community = create_community(name, founder_account_id=founder_account_id)
    community_id = community["id"]
    source_id = source_id or f"src-{community_id[:8]}"
    if with_post:
        post = publish_post(community_id, author_account_id=author_account_id)
        source_id = post["id"]
    reports = []
    for index, spec in enumerate(report_specs):
        tier, reason = spec
        reports.append(file_report(
            community_id, content_source_type=source_type, content_source_id=source_id,
            reporter_account_id=f"rep-{index + 1}", report_reason_code=reason,
            resolution_tier=tier,
        ))
    return community, reports, source_id


def setup_two_community_protest_quorum(name="r/Alpha", second_name="r/Beta"):
    """Two moderators in one community, each of whom also moderates a second
    community, plus a REQUESTED protest. Returns a dict of the resources."""
    community = create_community(name, founder_account_id="mod-a")
    community_id = community["id"]
    mod_a = founding_moderator(community_id)
    mod_b = appoint_moderator(community_id, "mod-b", actor_moderator_id=mod_a["id"])
    beta = create_community(second_name, founder_account_id="mod-b")
    protest = request_protest(community_id, actor_moderator_id=mod_a["id"])
    return {
        "community": community,
        "community_id": community_id,
        "mod_a": mod_a,
        "mod_b": mod_b,
        "beta": beta,
        "protest": protest,
        "protest_id": protest["id"],
    }


def setup_restricted_community_with_cluster_health(name="r/Alpha"):
    """A community holding one ESCALATED band-3 overlap-0.40 cluster, driven into
    a restricted posture by a single account-wide sanction."""
    community = create_community(name, founder_account_id="mod-alpha")
    community_id = community["id"]
    mod = founding_moderator(community_id)
    cluster = record_cluster(community_id, internal_link_count=4, external_link_count=6,
                             participant_count=10, legitimate_participant_count=6,
                             actor_moderator_id=mod["id"])
    escalate_cluster(cluster["id"])
    apply_account_wide_sanction("u-restrict", community_id, "BAN_ISSUED")
    return community, cluster, mod


def setup_sanctioned_account(community_id, account_id="u-target", outcome="BAN_ISSUED",
                             source_id="src-1"):
    """Create an ACTIVE sanction for an account inside a community, through the
    community decision route when a moderator exists, else the admin route."""
    if community_id is None:
        raise ValueError("a community id is required")
    return apply_account_wide_sanction(account_id, community_id, outcome)


# --- sanction-index driven posture fixtures ---------------------------------

def community_route_sanction(community_id, account_id, outcome="MUTE_ISSUED",
                             source_id=None, moderator_id=None):
    """Issue a sanction through the community decision route.

    A decision-route sanction is recorded with ``account_wide_enforcement_counted``
    false, so it only counts toward the sanction index once it is at least thirty
    days old.
    """
    source_id = source_id or f"src-{account_id}-{outcome}-{community_id[:6]}"
    item, decision = detect_and_decide(
        community_id, source_id=source_id, subject_account_id=account_id,
        decision_outcome=outcome, dissection_band=0,
        actor_moderator_id=moderator_id,
    )
    rows = sanction_rows(account_id, params={"status": "ACTIVE"})
    for row in rows:
        if row.get("decision_id") == decision["id"]:
            return row, item, decision
    assert rows, "Setup failed: the decision did not synthesize a sanction"
    return rows[-1], item, decision


def setup_restricted_community(account_id="u-target", name="r/Alpha",
                               founder_account_id="mod-alpha", age_days=35):
    """A community driven into RESTRICTED by the sanction index.

    Three decision-route sanctions for one account: two recorded ``age_days``
    before the third, so the third write recomputes the index to two thirds —
    which clears the 0.60 restriction gate without clearing the 0.80 negotiation
    gate. Returns a dict of the resources.
    """
    community = create_community(name, founder_account_id=founder_account_id)
    community_id = community["id"]
    moderator = founding_moderator(community_id)
    first, _item_a, _dec_a = community_route_sanction(
        community_id, account_id, "MUTE_ISSUED",
        source_id=f"src-{account_id}-a", moderator_id=moderator["id"])
    second, _item_b, _dec_b = community_route_sanction(
        community_id, account_id, "BAN_ISSUED",
        source_id=f"src-{account_id}-b", moderator_id=moderator["id"])
    advanced = _advance_days(CLOCK_BASE, age_days)
    set_clock(advanced)
    third, _item_c, decision_c = community_route_sanction(
        community_id, account_id, "WARNING_ISSUED",
        source_id=f"src-{account_id}-c", moderator_id=moderator["id"])
    return {
        "community": community,
        "community_id": community_id,
        "moderator": moderator,
        "moderator_id": moderator["id"],
        "account_id": account_id,
        "sanctions": [first, second, third],
        "decision": decision_c,
        "aged_clock": advanced,
    }


def setup_quarantined_community(account_id="u-target", name="r/Alpha",
                                founder_account_id="mod-alpha", extra_moderators=(),
                                with_post=True, with_succession=False, clusters=12):
    """A community driven to QUARANTINED.

    Restriction comes from the sanction index; quarantine comes from the brigade
    penalty. ``with_succession`` opens a succession while the community is still
    ACTIVE, so the archival cascade has an open handover to close. The default
    cluster count pushes the health index below the quarantine line under every
    reading the PRD states; pass a smaller count to land on an exact value.
    Returns a dict of the resources.
    """
    state = setup_restricted_community(account_id=account_id, name=name,
                                       founder_account_id=founder_account_id)
    return extend_to_quarantine(state, extra_moderators=extra_moderators,
                                with_post=with_post, with_succession=with_succession,
                                clusters=clusters)


def extend_to_quarantine(state, extra_moderators=(), with_post=True,
                         with_succession=False, succession_first=True,
                         clusters=12):
    """Continue a RESTRICTED fixture state into QUARANTINED.

    The succession, if requested, is opened before the brigade penalty lands so
    the community is still ACTIVE when the handover opens. ``clusters`` escalated
    band-5 overlap-1.00 clusters push the health index onto or below the
    quarantine line under every reading of the brigade penalty the PRD states.
    """
    community_id = state["community_id"]
    moderator_id = state["moderator_id"]
    if with_succession:
        state["succession"] = open_succession(community_id, actor_moderator_id=moderator_id)
    moderators = [state["moderator"]]
    for account in extra_moderators:
        moderators.append(appoint_moderator(community_id, account, actor_moderator_id=moderator_id))
    post = publish_post(community_id) if with_post else None
    escalated = []
    for _index in range(clusters):
        cluster = record_cluster(community_id, internal_link_count=10, external_link_count=10,
                                 participant_count=10, legitimate_participant_count=0,
                                 actor_moderator_id=moderator_id)
        escalate_cluster(cluster["id"], sanction_ladder="BAN")
        escalated.append(cluster)
    state.update({
        "moderators": moderators,
        "post": post,
        "clusters": escalated,
    })
    return state


def _advance_days(base_utc, days):
    """Return an ISO 8601 UTC instant ``days`` after ``base_utc``."""
    from datetime import datetime, timedelta, timezone
    start = datetime.strptime(base_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance_days(days, base_utc=None):
    """Advance the logical clock by ``days`` from ``base_utc`` (default: the base
    instant) and return the new instant."""
    instant = _advance_days(base_utc or CLOCK_BASE, days)
    set_clock(instant)
    return instant


def setup_succession_blocked(community_id, moderator_id, second_moderator_id,
                             succession_id=None, rounds=2):
    """Walk a succession into HANDOVER_BLOCKED.

    Discussion rounds alternate between the two moderators so the disputing
    moderator is always a distinct account from the author of the most recent
    round. Returns the succession id.
    """
    if succession_id is None:
        succession_id = open_succession(community_id, actor_moderator_id=moderator_id)["id"]
    authors = [moderator_id, second_moderator_id]
    for index in range(rounds):
        record_discussion(community_id, succession_id,
                          round_note=f"Round {index + 1}",
                          actor_moderator_id=authors[index % 2])
    last_author = authors[(rounds - 1) % 2]
    disputer = authors[rounds % 2]
    assert disputer != last_author, "the disputer must differ from the last round author"
    dispute_succession(community_id, succession_id, dispute_note="Block raised",
                       actor_moderator_id=disputer)
    return succession_id


# =============================================================================
# Small utilities
# =============================================================================

def _paginated_pair(response):
    """Return (rows, meta) from a list response, tolerating either envelope."""
    from prd_bench_local_runner.testing import validate_paginated
    try:
        return validate_paginated(response)
    except Exception:
        data = get_success_data(response)
        meta = response.json().get("meta", {})
        return (data if isinstance(data, list) else data.get("data", [])), meta


# --- single-resource reads --------------------------------------------------

def get_moderator(community_id, moderator_id, role="PlatformAdmin", user_id=None):
    if role == "PlatformAdmin":
        headers = ADMIN
    elif role == "Moderator":
        headers = make_moderator_headers(user_id)
    else:
        headers = make_content_reviewer_headers()
    return get_success_data(api_client.get_moderator(community_id, moderator_id, headers))


def get_content_report(community_id, report_id):
    return get_success_data(api_client.get_content_report(community_id, report_id, ADMIN))


def get_content_decision(community_id, decision_id):
    return get_success_data(api_client.get_content_decision(community_id, decision_id, ADMIN))


def get_detection_item(community_id, item_id):
    return get_success_data(api_client.get_detection_item(community_id, item_id, ADMIN))


def get_brigade_cluster(community_id, cluster_id):
    return get_success_data(api_client.get_brigade_cluster(community_id, cluster_id, ADMIN))


def get_rule(community_id, rule_id):
    return get_success_data(api_client.get_rule(community_id, rule_id, ADMIN))


def get_post(community_id, post_id):
    return get_success_data(api_client.get_post(community_id, post_id, ADMIN))


def list_moderator_actions(moderator_id, params=None):
    return api_client.list_moderator_actions(moderator_id, ADMIN, params=params)


def list_escalations(community_id, params=None):
    return api_client.list_escalations(community_id, ADMIN, params=params)


def list_community_sanctions(community_id, params=None):
    return api_client.list_community_sanctions(community_id, ADMIN, params=params)


def list_community_appeals(community_id, params=None):
    return api_client.list_community_appeals(community_id, ADMIN, params=params)


def archive_community(payload, headers=None):
    """Archive a quarantined community (administration route)."""
    return get_success_data(api_client.archive_community(payload, headers or ADMIN))


def rows_of(payload):
    """Coerce a list-endpoint payload into a list of rows."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise AssertionError(f"Setup failed: payload is not a list of rows: {payload!r}")


def count_rows(response):
    """Number of rows in a list response, without asserting the envelope shape."""
    try:
        data, meta = _paginated_pair(response)
        if isinstance(meta, dict) and isinstance(meta.get("total_count"), int):
            return meta["total_count"]
        return len(data)
    except Exception:
        return len(rows_of(get_success_data(response)))


def non_existent_community_id():
    return NON_EXISTENT_UUID


UNKNOWN_COMMUNITY_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_SUCCESSION_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_RESOURCE_ID = "00000000-0000-4000-8000-000000000002"