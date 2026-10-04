"""Incident intake, the interim hold and its release, and withdrawal."""

from db import STORE, now
from calculations import (cluster_risk_multiplier_pct, derive_severity,
                          propagate_risk, recompute_linked_clusters)
from errors import (ApiError, ERR_CROSS_REGION_REFERENCE, ERR_HOLD_BLOCKED_BY_APPEAL,
                    ERR_INVALID_STATE, ERR_REPORTER_ACCOUNT_MISMATCH,
                    ERR_SEVERITY_BELOW_HOLD_FLOOR, ERR_TRIP_ACCOUNT_MISMATCH)
from middleware import new_id, stamp, touch
from services import common


def _incident_lookup(incident_id):
    incident = STORE.incidents.get(incident_id)
    if incident is None:
        from errors import ERR_INCIDENT_NOT_FOUND
        raise ApiError(*ERR_INCIDENT_NOT_FOUND,
                       message="No such incident: %s" % incident_id)
    return incident


def find_incident(incident_id):
    return _incident_lookup(incident_id)


def freeze_intake_facts(incident):
    """prior_incident_count_at_intake and cluster_risk_multiplier_pct."""
    account_id = incident.get("account_id")
    created_at = incident.get("created_at")
    count = 0
    for other in STORE.account_incidents(account_id):
        if other.get("id") == incident.get("id"):
            continue
        other_created = other.get("created_at")
        if other_created is not None and created_at is not None and other_created < created_at:
            count += 1
    incident["prior_incident_count_at_intake"] = count
    incident["cluster_risk_multiplier_pct"] = cluster_risk_multiplier_pct(account_id)
    return incident


def file_incident(payload):
    account_id = payload.get("account_id")
    account = STORE.accounts.get(account_id)
    if account is None:
        from errors import ERR_RESOURCE_NOT_FOUND
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account: %s" % account_id)

    reporter_type = payload.get("reporter_type")
    reporter_account_id = payload.get("reporter_account_id")
    if reporter_type == "THIRD_PARTY":
        if reporter_account_id:
            raise ApiError(*ERR_REPORTER_ACCOUNT_MISMATCH,
                           message="A THIRD_PARTY report must omit reporter_account_id.")
    else:
        if not reporter_account_id:
            raise ApiError(*ERR_REPORTER_ACCOUNT_MISMATCH,
                           message="A %s report must carry reporter_account_id." % reporter_type)
        if reporter_account_id not in STORE.accounts:
            from errors import ERR_RESOURCE_NOT_FOUND
            raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                           message="No such reporter account: %s" % reporter_account_id)

    referenced_trip_id = payload.get("referenced_trip_id")
    if referenced_trip_id:
        trip = STORE.trips.get(referenced_trip_id)
        if trip is None:
            from errors import ERR_TRIP_NOT_FOUND
            raise ApiError(*ERR_TRIP_NOT_FOUND,
                           message="No such trip: %s" % referenced_trip_id)
        if trip.get("region_code") != account.get("home_region_code"):
            raise ApiError(*ERR_CROSS_REGION_REFERENCE,
                           message="The referenced trip belongs to another region.")

    incident = {
        "id": new_id(),
        "account_id": account_id,
        "referenced_trip_id": referenced_trip_id,
        "reporter_type": reporter_type,
        "reporter_account_id": reporter_account_id,
        "incident_category": payload.get("incident_category"),
        "severity": "S1",
        "aggravator_codes": list(payload.get("aggravator_codes") or []),
        "derivative_severity_flagged": False,
        "incident_status": "OPEN",
        "decision_category": "PENDING",
        "decided_at": None,
        "decision_basis": payload.get("decision_basis"),
        "decision_evidence_score": 0,
        "decision_support": 0,
        "decision_distinct_evidence_sources": 0,
        "appeal_reviewer_user_id": None,
        "decision_maker_user_id": None,
        "prior_incident_count_at_intake": 0,
        "cluster_risk_multiplier_pct": 100,
        "_appeal_committed_at": None,
        "_appeal_committed": False,
        "_appeal_file_deadline": None,
    }
    stamp(incident)
    STORE.incidents[incident["id"]] = incident

    freeze_intake_facts(incident)
    severity, derivative = derive_severity(
        incident.get("incident_category"),
        incident.get("aggravator_codes"),
        incident.get("prior_incident_count_at_intake"))
    incident["severity"] = severity
    incident["derivative_severity_flagged"] = derivative

    # The frozen cluster multiplier depends on the aggregates, which depend on
    # the incident, so the multiplier is re-read once the incident is visible.
    incident["cluster_risk_multiplier_pct"] = cluster_risk_multiplier_pct(account_id)
    recompute_linked_clusters(account_id)
    incident["cluster_risk_multiplier_pct"] = cluster_risk_multiplier_pct(account_id)

    common.refresh_account(account)
    return incident


