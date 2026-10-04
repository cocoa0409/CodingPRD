# Worklog — task_3205_satellite_radio_trial_conversion_radio_activation

## Step 1: Create task directory — 2026-09-30T10:21:00.000Z

Pre-allocated task directory `./tasks/task_3205_satellite_radio_trial_conversion_radio_activation/` verified present with empty `workspace/` inside (created externally per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-09-30T10:45:00.000Z

All three files are written, parse as valid YAML, and pass `scaffold_lint.py` with a clean verdict.

**Files** (all under `tasks/task_3205_satellite_radio_trial_conversion_radio_activation/`):

| File | Lines | Top-level keys verified |
|---|---|---|
| `SCAFFOLD.yaml` | 1396 | `scenario, domain_name, api_prefix (/api/v1), complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no `scaffold_difficulty_design`/`scaffold_corner_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1420 | `scaffold_difficulty_design` only — 18 instances, exactly 2 per each of the 9 §0.5 rules |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1384 | `scaffold_corner_design` only — 31 instances across all 9 claim-guide sections (1 `excluded_because` stub) |

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (59 endpoints, 14 entities, 18 §1.8 + 31 §1.9 instances, 505 calls scanned). Additional self-checks passed: zero unbound `${var}` placeholders, all `grounds:` refs resolve, all instance names unique across both design files, every declared error is referenced by a validation/transition/concurrency rule, and no forbidden race vocabulary.

**Domain model:** 14 flat peer entities — Automaker, Dealer, Customer, Vehicle, Radio, PackageTier, SubscriptionPlan, Subscription, OfferCampaign, OfferStep, OfferRedemption (immutable log), SignalCommand, BillingLedgerEntry (immutable log), DisclosureRecord. Four real state machines: Subscription (7 states with a CANCEL_SCHEDULED→ACTIVE save-offer cycle and terminal CANCELLED/EXPIRED/TRANSFERRED_AWAY), Radio (cyclic DEACTIVATED→REGISTERED reactivation loop), SignalCommand (QUEUED→SENT→{ACKED, FAILED→QUEUED retry cycle →EXHAUSTED, SUPERSEDED}), OfferCampaign (DRAFT↔ACTIVE↔PAUSED→ARCHIVED); DisclosureRecord is a two-phase field-combination machine. Key calculations: `term_pricing` (pinned evaluation order base→pct-floor→flat→family-ceil to break the anchor/price circularity), `family_discount` (anchor = argmax base price, tie-break `created_at`), `cancellation_refund`/`transfer_proration` (floor-variant day proration, different ledger entry types), `renewal_pricing` (forward-looking with a 15-day disclosure lead-time gate producing regulatory limbo instead of renewal), `signal_path_selection` (GEN1 satellite 60-min vs GEN2/3 cellular 15-min retry bases), `campaign_overlap_check` (half-open phase windows where PAUSED still occupies), and `trial_eligibility` (count-based radio occupancy). Two OCC rules (radio trial provisioning, vehicle transfer) guard true create-with-supersede races. Difficulty design covers dual-variant calcs on different entity domains, combinatorial formulas in modes (b) and (c), cyclic machines on two entities, depth-≥3 cascades from two different triggers (vehicle transfer, billing batch), two priority-conflict pairs, boundary precision at exact day/lead-time edges, cross-entity gates on two entity pairs, two overlap semantics (half-open timestamps vs occupancy count), and compensating invariants over monetary ledger sums and discount-grant cardinality.

## Step 3: Copy INSTRUCTION.md — 2026-09-30T10:46:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3205_satellite_radio_trial_conversion_radio_activation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T10:53:00.000Z

**Output path:** `tasks/task_3205_satellite_radio_trial_conversion_radio_activation/workspace/PRD.md`
**Line count:** 326 lines
**Design files:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, grepped, or referenced in any way.

**Section list:**
- §1 Introduction (3 paragraphs: business context, regulatory/signal pressures, reader orientation)
- §2 Global Specifications (10 subsections): 2.1 RBAC with per-role identity prose, 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, including `req_RANDOMALPHANUM123456`, the fixed timestamp, and empty `data`), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning (including the three `common_fields: false` entities), 2.5 Monetary Precision (floor vs. ceil pinning), 2.6 OCC (both rules, `ERR_STALE_VERSION` 412), 2.7 Logical Clock, 2.8 Signal Transport Discipline (path selection, 15/60-minute retry bases, attempt cap 3, FIFO, supersession), 2.9 Validation Order (all 19 priorities in sequence), 2.10 Common Lifecycle Semantics
- §3 Business Logic (11 subsections): reference data; vehicles/radios/trial provisioning; direct purchase & term pricing engine; signal pipeline; subscription lifecycle; cancellation/refunds/save-offer loop; offer campaigns; renewal/expiry/disclosure gate; disclosure records; ownership transfer & used-vehicle loop; billing ledger
- §4 Endpoint Definitions (4-column table, 61 endpoints including `_signals/{id}/force_send` per the SignalCommand transition note)
- §5 Error Code Catalogue (2-column table, all 21 error IDs)

