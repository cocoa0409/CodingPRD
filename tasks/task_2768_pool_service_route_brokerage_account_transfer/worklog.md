# Worklog — task_2768_pool_service_route_brokerage_account_transfer

## Step 1: Create task directory — 2026-09-04T18:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2768_pool_service_route_brokerage_account_transfer` and its `workspace/` subdirectory. Index 2768 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T20:52:00.000Z

All three scaffold artifacts are generated and the lint is clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2768_pool_service_route_brokerage_account_transfer/`)
- `SCAFFOLD.yaml` — 3817 lines; top keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` (verified programmatically). 12 entities, 7 state machines, 2 `concurrency_rules`, 13 calculations, 70 ordered validations, 61 endpoints, 70 error priorities over 69 ids, 5 roles (PlatformAdmin, Broker, Seller, Buyer, EscrowAgent; `segregation_of_duties` role model with three SoD clauses). The "harder than expert level" directive does not appear anywhere in the artifacts.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3416 lines, single top-level key, 24 §1.8 instances covering all eight difficulty rules: dual-formula (listed vs verified basis, replacement vs price-adjustment remedy, INCLUDED vs PASS_THROUGH chemicals), nested/ordered computation, three cyclic state paths, two multi-hop cascades (5-hop reprice, 4-hop holdback block), two validation-priority pairs, inclusive/strict/empty-set boundaries, three cross-entity invariants, two temporal-window corners, three conservation invariants.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 9073 lines, single top-level key, all nine claim-extraction sections: entities 11, state_machines 12, calculations 6, validations 22, endpoints 6, errors 27, rbac 9, complexity_layers 5, consistency_model 1 = **99 instances** (80 with full `test_recipe`, 19 `excluded_because` stubs, each citing an existing §1.8 instance by name; no name collides across the two design files).

**Lint** (`scaffold_lint.py`, verbatim):
```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  2732

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable design findings: `ERR_REPRICE_REQUIRED` (priority 26) is structurally unreachable because priorities 23/24 mask it on every endpoint that could raise it, so the errors section carries an honest `priority_ordering` instance asserting the masking instead of an unsatisfiable trigger; listing exclusivity is scoped to `(seller_id, region_code)`, which is what legitimises the two concurrent NV listings used by the cross-deal instances; both §1.2.1 OCC rules get a dedicated stale-version instance that also asserts the rejected write left no trace and bumped no version.

Orchestrator verification: `grep -rn "harder than expert"` over the task dir returns nothing — the difficulty directive did not leak into any artifact.

## Step 3: Copy shared files — 2026-09-04T20:52:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T21:12:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **562 lines / 116,830 bytes**, written across 9 incremental appends (no single giant Write).

**Sections written**
- §1 Introduction (route-brokerage framing, derived-not-entered numbers, explicit clock + conserved quantities).
- §2 in 11 subsections: 2.1 RBAC & segregation of duties, 2.2 response envelope (byte-identical to `section-2.2-response-structure.md`; only difference from `diff` is the trailing blank separator line), 2.3 pagination, 2.4 identity/timestamps/versions, 2.5 deterministic logical clock, 2.6 money & rounding, 2.7 roll-up/cascade propagation, 2.8 OCC, 2.9 explicit 1–70 check-precedence list incl. both co-violable pairs, 2.10 conserved quantities, 2.11 interval conventions.
- §3 in 9 subsections: 3.1 licensing regimes/sellers/buyers, 3.2 listings & account list, 3.3 billing evidence & verification, 3.4 valuations & publication, 3.5 negotiation/acceptance/termination, 3.6 diligence, exclusions & depth-5 repricing cascade, 3.7 permit transfer, 3.8 introductions/funding/closing + commission ladder + waterfall, 3.9 guarantee/attrition ledger/clawback settlement.
- §4 endpoint table: 4 columns, all **61** endpoints, root-flat topology, 201-vs-200 rule stated.
- §5 error table: 2 columns, all **69** distinct error IDs in precedence order (70 validation priorities, `ERR_VALIDATION` spanning two).

**Hard Contract audits (scripted against SCAFFOLD.yaml)**
- **Contract 1 — Field-Name Coverage: PASS.** 158/158 identifiers (every `entities[].fields[].name` plus every `request_body`/`query_params` input across all 61 endpoints) appear verbatim in backticks; 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 69 error IDs appear in §1–§4 prose (not only in the §5 table); all 36 state-machine `from`/`to` states, all 74 enum values, both `concurrency_rules` (OCC-framed, no "simultaneously"/"race" language — grep clean), and all 13 calculations incl. both dual-variant pairs (`LISTED_BASIS`/`VERIFIED_BASIS`, `REPLACEMENT_BASIS`/`PRICE_ADJUSTMENT_BASIS`) and all three conservation invariants are covered.
- **Contract 3 — §3 Path Purity: PASS.** Across 1,055 backticked tokens in §3: 0 path-like tokens, 0 bare HTTP methods, and 0 raw occurrences of GET/POST/PATCH/PUT/DELETE anywhere in the section.

**Tail intact:** last 40 lines read; the file ends on the final `ERR_LISTING_NOT_PUBLISHABLE | 422` row of the §5 table — a real section boundary, not mid-sentence. Grep for difficulty meta-commentary ("harder than", "expert level", "difficulty", "corner case", "test recipe") returns zero hits; fuzzy-quantifier grep is clean.

**Two scaffold gaps I resolved (implementer-visible decisions):** `CLAWBACK_CAP_PCT` is never declared anywhere in SCAFFOLD.yaml, so §3.8 pins `clawback_cap_cents` at twenty percent of `current_offer_price_cents` (any cap at or below the 15% `HOLDBACK_PCT` would make the note-principal and seller-cash waterfall buckets unreachable). The nonexistent `covenant_term_months` is replaced by `accepted_on` plus `retention_guarantee_days`, matching validation priority 43. Also normalised: `X-User-Role`/`X-User-ID` (scaffold prose said `X-Role`) and `amount_cents` for deposits (scaffold priority 55 said `deposit_amount_cents`). The state-machine precondition "`license_status != NONE` or `provisional_operation_allowed`" on permit filing has no error ID anywhere in the scaffold; I mapped it to `ERR_VALIDATION`.

I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`; all greps were scoped to `SCAFFOLD.yaml` by name.

