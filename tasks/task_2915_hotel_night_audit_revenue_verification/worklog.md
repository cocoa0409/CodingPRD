# Worklog — task_2915_hotel_night_audit_revenue_verification

## Step 1: Create task directory — 2026-09-05T16:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification` and its `workspace/` subdirectory. Index 2915 was pre-assigned by the orchestrating caller; no scan of `tasks/` was performed and no index was allocated locally (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T17:39:00.000Z

All three scaffold artifacts are complete and the linter is clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3566 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1675 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2720 |

`worklog.md` and `workspace/` are untouched (workspace/ left empty; only my own `scratch_*` helpers were removed from it).

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     13
  §1.8 instances scanned:     26
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  604

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Contents

- **SCAFFOLD.yaml** — §1.0–§1.7 only (no design keys): 13 entities, 11 state-machine dimensions across 8 entities, 1 OCC concurrency rule, 17 calculations (2 dual-variant), 84 prioritised validations, 69 endpoints, 83 error codes, 6 roles. Profile: `ledger_reconciliation` / `compliance_audit`, flat topology, parallel state machines, `segregation_of_duties` role model, immediate consistency, layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — all 9 Difficulty Rules, 26 instances (2–4 per rule), each with a full `test_recipe`.
- **SCAFFOLD_CORNER_DESIGN.yaml** — all 9 claim-extraction sections, 81 instances (53 full recipes + 28 `excluded_because` stubs, every cited `difficulty_instance` verified to exist): entities 12, state_machines 14, calculations 13, validations 9, endpoints 4, errors 19, rbac 5, cross-cutting layers 4, consistency model 1. Names are unique across both design files with zero collisions.

## Three things worth flagging

1. **The "Generate task harder than expert level!" directive line was deliberately omitted** from the `scenario:` key — only the numbered scenario text itself is stored, so the directive cannot leak into PRD.md via the scaffold.
2. **Two SCAFFOLD.yaml repairs made while authoring §1.9 turned up dead error codes** (both fixed by widening the scaffold, never by weakening a test):
   - `ERR_RECOUNT_LIMIT_REACHED` was unreachable: `redeclare` returns a batch to `DECLARED` "awaiting the next verify-settlements run", but priority 34 required status `CHARGES_SEALED` and nothing led back from `SETTLEMENT_REVIEW`, so `recount_round` could never exceed 1. Added a `SETTLEMENT_REVIEW → SETTLEMENT_REVIEW` re-verify transition (BusinessDate now has 9 transitions), widened priority 34 and `ERR_DATE_NOT_READY_TO_VERIFY`, and updated the endpoint description/side-effect.
   - `ERR_AUTHORIZATION_EXPIRED` (priority 92) was unreachable: `authorization_aging` lapses the row on *any* read or write, so priority 45's `status == APPROVED` gate always fired first with `ERR_AUTHORIZATION_NOT_APPROVED`. Priority 45, the error condition, and the `APPROVED → CAPTURED` preconditions now state that on a capture the aging recompute is evaluated first, so a lapsed authorization is reported as `EXPIRED`; rule 45 keeps `DECLINED`/`CAPTURED` on both actions and `EXPIRED` on decline only.
3. **`POST /night-audit/allowances` was reshaped earlier in the run** so `reason_code?` is optional at creation (with a submit-time fill-in side effect), which is what makes `ERR_REASON_CODE_REQUIRED` and `ERR_SUPPORTING_DOCUMENT_REQUIRED` triggerable at submit.

Two authoring constraints were honoured throughout because the linter parses structured calls: `grounds:` refs are quoted strings, and every deliberately-malformed request appears as a prose `trigger:` string rather than a structured call.

## Step 3: Copy shared files — 2026-09-05T17:40:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T18:00:00.000Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification/workspace/PRD.md`

- **Final line count:** 538
- **Final char count:** 114,316
- **Exact last section heading:** `## 5. Error Code Catalogue` (file ends on the completed final table row `| \`ERR_TIE_OUT_ATTEMPT_LIMIT_REACHED\` | 409 |`, a real section boundary)

