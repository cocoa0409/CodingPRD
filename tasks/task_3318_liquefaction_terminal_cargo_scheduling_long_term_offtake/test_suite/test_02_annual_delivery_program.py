"""Annual delivery program construction: slots, revisions, lifecycle, ACQ cap."""
import pytest

from test_helpers import (
    CM,
    GS,
    OP,
    ApiErrorId,
    add_cargo_slot,
    create_cancelled_slot,
    create_commercial_train,
    create_confirmed_adp_with_slots,
    create_customer,
    create_draft_adp,
    create_spa_payload,
    get_success_data,
    make_customer_rep_headers,
    validate_error,
    validate_success,
)


class TestAdpInitialState:
    def test_adp_initial_states_on_create(self, api):
        """PRD §3.3: "The first revision receives `revision_no` 1 and is born
        `DRAFT`." PRD §3.6: "the pipeline starts `IN_SERVICE`" and "The schedule is
        born `OPEN`".

        Design: Corner/state_machines/adp_initial_states_on_create
        """
        customer = create_customer(legal_name="Gimel Gas")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        pipeline = get_success_data(
            api.create_pipeline({"name": "PL-9", "daily_capacity_mmbtu": 500000}, OP)
        )
        adp = get_success_data(
            api.create_adp(
                {
                    "spa_id": spa["id"],
                    "contract_year": 2027,
                    "expected_spa_version": spa["version"],
                },
                CM,
            )
        )
        schedule = get_success_data(
            api.create_day_schedule(
                pipeline["id"], {"gas_day": "2027-06-03", "capacity_mmbtu": 100000}, GS
            )
        )
        assert adp["status"] == "DRAFT", f"ADP must be born DRAFT, got {adp['status']}"
        assert adp["revision_no"] == 1, (
            f"first revision must be revision_no 1, got {adp['revision_no']}"
        )
        assert schedule["status"] == "OPEN", (
            f"day schedule must be born OPEN, got {schedule['status']}"
        )
        pipeline = get_success_data(api.get_pipeline(pipeline["id"], OP))
        assert pipeline["status"] == "IN_SERVICE", (
            f"pipeline must start IN_SERVICE, got {pipeline['status']}"
        )

    def test_slot_creation_computes_feed_gas_and_initial_statuses(self, api):
        """PRD §3.6: "Every cargo slot's feed-gas requirement is fixed at creation:
        `scheduled_feed_gas_mmbtu` is the slot quantity multiplied by 1.10 — the
        terminal assumes ten percent fuel and loss over delivered LNG — rounded up
        to a whole MMBTU."
        PRD §3.4: "`lift_status` tracks the physical lifting lifecycle — `SCHEDULED`
        ... — while its `billing_status` tracks invoicing — `UNBILLED`".

        Design: Corner/entities/cargo_slot_computed_feed_gas_input_ignored
        """
        customer = create_customer(legal_name="Tau Gasworks")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        resp = api.create_cargo_slot(
            adp["id"],
            {
                "window_start": "2027-02-01T00:00:00Z",
                "window_end": "2027-02-08T00:00:00Z",
                "quantity_mmbtu": 3000001,
                "scheduled_feed_gas_mmbtu": 1,
            },
            CM,
        )
        slot = validate_success(resp, expected_status=201)
        # ceil(3000001 * 1.10) == 3300002
        assert slot["scheduled_feed_gas_mmbtu"] == 3300002, (
            f"client-supplied feed gas must be ignored; server computes "
            f"ceil(3000001*1.10)=3300002, got {slot['scheduled_feed_gas_mmbtu']}"
        )
        assert slot["lift_status"] == "SCHEDULED"
        assert slot["billing_status"] == "UNBILLED"