def rederive_severity(incident, aggravator_codes):
    incident["aggravator_codes"] = list(aggravator_codes or [])
    severity, derivative = derive_severity(
        incident.get("incident_category"),
        incident.get("aggravator_codes"),
        incident.get("prior_incident_count_at_intake"))
    incident["severity"] = severity
    incident["derivative_severity_flagged"] = derivative
    touch(incident)
    account = STORE.accounts.get(incident.get("account_id"))
    if account is not None:
        common.refresh_account(account)
    return incident


def place_hold(incident):
    account = STORE.accounts.get(incident.get("account_id"))
    if account is None:
        from errors import ERR_RESOURCE_NOT_FOUND
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account.")
    status = incident.get("incident_status")

    # Terminal lockdown: a decided incident performs no transition.
    if status in ("DECIDED", "MANDATORY_REPORTED_BLOCKED", "WITHDRAWN"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="An interim hold is not declared from %s." % status)

    # Communication suppression is only permitted for accounts that are ACTIVE
    # (or already RESTRICTED), so an appeal-pending account is refused first.
    if account.get("status") == "APPEAL_PENDING":
        raise ApiError(*ERR_HOLD_BLOCKED_BY_APPEAL,
                       message="Communication suppression is not available while the "
                               "account sits inside the appeal process.")

    if incident.get("severity") not in ("S3", "S4"):
        raise ApiError(*ERR_SEVERITY_BELOW_HOLD_FLOOR,
                       message="The incident severity is below the hold floor.")

    if account.get("status") not in ("ACTIVE", "RESTRICTED"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="An interim hold is not declared from %s." % status)
    if status not in ("OPEN",):
        raise ApiError(*ERR_INVALID_STATE,
                       message="An interim hold is not declared from %s." % status)

    incident["incident_status"] = "INVESTIGATING"
    touch(incident)
    account["status"] = "UNDER_HOLD"
    common.refresh_account(account)
    return incident


def release_hold(incident):
    account = STORE.accounts.get(incident.get("account_id"))
    if account is None:
        from errors import ERR_RESOURCE_NOT_FOUND
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account.")
    if incident.get("incident_status") != "INVESTIGATING":
        raise ApiError(*ERR_INVALID_STATE,
                       message="An interim hold release is not declared from %s."
                               % incident.get("incident_status"))
    if incident.get("severity") not in ("S3", "S4"):
        raise ApiError(*ERR_SEVERITY_BELOW_HOLD_FLOOR,
                       message="The incident severity is below the hold floor.")

    standing = [a for a in STORE.account_actions(account.get("id"))
                if a.get("enforcement_status") in ("ACTIVE", "MANDATORY_REPORTED")]
    incident["incident_status"] = "OPEN"
    touch(incident)
    account["status"] = "RESTRICTED" if standing else "ACTIVE"
    common.refresh_account(account)
    return incident


def withdraw(incident):
    account = STORE.accounts.get(incident.get("account_id"))
    status = incident.get("incident_status")
    if incident.get("decision_category") != "PENDING":
        raise ApiError(*ERR_INVALID_STATE,
                       message="A decided incident cannot be withdrawn.")
    severity = incident.get("severity")
    if severity == "S1" and status == "OPEN":
        pass
    elif severity == "S2" and status == "INVESTIGATING":
        pass
    else:
        raise ApiError(*ERR_INVALID_STATE,
                       message="Withdrawal is not declared from %s at %s."
                               % (status, severity))
    incident["incident_status"] = "WITHDRAWN"
    touch(incident)
    if account is not None and account.get("status") == "UNDER_HOLD":
        account["status"] = "ACTIVE"
        common.refresh_account(account)
    return incident