**Structure:** §1 Introduction; §2 with 12 domain-titled subsections (2.1 Operator Identity and RBAC → 2.12 Rejection Precedence), §2.2 emitted byte-verbatim from `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (verified by exact substring match); §3 with 9 subsections (3.1 property/outlets/calendar, 3.2 reservations and paperwork, 3.3 room-and-tax pass, 3.4 outlet checks, 3.5 shift settlement, 3.6 allowances, 3.7 departure/tenders/manual lines/card authorizations, 3.8 seal-sweep-balance-publish-close-reopen, 3.9 month-end tie-out and retention); §4 endpoint table with exactly 4 columns and all 69 endpoints; §5 error table with exactly 2 columns and all 81 error IDs.

**Hard Contract 1 — Field-Name Coverage: PASS.** Two independent mechanical passes. Pass 1 (whole document): 152 entity field names, 82 request-body input fields, 35 query params, 1 path param (`id`) — 0 missing. Pass 2 (stricter: restricted to §1–§3 prose only, after stripping fenced code blocks): same 270 identifiers plus all 92 enum values plus all 81 error IDs — 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 17 calculations expressed in prose (including the PROVISIONAL vs FINAL tax bases, round-then-sum city-ledger fee, order-sensitive late-checkout floor/ceiling, and the gross-vs-net discount gate); all 51 state-machine transitions covered (30 with explicit `FROM` → `TO` arrows, the remaining 21 — the re-derived folio settlement dimension, the in-request auto-advances, and the system forks — narratively, each verified by hand); the single OCC rule stated with write operation + `expected_business_date_version` + `ERR_STALE_BUSINESS_DATE_VERSION` + HTTP 412; the 12-band rejection precedence enumerated in §2.12 with the charge-seal `applies_to` set fully listed and the journal-reversal widened-set carve-out spelled out; all four segregation-of-duties originator bars, the frozen approval tier, field defaults/initial values, and all sibling branches (three no-show policies, three follow-up actions, two pace bases, two tax variants, match/variance fork, tie-out pass/fail, approve/reject review) written at equal density.

**Hard Contract 3 — §3 Path Purity: PASS.** Mechanical scan of every backticked token in §3: zero tokens beginning with `/`, zero bare HTTP methods, zero method+path combinations. §3 uses state-transition, role+action-verb, and capability framing throughout.

Two corrections made during the pass, both from misreading stitched `sed` output: a paragraph wrongly asserting that the comp-authorization gate also guards check closing was removed (the scaffold scopes it to the room-and-tax run alone), and `ERR_LEDGER_ACCOUNT_NOT_FOUND` is documented at 404 per the error catalogue. Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped; no sibling task directory was read; `worklog.md`, `SCAFFOLD*.yaml`, and `workspace/INSTRUCTION.md` were untouched; both task-scoped scratch scripts were deleted, so `workspace/` now holds only `INSTRUCTION.md` and `PRD.md`.

**Orchestrator verification:** confirmed PRD.md is not truncated — 538 lines, ends on a complete error-catalogue table row; all five top-level sections (§1–§5) present. No difficulty-directive or scaffold-reference leakage found.

## Step 6: Generate implementation — 2026-09-05T18:35:00.000Z

The implementation is complete and boots clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification/workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` (executable) | 8 |
| `requirements.txt` | 1 |
| `app.py` | 51 |
| `db.py` | 149 |
| `errors.py` | 107 |
| `response.py` | 46 |
| `middleware.py` | 53 |
| `shapes.py` | 177 |
| `money.py` | 35 |
| `constants.py` | 39 |
| `services/calc.py` | 134 |
| `services/derive.py` | 304 |
| `services/lookup.py` | 140 |
| `services/serial.py` | 260 |
| `services/__init__.py` | 0 |
| `routes/__init__.py` | 31 |
| `routes/clock.py` | 17 |
| `routes/properties.py` | 64 |
| `routes/outlets.py` | 74 |
| `routes/ledger_accounts.py` | 58 |
| `routes/periods.py` | 76 |
| `routes/business_dates.py` | 389 |
| `routes/folios.py` | 192 |
| `routes/journal.py` | 106 |
| `routes/tickets.py` | 177 |
| `routes/batches.py` | 160 |
| `routes/allowances.py` | 253 |
| `routes/documents.py` | 141 |
| `routes/cards.py` | 179 |
| `routes/reports.py` | 115 |

Total 3536 lines across 30 files; all 14 blueprints registered, every endpoint in the PRD §4 table implemented.

## Smoke test result

Booted with `PORT=57431 bash start.sh` (foreground `exec python3 app.py`, bound `0.0.0.0`), then drove a 55-request happy path plus negative checks through a scratch script — **0 failures**, no 500s, no import errors:

- Full pipeline: clock set → property → outlet → ledger account → business date → folio → check-in → post-room-and-tax → outlet checks (open/close, room-charge + cash) → settlement batch → allowance raise/submit/return/resubmit/approve/reverse → controller-tier allowance blocked by `ERR_ALLOWANCE_DOCUMENT_MISSING` (409) then approved after paperwork file+review → doc revoke → card auth create/capture, second auth decline → follow-up CONTACT → RESOLVE → seal-charges → verify-settlements → balance → revenue report → distribute → close → period tie-out.
- Arithmetic cross-checked against the PRD: day `room_revenue_amount` 110.00 (ROOM 210 − 40 rebate − 100 rebate + 40 reversal), `tax_revenue_amount` 13.75 (26.25 provisional + −12.50 `TAX_TRUE_UP` on the net-of-allowance base), `outlet_revenue_amount` 618.67 (490.93 + 127.74), settlement variance 0.49 inside the 5.00 tolerance → `MATCHED`, occupancy 1.00%, ADR 110.00, RevPAR 1.10, pace index 11.00%.
- Negative paths verified: 401 unknown role, 403 wrong role, 400 missing required field, 404 unknown id, 412 `ERR_STALE_BUSINESS_DATE_VERSION` on a stale report create.
- The specific PID was killed afterwards (no broad `pkill`); a second fresh boot on port 57952 confirmed an empty store (`GET /night-audit/properties` → `total_count: 0`) and the default logical clock `2026-08-01T00:00:00.000Z`. Scratch dir `workspace/scratch_2915/` and both temp logs deleted; `__pycache__` cleaned.