**Hard contract results:**
- Contract 1 (Field-Name Coverage): PASS — all ~110 scaffold field/endpoint identifiers mechanically verified present in backticks
- Contract 2 (Rule Coverage): PASS — all state transitions (Subscription ×11, Radio ×6, SignalCommand ×7, OfferCampaign ×5, DisclosureRecord ×1), all 8 calculations with pinned rounding/order, all validation priorities with error IDs, both OCC rules, both cancellation-refund variants (floor pinned, ceil explicitly excluded), PAUSED-occupies-window semantics, 15-day disclosure lead, and `supersession_seq` tie-break all expressed in prose
- Contract 3 (§3 Path Purity): PASS — 194 backticked tokens in §3 scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combinations

The file was written in four sequential append chunks to stay under the output cap; the document terminates correctly at the §5 error table.

## Step 5: Generate unit tests — 2026-09-30T11:12:00.000Z

**Files written**

- `test_helpers/`: `types.py` (enums + TypedDicts; append-only families `OfferRedemption`/`BillingLedgerEntry`/`DisclosureRecord` omit `updated_at`/`version`), `api_client.py` (one method per PRD endpoint), `api_errors.py` (21 error ids + HTTP map registered via `set_error_http_status_map`), `constants.py`, `factories.py` (unique-value generators for vin/esn/email/codes), `test_users.py` (opaque shared headers + entity-backed builders `make_customer/automaker/dealer_headers`), `fixtures.py` (composite setup: `setup_customer_with_radio`, `setup_active_paid_sub`, `provision_trial`, `dispatch_and_ack`, `exhaust_signal` driving the 3-round retry loop with clock hops, `create_active_campaign`, `send_renewal_disclosure`, `run_renewals`), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 14 test files (test_01–test_14).

**Coverage**

- Queue A (difficulty): **18/18 instances translated, 0 skipped** — every instance carries exactly 2 tests (≥2 requirement met).
- Queue B (corner): **31/31 non-stub instances translated, 0 skipped**; the single `excluded_because:` stub (`error_trial_plan_required_on_direct_purchase`) was verified to cross-reference the live difficulty instance `resource_temporal_overlap/radio_single_nonterminal_subscription_occupancy` and was not translated.
- Total: **67 tests**, all collected cleanly by `pytest --collect-only` with `PYTHONPATH=.` from the task directory; every `.py` file passes `python3 -m py_compile`.

**Design-tag audit**: every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 67 tags resolve to real instances in the source yamls (verified programmatically — 0 bad/duplicate tags, 0 shortfalls).

**PRD-citation audit**: 93 quoted citation fragments across all docstrings were checked verbatim (whitespace-normalized, elision-aware) against `workspace/PRD.md` — 0 failures. No `pytest.mark.skip`/`skipif`/`xfail` anywhere, and no scaffold references in generated code or docstrings.