class TestAdpRevisions:
    def test_adp_revision_supersede_reparents_slots(self, api):
        """PRD §3.3: "Creating another ADP for the same SPA and contract year
        produces the next revision (`revision_no` increments per superseding
        revision) and flips the prior revision — whatever its state, `DRAFT`,
        `PROPOSED`, or `CONFIRMED` — to `SUPERSEDED`; the superseded revision's
        non-`CANCELLED` cargo slots are re-parented to the new revision (their
        `adp_id` changes), and the scheduled and unallocated quantities on both
        revisions are recomputed, with both revisions' versions incremented."

        Design: Corner/entities/adp_revision_supersede_reparents_slots
        """
        customer = create_customer(legal_name="Upsilon Energy")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp1 = create_draft_adp(spa["id"], spa["version"])
        slot = add_cargo_slot(
            adp1["id"],
            window_start="2027-02-01T00:00:00Z",
            window_end="2027-02-08T00:00:00Z",
        )
        spa = get_success_data(api.get_spa(spa["id"], CM))
        adp2 = get_success_data(
            api.create_adp(
                {
                    "spa_id": spa["id"],
                    "contract_year": 2027,
                    "expected_spa_version": spa["version"],
                },
                CM,
            )
        )
        assert adp2["revision_no"] == 2, (
            f"second ADP revision must be revision_no 2, got {adp2['revision_no']}"
        )
        assert adp2["status"] == "DRAFT"
        adp1_after = get_success_data(api.get_adp(adp1["id"], CM))
        assert adp1_after["revision_no"] == 1
        assert adp1_after["status"] == "SUPERSEDED", (
            f"prior revision must flip to SUPERSEDED, got {adp1_after['status']}"
        )
        slot_after = get_success_data(api.get_cargo_slot(slot["id"], CM))
        assert slot_after["adp_id"] == adp2["id"], (
            f"slot must be re-parented to revision 2, got adp_id {slot_after['adp_id']}"
        )
        assert adp2["scheduled_quantity_mmbtu"] == 3600000

    def test_occ_stale_adp_revision_version(self, api):
        """PRD §2.8: "creating a new annual delivery program revision requires
        `expected_spa_version` matching the owning SPA's current `version`; a new
        revision supersedes the prior revision for the same contract year, so a
        stale expected version must fail rather than silently supersede state the
        client never observed." PRD §2.8: "the version-check failure, when it
        occurs, carries HTTP status 412 and the error id `ERR_STALE_VERSION`."
        PRD §3.3: "The SPA's `version` also increments when a new revision is
        created."

        Design: Corner/cross_cutting_layers/occ_stale_adp_revision_version
        """
        customer = create_customer(legal_name="Waw LNG")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        # commence requires a train in COMMERCIAL_OPERATION (PRD §3.1); walk one
        # to COD via the zero-required-cargoes path
        create_commercial_train(commissioning_cargoes_required=0)
        spa = get_success_data(api.commence_spa_deliveries(spa["id"], CM))
        spa_v = spa["version"]
        adp1 = create_draft_adp(spa["id"], spa_v)

        # revision-1 create bumped the SPA version, so replaying the same
        # expected_spa_version is now stale
        resp = api.create_adp(
            {
                "spa_id": spa["id"],
                "contract_year": 2027,
                "expected_spa_version": spa_v,
            },
            CM,
        )
        err = validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
        assert err["error_id"] == "ERR_STALE_VERSION"
        adp1_after = get_success_data(api.get_adp(adp1["id"], CM))
        assert adp1_after["status"] == "DRAFT", (
            f"failed revision create must not supersede revision 1, got "
            f"{adp1_after['status']}"
        )


