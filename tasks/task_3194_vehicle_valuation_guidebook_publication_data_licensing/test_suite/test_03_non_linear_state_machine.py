"""Difficulty rule: non_linear_state_machine.

Cyclic state machines: Source suspension loop and LicenseAgreement
suspend/reactivate loop carrying monotonic snapshot state.
"""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    make_region, make_config, make_source, make_methodology, make_agreement,
    submit_batch, submit_rejected_batch, reject_n_batches, get_source,
    create_batch_item_payload,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestSourceProbationActiveSuspensionCycle:
    def test_reinstate_resets_counter_and_returns_to_probation(self, api):
        """PRD §3.2: "reinstatement of a suspended source moves it
        SUSPENDED -> PROBATION and resets its consecutive_rejections counter
        to zero."

        Design: Difficulty/non_linear_state_machine/source_probation_active_suspension_cycle
        """
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN")
        source = make_source(region["id"], source_type="AUCTION",
                             external_key="src-cyc", name="Cyc")
        reject_n_batches(source["id"], config["id"], region["id"], 5, "cyc")
        source = get_source(source["id"])
        assert source["status"] == "SUSPENDED"
        assert source["consecutive_rejections"] == 5

        reinstated = validate_success(
            api.reinstate_source(source["id"], DATAOPS), 200)
        assert reinstated["status"] == "PROBATION"
        assert reinstated["consecutive_rejections"] == 0

    def test_cycle_reentry_allows_new_batch_after_reinstate(self, api):
        """PRD §3.2: "A batch can only be submitted by a source that is not
        SUSPENDED — a suspended source's submissions are rejected with
        ERR_INVALID_STATE (HTTP 409)." and "reinstatement of a suspended
        source moves it SUSPENDED -> PROBATION and resets its
        consecutive_rejections counter to zero."

        After reinstatement the source is PROBATION (not SUSPENDED), so a new
        batch submission succeeds — the cycle may re-enter.

        Design: Difficulty/non_linear_state_machine/source_probation_active_suspension_cycle
        """
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN")
        source = make_source(region["id"], source_type="AUCTION",
                             external_key="src-cyc2", name="Cyc2")
        reject_n_batches(source["id"], config["id"], region["id"], 5, "cyc2")
        assert get_source(source["id"])["status"] == "SUSPENDED"

        validate_success(api.reinstate_source(source["id"], DATAOPS), 200)
        batch = validate_success(api.create_batch(
            {
                "source_id": source["id"],
                "submission_ref": "cyc2-after-reinstate",
                "items": [create_batch_item_payload(config["id"], region["id"])],
            },
            DATAOPS), 201)
        assert batch["status"] == "RECEIVED"


class TestLicenseAgreementActiveSuspendedReactivationCycle:
    def test_reactivation_bumps_activation_version(self, api):
        """PRD §3.8: "Suspension moves ACTIVE -> SUSPENDED; reactivation
        moves SUSPENDED -> ACTIVE, again requiring a published methodology
        and capturing a fresh snapshot with another activation_version
        increment (the methodology re-pin on resume)."

        Design: Difficulty/non_linear_state_machine/license_agreement_active_suspended_reactivation_cycle
        """
        make_methodology(publish=True, version_label="v2026.09",
                         formula_hash="hash-lc")
        agreement = make_agreement(permitted_uses=("UNDERWRITING",),
                                   monthly_event_quota=1500, activate=True,
                                   licensee_ref="lic-cyc")
        assert agreement["activation_version"] == 1

        validate_success(api.suspend_license_agreement(agreement["id"], ADMIN), 200)
        reactivated = validate_success(
            api.reactivate_license_agreement(agreement["id"], ADMIN), 200)
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["activation_version"] == 2

    def test_each_activation_captures_a_snapshot(self, api):
        """PRD §3.8: "Activation requires that a PUBLISHED methodology exist;
        it moves the agreement DRAFT -> ACTIVE, captures a Snapshot recording
        the currently published methodology's version_label, and increments
        the agreement's activation_version" and reactivation captures "a
        fresh snapshot with another activation_version increment".

        Design: Difficulty/non_linear_state_machine/license_agreement_active_suspended_reactivation_cycle
        """
        make_methodology(publish=True, version_label="v2026.09",
                         formula_hash="hash-lc2")
        agreement = make_agreement(permitted_uses=("UNDERWRITING",),
                                   monthly_event_quota=1500, activate=True,
                                   licensee_ref="lic-cyc2")
        validate_success(api.suspend_license_agreement(agreement["id"], ADMIN), 200)
        validate_success(api.reactivate_license_agreement(agreement["id"], ADMIN), 200)

        data, meta = validate_paginated(
            api.list_agreement_snapshots(agreement["id"], ADMIN))
        assert meta["total_count"] == 2
        labels = sorted(row["methodology_version_label"] for row in data)
        assert labels == ["v2026.09", "v2026.09"]