Notable PRD adjudications applied: the zero-step campaign activation rejection is asserted only as "an error" (PRD does not uniquely name the error id for the empty-step check — ERR_INVALID_STATE vs ERR_INVALID_REQUEST is ambiguous); dual-failure priority tests assert the higher-priority error id exactly as PRD §2.9 orders them.

## Step 6: Generate implementation — 2026-09-30T11:44:00.000Z

**Files written** in `workspace/implementation/`:
- `start.sh` — foreground launcher, guarded `pip install`, `exec python3 app.py`
- `requirements.txt` — `flask>=2.2`
- `app.py` (1299 lines) — Flask app with all routes and handlers
- `core.py` (475 lines) — business logic: signals, state machines, pricing engine, renewal batch
- `db.py` — in-memory dicts + logical clock (default `2026-09-01T00:00:00Z`, no wall-clock fallback, no seeding)
- `errors.py` — all 21 error IDs with correct HTTP statuses
- `middleware.py` — `X-User-Role`/`X-User-ID` auth, entity-backed role identity
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more` in meta)
- `serializers.py` — wire views for all 14 entity types

**Endpoints: 60 routes registered**, covering every row of the §1.5 endpoint table (including the doubled-prefix list routes like `/api/v1/customers/{id}/api/v1/subscriptions` exactly as scaffolded).

**State machines implemented**:
- Subscription: full graph including cyclic `CANCEL_SCHEDULED → ACTIVE` (save-accept), signal-mediated `PENDING_ACTIVATION → ACTIVE`, system-driven `ACTIVE → EXPIRED`, `CANCEL_SCHEDULED → CANCELLED` finalization, `→ TRANSFERRED_AWAY`
- Radio: `UNREGISTERED/DEACTIVATED → REGISTERED ↔ SUSPENDED`, `→ DEACTIVATED` with unreferenced-radios guards
- SignalCommand: `QUEUED → SENT → ACKED/FAILED`, FAILED auto-requeue with linear backoff (15 min CELLULAR / 60 min SATELLITE), `EXHAUSTED` at 3 attempts, per-radio contradictory supersession, strict per-radio FIFO dispatch
- OfferCampaign: DRAFT/ACTIVE/PAUSED/ARCHIVED with half-open phase-window overlap check (PAUSED occupies), window-end guard, step-presence guard
- DisclosureRecord: sent/acknowledged two-state, drives subscription `disclosure_state` NONE → REQUIRED → SENT → ACKNOWLEDGED

**Calculations**: term_pricing (offer discount floor-pct-then-flat before family ceil-25%, both roundings pinned), family anchor (highest base price, earliest created_at tie-break, candidates = ACTIVE/SUSPENDED/CANCEL_SCHEDULED), offer_step_pricing (per-step rounding), cancellation_refund (floor both divisions, PRORATION_CREDIT), transfer_proration (TRANSFER_ADJUSTMENT + fresh trial for new owner with USED_DEALER/TRANSFER_IN origin), renewal_pricing with 15-day disclosure lead gate (regulatory limbo when missing), signal_path_selection (GEN1 → SATELLITE only), campaign_overlap_check, trial_eligibility (UNREGISTERED/DEACTIVATED + zero non-terminal subs).

**Compliance gates**: renewal disclosure required for immediate cancel of auto-renew paid subs from ACTIVE/SUSPENDED (422 ERR_RENEWAL_DISCLOSURE_REQUIRED), EXHAUSTED-signal block (409), save-offer cap 2/term (422), OCC on radio trials + vehicle transfer (412 ERR_STALE_VERSION), idempotency-key dedup on signal requeue and ledger postings.

**Smoke-boot result**: `bash start.sh` on a fresh port boots cleanly, all compile (`py_compile` OK on every .py), full end-to-end scenario passes: clock set → reference data → vehicle/radio → trial provision (OCC 412 verified on stale version, 422 RADIO_INELIGIBLE on occupied radio) → signal dispatch/ack (per-path CELLULAR/SATELLITE verified) → sub ACTIVE → paid purchase → disclosure gate blocks cancel → disclosure sent → cancel posts PRORATION_CREDIT → owner 403s → renewal via clock advance posts second CHARGE and slides `end_at`. All test servers cleaned up afterward.

## Step 7: Run tests and iterate — 2026-09-30T12:05:00.000Z (interrupted)

The first Step 7 subagent's context filled mid-analysis (its returned fragment was internal reasoning about `test_family_discount_absent_for_single_sub_households`, not a final summary). Orchestrator-side inspection of the on-disk state after its exit:

- Its first 8-round sweep completed with all 8 `results.{i}.json` files present; every round: **47/67 passed, 20 failed** (deterministic — same 20 tests in all 8 rounds, no flakiness observed).
- Failing-test union (20): `test_offer_step_pricing_per_step_rounding_before_flat`, `test_offer_step_pricing_flat_cannot_push_below_zero`, `test_signal_retry_cycle_exhausts_at_three`, `test_transfer_cascade_sub_signal_radio_discount`, `test_renewal_cascade_expiry_signal_and_family_reprice`, `test_disclosure_safety_vs_signal_block_priority_on_immediate_cancel`, `test_signal_block_alone_surfaces_when_disclosure_sent`, `test_renewal_disclosure_exactly_15_days_before_passes`, `test_renewal_disclosure_sent_well_before_boundary_renews`, `test_campaign_overlap_only_within_same_phase`, `test_radio_single_nonterminal_subscription_occupancy`, `test_renewal_disclosure_gate_blocks_charge`, `test_signal_retry_backoff_bases_differ_by_path`, `test_offer_sequence_step_up_rank_gating`, `test_offer_eligibility_min_household`, `test_exhausted_signal_blocks_suspend_until_requeue`, `test_disclosure_acknowledge_flow`, `test_occ_stale_version_on_trial_provisioning`, `test_idempotent_signal_requeue_key`, `test_clock_default_is_2026_09_01`.
- The subagent's mid-analysis hypothesis (unverified): for `test_family_discount_absent_for_single_sub_households` / related family tests, PRD line ~161 restricts family-anchor candidates to `ACTIVE`/`SUSPENDED`/`CANCEL_SCHEDULED` subscriptions, so a test asserting a discounted creation-time price for sub_b while sub_a is still `PENDING_ACTIVATION` contradicts the PRD — a test-setup ordering bug (activate the anchor first, then create the second sub), to be fixed in test_helpers/test_suite, not the implementation. Treated as a lead for the follow-up subagent, not as a settled verdict.
- File mtimes show test_suite/test_helpers were last written during Step 5 (11:01–11:11) and implementation during Step 6 (~11:40); the interrupted subagent's sweep results (11:44–11:45) postdate all edits, so no unverified partial edits appear to have landed.
- A fresh Step 7 subagent was spawned with the 20-failure list as a starting hint to continue the loop.

## Step 7 (continued): fix loop to clean sweep — 2026-09-30T12:35:00.000Z

All 8 rounds pass 67/67. Clean sweep achieved.

- **Iterations run**: 3 full 8-round parallel sweeps (round 1 reproduced the prior 47/67 baseline; round 2 reached 64/67; round 3: 67/67 in all 8 rounds).

- **Tests deleted**: none. Every failure traced to a fixable test artifact or a genuine implementation bug.

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/assertions.py` — added `assert_same_instant(actual, expected, label)`: parses both ISO 8601 strings and compares instants. PRD §2.4 pins three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`; other timestamp fields (`start_at`, `end_at`, `next_retry_at`, `due_before`) have no pinned serialization, so exact-string equality was a non-unique-derivability over-specification.

- **Fixes applied to `test_suite/`**:
  - `test_03_save_offer_and_signal_cycles.py` (`test_signal_retry_cycle_exhausts_at_three`), `test_10_corner_calculations.py` (`test_renewal_disclosure_gate_blocks_charge`, `test_signal_retry_backoff_bases_differ_by_path`), `test_12_corner_endpoints.py` (`test_disclosure_acknowledge_flow`), `test_14_corner_cross_cutting.py` (`test_clock_default_is_2026_09_01`), `test_05_validation_priorities_and_boundaries.py` (two renewal tests) — switched timestamp string-equality assertions to `assert_same_instant`.
  - `test_05_…py` (`test_renewal_disclosure_exactly_15_days_before_passes`, `test_renewal_disclosure_sent_well_before_boundary_renews`) and `test_04_cascades.py` (`test_renewal_cascade_expiry_signal_and_family_reprice`) — PRD §2.7 says clock advance itself re-evaluates time-based transitions, so per-batch counters are ambiguous (transition may already have fired inside `set_clock`); assertions moved to the resulting entity state, batch-counter asserts dropped.
  - `test_05_…py` (`test_disclosure_safety_vs_signal_block_priority_on_immediate_cancel`, `test_signal_block_alone_surfaces_when_disclosure_sent`) and `test_11_corner_validations.py` (`test_exhausted_signal_blocks_suspend_until_requeue`) — setups exhausted the ACTIVATE signal, leaving the sub PENDING_ACTIVATION, but PRD §3.6 scopes the cancel disclosure/signal-block guards to ACTIVE/SUSPENDED only; restructured setup to ACTIVE → suspend → exhaust the SUSPEND signal (SUSPENDED + EXHAUSTED), preserving the intended priority assertions; requeue command_type changed to SUSPEND.
  - `test_14_…py` (`test_occ_stale_version_on_trial_provisioning`) — PRD §2.9 orders `ERR_RADIO_INELIGIBLE` before `ERR_STALE_VERSION`, so the occupied-radio setup could never surface 412; test now immediate-cancels the first trial (PRD §3.6 frees the radio) before the stale retry, and asserts no new subscription was created.
  - `test_14_…py` (`test_idempotent_signal_requeue_key`) — idempotent-replay status (200 vs 201) is not pinned by PRD; replay now accepts either while still asserting success and identical command id.
  - `test_04_cascades.py` (`test_transfer_cascade_sub_signal_radio_discount`) — anchor must be ACTIVATED before the second sub is created (PRD §3.3 anchor candidate set excludes PENDING_ACTIVATION; confirmed the prior run's lead); also dropped `trial_plan_id` from the transfer because PRD §3.4 supersession correctly SUPERSEDES the DEACTIVATE when a contradictory ACTIVATE arrives — the TRANSFER_IN fresh-trial leg remains covered by test_01.
  - `test_06_state_dependencies_and_overlap.py` — `_campaign_with_step` cached tier/plan on the function object across per-test server restarts (stale plan id → 404 in the second caller); now builds fresh entities per call. `test_radio_single_nonterminal_subscription_occupancy` — the first trial is now activated before expiry (PRD §3.8 expires only ACTIVE subs) and the expiry-enqueued DEACTIVATE is acked so the radio returns to DEACTIVATED (trial-eligible per §3.2).

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/app.py` (`redeem`) — redemption record captured a transient list price for immediately-ACTIVE streaming subscriptions (the family recompute inside `create_subscription` runs before the redemption exists); the redemption's `redeemed_price_cents` is now persisted from the final post-recompute price.
  - `workspace/implementation/app.py` (`signal_requeue`) + `core.py` (`has_exhausted_signal`) — a RetentionAgent requeue now clears the exhausted-signal block for matching prior EXHAUSTED commands (PRD endpoint table: requeue "clears the block"; the exhausted command stays terminal history).
  - `workspace/implementation/app.py` (`signals_dispatch`) + `core.py` (`enqueue_signal`) + `db.py` — added a monotone insertion sequence (`_seq`, not serialized) as FIFO tie-break for commands enqueued within the same logical instant; the previous `created_at`-then-UUID tie-break could dispatch a later-enqueued ACTIVATE before an earlier DEACTIVATE.
  - `workspace/implementation/core.py` (`ack_signal` DEACTIVATE leg, new `radio_has_other_live_sub`) — DEACTIVATE ack now deactivates the radio when no other ACTIVE/SUSPENDED subscription references it, allowing the PRD §3.10 `DEACTIVATED → REGISTERED` cycle across owners when a fresh PENDING trial exists.
  - `workspace/implementation/core.py` (`run_renewals`) — implemented the PRD §3.8 limbo exit verbatim ("left ACTIVE past its end_at … until the disclosure is sent and a later billing run picks it up"): strictly past `end_at`, an existing disclosure of the needed type lets a later batch renew even if it missed the 15-day lead; at `end_at` itself the timely-disclosure rule still governs (keeps the 14-days-late boundary test blocked).

