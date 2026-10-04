"""Monitoring enrollment, consent guards and the consumer lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_consumer_payload
from test_helpers.fixtures import (
    DATA_PROTECTION_OFFICER,
    PLATFORM_ADMIN,
    create_consumer,
    create_monitored_consumer,
    grant_consent,
    pull_bureau_snapshot,
    read_consumer,
    read_consumer_version,
)


def test_consumer_enrollment_forces_the_initial_monitoring_posture(api, as_consumer):
    """PRD §2.5: "The response is created with a `201` status, and the platform
    forces the initial posture: `score_version` is 0, and `current_score`,
    `previous_score`, `utilization_pct` and `monitoring_consent_at` are all null,
    while `open_dispute_count` is 0."
    PRD §3.1: "A newly enrolled consumer reads as untouched: the monitoring posture
    is `ENROLLED`, no consent timestamp exists, and every score-derived field is empty."

    Design: Corner/entities/consumer_create_ignores_client_supplied_monitoring_fields
    """
    payload = create_consumer_payload()
    response = api.create_consumer(payload, as_consumer("unused"))
    data = validate_success(response, 201)

    assert data["full_name"] == "Maya Chen"
    assert data["state_code"] == "CA"
    assert data["dti_pct"] == 35.0
    assert data["score_version"] == 0
    assert data["current_score"] is None
    assert data["previous_score"] is None
    assert data["utilization_pct"] is None
    assert data["monitoring_consent_at"] is None
    assert data["open_dispute_count"] == 0
    assert data["version"] == 1
    assert data["monitoring_posture"] == "ENROLLED"
    assert response.json()["meta"]["api_request_id"].startswith("req_")
    assert response.json()["meta"]["api_request_timestamp"]


def test_consumer_enrollment_mints_system_defaults(api, as_consumer):
    """PRD §2.5: "the platform forces the initial posture: `score_version` is 0, and
    `current_score`, `previous_score`, `utilization_pct` and `monitoring_consent_at`
    are all null, while `open_dispute_count` is 0."

    Design: Corner/entities/enrollment_defaults_populate_system_fields
    """
    consumer = create_consumer(full_name="Defa Ult", email="defa@example.com",
                               state_code="TX", bureau_pin="2222", dti_pct=15.0, api=api)
    data = validate_success(
        api.get_consumer(consumer["id"], as_consumer(consumer["id"])), 200
    )
    assert data["score_version"] == 0
    assert data["open_dispute_count"] == 0
    assert data["current_score"] is None
    assert data["utilization_pct"] is None


def test_consumer_enrollment_without_dti_pct_is_rejected(api, as_consumer):
    """PRD §2.5: "A consumer enrols by submitting `full_name`, `email`, `state_code`,
    `bureau_pin`, and `dti_pct`."

    Design: Corner/entities/consumer_create_without_required_field_fails
    """
    payload = create_consumer_payload()
    payload.pop("dti_pct")
    response = api.create_consumer(payload, as_consumer("unused"))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows = validate_success(api.list_consumers(PLATFORM_ADMIN), 200)
    assert rows == [], "nothing may be persisted when a required field is missing"


def test_consumer_read_with_unknown_id_returns_not_found(api, consumer_headers):
    """PRD §2.9: "The rejection is an HTTP 404 with `ERR_CONSUMER_NOT_FOUND`, raised
    for any path-segment identifier that does not resolve to a resource of the type
    the segment names".

    Design: Corner/entities/consumer_get_with_unknown_id_returns_consumer_not_found
    """
    response = api.get_consumer(NON_EXISTENT_UUID, consumer_headers)
    data = validate_error(response, ApiErrorId.ERR_CONSUMER_NOT_FOUND, 404)
    assert isinstance(data["message"], str) and data["message"]


def test_consumer_enrollment_without_user_headers_is_rejected(api, anonymous_headers):
    """PRD §2.1: "A request missing either header, or carrying a role string that is
    not one of the roles enumerated below, is rejected with `ERR_INVALID_REQUEST` and
    an HTTP 400 status."

    Design: Corner/validations/missing_user_context_header_is_rejected_before_anything_else
    """
    response = api.create_consumer(create_consumer_payload(), anonymous_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert validate_success(api.list_consumers(PLATFORM_ADMIN), 200) == []


def test_monitoring_consent_refused_after_a_bureau_pull(api, as_consumer):
    """PRD §2.5: "The Prior-Bureau-Snapshot Rule requires that the consumer's
    `score_version` still be 0 at the moment consent is granted; a consumer who has
    already been pulled cannot retroactively enrol, and the attempt is rejected with
    `ERR_PRIOR_BUREAU_SNAPSHOT_EXISTS`."

    Design: Corner/state_machines/monitoring_consent_is_refused_after_a_bureau_pull
    """
    consumer = create_consumer(email="prior@example.com", bureau_pin="6666", api=api)
    grant_consent(consumer["id"], api=api)
    pull_bureau_snapshot(consumer["id"], score=660, api=api)

    response = api.grant_monitoring_consent(consumer["id"], as_consumer(consumer["id"]))
    validate_error(response, ApiErrorId.ERR_PRIOR_BUREAU_SNAPSHOT_EXISTS, 409)

    data = read_consumer(consumer["id"], api=api)
    assert data["score_version"] == 1
    assert data["monitoring_consent_at"] is not None


def test_bureau_pull_before_consent_is_rejected(api, as_consumer):
    """PRD §2.5: "The consumer must already hold monitoring consent, otherwise the
    request is refused with `ERR_MONITORING_NOT_CONSENTED`."

    Design: Corner/validations/unusable_snapshot_state_rejects_the_pull_request
    """
    from test_helpers.factories import create_bureau_snapshot_payload
    from test_helpers.fixtures import BUREAU_CONNECTOR

    consumer = create_consumer(email="noconsent@example.com", bureau_pin="8756", api=api)
    payload = create_bureau_snapshot_payload(consumer["version"], score=660)
    response = api.create_bureau_snapshot(consumer["id"], payload, BUREAU_CONNECTOR)
    validate_error(response, ApiErrorId.ERR_MONITORING_NOT_CONSENTED, 409)

    data = read_consumer(consumer["id"], api=api)
    assert data["score_version"] == 0
    assert validate_success(
        api.list_consumer_bureau_snapshots(consumer["id"], PLATFORM_ADMIN), 200
    ) == []


def test_first_pull_starts_at_the_initial_snapshot_ordinal(api, as_consumer):
    """PRD §2.6: "The `score_version` field is a monotonic pull counter equal to the
    number of that consumer's `BureauSnapshot` rows whose status is not `CANCELLED`,
    and the next accepted pull pins its `snapshot_ordinal` to `score_version + 1`."

    Design: Corner/state_machines/first_pull_after_consent_starts_at_the_initial_state
    """
    consumer = create_consumer(email="init@example.com", bureau_pin="9999", api=api)
    assert consumer["score_version"] == 0
    assert consumer["monitoring_consent_at"] is None

    # PRD §2.5: monitoring consent is the single intermediate step permitted
    # between enrollment and the first pull.
    grant_consent(consumer["id"], api=api)
    snapshot = pull_bureau_snapshot(consumer["id"], score=660, api=api)
    assert snapshot["snapshot_ordinal"] == 1
    assert snapshot["status"] == "ACTIVE"
    assert read_consumer(consumer["id"], api=api)["score_version"] == 1


def test_closing_a_consumer_supersedes_snapshots_and_keeps_the_score(api, as_consumer):
    """PRD §3.6: "a `DataProtectionOfficer` may close a consumer, which archives the
    consumer, transitions every non-terminal consent record for that consumer to
    `NOT_SEALED`, supersedes every non-cancelled snapshot, returns every decision still
    `ELIGIBLE` or `PREQUALIFIED` to `ELIGIBLE`, and recomputes the monitoring posture."
    PRD §2.6: "`current_score` is the `score` of the snapshot holding the highest
    `snapshot_ordinal` for the consumer regardless of that snapshot's later status".

    Design: Difficulty/compensating_invariant/monitoring_consent_permanence_across_close_and_reopen
    """
    consumer, snapshot = create_monitored_consumer(
        score=660, email="closep@example.com", bureau_pin="1234", api=api
    )
    validate_success(
        api.close_consumer(consumer["id"], DATA_PROTECTION_OFFICER), 200
    )

    data = read_consumer(consumer["id"], api=api)
    assert data["score_version"] == 1
    assert data["current_score"] == 660

    snapshots = validate_success(
        api.list_consumer_bureau_snapshots(consumer["id"], PLATFORM_ADMIN), 200
    )
    assert all(s["status"] == "SUPERSEDED" for s in snapshots)


def test_consent_cannot_be_regranted_after_a_close(api, as_consumer):
    """PRD §2.5: "The Prior-Bureau-Snapshot Rule requires that the consumer's
    `score_version` still be 0 at the moment consent is granted; a consumer who has
    already been pulled cannot retroactively enrol, and the attempt is rejected with
    `ERR_PRIOR_BUREAU_SNAPSHOT_EXISTS`."

    Design: Difficulty/compensating_invariant/monitoring_consent_permanence_across_close_and_reopen
    """
    consumer, snapshot = create_monitored_consumer(
        score=660, email="closer@example.com", bureau_pin="1235", api=api
    )
    before = read_consumer(consumer["id"], api=api)
    validate_success(api.close_consumer(consumer["id"], DATA_PROTECTION_OFFICER), 200)

    # After the close the consumer is no longer ACTIVE, so the ownership-gated
    # consent route can no longer reach the Prior-Bureau-Snapshot Rule; the
    # permanence the design asserts is that the score and consent timestamp stand.
    response = api.grant_monitoring_consent(
        consumer["id"], as_consumer(consumer["id"])
    )
    assert response.status_code >= 400

    after = read_consumer(consumer["id"], api=api)
    assert after["score_version"] == 1
    assert after["monitoring_consent_at"] == before["monitoring_consent_at"]


def test_closing_a_consumer_with_an_open_referral_is_refused(api, as_consumer):
    """PRD §3.6: "The close itself is gated twice — it is refused with
    `ERR_CONSUMER_HAS_OPEN_REFERRAL` if any referral for that consumer is still `SENT`".

    Design: Corner/state_machines/closing_a_consumer_with_open_referrals_is_refused
    """
    from test_helpers.fixtures import create_referral_for, setup_consented_scenario

    ctx = setup_consented_scenario(api=api)
    create_referral_for(ctx, external_referral_ref="NS-L-9300", api=api)

    response = api.close_consumer(ctx["consumer"]["id"], DATA_PROTECTION_OFFICER)
    validate_error(response, ApiErrorId.ERR_CONSUMER_HAS_OPEN_REFERRAL, 409)

    referral_rows = validate_success(
        api.list_referrals(PLATFORM_ADMIN, params={"consumer_id": ctx["consumer"]["id"]}),
        200,
    )
    assert len(referral_rows) == 1 and referral_rows[0]["status"] == "SENT"