## Storage

Purely in-memory: `db.py` holds a single `Store` object of plain dicts, created empty at import. There is no SQLite file, no JSON on disk, no `/tmp` cache, and **no seeding of any kind** — `grep -rn "seed\|preload\|hardcode"` matches only the docstrings in `app.py`/`db.py` that state the invariant. Every entity a test needs is built through declared endpoints.

## Notable interpretation decisions

- §2.12 ("Implementations must evaluate in this sequence") governs cross-band ordering over the narrative gate lists in §3.6/§3.7: charge-seal before endpoint state, paperwork gate before the approved-amount check, and balance assertions ordered declined-auth → settlements → ledger control. Within band 9 the PRD's own enumeration ("segregation of duties, approval tiers, outlet scope, paperwork gates") sets self-approval before tier before document, matching scaffold priorities 50/52/56.
- Capture runs the ageing recompute before the status gate, per the PRD's explicit statement, so a lapse during the request yields `ERR_AUTHORIZATION_EXPIRED` rather than `ERR_AUTHORIZATION_NOT_APPROVED`.
- Card-authorization lapse observed on reads changes `status` to `EXPIRED` without bumping `updated_at`/`version` (a GET must not mutate); the explicit lapse pass inside `balance` does bump, being a declared system write.
- The `ALLOWANCE` line minted by a reversal carries `allowance_id` of the new compensating allowance and `reverses_posting_id` of the original approval line.
- Document interval-overlap is only evaluated for folio-targeted paperwork (`ALLOWANCE_APPROVAL` rows carry a null `folio_id`, so they never collide with each other).

## Step 5: Generate unit tests — 2026-09-05T19:20:00.000Z

Test suite generation for `task_2915_hotel_night_audit_revenue_verification` is complete.

## Output location (verified at the task root, not under `workspace/`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2915_hotel_night_audit_revenue_verification/test_suite/`

## Totals
**108 tests**, collected clean by pytest (`108 tests collected in 0.26s`), every file `py_compile`-clean, zero unused imports.

test_helpers (9 files, 2617 lines): `__init__.py` 22, `api_client.py` 487, `api_errors.py` 200, `assertions.py` 221, `constants.py` 196, `factories.py` 354, `fixtures.py` 754, `test_users.py` 136, `types.py` 247.

test_suite (20 files, 8430 lines / tests): `conftest.py` 76, `test_01` 737/12, `test_02` 1009/11, `test_03` 120/2, `test_04` 333/6, `test_05` 246/4, `test_06` 665/12, `test_07` 355/7, `test_08` 337/6, `test_09` 247/4, `test_10` 128/2, `test_11` 176/2, `test_12` 113/2, `test_13` 348/8, `test_14` 638/6, `test_15` 632/7, `test_16` 489/4, `test_17` 826/7, `test_18` 674/4, `test_19` 281/2.

## Design-index audit (machine-checked)
- 26 live difficulty instances → all translated, **every one with ≥2 tests**.
- 53 live corner instances → all translated, **every one with ≥1 test**; the 28 `excluded_because:` stubs were not translated (by design).
- No test is untagged or dual-tagged; every tag is the last docstring line and matches a real `name:` verbatim; no tag points at a stub or a non-existent instance.
- No docstring or comment mentions the scaffold or a scaffold section; citations are PRD-only.

## Instances/claims skipped or narrowed (PRD-first filter)
No live instance was skipped, but three recipe claims were dropped as not uniquely derivable, and the surrounding assertions kept:
- `rbac_segregation_of_duties...`: the recipe's "second CASH batch declared by RevenueManager" is impossible — PRD gives `POST /settlement-batches` to OutletManager and NightAuditor only. Replaced with the reachable identity clash: an admitted `Controller` whose `X-User-ID` equals the batch's `declared_by_user_id` (the outlet id) → `ERR_SELF_APPROVAL_FORBIDDEN`, then `u_ctl_1` accepts → 200.
- `layer_optimistic_concurrency...`: the recipe's absolute day versions (stale 4 / fresh 5, "+1 per accepted write") are unsafe because every line stamped to a day re-derives it. The staleness is instead manufactured by the PRD-explicit mechanism (report creation increments the day's `version`), and versions are read dynamically; 0, 99 and the stale value all → 412, omission → 400, refusals consume no version, then the fresh value → 201 and the predecessor flips to `SUPERSEDED`.
- `consistency_immediate...`: the recipe's SETTLEMENT_REVIEW day contradicts the approve gate (an approval needs a day that still accepts charges), so the day is walked through close and `REOPENED` with a fresh DISTRIBUTED report — the same shape test_06 uses — and the recipe's unsigned `credits_total_amount == 200.00` is asserted with the PRD's signed convention (`-200.00`).