Final state: 67/67 passing in all 8 concurrent rounds, deterministic.

## Step 8: Finalize PRD — 2026-09-30T13:05:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

**Line counts and delta**
- `PRD.md`: 326 lines, 54,341 bytes
- `PRD_FINALIZED.md`: 326 lines, 56,527 bytes
- Delta: 0 lines (+0.0%), +2,186 bytes (+4.0%) — all edits are inline insertions/revisions within existing paragraphs; no new sections.

**Changes (one bullet per edit)**
- **§2.4** — revise — pinned that the three-fractional-digit ISO 8601 UTC `Z` format applies uniformly to every serialized timestamp field (`start_at`, `end_at`, `sent_at`, `due_before`, `next_retry_at`, etc.), and that unset nullable timestamps serialize as null — `implementation/response.py:22-27`.
- **§2.4** — revise — pinned that an idempotent replay response carries HTTP 201, the same status as the original creation — `implementation/app.py:902-904` (ledger idempotency at `core.py:318-322` is internal-only).
- **§2.8** — revise — pinned that commands sharing a `created_at` instant are ordered by enqueue sequence, and that the same order decides which command is "newer" for supersession — `implementation/db.py:36-44`, `core.py:95`, `app.py:135-136,147-149`, `core.py:67-80`.
- **§3.4** — revise — mirrored the enqueue-sequence tie-break into the batch-dispatch sentence — `implementation/app.py:135-136`.
- **§3.4** — insert — defined the DEACTIVATE-ack radio rule: radio moves to `DEACTIVATED` when no *other* `ACTIVE`/`SUSPENDED` subscription references it; `PENDING_ACTIVATION` does not block — `implementation/core.py:114-125`, `core.py:199-209`.
- **§3.4** — revise — pinned that a requeue lifts the exhausted-signal block only for prior `EXHAUSTED` commands of the *same* `command_type` on that subscription; other command types keep blocking — `implementation/app.py:905-914`, `core.py:235-241`.
- **§3.6** — revise — replaced the two vague radio-deactivation phrases ("no other non-terminal subscription references it" / "when unreferenced") with references to the §3.4 rule, matching `implementation/core.py:411-415` + `199-209`.
- **§3.7** — insert — pinned that `redeemed_price_cents` is the created subscription's final `current_term_price_cents` after the family-anchor recompute the redemption triggers — `implementation/app.py:1210-1220`.
- **§3.8** — revise — pinned the limbo exit: strictly past `end_at`, any existing disclosure of the needed type satisfies the gate on a later billing run even if it missed the 15-day lead; exactly at `end_at` the timely rule still governs — `implementation/core.py:464-485`.