class TestAdpApprovalGauntlet:
    def test_adp_propose_without_slots_rejected(self, api):
        """PRD §3.3: "Proposing by a `CommercialManager` moves `DRAFT` to `PROPOSED`
        and requires at least one cargo slot — proposing an empty program is
        rejected with `ERR_ADP_INVALID_STATE`."

        Design: Corner/state_machines/adp_propose_without_slots_rejected
        """
        customer = create_customer(legal_name="Phi Gas")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        resp = api.propose_adp(adp["id"], CM)
        err = validate_error(resp, ApiErrorId.ERR_ADP_INVALID_STATE.value)
        assert err["error_id"] == "ERR_ADP_INVALID_STATE"
        adp = get_success_data(api.get_adp(adp["id"], CM))
        assert adp["status"] == "DRAFT"

    def test_state_beats_fiscal_on_adp_confirm(self, api):
        """PRD §2.9: "the system evaluates them in a fixed order so that the
        surfaced error is deterministic: authentication and role authorization
        first, then existence of every path identifier and referenced body foreign
        key, then state legality of the requested transition, then business checks
        in their declared sequence — ... — the ACQ fiscal cap — and finally
        body-schema conformance."
        (The fixed sequence places state legality ahead of the ACQ fiscal cap, so
        a confirm against a DRAFT ADP that also breaches the ACQ cap surfaces the
        state error.)

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_adp_confirm
        """
        customer = create_customer(legal_name="Theta Gas Supply")
        spa = get_success_data(
            api.create_spa(
                create_spa_payload(
                    customer["id"], annual_contract_quantity_mmbtu=3000000
                ),
                CM,
            )
        )
        adp = create_draft_adp(spa["id"], spa["version"])
        add_cargo_slot(
            adp["id"],
            window_start="2027-02-01T00:00:00Z",
            window_end="2027-02-08T00:00:00Z",
            quantity_mmbtu=3600000,
        )
        resp = api.confirm_adp(adp["id"], make_customer_rep_headers(customer["id"]))
        err = validate_error(resp, ApiErrorId.ERR_ADP_INVALID_STATE.value)
        assert err["error_id"] == "ERR_ADP_INVALID_STATE"
        adp = get_success_data(api.get_adp(adp["id"], CM))
        assert adp["status"] == "DRAFT"

    def test_confirm_from_draft_rejected_even_within_acq(self, api):
        """PRD §3.3: "Out-of-order transitions (confirming a draft, locking a
        draft) are rejected with `ERR_ADP_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_adp_confirm
        """
        customer = create_customer(legal_name="Theta Gas Supply")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        add_cargo_slot(adp["id"], quantity_mmbtu=3600000)
        resp = api.confirm_adp(adp["id"], make_customer_rep_headers(customer["id"]))
        err = validate_error(resp, ApiErrorId.ERR_ADP_INVALID_STATE.value)
        assert err["error_id"] == "ERR_ADP_INVALID_STATE"
        adp = get_success_data(api.get_adp(adp["id"], CM))
        assert adp["status"] == "DRAFT"

    def test_acq_exceeded_at_confirm(self, api):
        """PRD §3.3: "the system enforces the fiscal cap — the sum of the program's
        cargo-slot quantities must not exceed the SPA's
        `annual_contract_quantity_mmbtu`, or the confirmation is rejected with
        `ERR_ACQ_EXCEEDED`."

        Design: Corner/validations/acq_exceeded_at_confirm
        """
        customer = create_customer(legal_name="Kaf Gas")
        spa = get_success_data(
            api.create_spa(
                create_spa_payload(
                    customer["id"], annual_contract_quantity_mmbtu=3000000
                ),
                CM,
            )
        )
        adp = create_draft_adp(spa["id"], spa["version"])
        add_cargo_slot(
            adp["id"],
            window_start="2027-02-01T00:00:00Z",
            window_end="2027-02-08T00:00:00Z",
            quantity_mmbtu=3600000,
        )
        get_success_data(api.propose_adp(adp["id"], CM))
        resp = api.confirm_adp(adp["id"], make_customer_rep_headers(customer["id"]))
        err = validate_error(resp, ApiErrorId.ERR_ACQ_EXCEEDED.value)
        assert err["error_id"] == "ERR_ACQ_EXCEEDED"

    def test_slot_window_outside_contract_year_rejected(self, api):
        """PRD §3.3: "The slot window must lie entirely within the ADP's contract
        year — from the first instant of the year up to, but not including, the
        first instant of the following year — and a window violating either bound
        is rejected with `ERR_SLOT_WINDOW_INVALID`"."

        Design: Corner/validations/slot_window_outside_contract_year_rejected
        """
        customer = create_customer(legal_name="Pe Energy")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        resp = api.create_cargo_slot(
            adp["id"],
            {
                "window_start": "2028-01-10T00:00:00Z",
                "window_end": "2028-01-17T00:00:00Z",
                "quantity_mmbtu": 3600000,
            },
            CM,
        )
        err = validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_INVALID.value)
        assert err["error_id"] == "ERR_SLOT_WINDOW_INVALID"

    def test_slot_window_reversed_rejected(self, api):
        """PRD §3.3: "each defined by a flexibility `window_start` (inclusive), a
        `window_end` (exclusive) that must be strictly after the window start".
        PRD §3.3: "a window violating either bound is rejected with
        `ERR_SLOT_WINDOW_INVALID`".

        Design: Corner/validations/slot_window_outside_contract_year_rejected
        """
        customer = create_customer(legal_name="Pe Energy")
        spa = get_success_data(api.create_spa(create_spa_payload(customer["id"]), CM))
        adp = create_draft_adp(spa["id"], spa["version"])
        resp = api.create_cargo_slot(
            adp["id"],
            {
                "window_start": "2027-02-08T00:00:00Z",
                "window_end": "2027-02-01T00:00:00Z",
                "quantity_mmbtu": 3600000,
            },
            CM,
        )
        err = validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_INVALID.value)
        assert err["error_id"] == "ERR_SLOT_WINDOW_INVALID"


