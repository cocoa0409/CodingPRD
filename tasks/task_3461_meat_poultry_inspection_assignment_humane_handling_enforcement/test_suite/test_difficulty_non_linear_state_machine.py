"""Depth tests: non-linear state machines.

The Establishment carries two independent status dimensions on one row, and
the NoncomplianceRecord/Appeal pair forms a cycle (OPEN -> APPEALED -> OPEN on
remand) that can be traversed repeatedly before a terminal outcome.
"""

from test_helpers import (
    ApiErrorId,
    DISTRICT_MANAGER_HEADERS,
    assert_enforcement_action,
    fixtures as fx,
    make_establishment_manager_headers,
    factories as f,
    validate_error,
    validate_success,
    validate_paginated,
)


def _dimensions(api, est_id):
    data = validate_success(api.get_establishment(est_id, DISTRICT_MANAGER_HEADERS), 200)
    return data["grant_status"], data["inspection_status"]


class TestEstablishmentParallelDimensions:
    def _build_through_suspension(self, api):
        """Create -> grant -> egregious-confirm suspension. Returns the ids and
        the per-step dimension captures."""
        est = fx.create_establishment(
            api, name="D6 Sheep Plant", species_classes=["SHEEP"], slaughter_capable=True
        )
        captures = {"g0i0": _dimensions(api, est["id"])}
        application = fx.create_grant_application(api, est["id"])
        fx.begin_grant_review(api, application["id"])
        fx.record_all_adequate(api, application["id"])
        fx.decide_grant(api, application["id"], "GRANT")
        captures["g1i1"] = _dimensions(api, est["id"])
        pair = fx.create_inspector_pair(api, ["SHEEP"])
        cycle = fx.suspend_establishment_via_egregious_event(
            api, fx.get_establishment(api, est["id"]), pair["issuer"]["id"], pair["reviewer"]["id"],
            observed_at="2026-08-31T06:00:00Z",
        )
        captures["g2i2"] = _dimensions(api, est["id"])
        return est["id"], cycle, captures

    def test_grant_and_inspection_dimensions_move_independently(self, api):
        """PRD §2.5: "An Establishment carries two independent status dimensions
        on one row."
        PRD §2.5: "A newly registered establishment begins at `UNGRANTED` ×
        `INACTIVE`. Granting inspection moves the pair to `GRANTED` × `ACTIVE`
        in a single request. Suspension and lifting move only the inspection
        dimension (`ACTIVE` ↔ `SUSPENDED`); the grant dimension is untouched."

        Design: Difficulty/non_linear_state_machine/establishment_parallel_grant_and_inspection_dimensions
        """
        est_id, cycle, captures = self._build_through_suspension(api)

        fx.lift_enforcement(api, cycle["enforcement_action"]["id"])
        captures["g3i3"] = _dimensions(api, est_id)

        assert captures["g0i0"] == ("UNGRANTED", "INACTIVE")
        assert captures["g1i1"] == ("GRANTED", "ACTIVE"), "grant moves both dimensions"
        assert captures["g2i2"] == ("GRANTED", "SUSPENDED"), "suspension moves only inspection"
        assert captures["g3i3"] == ("GRANTED", "ACTIVE"), "lift cycles inspection back; grant holds"

    def test_lifted_auto_suspension_keeps_lifetime_count(self, api):
        """PRD §2.10: "`suspension_count` is the lifetime number of the
        establishment's enforcement actions of type `SUSPENSION` that have
        reached `IN_EFFECT`."
        PRD §3.4: "Lifting requires the action to be `IN_EFFECT` (otherwise
        `ERR_INVALID_STATE`) and requires `abatement_evidence` of at least 20
        characters (otherwise `ERR_INVALID_REQUEST`); the evidence is stored on
        the action, which moves to the terminal `LIFTED` status."

        Design: Difficulty/non_linear_state_machine/establishment_parallel_grant_and_inspection_dimensions
        """
        est_id, cycle, _captures = self._build_through_suspension(api)

        lifted = fx.lift_enforcement(api, cycle["enforcement_action"]["id"])

        assert_enforcement_action(lifted)
        assert lifted["status"] == "LIFTED"
        assert lifted["auto_created"] is True
        assert isinstance(lifted["abatement_evidence"], str) and len(lifted["abatement_evidence"]) >= 20
        data = validate_success(api.get_establishment(est_id, DISTRICT_MANAGER_HEADERS), 200)
        # The lifetime counter is not decremented by the lift.
        assert data["suspension_count"] == 1
        assert data["grant_status"] == "GRANTED"
        assert data["inspection_status"] == "ACTIVE"