Items from `<step_7_diff>` intentionally producing **no** PRD edit: all test-fixture restructurings (cancel-guard scope, OCC-vs-eligibility ordering, anchor-must-be-ACTIVE, §3.8-expires-only-ACTIVE, campaign fixture caching, TRANSFER_IN supersession) — the PRD already pins those behaviors; and the `set_clock` batch-counter ambiguity — §2.7 already pins that clock advance re-evaluates transitions.

**Per-edit pre-edit search log** (abridged; full log in Step 8 subagent transcript):
1. §2.4 timestamp format — read `response.py` + all 14 serializers; added null-serialization clause.
2. §2.4 idempotent-replay status — read `app.py:893-914`, `core.py:318-322`; confirmed no `POST /signal-commands` endpoint exists; no wording adjustment.
3. §2.8 FIFO tie-break — read `app.py:127-156`, `app.py:159-166` (force_send bypass), `core.py:67-80`, `db.py:36-44`; extended sentence to define "newer" for supersession at equal instants.
4. §3.4 dispatch mirror — same paths as edit 3; scoped as parenthetical cross-reference to §2.8.
5. §3.4 DEACTIVATE-ack radio rule — read `core.py:199-209`, `core.py:114-125`, all DEACTIVATE enqueue sites, SUSPEND leg (untouched), §3.2 eligibility (untouched); wording scoped to DEACTIVATE ack, notes PENDING does not block.
6. §3.4 requeue block clearing — read `core.py:235-241`, `app.py:750`, `app.py:799`, `app.py:893-914`; added "different command_type keeps blocking" sentence.
7. §3.6 cancel radio phrases — read `core.py:418-425`, `app.py:777-802`; replaced stronger "no other non-terminal subscription" claim (contradicted impl) with pointer to §3.4 rule.
8. §3.7 redeemed_price_cents — read `app.py:1165-1221`, `core.py:373-394`, `core.py:289-313`, `app.py:805-849` (save-offer flow, out of scope), `core.py:380`; softened wording to pure "final post-recompute term price" definition.
9. §3.8 limbo exit — read `core.py:447-505`, `app.py:116`, `app.py:120-124`, `app.py:852-869`; wording distinguishes strictly-past-`end_at` (forgiving) from exactly-at-`end_at` (timely rule), matching `ts > sub["end_at"]` at `core.py:479`.