## Housekeeping
`workspace/scratch_2915_unused.py`, `workspace/scratch_2915_prune.py`, `/tmp/na_scaffold_errs_2915.txt`, `/tmp/na_mine_errs_2915.txt` and all `__pycache__`/`.pytest_cache` dirs deleted. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` (never read). `worklog.md`, `SCAFFOLD*.yaml`, `workspace/PRD.md` and `workspace/INSTRUCTION.md` untouched; no server was started and no `pkill` was run.

## Step 7: Run tests and iterate — 2026-09-05T19:47:00.000Z

All 8 rounds pass 108/108. `worklog.md` untouched (still 19:28, pre-my-work). No test was deleted outright; one assertion was dropped.

## Summary

**Iterations run:** 3 full 8-round sweeps (99/108 → 107/108 → **108/108**). All failures were deterministic (identical in all 8 rounds every time) — no load-induced flakiness appeared.

**Tests deleted:** none. One assertion removed under STEP 1c (partial coverage):
- `test_14_calculations_and_derivations.py::test_the_city_ledger_sweep_takes_only_departed_direct_bill_debtors` — dropped only the `settlement_status == "SETTLED"` expectation on the `settled` folio. **Non-unique-derivability.** That folio has *zero* journal lines (its late-checkout charge was `0.00` so PRD §3.7 wrote no line, and §3.3 skips a `DEPARTED` account). PRD §3.7 scopes the derivation to "re-derived from the account's own two running totals **after every line that touches it**", and §3.2 states the account "begins ... `UNSETTLED` ... with `charges_total_amount`, `credits_total_amount`, and `balance_amount` all at `0.00`". For a never-touched folio those two sentences admit both readings, so the outcome isn't determined. The assertions that actually prove the sweep-filter exclusion (`balance_amount == 0.00`, no `CITY_LEDGER_FEE` line) were kept, as were the `UNSETTLED` expectations on the two folios that *do* carry lines.

**Fixes to `test_helpers/`:** none needed — the helper layer was sound.

**Fixes to `test_suite/` (5):**
- `test_02_…close_sequence.py::test_one_decline_fires_three_side_effects…` — capture called as `FRONT_DESK`; PRD §3.7 says "**Capturing** is reserved to the `NightAuditor`" (§4 agrees), so §2.12's authorization band correctly returned `ERR_UNAUTHORIZED` before the state check. Switched to `AUDITOR` so the intended `ERR_AUTHORIZATION_NOT_APPROVED` is reached.
- `test_15_validations.py::test_only_a_rate_error_allowance…` — setup booked `contracted_rate_amount=400.00` against a `200.00` rack rate = 100% variance, above the shared property's deliberately-wide 95% tolerance, so check-in correctly raised `ERR_RATE_VARIANCE_UNAUTHORIZED`. Lowered to `380.00` (90%, inside tolerance); nothing downstream depended on the rate.
- `test_15_validations.py::test_settlement_resolution_can_only_be_judged…` — asserted `variance_amount == -160.48`; PRD §3.5 defines it as "`declared_amount` minus `system_amount`", i.e. `160.48 − 0.00 = +160.48`. Sign corrected (the sibling test in test_08 already asserted the positive convention).
- `test_18_rbac_and_segregation.py::test_no_role_can_reach_another_roles_exclusive_operations` — asserted `status` on a folio; a Folio has no such field, it carries `stay_status`/`settlement_status` (§3.2). Corrected to `stay_status`.
- `test_19_concurrency_and_consistency.py::test_one_approval_lands_its_whole_cascade…` — expected `pace_index_pct == 50.00` but the day was opened without benchmarks, which default to `0.00`, and §3.8 says the index "is exactly `0.00` when that benchmark is `0.00`". Supplied `benchmark_calendar_room_revenue_amount=400.00` so the PRD formula (`100 × 200.00 / 400.00`) yields the asserted 50.00 — kept the assertion, fixed the precondition.

**Fixes to `implementation/` (3 sites, 2 defects):**
- `services/serial.py::folio_out` + `routes/folios.py` (list filter) — the serializer recomputed `settlement_status` on every read, so a brand-new folio (balance `0.00`, no lines) reported `SETTLED`, contradicting PRD §3.2's explicit initial `UNSETTLED`. Now reports the stored field, which `derive.rederive_folio` already maintains on `append_posting` — verified to be the *single* journal-line path, so the stored value is always current. The city-ledger sweep's terminal `TRANSFERRED_TO_CITY_LEDGER` write is unaffected (it sets the field after appending its lines).
- `services/derive.py::date_aggregates` — `settlement_variance_total_amount` summed every batch with a non-null variance except `RECOUNT_REQUESTED`, so a `MATCHED` batch's variance leaked in (10.01 instead of 5.01). PRD §3.5 gives the contributing set as `VARIANCE_FLAGGED` ("additionally contributes the absolute value of its variance") plus `ACCEPTED_WITH_VARIANCE` ("continues contributing"); restricted to those two.

**Final round-by-round:** R1 108/108, R2 108/108, R3 108/108, R4 108/108, R5 108/108, R6 108/108, R7 108/108, R8 108/108 — 0 failed, 0 errors in every round. `__pycache__`/`.pytest_cache` cleaned; no seeded data added to the implementation (storage remains in-memory dicts).

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (all written 19:47) — every round reports `passed=108 total=108 failed=0 errors=0`. Step 8 is NOT skipped: Step 7 applied 2 implementation defect fixes across 3 sites.

## Step 8: Finalize PRD — 2026-09-05T19:55:00.000Z

Done. Two edits to `PRD_FINALIZED.md`, both tracing to the two `implementation/` defects in `<step_7_diff>`; the five `test_suite/` fixes and the one dropped assertion needed no new prose beyond edit #1 (the rest were fixture/precedence bugs the PRD already determines).

**Line counts:** PRD.md 538 → PRD_FINALIZED.md 538 (0.0% delta; 2 lines revised in place, file still ends with the complete `## 5. Error Code Catalogue` table).