Orchestrator verification: `tail -15` confirms the file ends on the last §5 error-table row; all five top-level sections (§1 line 3, §2 line 11, §3 line 226, §4 line 418, §5 line 488) are present. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T21:58:00.000Z

Implementation complete and verified.

**Modules** (`.../workspace/implementation/`, 3517 lines total):
`start.sh` 10 (executable, guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000) · `requirements.txt` 1 · `app.py` 54 · `errors.py` 93 · `store.py` 71 · `responses.py` 97 · `validators.py` 194 · `auth.py` 70 · `calc.py` 372 · `serializers.py` 156 · `services.py` 357 · `routes/`: clock 30, profiles 63, parties 137, listings 214, accounts 295, billing 92, valuations 50, deals 539, escrow 109, licenses 190, attrition 122, settlements 201.

**Coverage, verified mechanically**
- Endpoints: 61 implemented, 61 in PRD §4 — machine-diffed the Flask `url_map` against the PRD table: zero missing, zero extra.
- Errors: 69 PRD ids + `ERR_INTERNAL`; ids and HTTP statuses machine-diffed against the PRD catalog — no missing, no extras, no status mismatches; all 12 not-found ids are wired through `services._found`.
- Storage: in-memory dicts only; no seeding — a fresh boot reports `total_count: 0` on all 12 collections and `_clock` at `2026-08-01T00:00:00Z`. Cold boot to first 200: **0.69 s**.

**Design decisions of note**
- Uniform "lenient resolve → ownership/SoD guard → validation → existence → state → business" ordering so priority-3/4 checks can precede 5/7-17, with the PRD's two called-out inversions (23 before 51 on close, 38 before 47 on introduce) and PRD's own accept ordering.
- `Decimal` + `ROUND_HALF_UP` everywhere; ratios at 4 dp, money at whole cents, per-month rounding before averaging in verification.
- Commission, clawback cap and `effective_multiple_at_close` computed at close (PRD beats scaffold); posture ≠ COMPLETE maps to `ERR_VERIFIED_MRR_SHORTFALL`; the DENIED retry buffer is enforced by the single closed-interval window rule including the row's own prior window.
- **One bug found and fixed this session:** `accept` unconditionally created a new `EscrowAccount` and re-fanned permits, so a repriced-then-re-accepted deal got a second escrow (and `escrow_of_deal` then returned the stale target-0 row, deadlocking funding) plus duplicate permit rows. Accept now reuses the deal's existing escrow — resetting `target_amount_cents`/`holdback_amount_cents`/`deposits_blocked` per §3.5's "until a fresh acceptance sets it again" — and only fans out permit types with no live (non-`CANCELLED`) row. Re-verified: 1 escrow, 1 permit row, deal funds and closes.

**Smoke tests** (own port 41768, killed afterwards by its own PID; no broad pkill): ~130 requests across 5 scripts. Full lifecycle twice end-to-end (profile → parties → listing → stops → billing → verify → valuations → publish → offer/counter/re-offer → accept → waive/apply/deny/re-apply/approve → introduce → diligence → financing → deposits → close → attrition → settlement propose/dispute/settle → holdback release), plus the diligence 5-hop cascade (valuation superseded, deal `REPRICE_REQUIRED`, escrow blocked with target 0), the reprice escape and re-accept, terminate unwind (escrow REFUNDED, permits CANCELLED, stops back to PENDING, listing relisted), recovery unfreeze (clawback back to `MONITORING`, schedule restored), replacement credit (50 % cap → net 10000, `attrition_pct` 0.1667), both remedy bases, and all four SoD bars. Escrow cash conservation held after every mutation. Envelope matches §2.2 exactly (`req_` ids, 3-digit fractional timestamps, `object`/`array`, `data.error_id`+`message`, pagination meta only on lists, `limit=0/101/offset=-1` → `ERR_VALIDATION`). Every non-expected status turned out to be a flaw in my test script, not the server.

`test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` were never read, listed, globbed or grepped; `worklog.md` untouched.

## Step 5: Generate unit tests — 2026-09-04T23:24:00.000Z

Test generation is complete and audited.

**Deliverables** (all at the task root, nothing written under `workspace/`)

`test_helpers/` — 9 modules, 2578 lines:
`__init__.py` 45, `api_client.py` 238 (includes `canonical_instant`/`instants_equal` for sub-second ISO normalisation), `api_errors.py` 165, `assertions.py` 426, `constants.py` 137, `factories.py` 278 (all money as JSON int cents), `fixtures.py` 888 (deal-lifecycle builders: `route_with_billing_history` → `accepted_deal` → `permits_approved_deal` → `diligence_cleared_deal` → `financing_approved_deal` → `escrow_funded_deal` → `closed_deal` → `clawback_triggered_deal`/`replacement_recorded_deal`/`open_settlement`, plus `nv_deal_route`, `nv_stop`, `append_attrition`, `approve_permit`, `set_clock`), `test_users.py` 82, `types.py` 419.