## Step 9: Complete PRD — 2026-09-30T13:20:00.000Z

`PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (326 lines both; 56,527 → 62,648 chars, +6,121).

**Counts:** 27 ambiguity-pins, 1 mismatch-revision. All edits were inline inserts/revisions; no sections added.

**Changes:**
- §2.1 — insert — ambiguity — feed against another automaker's record rejected with `ERR_FORBIDDEN_OWNER` — app.py:511-512
- §2.3 — insert — ambiguity — list ties broken by record `id`; `status`, `customer_id`, `plan_id`, `campaign_id` filters pinned — app.py:198,278-280,433-435,1063-1065,1230-1235
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — core.py:32
- §2.4 — insert — ambiguity — idempotency surfaces: requeue endpoint for signals, internal postings for ledger (same-key postings collapse) — app.py:902-904, core.py:319-322
- §2.6 — insert — ambiguity — missing/non-integer `expected_radio_version` yields `ERR_STALE_VERSION` — app.py:499-501
- §2.6 — insert — ambiguity — same for `expected_vehicle_version` — app.py:608-610
- §2.7 — insert — ambiguity — malformed `to_iso8601` is `ERR_INVALID_REQUEST`; clock-set runs the billing pass internally but returns only `now_iso8601` — app.py:113-117
- §2.8 — insert — ambiguity — "contradicts" = different `command_type` (same-type never supersedes) — core.py:63-79
- §2.9 — insert — ambiguity — campaign activation/archive preconditions are `ERR_INVALID_STATE`, not window errors — app.py:1118-1123,1151-1162
- §3.2 — insert — ambiguity — used-dealer door requires `DEACTIVATED` status (implied by general eligibility) — app.py:574, core eligibility
- §3.2 — insert — ambiguity — feed items bump radio version per provisioned item — app.py:544
- §3.2 — insert — ambiguity — used-reactivation cross-dealer ownership → `ERR_FORBIDDEN_OWNER`; hardware gate applies to all three trial doors — app.py:560-561,542,579,498
- §3.2 — insert — ambiguity — PlatformAdmin direct trial takes origin `WEB_SIGNUP` — app.py:474-479
- §3.3 — insert — ambiguity — purchase origin: `WEB_SIGNUP`/`CALL_CENTER` by role (PlatformAdmin → `WEB_SIGNUP`) — app.py:677
- §3.3 — insert — ambiguity — `end_at` = `start_at` + term days in seconds — core.py:355
- §3.3 — insert — ambiguity — offer discount capped at base (percentage floor + flat, floored at zero) — core.py:255-261
- §3.3 — insert — ambiguity — STREAMING_ONLY purchase ignores supplied `radio_id`; non-streaming purchase without `radio_id` is `ERR_INVALID_REQUEST` — app.py:667-671
- §3.3 — insert — ambiguity — family discount = ceil(post-offer price × 2500/10000) — core.py:270
- §3.3 — insert — ambiguity — `SAVE_OFFER` subs exempt from family recompute price re-derivation (anchor flag still tracked) — core.py:300-311
- §3.3 — insert — ambiguity — purchase `CHARGE` equals freshly computed `current_term_price_cents` — core.py:380
- §3.4 — insert — ambiguity — dispatch due when `next_retry_at` ≤ now; `superseded_count` always 0 (supersession happens at enqueue) — app.py:127-156
- §3.4 — insert — ambiguity — force_send bypasses FIFO queue order — app.py:159-166
- §3.4 — insert — ambiguity — requeue on streaming-only (radio-less) subscription → `ERR_INVALID_REQUEST` — app.py:900-901
- §3.5 — revise — mismatch — radio `REGISTERED` on any `ACTIVATE` ack (not only trials); `last_signal_at` always set — core.py:170-178
- §3.5 — insert — ambiguity — resume at exactly `end_at` is `ERR_INVALID_STATE` (strict inequality) — app.py:767-768
- §3.6 — insert — ambiguity — END_OF_TERM cancel from `PENDING_ACTIVATION` → `ERR_INVALID_STATE`; cancel from terminal/CANCEL_SCHEDULED likewise — app.py:783-788
- §3.6 — insert — ambiguity — no ledger entry for zero-amount trial refund (immediate cancel from PENDING) — core.py:421-422
- §3.6 — insert — ambiguity — refund zero at/after `end_at`; `PRORATION_CREDIT` posted only for paid kinds — core.py:398-408,421-422
- §3.6 — insert — ambiguity — save price = base minus step offer discount (no family component); `SAVE_CREDIT` is negative base-minus-next-price; redemption records the save-priced amount — app.py:833-847
- §3.7 — insert — ambiguity — campaign window inclusive at redemption; malformed window timestamps `ERR_INVALID_REQUEST`; has-steps check DRAFT-only; window-closed error `ERR_CAMPAIGN_WINDOW` from DRAFT vs `ERR_INVALID_STATE` from PAUSED; archive guards → `ERR_INVALID_STATE` — app.py:1028-1031,1120-1125,1151-1162
- §3.7 — insert — ambiguity — `eligibility_expr` defaults null; `requires_streaming` semantics; rank-0 steps unconstrained; sequence compares redeemed `step_index` set within the campaign; customer may redeem only for self — app.py:963-1018,1185-1186
- §3.8 — insert — ambiguity — expiry/finalize trigger when `end_at` ≤ now; limbo keeps `disclosure_state` REQUIRED until the send/ack flow advances it — core.py:451,457,481-484
- §3.9 — insert — ambiguity — `due_before` = current `end_at` at send time; re-acknowledgment idempotent — app.py:861,881-882
- §3.10 — insert — ambiguity — DealerPartner/PlatformAdmin may transfer any vehicle; `trial_plan_id` must be a trial plan; fresh trial per radio; transfer credit posted only for paid kinds; `supersession_seq` = count of pre-existing subs on the (radio, customer) pairing (0 for radio-less subs) — app.py:606-635, core.py:366-369