def gather_evidence(incident, payload):
    account = STORE.accounts.get(incident.get("account_id"))
    evidence_type = payload.get("evidence_type")
    source_entity_id = payload.get("source_entity_id")

    if evidence_type in ("TRIP_DATA", "IN_APP_MESSAGE"):
        trip = STORE.trips.get(source_entity_id)
        if trip is None:
            from errors import ERR_TRIP_NOT_FOUND
            raise ApiError(*ERR_TRIP_NOT_FOUND,
                           message="No such trip: %s" % source_entity_id)
        involved = {trip.get("rider_account_id"), trip.get("driver_account_id")}
        counterparty = incident.get("reporter_account_id")
        if incident.get("account_id") not in involved or counterparty not in involved:
            raise ApiError(*ERR_TRIP_ACCOUNT_MISMATCH,
                           message="The trip does not involve both the subject account "
                                   "and the reported counterparty.")
        if trip.get("region_code") != (account or {}).get("home_region_code"):
            raise ApiError(*ERR_CROSS_REGION_REFERENCE,
                           message="The referenced trip belongs to another region.")

    if evidence_type == "DEVICE_LINK":
        link = STORE.links.get(source_entity_id)
        if link is None:
            from errors import ERR_RESOURCE_NOT_FOUND
            raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                           message="No such account-device link: %s" % source_entity_id)
        cluster = STORE.clusters.get(link.get("device_cluster_id"))
        if cluster is not None and cluster.get("region_code") != (account or {}).get("home_region_code"):
            raise ApiError(*ERR_CROSS_REGION_REFERENCE,
                           message="The referenced device cluster belongs to another region.")

    if evidence_type == "RATINGS_HISTORY" and source_entity_id:
        subject = STORE.accounts.get(source_entity_id)
        if subject is not None and subject.get("home_region_code") != (account or {}).get("home_region_code"):
            raise ApiError(*ERR_CROSS_REGION_REFERENCE,
                           message="The referenced account belongs to another region.")

    evidence = {
        "id": new_id(),
        "incident_id": incident.get("id"),
        "evidence_type": evidence_type,
        "source_entity_id": source_entity_id,
        "evidence_weight": payload.get("evidence_weight"),
        "evidence_status": "PENDING",
        "recorded_at": now(),
        "exclusion_reason": None,
    }
    stamp(evidence)
    STORE.evidence[evidence["id"]] = evidence

    _apply_stale_link_to_evidence(evidence)
    return evidence


def _apply_stale_link_to_evidence(evidence):
    from calculations import unconditional_exclusion_reason
    reason = unconditional_exclusion_reason(evidence)
    if reason in ("STALE_SOURCE", "NO_MESSAGE_HISTORY", "STALE_LINK"):
        evidence["_pre_excluded_reason"] = reason
    return evidence


def accept_evidence(incident, evidence_id, accepted):
    evidence = STORE.evidence.get(evidence_id)
    if evidence is None or evidence.get("incident_id") != incident.get("id"):
        from errors import ERR_RESOURCE_NOT_FOUND
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such evidence item: %s" % evidence_id)

    if accepted:
        from calculations import unconditional_exclusion_reason
        reason = unconditional_exclusion_reason(evidence)
        if reason is not None:
            # The unconditional exclusions are applied ahead of the scoring pass.
            evidence["evidence_status"] = "EXCLUDED"
            evidence["exclusion_reason"] = reason
        else:
            evidence["evidence_status"] = "INCLUDED"
            evidence["exclusion_reason"] = None
            if evidence.get("evidence_type") == "LAW_ENFORCEMENT_CONTACT":
                trip = STORE.trips.get(incident.get("referenced_trip_id"))
                if trip is not None:
                    trip["law_enforcement_contact_logged"] = True
                    touch(trip)
    else:
        evidence["evidence_status"] = "EXCLUDED"
        evidence["exclusion_reason"] = evidence.get("exclusion_reason") or "DECLINED"
    touch(evidence)

    _maybe_advance_to_decision(incident)
    return incident


def _maybe_advance_to_decision(incident):
    """The advance fires once the last PENDING item resolves."""
    rows = [e for e in STORE.evidence.values() if e.get("incident_id") == incident.get("id")]
    if any(e.get("evidence_status") == "PENDING" for e in rows):
        return False
    included = [e for e in rows if e.get("evidence_status") == "INCLUDED"]
    if not included:
        return False

    account = STORE.accounts.get(incident.get("account_id"))
    if incident.get("incident_status") != "INVESTIGATING":
        return False

    from calculations import evidence_scores
    scores = evidence_scores(incident.get("id"))
    incident["decision_evidence_score"] = scores["evidence_score"]
    incident["decision_support"] = scores["support_score"]
    incident["decision_distinct_evidence_sources"] = scores["distinct_evidence_source_count"]
    incident["incident_status"] = "PENDING_DECISION"
    touch(incident)
    if account is not None:
        account["status"] = "PENDING_DECISION"
        common.refresh_account(account)
    return True