**Changes**

- §3.7 (settlement-dimension derivation paragraph) — revise — added that the re-derivation is the only thing that computes `settlement_status`, that it is stored as each line is appended and **not** recomputed on read, so a folio no journal line has touched yet still reports the initial `UNSETTLED` despite `balance_amount == 0.00`, and that thereafter it reports whatever the most recent touching line left — `services/serial.py:112` (reports `row["settlement_status"]`), `services/derive.py:110-115` + `:302-303`, `routes/folios.py:61`, `routes/folios.py:83`.
- §3.5 (verdict paragraph) — revise — pinned that a `MATCHED` batch contributes nothing to `settlement_variance_total_amount` even when its stamped variance is non-zero, and closed the contributing set: the day figure is the rounded sum of `|variance_amount|` over exactly the day's `VARIANCE_FLAGGED` and `ACCEPTED_WITH_VARIANCE` batches — `services/derive.py:212-225`.

**Per-edit pre-edit search log**

Edit 1 — (a) Subject: how `settlement_status` is produced/stored/reported for a Folio, including its terminal value. (b) Enumerated: grepped `settlement_status|rederive_folio|folio_figures|folio_balance` across all of `implementation/`, then read every hit — `derive.folio_figures` (:69-93, preserves stored `TRANSFERRED_TO_CITY_LEDGER`), `derive.rederive_folio` (:110-115), `derive.append_posting` (:280-309, verified the *only* posting-insert path via a grep for `insert("postings"`/`append_posting`, 18 call sites, all through it), `serial.folio_out` (:86-118, recomputes charges/credits/balance live but reads the stored verdict), `routes/folios.py` create (:44-63 initial `UNSETTLED`), list filter (:75-88), tender gate (:184), `routes/journal.py:37,51`, `routes/tickets.py:106,121,153`, `routes/allowances.py:124,147,228`, `routes/cards.py:114`, `routes/business_dates.py:131-194` (room/tax + true-up appends) and `:286-315` (sweep: three appends, *then* the terminal write). (c) Adjustment: scoped "not recomputed on a read" to the verdict only — `charges_total_amount`, `credits_total_amount` and `balance_amount` *are* recomputed live in `folio_out`, so a blanket "nothing is recomputed on read" would have been a new mismatch; and phrased the stored-value rule as "whatever the most recent line touching it left there" rather than "always equals the derivation", so the sweep's terminal `TRANSFERRED_TO_CITY_LEDGER` write (and the paragraph's existing exception sentence) stays true. Also confirmed a comp folio's `0.00` `ROOM`/`OCCUPANCY_TAX` lines *do* drive it to `SETTLED`, so the wording keys on "no line has touched it", not on "balance is 0.00".

Edit 2 — (a) Subject: which batch states feed `settlement_variance_total_amount` (and, adjacently, `unresolved_settlement_batch_count`). (b) Enumerated: `derive.date_aggregates` :212-225/:241-242 (sole computation of both figures; recomputed on every serialization via `serial.business_date_out` :81), every batch state-writer in `routes/batches.py` — create (:64-79, variance null), `request_recount` (:92-94), `redeclare` (:119-125, clears `variance_amount` to null, keeps `system_amount`), `accept_variance` (:139-141) — plus the verification step and the balance-step assertions in `routes/business_dates.py` (verify stamps variance only while resolving to `MATCHED`/`VARIANCE_FLAGGED`; balance reads `unresolved_settlement_batch_count` and never the variance total). Confirmed no path can leave a `DECLARED` batch holding a non-null variance, so the closed-set sentence is safe. (c) Adjustment: changed "even though it carries a stamped non-zero variance" to "even when the variance it has been stamped with is non-zero", since a `MATCHED` batch may legitimately carry `0.00`; left `unresolved_settlement_batch_count` prose untouched (already fully determined elsewhere in §3.5, and impl agrees).

No scratch files were created; `PRD.md`, `implementation/`, `test_suite/`, `test_helpers/` and `worklog.md` were not modified.

**Orchestrator verification:** `cmp` confirms PRD_FINALIZED.md DIFFERS from PRD.md; both edits are present in the diff (§3.5 verdict paragraph line 264, §3.7 settlement-dimension paragraph line 320) and the file still ends on the complete error-catalogue table.