`test_suite/` — 13 files, 7203 lines, **128 tests**:
`conftest.py` 30; `test_01_licensing_regimes_and_parties.py` 304 (8); `test_02_route_listings_and_customer_stops.py` 932 (18); `test_03_billing_evidence_and_verification.py` 576 (10); `test_04_valuation_snapshots_and_publication.py` 782 (15); `test_05_deal_negotiation_and_acceptance.py` 664 (12); `test_06_diligence_signoff_and_repricing.py` 493 (8); `test_07_permit_transfers.py` 365 (5); `test_08_escrow_funding_and_closing.py` 733 (14); `test_09_customer_introductions.py` 399 (7); `test_10_retention_ledger_and_replacements.py` 730 (12); `test_11_clawback_settlements.py` 836 (12); `test_12_role_access_and_segregation_of_duties.py` 379 (7).

**Design-index coverage** — every test translates exactly one instance, no untagged/dual-tagged tests:
- Queue A (difficulty): 24/24 instances translated, exactly 2 tests each = 48 tests. 0 skipped.
- Queue B (corner): 80/80 non-stub instances translated, 1 test each = 80 tests. 0 skipped. The 19 `[STUB]` instances are not translatable by definition and were not emitted.

**PRD-first deviations** (asserted the PRD, not the index): on terminating a funded deal the index wanted both permit transfers `CANCELLED` while its own setup had them `APPROVED` — PRD §3.5 leaves `APPROVED`/`WAIVED` alone, so the test asserts they remain `APPROVED`; `waiver_basis` uses the PRD's `RECIPROCITY_AZ` rather than the index's value.

**Verification run**: 128/128 tests carry a `Design:` line as the docstring's final line, all tag names exist in the two design yamls, difficulty tags appear exactly twice and corner tags exactly once; 302 PRD citations machine-checked verbatim against `workspace/PRD.md` with 0 unverified; `pyflakes` over `test_suite/` is fully clean (0 warnings after dropping stale `pytest`/`assert_cents` imports); no leakage of "scaffold", §1.x, queue or design-index vocabulary into either output directory.

Orchestrator verification: `ls -d workspace/test_suite workspace/test_helpers` → none; both directories are correctly at the task root. 128 `def test_` functions counted independently.

## Step 7: Run tests and iterate — 2026-09-04T23:56:00.000Z

All 8 rounds pass 128/128. The loop is closed.

## Summary

**Iterations run:** 2 (iteration 1 = baseline diagnosis at a deterministic 120/128 in all 8 rounds; iteration 2 = verification sweep after the fix batch, 128/128 in all 8 rounds).

**Tests deleted:** none. All 8 failing assertions traced to verbatim PRD sentences and were uniquely derivable, so no PRD-silence deletion applied.

**Fixes to `test_helpers/`:**
- `test_helpers/fixtures.py` — `escrow_funded_deal` never re-read the deal after the final deposit, so `ctx["deal"]` stayed at `FINANCING_APPROVED` while the server had already cascaded it to `ESCROW_FUNDED` (PRD §3.8). Added the re-read, matching the sibling `nv_deal_route`. This was the shared root cause of 2 failures (test_08 helper `one_permit_short_funded_deal` and one test_09 assertion).

