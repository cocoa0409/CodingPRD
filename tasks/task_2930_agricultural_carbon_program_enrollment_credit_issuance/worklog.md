# Worklog — task_2930_agricultural_carbon_program_enrollment_credit_issuance

## Step 1: Create task directory — 2026-09-05T17:53:32.274Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance` and its `workspace/` subdirectory. Index 2930 was pre-assigned by the orchestration prompt (no scan of ./tasks/ performed, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold (subagent: prd-bench-scaffold-generator) — 2026-09-05T19:35:18.403Z

Step 2 complete. All three scaffold artifacts are written and the linter is clean.

## Linter verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2930_agricultural_carbon_program_enrollment_credit_issuance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     37
  Calls scanned (§1.8+§1.9):  1166

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Artifacts

- `SCAFFOLD.yaml` — 166 KB; §1.0–§1.7 only (verified: contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`). 14 entities, 13 state machines, 3 concurrency rules, 10 calculations, 25 validation priority tiers, 72 endpoints, 55 errors, 4 roles. `complexity_profile`: `difficulty_level: beyond_expert`, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `complexity_layers: [dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 148 KB; single top-level key; 9 rule_ids × 2 instances (one rule carries 3) = **19 instances**.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 268 KB / 4000 lines; single top-level key; **64 instances = 37 executable + 27 `excluded_because:` stubs** across all nine guide sections: entities 6 (0 stubs), state_machines 12 (6), calculations 10 (7), validations 18 (9), endpoints 4 (0), errors 2 (0), rbac 4 (1), cross_cutting_complexity_layers 7 (4), consistency_model 1 (0).

## Coverage audit

- **Errors**: all **55** catalog ids are triggered by at least one *executable* (test_recipe-bearing) instance — verified by script over §1.8 ∪ §1.9, not by stub reference alone. The last five were closed in this session: `ERR_SUPERSEDED_BATCH_NOT_CANCELLED`, `ERR_SUPERSEDED_BATCH_MISMATCH`, `ERR_UNRESOLVED_REVERSAL`, `ERR_CLAWBACK_OUTSTANDING`, `ERR_DUPLICATE_PAYMENT`, `ERR_BUFFER_POOL_DEFICIT`, `ERR_BASELINE_ENROLLMENT_MISMATCH`, `ERR_STALE_ENROLLMENT_VERSION`, `ERR_STALE_BATCH_VERSION`, `ERR_RESOURCE_NOT_OWNED`, `ERR_UNAUTHORIZED`, `ERR_UNAUTHENTICATED`.
- **Names**: 83 unique names across both design files, zero collisions. All 27 stub `difficulty_instance:` citations normalised to `<rule_id> / <name>` and machine-verified against the §1.8 file (one wrong rule_id — `priority_interaction_matrix` → `priority_pair_validation_conflict` — was corrected).
- **claim_type vocabulary** stayed closed to the claim-extraction guide's per-section tables (30 distinct values; nothing invented).
- **Concurrency**: one executable OCC instance per §1.2.1 rule (`baseline-create-stale-enrollment`, `run-create-stale-enrollment`, `batch-cancel-stale-batch`); every `expected_*_version` payload value is a `${var}`, never a literal.

## Adjudications worth carrying forward

- The scenario directive line "Generate task harder than expert level!" was deliberately **omitted from `scenario:`** and preserved instead as `complexity_profile.difficulty_level: beyond_expert`, so the directive cannot leak into PRD.md via the scenario key.
- Every formula-derived assert literal was computed in Decimal, not estimated: mapped_acres 1480.69; qc scores 88.00/77.50/96.00; baseline clamps HISTORICAL 5.00/140.000 vs MODELED 12.00/180.000; net removals 283.360 and 226.380; issuance 283 gross / 18.00% / 51 buffer / 232 issued / serials 1–232 (and 233–464 on re-issuance); required_reserve 12 = ceil(232×0.05); payments PER_CREDIT 382800/76560/306240 and PER_ACRE 962500/192500/770000; reversal waterfall 111 affected / 51 buffer draw / 60 unbacked / **99000** clawback (the PER_CREDIT 60% share — not the 165000 full-price figure an earlier draft carried); discrepancies 5.87 / 41.16 / 5.00.
- Three reachability corrections were made rather than weakening the corner: `ERR_BUFFER_POOL_DEFICIT` is unreachable on a first issuance (buffer_pct ≥ base+8 always exceeds `min_reserve_ratio` 0.05), so it is triggered only after a reversal drains the pool to balance 0 vs required 12; `ERR_UNRESOLVED_REVERSAL` is triggered while the event is still `REPORTED` (post-assess the batch is SUSPENDED and tier 9 would win); `ERR_CLAWBACK_OUTSTANDING` needed a *second* enrollment's untouched ACCRUED payment, because assess hop 6 claws back the breached enrollment's own payments.
- A second baseline proposal on an **ACTIVE** enrollment is not a legal retry path (approve requires `ACCEPTED`), so the OCC happy-path retry uses the supersede-a-PROPOSED-row route instead.
- Scratch stayed task-scoped in `.scratch/step2/` (Decimal verification scripts); `workspace/` and `worklog.md` are intact and no sibling task directory was read.

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over all three scaffold files returns nothing — the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T19:35:51.907Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent: prd-bench-doc-generator) — 2026-09-05T19:52:29.819675408Z

PRD complete at `workspace/PRD.md` — **542 lines**, ending on a complete §5 error table (final row `ERR_UNRESOLVED_REVERSAL | 409`). Built entirely with chunked heredoc appends; the two withheld design files were never opened, and no sibling task directory was read.

**Section list**
- §1 Introduction (3 paragraphs: traceability chain, four mutually distrustful actors, the two dominating properties — arithmetic conservatism and ledger reconciliation)
- §2 Global Specifications: 2.1 RBAC (`X-User-ID`/`X-User-Role`, four roles, ownership-after-existence/before-state) · 2.2 Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Logical programme clock and crop years · 2.5 Identity/audit fields and the one immutable record type (`PracticeHistory`) · 2.6 Path resolution and reverse reachability (all 13 path params + every list filter) · 2.7 Numeric precision, rounding, units · 2.8 OCC (3 rules, `ERR_STALE_ENROLLMENT_VERSION`, `ERR_STALE_BATCH_VERSION`) · 2.9 Segregation of duties · 2.10 The 25-rung validation ladder · 2.11 Cascade discipline and compensation · 2.12 The programme buffer pool
- §3 Business Logic, 9 subsections: 3.1 grower onboarding + field mapping · 3.2 practice history + published methodologies · 3.3 enrollment, additionality screening, adjudication · 3.4 baseline (both variants) and activation · 3.5 data packets and QC · 3.6 quantification (both variants) plus commissioning and conducting verification · 3.7 credit issuance and the buffer split (pinned 6-step order) · 3.8 registry custody, reversals, permanence · 3.9 compensation, exit, termination, cooldown, ledger reconciliation read
- §4 Endpoint Definitions — 4-column table, all **72** endpoint rows
- §5 Error Code Catalogue — 2-column table, all **55** error rows

**Hard Contracts (verified by script, not by eye)**
- Contract 1 — Field-Name Coverage: **PASS**. 158 distinct identifiers (all `entities[].fields[].name`, all endpoint `input` tokens with `?` stripped, all path params) — 0 missing, each present verbatim in backticks. Two passes: an initial pass mis-reported 153 misses because the fenced ```json blocks in §2.2 flipped backtick pairing; the corrected pass strips fences first. All 55 error IDs and all state enum values also present (`EXIT_REQUESTED` appears inside transition tokens such as `ACTIVE → EXIT_REQUESTED`).
- Contract 2 — Rule Coverage: **PASS**. All 25 validation rungs with error IDs, HTTP statuses and `applies_to` scopes; all 3 concurrency rules with write endpoint, version field, error ID and 412; all 53 scaffold transitions (every from/to state token present); all 10 calculations including every one of the 9 named variants; cross-entity cascades with explicit asymmetric compensation and sibling-branch symmetry (screening fork, exit fork, opinion fork, reversal type fork).
- Contract 3 — §3 Path Purity: **PASS**. 0 backtick tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path.

**Zero-Silence adjudications** (scaffold self-conflicts resolved, all recorded as decisions in prose)
1. Quantification revise: state machine allows "optionally with the newly supplied method", endpoint `input: []`. Followed the endpoint — revise accepts no new method and recomputes against the current quality-passed packet set.
2. Verification resample: state machine clears `material_discrepancy_pct` to null, endpoint resets it to 0.00. Followed the endpoint (0.00), with `restated_removals_t` and `findings_note` cleared to null.
3. Reversal resolve: state machine has a `SUSPENDED → LISTED` edge keyed on the resolving event's own `credit_batch_id`, while the endpoint says "the reversed batch itself stays SUSPENDED". Adjudicated for the state machine — every suspended batch, including the event's own, returns to `LISTED` once `pool_status` is `HEALTHY`; the endpoint clause would make the documented `LISTED → SUSPENDED → LISTED` cycle and the `BREACHED → IN_COMPLIANCE` compensation unreachable for `INTENTIONAL` reversals, which suspend only that one batch.
4. `decide-exit` fully-served branch: state machine moves `ACCRUED` payments to `PAID`, endpoint is silent. Union kept (final settlement to `PAID`).
5. `decide-exit` under-served branch: endpoint sets `permanence_status` to `BREACHED`, state machine is silent. Union kept.
6. The issue endpoint accepts an optional `registry_account_ref` even though a batch always starts `UNLISTED`. Documented as retained on the batch without listing it; only an explicit `RegistryOfficer` listing moves the registry axis.
7. Scaffold header counts (69 endpoints / 53 errors) disagree with its own tables (72 / 55). Documented the actual table rows.

Orchestrator verification (truncation guard): `wc -l` = 542; `tail -25` ends on the last error-catalogue row, a real section boundary — not mid-sentence. Headings present: §1 §2 §3 §4 §5. No regeneration needed. Leak check for "harder than expert"/"beyond_expert"/"scaffold" in PRD.md: no hits.

## Step 6: Generate implementation (subagent: prd-bench-implementation-generator) — 2026-09-05T20:31:44.356790810Z

Implementation complete. Summary below.

## Deliverables

`workspace/implementation/`

| File | Lines |
| --- | --- |
| `start.sh` (exec, foreground, `$PORT`, guarded pip install), `requirements.txt` (`Flask>=2.0`) | — |
| `app.py` | 104 |
| `db.py` (in-memory store, logical clock, `common_fields`, idempotent `touch`) | 164 |
| `errors.py` (58-code catalogue keyed to PRD §5) | 133 |
| `middleware.py` (rungs 1/2/4) | 54 |
| `response.py` (envelope + pagination) | 77 |
| `validators.py` (rung 5) | 186 |
| `routes/`: clock 23, payments 66, standards 103, growers 127, baselines 150, fields 165, packets 171, batches 177, reversals 194, runs 260, verifications 303, enrollments 410 | 2149 |
| `services/`: payments 53, common 252, serialize 288, calc 447 | 1040 |

**3907 lines of Python**, all `py_compile` clean. Storage is process-local dicts only; the sole row written at boot is the PRD §2.12-mandated `PROGRAM_BUFFER` ledger singleton — no business entity is ever seeded.

**72 endpoints**, byte-for-byte identical set to the PRD §4 table (verified by diffing the normalised route list against the table: `ROUTES_MATCH_EXACTLY`).

## Verification performed

Two full end-to-end smoke runs against `PORT=18930 bash start.sh` (killed by specific PID afterwards; port confirmed free, no broad pkill). Scripts live at `.scratch/step6/e2e.py` and `e2e2.py`. Hand-checked figures all matched: mapped acres 3000 from a 4000×3000 box; MODEL run 0.5×2900×0.92 = 1334.000 → deduction 133.400 → net 1200.600; MEASUREMENT run 1750−562.5 = 1187.500, sampling 30−80/4 = 10.00, net 1068.750; issuance tier MEDIUM, buffer 16.00 %, `ceil(1200×0.16)` = 192, issued 1008, serials 1–1008, `next_serial_number` 1009; PER_CREDIT payment 1663200/332640/1330560; three-band PER_ACRE waterfall 2 775 000 on 2500 acres at 1200 ¢; reversal 504/192/312/514800 → pool DEFICIT → programme-wide LISTED→SUSPENDED → BREACHED → CLAWED_BACK → grower auto-suspension at 250000 ¢ (acreage aggregate correctly unchanged by suspension); exit fee 1 110 000 at a 2/4 served ratio; cooldown refusal; cancel compensation releasing buffer without rolling back the serial cursor. Envelope, 401/403/404/405/409/412/422, unknown-route and bad-JSON paths all return the error envelope.

## PRD ambiguities resolved (interpretation chosen)

1. **`POST /quantification-runs/{id}/issue` returns the QuantificationRun at HTTP 200**, not the batch at 201. §3.7 states the batch "is not returned by the issuing call… discovered through the filtered list endpoints", and §4 gives 200 for non-creation calls. This overrides `SCAFFOLD.yaml`'s `code: 201, output: CreditBatch`.
2. **Buffer-pool singleton** seeded at boot is a system ledger fixture required by §2.12, not test entity data — the only row written at startup.
3. **`errors.py` follows PRD §5 over the scaffold** where they disagreed (e.g. `ERR_ADDITIONALITY_FAILED` 422 rather than the scaffold's split codes, `ERR_PRACTICE_STANDARD_RETIRED` 409, `ERR_BASELINE_NOT_APPROVED` 422, `ERR_BUFFER_POOL_DEFICIT` 409).
4. **Musts with no error code → `ERR_INVALID_REQUEST` (400)**: `vintage_year == run.crop_year`, `affected_acres <= enrolled_acres`, `detected_crop_year >= vintage_year`, `site_visit_end >= site_visit_start`, run crop-year window, conditionally required `rejection_reason`/`flag_reason`.
5. **Rung 22 enumerates exactly seven uniqueness rules**, so `tax_id`, `field_name` and `accreditation_id` uniqueness are deliberately *not* enforced (no code exists, and enforcing would make factory collisions fatal).
6. **Payment settlement's grower/permanence preconditions are rung 9 (`ERR_INVALID_STATE_TRANSITION`)**, not rung 7 — rung 7 enumerates fields/enrollments/data packets/exit requests only; `ERR_CLAWBACK_OUTSTANDING` stays at rung 25.
7. **`supersedes_batch_id` resolution happens at the rung-20 position** (rung 6's applies-to list omits issuance), so a non-VERIFIED run with a bogus superseded id reports the state error.
8. **Reversal resolution returns *every* SUSPENDED batch — including the event's own — to LISTED when the pool is HEALTHY** (PRD §3.8 explicit; the scaffold's "the reversed batch itself stays SUSPENDED" is contradicted and loses).
9. **`outstanding_clawback_cents` is booked on every assessment**, once per event, even when no enrollment was breached — §2.11 defines it as the sum over ASSESSED/RESOLVED events.
10. **Reporting a reversal zeroes** `affected_credits`/`buffer_draw_credits`/`unbacked_credits`/`grower_clawback_cents` (PRD "remain at zero"), not null as the scaffold says.
11. **Cancel compensation is PRD-literal**: `released_total +=`, `balance_credits -=`, `contributed_total -=` buffer credits (balance may go negative), grower `lifetime_credits_issued -=` issued credits, serial cursor untouched.
12. **Timestamps**: `created_at`/`updated_at`/`paid_at`/start-visit stamps come from the logical clock (3 fractional digits; `paid_at` and `site_visit_start` keep the raw supplied instant), while `api_request_timestamp` is format-only real time. An internal `_seq` guarantees deterministic ascending list order when logical timestamps tie.
13. **`version` starts at 1 and advances at most once per row per request**, so multi-hop cascades touching the same row still increment by exactly one.
14. **The clock endpoint performs no auth at all** (§2.4/rung 1 exempt it), and list endpoints are not owner-filtered (rung 4 governs "the addressed resource").
15. Retirement re-derives both `required_reserve_credits` and `pool_status` (both are defined as derived figures in §2.12).

## Step 5: Generate unit tests (subagent: prd-bench-unit-test-generator) — 2026-09-05T21:17:15.958955484Z

Step 5 complete. Test infrastructure and suite are written at the task root.

## Files written (7,272 lines total)

`test_helpers/` (2,382 lines): `__init__.py` 1, `types.py` 241, `constants.py` 208, `api_errors.py` 142, `test_users.py` 113, `api_client.py` 308, `factories.py` 429, `assertions.py` 254, `fixtures.py` 686.

`test_suite/` (4,890 lines): `conftest.py` 25, plus 18 test modules — test_01 135, test_02 212, test_03 176, test_04 204, test_05 141, test_06 162, test_07 204, test_08 212, test_09 209, test_10 405, test_11 492, test_12 258, test_13 953, test_14 309, test_15 127, test_16 340, test_17 219, test_18 107.

## Design-index coverage: 75 tests, 100% of non-stub instances

- **Queue A (Difficulty, depth)**: 19 instances → **38 tests** (2 per instance, one per rule-pair leg), in test_01–test_09, four tests per rule file (test_02 has 6).
- **Queue B (Corner, breadth)**: 64 instances of which **27 are `excluded_because:` stubs** (the yaml itself defers them to a named queue-A instance) → **37 real instances → 37 tests**: validations 9 (test_13), entities 6 (test_10), state_machines 6 (test_11), endpoints 4 (test_14), calculations 3 (test_12), rbac 3 (test_16), cross_cutting 3 (test_17), errors 2 (test_15), consistency_model 1 (test_18).
- **SKIPPED: none.** Every non-stub instance passed the PRD-first two-condition filter. No stub instance was accidentally translated.

## Verification (all from the task root)

- `check_citations.py`: **75 tests, 0 problems** — every docstring has verbatim PRD quotes and exactly one trailing `Design:` line.
- Design-tag audit: 0 dangling tags, 0 section mismatches, 0 uncovered non-stub instances, 0 stub-covered.
- `check_names.py`: **no name problems** (no undefined names, no unused imports).
- Every `scenario.*` attribute and every `api.*` method used resolves against `fixtures.py` / `api_client.py` (77 client methods checked).
- All 27 modules import cleanly under `PYTHONPATH=.` (real exec, so bad imported symbols would surface); `python3 -m py_compile` on every file passes. `__pycache__` cleaned up afterwards.

## Path check

`ls` confirms `test_helpers/` and `test_suite/` exist at the task root, and `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation`, `sweep.sh` — **no stray copies under workspace/**. `workspace/implementation/` was never read or written; no sibling task directory was read; `worklog.md` untouched. All scratch artifacts live in `.scratch/step5/`; no sibling scratch subdir was removed. No servers started, no pkill run.

## Notable PRD-over-design resolutions (kept for Step 7 context)

Where the design index conflicted with PRD.md I followed the PRD: `ERR_INVALID_REQUEST` at **400**, `ERR_SUPERSEDED_BATCH_MISMATCH` at **422**, `ERR_BUFFER_POOL_DEFICIT` at **409**; batches are never read off the issue response (PRD §3.7 says the issuing call does not return the batch), so tests re-read via the batch listing; site-visit boundaries are supplied as calendar dates and compared with a day-granular helper because §3.6 declares dates while start-visit stamps a clock instant; the design's `exit_fee_cents is None` assertion was dropped as not PRD-derivable.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root (not under workspace/); `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/, sweep.sh. The orchestrator pre-wrote `workspace/sweep.sh` (a DONE-sentinel sweep script) for Step 7 so the sweep cannot hit the inline-quoting bug or the relaunch-on-early-return trap.

## Step 7: Run tests and iterate (long-lived fix subagent) — 2026-09-05T21:59:54.750228398Z

Clean sweep: **75/75 in all 8 rounds.**

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (43/75 → 74/75 → 75/75).

**Tests deleted:** None. No test failed the STEP 1a coverage check outright.

**Fixes applied to `test_helpers/`:** None. The helper layer was clean — the mass failure was upstream in the implementation, not in fixtures.

**Fixes applied to `test_suite/`:**
- `test_suite/test_09_compensating_invariants.py` — `test_cancellation_never_rewinds_the_serial_cursor_or_lifetime_issuance` (renamed to `test_cancellation_never_rewinds_the_serial_cursor`). Three assertions contradicted PRD §3.8 verbatim and were corrected to the PRD-mandated post-cancellation figures:
  - `contributed_total == 51` → `== 0`. PRD §3.8: "the buffer pool's `released_total` increases by the batch's `buffer_credits`, its `balance_credits` and `contributed_total` each decrease by the same quantity".
  - `lifetime_credits_issued == 232` → `== 0`. PRD §3.8: "the grower's `lifetime_credits_issued` and the enrollment's `credits_issued_total` each decrease by `issued_credits`", reinforced by §2's grower-aggregate prose ("decreased again only by a batch cancellation") and by the ledger-summary section ("cancellations having already been subtracted from it by the cancel compensation").
  - Removed the invariant `contributed_total - drawn_total - released_total == balance_credits`. This is a genuine **PRD self-contradiction**, so it fails STEP 1b unique derivability: the buffer-pool definition states "The pool's `balance_credits` is its contributions less its draws less its releases", while §3.8 decrements `contributed_total` *and* increments `released_total` for the same quantity — double-subtracting. A faithful PRD-only implementer following §3.8's explicit hop list necessarily breaks the definitional identity. Replaced with the directly-stated `released_total == 51` and `drawn_total == 0`.

**Fixes applied to `implementation/`:**
- `workspace/implementation/response.py`, `array_response()` — moved `limit`, `offset`, `total_count` and `has_more` from the top level of the response body into the `meta` object. PRD §2.3: "List responses carry four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count` and `has_more`", matching the §2.2 envelope sample. This single misplacement accounted for **31 of the 32** initial failures (every test that read any list endpoint), all reporting the same `meta.total_count must be int`.

**Key findings:**
- Zero flakiness at any point — all 32 failures were bit-identical across all 8 rounds in every sweep, so no load-induced noise had to be filtered out.
- The failure count was wildly misleading: 31 "independent" failures spread across 13 test files were one shared envelope-shape defect in a single helper function. Confirmed the triage hint's shape (many tests, one upstream cause) applies to the implementation's shared response layer just as much as to `test_helpers`.
- The implementation's cancel cascade in `routes/batches.py` was verified hop-by-hop against PRD §3.8 and matches it exactly, which is what identified the remaining failure as a test-assertion bug rather than an implementation bug.

**Final round tallies:** 75/75 passed in all 8 rounds (0 errors, 0 skipped).

`worklog.md` was not touched.

Orchestrator verification: sweep ran under the pre-written `workspace/sweep.sh` with its SWEEP_DONE sentinel; the orchestrator independently read all 8 `results.$i.json` and confirms 75/75 in every round. Step 8 is NOT skipped — Step 7 applied 1 `implementation/` fix and 1 `test_suite/` fix.

## Step 8: Finalize PRD (subagent: PRD finalizer) — 2026-09-05T22:09:10.378940902Z

Done.

## Line counts
- `PRD.md` — 542 lines; `PRD_FINALIZED.md` — 542 lines; **0.00% line delta** (both edits are in-line revisions of existing sentences; no sections, lines, or headings added). File ends at a real section boundary — the last row of the §5 error-code table.

## Changes (2)
- **§2.12 (The Programme Buffer Pool), line 194 — revise** — replaced the false definitional identity `balance_credits = contributions − draws − releases` with the impl's actual model: `balance_credits` is a *stored running counter* seeded at 0, moved only by the §3.7/§3.8 hops (issuance `+buffer_credits`, reversal draw `−buffer_draw_credits`, cancellation `−buffer_credits`), never re-derived on read; the identity that actually holds at all times is `balance_credits == contributed_total − drawn_total`. Also qualified `contributed_total` as being net of cancellation withdrawals. — `implementation/routes/runs.py:238-239`, `implementation/routes/reversals.py:117-118`, `implementation/routes/batches.py:128-130`, `implementation/services/common.py:134-141`, `implementation/db.py:147-155`.
- **§1 (Introduction), line 9 — revise** — the same false universal claim ("the buffer pool's balance always equals contributions less draws less releases") restated as "equals its running `contributed_total` less its `drawn_total`, a cancelled batch's contribution being taken out of both figures at once". — same impl sites as above.

**No edit made for the other two Step 7 items**, deliberately:
- `response.py::array_response()` pagination-in-`meta` — PRD §2.2's envelope sample and §2.3's sentence already uniquely determine this; the Step 7 change moved the *implementation* into compliance with an already-pinned PRD rule, so there is nothing to pin. Verified `object_response` and `error_response` omit the four fields, matching §2.2's "included for list endpoints" and "the `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`".
- The two corrected test figures (`contributed_total == 0`, `lifetime_credits_issued == 0`) — pure test-assertion bugs; §3.8's cancel hop list already states both decrements verbatim and `routes/batches.py:130,142-148` matches. PRD prose left verbatim.

## Per-edit pre-edit search log

**Edit 1 — §2.12 `balance_credits` / `contributed_total`**
- (a) Subject: the buffer pool's credit counters — how `balance_credits`, `contributed_total`, `drawn_total`, `released_total` are maintained, and whether any of them is derived at read time.
- (b) Paths enumerated (grepped `balance_credits|contributed_total|drawn_total|released_total|unbacked_reversal_credits|next_serial_number|outstanding_issued_credits|min_reserve_ratio|required_reserve` across all of `implementation/`, then read each hit in context): `db.py:145-156` (seeding, all counters at 0); `routes/runs.py:196-245` (issuance: `contributed_total +=`, `balance_credits +=`, solvency gate at 198-209 reading `balance_credits` prospectively); `routes/reversals.py:97-149` (assessment: `drawn_total +=`, `balance_credits -=`, `unbacked_reversal_credits +=`; intentional branch touches the pool not at all); `routes/reversals.py:152-194` (resolution — confirmed it *never* restores `balance_credits`, only registry/permanence); `routes/batches.py:74-102` (retirement — confirmed it touches only `outstanding_issued_credits`, leaving `balance_credits`/`contributed_total`/`released_total` alone, so the "buffer contribution stays in the pool permanently" prose in §3.8 remains true); `routes/batches.py:105-162` (cancellation, the three hops); `services/common.py:134-141` (`recompute_pool` — re-derives only `required_reserve_credits` and `pool_status`, **not** `balance_credits`); `services/calc.py:446-447` (`required_reserve`); `services/serialize.py:236-249` (`buffer_account` returns every counter as stored, no derivation).
- (c) Wording adjustments made to keep all of those consistent: (i) scoped the "moves only through" clause to "the hops named in §3.7 and §3.8" after confirming the grep found exactly three mutation sites, all in those two sections — this keeps retirement (which does not move `balance_credits`) and resolution (likewise) correctly excluded without naming them; (ii) chose the positive identity `balance_credits == contributed_total − drawn_total` only after algebraically checking it holds across *all three* mutation sites (issuance moves both sides by `+buffer_credits`; a draw moves both sides by `−buffer_draw_credits`; a cancel moves both sides by `−buffer_credits`), rather than the narrower "it is whatever the hops leave behind", which would have under-determined the read; (iii) added "rather than a figure re-derived on read" specifically because `services/common.py:134-141` and `services/serialize.py:239` show no derivation anywhere; (iv) kept §2.12's "five lifetime counters and three derived figures" sentence untouched, since framing `balance_credits` as a stored counter *agrees* with that count.

**Edit 2 — §1 introduction restatement of the same identity**
- (a) Subject: identical — the buffer-pool balance identity, in its Introduction summary form.
- (b) Paths enumerated: the same set as Edit 1 (re-checked `routes/runs.py:238-239`, `routes/reversals.py:117-118`, `routes/batches.py:128-130`, `services/common.py:134-141`); additionally grepped `PRD.md` for `balance_credits|released_total|contributed_total|drawn_total|less its draws|less its releases` to confirm §1 line 9 and §2.12 line 194 are the *only* two places the false identity is asserted, and that §3.7 line 352 / §3.8 lines 360, 366 state the individual hops in a form the impl already matches exactly (so they were left verbatim).
- (c) Adjustment: added the clause "a cancelled batch's contribution being taken out of both figures at once" so the Introduction does not read as contradicting §3.8's `released_total`-up/`contributed_total`-down hop; deliberately kept the Introduction's neighbouring claims (`gross = buffer + issued`, serials never reused) verbatim, both of which `routes/runs.py:211-212,243` and `routes/batches.py:126` still satisfy.

**Scope note for a Step 9 reviewer:** I found a second, structurally identical PRD self-contradiction that I did **not** touch, because it traces to no Step 7 item — §2.12 defines `outstanding_issued_credits` as "the sum of `issued_credits` over every batch whose `issuance_status` is `ISSUED`", while §3.8's retirement hop decreases it (`routes/batches.py:96-98`) without moving `issuance_status` off `ISSUED`. The implementation maintains it as a running counter, so the §2.12 definition is unreachable in practice. Left as-is per the hard scope rule.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two claimed line revisions (lines 9 and 194) — the file is NOT byte-identical to PRD.md, and it ends on the last §5 error-table row. The `outstanding_issued_credits` contradiction flagged above is handed to Step 9, which is in scope for it.

## Step 9: Complete PRD — pass 1 of 3 (infra + growers/fields/standards/clock) — 2026-09-05T22:34:44.841146094Z

Orchestrator note: Step 9 was deliberately split into three SEQUENTIAL passes partitioned by implementation module, all editing one shared `PRD_COMPLETED.md`. Pass 1 performs the `cp` from PRD_FINALIZED.md; passes 2 and 3 edit in place and are forbidden from re-copying. A single-pass Step 9 on a 3900-line implementation reliably under-scans and can leave PRD_COMPLETED.md byte-identical to its source.

Pass 1 complete.

## Confirmation
The `cp workspace/PRD_FINALIZED.md → workspace/PRD_COMPLETED.md` was performed by pass 1 as its first action.

## Deltas
- `PRD_FINALIZED.md`: 542 lines / 109,088 chars
- `PRD_COMPLETED.md`: 549 lines / 115,277 chars (**+7 lines, +6,189 chars**)
- `diff` shows 17 changed hunks (49 changed lines); file still ends at the last row of the §5 error-code table (now `| ERR_INTERNAL | 500 |`).

**Counts: 12 ambiguity-pins, 5 mismatch-revisions.**

## Changes
- §2.1 — revise — mismatch — whitespace-only identity header now counted as absent alongside the empty string — `middleware.py:22-25`
- §2.1 — insert — ambiguity — ownership binds single-resource reads/writes only; list endpoints are never narrowed to the caller (a `Grower` listing fields/practice-history sees every row) — `routes/fields.py:85-89,151-155`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + 32 lower-case hex chars — `db.py:85`
- §2.2 — insert — mismatch — `api_request_timestamp` is read from the host's real UTC clock, not the logical clock, so it does not move when the clock is repositioned — `response.py:12-14`
- §2.3 — insert — ambiguity — `limit`/`offset` bounds are enforced with `ERR_INVALID_REQUEST` (not clamped); non-integer refused; empty-string param takes the default; undeclared query params ignored — `response.py:56-74`
- §2.3 — revise — ambiguity — list ordering is by the server's monotonic creation sequence, not the `created_at` string, so rows sharing one frozen clock instant come back in write order — `response.py:80`
- §2.4 — revise — ambiguity — `current_utc` is required, endpoint accepts absent identity headers, `data` carries exactly two keys, and the instant is echoed back byte for byte as supplied — `routes/clock.py:16-23`, `db.py:46-53`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` render the logical clock at exactly millisecond width, truncating any finer fraction; `updated_at` equals `created_at` on creation — `db.py:65-66,99-107`
- §2.5 — revise — mismatch — `version` starts at **1** and advances by exactly one **per mutating request**: a row touched several times in one request (revisited cascade hop) still advances by one and refreshes `updated_at` once — `db.py:110-125`
- §2.6 — revise — ambiguity — practice-standard list also filters on the version, under either `standard_version` or the alias `version` — `routes/standards.py:14-19`
- §2.7 — insert — ambiguity — declared scale governs the value, not the rendering (`12.50` emits as `12.5`, zero as `0.0`) — `services/serialize.py:6-11`
- §2.7 — insert — ambiguity — numeric input must be a JSON number (strings/booleans/non-finite refused); over-scale refused but normalising trailing zeros tolerated; integer fields reject `3.0`/`true` — `validators.py:72-117`
- §2.10 rung 5 — insert — ambiguity — five edge conventions: absent/empty body reads as `{}`; explicit `null` == omitted; non-empty strings trimmed for the emptiness test only and stored untrimmed; undeclared body properties ignored; instants accept 0 or 1–9 fractional digits with case-insensitive `T`/`Z` and reject offsets — `validators.py:18-51,167-186`
- §3.1 — revise — mismatch — `tax_id` uniqueness across growers is **not** enforced — `routes/growers.py:31` (no uniqueness scan anywhere)
- §3.1 — revise — mismatch — `field_name` uniqueness among a grower's fields is **not** enforced — `routes/fields.py:41`
- §3.1 — revise — ambiguity — `county_code` stays null when omitted — `routes/fields.py:52,78`
- §3.2 — revise — mismatch — `acres == 0` when `adopted` is false is a convention, not a validation; `observed_emissions_per_acre` defaults to zero (never null) when omitted — `routes/fields.py:128,145`
- §3.2 — insert — ambiguity — revision requires `ACTIVE` (`ERR_INVALID_STATE_TRANSITION` otherwise), `revision_note` is exposed and null until first revision, and `ERR_DUPLICATE_STANDARD_VERSION` is not re-applied on revision — `routes/standards.py:92-103`
- §4 intro — insert — ambiguity — trailing slash tolerated on every path; routing precedes authentication, so unmatched path → `ERR_NOT_FOUND` (404) and wrong method → `ERR_METHOD_NOT_ALLOWED` (405) even without headers; unexpected fault → `ERR_INTERNAL` (500) in the error envelope — `app.py:50,64-91`
- §4 table — revise — mismatch — grower create/list descriptions said "county"; they are mailing state (`mailing_state`) — `routes/growers.py:17-20,32-34`
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 rows plus a note that these are transport codes no ladder rung produces — `errors.py:69-71`

## Deliberately left unpinned
- `services/common.py` filter-matching semantics (exact-string matching, `int` coercion errors, unknown-param skipping) and every cascade helper in it — that file belongs to pass 3; pinned only the filter **key sets** declared in pass 1's own route modules.
- `calc.mapped_acres` / `calc.rectangles_overlap` internals — already pinned exactly by §3.1 (4000 sq-units per acre, round half up 2dp, positive-area intersection with shared edges/corners allowed).
- Ledger-summary (`routes/growers.py:69-104`) — §3.9's "reconciliation read" paragraph already pins the field set, each derivation and the `VOID`-counted-nowhere rule exactly as implemented.
- JSON key ordering (`JSON_SORT_KEYS = False`) — insertion order is not an observable contract for JSON objects.
- Process-local storage / empty store on restart — an environmental property of the harness, not an API behavior.

## Step 9: Complete PRD — pass 2 of 3 (enrollments/baselines/packets/runs/calc) — 2026-09-05T22:34:44.872192479Z

Pass 2 complete. Verified all 28 marker phrases from these edits are present exactly once each in the file.

**No re-copy:** PRD_FINALIZED.md was NOT copied over PRD_COMPLETED.md. Pass 1's edits were located first by a `fold -w 100 -s` diff of the two files and left untouched; every change below was a surgical `Edit` on the existing PRD_COMPLETED.md.

**Line count:** 549 before → **551** after. File still ends at a real section boundary — last three lines are the final §5 rows `| ERR_NOT_FOUND | 404 |`, `| ERR_METHOD_NOT_ALLOWED | 405 |`, `| ERR_INTERNAL | 500 |`.

**Counts:** 22 changes total — **15 ambiguity pins**, **7 mismatch revisions**.

### Changes
- §2.6 — insert — ambiguity — added `start_crop_year` to the enrollment attribute-filter list — `routes/enrollments.py:26`
- §2.10 rung 7 — revise — mismatch — replaced "applies to all grower-scoped write endpoints" with the exact nine-endpoint enumeration, and stated the admin-only steps (request-info, screen, decide-exit, accrue-payment) are deliberately not gated — `routes/enrollments.py:75,127`, `routes/packets.py:51,136`
- §2.10 rung 14 — revise — mismatch — the two-step additionality cascade applies to submit/resubmit only; baseline proposal borrows `ERR_INSUFFICIENT_PRACTICE_HISTORY` alone — `routes/enrollments.py:61-64` vs `routes/baselines.py:46-47`
- §2.10 rung 5 — insert — ambiguity — every crop-year-valued field (`start_crop_year`, `vintage_year`, `requested_exit_year`, packet/run `crop_year`) shares the 2000–2100 range — `validators.py` `v_crop_year`
- §2.12 — insert — ambiguity — the `pool_status` HEALTHY test runs before the reserve comparison, and the prospective comparison uses post-issuance balance against post-issuance `outstanding_issued_credits` — `routes/runs.py:198-205`
- §3.3 — insert — ambiguity — enrollment creation defaults (narrative/admin/exit fields null, `accrued_payment_cents` and `credits_issued_total` at 0), plus a new paragraph pinning the body-borne `field_id` early ownership hop ahead of rung 5 and the fixed FK resolution order — `routes/enrollments.py:87-90,121-122,175-203`
- §3.3 — insert — ambiguity — `commitment_years` has no rung-5 bound; zero/negative reports `ERR_COMMITMENT_TERMS_INVALID` — `routes/enrollments.py:94,136-142`
- §3.3 — insert — ambiguity — a `start_crop_year` window breach is `ERR_INVALID_REQUEST` on rung 5, decided before body FKs resolve — `routes/enrollments.py:114-119`
- §3.3 — revise — mismatch — exclusivity order corrected: temporal overlap (rung 17) is tested first and the duplicate check (rung 22) last, with the terminal-status set enumerated — `routes/enrollments.py:148-173`
- §3.3 — insert — ambiguity — screening figures are written only on success; a refused submit leaves DRAFT figures untouched and a refused resubmit keeps `missing_items` — `routes/enrollments.py:240-246,258`
- §3.3 — insert — ambiguity — `missing_items` must be an array of non-empty strings; an empty array is accepted — `validators.py` `v_str_list`, `routes/enrollments.py:267`
- §3.4 — insert — mismatch — baseline proposal places no state precondition on the enrollment at all — `routes/baselines.py:27-35`
- §3.4 — insert — ambiguity — approval's field-transition and acreage-accumulation hops are conditional on the field being `MAPPED`, so a second live commitment does not double-count acreage — `routes/baselines.py:123-132`
- §3.5 — insert — mismatch — omitted `measured_value` is stored as `0.0000` rather than null; a new packet carries null `flag_reason` and `correction_count` 0; filing is not gated on enrollment state (only correction demands ACTIVE) — `routes/packets.py:69-76,139`
- §3.5 — insert — ambiguity — a correction supplying none of the three optional fields is still valid (rescore, increment, back to PENDING) — `routes/packets.py:145-154`
- §3.5 — insert — ambiguity — an omitted `flag_reason` on rejection leaves the earlier flagging reason standing — `routes/packets.py:167-169`
- §3.6 — insert — ambiguity — a crop_year window breach is `ERR_INVALID_REQUEST`, evaluated after both body FKs (enrollment then baseline) resolve — `routes/runs.py:63-71`
- §3.6 — revise — mismatch — figures are computed once at creation (a DRAFT run does not track later packet changes); revision may carry a fresh `method`, re-checks nothing but the run's own status, and a failed recomputation reports `ERR_NO_QUALIFYING_DATA` — `routes/runs.py:94-110,143-160`
- §3.7 — revise — mismatch — the issuance preconditions restated in ladder order (adverse opinion → enrollment ACTIVE → standard version → buffer pool last) — `routes/runs.py:175-209`
- §3.7 — insert — ambiguity — `vintage_year` mismatch is `ERR_INVALID_REQUEST` on rung 5; `supersedes_batch_id` is resolved late, after the state and version rungs; issuance does not test the predecessor's `issuance_status` — `routes/runs.py:171-192`
- §3.7 — insert — ambiguity — zero `issued_credits` still mints a batch with an empty serial range (`serial_end` one below `serial_start`) and no cursor advance; the issuing call returns the run at HTTP 200 — `routes/runs.py:211-212,243,260`
- §3.8/§3.9 — insert — ambiguity — accrue-payment's only gate is `payment_model` (else `ERR_INVALID_STATE_TRANSITION`), with no status/standing/window check, returning 201; request-exit does not clear a stale `rejection_reason`; the fully-served exit branch stamps `paid_at` and raises `net_paid_cents` while leaving `accrued_payment_cents` intact; the exit-fee served ratio is unrounded — `routes/enrollments.py:323-325,359-372,396-410`, `services/calc.py` `exit_fee_cents`

### Widened rather than reverted
- §3.8's permanence-status summary (pass-1-adjacent wording) was **widened**, not reverted, to admit the termination-driven `BREACHED` from `routes/enrollments.py:376`. Checked `routes/reversals.py:170-193` first: the reversal-resolve loop restores `IN_COMPLIANCE` when a suspended batch of the same enrollment is restored, so the new sentence says only that restoration could ever lift it rather than calling `BREACHED` permanent.

### Deliberately left unpinned
- Two defensive branches in `services/calc.py` are unreachable and were not pinned: the zero-denominator guard in `additionality` and the `enrolled == 0` guard in `qc_score`. Both are blocked upstream by rung 15's `0 < enrolled_acres <= mapped_acres`, so pinning them would document behavior no request can reach.
- Passes 1's and 3's partitions were not touched; several of their files were read/grepped as cross-reference only, to keep wording from contradicting the other passes.

## Step 9: Complete PRD — pass 3 of 3 (verifications/batches/reversals/payments/common) — 2026-09-05T22:52:28.299425732Z

Pass 3 complete. All edits were surgical in-paragraph `Edit` calls on the existing `PRD_COMPLETED.md`.

## Confirmation
Did **not** copy `PRD_FINALIZED.md` over `PRD_COMPLETED.md`. Line count **551 before → 551 after** (every change was an in-paragraph insert/revision; no new lines, no new sections). File still ends at the last row of the §5 error-code table (`| ERR_INTERNAL | 500 |`).

## Counts
- **13 ambiguity-pins**, **8 mismatch-revisions** (21 edits total)

## Changes
- §2.6 — insert — ambiguity — filter-matching semantics: exact equality with no case folding/trimming/partial match, array-membership for `practice_code`, `accredited_practice` accepted as its second name, `status` on the verification list reads the `opinion` axis, filters AND'd, empty-string filter matched literally (selects nothing) while an integer-valued filter that won't parse — empty string included — is `ERR_INVALID_REQUEST` — `services/common.py:106-128`, `routes/verifications.py:18-29`
- §2.10 rung 5 — revise — mismatch — rung 5 applies only to endpoints that read a body; the seven that never read one (enrollment submit/resubmit, body suspend/reinstate, start-visit, assess, pay) ignore even invalid JSON — `routes/verifications.py:215,121,134`, `routes/reversals.py:85`, `routes/payments.py:40`
- §2.12 — revise — mismatch — counter tally corrected to six running counters, a serial cursor and two derived figures — consequence of the next two edits
- §2.12 — revise — mismatch — `unbacked_reversal_credits` (and `drawn_total`) move on unintentional reversals only — `routes/reversals.py:115-121,132-137`
- §2.12 — revise — mismatch — **`outstanding_issued_credits` restated as a stored running counter** (see below) — `db.py:152`, `routes/runs.py:240`, `routes/batches.py:96,131`
- §3.6 — revise — mismatch — `accreditation_id` is recorded as supplied and **not** checked for uniqueness (the PRD promised uniqueness with no error code to raise) — `routes/verifications.py:84-104`
- §3.6 — insert — ambiguity — a site-visit window closing before it opens is a rung-5 `ERR_INVALID_REQUEST` — `routes/verifications.py:77`
- §3.6 — insert — ambiguity — rung-6 order on verification creation: `quantification_run_id` then `verification_body_id` — `routes/verifications.py:159-160`
- §3.6 — insert — ambiguity — start-visit writes `site_visit_start` as the raw clock instant (not §2.5 millisecond width), replacing the calendar date; the capacity rule reads only its leading `YYYY-MM-DD` — `routes/verifications.py:227,43-47`
- §3.6 — insert — ambiguity — `findings_note` refused when supplied empty/whitespace — `routes/verifications.py:240`
- §3.8 — insert — ambiguity — listing's `registry_account_ref` is required and overwrites the one retained at issuance — `routes/batches.py:54,68`
- §3.8 — revise — mismatch — retirement re-derives `pool_status` as well as `required_reserve_credits`, so it can lift the pool out of `DEFICIT` — `routes/batches.py:99`
- §3.8 — insert — ambiguity — reversal reporting: the `affected_acres` and `detected_crop_year` bounds are `ERR_INVALID_REQUEST` evaluated after the batch resolves; the `ISSUED` gate is `ERR_INVALID_STATE_TRANSITION` and reads the issuance axis only, so a retired batch is reportable — `routes/reversals.py:37-46`
- §3.8 — insert — ambiguity — assessment has only two preconditions; a since-cancelled batch is still assessable — `routes/reversals.py:90-95`
- §3.8 — insert — ambiguity — `buffer_draw_credits` floored at zero for a negative pool balance — `services/calc.py:405-407`
- §3.8 — revise — mismatch — `outstanding_clawback_cents` is booked on *every* assessment, not only ones that suspended a batch or clawed back cash — `routes/reversals.py:141-144`
- §3.8 — insert — ambiguity — threshold suspension writes a server-generated `suspension_reason`; an already-suspended grower is left alone — `services/common.py:179-184`
- §3.8 — revise — mismatch — the intentional branch touches no pool counter at all; an unlisted batch means hops 5-6 do nothing while 1 and 7 still run — `routes/reversals.py:132-137`
- §3.8 — insert — ambiguity — resolution reduces neither `outstanding_clawback_cents` nor a clawback-driven grower suspension — `routes/reversals.py:152-194`
- §3.9 — insert — ambiguity — a per-credit payment's `crop_year` is copied from the batch's `vintage_year` — `services/payments.py:41`
- §3.9 — insert — ambiguity — settlement's three rung-9 tests in order, `paid_at` written as the raw clock instant, `accrued_payment_cents` left standing — `routes/payments.py:47-63`

## The `outstanding_issued_credits` item (Step 8's flagged self-contradiction)
Impl paths that move the counter, enumerated before the wording was settled:
1. Seeded at 0 — `db.py:152`
2. **Issuance**: `+= batch.issued_credits` — `routes/runs.py:240-242`
3. **Retirement**: `-= batch.issued_credits` — `routes/batches.py:96-98`
4. **Cancellation**: `-= batch.issued_credits` — `routes/batches.py:131-133`
Read-only consumers: `services/common.py:136` (reserve/status derivation) and `routes/runs.py:201` (the prospective solvency arithmetic). Nothing else writes it, and it can never go negative because retire and cancel are mutually exclusive on one batch.

Replaced the "sum over every batch whose `issuance_status` is `ISSUED`" definition with a stored-running-counter definition naming those exact three hops, and stated explicitly *why* neither a sum over `ISSUED` batches (retirement leaves the axis at `ISSUED`) nor a sum over all minted batches (cancellation) reproduces it. The dependent §2.12 tally sentence was corrected to match.

## Deliberately left unpinned
- `routes/verifications.py:265-267` sets the run to `REJECTED` unconditionally on an `ADVERSE` opinion, so a resampled verification could reject a run already `VERIFIED` by a sibling verification. Reaching it needs two verifications on one run plus a resample; the PRD's `SUBMITTED → REJECTED` wording is close enough and pinning it would add speculative prose.
- Duplicate members in `accredited_practices` are stored as supplied (no dedup) — unobservable through any filter or gate.
- Creation-order iteration inside the cascades (`sorted_rows`) — every touched row carries the same logical-clock stamp, so order is unobservable.
- Unreachable guards: the `enrolled_acres == 0` branch in `calc.reversal_assessment`, the dangling-predecessor branch in `list_on_registry`, and the unused `event` parameter of `breach_enrollments_for_batches`.

## Interaction with passes 1 and 2
Nothing was reverted. Three edits widen sentences the earlier passes owned: the rung-5 exception (§2.10, pass 1's) names enrollment submit/resubmit from pass 2's partition, which pass 2 left unpinned; the §2.12 counter tally (pass 1's) had to follow the `outstanding_issued_credits` restatement; and the `paid_at` clause in §3.9 settlement is inherited by pass 2's exit-approval branch, which already says it "settles exactly as an explicit settlement would".

## Pipeline complete — 2026-09-05T22:52:47.7509578Z

Orchestrator final verification, all checks passing:

- **Tests**: 19 files in `test_suite/`, 75 test functions; final 8-round `--isolation per-test-server` sweep reads **75/75 in every round** (`workspace/implementation/results.{1..8}.json`), re-read directly by the orchestrator rather than trusted from a subagent report.
- **PRD chain**: `PRD.md` 542 lines / 108,333 chars → `PRD_FINALIZED.md` 542 lines / 109,088 chars (2 revisions) → `PRD_COMPLETED.md` 551 lines / 131,299 chars (56 diff hunks over PRD_FINALIZED; 40 pins/revisions across the three passes). `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md`, and both end on a real §5 error-table boundary.
- **Difficulty-directive containment**: "Generate task harder than expert level!" was forwarded only to the Step 2 scaffold subagent. `grep -in "harder than expert|beyond_expert|SCAFFOLD"` over PRD.md, PRD_FINALIZED.md and PRD_COMPLETED.md returns nothing.
- **Layout**: `test_helpers/` and `test_suite/` sit at the task root, not under `workspace/`; the only `worklog.md` on disk is the task-root one (no cwd-drift stray under `workspace/`).
- `workspace/sweep.sh` and its `SWEEP_DONE` sentinel are retained as the reproducible sweep entry point; `workspace/sweep.log` is interleaved output from 8 concurrent writers and is not a diagnostic source.