## Step 9: Complete PRD — 2026-09-05T21:10:00.000Z

Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were forbidden to re-copy). Partition was by implementation module so the passes' subjects were disjoint, and each pass received the previous passes' out-of-slice findings as an explicit hand-off list. Net result: **69 edits (43 ambiguity-pins, 26 mismatch-revisions)**, 62 lines revised in place, 538 lines unchanged, +27,055 chars over `PRD_FINALIZED.md`.

### Pass 1 — core plumbing, cross-cutting mechanics, configuration/registry endpoints
Slice: `app.py`, `constants.py`, `db.py`, `errors.py`, `middleware.py`, `money.py`, `response.py`, `shapes.py`, `routes/__init__.py`, `routes/clock.py`, `routes/properties.py`, `routes/outlets.py`, `routes/ledger_accounts.py`, `routes/periods.py`, `services/lookup.py`, `services/calc.py`.
Performed the `cp` itself, exactly once. 115,167 → 123,655 chars (+8,488). **15 ambiguity-pins, 6 mismatch-revisions (21 edits).**

- §2.1 — insert — ambiguity — header values trimmed before evaluation; whitespace-only counts as empty — `middleware.py:34-39`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` read from the logical clock — `response.py:13,19`
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` 400; empty string = omitted; over-large offset yields an empty page; `created_at` ties broken by insertion order — `shapes.py:123-158`, `db.py:143-145`
- §2.3 — insert — ambiguity — filters are exact raw-string matches, unrecognised enum values match nothing rather than 400; boolean filters *are* validated — `shapes.py:161-177`
- §2.4 — insert — ambiguity — `id` is a random v4 UUID, canonical lowercase hyphenated; `created_at` from the logical clock — `db.py:53-65,131-140`
- §2.4 — insert — ambiguity — one request advances a row's `version` by at most 1 however many of its writes reach the row, and stamps `updated_at` once — `services/derive.py:18-31`
- §2.5 — insert — ambiguity — `current_utc` required; clock may move backwards; 200 with empty `data` — `routes/clock.py:12-17`
- §2.5 — insert — ambiguity — inbound instants are lenient (`T`/space, optional seconds, 1–9 fractional digits, `Z` or `±HH:MM`, no-zone read as UTC); output always `Z` with 3 digits — `db.py:57-97`
- §2.6 — insert — ambiguity — JSON numbers may serialise without trailing zeros — `money.py:20-26`
- §2.6 — insert — ambiguity — "half up" = half away from zero; configuration money stored as supplied, transacted amounts quantized to 2dp on input — `money.py:15-17` + call sites
- §2.7 — insert — ambiguity — every rulebook setting required except the three with defaults; explicit `null` takes the default — `properties.py:13-31`, `shapes.py:91-112`
- §2.7 — revise — ambiguity — manager/controller threshold-ordering violation is `ERR_INVALID_REQUEST` 400 at step 3 — `properties.py:38-42`
- §2.9 — insert — ambiguity — cascade mutations increment each record once per request — `services/derive.py:22-29`
- §2.9 — revise — mismatch — **four** supersession producers, not three; supersession keys off `charge_type` — `services/derive.py:11,307-308`, `tickets.py:125,157`
- §2.12 step 3 — insert — ambiguity — absent/empty body read as `{}`; invalid JSON, non-object body, required field explicitly `null`, out-of-bounds numbers all → 400 — `shapes.py:29-114`
- §3.1 — insert — ambiguity — property `name` not unique; listing narrows by `name` alone — `properties.py:56-64`
- §3.1 — revise — mismatch — outlet listing narrows by `property_id`, `outlet_type`, `status` only — `outlets.py:60-73`
- §3.1 — insert — ambiguity — suspension is idempotent; no un-suspend — `outlets.py:45-51`
- §3.1 — revise — 3 mismatches + 2 pins — ledger `account_code` uniqueness NOT enforced; `credit_limit_amount` never enforced on ledger accounts; listing supports `property_id`/`ledger_type` only; defaults; `current_balance_amount` derived per read — `ledger_accounts.py:19-27,47-57`, `serial.py:180-189`
- §3.9 — insert — ambiguity — tie-out gate order tieable → attempt-limit → open-days; a period owning no day ties against `0.00` — `periods.py:19-33`
- §3.9 — insert — ambiguity — only `gl_control_total_amount` stored; the other two derived; variance reads `null` before any attempt — `serial.py:47-64`, `derive.py:255-260`
- §4 — revise — mismatch — "two endpoints are creations that read as actions" → exactly one (journal reversal) — `journal.py:86`, `allowances.py:234`, `app.py:18`
- §5 — revise — mismatch — two transport-level refusals outside the catalogue: unrouted path → 404, unsupported method → 405 — `app.py:29-32`

### Pass 2 — business-date close engine, folio/journal layers, shared derivation & serialization
Slice: `routes/business_dates.py`, `routes/folios.py`, `routes/journal.py`, `services/derive.py`, `services/serial.py`. Did NOT re-copy. 123,655 → 131,406 chars (+7,751). **11 ambiguity-pins, 14 mismatch-revisions (25 edits).**