class TestNoncomplianceRecordAppealCycle:
    def test_open_appealed_remand_reopen_appeal_vacate_cycle(self, api):
        """PRD §3.9: "Filing creates the appeal in `FILED` status and, in the
        same request, moves the record to `APPEALED`, recording the status it
        held at filing time in the record's `status_before_appeal` field."
        PRD §3.9: "An `outcome` of `REMAND` moves the appeal to `REMANDED` and
        the record from `APPEALED` back to `OPEN`, reopening the finding for
        correction and response."
        PRD §3.9: "An `outcome` of `VACATE` moves the appeal to `VACATED` and
        the record from `APPEALED` to `VACATED`."

        Design: Difficulty/non_linear_state_machine/noncompliance_record_appeal_cycle
        """
        fx.set_clock(api, "2026-09-01T06:00:00Z")
        est = fx.create_establishment(
            api, name="D7 Swine Plant", species_classes=["SWINE"], slaughter_capable=True
        )
        pair = fx.create_inspector_pair(api, ["SWINE"])
        record = fx.issue_nr(
            api, est["id"], pair["issuer"]["id"],
            regulation_family="SANITATION",
            description="peeled paint over evisceration",
            observed_at="2026-09-01T05:00:00Z",
        )

        appeal1 = fx.file_appeal(api, record["id"], est["id"], grounds="grounds-text-one")
        mid = fx.get_nr(api, record["id"])
        assert mid["status"] == "APPEALED"
        assert mid["status_before_appeal"] == "OPEN", "status at filing time recorded"

        fx.decide_appeal(api, appeal1["id"], pair["reviewer"]["id"], "REMAND")
        reopened = fx.get_nr(api, record["id"])
        assert reopened["status"] == "OPEN", "remand re-opens the record (the cycle edge)"

        appeal2 = fx.file_appeal(api, record["id"], est["id"], grounds="grounds-text-two")
        fx.decide_appeal(api, appeal2["id"], pair["reviewer"]["id"], "VACATE")
        vacated = fx.get_nr(api, record["id"])
        assert vacated["status"] == "VACATED", "second traversal reaches the terminal outcome"

    def test_vacated_record_rejects_further_writes(self, api):
        """PRD §3.9: "All three appeal outcomes are terminal for the appeal, and
        `VERIFIED` and `VACATED` are terminal for the record."
        PRD §3.3: "Verification is defined from either `OPEN` or
        `RESPONSE_SUBMITTED` (otherwise `ERR_INVALID_STATE`)"
        PRD §3.9: "Filing requires the record to be `OPEN`, `RESPONSE_SUBMITTED`,
        or `ESCALATED` (otherwise `ERR_INVALID_STATE`)"

        Design: Difficulty/non_linear_state_machine/noncompliance_record_appeal_cycle
        """
        est = fx.create_establishment(
            api, name="D7 Terminal Plant", species_classes=["SWINE"], slaughter_capable=True
        )
        pair = fx.create_inspector_pair(api, ["SWINE"])
        vacated = fx.create_vacated_nr(api, est["id"], pair["issuer"]["id"], pair["reviewer"]["id"])
        record = vacated["record"]
        assert record["status"] == "VACATED"

        verify_resp = api.verify_nr_response(
            record["id"], f.verify_response_payload("VERIFY"), fx.make_inspector_headers(pair["issuer"]["id"])
        )
        validate_error(verify_resp, ApiErrorId.ERR_INVALID_STATE)

        respond_resp = api.respond_to_nr(
            record["id"],
            f.nr_response_payload("late response"),
            make_establishment_manager_headers(est["id"]),
        )
        validate_error(respond_resp, ApiErrorId.ERR_INVALID_STATE)

        appeal_resp = api.create_appeal(
            f.appeal_payload(record["id"], "grounds-text-three"),
            make_establishment_manager_headers(est["id"]),
        )
        validate_error(appeal_resp, ApiErrorId.ERR_INVALID_STATE)

        # Nothing moved: still VACATED, and the record list shows no reopening.
        assert fx.get_nr(api, record["id"])["status"] == "VACATED"
        rows, meta = validate_paginated(api.list_appeals(record["id"], DISTRICT_MANAGER_HEADERS))
        assert len(rows) == 1, f"only the first appeal exists, got {len(rows)}"