**Fixes to `test_suite/`:**
- `test_04_valuation_snapshots_and_publication.py` — the local `suspension_pair` helper built routes with no billing history and no verified stop, so a `VERIFIED_BASIS` snapshot legitimately hit `ERR_NO_VALUATION_INPUTS` (§2.9 #42) before `ERR_SELLER_SUSPENDED` (#65). Added three trailing bank-verified months with zero variance and verified the stop, so suspension is the only rule broken. The asserted `LISTED_BASIS` figures (20000 / 9.0 / 10.0 / 200000) are unaffected because `valuation_figures` depends only on recurring, repair and age.
- `test_10_retention_ledger_and_replacements.py:554` — the holdback release omitted its explicit expected status; §4 names holdback releases as appending a child record, and two other passing tests (test_08:406, test_12:295) assert 201. Now `validate_success(..., 201)`.

**Fixes to `implementation/`:**
- `services.py::verification_posture` — returned `EMPTY` whenever no stop was `VERIFIED`, so a DISPUTED-only listing read `EMPTY`. §3.3 pins "on the two that land in `DISPUTED` the listing's posture is recomputed to `INCOMPLETE`". Now `EMPTY` requires no VERIFIED **and** no DISPUTED stop; `COMPLETE` keeps its all-VERIFIED/EXCLUDED-with-count≥1 condition. (2 failures)
- `routes/deals.py::_gate` — emitted `ERR_REPRICE_REQUIRED` ahead of the transition/terminal error. §3.5's explicit accept ordering plus §2.9's numbering make the repricing lockout structurally masked by the transition check, so the reprice branch (and the now-dead `_reprice` helper and unused `reprice_allowed` parameter) were removed. `_terminal`-before-`_invalid` order preserved. (1 failure)
- `routes/accounts.py` (introduce) — same masking fixed for consistency: `REPRICE_REQUIRED` folded into the `ERR_INVALID_DEAL_TRANSITION` set.
- `routes/escrow.py::release_holdback` — removed the deal-terminal pre-check that §3.9 never declares for that endpoint (it declares only a `PARTIALLY_RELEASED` escrow whose deal is `CLOSED`), letting `ERR_ESCROW_NOT_OPEN` answer first. The `deposit` handler's `ERR_DEAL_TERMINAL` check was left intact since §3.8 does declare it there. (1 failure)

**Per-round evidence (iteration 2):** results.1 through results.8 each report `passed 128 / total 128`, `failed 0`, `errors 0`, `skipped 0`, duration ~233.7 s.

No entity data is seeded or persisted anywhere in `implementation/` (storage remains in-memory dicts), no assertion was weakened or skipped, no endpoint/field/capability was added, and `worklog.md` was not touched. Only the four implementation files and three test-layer files listed above were modified.

Orchestrator verification: read all 8 `results.$i.json` directly (mtime 23:45) — each reports `128 / 128`. Step 7 made 4 `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T00:12:00.000Z

Done. `PRD_FINALIZED.md` is a 6-edit patch of `PRD.md` on 5 lines.

## Line counts
- `PRD.md`: 562 lines / 116,830 bytes
- `PRD_FINALIZED.md`: 562 lines / 118,549 bytes — **0.0% line delta, +1.47% bytes** (all edits are inline within existing paragraphs; file still ends at the final §5 row `| ERR_LISTING_NOT_PUBLISHABLE | 422 |`)

## Changes
- **§3.2 (posture roll-up) — revise** — `EMPTY` now requires *no* `VERIFIED` **and** *no* `DISPUTED` stop, the three clauses are declared as tested in order, and a `DISPUTED`-only listing is explicitly `INCOMPLETE`; also spelled out that an all-`UNVERIFIED` / all-`EXCLUDED` / mixed listing reads `EMPTY` — `implementation/services.py:131-144` (used at `services.py:157`, initial value `routes/listings.py:60`).
- **§2.9 item 26 — revise** — added that no operation declares the `ERR_REPRICE_REQUIRED` check, so the identifier is never reported and a `REPRICE_REQUIRED` deal is answered by whatever other status check the endpoint declares — `implementation/routes/deals.py:37-50` (reprice branch and `_reprice` helper removed).
- **§3.5 (acceptance check order) — revise** — "then the repricing lockout" replaced by a note that transition validity answers on a `REPRICE_REQUIRED` deal with `ERR_INVALID_DEAL_TRANSITION` — `routes/deals.py:241` via `_gate` at `routes/deals.py:37`.
- **§3.8 (introduction gates) — insert** — non-conforming deal statuses answer `ERR_INVALID_DEAL_TRANSITION` (`REPRICE_REQUIRED` and `CLOSED` included), `TERMINATED`/`GUARANTEE_CLOSED` answer `ERR_DEAL_TERMINAL`, unstamped covenant answers `ERR_INVALID_DEAL_TRANSITION` — `routes/accounts.py:195-202`.
- **§3.9 (holdback release) — insert** — segregation first, then escrow status before anything about the deal; no absorbing-deal check on this endpoint, so a non-`PARTIALLY_RELEASED` escrow answers `ERR_ESCROW_NOT_OPEN` even when its deal is already `GUARANTEE_CLOSED`; a `PARTIALLY_RELEASED` escrow whose deal isn't `CLOSED` answers `ERR_GUARANTEE_NOT_STARTED` — `routes/escrow.py:80-101`.
- **§3.9 (holdback release) — insert** — the release is a child-record append, so it reports a creation status and returns the updated escrow account — `routes/escrow.py:110`.

**No edit made** for two Step 7 items, both pure fixture/test bugs where PRD already determines behavior: the `escrow_funded_deal` re-read (§3.8 already pins the `FINANCING_APPROVED → ESCROW_FUNDED` deposit cascade, `routes/escrow.py:69-73`) and the test_04 `suspension_pair` rebuild (§2.9 numbering already pins #42 `ERR_NO_VALUATION_INPUTS` before #65 `ERR_SELLER_SUSPENDED`, matching `routes/listings.py:203-209`).

## Pre-edit search log
1. **§3.2 posture** — (a) subject: `verification_posture` value. (b) enumerated: `services.py:131-144` definition; sole caller `recompute_listing:147-161`; every `recompute_listing` callsite (`routes/accounts.py` create/verify/exclude/reinstate/introduce/replace, `routes/deals.py:532` terminate); initial literal `"EMPTY"` at `routes/listings.py:60`; consumer `routes/deals.py:360` (`COMPLETE` gate); `serializers.py`. Also cross-read §3.3's "recomputed to `INCOMPLETE`" sentence and test_02:841/868 (all-`UNVERIFIED` reads `EMPTY`). (c) adjustment: added the ordered-cascade framing plus the explicit "all `UNVERIFIED` / all `EXCLUDED` reads `EMPTY`" clause, because a bare "no `VERIFIED` and no `DISPUTED`" plus the untouched `INCOMPLETE` sentence would have left the all-`UNVERIFIED` listing ambiguous and could have flipped it to `INCOMPLETE`, contradicting `services.py:139`.
2. **§2.9 item 26** — (a) subject: when `ERR_REPRICE_REQUIRED` is reported. (b) enumerated: grep `REPRICE_REQUIRED` over all of `implementation/` — `errors.py:38` (status map only, never raised), `deals.py` `_gate`/offers/accept/clear-diligence/approve-financing/close/terminate, `accounts.py:195` introduce, `accounts.py:258-266` replace, `escrow.py:58` deposit (blocked escrow), `attrition.py:48-52`, `settlements.py:41-45`, `listings.py:181`, `services.py:232`. (c) adjustment: dropped a first draft that said "an *earlier* check always answers" — false, since `attrition.py:50` and `settlements.py:43` answer `ERR_GUARANTEE_NOT_STARTED` (#32, *later* than #26) and `replace` can answer #22; rewrote as "no operation declares this check", which holds for every enumerated path.
3. **§3.5 accept order** — (a) subject: acceptance's check sequence. (b) enumerated: `deals.py:241-254` (gate → qualification → guarantee days → down payment → seller standing → split), `_gate:37-50`, `_terminal`/`_invalid`, and the parallel `_gate` users (counter 175, offers 201, clear-diligence 350, approve-financing 381) to confirm none of them emits the reprice error either. (c) no adjustment beyond scoping the claim to "this endpoint".
4. **§3.8 introduction gates** — (a) subject: deal-status refusal on introduce. (b) enumerated: `accounts.py:194-202`; compared with the global order in §2.9 (#21 excluded, #22 not-introducible, #24 invalid transition, #25 terminal, #34 mismatch, #38 permits, #47/#48/#62 window/limit/sequence, #65 suspended) against `accounts.py:186-230`; also checked `deals.py:405-411` so the wording would not imply closing answers the transition error. (c) adjustment: named `CLOSED` explicitly and carved out `TERMINATED`/`GUARANTEE_CLOSED`, since `CLOSED` is not absorbing in this domain but is still refused with the transition error at `accounts.py:195`.
5. **§3.9 release ordering** — (a) subject: holdback-release precondition order and the absence of a deal-terminal check. (b) enumerated: `escrow.py:78-101` (SoD → path → existence → escrow status → deal `CLOSED` → timing); parallel escrow-status users `escrow.py:56-60` (deposit *keeps* its `ERR_DEAL_TERMINAL`, §3.8 declares it) and `settlements.py:176-185` (settle: mismatch → settlement status → escrow status, no deal check); `recompute_deal_ledger` for the `holdback_release_blocked` / `scheduled_holdback_release_utc` fields the timing check reads. (c) adjustment: scoped every clause to "this endpoint" so the deposit handler's declared `ERR_DEAL_TERMINAL` is not contradicted, and stated the SoD-first ordering rather than implying escrow status runs first absolutely.
6. **§3.9 release status code** — (a) subject: HTTP status of a successful holdback release. (b) enumerated: `escrow.py:110` (201, body = escrow), `escrow.py:75` deposit (201, already stated in §3.8), `settlements.py:201` settle (200 — a modification, so the wording had to stay confined to the release), plus §4's "operations that create a new record answer 201 … as deposits and holdback releases do". (c) adjustment: worded it as "appended as a child record … reports a creation status" mirroring §3.8's deposit sentence, and added "answers with the updated escrow account" to match the returned body without implying a new resource type exists.

## Step 9: Complete PRD — 2026-09-05T01:05:00.000Z

Step 9 was executed as **four sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden from copying). Partitioning by implementation module was chosen because a single agent cannot hold the 3517-line implementation plus the 562-line PRD without losing scan fidelity; a single-pass scan risks emitting a byte-identical file, which would mean the scan never ran.

Partition:
- Pass 1: `app.py`, `errors.py`, `store.py`, `responses.py`, `validators.py`, `auth.py`, `serializers.py`, `routes/{clock,profiles,parties}.py`
- Pass 2: `calc.py`, `services.py`, `routes/{listings,billing,valuations}.py`
- Pass 3: `routes/{accounts,deals}.py`
- Pass 4: `routes/{licenses,escrow,attrition,settlements}.py` + cross-pass coherence check

### Pass 1 summary (verbatim)

**Step 0 confirmation:** Ran `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` (source: `PRD_FINALIZED.md`, produced by Step 8). All edits below were made against `PRD_COMPLETED.md` only, via targeted `Edit` calls.

**Line counts / delta:** `PRD_FINALIZED.md` 562 lines / 118,549 chars → `PRD_COMPLETED.md` 565 lines / 122,912 chars (**+3 lines, +4,363 chars**). Tail verified: file still ends at `| ERR_LISTING_NOT_PUBLISHABLE | 422 |`. The 3 added lines are one new bullet in §2.2 and the blank line + one new paragraph in §2.6; everything else is in-paragraph.

**Counts: 17 ambiguity-pins, 0 mismatch-revisions.** No passage in the PRD described behavior that contradicts my partition's modules — every finding was PRD silence.

Changes: §2.1 only `X-User-Role` authenticated, missing `X-User-ID` → `ERR_ACTOR_NOT_OWNER` never 401 (`auth.py:19-24`); §2.1 Seller/Buyer self-read ownership compares path `id` and precedes UUID well-formedness (`routes/parties.py:46-49,97-100`); §2.2 `api_request_id` = `req_` + exactly 20 uppercase-alnum chars (`responses.py:16-20`); §2.2 `api_request_timestamp` from wall clock not logical clock (`responses.py:42`); §2.2 new bullet — HTTP-layer rejections use the same envelope with `ERR_VALIDATION` (`app.py:38-41`); §2.3 empty `limit=`/`offset=` falls back to default, whitespace and leading `+` tolerated (`responses.py:76-90`); §2.3 collection ordering breaks `created_at` ties by insertion sequence (`store.py:68-71`); §2.4 UUID well-formedness by parsing while lookup is exact string match, so variant spellings clear 400 then 404 (`validators.py:34-48`); §2.4 `created_at`/`updated_at` are wall-clock, unaffected by the logical clock (`store.py:43-44,54-65`); §2.5 clock-set `data` shape/200, UTC normalisation, fractional seconds retained though rendering truncates (`routes/clock.py:14-30`, `validators.py:154-171`); §2.5 `_utc` fields render whole-second (`responses.py:31-36`, `serializers.py:10-14,28`); §2.6 one-decimal precision covers `base_multiple`/`age_adjustment`/`effective_multiple_at_close`, ratios serialise as JSON numbers (`serializers.py:15-18,31`, `calc.py:80-83`); §2.9 check 5 absent body read as `{}`, non-JSON/non-object bodies are themselves `ERR_VALIDATION` (`validators.py:19-31`); §3.1 `reciprocity_states` required, two-letter, not deduplicated, not checked against the state's own code (`routes/profiles.py:30`, `validators.py:174-194`); §3.1 `suspension_reason_code` required non-empty, re-suspending succeeds and bumps `version`, nothing returns a seller to `ACTIVE` (`routes/parties.py:64-74`); §3.2 `verified_by_user_id` added to the null-at-creation field list (`serializers.py:61`, `services.py:356`); §4 preamble string filters exact-match, never enum-validated (`routes/profiles.py:60-62`, `routes/parties.py:57-60,108-118`).

**Deliberately left to later passes:** §3.8 introduction-queue ordering (owner `services.py`); the validated `is_superseded` boolean filter (owner `routes/valuations.py`); whether reinstatement clears `verified_by_user_id` (owner `routes/accounts.py`); `ERR_INTERNAL`/500 for unhandled exceptions (`app.py:43-45`) — not pinned because §5's table has no such row and adding one would create new spec surface rather than pin existing prose.

### Pass 2 summary (verbatim)

**Integrity**: I ran no `cp`. I edited the existing `workspace/PRD_COMPLETED.md` in place with 11 targeted `Edit` calls (no `Write`). All 17 of pass 1's edits are still present — I grepped 15 distinctive pass-1 marker phrases and all 15 matched. File still ends at `| ERR_LISTING_NOT_PUBLISHABLE | 422 |`.

**Size**: 565 lines / 122,912 chars before → 565 lines / 126,189 chars after (all changes in-paragraph).

**Counts**: 10 ambiguity-pins, 1 mismatch-revision.

Changes: §2.6 all four-decimal ratios come from one routine yielding exactly `0.0000` on a zero denominator (`calc.py:64-69,305,341-342`); §2.8 `expected_listing_version` must be integer ≥ 0, negative/non-integer is `ERR_VALIDATION` not 412 (`routes/listings.py:193`); §3.2 listing `state_code` exactly two uppercase letters (`routes/listings.py:31-33`); §3.2 amendment merges each window end from request-or-stored, excludes the listing's own stored window from the overlap test, orders the merged end-after-start test after listing resolution and before the status check, and a field-less PATCH still succeeds and bumps `version` (`routes/listings.py:93-129`); §3.2 the withdrawal deal-sweep writes only `status`/`termination_reason_code`/`version` — no escrow refund, no permit cancellation, no introduced-stop reset, `REPRICE_REQUIRED` included (`routes/listings.py:180-184`); §3.2 a `VERIFIED` stop with a null verified figure contributes zero to the roll-up and to verified-basis inputs (`services.py:155,177`); §3.4 a successful snapshot answers 201 with the valuation in `data`, not the listing (`routes/listings.py:211-214`); §3.6 if the exclusion empties the verified set, hop 3 still supersedes the old snapshot but writes no replacement and the chain stops (`services.py:220-226`); §3.8 **mismatch** — introduction-queue tie-break (`services.py:315-316`, `store.py:70`); §3.9 the escrow is rewritten only when the two holdback fields would actually change, so a repeat append does not bump escrow `version` (`services.py:280-296`); §4 boolean `is_superseded` filter plus the fact that no list endpoint scopes rows by ownership (`routes/valuations.py:31-46`, verified against all 12 list handlers).

**Deferred items resolved:** (1) queue ordering — replaced the false "because `created_at` carries millisecond precision the ordering is total" with `route_day` rank → `service_start_date` → `created_at` → insertion sequence as the true final key. (2) boolean filter — pinned `true`/`false`/`1`/`0` in any case, anything else `ERR_VALIDATION`; verified by grep it is the API's only validated query filter.

**Left to later passes**: `routes/accounts.py` owns the write leaving a substitute stop's `verified_repair_mrr_cents`/`verification_variance` null (`accounts.py:284-289`); `routes/deals.py` owns the closing copy of `effective_multiple_at_close`; `routes/settlements.py` owns the escrow-resolution fallback feeding `calc.settlement_figures`.

### Pass 3 summary (verbatim)

**No `cp` was run.** I edited the existing `workspace/PRD_COMPLETED.md` in place with 23 targeted `Edit` calls. All 25 hunks from passes 1–2 are still present (verified by hunk-by-hunk diff against `PRD_FINALIZED.md`: 25 pass-1/2 hunks + 17 of my paragraphs = 42 hunks total).

**Size:** before 565 lines / 126,189 chars → after **565 lines / 132,313 chars**. File still ends at line 565 with `| ERR_LISTING_NOT_PUBLISHABLE | 422 |`.

**Counts:** ambiguity-pins **19**, mismatch-revisions **4**.

Changes: §3.2 duplicate `customer_ref` `ERR_VALIDATION` tested after listing resolution but before its status (`accounts.py:46-51`); §3.3 `verified_by_user_id` stamped with the acting broker on both `VERIFIED` and `DISPUTED` (`accounts.py:112`); §3.3 a re-run landing on the value the stop already holds is accepted and bumps both versions, verification declares no listing-status precondition and no seller-standing gate (`accounts.py:85-115`); §3.6 `exclusion_reason_code` required non-empty (`accounts.py:122`); §3.6 reinstatement takes no body, requires the listing be neither `CLOSED` nor `WITHDRAWN`, a non-`EXCLUDED` stop answers `ERR_INVALID_ACCOUNT_TRANSITION`, and `verified_by_user_id` is *not* cleared (`accounts.py:144-165`); §3.6 a named snapshot that is superseded, carries the other basis, or belongs to another listing all answer `ERR_VALUATION_SUPERSEDED` (`deals.py:352-356`); §3.6 **mismatch** — the PRD glossed `COMPLETE` as "every included stop resolved to `VERIFIED` or `DISPUTED`", contradicting §3.2 and the implementation; revised to "every stop `VERIFIED` or `EXCLUDED`, `verified_account_count` ≥ 1", and pinned that a non-`COMPLETE` posture reports `ERR_VERIFIED_MRR_SHORTFALL` (`deals.py:360-362`); §3.6 `lender_name` 1–160 chars (`deals.py:376`); §3.5 `retention_guarantee_days` at creation integer 30–365 (`deals.py:84`); §3.5 the restated value at acceptance replaces the creation value (`deals.py:260`); §3.5 the two bounds answer differently — <30 or >365 is `ERR_VALIDATION` 400, 30–59 is `ERR_COVENANT_TERMS_INSUFFICIENT` 422 (`deals.py:236` vs `246-248`); §3.5 **mismatch** — a re-acceptance after repricing re-uses the same escrow row rather than creating a second (`deals.py:269-295`); §3.5 **mismatch** — a permit row is minted only for a required type with no non-`CANCELLED` transfer, so re-acceptance does not duplicate rows (`deals.py:299-319`); §3.5 the holding statuses that block the listing release, and that nothing else unwinds on the `REPRICE_REQUIRED` termination edge (`deals.py:485-516`); §3.5 `termination_reason_code` required non-empty (`deals.py:504`); §3.8 only the clock is tested for the introduction window, `introduction_date` is stored as given (`accounts.py:211-215,234`); §3.8 an already-`CLOSED` deal answers `ERR_INVALID_DEAL_TRANSITION`, terminal answers `ERR_DEAL_TERMINAL` (`deals.py:404-411`); §3.8 the three closing checks run in §2.9's order, not the narrated order, so both-failing reports `ERR_ESCROW_UNDERFUNDED` (`deals.py:413-427`); §3.8 `effective_multiple_at_close` read at the closing instant, null when no live snapshot, closing proceeds regardless (`deals.py:440-441`); §3.8 an introduced stop never verified keeps a null `current_mrr_cents` and contributes zero to `guaranteed_mrr_cents` (`deals.py:444-451`); §3.9 replacement preconditions and their order (`accounts.py:250-269`); §3.9 substitute-stop field writes and nulls, 201 carries the substitute (`accounts.py:284-292`); §4 **mismatch** — the `/service-accounts/{id}/replace` row omitted the required `route_day` (`accounts.py:248`).

**Deferred items resolved:** (1) reinstatement does *not* clear `verified_by_user_id` (`accounts.py:158-162` clears only the reason code and three verified figures), so the retained stamp keeps that broker barred from diligence sign-off; cross-checked against `clear_diligence` (`deals.py:339-342`). (2) the substitute's null `verified_repair_mrr_cents`/`verification_variance` — pinned the write itself, consistent with pass 2's §3.2 null-reads-as-zero sentence. (3) `effective_multiple_at_close` — copied from whichever `VERIFIED_BASIS` snapshot is non-superseded *at the closing instant*, null when none is live.

**Left to a later pass:** what a null `effective_multiple_at_close` does to a `REPLACEMENT_BASIS` settlement (owner `routes/settlements.py`). Two impl details judged unreachable and deliberately not pinned: acceptance minting no permit transfers when no state profile matches (publication already requires one), and `terminate`'s no-op on an already-`REFUNDED` escrow (termination is absorbing).

### Pass 4 summary (verbatim)

**No `cp` was run.** I edited `workspace/PRD_COMPLETED.md` in place with targeted `Edit` calls only. Passes 1–3's work is intact: the diff against `PRD_FINALIZED.md` still shows every line they touched, plus my own 15 lines.

**Size:** before my pass 565 lines / 132,313 chars → after 565 lines / 139,770 chars (+7,457 chars, no new lines). `PRD_FINALIZED.md` is 562 lines / 118,549 chars. File is NOT byte-identical to `PRD_FINALIZED.md` (`cmp` differs at line 15) and still ends at `| ERR_LISTING_NOT_PUBLISHABLE | 422 |`.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions, 1 cross-pass coherence revision.

Changes: §2.8 `expected_deal_version` carries no lower bound so a negative value is a 412, unlike `expected_listing_version` which 400s (`routes/attrition.py:32` vs `routes/listings.py:193`); §2.9 check 10 **mismatch** — `ERR_ESCROW_NOT_FOUND` also covers the body `escrow_id` (`routes/settlements.py:39`); §3.7 apply/decide/waive declare no deal-status precondition, and a deal terminated from `REPRICE_REQUIRED` keeps filable rows (`routes/licenses.py:100,142,170`, `routes/deals.py:511-520`); §3.7 `applied_on` never compared to the logical clock (`routes/licenses.py:124`); §3.7 **mismatch** — the retry edge out of `DENIED` retains `decided_on` as well as `denial_reason_code` (`routes/licenses.py:135-137`); §3.7 the buyer-operability `ERR_VALIDATION` precedes both status and profile tests and is skipped when either is unresolvable (`routes/licenses.py:113-122`); §3.7 **mismatch** — the conflict scan includes the re-filed transfer's *own* prior window, which is what enforces the retry buffer (`routes/licenses.py:77-96`); §3.7 rows lacking `applied_on`/`processing_window_end` occupy no window, and filings on different deals contend (`routes/licenses.py:80-91`); §3.7 out-of-order `decided_on` is `ERR_VALIDATION` ahead of the status test, skipped when `applied_on` is null (`routes/licenses.py:154-158`); §3.8 `ERR_DEAL_TERMINAL` precedes `ERR_ESCROW_NOT_OPEN` on deposits (`routes/escrow.py:56-60`); §3.8 the escrow reaches `FUNDED` on its own when the deal is only `ACCEPTED`/`DILIGENCE_CLEARED`, only the `FINANCING_APPROVED` edge cascades (`routes/escrow.py:69-73`); §3.8 `amount_cents` of exactly zero is accepted, stamps `funded_by_user_id`, bumps version, moves no cents (`routes/escrow.py:51,65-75`); §3.9 the recording `X-User-ID` is retained internally for the proposal segregation bar but is not a resource field (`routes/attrition.py:71`, `serializers.py:94`); §3.9 no precondition on the stop's transfer or verification dimension, transfer moves are conditional, null figures read as zero (`routes/attrition.py:75-91`); §3.9 after `SETTLED` a later append recomputes the six ledger figures only, touching neither flag nor escrow holdback fields (`services.py:280-296`); §3.9 with no `escrow_id` the derivation resolves the deal's own escrow while the stored `escrow_id` stays null (`routes/settlements.py:19-22,36-48`); §3.9 **mismatch** — `VOID` is a declared status no endpoint ever writes (`routes/settlements.py:16`); §3.9 null `effective_multiple_at_close` is read as a multiple of zero (`calc.py:336-337`); §3.9 dispute recomputes nothing, snapshot figures and `computed_from_clock_utc` survive (`routes/settlements.py:154-156`); §3.9 execution recomputes nothing and pays from the stored proposal figures (`routes/settlements.py:183-191`); §3.9 the quiet release leaves `clawback_status` as the ledger set it, only a settlement writes `SETTLED` (`routes/escrow.py:103-109`).

**Deferred items resolved:** (1) the `escrow is None` → `from_holdback_cents = 0` branch is **confirmed unreachable** and nothing was pinned for it — a settlement requires `clawback_status == CLAWBACK_TRIGGERED`, only set by `recompute_deal_ledger`, reachable solely from paths that require a `CLOSED`/`GUARANTEE_CLOSED` deal, and acceptance always mints exactly one escrow per deal while closing requires it funded. Only the reachable half was pinned. (2) null `effective_multiple_at_close` under `REPLACEMENT_BASIS` — read as `Decimal("0")`, so both terms and both adjustment figures are zero, the waterfall snapshots a zero draw and carries the whole holdback to the seller, and the resulting draft is unproposable yet still blocks a second settlement.

**Cross-pass coherence check:** one genuine tension found and fixed — §3.9's "That freeze is reversible in both of the ways the ledger can improve" read as unconditional, contradicting the `clawback_status != "SETTLED"` guard at `services.py:280`; scoped to "reversible, up until a settlement settles". Otherwise coherent: verification posture (§3.2/§3.3/§3.6), `verified_by_user_id` (§3.2/§3.3/§3.6/§3.9), conditional escrow rewrite and versioning, `REPRICE_REQUIRED` handling across §2.9/§3.5/§3.6/§3.7/§3.8, and the Step-8 holdback-release ordering in §3.9 all match the implementation and each other. One overreach in pass 4's own first draft (claiming a `TERMINATED` deal always blocks filing) was corrected after checking `routes/deals.py:511-514`.

### Step 9 totals

63 ambiguity-pins + 9 mismatch-revisions + 1 cross-pass coherence revision across the four passes. `PRD_FINALIZED.md` 562 lines / 118,549 chars → `PRD_COMPLETED.md` 565 lines / 139,770 chars (+3 lines, +21,221 chars / +17.9%).

Orchestrator verification: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (121 changed lines in the diff) — the scan genuinely ran. Tail ends at the final §5 error-table row; all five top-level sections present. No difficulty-directive leak in any PRD variant. `test_suite/`/`test_helpers/` remain at the task root with nothing stray under `workspace/`. Step 9 touched only PRD prose, so the final 8-round sweep (results.1–8 = 128/128 each) remains valid.

## Pipeline complete — 2026-09-05T01:06:00.000Z

All nine steps finished. Final artifact set verified: SCAFFOLD.yaml + both design indices, worklog.md, test_helpers/ (9 modules), test_suite/ (13 files, 128 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}, and results.{1..8}.json all at 128/128.