- §2.8 — insert — ambiguity — hand-posted `amount` of zero is 400 at step 3, ahead of existence checks — `journal.py:29-31`
- §2.8 — revise — mismatch — `night_index` not universal on `ROOM`/`OCCUPANCY_TAX`; a compensating line never inherits it — `business_dates.py:130-153`, `journal.py:80-85`
- §2.8 — revise — mismatch — `reason_code` is not "null elsewhere"; a client may supply it on any hand-posted line — `journal.py:26,59`
- §2.8 — revise — mismatch — reversal copies `reason_code`; `night_index`/`outlet_ticket_id`/`allowance_id` null; any of the twelve classes may be reversed — `journal.py:64-85`
- §2.12 step 7 — revise — mismatch — the "exactly these writes" list omitted checking a guest in — `folios.py:98`
- §3.1 — insert — ambiguity — `out_of_order_room_count` ceiling judged after `property_id` resolves, 400, ahead of the duplicate-day check — `business_dates.py:49-55`
- §3.2 — revise — mismatch — `confirmation_code` uniqueness is NOT enforced — `folios.py:44-62`
- §3.2 — revise — mismatch — `credit_limit_amount` caps exactly two writes, not "any charge" — `journal.py:50-54`, `tickets.py:106-109`
- §3.2 — insert — ambiguity — cancellation names no operating day, so neither seal gate nor archived refusal reaches it — `folios.py:154-165`
- §3.3 — revise — ambiguity — `ROOM`-line count spans every day and counts a compensating line as one more, so reversal never frees a night — `business_dates.py:108-127`
- §3.3 — insert — ambiguity — `is_comp` plays no part in the no-show branch — `business_dates.py:138-157`
- §3.7 — insert — ambiguity — check-out runs a lapse pass (bumping `version`) before the sufficiency test; the four gates listed by subject, not precedence — `folios.py:135-144`
- §3.7 — insert — ambiguity — a routed tender moves the named ledger account's balance and `version` — `folios.py:187-190`, `derive.py:304`
- §3.7 — insert — ambiguity — `ERR_CHARGE_TYPE_NOT_POSTABLE` sits at step 8; cross-property anchors on the day's property; credit limit binds `MISC_CHARGE` only — `journal.py:34-54`
- §3.7 — revise — mismatch — reversal copy list corrected here too — `journal.py:80-85`
- §3.7 — revise — mismatch — `declined_authorization_count` is property-wide and day-less, derived per read — `derive.py:149-157,244`
- §3.7 — revise — mismatch — `RESOLVE` drops the property-wide count, not "the day's" — `derive.py:149-157`
- §3.8 — insert — ambiguity — seal walks the property's accounts in `created_at` order regardless of `stay_status` — `business_dates.py:178-195`
- §3.8 — revise — mismatch — sweep picks the earliest-created `CITY_LEDGER` account; with none it writes the balancing line with a null `ledger_account_id` rather than refusing — `business_dates.py:278-306`
- §3.8 — revise — mismatch — ledger balance rises only when such an account exists; the pair nets to zero either way — `business_dates.py:300-306`
- §3.8 — revise — mismatch — lapse pass follows the archived refusal and state gate, bumps each lapsed row's `version`, and the three assertions run declined → settlements → ledger control — `business_dates.py:327-345`
- §3.8 — revise — mismatch — no day aggregate or statistic is stored except the three sweep totals; all derived per read — `derive.py:176-247`, `serial.py:67-83`
- §3.8 — revise — ambiguity — close increments the period's `version` as well as the day's — `business_dates.py:369`
- §3.8 — revise — ambiguity — reopen likewise increments the period's `version` — `business_dates.py:388`
- §4 — revise — mismatch — GET `/journal-postings` carried the POST row's description — `journal.py:95-106`

Hand-off verdicts: items 1, 2, 3, 5, 7, 8 pinned; item 4 already pinned by Step 8's §3.7 prose; item 6 pinned for the 400, listing-filter half already pinned by pass 1.

### Pass 3 — outlet tickets, shift settlement, allowances, authorization documents, card authorizations, revenue reports
Slice: `routes/tickets.py`, `routes/batches.py`, `routes/allowances.py`, `routes/documents.py`, `routes/cards.py`, `routes/reports.py`. Did NOT re-copy. 131,406 → 142,222 chars (+10,816). **17 ambiguity-pins, 6 mismatch-revisions (23 edits).**

