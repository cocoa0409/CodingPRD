# Worklog — task_3217_user_generated_experience_economy_developer_payouts_age

## Step 1: Create Task Directory — 2026-09-30T11:12:03.000Z

Pre-allocated task directory confirmed: `tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/` already exists; index not computed per invocation instructions.

## Step 2: Generate Scaffold — 2026-09-30T11:29:05.000Z

  All three files are well-formed and lint clean. Let me verify the SCAFFOLD.yaml doesn't contain `scaffold_difficulty_design` or `scaffold_corner_design` as top-level keys (it doesn't, per the output above). The top-level keys are: scenario, domain_name, api_prefix, complexity_profile, response_envelope (and entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles below).
  
  **Final verdict block from scaffold_lint.py:**
  
  ```
  SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  ============================================================
    SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD.yaml
    Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD_DIFFICULTY_DESIGN.yaml
    Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD_CORNER_DESIGN.yaml
  
  Coverage
    §1.5 endpoints declared:    84
    §1.1 entities declared:     18
    §1.8 instances scanned:     18
    §1.9 instances scanned:     23
    Calls scanned (§1.8+§1.9):  362
  
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
  
  ## Summary
  
  Generated scaffold for task_3217_user_generated_experience_economy_developer_payouts_age (Roblox-style UGC economy):
  
  **Files written:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD.yaml` (1799 lines) — §1.0–§1.7
  - `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1289 lines) — §1.8, 18 instances (9 rules × 2)
  - `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/SCAFFOLD_CORNER_DESIGN.yaml` (1032 lines) — §1.9, 23 instances across 7 sections
  
  **Difficulty design (much harder than expert):**
  - **18 entities** (above Expert band 10-15): User, IdentityVerification, TaxDocument, ParentalControls, Experience, ExperienceAgeRating, ModerationSubmission, ModerationAppeal, CurrencyPurchaseOrder, PurchaseOrder, DevExchangeRequest, MarketplaceItem, ResaleListing, ChatMessage, Report, AccountTermination, EngagementSnapshot, AuditLog
  - **84 endpoints** (well above Expert band 20-32)
  - **29 error codes** (above Expert band 18-30)
  - **11 calculations** with 5+ dual-variant / combinatorial cases
  - **10 state machines** including fork-join (ModerationSubmission), parallel dimensions (User.status × is_devex_eligible), and cascades
  - **2 OCC concurrency rules** on User and MarketplaceItem
  - **Complexity profile:** primary=ledger_reconciliation, secondary=compliance_audit; 7 cross-cutting layers including selector_policy, scheduled_actions, dual_variant_calculation
  
  **Harder-than-expert mechanics engineered in:**
  - Tiered currency exchange with sum-then-round (mode b) and a promotional variant that rounds twice
  - Progressive DevEx ladder (mode a, 4 brackets, marginal rates) paired with progressive withholding tax (mode b, nested rounding against the already-rounded ladder output) and explicit evaluation-order pinning (mode c)
  - Asymmetric boundary operators: parental spend `>=` rejects at exactly the limit, resale floor `>=` accepts at exactly the floor, moderation thresholds `>=0.85` / `<=0.10`
  - Calendar-month (parental spend) vs rolling-7-day (resale eligibility) interval semantics for Rule 8
  - Cross-entity gating: PurchaseOrder → MarketplaceItem, Experience → User (creator age vs assigned rating)
  - Depth-3 transitive cascade: Report.action(TERMINATE_SENDER) → AccountTermination → DevExchangeRequest cancel → User.TERMINATED
  - Compensating invariants on both robux_balance and earned_robux_lifetime
  - Segregation of duties: FinanceOfficer who approves cannot mark paid; appeals reviewer cannot equal original moderator; termination initiator cannot be the terminated user
  
  All 362 setup/trigger calls across both design files lint clean against §1.5 (paths, roles, payload shapes, captures, OCC placeholders, FK reverse-reachability).

## Step 3: Copy Shared Files — 2026-09-30T11:29:40.000Z

Copied `INSTRUCTION.md` → `tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T11:37:20.000Z

  All checks pass. PRD generation is complete.
  
  ## Report
  
  **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/PRD.md`
  
  **What was generated.** A full PRD for the UGC experience economy / DevEx payouts / age-ratings domain, structured as: §1 Introduction (2 paragraphs), §2 Global Specifications with nine domain-derived subsections (roles & identity model with entity-backed `Creator` vs opaque operator roles; verbatim §2.2 envelope; pagination; common resource properties including the `common_fields: false` carve-out for `EngagementSnapshot`/`AuditLog`; the eight-step validation priority order; the two OCC rules `expected_user_version`/`expected_item_version`; integer-Robux + half-up rounding discipline; the platform logical clock starting at 2026-09-01T00:00:00Z; audit/idempotency), §3 Business Logic in twelve subsections organized by workflow (accounts & parental controls, identity/tax/DevEx eligibility, tiered currency exchange, experience publishing & moderation pipeline, appeals, marketplace & resale waterfall, purchases & parental spend cap with the strict `>=` boundary, engagement payouts, age-rating access, chat & reports, termination disposition, DevEx progressive ladder + withholding), §4 endpoint table (4 columns, 77 endpoints), §5 error catalogue (2 columns, 29 errors).
  
  **Hard contract reports:**
  - Contract 1 (Field-Name Coverage): entity fields 111 required / 111 present / 0 missing; endpoint inputs 69 required / 69 present / 0 missing — PASS (after repairing `content_descriptors`, `message_id`, `reporter_user_id` found on the first pass).
  - Contract 2 (Rule Coverage): all 11 state machines' transitions with preconditions, side-effects and cascades expressed (user suspension cascade with reinstatement non-reversal, moderation auto-route thresholds 0.85/0.10 with pinned inclusive boundaries, CHILD-creator SEVENTEEN_PLUS publish block, appeal overturn retroactive cascade, resale 7-day account-age gate, disposition-reason consistency matrix, officer approve/pay segregation); all 11 calculations rendered as precise natural-language formulas with constants embedded (tiered exchange 0.80/0.90/1.00/1.10 with sum-then-round and the promo-bonus variant on the rounded sum, 30% marketplace fee waterfall with fee-first royalty-second order pinned, DevEx brackets 0.35/0.38/0.40/0.42 applied to gross before withholding, W9 progressive withholding vs W8BEN/W8BENE flat 30%, engagement rates 2/3/4/5 per hour by rating, parental spend strict `>=` rejection at the exact limit, resale floor `floor(price*0.5)` inclusive with the 101→50 worked example); all 8 validation priority tiers stated in explicit order; both OCC rules named with endpoint framing, occ field, `ERR_STALE_VERSION`/412; verification script confirms 0 missing across validations/calculations/states/errors — PASS.
  - Contract 3 (§3 Path Purity): 535 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS.
  
  **Additional checks:** §2.2 matches `section-2.2-response-structure.md` byte-for-byte; all 29 error IDs appear in §2/§3 prose; all 27 state values and all 53 enum field values appear verbatim; all 7 role names spelled exactly with `identity:` translated per-role in §2.1. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Step 5: Generate Unit Tests — 2026-09-30T12:00:05.000Z

  Generation complete. Report:
  
  ## Task 3217 — Unit test generation complete
  
  **Generated** (under `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/`):
  
  - `test_helpers/` (9 files, ~1,800 lines): `types.py` (all 19 entity TypedDicts; append-only `EngagementSnapshot`/`AuditLog` correctly omit `updated_at`/`version`), `api_client.py` (one method per PRD endpoint), `api_errors.py` (full §5 catalog registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (executable PRD formulas: tiered exchange, DevEx ladder, W9/W8 withholding, marketplace split/waterfall, engagement rates, resale floor — all sanity-checked against hand-derived values), `test_users.py` (`make_creator_headers` for the entity-backed Creator role; distinct officer IDs for segregation tests), `fixtures.py` (notably `setup_devex_eligible_user` which raises `earned_robux_lifetime` via published-experience engagement + monthly settlement and ages the account past 30 days via the clock — earned Robux cannot come from currency purchases).
  - `test_suite/` (conftest + 9 files): **53 tests**, all collecting cleanly under pytest.
  
  **Coverage audit**: 15/18 difficulty instances with ≥2 tests each; 23/23 corner instances with ≥1 test each. Every test docstring carries verbatim-grep-verified PRD citations plus exactly one `Design:` tag resolving to a real instance name.
  
  **3 instances SKIPPED under the PRD-first rule** (gaps left as gaps, no placeholders):
  1. `Difficulty/priority_pair_validation_conflict/state_vs_referential_on_appeal_file` — asserts a suspended appellant gets `ERR_INVALID_STATE` when filing an appeal, but no PRD sentence requires the appellant to be ACTIVE; the outcome is not uniquely derivable.
  2. `Difficulty/cross_entity_state_dependency/experience_publish_blocked_when_creator_age_insufficient_for_rating` — requires forcing the moderation pipeline to assign `SEVENTEEN_PLUS`, but the PRD exposes no input controlling descriptor sets or the descriptor→rating mapping.
  3. `Difficulty/resource_temporal_overlap/resale_account_age_window_rolling_interval` — the scaffold gates listing *creation* at `account_age_days >= 7`, but the PRD places the seven-day gate on the sale-confirmation transition and names no error for it; PRD wins, so the asserted creation-time rejection isn't covered.
  
  **Notable corrections to design-index arithmetic** (PRD is the contract): the `currency_exchange_base_vs_promotional_bonus` yaml's self-corrected value of 4899 for 5500 cents is wrong — the tiered sum is 799.2+3600+501 = 4900.2 → **4900**; the test asserts the PRD-derived value. The `safety_vs_fiscal_on_purchase_confirm` recipe's spend narrative was internally inconsistent with the strict `>=` limit; the test was rebuilt (limit 400, then 350+60) so the safety and fiscal checks genuinely both fail. The `missing_auth_header_returns_400` corner recipe's assert contradicted its own name; the test follows the instance's claim (headers omitted → 400), which the PRD covers verbatim.
  
  No server processes were started or killed; tests assume the runner-managed `API_BASE_URL` as specified.

## Step 6: Generate Implementation — 2026-09-30T12:30:30.000Z

  Done. Complete Python + Flask implementation generated and smoke-tested at `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/implementation/`:
  
  **Files**
  - `start.sh` — guarded dependency install (`import flask` check) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
  - `app.py` — Flask entry, blueprint registration, `ApiError`/404/405/500 handlers
  - `db.py` — in-memory store, empty on every boot (no seeding), logical clock starting at 2026-09-01T00:00:00Z
  - `errors.py`, `response.py`, `middleware.py`, `util.py` — error catalog, envelope (`meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more`), `X-User-ID`/`X-User-Role` auth, pagination (default 10, 1-100), timestamps (3 fractional digits), audit log writer
  - `services.py` — all calculations with `Decimal` ROUND_HALF_UP on final aggregates only: tiered currency exchange (999@0.80/4000@0.90/15000@1.00/rest@1.10, marginal), marketplace split (fee-first 30%, then royalty on post-fee share for resales), DevEx ladder (30000@0.35/70000@0.38/900000@0.40/rest@0.42), W9 progressive withholding vs flat 30% W8BEN(E), engagement payout (floor(M/60)*rate by rating), age-band (365.2425 avg years, birthday-inclusive), rating access by band ordering
  - `routes_core.py`, `routes_money.py`, `routes_safety.py` — all 60+ endpoints
  
  **Verified by smoke tests** (server killed by exact PID afterward; nothing left running):
  - Tiered exchange, idempotent replay vs `ERR_DUPLICATE_IDEMPOTENCY_KEY` on payload mismatch
  - Moderation pipeline: inject_score thresholds (0.85 reject / 0.10 approve), HUMAN_REVIEW decide with self-review SoD, escalate → QUEUED with different-second-reviewer SoD
  - Appeals: `ERR_SUBMISSION_NOT_REJECTED` gate, appeals-reviewer SoD, OVERTURNED cascade replays approval with `APPEAL_DECISION` rating superseding
  - Resale: floor 50 on price 101 (49 → `ERR_RESALE_FLOOR_VIOLATION`, 50 OK), `expected_item_version` OCC → 412, 7-day seller age gate, waterfall (fee 15, royalty 7, seller credit 28 on a 50-robux resale at 20% royalty)
  - Parental spend cap strict `>=` (at-cap rejected, below-cap OK), RESTRICTED chat → `ERR_PARENTAL_CHAT_RESTRICTED`, SAFE filter strips digits/punctuation, CHILD viewers get filtered experience descriptions
  - DevEx: eligibility derivation, `ERR_DEVEX_MINIMUM_NOT_MET` before eligibility, ladder+W9 withholding (30000 robux → 10500/50/10450), approve/pay officer SoD, stale-version 412
  - Suspension cascade (listings cancelled, experiences SUSPENDED, devex cancelled; reinstate doesn't undo), termination pipeline (dispose → COMPLETE → user TERMINATED, balance zeroed, lifetime preserved, 30-day FORFEIT clawback to REVERSED), archive settles pending engagement payout, monthly settle endpoint
  
  Judgment calls documented in code comments: item copy ownership tracked via a private `_owners` list (scaffold lacks an Ownership entity); rating derived from descriptor severity map (GAMBLING_SIMULATED→SEVENTEEN_PLUS, ALCOHOL_REFERENCE→THIRTEEN_PLUS, VIOLENCE_MILD→NINE_PLUS); NINE_PLUS allows any viewer aged ≥9 (per "admits a CHILD only when at least nine"); tax documents land directly in UNDER_REVIEW per PRD's auto-transition; termination EARNINGS_DISPOSED→COMPLETE chained in the same call per "system once disposition side effects settle".

## Step 7: Run Tests and Iterate — 2026-09-30T12:42:00.000Z

  All 8 rounds pass 53/53. Clean exit.
  
  ---
  
  **Summary**
  
  - **Iterations run**: 3 sweeps (initial + 2 after fixes).
  
  - **Tests deleted**: none.
  
  - **Fixes applied to `test_helpers/`**:
    - `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/test_helpers/factories.py` — `create_limited_item_payload`: pre-seed `item_kind="LIMITED_HAT"` into `overrides` before delegating to `create_marketplace_item_payload` (whose own default `"HAT"` was winning via setdefault), so the resulting payload is actually a LIMITED_* kind and the `total_supply` / `royalty_pct` defaults are legal under PRD §3.5's "for non-limited kinds, `total_supply` must be null and `royalty_pct` must be 0". This unblocked 4 tests across `TestResalePriceFloor`, `TestResaleOptimisticConcurrency`, `TestSuspensionCascade`.
  
  - **Fixes applied to `test_suite/`** (all PRD §3.1 username rule — "a unique handle of three to twenty characters"):
    - `test_01_accounts_auth_and_defaults.py` `test_user_create_returns_full_envelope_and_initial_state`: `"u1"` → `"u_1"` (was 2 chars).
    - `test_03_moderation_pipeline.py` `test_automated_moderation_score_at_boundaries`: `f"c{i+1}"` → `f"cr_{i+1}"` (was 2 chars).
    - `test_04_marketplace_split_and_refunds.py` `test_marketplace_split_limited_resale_royalty_waterfall`: `"oc"`, `"rs"`, `"bb"` → `"oc_x"`, `"rs_x"`, `"bb_x"`.
  
  - **Fixes applied to `implementation/`**:
    - `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/implementation/routes_money.py` `confirm_purchase_order`: in the primary `MARKETPLACE_ITEM` settlement branch, when the item `is_limited`, append the buyer to the item's `_owners` list. PRD §3.6 ("A `Creator` lists a limited item they own" — for the reseller flow to be reachable at all, primary purchase of a limited must grant the buyer ownership) requires this; without it, only the original creator could ever list a limited for resale and the entire waterfall path in §3.7 was unreachable.
  
  Final state: 53/53 passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-09-30T12:45:30.000Z

  Done. `/home/ubuntu/github/CodingPRD/tasks/task_3217_user_generated_experience_economy_developer_payouts_age/workspace/PRD_FINALIZED.md` created with a minimal, scope-bounded patch.
  
  **Line counts / delta**: PRD.md 317 lines, PRD_FINALIZED.md 317 lines (0% line-count delta; two sentences expanded inline, no sections added or removed).
  
  **Changes**
  
  - §3.6 (Marketplace) — revise — after "subsequent sales run through the resale pipeline", appended sentences pinning that limited-item ownership is a set of owners: the creator holds a copy from creation, each completed primary purchase of a limited grants the buyer ownership (without removing existing owners), only a current owner may list for resale, a confirmed resale transfers ownership seller→buyer, and a resale refund reverses the transfer — `implementation/routes_money.py:610` (creator seeded into `_owners`), `routes_money.py:990-994` (primary purchase appends buyer, no removal), `routes_money.py:978-981` (resale transfers seller→buyer), `routes_money.py:1032-1035` (refund reverses), `routes_money.py:737` (ownership gate on listing creation).
  - §3.7 (Purchases/refunds) — revise — extended the resale-refund sentence: refunding a resale "also reverses the ownership transfer so the item returns to the seller" — `implementation/routes_money.py:1032-1035`.
  
  **Step-7 diff items that required no PRD edit**
  
  - test_helpers `create_limited_item_payload` fix — pure fixture bug (factory default `HAT` shadowing `LIMITED_HAT` via setdefault); PRD §3.5's non-limited structural rule already matches impl (`routes_money.py:589-593` accepts `royalty_pct` of null or 0 for non-limited kinds, which covers both the PRD text and the fixture default). No PRD silence.
  - Three username test fixes (`"u1"`→`"u_1"` etc.) — pure test bugs; PRD §3.1 already pins "three to twenty characters" and impl `routes_core.py:88` enforces `min_len=3, max_len=20` exactly. No PRD silence.
  
  **Pre-edit search log**
  
  Edit 1 (§3.6 ownership sentences):
  - (a) Subject: limited-item copy ownership — who holds a copy and how primary purchase, resale, and refund mutate it.
  - (b) Paths enumerated and read: `routes_money.py:600-612` (`create_item` — `_owners` seeded with creator for limited kinds, empty otherwise), `routes_money.py:712-758` (`create_listing` — `actor not in item.get("_owners", [])` gate at line 737), `routes_money.py:900-1010` (`confirm_purchase_order` — primary limited purchase appends buyer at 990-994; resale removes seller/appends buyer at 978-981), `routes_money.py:1012-1058` (`refund_po` — resale refund checks buyer ownership at 1020 and restores seller ownership at 1032-1035; non-limited refund path touches only `copies_sold`, no ownership), `routes_safety.py:341-365` (termination `REVERSED` path — touches only order status, no ownership), `services.py` (no ownership logic), `response.py`/`_public` at `routes_money.py:66-67` (underscore-prefixed fields never exposed in API responses, so no resource-shape wording needed). `LIMITED_ITEM_RESALE` creation path (`create_po`) does not touch `_owners`.
  - (c) Wording adjustment: initial draft said "item ownership transfers to the buyer"; after enumerating the primary-purchase path (which does *not* remove the creator) I re-scoped to a "set of owners" model and stated the resale transfer is seller→buyer specifically, matching all enumerated paths.
  
  Edit 2 (§3.7 refund sentence):
  - (a) Subject: resale refund's effect on item ownership.
  - (b) Paths enumerated: `routes_money.py:1012-1036` (resale branch of `refund_po` — the only refund path that mutates `_owners`); confirmed the non-resale branches (1037-1047) do not touch ownership, and that no other refund/reversal path (currency-order refund `routes_money.py:540-562`, termination reversal `routes_safety.py:341-365`) mutates ownership.
  - (c) Wording kept narrow ("refunding a resale also reverses the ownership transfer") — no universal claim about other refund types, so all enumerated paths remain consistent.

## Step 9: Complete PRD — 2026-09-30T12:58:15.000Z

  All 26 paragraph edits applied cleanly. Work complete.
  
  ## Summary
  
  **Source**: `PRD_FINALIZED.md` (317 lines / 57,325 chars) → `PRD_COMPLETED.md` (320 lines / 67,636 chars), char-delta **+10,311**.
  
  **Counts**: 24 ambiguity-pins, 3 mismatch-revisions (one hunk §3.1 carries both a pin and a boundary revision; counted once under mismatch).
  
  Changes (all inline in-paragraph; no new sections):
  
  - §2.1 — insert — ambiguity — defines "malformed header" concretely and pins that an unrecognized `Creator` X-User-ID passes header validation but fails as `ERR_USER_NOT_FOUND` when the acting user must be resolved — middleware.py:25-34; routes_money.py:455-457
  - §2.2 — insert — ambiguity — pins synthetic `data` payloads for clock set, monthly settlement, parental-controls write — routes_core.py:77, 280, 734
  - §2.2 — insert — ambiguity — pins that parental-controls GET and per-user IV/tax lists return array envelope with pagination meta — routes_core.py:296, 345, 431
  - §2.2 — insert — ambiguity — pins resource-id charset (UUID, lowercase) vs `req_` id charset (uppercase alnum) — response.py:10; util.py:16
  - §2.3 — insert — ambiguity — pins non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST`, `created_at` then `id` tie-break, and equality filter query params incl. boolean spellings — util.py:154-206
  - §2.5 — insert — ambiguity — pins 404 mapping for uncatalogued resources (IV/TD→`ERR_USER_NOT_FOUND`, DevEx→`ERR_ORDER_NOT_FOUND`, age-rating→`ERR_EXPERIENCE_NOT_FOUND`, chat/audit/unmatched route→`ERR_INVALID_REQUEST`) — routes_core.py:351, 437; routes_money.py:1062; routes_safety.py:60, 432, 457; app.py:27
  - §2.5 — insert — ambiguity — pins DevEx submission fiscal sub-order: minimum → eligibility → over-earned → stale version — routes_money.py:1090-1098
  - §3.1 — insert — ambiguity — pins username full-match regex and duplicate rejection as `ERR_INVALID_REQUEST` — routes_core.py:88, 105-107
  - §3.1 — revise — mismatch — age-band boundary: pins the exact `floor(days/365.2425)` formula and notes the accepted drift, replacing the absolute "boundary lands on the birthday itself" claim — services.py:25-33
  - §3.1 — insert — ambiguity — suspension `reason` is optional (null allowed) — routes_core.py:201
  - §3.1 — insert — ambiguity — `pin_hash` stored but never re-verified; GET parental-controls takes `child_user_id` query param — routes_core.py:239, 290-292
  - §3.1 — insert — ambiguity — pins that `chat_filter_level` follows band alone unless `RESTRICTED` (`FILTERED`/`OPEN` do not alter it) — services.py:64-72
  - §3.2 — insert — ambiguity — latest-submitted IV/TD row governs eligibility; strict `current_utc > expiry_date` comparison; lazy expiry sweep points (clock set, IV list, eligibility check) — services.py:88-115; routes_core.py:73-75
  - §3.2 — insert — ambiguity — tax `SUBMITTED` phase is instantaneous (row observable only as `UNDER_REVIEW`) — routes_core.py:408
  - §3.3 — insert — ambiguity — pins that no request surface can attach a promotion code, so the ×1.10 bonus is specified but unreachable — routes_money.py:458-461
  - §3.4 — insert — ambiguity — pins descriptor→rating max-severity map (GAMBLING_SIMULATED→SEVENTEEN_PLUS, ALCOHOL_REFERENCE→THIRTEEN_PLUS, VIOLENCE_MILD→NINE_PLUS, else ALL) and that create-experience accepts no descriptors — routes_money.py:58-63, 185-197; routes_core.py:502
  - §3.4 — insert — ambiguity — cascades apply only while subject is in the expected pre-decision state; escalated submissions wait in `QUEUED` (no automatic re-dispatch) — routes_money.py:226-259, 289-294
  - §3.4 — insert — ambiguity — `visit_count_lifetime` has no join surface in this API (stays 0); republish clears `suspended_reason` — routes_core.py:503, 604-605
  - §3.5 — revise — mismatch — OVERTURNED always writes a new rating row (`supersedes_id` null when none) and publishes only from `DRAFT`; a `SUSPENDED` experience keeps its new rating but stays `SUSPENDED` until re-publish — routes_money.py:405-416
  - §3.6 — insert — ambiguity — resale creation gates: limited-only (`ERR_INVALID_REQUEST`), seller `account_age_days` ≥ 7 at listing time (`ERR_INVALID_STATE`), item `ON_SALE` (`ERR_ITEM_NOT_ON_SALE`), validated version pinned on the listing — routes_money.py:730-743
  - §3.6 — insert — ambiguity — resale confirm: seller's `earned_robux_lifetime` also grows; royalty accrues to original creator's lifetime earnings only, not their spendable balance — routes_money.py:966-972
  - §3.7 — insert — ambiguity — parental spend window measured against the platform logical clock via stored completion instants — routes_money.py:886-896, 1003
  - §3.7 — insert — ambiguity — `copies_sold` increments on primary completion incl. limited; limited primary purchase adds buyer to owner set; gamepass credits the experience's creator — routes_money.py:986-997
  - §3.7 — insert — ambiguity — refund side effects (resale royalty clawback, seller balance debit, `copies_sold` decrement floor 0, limited owner retained); 30-day REVERSED window on logical clock; only `FORFEIT_TO_PLATFORM` triggers reversal — routes_money.py:1009-1053; routes_safety.py:340-364
  - §3.8 — insert — ambiguity — unrated experience settles at `ALL` rate; `snapshot_date` optional defaulting to current platform date; `ARCHIVED` snapshot → `ERR_INVALID_STATE`; 30-day window is inclusive `current_utc`−29d..`current_utc` — services.py:254-256; routes_core.py:672-704
  - §3.9 — insert — ambiguity — `NINE_PLUS` age test uses the same average-year formula; empty `allowed_age_ratings` imposes no restriction — services.py:147-170
  - §3.10 — revise — mismatch — filter level applied is simply the sender's own `chat_filter_level` (no viewer-level merging); plus pins: SAFE strips all but letters/space/apostrophe/hyphen, STANDARD hashes blocked whole words case-insensitively, CHILD-viewer recognition only for resolvable `Creator` callers, no `PUBLISHED` gate on sending — routes_safety.py:91-104; util.py:210-226; routes_core.py:57-60, services.py:77-83
  - §3.10 — insert — ambiguity — SUSPEND_SENDER records reason "chat safety action" and is a no-op on already-suspended senders; TERMINATE_SENDER pins `earnings_disposition` FORFEIT_TO_PLATFORM — routes_safety.py:224-227
  - §3.11 — insert — ambiguity — synthetic PAID DevEx shape (requested/locked = disposed, withholding 0, net = ladder value); child cascade enumerated (listings cancelled, experiences archived, SUBMITTED/APPROVED DevEx cancelled); `EARNINGS_DISPOSED` instantaneous within the dispose call — routes_safety.py:390-419
  - §3.12 — insert — ambiguity — approval records the approving officer for the pay-step SoD check — routes_money.py:1161, 1188
  - §3.12 — insert — ambiguity — mark-paid does not reduce `earned_robux_lifetime`; reject `reason` accepted but not persisted — routes_money.py:1191, 1174
  
  No PRD-vs-implementation mismatches remain that I could identify; all other impl behaviors (formulas, thresholds, envelopes, state guards, SoD checks, idempotency replay semantics, termination pipeline) were already uniquely pinned by the PRD.