class TestAdpQuantityConservation:
    def test_adp_quantity_conservation_on_cancellation(self, api):
        """PRD §3.3: "`scheduled_quantity_mmbtu` is the sum of `quantity_mmbtu`
        over the program's non-`CANCELLED` cargo slots; `cancelled_quantity_mmbtu`
        is the same sum over `CANCELLED` slots; `unallocated_quantity_mmbtu` is the
        SPA's annual contract quantity minus the scheduled quantity minus the
        cancelled quantity."

        Design: Difficulty/compensating_invariant/adp_quantity_conservation_on_cancellation
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {"quantity_mmbtu": 3600000},
                {
                    "window_start": "2027-09-01T00:00:00Z",
                    "window_end": "2027-09-08T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
            ],
            annual_contract_quantity_mmbtu=7200000,
        )
        adp_pre = get_success_data(api.get_adp(ctx["adp"]["id"], CM))
        assert adp_pre["scheduled_quantity_mmbtu"] == 7200000
        assert adp_pre["cancelled_quantity_mmbtu"] == 0
        assert adp_pre["unallocated_quantity_mmbtu"] == 0

        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        get_success_data(
            api.cancel_cargo_slot(ctx["slots"][0]["id"], ctx["rep"])
        )
        adp = get_success_data(api.get_adp(ctx["adp"]["id"], CM))
        assert adp["scheduled_quantity_mmbtu"] == 3600000, (
            f"scheduled must drop to 3600000, got {adp['scheduled_quantity_mmbtu']}"
        )
        assert adp["cancelled_quantity_mmbtu"] == 3600000
        assert adp["unallocated_quantity_mmbtu"] == 0

    def test_adp_quantity_invariant_holds_across_cancellation(self, api):
        """PRD §3.3: "`scheduled_quantity_mmbtu` is the sum of `quantity_mmbtu`
        over the program's non-`CANCELLED` cargo slots; `cancelled_quantity_mmbtu`
        is the same sum over `CANCELLED` slots; `unallocated_quantity_mmbtu` is the
        SPA's annual contract quantity minus the scheduled quantity minus the
        cancelled quantity."

        Design: Difficulty/compensating_invariant/adp_quantity_conservation_on_cancellation
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {"quantity_mmbtu": 3600000},
                {
                    "window_start": "2027-09-01T00:00:00Z",
                    "window_end": "2027-09-08T00:00:00Z",
                    "quantity_mmbtu": 3600000,
                },
            ],
            annual_contract_quantity_mmbtu=7200000,
        )
        acq = ctx["spa"]["annual_contract_quantity_mmbtu"]
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        get_success_data(api.cancel_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        adp = get_success_data(api.get_adp(ctx["adp"]["id"], CM))
        total = (
            adp["scheduled_quantity_mmbtu"]
            + adp["cancelled_quantity_mmbtu"]
            + adp["unallocated_quantity_mmbtu"]
        )
        assert total == acq, (
            f"scheduled + cancelled + unallocated must equal ACQ {acq}, got {total}"
        )
