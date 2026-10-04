"""Prior-year snapshots: supersession, carryforward import, and the import
guards (superseded snapshot, tax-year rule)."""
from test_helpers import (
    add_form,
    carryforward_item,
    create_account,
    create_return,
    create_snapshot,
    get_pending_prompt,
    get_return,
    get_snapshot,
    import_snapshot,
    list_prompts,
    make_taxpayer_headers,
    remove_form,
    seed_catalog,
    setup_return_with_forms,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestSnapshotSupersession:
    def test_reregistration_supersedes_earlier_snapshot(self, api):
        """PRD §3.3: "Registering a newer snapshot for the same account and
        tax year automatically moves any existing `AVAILABLE` or `IMPORTED`
        snapshot for that pair to `SUPERSEDED`; a superseded snapshot may
        never be imported, and an import attempt against one fails with
        `ERR_SNAPSHOT_SUPERSEDED` (HTTP 422)."

        Design: Corner/entities/snapshot_supersession_on_reregistration
        """
        account = create_account(email=unique_email("ent3"))
        old = create_snapshot(
            account, 2024, [carryforward_item("BASIS", "lot-1", 100000)]
        )
        assert old["import_status"] == "AVAILABLE"
        new = create_snapshot(
            account, 2024, [carryforward_item("BASIS", "lot-1", 150000)]
        )
        assert new["import_status"] == "AVAILABLE"
        assert get_snapshot(account, old["id"])["import_status"] == "SUPERSEDED"

    def test_superseded_snapshot_import_rejected(self, api):
        """PRD §3.3: "Registering a newer snapshot for the same account and
        tax year automatically moves any existing `AVAILABLE` or `IMPORTED`
        snapshot for that pair to `SUPERSEDED`; a superseded snapshot may
        never be imported, and an import attempt against one fails with
        `ERR_SNAPSHOT_SUPERSEDED` (HTTP 422)."

        Design: Corner/state_machines/superseded_snapshot_import_rejected
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("sm6"))
        ret = create_return(account)
        old = create_snapshot(
            account, 2024, [carryforward_item("BASIS", "lot-1", 100000)]
        )
        create_snapshot(account, 2024, [carryforward_item("BASIS", "lot-1", 150000)])
        resp = api.import_snapshot(
            account["id"], old["id"], ret.id, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_SUPERSEDED)
        assert get_return(ret)["minimum_required_tier"] == "FREE"

    def test_snapshot_year_not_prior_rejected(self, api):
        """PRD §3.3: "Two preconditions apply: the target return must be
        editable (`DRAFT` or `AMENDED`, else `ERR_RETURN_NOT_EDITABLE`), and
        the snapshot's `tax_year` must be strictly earlier than the return's
        `tax_year` (else `ERR_SNAPSHOT_YEAR_INVALID`, HTTP 422)."

        Design: Corner/validations/snapshot_year_not_prior_rejected
        """
        seed_catalog(tiers=("FREE",), forms=("F1040",))
        account = create_account(email=unique_email("val5"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        snapshot = create_snapshot(
            account, 2025, [carryforward_item("CAPITAL_LOSS", "lot-x", 10000)]
        )
        resp = api.import_snapshot(
            account["id"], snapshot["id"], ret.id, ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_YEAR_INVALID)
        assert get_snapshot(account, snapshot["id"])["import_status"] == "AVAILABLE"


class TestImportCascade:
    def test_import_supersedes_existing_prompt_and_recomputes(self, api):
        """PRD §3.3: "The import then runs the full recomputation pass —
        provisional minimum-tier classification, free-file eligibility, and
        the federal refund — and if the new minimum outranks the return's
        current tier, a `PENDING` upgrade prompt is created (superseding any
        existing pending prompt) exactly as in the question flow."
        PRD §3.3: "The snapshot itself moves `AVAILABLE` → `IMPORTED`."

        Design: Difficulty/transitive_cascade/snapshot_import_tier_prompt_cascade
        """
        seed_catalog(
            tiers=("FREE", "PREMIER", "SELF_EMPLOYED"), forms=("F1040", "SCH_D")
        )
        account = create_account(email=unique_email("casc2"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        add_form(ret, "SCH_D", -200000)
        prompt1 = get_pending_prompt(ret)
        assert prompt1 is not None, "Setup failed: expected a PENDING prompt"
        snapshot = create_snapshot(
            account, 2024, [carryforward_item("CAPITAL_LOSS", "stocks-2024", 200000)]
        )
        import_snapshot(account, snapshot["id"], ret)
        assert get_snapshot(account, snapshot["id"])["import_status"] == "IMPORTED"
        prompts = {p["id"]: p for p in list_prompts(ret)}
        assert prompts[prompt1["id"]]["status"] == "SUPERSEDED"
        after = get_return(ret)
        assert after["minimum_required_tier"] == "PREMIER"
        assert after["free_file_eligible"] is False
        assert after["upgrade_prompt_pending"] is True

    def test_import_creates_carryforward_forms_with_mapped_codes(self, api):
        """PRD §3.3: "On success, each carryforward entry materializes as a
        new `ReturnForm` with `source` `IMPORTED`, its
        `carryforward_item_type` set to the entry's item type, its
        `amount_cents` taken from `remaining_amount_cents`, and its form code
        mapped by type: `DEPRECIATION` becomes `F4562`, `CAPITAL_LOSS`
        becomes `SCH_D`, and `BASIS` becomes `F8949`."

        Design: Difficulty/transitive_cascade/snapshot_import_tier_prompt_cascade
        """
        seed_catalog(tiers=("FREE", "PREMIER"), forms=("F1040", "F4562"))
        account = create_account(email=unique_email("casc2b"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        snapshot = create_snapshot(
            account, 2024, [carryforward_item("DEPRECIATION", "truck", 50000)]
        )
        import_snapshot(account, snapshot["id"], ret)
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        rows = validate_success(forms)
        imported = [f for f in rows if f.get("source") == "IMPORTED"]
        assert len(imported) == 1
        assert imported[0]["form_code"] == "F4562"
        assert imported[0]["carryforward_item_type"] == "DEPRECIATION"
        assert imported[0]["amount_cents"] == 50000


class TestDerivedFieldReconciliation:
    def test_import_then_removal_reconciles_derived_fields(self, api):
        """PRD §3.2: "Every form add — and every form removal — triggers an
        eager **provisional classification**. The system considers only
        `ACTIVE` forms (removed rows are excluded from classification and
        refund math but retained for audit) and takes the highest `tier_rank`
        among the `minimum_tier` values of their form specs; the tier at that
        rank becomes the return's `minimum_required_tier`."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_import_and_removal
        """
        seed_catalog(tiers=("FREE", "PREMIER"), forms=("F1040", "SCH_D"))
        account = create_account(email=unique_email("cc3"))
        ret = create_return(account)
        add_form(ret, "F1040", 0)
        snapshot = create_snapshot(
            account, 2024, [carryforward_item("CAPITAL_LOSS", "lot-9", 75000)]
        )
        import_snapshot(account, snapshot["id"], ret)
        forms = api.list_forms(ret.id, make_taxpayer_headers(account["id"]))
        rows = validate_success(forms)
        imported = [f for f in rows if f.get("source") == "IMPORTED"][0]
        assert imported["form_code"] == "SCH_D"
        assert imported["amount_cents"] == 75000
        after_import = get_return(ret)
        assert after_import["minimum_required_tier"] == "PREMIER"
        assert after_import["free_file_eligible"] is False
        remove_form(ret, imported["id"])
        after_removal = get_return(ret)
        assert after_removal["minimum_required_tier"] == "FREE"
        assert after_removal["free_file_eligible"] is True
        assert after_removal["upgrade_prompt_pending"] is False