- §4 — revise — mismatch — `GET /outlet-tickets` row carried the POST row's description — `tickets.py:167-177`
- §3.4 — insert — ambiguity — suspended-outlet refusal evaluated last (after duplicate-number); outlet status consulted at open only — `tickets.py:42-63,87-138`
- §3.4 — insert — ambiguity — close gates by subject: charge-seal first, then `OPEN`, then scope, credit-limit last — `tickets.py:93-108`
- §3.4 — insert — ambiguity — a close-supplied `transmitted_at` overwrites one set at open — `tickets.py:115-118`
- §3.4 — revise — mismatch — void unwinds only `total_amount`; the four priced figures, `closed_at`, `closed_by_user_id` stand — `tickets.py:142-145`
- §3.4 — revise — ambiguity — the reversing `OUTLET_TRANSFER` DOES inherit `outlet_ticket_id`, is `OUTLET_POS`, and names the voiding operator — `tickets.py:153-155`
- §3.5 — insert — ambiguity — same suspended-last ordering; redeclare ignores outlet status; only the archived-day refusal reaches batch writes — `batches.py:52-63,107-111`
- §3.5 — insert — ambiguity — `system_amount`/`variance_amount` stay stamped on a `RECOUNT_REQUESTED` row — `batches.py:92-94`
- §3.5 — insert — ambiguity — redeclare clears only `variance_amount`; `system_amount` keeps the last reconciled figure — `batches.py:112-125`
- §3.6 — revise — mismatch — approve-gate list claimed §2.12 precedence order but contradicted it; re-listed by subject, added the missing `ERR_FOLIO_ALREADY_TRANSFERRED` gate, stated the real order (sealed → transferred → state → originator → tier → paperwork → amount) — `allowances.py:120-142`
- §3.6 — insert — ambiguity — `APPROVED` is a status no stored row ever holds — `allowances.py:146`
- §3.6 — insert — ambiguity — reversal copies `narrative`/`supporting_document_reference`, stamps both user fields from the reverser, `approved_at` stamped, no tier/originator/paperwork check, posting's `allowance_id` names the compensating row, response is the original at 200 — `allowances.py:199-234`
- §3.2 — revise — mismatch — the reference is stored and echoed on any document type and never compared even on `RATE_OVERRIDE`; cross-property precedes target-mismatch — `documents.py:41-56,82`, `lookup.py:124-131`
- §3.2 — insert — ambiguity — overlap test reaches only folio-bearing filings; `REJECTED`/`REVOKED` docs free their interval — `documents.py:65-72`
- §3.2 — insert — ambiguity — `reviewed_at` stays at the original review; no originator bar on revoke — `documents.py:113-123`
- §3.7 — insert — ambiguity — `authorized_amount` strictly > 0; recording names no day, so no archived/charge-seal/cross-property gate — `cards.py:39-59`
- §3.7 — insert — ambiguity — the read-path lapse moves `status` without `updated_at`/`version`; only the two deliberate passes bump it; a stale `obtained_at` yields a 201 already `EXPIRED` at version 1 — `cards.py:18-32,60,167,173`
- §3.7 — insert — ambiguity — on decline the lapse runs first and a lapsed row gets `ERR_AUTHORIZATION_NOT_APPROVED`; `ERR_AUTHORIZATION_EXPIRED` is capture-only — `cards.py:69-72`
- §3.7 — revise — mismatch — the decline moves exactly three rows' version (auth, folio, folio's arrival day, whatever its status) — `cards.py:76-82`
- §3.7 — insert — ambiguity — a supplied `ledger_account_id` routes the capture line and moves that account's balance/version; a `TRANSFERRED_TO_CITY_LEDGER` account still accepts a capture — `cards.py:97,114-116`
- §3.7 — insert — ambiguity — `RESOLVE` moves three rows' version; `CONTACT`/`ESCALATE` only the authorization's — `cards.py:155-160`
- §3.8 — insert — ambiguity — `recipient_role_list` elements must be strings but role names are unvalidated and an empty array is accepted at creation; the day's state gate precedes the version token — `reports.py:29-39`
- §3.8 — revise — mismatch — `ERR_REPORT_NOT_DRAFT` precedes element-type validation (a departure from §2.12 step 3); the emptiness rule applies to the effective list — `reports.py:81-96`

All four hand-off items confirmed and pinned. Two pre-existing claims were minimally corrected (the §3.7 decline "does not touch a CLOSED day's version" sentence, false for the folio's arrival day; the §3.6 claim that approve gates were listed in §2.12 precedence order). No earlier pass's sentence was reverted.

Pass 3's explicit residual statement: nothing behavioral in its slice remains unpinned. Two deliberate non-edits — the abridged "filterable by …" phrases in several §4 list rows (not false, and §3 prose pins each full filter set), and the tie-break when two candidate original postings match a reversal lookup (unobservable, since at most one candidate can ever exist).

### Orchestrator verification
- `PRD_COMPLETED.md` is 538 lines / 142,222 chars and **DIFFERS** from `PRD_FINALIZED.md` (62 lines revised) — it is not the byte-identical no-op that indicates a skipped scan.
- All five top-level sections (§1–§5) still present at lines 3/11/176/376/452; file ends on the complete final error-catalogue row.
- No file under `implementation/`, `test_suite/`, or `test_helpers/` has been modified since the green sweep's `results.1.json` (19:47), so the verified 8×108/108 result still describes the shipped code.

## Pipeline complete
Steps 1–9 all finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (20 files, 108 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (30 files) with `results.{1..8}.json` all at 108/108. The orchestrator's own sweep artifacts (`workspace/run_sweep.sh`, `workspace/sweep.log`, `workspace/round.{1..8}.log`) were removed at the end; the spliced `sweep.log` had no diagnostic value and the per-round results files are the durable evidence.
