"""Payload factories — one per entity, carrying only client-supplied fields."""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def next_sequence() -> int:
    """Monotonic in-process counter for unique-per-broker identity hashes."""
    return next(_counter)


DEFAULTS = {
    "BROKER_LEGAL_NAME": "Silverleaf Data Exchange",
    "BROKER_CONTACT_EMAIL": "compliance@silverleaf.example",
    "BROKER_DESCRIPTION": (
        "Resells licensed automotive and household ownership attributes to lead "
        "generators."
    ),
    "REGISTRATION_DESCRIPTION": (
        "California registry filing for the automotive and household attribute "
        "resale business."
    ),
    "RECIPIENT_NAME": "Cobalt Lead Services",
    "SOURCE_LABEL": "OWNERSHIP_FEED_D",
    "SCOPE_NOTE": (
        "Review of the broker's consumer deletion request handling, identity "
        "verification practice and downstream propagation evidence."
    ),
    "WAIVER_JUSTIFICATION": (
        "Archive tier schema cannot represent the purge marker; legal sign-off "
        "recorded."
    ),
    "LIFT_JUSTIFICATION": (
        "Consumer re-established the relationship in writing and asked to be "
        "re-enrolled."
    ),
}

# Disclosure prose long enough to earn full weight credit in every category.
DISCLOSURE_CONTENT = {
    "SOURCES": (
        "Public records, loyalty programme partners and licensed survey panels "
        "supply the source data."
    ),
    "RECIPIENTS": (
        "Advertising networks, analytics vendors and credit marketing affiliates "
        "receive the segments."
    ),
    "RETENTION": (
        "Records are retained for thirty-six months after the last verified "
        "engagement event."
    ),
    "OPT_OUT_MECHANISM": (
        "Consumers opt out through the web portal, the state platform or a "
        "recognised GPC signal."
    ),
    "SENSITIVE_CATEGORIES": (
        "Precise geolocation and health inference attributes are held for a small "
        "subset of records."
    ),
    "MINORS_DATA": (
        "No record knowingly describes a minor; age screening removes flagged "
        "households at intake."
    ),
}


def create_broker_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["BROKER_LEGAL_NAME"],
        "primary_contact_email": DEFAULTS["BROKER_CONTACT_EMAIL"],
        "home_state_code": "CA",
        "operating_state_codes": ["CA"],
        "business_description": DEFAULTS["BROKER_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def create_fee_deposit_payload(**overrides) -> dict:
    payload = {"amount_cents": TEST_DEFAULTS["FEE_DEPOSIT_CENTS"]}
    payload.update(overrides)
    return payload


def create_registration_payload(broker_id, expected_broker_version, **overrides) -> dict:
    payload = {
        "broker_id": broker_id,
        "state_code": "CA",
        "coverage_period_start": TEST_DEFAULTS["COVERAGE_PERIOD_START"],
        "coverage_period_end": TEST_DEFAULTS["COVERAGE_PERIOD_END"],
        "business_description": DEFAULTS["REGISTRATION_DESCRIPTION"],
        "expected_broker_version": expected_broker_version,
    }
    payload.update(overrides)
    return payload


def create_disclosure_payload(category, **overrides) -> dict:
    payload = {
        "category": category,
        "content": DISCLOSURE_CONTENT.get(category, DISCLOSURE_CONTENT["SOURCES"]),
        "covers_sensitive_categories": False,
    }
    payload.update(overrides)
    return payload


def create_consumer_payload(broker_id, **overrides) -> dict:
    payload = {
        "broker_id": broker_id,
        "identity_hash": f"sha256:consumer{next_sequence():016d}",
        "state_code": "CA",
        "source_label": DEFAULTS["SOURCE_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_consent_payload(action, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_collection_payload(**overrides) -> dict:
    payload = {"source_label": DEFAULTS["SOURCE_LABEL"]}
    payload.update(overrides)
    return payload


def create_deletion_request_payload(
    broker_id, consumer_id, expected_consumer_version, **overrides
) -> dict:
    payload = {
        "broker_id": broker_id,
        "consumer_id": consumer_id,
        "intake_channel": "DIRECT_PORTAL",
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_verification_attempt_payload(**overrides) -> dict:
    payload = {
        "method": "GOVT_ID",
        "evidence_points_count": 3,
        "document_quality_score": 80,
    }
    payload.update(overrides)
    return payload


def create_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_downstream_recipient_payload(broker_id, **overrides) -> dict:
    payload = {
        "broker_id": broker_id,
        "name": DEFAULTS["RECIPIENT_NAME"],
        "contract_propagation_required": True,
        "ack_sla_days": TEST_DEFAULTS["ACK_SLA_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_recipient_status_payload(status, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


def create_suppression_entry_payload(
    broker_id, consumer_id, originating_request_id=None, **overrides
) -> dict:
    payload = {
        "broker_id": broker_id,
        "consumer_id": consumer_id,
        "originating_request_id": originating_request_id,
        "source_scope": "ALL_SOURCES",
    }
    payload.update(overrides)
    return payload


def create_lift_payload(**overrides) -> dict:
    payload = {"lift_justification": DEFAULTS["LIFT_JUSTIFICATION"]}
    payload.update(overrides)
    return payload


def create_opt_out_signal_payload(
    broker_id, consumer_id, expected_consumer_version, **overrides
) -> dict:
    payload = {
        "broker_id": broker_id,
        "consumer_id": consumer_id,
        "signal_type": "WRITTEN_REQUEST",
        "scope": "SALE_AND_SHARING",
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_regulator_inquiry_payload(broker_id, response_due_at, **overrides) -> dict:
    payload = {
        "broker_id": broker_id,
        "scope_note": DEFAULTS["SCOPE_NOTE"],
        "response_due_at": response_due_at,
    }
    payload.update(overrides)
    return payload


def create_inquiry_response_payload(cited_audit_event_ids, **overrides) -> dict:
    payload = {"cited_audit_event_ids": list(cited_audit_event_ids)}
    payload.update(overrides)
    return payload


def create_escalation_payload(deficiency_code, **overrides) -> dict:
    payload = {"deficiency_code": deficiency_code}
    payload.update(overrides)
    return payload


def create_fail_payload(failure_code="RECIPIENT_UNREACHABLE", **overrides) -> dict:
    payload = {"failure_code": failure_code}
    payload.update(overrides)
    return payload


def create_waive_payload(**overrides) -> dict:
    payload = {"waiver_justification": DEFAULTS["WAIVER_JUSTIFICATION"]}
    payload.update(overrides)
    return payload


def create_rejection_payload(
    rejection_reason_code="INCOMPLETE_DISCLOSURE", **overrides
) -> dict:
    payload = {"rejection_reason_code": rejection_reason_code}
    payload.update(overrides)
    return payload


def create_denial_payload(denial_reason_code="IDENTITY_UNVERIFIED", **overrides) -> dict:
    payload = {"denial_reason_code": denial_reason_code}
    payload.update(overrides)
    return payload
